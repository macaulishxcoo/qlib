#!/usr/bin/env python3
"""主升浪因子仓库口径复验（validation v1）。

研究问题
--------
1. 对话验证（新浪前复权日线、118 只当前成分、2022-2026）的结论在仓库口径下
   是否存活？仓库口径 = cn_data_2026（后复权）+ qlib csi1000 历史成分
   （含被调出/退市，无幸存者偏差）+ ST/停牌/涨停过滤。
2. 主升浪 15 因子与 Alpha158 关键族的冗余度，验证"增量"主张是否成立。

口径
----
- 股票池：qlib csi1000 历史成分（D.instruments 按 csi1000.txt 历史区间解析）
- 数据：~/.qlib/qlib_data/cn_data_2026
- label：Ref($open,-1)/Ref($close,-(h+1))-1（T+1 开盘成交口径，h=5/10/20），
  另附 h=5 close-to-close 作口径对比
- 过滤：ST/*ST/退市整理（st_status_pit_v1 PIT 区间，逐日 asof）+ 停牌
  （无有效价格/量）+ 涨停信号日（主板 9.5%、创业板/科创板 19.5%）
- 冗余阈值：逐日横截面 Spearman 中位数 |corr| > 0.70 判近亲，> 0.95 判重复

输出（拒绝覆盖非空目录）
------------------------
output/analysis_static/zsl_main_wave_factor_validation_v1/
  zsl_ic_summary.csv        15 因子 × 口径 × horizon 的 RankIC/ICIR/分年度/正占比
  zsl_quantile_spread.csv   5 分位多空价差（h=5）
  zsl_filter_impact.csv     过滤前后 IC 对比（h=5）
  zsl_vs_alpha158_corr.csv  15 因子 vs Alpha158 对照族的逐日相关汇总
  methodology.json          口径快照
  validation_report.txt     中文报告
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
INSTRUMENTS = "csi1000"
DATA_START = "2020-01-01"          # 提供 250 日预热 + 未来 20 日缓冲
DATA_END = "2026-07-31"
EVAL_START = "2022-01-01"          # 与对话验证窗口可比
HORIZONS = [5, 10, 20]
N_QUANTILES = 5

ST_INTERVALS = Path("data/external/tushare/a_share_st_status_pit_v1/normalized/st_status_intervals.csv.gz")
LIMIT_MAIN = 0.095      # 主板 10% 涨停
LIMIT_GEM = 0.195       # 创业板/科创板 20% 涨停
CORR_NEAR = 0.70
CORR_DUP = 0.95

# ---- 主升浪 15 因子（qlib 表达式，来源：用户主升浪因子库脚本） ----
ZSL_FACTOR_EXPRESSIONS = {
    # 1. 趋势状态：均线多头排列、趋势向上
    "MA_SPREAD": "((Mean($close,5)-Mean($close,20))/Mean($close,20)"
                 "+(Mean($close,20)-Mean($close,60))/Mean($close,60))/2",
    "SLOPE_NORM": "Slope(Mean($close,20),10)/Mean($close,20)",
    "ABOVE_MA60": "$close/Mean($close,60)-1",
    # 2. 价格位置：从底部起来、接近新高
    "DIST_HIGH_250": "$close/Max($high,250)-1",
    "UP_FROM_LOW_250": "$close/Min($low,250)-1",
    # 3. 突破：创阶段新高
    "BREAKOUT_120": "$close/Ref(Max($high,120),1)-1",
    # 4. 蓄势质量：突破前横盘紧凑度
    "TIGHTNESS_20": "(Max($high,20)-Min($low,20))/Mean($close,20)",
    "TIGHTNESS_60": "(Max($high,60)-Min($low,60))/Mean($close,60)",
    # 5. 量能确认：放量上涨、量价齐升
    "VOL_RATIO": "$volume/(Mean($volume,20)+1e-8)",
    "PV_CORR_20": "Corr($close,$volume,20)",
    "VOL_TREND": "Mean($volume,5)/(Mean($volume,60)+1e-8)",
    # 6. 动量与路径质量：涨得稳、不是一天爆拉
    "MOM_20_5": "Ref($close,5)/(Ref($close,25)+1e-8)-1",
    # FIP_60 无法用 qlib 表达式可靠表达（Count 对布尔比较语义有坑），
    # 在 load_data() 中逐股用 pandas 计算，见 compute_fip_60()。
    "SMOOTH_MOM": "($close/(Ref($close,20)+1e-8)-1)"
                  "/(Std($close/(Ref($close,1)+1e-8)-1,20)+1e-4)",
    "PULLBACK_20": "$close/Max($high,20)-1",
}

# 越小越好、IC 取反后解读的因子
DIRECTION_FLIP = {"TIGHTNESS_20", "TIGHTNESS_60", "FIP_60"}

# ---- Alpha158 对照族（语义上与主升浪因子最近） ----
CONTROL_SELECT = [
    "MA5", "MA10", "MA20", "MA60",
    "ROC5", "ROC20", "ROC60",
    "BETA10", "BETA20", "BETA60",
    "KLEN", "STD20",
    "CORR5", "CORR20", "CORR60",
    "CORD20",
    "VMA5", "VMA20", "VMA60",
    "VSUMP20",
    "MAX20", "MAX60", "MIN20", "MIN60",
    "RANK20", "RSV20", "IMAX60",
]


def qlib_to_ts(code: str) -> str:
    """SH600007 -> 600007.SH"""
    return f"{code[2:]}.{code[:2]}"


def is_gem(code: str) -> bool:
    """创业板 30xxxx（深）与科创板 688xxx（沪）为 20% 涨跌停。"""
    num = code[2:]
    return num.startswith("30") or num.startswith("688")


def alpha158_map() -> dict[str, str]:
    fields, names = Alpha158DL.get_feature_config(
        {
            "kbar": {},
            "price": {"windows": [0], "feature": ["OPEN", "HIGH", "LOW", "VWAP"]},
            "rolling": {},
        }
    )
    return dict(zip(names, fields))


def load_data() -> pd.DataFrame:
    """拉取主升浪因子 + Alpha158 对照 + 未来收益 label + 过滤用原始字段。"""
    amap = alpha158_map()
    control_exprs = {}
    missing = []
    for name in CONTROL_SELECT:
        if name in amap:
            control_exprs[name] = amap[name]
        else:
            missing.append(name)
    if missing:
        print(f"      [warn] Alpha158 对照缺失: {missing}", flush=True)

    labels = {}
    for h in HORIZONS:
        labels[f"FWD_{h}_open"] = f"Ref($open,-1)/(Ref($close,-{h+1})+1e-8)-1"
    labels["FWD_5_close"] = "Ref($close,-5)/$close-1"   # 口径对比用

    fields = list(ZSL_FACTOR_EXPRESSIONS.values()) + list(control_exprs.values()) + list(labels.values())
    names = list(ZSL_FACTOR_EXPRESSIONS.keys()) + list(control_exprs.keys()) + list(labels.keys())
    raw_fields = ["$close", "$change", "$volume", "$open", "$high", "$low"]

    print(f"[1/5] Loading {len(fields)} factor/label fields from qlib ...", flush=True)
    df = D.features(D.instruments(INSTRUMENTS), fields + raw_fields, start_time=DATA_START, end_time=DATA_END, freq="day")
    df.columns = names + raw_fields
    # qlib 返回 MultiIndex (instrument, datetime) -> 重排为 (datetime, instrument)
    df = df.reset_index().set_index(["datetime", "instrument"]).sort_index()
    df["FIP_60"] = compute_fip_60(df["$close"])
    print(f"      rows={len(df)}, instruments={df.index.get_level_values('instrument').nunique()}, "
          f"dates={df.index.get_level_values('datetime').nunique()}", flush=True)
    return df


def compute_fip_60(close: pd.Series) -> pd.Series:
    """逐股计算 FIP_60（Frog-in-the-Pan 信息离散度）。

    FIP = sign(60 日动量) * (60 日内下跌天数占比 - 上涨天数占比)
    qlib 表达式的 Count(布尔) 语义不可靠（后复权价上涨日占比高导致恒 0），
    这里用 pandas rolling 精确实现，返回与 close 同 index 的 Series。
    """
    df = close.reset_index()[["instrument", "datetime", "$close"]].sort_values(["instrument", "datetime"])
    ret = df.groupby("instrument")["$close"].pct_change()
    up = (ret > 0).astype(float)
    dn = (ret < 0).astype(float)
    up_sum = up.groupby(df["instrument"]).transform(lambda s: s.rolling(60, min_periods=30).sum())
    dn_sum = dn.groupby(df["instrument"]).transform(lambda s: s.rolling(60, min_periods=30).sum())
    mom60 = df["$close"] / df.groupby("instrument")["$close"].shift(60) - 1
    fip = np.sign(mom60) * (dn_sum - up_sum) / 60
    out = pd.Series(fip.to_numpy(), index=pd.MultiIndex.from_arrays([df["datetime"], df["instrument"]]))
    return out.reindex(close.index)


def build_filter_mask(df: pd.DataFrame) -> pd.DataFrame:
    """逐日构建 ST/停牌/涨停过滤掩码（True = 保留，False = 剔除信号观测）。"""
    print("[2/5] Building ST / suspension / limit-up filters ...", flush=True)
    mask = pd.DataFrame(True, index=df.index, columns=["keep"])

    # 停牌：无有效价格或成交量
    mask["keep"] &= df["$close"].notna() & df["$volume"].notna() & (df["$volume"] > 0)

    # 涨停信号日（当日买入不可成交）：按 code 前缀分板阈值
    codes = df.index.get_level_values("instrument")
    gem_flag = codes.map(is_gem)
    limit_thresh = np.where(gem_flag, LIMIT_GEM, LIMIT_MAIN)
    mask["keep"] &= ~(df["$change"] >= limit_thresh)

    # ST/*ST/退市整理（PIT 区间，逐日 asof）
    st = pd.read_csv(ST_INTERVALS, compression="gzip", parse_dates=["start_date", "end_date"])
    st_active = st.loc[st["is_st"] | st["is_delist_phase"], ["ts_code", "start_date", "end_date"]]
    st_set_by_date: dict[pd.Timestamp, set[str]] = {}
    dates = df.index.get_level_values("datetime").unique()
    for d in dates:
        active = st_active[(st_active["start_date"] <= d) & (st_active["end_date"] >= d)]
        st_set_by_date[d] = set(active["ts_code"])
    ts = df.index.get_level_values("instrument").map(qlib_to_ts)
    df_tmp = pd.DataFrame({"datetime": df.index.get_level_values("datetime"), "ts_code": ts})
    df_tmp["is_st"] = [
        ts_code in st_set_by_date.get(d, set())
        for d, ts_code in zip(df_tmp["datetime"], df_tmp["ts_code"])
    ]
    mask["keep"] &= ~df_tmp["is_st"].to_numpy()

    print(f"      keep ratio: {mask['keep'].mean():.1%}", flush=True)
    return mask


def cross_pair_correlations(sub: pd.DataFrame, group_a: list[str], group_b: list[str]) -> pd.DataFrame:
    """逐日横截面 Spearman 相关，只算 group_a × group_b 跨组对。

    返回 DataFrame: datetime, factor_a(in group_a), factor_b(in group_b), spearman
    """
    rows = []
    for d, g in sub.groupby(level="datetime", sort=True):
        m = g[group_a + group_b].corr(method="spearman")
        for a in group_a:
            for b in group_b:
                rows.append((d, a, b, m.loc[a, b]))
    return pd.DataFrame(rows, columns=["datetime", "factor_a", "factor_b", "spearman"])


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--output-dir", type=Path,
                        default=Path("output/analysis_static/zsl_main_wave_factor_validation_v1"))
    args = parser.parse_args()
    out = args.output_dir
    if out.exists() and any(out.iterdir()):
        raise FileExistsError(f"Refusing to overwrite existing experiment output: {out}")
    out.mkdir(parents=True, exist_ok=True)

    qlib.init(provider_uri=str(QLIB_DIR), region=REG_CN)
    df = load_data()
    mask = build_filter_mask(df)

    eval_df = df.loc[pd.Timestamp(EVAL_START): pd.Timestamp(DATA_END)]

    # ---- 3. 主检验：15 因子 RankIC ----
    print("[3/5] Computing daily RankIC for 15 ZSL factors ...", flush=True)
    # FIP_60 由 pandas 计算（见 compute_fip_60），不在表达式 dict 中，显式补回
    zsl_cols = list(ZSL_FACTOR_EXPRESSIONS.keys()) + ["FIP_60"]
    label_cols = [f"FWD_{h}_open" for h in HORIZONS] + ["FWD_5_close"]
    ic_rows = []
    for f in zsl_cols:
        for lab in label_cols:
            sub = eval_df[[f, lab]].dropna()
            ic = sub.groupby(level="datetime").apply(
                lambda g: g[f].corr(g[lab], method="spearman")
                if g[f].notna().sum() > 30 else np.nan
            ).dropna()
            if f in DIRECTION_FLIP:
                ic = -ic
            yearly = ic.groupby(ic.index.year).agg(["mean", "std", "count"])
            row = {
                "factor": f,
                "label": lab,
                "ic_mean": ic.mean(),
                "icir": ic.mean() / (ic.std() + 1e-12),
                "ic_pos_ratio": (ic > 0).mean(),
                "days": len(ic),
            }
            for y, yr in yearly.iterrows():
                row[f"ic_{y}"] = yr["mean"]
            ic_rows.append(row)
    ic_sum = pd.DataFrame(ic_rows)
    ic_sum.to_csv(out / "zsl_ic_summary.csv", index=False)
    print(f"      done: {len(ic_sum)} rows", flush=True)

    # ---- 4. 分层价差（h=5, T+1 口径） ----
    print("[4/5] Quantile spread (Q5-Q1, FWD_5_open) ...", flush=True)
    spread_rows = []
    for f in zsl_cols:
        sub = eval_df[[f, "FWD_5_open"]].dropna()
        def _spread(g):
            if g[f].notna().sum() < N_QUANTILES * 10:
                return np.nan
            q = pd.qcut(g[f], N_QUANTILES, labels=False, duplicates="drop")
            return g.loc[q == q.max(), "FWD_5_open"].mean() - g.loc[q == q.min(), "FWD_5_open"].mean()
        sp = sub.groupby(level="datetime").apply(_spread).dropna()
        if f in DIRECTION_FLIP:
            sp = -sp
        spread_rows.append({"factor": f, "q5_q1_daily_mean": sp.mean(), "q5_q1_daily_std": sp.std(), "days": len(sp)})
    pd.DataFrame(spread_rows).to_csv(out / "zsl_quantile_spread.csv", index=False)

    # ---- 5. 过滤影响（h=5 T+1 口径：全样本 vs 过滤后） ----
    print("[5/5] Filter impact ...", flush=True)
    filt_rows = []
    for f in zsl_cols:
        all_ic = eval_df[[f, "FWD_5_open"]].dropna().groupby(level="datetime").apply(
            lambda g: g[f].corr(g["FWD_5_open"], method="spearman") if g[f].notna().sum() > 30 else np.nan
        ).dropna()
        kept = eval_df.loc[mask["keep"].loc[eval_df.index], [f, "FWD_5_open"]].dropna().groupby(level="datetime").apply(
            lambda g: g[f].corr(g["FWD_5_open"], method="spearman") if g[f].notna().sum() > 30 else np.nan
        ).dropna()
        if f in DIRECTION_FLIP:
            all_ic, kept = -all_ic, -kept
        filt_rows.append({
            "factor": f,
            "ic_all_mean": all_ic.mean(),
            "ic_filtered_mean": kept.mean(),
            "delta": kept.mean() - all_ic.mean(),
        })
    filt_sum = pd.DataFrame(filt_rows)
    filt_sum.to_csv(out / "zsl_filter_impact.csv", index=False)

    # ---- 冗余：ZSL vs Alpha158 对照 ----
    print("[+] Redundancy: ZSL vs Alpha158 controls ...", flush=True)
    control_cols = [c for c in CONTROL_SELECT if c in df.columns]
    red = cross_pair_correlations(eval_df[zsl_cols + control_cols].dropna(how="all"), zsl_cols, control_cols)
    red = red.rename(columns={"factor_a": "zsl", "factor_b": "alpha158"})
    red_sum = (
        red.groupby(["zsl", "alpha158"])["spearman"]
        .agg(median="median", max_abs=lambda s: s.abs().max(), days="count")
        .reset_index()
    )
    red_sum["flag"] = np.where(red_sum["median"].abs() > CORR_DUP, "duplicate",
                     np.where(red_sum["median"].abs() > CORR_NEAR, "near_duplicate", "distinct"))
    red_sum.to_csv(out / "zsl_vs_alpha158_corr.csv", index=False)

    # ---- 汇总每因子最接近的对照 ----
    worst = (
        red_sum.sort_values("median", key=lambda s: s.abs(), ascending=False)
        .drop_duplicates("zsl")
        .sort_values("zsl")
        [["zsl", "alpha158", "median", "max_abs", "flag"]]
    )

    # ---- 报告 ----
    print("[+] Writing report ...", flush=True)
    lines = []
    lines.append("# 主升浪因子仓库口径复验报告 v1\n")
    lines.append(f"- 股票池: qlib {INSTRUMENTS} 历史成分（无幸存者偏差）")
    lines.append(f"- 数据: {QLIB_DIR}（后复权）")
    lines.append(f"- 检验窗口: {EVAL_START} ~ {DATA_END}，数据预热自 {DATA_START}")
    lines.append(f"- label: T+1 开盘成交口径 Ref($open,-1)/Ref($close,-(h+1))-1, h={HORIZONS}")
    lines.append(f"- 过滤: ST/*ST/退市整理 + 停牌 + 涨停信号日；保留率见下")
    lines.append(f"- 冗余判定: 中位 |Spearman| > {CORR_DUP} = duplicate, > {CORR_NEAR} = near_duplicate\n")
    lines.append(f"过滤保留率: {mask['keep'].mean():.1%}\n")

    lines.append("## 一、RankIC 主表（h=5, T+1 口径）")
    lines.append("| 因子 | IC | ICIR | IC>0占比 | Q5-Q1(日) | 最接近的Alpha158 | 相关 | 判定 |")
    lines.append("|---|---|---|---|---|---|---|---|")
    lookup = {r["factor"]: r for _, r in ic_sum[ic_sum["label"] == "FWD_5_open"].iterrows()}
    spread_lookup = {r["factor"]: r["q5_q1_daily_mean"] for _, r in pd.DataFrame(spread_rows).iterrows()}
    worst_lookup = {r["zsl"]: r for _, r in worst.iterrows()}
    for f in zsl_cols:
        r = lookup.get(f, {})
        w = worst_lookup.get(f, {})
        lines.append(f"| {f} | {r.get('ic_mean', np.nan):+.4f} | {r.get('icir', np.nan):.2f} | "
                     f"{r.get('ic_pos_ratio', np.nan):.0%} | {spread_lookup.get(f, np.nan):+.5f} | "
                     f"{w.get('alpha158', '-')} | {w.get('median', np.nan):+.2f} | {w.get('flag', '-')} |")

    lines.append("\n## 二、分年度 IC（h=5, T+1 口径）")
    years = sorted({c for c in ic_sum.columns if str(c).startswith("ic_20")})
    lines.append("| 因子 | " + " | ".join(y.replace("ic_", "") for y in years) + " |")
    lines.append("|" + "---|" * (len(years) + 1))
    for f in zsl_cols:
        r = lookup.get(f, {})
        lines.append(f"| {f} | " + " | ".join(f"{r.get(y, np.nan):+.3f}" for y in years) + " |")

    lines.append("\n## 三、与对话验证（新浪 118 只当前成分）结论对照")
    lines.append("| 维度 | 对话结论 | 仓库复验 | 判定 |")
    lines.append("|---|---|---|---|")
    lines.append("| 中期动量有效 | ABOVE_MA60/MOM_20_5 IC≈+0.04 | 见上表 | 以复验为准 |")
    lines.append("| VOL_TREND/PV_CORR 为增量 | 是 | 见冗余表（对照 Alpha158 CORR/VMA 族） | 以复验为准 |")
    lines.append("| TIGHTNESS 方向反 | 是（-0.055） | 见上表 | 以复验为准 |")
    lines.append("| DIST_HIGH_250 无效 | IC≈0.005 | 见上表 | 以复验为准 |")
    lines.append("| 条件组合失败 | 不支持形态内挑动量 | 本复验未复现条件组合 | — |")

    lines.append("\n## 四、冗余汇总（每因子最接近的 Alpha158 对照）")
    lines.append("| 主升浪因子 | 最近 Alpha158 | 中位相关 | 判定 |")
    lines.append("|---|---|---|---|")
    for _, w in worst.iterrows():
        lines.append(f"| {w['zsl']} | {w['alpha158']} | {w['median']:+.2f} | {w['flag']} |")

    lines.append("\n## 五、过滤影响（h=5: 全样本 vs 过滤后 IC）")
    lines.append("| 因子 | 全样本 | 过滤后 | Δ |")
    lines.append("|---|---|---|---|")
    for _, r in filt_sum.iterrows():
        lines.append(f"| {r['factor']} | {r['ic_all_mean']:+.4f} | {r['ic_filtered_mean']:+.4f} | {r['delta']:+.4f} |")

    (out / "validation_report.txt").write_text("\n".join(lines), encoding="utf-8")

    meta = {
        "purpose": "主升浪因子仓库口径复验：对话结论复核 + Alpha158 冗余核查",
        "universe": f"qlib {INSTRUMENTS} 历史成分",
        "data_dir": str(QLIB_DIR),
        "eval_window": [EVAL_START, DATA_END],
        "data_warmup_from": DATA_START,
        "label": "Ref($open,-1)/Ref($close,-(h+1))-1, h=5/10/20; FWD_5_close 作口径对比",
        "filters": "ST/*ST/退市整理(PIT) + 停牌 + 涨停信号日",
        "zsl_factor_count": len(zsl_cols),
        "alpha158_control_count": len(control_cols),
        "corr_thresholds": {"near_duplicate": CORR_NEAR, "duplicate": CORR_DUP},
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
    }
    (out / "methodology.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"      report -> {out / 'validation_report.txt'}", flush=True)
    print("DONE", flush=True)


if __name__ == "__main__":
    main()
