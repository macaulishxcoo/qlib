#!/usr/bin/env python3
"""S1：沪深普通 A 股日频估值轮动 + 质量/两融拥挤过滤检验 v1。

协议：research/protocols/a_share_daily_valuation_s1_protocol_v1.md

研究问题
--------
日频估值轮动（EP_ttm/PB_inv/DV_ttm）作为日频选股信号是否有效：
其 alpha 是否独立于价格反转（不是反转换皮）？叠加 PIT 质量过滤
（ep/bm/accruals）与两融拥挤剔除（rzye_zscore）后是否提升？

本脚本只检验信号层（RankIC/分层/正交性），不做组合回测（留待 S2/S3）。

口径
----
- 母池：沪深普通 A 股（all.txt 剔北交所，含退市，无幸存者偏差）
- 数据：~/.qlib/qlib_data/cn_data_2026（后复权）+ daily_basic/margin/
  fina_indicator（PIT）
- 信号：EP_ttm=1/pe_ttm, PB_inv=1/pb, DV_ttm；质量 ep/bm/accruals（TTM，
  日频市值 asof）；两融 rzye_zscore(250d)
- 标签：T+1 开盘成交 Ref($open,-1)/(Ref($close,-(h+1))-1)，主检验 h=5
- 过滤：ST/*ST/退市整理(PIT) + 停牌 + 涨停信号日
- 检验窗口：2022-01-01 ~ 2026-07-31（数据预热自 2020-07-01）

输出（拒绝覆盖非空目录）
------------------------
output/analysis_static/a_share_daily_valuation_s1/
  t1_signal_ic.csv / t2_orthogonality.csv / t3_quality_filter.csv
  t4_margin_filter.csv / t5_composite.csv / ts_size_layers.csv
  daily_ic.csv.gz / decision.json / methodology.json / validation_report.txt
"""

from __future__ import annotations

import argparse
import glob
import json
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd
from scipy import stats

import qlib
from qlib.config import REG_CN
from qlib.data import D

from analyze_a_share_trend_persistence_v1 import build_universe, qlib_to_ts, is_gem
from load_financials_extended_v1 import load_financials_extended

QLIB_DIR = Path("~/.qlib/qlib_data/cn_data_2026").expanduser()
DAILY_BASIC_DIR = Path("data/external/tushare/a_share_daily_basic_pit_v1/raw")
MARGIN_DIR = Path("data/external/tushare/margin_pit_v1/raw")
ST_INTERVALS = Path("data/external/tushare/a_share_st_status_pit_v1/normalized/st_status_intervals.csv.gz")

LOAD_START = "2020-07-01"      # 250 日 z-score + 过滤预热
EVAL_START = "2022-01-01"
DATA_END = "2026-07-31"
HORIZONS = [5, 10, 20]
N_QUANTILES = 5
LIMIT_MAIN, LIMIT_GEM = 0.095, 0.195
ZSCORE_MIN_PERIODS = 120
ZSCORE_WINDOW = 250
MARGIN_THRESH_MAIN = 2.0
MARGIN_THRESH_SENS = 1.5
QUALITY_TAIL = 0.20          # 质量分后 20% 剔除
REVERSAL_WINDOW = 20
ANNUALIZATION_DAYS = 238
T_CRIT = 2.0


def ts_to_qlib(code: str) -> str:
    """600007.SH -> SH600007"""
    num, ex = code.split(".")
    return f"{ex}{num}"


def load_daily_basic() -> pd.DataFrame:
    """读 daily_basic 按日文件（LOAD_START 起），返回 ts_code/trade_date/估值与市值字段。"""
    files = sorted(glob.glob(str(DAILY_BASIC_DIR / "*.csv.gz")))
    files = [f for f in files if f.rsplit("/", 1)[-1][:8] >= LOAD_START.replace("-", "")]
    frames = []
    for i, f in enumerate(files):
        d = pd.read_csv(f, usecols=["ts_code", "trade_date", "pe_ttm", "pb", "dv_ttm",
                                    "total_mv", "total_share", "circ_mv"])
        frames.append(d)
        if (i + 1) % 300 == 0:
            print(f"      daily_basic {i + 1}/{len(files)}", flush=True)
    out = pd.concat(frames, ignore_index=True)
    out["trade_date"] = pd.to_datetime(out["trade_date"].astype(str), format="%Y%m%d")
    out["instrument"] = out["ts_code"].map(ts_to_qlib)
    return out


def load_margin() -> pd.DataFrame:
    """读 margin 按日文件（LOAD_START 起），返回 instrument/trade_date/rzye。"""
    files = sorted(glob.glob(str(MARGIN_DIR / "*.csv.gz")))
    files = [f for f in files if f.rsplit("/", 1)[-1][:8] >= LOAD_START.replace("-", "")]
    frames = []
    for i, f in enumerate(files):
        d = pd.read_csv(f, usecols=["trade_date", "ts_code", "rzye"])
        frames.append(d)
        if (i + 1) % 300 == 0:
            print(f"      margin {i + 1}/{len(files)}", flush=True)
    out = pd.concat(frames, ignore_index=True)
    out["trade_date"] = pd.to_datetime(out["trade_date"].astype(str), format="%Y%m%d")
    out["instrument"] = out["ts_code"].map(ts_to_qlib)
    return out


def ttm_by_period(frame: pd.DataFrame, value_col: str) -> pd.DataFrame:
    """逐报告期 TTM：v[end] - v[end-1y] + v[(end.year-1)-12-31]。

    与原价值质量线 ttm_value 对"最新期"的逻辑一致，推广到全部报告期。
    """
    rows = []
    for ts_code, g in frame.groupby("ts_code"):
        g = g.dropna(subset=[value_col]).sort_values("end_date")
        if g.empty:
            continue
        val_by_end = dict(zip(g["end_date"], g[value_col]))
        for _, r in g.iterrows():
            e = r["end_date"]
            yoy = e - pd.DateOffset(years=1)
            prior = pd.Timestamp(f"{e.year - 1}-12-31")
            if yoy in val_by_end and prior in val_by_end:
                rows.append({
                    "ts_code": ts_code,
                    "end_date": e,
                    "available_date": r["available_date"],
                    value_col: float(r[value_col] - val_by_end[yoy] + val_by_end[prior]),
                })
    return pd.DataFrame(rows)


def build_quality_slow_factors() -> pd.DataFrame:
    """PIT 财务 -> 每股每报告期的慢分子：profit_dedt_ttm / bps / (ni_ttm-cfo_ttm) / total_assets。"""
    print("      loading extended financials ...", flush=True)
    fin = load_financials_extended()
    fin["end_date"] = pd.to_datetime(fin["end_date"])
    fin["available_date"] = pd.to_datetime(fin["available_date"])
    fin = fin.sort_values(["ts_code", "end_date", "available_date"]).drop_duplicates(
        ["ts_code", "end_date", "available_date"], keep="last")

    pd_ttm = ttm_by_period(fin, "profit_dedt")
    ni_ttm = ttm_by_period(fin, "n_income_attr_p")
    cfo_ttm = ttm_by_period(fin, "n_cashflow_act")

    bps = fin[["ts_code", "end_date", "available_date", "bps"]].dropna(subset=["bps"])
    assets = fin[["ts_code", "end_date", "available_date", "total_assets"]].dropna(subset=["total_assets"])

    slow = pd_ttm.rename(columns={"profit_dedt": "profit_dedt_ttm"})
    slow = slow.merge(ni_ttm.rename(columns={"n_income_attr_p": "ni_ttm"}),
                      on=["ts_code", "end_date", "available_date"], how="left")
    slow = slow.merge(cfo_ttm.rename(columns={"n_cashflow_act": "cfo_ttm"}),
                      on=["ts_code", "end_date", "available_date"], how="left")
    slow = slow.merge(bps, on=["ts_code", "end_date", "available_date"], how="left")
    slow = slow.merge(assets, on=["ts_code", "end_date", "available_date"], how="left")
    slow["ni_minus_cfo_ttm"] = slow["ni_ttm"] - slow["cfo_ttm"]
    slow["instrument"] = slow["ts_code"].map(ts_to_qlib)
    return slow[["instrument", "available_date", "profit_dedt_ttm", "bps",
                 "ni_minus_cfo_ttm", "total_assets"]].dropna(subset=["profit_dedt_ttm"])


def build_filter_mask(df: pd.DataFrame) -> np.ndarray:
    """ST/停牌/涨停过滤掩码（True=保留）。"""
    mask = df["$close"].notna() & df["$volume"].notna() & (df["$volume"] > 0)
    codes = df.index.get_level_values("instrument")
    limit = np.where(codes.map(is_gem), LIMIT_GEM, LIMIT_MAIN)
    mask &= ~(df["$change"] >= limit)

    st = pd.read_csv(ST_INTERVALS, compression="gzip", parse_dates=["start_date", "end_date"])
    st_active = st.loc[st["is_st"] | st["is_delist_phase"], ["ts_code", "start_date", "end_date"]]
    st_by_date: dict[pd.Timestamp, set[str]] = {}
    dates = df.index.get_level_values("datetime").unique()
    for d in dates:
        active = st_active[(st_active["start_date"] <= d) & (st_active["end_date"] >= d)]
        st_by_date[d] = set(active["ts_code"])
    ts = df.index.get_level_values("instrument").map(qlib_to_ts)
    dts = df.index.get_level_values("datetime")
    st_flag = np.array([c in st_by_date.get(d, set()) for d, c in zip(dts, ts)])
    mask &= ~st_flag
    return mask.to_numpy()


def daily_ic_series(df: pd.DataFrame, signal: str, label: str) -> pd.Series:
    """逐日 RankIC（Spearman），index=datetime。"""
    sub = df[[signal, label]].dropna()
    return sub.groupby(level="datetime").apply(
        lambda g: g[signal].corr(g[label], method="spearman")
        if g[signal].notna().sum() > 30 else np.nan,
        include_groups=False,
    ).dropna()


def summarize_ic(ic: pd.Series) -> dict:
    yearly = ic.groupby(ic.index.year).mean()
    return {
        "ic_mean": float(ic.mean()),
        "icir": float(ic.mean() / (ic.std() + 1e-12)),
        "ic_pos_ratio": float((ic > 0).mean()),
        "days": int(len(ic)),
        "yearly": {int(y): float(v) for y, v in yearly.items()},
    }


def daily_residual_ic(df: pd.DataFrame, signal: str, ctrl: str, label: str) -> pd.Series:
    """每日：signal 对 ctrl 横截面秩 OLS 回归取残差，残差与 label 的 Spearman。"""
    def _one(g):
        s = g[[signal, ctrl, label]].dropna()
        if len(s) < 100:
            return np.nan
        sr = s[signal].rank(pct=True).to_numpy()
        cr = s[ctrl].rank(pct=True).to_numpy()
        y = s[label].to_numpy()
        X = np.column_stack([np.ones(len(s)), cr])
        beta, *_ = np.linalg.lstsq(X, sr, rcond=None)
        resid = sr - X @ beta
        return stats.spearmanr(resid, y)[0]
    return df.groupby(level="datetime").apply(_one, include_groups=False).dropna()


def cross_rank(df: pd.DataFrame, col: str) -> pd.Series:
    return df.groupby(level="datetime")[col].rank(pct=True)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--output-dir", type=Path,
                        default=Path("output/analysis_static/a_share_daily_valuation_s1"))
    parser.add_argument("--horizon", type=int, default=5)
    args = parser.parse_args()
    out = args.output_dir
    if out.exists() and any(out.iterdir()):
        raise FileExistsError(f"Refusing to overwrite existing experiment output: {out}")
    out.mkdir(parents=True, exist_ok=True)
    label = f"FWD_{args.horizon}_open"

    qlib.init(provider_uri=str(QLIB_DIR), region=REG_CN)

    # ---- 1. 母池行情面板 ----
    print("[1/8] Universe + market panel ...", flush=True)
    codes, excluded = build_universe()
    mkt = D.features(codes, ["$close", "$open", "$change", "$volume"],
                     start_time=LOAD_START, end_time=DATA_END, freq="day")
    mkt.columns = ["$close", "$open", "$change", "$volume"]
    mkt = mkt.reset_index().set_index(["datetime", "instrument"]).sort_index()
    g = mkt.groupby(level="instrument")
    for h in HORIZONS:
        mkt[f"FWD_{h}_open"] = g["$open"].shift(-1) / g["$close"].shift(-(h + 1)) - 1
    mkt["REVERSAL_20"] = mkt["$close"] / g["$close"].shift(REVERSAL_WINDOW) - 1
    print(f"      rows={len(mkt)}, instruments={mkt.index.get_level_values('instrument').nunique()}", flush=True)

    # ---- 2. daily_basic ----
    print("[2/8] Loading daily_basic ...", flush=True)
    db = load_daily_basic()
    mkt2 = mkt.reset_index().merge(
        db[["instrument", "trade_date", "pe_ttm", "pb", "dv_ttm", "total_mv", "total_share", "circ_mv"]],
        left_on=["instrument", "datetime"], right_on=["instrument", "trade_date"], how="left",
    ).set_index(["datetime", "instrument"]).sort_index()
    mkt2["EP_ttm"] = 1.0 / mkt2["pe_ttm"].where(mkt2["pe_ttm"] > 0)
    mkt2["PB_inv"] = 1.0 / mkt2["pb"].where(mkt2["pb"] > 0)
    mkt2["DV_ttm"] = mkt2["dv_ttm"]
    print(f"      EP_ttm coverage={mkt2['EP_ttm'].notna().mean():.1%}", flush=True)

    # ---- 3. 质量慢变量（merge_asof 到日频） ----
    print("[3/8] Building quality slow factors (TTM) ...", flush=True)
    slow = build_quality_slow_factors().rename(columns={"available_date": "datetime"})
    slow = slow.drop_duplicates(["instrument", "datetime"], keep="last").sort_values("datetime")
    mkt3 = mkt2.reset_index().sort_values("datetime")
    q = pd.merge_asof(
        mkt3, slow, on="datetime", by="instrument", direction="backward",
    ).set_index(["datetime", "instrument"]).sort_index()
    q["ep"] = q["profit_dedt_ttm"] / (q["total_mv"] * 1e4)
    q["bm"] = q["bps"] * q["total_share"] / q["total_mv"]
    q["accruals"] = -q["ni_minus_cfo_ttm"] / q["total_assets"]
    q.loc[q["ep"] <= 0, "ep"] = np.nan
    q.loc[q["bps"] <= 0, "bm"] = np.nan
    q.loc[q["ni_minus_cfo_ttm"] <= 0, "accruals"] = np.nan
    print(f"      ep coverage={q['ep'].notna().mean():.1%}, bm={q['bm'].notna().mean():.1%}, "
          f"accruals={q['accruals'].notna().mean():.1%}", flush=True)

    # ---- 4. 两融 zscore ----
    print("[4/8] Loading margin + zscore ...", flush=True)
    mg = load_margin()
    mg = mg.sort_values(["instrument", "trade_date"])
    mg["rzye_zscore"] = mg.groupby("instrument")["rzye"].transform(
        lambda s: (s - s.rolling(ZSCORE_WINDOW, min_periods=ZSCORE_MIN_PERIODS).mean())
        / (s.rolling(ZSCORE_WINDOW, min_periods=ZSCORE_MIN_PERIODS).std() + 1e-12)
    )
    mkt4 = q.reset_index().merge(
        mg[["instrument", "trade_date", "rzye_zscore"]],
        left_on=["instrument", "datetime"], right_on=["instrument", "trade_date"], how="left",
    ).set_index(["datetime", "instrument"]).sort_index()
    print(f"      rzye_zscore coverage={mkt4['rzye_zscore'].notna().mean():.1%}", flush=True)

    # ---- 5. 过滤 ----
    print("[5/8] Filters ...", flush=True)
    mask = build_filter_mask(mkt4)
    eval_all = mkt4.loc[pd.Timestamp(EVAL_START): pd.Timestamp(DATA_END)]
    mask_full = pd.Series(mask, index=mkt4.index)
    df = eval_all.loc[mask_full.loc[eval_all.index].to_numpy()]
    print(f"      eval rows={len(df)}, keep={mask.mean():.1%}", flush=True)

    # ---- 6. 组合分数 ----
    print("[6/8] Composite scores ...", flush=True)
    df["r_EP"] = cross_rank(df, "EP_ttm")
    df["r_PB"] = cross_rank(df, "PB_inv")
    df["r_DV"] = cross_rank(df, "DV_ttm")
    df["combo0"] = (df["r_EP"] + df["r_PB"] + df["r_DV"]) / 3
    df["r_ep"] = cross_rank(df, "ep")
    df["r_bm"] = cross_rank(df, "bm")
    df["r_acc"] = cross_rank(df, "accruals")
    df["quality"] = (df["r_ep"] + df["r_bm"] + df["r_acc"]) / 3
    df["quality_pct"] = cross_rank(df, "quality")
    df["combo1"] = df["combo0"].where(df["quality_pct"] >= QUALITY_TAIL)
    # 无两融数据（非标的）视为不拥挤，保留；仅剔除 rzye_zscore > 阈值 的过热票
    df["combo2"] = df["combo1"].where(
        df["rzye_zscore"].isna() | (df["rzye_zscore"] <= MARGIN_THRESH_MAIN)
    )

    # ---- 7. 检验 ----
    print("[7/8] T1-T5 tests ...", flush=True)
    t1_rows = []
    for sig in ["EP_ttm", "PB_inv", "DV_ttm"]:
        ic = daily_ic_series(df, sig, label)
        s = summarize_ic(ic)
        s["signal"] = sig
        t1_rows.append(s)
    t1 = pd.DataFrame(t1_rows).set_index("signal")
    t1.to_csv(out / "t1_signal_ic.csv")

    ic_ep = daily_ic_series(df, "EP_ttm", label)
    ic_ep_resid = daily_residual_ic(df, "EP_ttm", "REVERSAL_20", label)
    decay = 1 - abs(ic_ep_resid.mean()) / (abs(ic_ep.mean()) + 1e-12)
    t2 = pd.DataFrame([{
        "signal": "EP_ttm", "orig_ic": ic_ep.mean(), "resid_ic": ic_ep_resid.mean(),
        "decay": decay,
    }])
    t2.to_csv(out / "t2_orthogonality.csv", index=False)

    t3_rows = []
    for sig in ["EP_ttm", "combo0"]:
        ic_all = daily_ic_series(df, sig, label)
        sub = df[df["quality_pct"].ge(QUALITY_TAIL)]
        ic_filt = daily_ic_series(sub, sig, label)
        t3_rows.append({
            "signal": sig, "ic_all": ic_all.mean(), "ic_quality_filtered": ic_filt.mean(),
            "delta": ic_filt.mean() - ic_all.mean(),
        })
    t3 = pd.DataFrame(t3_rows)
    t3.to_csv(out / "t3_quality_filter.csv", index=False)

    t4_rows = []
    for sig in ["combo1"]:
        ic_all = daily_ic_series(df, sig, label)
        sub2 = df[df["rzye_zscore"].le(MARGIN_THRESH_MAIN) | df["rzye_zscore"].isna()]
        ic_filt = daily_ic_series(sub2, sig, label)
        s_all, s_filt = summarize_ic(ic_all), summarize_ic(ic_filt)
        t4_rows.append({
            "signal": sig, "ic_all": s_all["ic_mean"], "icir_all": s_all["icir"],
            "ic_margin_filtered": s_filt["ic_mean"], "icir_margin_filtered": s_filt["icir"],
            "delta_ic": s_filt["ic_mean"] - s_all["ic_mean"],
        })
    t4 = pd.DataFrame(t4_rows)
    t4.to_csv(out / "t4_margin_filter.csv", index=False)

    combo_ics = {}
    for name in ["combo0", "combo1", "combo2"]:
        combo_ics[name] = daily_ic_series(df, name, label)
    t5 = pd.DataFrame({k: summarize_ic(v) for k, v in combo_ics.items()}).T
    t5.to_csv(out / "t5_composite.csv")
    combo_ics["combo2"].dropna().to_csv(out / "daily_ic.csv.gz", compression="gzip")

    # 市值分层（按日截面 total_mv 分位）
    size_rows = []
    mv_pct = cross_rank(df, "total_mv")
    for layer, (lo, hi) in enumerate([(0, 0.2), (0.2, 0.4), (0.4, 0.6), (0.6, 0.8), (0.8, 1.0)]):
        sub = df[(mv_pct > lo) & (mv_pct <= hi)]
        ic = daily_ic_series(sub, "EP_ttm", label)
        size_rows.append({"layer": f"S{layer + 1}", "ic_mean": ic.mean(), "days": len(ic)})
    pd.DataFrame(size_rows).to_csv(out / "ts_size_layers.csv", index=False)

    # ---- 8. 判定与报告 ----
    print("[8/8] Decision + report ...", flush=True)
    c2 = summarize_ic(combo_ics["combo2"])
    if decay < 0.5 and c2["icir"] >= 0.3:
        decision = "signal_viable"
    elif decay >= 0.5:
        decision = "reversal_artifact"
    else:
        decision = "signal_weak"

    stress = combo_ics["combo2"].loc["2025-07-01":]
    stress_s = summarize_ic(stress) if len(stress) > 20 else {"ic_mean": np.nan, "icir": np.nan, "ic_pos_ratio": np.nan, "days": len(stress)}

    lines = []
    lines.append(f"# S1 日频估值 + 质量/两融过滤检验报告 v1\n")
    lines.append(f"- 母池: 沪深普通 A 股 {len(codes)} 只（剔北交所 {len(excluded)}）")
    lines.append(f"- 窗口: {EVAL_START} ~ {DATA_END}（预热自 {LOAD_START}），过滤保留率 {mask.mean():.1%}")
    lines.append(f"- 主 label: T+1 开盘成交 h={args.horizon}")
    lines.append(f"\n## 判定：**{decision}**\n")

    lines.append("### T1 单信号 RankIC")
    lines.append("| 信号 | IC | ICIR | IC>0 | 分年度 |")
    lines.append("|---|---|---|---|---|")
    for sig, r in t1.iterrows():
        yr = " ".join(f"{y}:{v:+.3f}" for y, v in r["yearly"].items())
        lines.append(f"| {sig} | {r['ic_mean']:+.4f} | {r['icir']:.2f} | {r['ic_pos_ratio']:.0%} | {yr} |")

    lines.append(f"\n### T2 反转正交性（EP_ttm vs REVERSAL_{REVERSAL_WINDOW}）")
    lines.append(f"| 原IC | 残差IC | 衰减 | 判定 |")
    lines.append(f"|---|---|---|---|")
    lines.append(f"| {ic_ep.mean():+.4f} | {ic_ep_resid.mean():+.4f} | {decay:.0%} | {'<50% 非换皮' if decay < 0.5 else '>=50% 反转换皮'} |")

    lines.append("\n### T3 质量过滤增量（剔除质量后 20%）")
    for _, r in t3.iterrows():
        lines.append(f"- {r['signal']}: 全样本 IC {r['ic_all']:+.4f} → 过滤后 {r['ic_quality_filtered']:+.4f} (Δ{r['delta']:+.4f})")

    lines.append("\n### T4 两融拥挤剔除（rzye_zscore>2）")
    for _, r in t4.iterrows():
        lines.append(f"- {r['signal']}: IC {r['ic_all']:+.4f}(IR {r['icir_all']:.2f}) → 剔除后 {r['ic_margin_filtered']:+.4f}(IR {r['icir_margin_filtered']:.2f})")

    lines.append("\n### T5 组合 0/1/2")
    lines.append("| 组合 | IC | ICIR | IC>0 |")
    lines.append("|---|---|---|---|")
    for name in ["combo0", "combo1", "combo2"]:
        r = summarize_ic(combo_ics[name])
        lines.append(f"| {name} | {r['ic_mean']:+.4f} | {r['icir']:.2f} | {r['ic_pos_ratio']:.0%} |")

    lines.append("\n### 市值分层（EP_ttm 各层 IC）")
    for _, r in pd.DataFrame(size_rows).iterrows():
        lines.append(f"- {r['layer']}: IC {r['ic_mean']:+.4f}")

    lines.append(f"\n### 压力段 2025-07 后（组合2）")
    lines.append(f"- IC {stress_s['ic_mean']:+.4f} / ICIR {stress_s['icir']:.2f} / 天数 {stress_s['days']}")

    (out / "validation_report.txt").write_text("\n".join(lines), encoding="utf-8")

    meta = {
        "purpose": "S1 日频估值轮动 + 质量/两融过滤信号层检验",
        "protocol": "research/protocols/a_share_daily_valuation_s1_protocol_v1.md",
        "universe": f"沪深普通 A 股 {len(codes)} 只",
        "eval_window": [EVAL_START, DATA_END],
        "horizon": args.horizon,
        "decision": decision,
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
    }
    (out / "methodology.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    (out / "decision.json").write_text(json.dumps({"decision": decision, **{k: summarize_ic(combo_ics[k]) for k in combo_ics}}, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"      report -> {out / 'validation_report.txt'}", flush=True)
    print(f"      decision = {decision}", flush=True)
    print("DONE", flush=True)


if __name__ == "__main__":
    main()
