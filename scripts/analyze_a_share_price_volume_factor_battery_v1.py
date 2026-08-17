#!/usr/bin/env python3
"""非 Alpha158 价量因子电池检验 v1。

协议：research/protocols/a_share_price_volume_factor_battery_v1.md

研究问题
--------
Alpha158 2021 后单因子 alpha 衰减严重（DEV_LOG §3/§10/§12.6）。但 Alpha158 结构上
吃不到五类信息：时间分解（隔夜/日内）、换手率、滚动 VWAP 偏离、市场相对强度、
收益高阶矩。本电池检验这五类共 7 个因子在当前 regime（2022-2026）下是否仍有
未被定价的横截面选股能力，并逐一对 Alpha158 最近语义因子做冗余判定。

口径
----
- 主池：沪深普通 A 股母池（all.txt 历史在市，剔除 BJ/指数/B 股，无幸存者偏差）
- 辅助层：csi1000 历史成分（同一套 R1/R4 重跑，不作主结论）
- 数据：~/.qlib/qlib_data/cn_data_2026（后复权）+ daily_basic_pit_v1（自由流通
  换手率，2016-2026）+ sh000852 指数（市场相对基准）
- 因子：7 个（全部 pandas 逐股计算，规避 qlib 表达式语义坑）
- 对照：Alpha158 最近语义 6 个（OPEN0/KMID/VWAP0/VMA20/ROC20/STD20/STD60）
- 标签：T+1 开盘成交 Ref($open,-1)/Ref($close,-6)-1（h=5 主，h=10/20 附录）
- 过滤：ST/*ST/退市整理（PIT）+ 停牌 + 涨停信号日
- 检验窗口：2022-01-01 ~ 2026-07-31（预热自 2020-01-01）

输出（拒绝覆盖非空目录）
------------------------
output/analysis_static/a_share_price_volume_factor_battery_v1/
  battery_daily_ic.csv.gz        R1 每因子每日 RankIC（long 格式，h=5）
  battery_ic_summary.csv         全期 IC/ICIR/IC>0/2026 IC/2022-2025 同向年数
  battery_ic_yearly.csv          分年度 IC（h=5）
  battery_qspread.csv            每因子每日 Q5-Q1 价差（h=5）
  battery_quantile_means.csv     五分位均值（全期，h=5）
  battery_redundancy.csv         候选×对照 逐日相关（含中位数/均值）
  battery_ic_h10_h20.csv         附录：h=10/20 全期 IC/ICIR
  decision.json                  预设判定（每因子）
  methodology.json               口径快照
  validation_report.txt          中文报告
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
from qlib.contrib.data.loader import Alpha158DL
from qlib.data import D

QLIB_DIR = Path("~/.qlib/qlib_data/cn_data_2026").expanduser()
ALL_FILE = QLIB_DIR / "instruments" / "all.txt"
DATA_START = "2020-01-01"
DATA_END = "2026-07-31"
EVAL_START = "2022-01-01"
HORIZONS = [5, 10, 20]
N_QUANTILES = 5
ANNUALIZATION_DAYS = 238

ST_INTERVALS = Path("data/external/tushare/a_share_st_status_pit_v1/normalized/st_status_intervals.csv.gz")
DAILY_BASIC = Path("data/external/tushare/a_share_daily_basic_pit_v1/normalized/daily_basic.csv.gz")
LIMIT_MAIN = 0.095      # 主板 10% 涨停
LIMIT_GEM = 0.195       # 创业板/科创板 20% 涨停
EXCLUDE_PREFIXES = ("BJ",)
EXCLUDE_PATTERNS = [("SH", "000"), ("SZ", "399"), ("SH", "900"), ("SZ", "200")]

ICIR_ALIVE = 0.3        # ICIR 存活门槛（metrics_judgment_standard：0.3 = 中）
ICIR_WEAK = 0.2
YEARLY_STRICT = 3       # 2022-2025 至少 3 年同向
CORR_NEAR = 0.70
CORR_DUP = 0.95

INDEX_BENCH = "sh000852"        # 中证 1000（主线相对基准）

# ---- 因子电池（7 个，全部 pandas 逐股计算） ----
FACTOR_NAMES = [
    "OVN_INT5",          # 隔夜收益 5 日均值
    "INTRADAY_INT5",     # 日内收益 5 日均值
    "TURNOVER_LEVEL5",   # 自由流通换手率 5 日均值
    "TURNOVER_CHG",      # 换手率相对 20 日均值偏离
    "VWAP_DEV5",         # close 相对 5 日 VWAP 均值偏离
    "REL_STRENGTH20",    # 个股 20 日收益 − 中证1000 20 日收益
    "SKEW60",            # 60 日日收益偏度
]

# ---- Alpha158 对照（最近语义） ----
CONTROL_MAP = {
    "OPEN0": ("$open/$close", "OVN_INT5"),
    "KMID": ("($close-$open)/$open", "INTRADAY_INT5"),
    "VWAP0": ("$vwap/$close", "VWAP_DEV5"),
    "VMA20": ("Mean($volume, 20)/($volume+1e-12)", None),   # 换手族对照
    "ROC20": ("Ref($close, 20)/$close", "REL_STRENGTH20"),
    "STD20": ("Std($close, 20)/$close", "SKEW60"),
    "STD60": ("Std($close, 60)/$close", "SKEW60"),
}

# 每候选因子的对照（协议 §6 表）
CANDIDATE_CONTROLS = {
    "OVN_INT5": ["OPEN0"],
    "INTRADAY_INT5": ["KMID"],
    "TURNOVER_LEVEL5": ["VMA20"],
    "TURNOVER_CHG": ["VMA20"],
    "VWAP_DEV5": ["VWAP0"],
    "REL_STRENGTH20": ["ROC20"],
    "SKEW60": ["STD20", "STD60"],
}


def qlib_to_ts(code: str) -> str:
    """SH600007 -> 600007.SH"""
    return f"{code[2:]}.{code[:2]}"


def ts_to_qlib(ts: str) -> str:
    """000001.SZ -> SZ000001（qlib instrument 大写前缀格式）"""
    return f"{ts[-2:].upper()}{ts[:6]}"


def is_gem(code: str) -> bool:
    num = code[2:]
    return num.startswith("30") or num.startswith("688")


def build_universe() -> list[str]:
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


def load_turnover() -> pd.Series:
    """自由流通换手率 turnover_rate_f（ts_code × trade_date -> 值）。"""
    db = pd.read_csv(DAILY_BASIC, compression="gzip", usecols=["ts_code", "trade_date", "turnover_rate_f"])
    db["trade_date"] = pd.to_datetime(db["trade_date"].astype(str), format="%Y%m%d")
    db["code"] = db["ts_code"].map(ts_to_qlib)
    return db.set_index(["code", "trade_date"])["turnover_rate_f"]


def load_index_ret20() -> pd.Series:
    """基准指数 20 日收益（datetime -> 值，close/Ref(close,20)-1）。"""
    idx = D.features([INDEX_BENCH], ["$close"], start_time=DATA_START, end_time=DATA_END, freq="day")
    idx = idx.reset_index().set_index("datetime")["$close"]
    ret20 = idx / idx.shift(20) - 1
    return ret20


def load_market(codes: list[str]) -> pd.DataFrame:
    """拉取原始字段 + 对照因子表达式 + 逐股 pandas 计算 7 个因子 + 标签。"""
    raw = ["$close", "$open", "$volume", "$vwap", "$change"]
    control_fields = [expr for expr, _ in CONTROL_MAP.values()]
    labels = {f"FWD_{h}_open": f"Ref($open,-1)/(Ref($close,-{h+1})+1e-8)-1" for h in HORIZONS}

    fields = raw + control_fields + list(labels.values())
    names = ["close", "open", "volume", "vwap", "change"] + list(CONTROL_MAP.keys()) + list(labels.keys())
    df = D.features(codes, fields, start_time=DATA_START, end_time=DATA_END, freq="day")
    df.columns = names
    df = df.reset_index().set_index(["datetime", "instrument"]).sort_index()

    g = df.groupby(level="instrument")
    close, open_, volume, vwap = df["close"], df["open"], df["volume"], df["vwap"]

    # ---- 因子计算（全部逐股 pandas，规避 qlib 表达式语义坑） ----
    def roll_series(s: pd.Series, w: int, fn: str) -> pd.Series:
        """对 Series 按 instrument 分组滚动聚合，返回与 df.index 对齐的 Series。"""
        out = s.groupby(level="instrument").transform(lambda x: getattr(x.rolling(w, min_periods=w // 2), fn)())
        return pd.Series(out.to_numpy(), index=df.index)

    overnight = open_ / g["close"].shift(1) - 1
    intraday = close / open_ - 1
    df["OVN_INT5"] = roll_series(overnight, 5, "mean")
    df["INTRADAY_INT5"] = roll_series(intraday, 5, "mean")
    df["VWAP_DEV5"] = close / roll_series(vwap, 5, "mean") - 1

    turnover = load_turnover()
    # 对齐 df.index（datetime, instrument）：level 顺序必须一致，reindex 按 tuple 匹配
    tr = turnover.reset_index()
    tr = tr.set_index(["trade_date", "code"])["turnover_rate_f"]
    tr = tr.reindex(df.index)
    tr_mean5 = roll_series(tr, 5, "mean")
    tr_mean20 = roll_series(tr, 20, "mean")
    df["TURNOVER_LEVEL5"] = tr_mean5
    df["TURNOVER_CHG"] = (tr.to_numpy() / tr_mean20.to_numpy() - 1)

    ret = g["close"].pct_change(fill_method=None)
    df["SKEW60"] = roll_series(ret, 60, "skew")

    # ---- 市场相对强度 ----
    index_ret20 = load_index_ret20()
    mom20 = close / g["close"].shift(20) - 1
    dts = df.index.get_level_values("datetime")
    bench = pd.Series(index_ret20.reindex(dts).to_numpy(), index=df.index)
    df["REL_STRENGTH20"] = mom20 - bench

    return df


def build_filter_mask(df: pd.DataFrame) -> np.ndarray:
    mask = df["close"].notna() & df["volume"].notna() & (df["volume"] > 0)

    codes = df.index.get_level_values("instrument")
    gem = codes.map(is_gem)
    limit_thresh = np.where(gem, LIMIT_GEM, LIMIT_MAIN)
    mask &= ~(df["change"] >= limit_thresh)

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


def daily_ic_and_spread(g: pd.DataFrame, label: str, factors: list[str]) -> dict:
    """单日：每因子 RankIC + Q5-Q1 价差。"""
    out: dict[str, float] = {}
    g = g.dropna(subset=[label])
    if len(g) < N_QUANTILES * 10:
        return out
    for f in factors:
        s = g[[f, label]].dropna()
        if len(s) < 30:
            out[f"ic_{f}"] = np.nan
            out[f"qs_{f}"] = np.nan
            continue
        out[f"ic_{f}"] = s[f].corr(s[label], method="spearman")
        try:
            q = pd.qcut(s[f], N_QUANTILES, labels=False, duplicates="drop")
            tmp = s.assign(q=q)
            top = tmp.loc[tmp["q"] == tmp["q"].max(), label].mean()
            bot = tmp.loc[tmp["q"] == tmp["q"].min(), label].mean()
            out[f"qs_{f}"] = top - bot
        except Exception:
            out[f"qs_{f}"] = np.nan
    return out


def daily_correlations(g: pd.DataFrame, factors: list[str], controls: list[str]) -> pd.Series:
    """单日：候选 × 对照 横截面 Spearman（只算跨组对）。"""
    cols = [c for c in factors + controls if c in g.columns]
    if len(cols) < 2:
        return pd.Series(dtype=float)
    m = g[cols].corr(method="spearman")
    rows = {}
    for f in factors:
        for c in controls:
            if c in m.columns:
                rows[f"corr_{f}__{c}"] = m.loc[f, c]
    return pd.Series(rows)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--output-dir", type=Path,
                        default=Path("output/analysis_static/a_share_price_volume_factor_battery_v1"))
    args = parser.parse_args()
    out = args.output_dir
    if out.exists() and any(out.iterdir()):
        raise FileExistsError(f"Refusing to overwrite existing experiment output: {out}")
    out.mkdir(parents=True, exist_ok=True)

    qlib.init(provider_uri=str(QLIB_DIR), region=REG_CN)

    factors = FACTOR_NAMES
    controls = list(CONTROL_MAP.keys())
    label5 = "FWD_5_open"

    # ---- 主池 ----
    print("[1/6] Building SH/SZ ordinary A-share universe ...", flush=True)
    codes, excluded = build_universe()
    print(f"      universe={len(codes)}, excluded={len(excluded)}", flush=True)

    print("[2/6] Loading market + factors (universe) ...", flush=True)
    mkt = load_market(codes)
    mask = build_filter_mask(mkt)
    print(f"      rows={len(mkt)}, instruments={mkt.index.get_level_values('instrument').nunique()}, "
          f"keep={mask.mean():.1%}", flush=True)
    eval_all = mkt.loc[pd.Timestamp(EVAL_START): pd.Timestamp(DATA_END)]
    mask_full = pd.Series(mask, index=mkt.index)
    eval_keep = eval_all.loc[mask_full.loc[eval_all.index].to_numpy()]

    # ---- 辅助层 csi1000 ----
    print("[3/6] Loading csi1000 auxiliary layer ...", flush=True)
    csi = load_market(D.instruments("csi1000"))
    mask_csi = build_filter_mask(csi)
    csi_eval_all = csi.loc[pd.Timestamp(EVAL_START): pd.Timestamp(DATA_END)]
    csi_mask_full = pd.Series(mask_csi, index=csi.index)
    csi_eval = csi_eval_all.loc[csi_mask_full.loc[csi_eval_all.index].to_numpy()]
    print(f"      rows={len(csi_eval)}, instruments={csi_eval.index.get_level_values('instrument').nunique()}", flush=True)

    # ---- 逐日统计 ----
    print("[4/6] Running daily stats (universe + csi1000) ...", flush=True)
    ic_rows, qs_rows, corr_rows = [], [], []
    for d, g in eval_keep.groupby(level="datetime", sort=True):
        stats = daily_ic_and_spread(g, label5, factors)
        for f in factors:
            if f"ic_{f}" in stats:
                ic_rows.append((d, f, stats[f"ic_{f}"]))
                qs_rows.append((d, f, stats[f"qs_{f}"]))
        corr_rows.append((d, daily_correlations(g, factors, controls)))
    ic_df = pd.DataFrame(ic_rows, columns=["datetime", "factor", "ic"])
    qs_df = pd.DataFrame(qs_rows, columns=["datetime", "factor", "q5q1"])
    corr_df = pd.DataFrame(corr_rows, columns=["datetime", "corrs"])
    corr_full = pd.concat([corr_df["datetime"], corr_df["corrs"].apply(pd.Series)], axis=1)

    ic_csi, qs_csi = [], []
    for d, g in csi_eval.groupby(level="datetime", sort=True):
        stats = daily_ic_and_spread(g, label5, factors)
        for f in factors:
            if f"ic_{f}" in stats:
                ic_csi.append((d, f, stats[f"ic_{f}"]))
                qs_csi.append((d, f, stats[f"qs_{f}"]))
    ic_csi_df = pd.DataFrame(ic_csi, columns=["datetime", "factor", "ic"])

    # ---- 汇总 ----
    print("[5/6] Summarizing ...", flush=True)
    summary_rows = []
    for f in factors:
        s = ic_df[ic_df["factor"] == f].set_index("datetime")["ic"].dropna()
        yearly = s.groupby(s.index.year).mean()
        pos_2225 = int((yearly.loc[[y for y in range(2022, 2026) if y in yearly.index]] > 0).sum())
        corr_cols = [c for c in corr_full.columns if c.startswith(f"corr_{f}__")]
        corr_vals = corr_full[corr_cols]
        med_corrs = corr_vals.median().abs() if len(corr_cols) else pd.Series(dtype=float)
        max_med = float(med_corrs.max()) if len(med_corrs) else np.nan
        max_med_name = med_corrs.idxmax().replace(f"corr_{f}__", "") if len(med_corrs) else ""
        qs = qs_df[qs_df["factor"] == f]["q5q1"].dropna()
        qs_ann = qs.mean() * (ANNUALIZATION_DAYS / 5)
        s_csi = ic_csi_df[ic_csi_df["factor"] == f].set_index("datetime")["ic"].dropna()
        summary_rows.append({
            "factor": f,
            "ic_mean": s.mean(), "icir": s.mean() / (s.std() + 1e-12),
            "ic_pos_ratio": (s > 0).mean(), "days": len(s),
            "yearly_same_sign_2022_2025": pos_2225,
            "ic_2026": yearly.get(2026, np.nan),
            "q5q1_annualized": qs_ann,
            "max_med_abs_corr": max_med, "max_corr_control": max_med_name,
            "csi1000_ic_mean": s_csi.mean(), "csi1000_icir": s_csi.mean() / (s_csi.std() + 1e-12),
        })
    summary = pd.DataFrame(summary_rows)

    yearly_all = ic_df.pivot_table(index=ic_df["datetime"].dt.year, columns="factor", values="ic", aggfunc="mean")
    quantile_means = {}
    for f in factors:
        tmp = eval_keep[[f, label5]].dropna()
        try:
            tmp = tmp.assign(q=pd.qcut(tmp[f], N_QUANTILES, labels=False, duplicates="drop"))
            quantile_means[f] = tmp.groupby("q")[label5].mean()
        except Exception:
            quantile_means[f] = np.nan
    qm_df = pd.DataFrame(quantile_means)

    # 附录：h=10/20 全期 IC/ICIR
    h_extra = {}
    for h in [10, 20]:
        lab = f"FWD_{h}_open"
        rows = []
        for d, g in eval_keep.groupby(level="datetime", sort=True):
            stats = daily_ic_and_spread(g, lab, factors)
            for f in factors:
                if f"ic_{f}" in stats:
                    rows.append((d, f, stats[f"ic_{f}"]))
        tmp = pd.DataFrame(rows, columns=["datetime", "factor", "ic"])
        h_extra[h] = tmp.groupby("factor")["ic"].agg(["mean", "std"])

    # ---- 判定 ----
    decisions = {}
    for _, r in summary.iterrows():
        f = r["factor"]
        if (r["icir"] >= ICIR_ALIVE and r["yearly_same_sign_2022_2025"] >= YEARLY_STRICT
                and r["max_med_abs_corr"] < CORR_NEAR):
            decisions[f] = "alive"
        elif r["icir"] >= ICIR_WEAK and r["yearly_same_sign_2022_2025"] >= 2 and r["max_med_abs_corr"] < CORR_NEAR:
            decisions[f] = "weak"
        else:
            decisions[f] = "dead"

    # ---- 写产物 ----
    ic_df.to_csv(out / "battery_daily_ic.csv.gz", index=False, compression="gzip")
    qs_df.to_csv(out / "battery_qspread.csv", index=False)
    corr_full.to_csv(out / "battery_redundancy.csv", index=False)
    summary.to_csv(out / "battery_ic_summary.csv", index=False)
    yearly_all.to_csv(out / "battery_ic_yearly.csv")
    qm_df.to_csv(out / "battery_quantile_means.csv")
    pd.DataFrame({h: h_extra[h]["mean"] for h in [10, 20]}).to_csv(out / "battery_ic_h10_h20.csv")
    (out / "decision.json").write_text(json.dumps(decisions, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    # ---- 报告 ----
    print("[6/6] Writing report ...", flush=True)
    lines = []
    lines.append(f"# 非 Alpha158 价量因子电池检验报告 v1\n")
    lines.append(f"- 主池: 沪深普通 A 股 {len(codes)} 只（all.txt 历史在市；剔除 BJ/指数/B 股 {len(excluded)} 只）")
    lines.append(f"- 辅助层: csi1000 历史成分（仅 RankIC 重跑，不作主结论）")
    lines.append(f"- 数据: {QLIB_DIR}（后复权）+ daily_basic_pit_v1（换手率）+ {INDEX_BENCH}（市场基准）")
    lines.append(f"- 窗口: {EVAL_START} ~ {DATA_END}（预热自 {DATA_START}），过滤保留率 {mask.mean():.1%}")
    lines.append(f"- 主 label: T+1 开盘成交，h=5；年化 = 日均 × {ANNUALIZATION_DAYS}/5")
    lines.append(f"- 判定: alive = ICIR≥{ICIR_ALIVE} & 2022-2025 同向≥{YEARLY_STRICT} & 全部对照|corr|<{CORR_NEAR}；"
                 f"weak = ICIR≥{ICIR_WEAK} & 同向≥2 & distinct；否则 dead\n")

    lines.append("### 汇总（h=5，母池）")
    lines.append("| 因子 | IC | ICIR | IC>0 | 22-25同向 | 2026 IC | Q5-Q1年化 | 最大对照|corr| | 对照 | csi1000 IC/ICIR | 判定 |")
    lines.append("|---|---|---|---|---|---|---|---|---|---|---|")
    for _, r in summary.iterrows():
        lines.append(
            f"| {r['factor']} | {r['ic_mean']:+.4f} | {r['icir']:.2f} | {r['ic_pos_ratio']:.0%} | "
            f"{r['yearly_same_sign_2022_2025']}/4 | {r['ic_2026']:+.4f} | {r['q5q1_annualized']:+.4f} | "
            f"{r['max_med_abs_corr']:.2f} | {r['max_corr_control']} | "
            f"{r['csi1000_ic_mean']:+.4f}/{r['csi1000_icir']:.2f} | {decisions[r['factor']]} |"
        )

    lines.append("\n### 分年度 IC（h=5，母池）")
    lines.append("| 因子 | 2022 | 2023 | 2024 | 2025 | 2026 |")
    lines.append("|---|---|---|---|---|---|")
    for f in factors:
        yr = yearly_all[f]
        lines.append(f"| {f} | " + " | ".join(f"{yr.get(y, np.nan):+.4f}" for y in range(2022, 2027)) + " |")

    lines.append("\n### 五分位均值（h=5，全期；Q1=最低因子值，Q5=最高）")
    lines.append("| 因子 | Q1 | Q2 | Q3 | Q4 | Q5 |")
    lines.append("|---|---|---|---|---|---|")
    for f in factors:
        vals = qm_df[f]
        lines.append(f"| {f} | " + " | ".join(f"{v:+.5f}" for v in vals) + " |")

    lines.append("\n### 冗余判定（候选 × Alpha158 对照，逐日横截面 Spearman 中位数）")
    lines.append("| 候选 | 对照 | 中位数 corr | 判定 |")
    lines.append("|---|---|---|---|")
    for f in factors:
        for c in CANDIDATE_CONTROLS[f]:
            col = f"corr_{f}__{c}"
            if col in corr_full.columns:
                med = corr_full[col].median()
                tag = "duplicate" if abs(med) >= CORR_DUP else ("near" if abs(med) >= CORR_NEAR else "distinct")
                lines.append(f"| {f} | {c} | {med:+.2f} | {tag} |")

    lines.append("\n### 附录：h=10/20 全期 IC/ICIR（母池）")
    lines.append("| 因子 | h=10 IC | h=10 ICIR | h=20 IC | h=20 ICIR |")
    lines.append("|---|---|---|---|---|")
    for f in factors:
        r10 = h_extra[10].loc[f]
        r20 = h_extra[20].loc[f]
        lines.append(f"| {f} | {r10['mean']:+.4f} | {r10['mean']/(r10['std']+1e-12):.2f} | "
                     f"{r20['mean']:+.4f} | {r20['mean']/(r20['std']+1e-12):.2f} |")

    (out / "validation_report.txt").write_text("\n".join(lines), encoding="utf-8")

    meta = {
        "purpose": "检验 Alpha158 之外五类量价信息（时间分解/换手/VWAP偏离/市场相对/高阶矩）的横截面选股能力",
        "protocol": "research/protocols/a_share_price_volume_factor_battery_protocol_v1.md",
        "universe": f"沪深普通 A 股 {len(codes)} 只（剔除 {len(excluded)} 只）",
        "auxiliary": "csi1000 历史成分（RankIC）",
        "data_dir": str(QLIB_DIR),
        "eval_window": [EVAL_START, DATA_END],
        "data_warmup_from": DATA_START,
        "horizon": 5,
        "label": "Ref($open,-1)/(Ref($close,-6))-1",
        "factors": FACTOR_NAMES,
        "controls": controls,
        "filters": "ST/*ST/退市整理(PIT) + 停牌 + 涨停信号日",
        "thresholds": {"icir_alive": ICIR_ALIVE, "icir_weak": ICIR_WEAK,
                       "yearly_strict": YEARLY_STRICT, "corr_near": CORR_NEAR, "corr_dup": CORR_DUP},
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
    }
    (out / "methodology.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"      report -> {out / 'validation_report.txt'}", flush=True)
    print(f"      decisions = {decisions}", flush=True)
    print("DONE", flush=True)


if __name__ == "__main__":
    main()
