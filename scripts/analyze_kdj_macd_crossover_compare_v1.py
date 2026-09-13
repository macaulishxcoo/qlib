#!/usr/bin/env python3
"""KDJ vs MACD 金叉入场对比 v1（提前买 vs 等确认）。

场景：评论称"KDJ 金叉 + MACD 即将金叉，提前买，结果科技大回调；等 MACD
金叉确认就躲过了"。本脚本将两种入场方式做成可检验对比：
  - 版本 A（提前买）：KDJ 金叉日信号（KDJ 先行于 MACD）
  - 版本 B（等确认）：MACD 金叉日信号（DIF 上穿 DEA）

口径
----
- 母池：沪深普通 A 股（all.txt 剔北交所，约 5542 只，含退市）
- 数据：cn_data_2026（后复权）
- KDJ：RSV=(C-LLV(L,9))/(HHV(H,9)-LLV(L,9))*100，K=SMA(RSV,3)，D=SMA(K,3)
      金叉 = K 上穿 D（前日 K<=D 且今日 K>D）
- MACD：DIF=EMA12-EMA26，DEA=EMA(DIF,9)；金叉 = DIF 上穿 DEA
- 未来收益：T+1 开盘成交 Ref($open,-1)/(Ref($close,-(h+1))-1)，h=5/10/20
- 过滤：ST/*ST/退市（PIT）+ 停牌 + 涨停信号日
- 检验窗口：2022-01-01 ~ 2026-06-30（保证 h=20 未来完整；不使用基准，
  对比纯股票自身收益，避免 SH000852 数据 bug 干扰）

输出（拒绝覆盖非空目录）
------------------------
output/analysis_static/kdj_macd_crossover_compare_v1/
  compare_summary.csv / yearly_summary.csv / validation_report.txt / methodology.json
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

from analyze_a_share_trend_persistence_v1 import build_universe, qlib_to_ts, is_gem

QLIB_DIR = Path("~/.qlib/qlib_data/cn_data_2026").expanduser()
ST_INTERVALS = Path("data/external/tushare/a_share_st_status_pit_v1/normalized/st_status_intervals.csv.gz")

DATA_START = "2020-01-01"   # 指标预热
EVAL_START = "2022-01-01"
EVAL_END = "2026-06-30"
HORIZONS = [5, 10, 20]
LIMIT_MAIN, LIMIT_GEM = 0.095, 0.195
ANNUALIZATION_DAYS = 238


def compute_indicators(df: pd.DataFrame) -> pd.DataFrame:
    """逐股计算 KDJ(K/D) 与 MACD(DIF/DEA)。"""
    df = df.sort_index()
    g = df.groupby(level="instrument")
    llv9 = g["$low"].transform(lambda s: s.rolling(9, min_periods=9).min())
    hhv9 = g["$high"].transform(lambda s: s.rolling(9, min_periods=9).max())
    rsv = (df["$close"] - llv9) / (hhv9 - llv9 + 1e-12) * 100.0
    df["K"] = rsv.ewm(alpha=1 / 3, adjust=False).mean()
    df["D"] = df["K"].ewm(alpha=1 / 3, adjust=False).mean()

    ema12 = g["$close"].transform(lambda s: s.ewm(span=12, adjust=False).mean())
    ema26 = g["$close"].transform(lambda s: s.ewm(span=26, adjust=False).mean())
    df["DIF"] = ema12 - ema26
    df["DEA"] = df["DIF"].ewm(alpha=1 / 10, adjust=False).mean()  # 指数族按股内连续
    # DEA 需按股单独 ewm，上面的整体 ewm 跨股会串，改为逐股：
    df["DEA"] = df.groupby(level="instrument")["DIF"].transform(
        lambda s: s.ewm(alpha=1 / 10, adjust=False).mean()
    )
    return df


def build_filter_mask(df: pd.DataFrame) -> np.ndarray:
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
    mask &= ~np.array([c in st_by_date.get(d, set()) for d, c in zip(dts, ts)])
    return mask.to_numpy()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--output-dir", type=Path,
                        default=Path("output/analysis_static/kdj_macd_crossover_compare_v1"))
    args = parser.parse_args()
    out = args.output_dir
    if out.exists() and any(out.iterdir()):
        raise FileExistsError(f"Refusing to overwrite existing experiment output: {out}")
    out.mkdir(parents=True, exist_ok=True)

    qlib.init(provider_uri=str(QLIB_DIR), region=REG_CN)

    # ---- 1. 面板 + 指标 ----
    print("[1/4] Loading market + computing KDJ/MACD ...", flush=True)
    codes, excluded = build_universe()
    mkt = D.features(codes, ["$close", "$open", "$high", "$low", "$change", "$volume"],
                     start_time=DATA_START, end_time="2026-08-07", freq="day")
    mkt.columns = ["$close", "$open", "$high", "$low", "$change", "$volume"]
    mkt = mkt.reset_index().set_index(["datetime", "instrument"]).sort_index()
    mkt = compute_indicators(mkt)

    # 金叉信号
    mkt["K_prev"], mkt["D_prev"] = mkt.groupby(level="instrument")["K"].shift(1), mkt.groupby(level="instrument")["D"].shift(1)
    mkt["DIF_prev"], mkt["DEA_prev"] = mkt.groupby(level="instrument")["DIF"].shift(1), mkt.groupby(level="instrument")["DEA"].shift(1)
    mkt["KDJ_cross"] = (mkt["K"] > mkt["D"]) & (mkt["K_prev"] <= mkt["D_prev"])
    mkt["MACD_cross"] = (mkt["DIF"] > mkt["DEA"]) & (mkt["DIF_prev"] <= mkt["DEA_prev"])
    print(f"      KDJ 金叉事件={int(mkt['KDJ_cross'].sum())}, MACD 金叉事件={int(mkt['MACD_cross'].sum())}", flush=True)

    # 未来收益
    g = mkt.groupby(level="instrument")
    for h in HORIZONS:
        mkt[f"FWD_{h}"] = g["$open"].shift(-1) / g["$close"].shift(-(h + 1)) - 1

    # ---- 2. 过滤 ----
    print("[2/4] Filters ...", flush=True)
    mask = build_filter_mask(mkt)
    eval_mask = ((mkt.index.get_level_values("datetime") >= pd.Timestamp(EVAL_START)) &
                 (mkt.index.get_level_values("datetime") <= pd.Timestamp(EVAL_END)))
    valid = mask & eval_mask
    print(f"      eval rows={valid.sum()}", flush=True)

    # ---- 3. 事件统计 ----
    print("[3/4] Comparing entry versions ...", flush=True)
    rows, yearly_rows = [], []
    for version, sig_col in [("A_KDJ提前买", "KDJ_cross"), ("B_MACD等确认", "MACD_cross")]:
        events = mkt.loc[valid & mkt[sig_col].to_numpy()]
        print(f"      {version}: 事件数={len(events)}", flush=True)
        for h in HORIZONS:
            s = events[f"FWD_{h}"].dropna()
            if len(s) < 50:
                continue
            yearly = events.groupby(events.index.get_level_values("datetime").year)[f"FWD_{h}"].agg(
                ["mean", lambda x: (x > 0).mean()])
            rows.append({
                "version": version, "horizon": h, "n": len(s),
                "mean_return": s.mean(), "median_return": s.median(),
                "win_rate": (s > 0).mean(),
                "annualized": s.mean() * (ANNUALIZATION_DAYS / h),
            })
            for y, yr in yearly.iterrows():
                yearly_rows.append({
                    "version": version, "horizon": h, "year": int(y),
                    "mean_return": yr["mean"], "win_rate": yr.iloc[1],
                })
    cmp = pd.DataFrame(rows)
    cmp.to_csv(out / "compare_summary.csv", index=False)
    yearly_df = pd.DataFrame(yearly_rows)
    yearly_df.to_csv(out / "yearly_summary.csv", index=False)

    # 额外：KDJ 金叉后 MACD 平均多少天金叉（先行时滞，向量化：按股 searchsorted）
    kdj_ev = mkt.loc[valid & mkt["KDJ_cross"].to_numpy()].index.to_frame().reset_index(drop=True)
    macd_ev = mkt.loc[valid & mkt["MACD_cross"].to_numpy()].index.to_frame().reset_index(drop=True)
    kdj_ev["dts"] = kdj_ev["datetime"].map(pd.Timestamp.toordinal)
    macd_ev["dts"] = macd_ev["datetime"].map(pd.Timestamp.toordinal)
    macd_by_inst = {inst: g["dts"].to_numpy() for inst, g in macd_ev.groupby("instrument")}
    lags = []
    for inst, g in kdj_ev.groupby("instrument"):
        fut = macd_by_inst.get(inst)
        if fut is None or len(fut) == 0:
            continue
        pos = np.searchsorted(fut, g["dts"].to_numpy(), side="right")
        for p, _ in zip(pos, range(len(g))):
            if p < len(fut):
                lags.append(fut[p] - g["dts"].iloc[_])
    lag_s = pd.Series(lags) if lags else pd.Series(dtype=float)

    # ---- 4. 报告 ----
    print("[4/4] Report ...", flush=True)
    lines = []
    lines.append("# KDJ vs MACD 金叉入场对比报告 v1\n")
    lines.append(f"- 母池: 沪深普通 A 股 {len(codes)} 只（剔北交所 {len(excluded)}）")
    lines.append(f"- 窗口: {EVAL_START} ~ {EVAL_END}（指标预热自 {DATA_START}）")
    lines.append(f"- 口径: T+1 开盘成交未来 h 日收益，绝对收益（未扣费、不用基准）\n")
    if not lag_s.empty:
        lines.append(f"KDJ 金叉 → MACD 金叉平均时滞: {lag_s.mean():.1f} 日（中位 {lag_s.median():.0f}，n={len(lag_s)}）\n")

    lines.append("### 提前买（KDJ金叉）vs 等确认（MACD金叉）")
    lines.append("| 版本 | h | n | 未来收益均值 | 中位数 | 胜率 | 年化 |")
    lines.append("|---|---|---|---|---|---|---|")
    for _, r in cmp.iterrows():
        lines.append(f"| {r['version']} | {r['horizon']} | {r['n']} | {r['mean_return']:+.4f} | "
                     f"{r['median_return']:+.4f} | {r['win_rate']:.1%} | {r['annualized']:+.1%} |")

    lines.append("\n### 分年度（h=5）")
    lines.append("| 版本 | 年份 | 收益均值 | 胜率 |")
    lines.append("|---|---|---|---|")
    for _, r in yearly_df[yearly_df["horizon"].eq(5)].iterrows():
        lines.append(f"| {r['version']} | {r['year']} | {r['mean_return']:+.4f} | {r['win_rate']:.1%} |")

    (out / "validation_report.txt").write_text("\n".join(lines), encoding="utf-8")
    meta = {
        "purpose": "KDJ vs MACD 金叉入场对比（提前买 vs 等确认）",
        "universe": f"沪深普通 A 股 {len(codes)} 只",
        "eval_window": [EVAL_START, EVAL_END],
        "signals": {"A_KDJ提前买": "K 上穿 D", "B_MACD等确认": "DIF 上穿 DEA"},
        "label": "Ref($open,-1)/(Ref($close,-(h+1))-1)",
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
    }
    (out / "methodology.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"      report -> {out / 'validation_report.txt'}", flush=True)
    print("DONE", flush=True)


if __name__ == "__main__":
    main()
