#!/usr/bin/env python3
"""沪深普通 A 股趋势持续性（regime persistence）检验 v2-labelfix。
标签修正版：正确 open-to-open FWD 口径（原 v1 公式方向反转，见 DEV_LOG_DailyStrategyExploration.md §6）。

协议：research/protocols/a_share_trend_persistence_protocol_v1.md

研究问题
--------
沪深普通 A 股在月频上是否存在趋势持续性：过去 60 日自身收益为"上"状态的股票，
未来 5/10/20 日条件收益显著高于"下"状态；该效应在控制当日横截面动量排名后
是否仍存在（对应 TSMOM / time-series trend）。

口径
----
- 研究母池：qlib all.txt 历史在市区间（含被调出/退市，无幸存者偏差），剔除
  北交所（BJ）+ 防御性剔除指数/B 股
- 辅助交叉验证层：csi1000 历史成分（同一套 T1/T4 重跑，不作主结论）
- 数据：~/.qlib/qlib_data/cn_data_2026（后复权）
- 信号：TS_UP60（60 日收益>0 状态）、TS_STRENGTH60（60 日收益/60 日日收益波动率）、
  TS_MOM60（裸 60 日收益，正交性控制用）
- 标签：T+1 开盘成交口径 Ref($open,-1)/(Ref($close,-(h+1))-1)，h=5/10/20
- 过滤：ST/*ST/退市整理（PIT 区间逐日 asof）+ 停牌 + 涨停信号日
- 检验窗口：2022-01-01 ~ 2026-07-31，数据预热自 2020-01-01

输出（拒绝覆盖非空目录）
------------------------
output/analysis_static/a_share_trend_persistence_v1/
  ts_state_returns.csv        T1 状态条件收益（每日 + 分年度）
  ts_quantile_spread.csv      T2 五分位价差（每日 + 分年度）
  ts_orthogonality.csv        T3 控制截面动量后状态增量（每日 + 分年度）
  ts_daily_ic.csv.gz          T4 日频 IC（母池 + csi1000 辅助层）
  ts_summary.csv              汇总（母池 + 辅助层，全期 + 分年度）
  decision.json               预设判定结果
  methodology.json            口径快照
  validation_report.txt       中文报告
"""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

import qlib
from qlib.config import REG_CN
from qlib.data import D

QLIB_DIR = Path("~/.qlib/qlib_data/cn_data_2026").expanduser()
ALL_FILE = QLIB_DIR / "instruments" / "all.txt"
DATA_START = "2020-01-01"
DATA_END = "2026-07-31"
EVAL_START = "2022-01-01"
HORIZONS = [5, 10, 20]
N_QUANTILES = 5
ST_INTERVALS = Path("data/external/tushare/a_share_st_status_pit_v1/normalized/st_status_intervals.csv.gz")
LIMIT_MAIN = 0.095      # 主板 10% 涨停
LIMIT_GEM = 0.195       # 创业板/科创板 20% 涨停
EXCLUDE_PREFIXES = ("BJ",)
# 防御性剔除（当前 all.txt 无命中，规则保留）：沪指数 SH000xxx、深指数 SZ399xxx、
# 沪 B 股 SH900xxx、深 B 股 SZ200xxx
EXCLUDE_PATTERNS = [("SH", "000"), ("SZ", "399"), ("SH", "900"), ("SZ", "200")]
YEARLY_STRICT = 3       # 2022-2025 至少 3 年同向
T_CRIT = 2.0            # t 统计量阈值（近似双边 95%）
ANNUALIZATION_DAYS = 238


def qlib_to_ts(code: str) -> str:
    """SH600007 -> 600007.SH"""
    return f"{code[2:]}.{code[:2]}"


def is_gem(code: str) -> bool:
    """创业板 30xxxx（深）与科创板 688xxx（沪）为 20% 涨跌停。"""
    num = code[2:]
    return num.startswith("30") or num.startswith("688")


def build_universe() -> list[str]:
    """构建沪深普通 A 股母池 code 列表（all.txt 历史在市，含退市）。"""
    lines = [ln for ln in ALL_FILE.read_text().strip().splitlines() if ln.strip()]
    codes, excluded = [], []
    for ln in lines:
        code = ln.split()[0]
        if code.startswith(EXCLUDE_PREFIXES):
            excluded.append(code)
            continue
        ex, num = code[:2], code[2:]
        if (ex, num[:3]) in EXCLUDE_PATTERNS:
            excluded.append(code)
            continue
        codes.append(code)
    return codes, excluded


def load_market(codes: list[str], label: str) -> pd.DataFrame:
    """拉取行情 + 逐股计算三个趋势信号与未来收益标签。"""
    fields = ["$close", "$open", "$change", "$volume"]
    df = D.features(codes, fields, start_time=DATA_START, end_time=DATA_END, freq="day")
    df.columns = fields
    df = df.reset_index().set_index(["datetime", "instrument"]).sort_index()

    g = df.groupby(level="instrument")
    close = df["$close"]
    ret = g["$close"].pct_change(fill_method=None)
    df["TS_MOM60"] = close / g["$close"].shift(60) - 1
    df["TS_UP60"] = (df["TS_MOM60"] > 0).astype(float)
    df["ret"] = ret
    # groupby.transform 结果索引名可能丢失，除以到 numpy 规避 Series 对齐问题
    std60 = df.groupby(level="instrument")["ret"].transform(
        lambda s: s.rolling(60, min_periods=30).std()
    )
    df["TS_STRENGTH60"] = df["TS_MOM60"].to_numpy() / std60.to_numpy()
    df["TS_STRENGTH60"] = df["TS_STRENGTH60"].replace([np.inf, -np.inf], np.nan)
    # 标签修正（2026-08-14）：原公式 open[t+1]/close[t+h+1]-1 ≈ -r，方向反转
    # （与正确 open-to-open 收益 corr=-0.93）。正确口径：T+1 开盘入场、T+1+h 开盘出场。
    for h in HORIZONS:
        df[f"FWD_{h}_open"] = g["$open"].shift(-(h + 1)) / g["$open"].shift(-1) - 1
    df["FWD_5_close"] = g["$close"].shift(-5) / close - 1
    df = df.drop(columns=["ret"])
    return df


def build_filter_mask(df: pd.DataFrame) -> np.ndarray:
    """逐观测过滤掩码（True = 保留）：ST/停牌/涨停信号日。"""
    mask = df["$close"].notna() & df["$volume"].notna() & (df["$volume"] > 0)

    codes = df.index.get_level_values("instrument")
    gem = codes.map(is_gem)
    limit_thresh = np.where(gem, LIMIT_GEM, LIMIT_MAIN)
    mask &= ~(df["$change"] >= limit_thresh)

    st = pd.read_csv(ST_INTERVALS, compression="gzip", parse_dates=["start_date", "end_date"])
    st_active = st.loc[st["is_st"] | st["is_delist_phase"], ["ts_code", "start_date", "end_date"]]
    st_set_by_date: dict[pd.Timestamp, set[str]] = {}
    dates = df.index.get_level_values("datetime").unique()
    for d in dates:
        active = st_active[(st_active["start_date"] <= d) & (st_active["end_date"] >= d)]
        st_set_by_date[d] = set(active["ts_code"])
    ts = df.index.get_level_values("instrument").map(qlib_to_ts)
    dts = df.index.get_level_values("datetime")
    st_flag = np.array([c in st_set_by_date.get(d, set()) for d, c in zip(dts, ts)])
    mask &= ~st_flag
    return mask.to_numpy()


def daily_stats(g: pd.DataFrame, label: str) -> pd.Series:
    """单个交易日的四项检验统计。

    T1 状态条件收益、T2 vol-scaled 五分位、T3 控制截面动量后状态增量、T4 日频 IC。
    """
    out: dict[str, float] = {}
    g = g.dropna(subset=[label])
    up = g["TS_UP60"].eq(1)
    dn = g["TS_UP60"].eq(0)
    if up.sum() >= 10 and dn.sum() >= 10:
        out["t1_spread"] = g.loc[up, label].mean() - g.loc[dn, label].mean()
    else:
        out["t1_spread"] = np.nan
    out["ic"] = g["TS_UP60"].corr(g[label], method="spearman")

    s = g.dropna(subset=["TS_STRENGTH60"])
    if len(s) >= N_QUANTILES * 10:
        try:
            q = pd.qcut(s["TS_STRENGTH60"], N_QUANTILES, labels=False, duplicates="drop")
            s = s.assign(q=q)
            top = s.loc[s["q"] == s["q"].max(), label].mean()
            bot = s.loc[s["q"] == s["q"].min(), label].mean()
            out["t2_spread"] = top - bot
        except Exception:
            out["t2_spread"] = np.nan
    else:
        out["t2_spread"] = np.nan

    m = g.dropna(subset=["TS_MOM60"])
    if len(m) >= N_QUANTILES * 10:
        try:
            mq = pd.qcut(m["TS_MOM60"], N_QUANTILES, labels=False, duplicates="drop")
            m = m.assign(mq=mq)
            def _group_delta(x: pd.DataFrame) -> float:
                u, d = x["TS_UP60"].eq(1), x["TS_UP60"].eq(0)
                if u.sum() >= 5 and d.sum() >= 5:
                    return x.loc[u, label].mean() - x.loc[d, label].mean()
                return np.nan
            grp_delta = m.groupby("mq", sort=True).apply(_group_delta, include_groups=False)
            out["t3_avg"] = float(grp_delta.mean())
        except Exception:
            out["t3_avg"] = np.nan
    else:
        out["t3_avg"] = np.nan
    return pd.Series(out)


def run_daily_stats(eval_df: pd.DataFrame, label: str = "FWD_5_open") -> pd.DataFrame:
    """逐日运行 daily_stats，返回 index=datetime 的统计表。"""
    stats = eval_df.groupby(level="datetime", sort=True).apply(
        lambda g: daily_stats(g, label), include_groups=False
    )
    stats.index = pd.DatetimeIndex(stats.index)
    return stats


def annualized(x: pd.Series, h: int = 5) -> float:
    """日序列均值 → 年化（label 为 h 日收益，期数缩放）。"""
    return float(x.mean()) * (ANNUALIZATION_DAYS / h)


def t_stat(x: pd.Series) -> float:
    x = x.dropna()
    if len(x) < 30:
        return np.nan
    return float(x.mean() / (x.std(ddof=1) / np.sqrt(len(x))))


def yearly_table(stats: pd.DataFrame, cols: list[str]) -> pd.DataFrame:
    out = {}
    for c in cols:
        out[c] = stats.groupby(stats.index.year)[c].mean()
    return pd.DataFrame(out).reindex(index=range(stats.index.year.min(), stats.index.year.max() + 1))


def decide(t1_mean: float, t1_t: float, t1_yearly_pos: int, t3_mean: float, t3_t: float) -> str:
    """协议 §7 预设判定。"""
    if t1_mean > 0 and abs(t1_t) > T_CRIT and t1_yearly_pos >= YEARLY_STRICT:
        if t3_mean > 0 and abs(t3_t) > T_CRIT:
            return "supported"
        return "momentum_artifact"
    return "not_supported"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--output-dir", type=Path,
                        default=Path("output/analysis_static/a_share_trend_persistence_v2_labelfix"))
    parser.add_argument("--horizon", type=int, default=5, help="主检验未来收益窗口（5/10/20）")
    args = parser.parse_args()
    out = args.output_dir
    if out.exists() and any(out.iterdir()):
        raise FileExistsError(f"Refusing to overwrite existing experiment output: {out}")
    out.mkdir(parents=True, exist_ok=True)
    label = f"FWD_{args.horizon}_open"

    qlib.init(provider_uri=str(QLIB_DIR), region=REG_CN)

    # ---- 母池 ----
    print("[1/6] Building SH/SZ ordinary A-share universe ...", flush=True)
    codes, excluded = build_universe()
    print(f"      universe={len(codes)}, excluded={len(excluded)}", flush=True)

    print("[2/6] Loading market + signals (universe) ...", flush=True)
    mkt = load_market(codes, label)
    mask = build_filter_mask(mkt)
    print(f"      rows={len(mkt)}, instruments={mkt.index.get_level_values('instrument').nunique()}, "
          f"keep={mask.mean():.1%}", flush=True)
    eval_all = mkt.loc[pd.Timestamp(EVAL_START): pd.Timestamp(DATA_END)]
    mask_full = pd.Series(mask, index=mkt.index)
    eval_keep = eval_all.loc[mask_full.loc[eval_all.index].to_numpy()]

    # ---- 辅助层 csi1000 ----
    print("[3/6] Loading csi1000 auxiliary layer ...", flush=True)
    csi = load_market(D.instruments("csi1000"), label)  # D.instruments 返回查询对象，直接传入
    mask_csi = build_filter_mask(csi)
    csi_eval_all = csi.loc[pd.Timestamp(EVAL_START): pd.Timestamp(DATA_END)]
    csi_mask_full = pd.Series(mask_csi, index=csi.index)
    csi_eval = csi_eval_all.loc[csi_mask_full.loc[csi_eval_all.index].to_numpy()]
    print(f"      rows={len(csi_eval)}, instruments={csi_eval.index.get_level_values('instrument').nunique()}", flush=True)

    print("[4/6] Running daily stats (universe + csi1000) ...", flush=True)
    stats = run_daily_stats(eval_keep, label)
    stats_csi = run_daily_stats(csi_eval, label)
    print(f"      universe days={len(stats)}, csi1000 days={len(stats_csi)}", flush=True)

    # ---- 汇总 ----
    print("[5/6] Summarizing ...", flush=True)
    yearly_u = yearly_table(stats, ["t1_spread", "ic", "t2_spread", "t3_avg"])
    yearly_c = yearly_table(stats_csi, ["t1_spread", "ic"])
    yearly_u.to_csv(out / "ts_summary_yearly.csv")
    yearly_c.to_csv(out / "ts_summary_yearly_csi1000.csv")

    t1_mean, t1_t = annualized(stats["t1_spread"], args.horizon), t_stat(stats["t1_spread"])
    t2_mean, t2_t = annualized(stats["t2_spread"], args.horizon), t_stat(stats["t2_spread"])
    t3_mean, t3_t = annualized(stats["t3_avg"], args.horizon), t_stat(stats["t3_avg"])
    ic_mean, icir = stats["ic"].mean(), stats["ic"].mean() / (stats["ic"].std() + 1e-12)
    pos2225 = int((yearly_u.loc[range(2022, 2026), "t1_spread"] > 0).sum())
    decision = decide(t1_mean, t1_t, pos2225, t3_mean, t3_t)

    t1_c_mean, t1_c_t = annualized(stats_csi["t1_spread"], args.horizon), t_stat(stats_csi["t1_spread"])
    ic_c_mean, icir_c = stats_csi["ic"].mean(), stats_csi["ic"].mean() / (stats_csi["ic"].std() + 1e-12)

    summary = {
        "universe": {
            "t1_annualized_spread": t1_mean, "t1_tstat": t1_t, "t1_years_pos_2022_2025": pos2225,
            "t2_annualized_spread": t2_mean, "t2_tstat": t2_t,
            "t3_annualized_avg": t3_mean, "t3_tstat": t3_t,
            "ic_mean": ic_mean, "icir": icir, "ic_pos_ratio": (stats["ic"] > 0).mean(),
            "days": len(stats),
        },
        "csi1000_aux": {
            "t1_annualized_spread": t1_c_mean, "t1_tstat": t1_c_t,
            "ic_mean": ic_c_mean, "icir": icir_c,
            "days": len(stats_csi),
        },
        "decision": decision,
        "horizon": args.horizon,
    }
    (out / "ts_summary.csv").write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    stats.reset_index().to_csv(out / "ts_state_returns.csv", index=False)
    stats_csi.reset_index().to_csv(out / "ts_state_returns_csi1000.csv", index=False)
    stats[["t2_spread"]].dropna().to_csv(out / "ts_quantile_spread.csv")
    stats[["t3_avg"]].dropna().to_csv(out / "ts_orthogonality.csv")
    stats[["ic"]].dropna().to_csv(out / "ts_daily_ic.csv.gz", compression="gzip")
    stats_csi[["ic"]].dropna().to_csv(out / "ts_daily_ic_csi1000.csv.gz", compression="gzip")

    # ---- 报告 ----
    print("[6/6] Writing report ...", flush=True)
    lines = []
    lines.append(f"# 沪深普通 A 股趋势持续性检验报告 v1\n")
    lines.append(f"- 母池: 沪深普通 A 股 {len(codes)} 只（all.txt 历史在市，含退市；剔除北交所 {len(excluded)} 只）")
    lines.append(f"- 辅助层: csi1000 历史成分（仅 T1/T4 重跑，不作主结论）")
    lines.append(f"- 数据: {QLIB_DIR}（后复权）")
    lines.append(f"- 窗口: {EVAL_START} ~ {DATA_END}（预热自 {DATA_START}），过滤保留率 {mask.mean():.1%}")
    lines.append(f"- 主 label: T+1 开盘成交，h={args.horizon}；年化 = 日均价差 × {ANNUALIZATION_DAYS}/{args.horizon}")
    lines.append(f"- 判定阈值: t > {T_CRIT}，2022-2025 同向 ≥ {YEARLY_STRICT} 年\n")

    lines.append(f"## 判定：**{decision}**\n")

    lines.append("### 母池汇总（h=5 主表请读 ts_summary.csv；此处 h={})".format(args.horizon))
    lines.append("| 统计 | 值 |")
    lines.append("|---|---|")
    lines.append(f"| T1 状态价差（年化） | {t1_mean:+.3f} (t={t1_t:.2f}) |")
    lines.append(f"| T1 2022-2025 同向年数 | {pos2225}/4 |")
    lines.append(f"| T2 vol-scaled 五分位价差（年化） | {t2_mean:+.3f} (t={t2_t:.2f}) |")
    lines.append(f"| T3 控制截面动量后状态增量（年化） | {t3_mean:+.3f} (t={t3_t:.2f}) |")
    lines.append(f"| T4 日频 IC / ICIR | {ic_mean:+.4f} / {icir:.2f} |")

    lines.append("\n### 分年度 T1 状态价差（母池）")
    lines.append("| 年份 | T1 价差 | IC |")
    lines.append("|---|---|---|")
    for y, row in yearly_u.iterrows():
        if pd.isna(row["t1_spread"]):
            continue
        lines.append(f"| {y} | {row['t1_spread'] * (ANNUALIZATION_DAYS / args.horizon):+.4f} | {row['ic']:+.4f} |")

    lines.append("\n### csi1000 辅助层")
    lines.append("| 统计 | 值 |")
    lines.append("|---|---|")
    lines.append(f"| T1 状态价差（年化） | {t1_c_mean:+.3f} (t={t1_c_t:.2f}) |")
    lines.append(f"| T4 日频 IC / ICIR | {ic_c_mean:+.4f} / {icir_c:.2f} |")

    lines.append("\n### 解读对照")
    lines.append("| 判定 | 含义 |")
    lines.append("|---|---|")
    lines.append("| supported | T1 显著 + 2022-2025 至少 3 年同向 + T3 控制截面动量后仍显著 → 候选为价值质量策略的趋势确认层（不单飞） |")
    lines.append("| momentum_artifact | T1 显著但 T3 不显著 → 纯截面动量换皮，价量线收口 |")
    lines.append("| not_supported | T1 不显著或不够稳定 → 主升浪全部变体测完，价量线收口 |")
    (out / "validation_report.txt").write_text("\n".join(lines), encoding="utf-8")

    meta = {
        "purpose": "沪深普通 A 股趋势持续性检验：主升浪直觉的时序结构假设",
        "protocol": "research/protocols/a_share_trend_persistence_protocol_v1.md",
        "universe": f"沪深普通 A 股 {len(codes)} 只（剔除 BJ {len(excluded)} 只）",
        "auxiliary": "csi1000 历史成分（T1/T4）",
        "data_dir": str(QLIB_DIR),
        "eval_window": [EVAL_START, DATA_END],
        "data_warmup_from": DATA_START,
        "horizon": args.horizon,
        "label": f"Ref($open,-1)/(Ref($close,-{args.horizon + 1}))-1",
        "signals": ["TS_UP60", "TS_STRENGTH60", "TS_MOM60"],
        "filters": "ST/*ST/退市整理(PIT) + 停牌 + 涨停信号日",
        "thresholds": {"t_crit": T_CRIT, "yearly_strict": YEARLY_STRICT, "n_quantiles": N_QUANTILES},
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
    }
    (out / "methodology.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"      report -> {out / 'validation_report.txt'}", flush=True)
    print(f"      decision = {decision}", flush=True)
    print("DONE", flush=True)


if __name__ == "__main__":
    main()
