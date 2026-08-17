#!/usr/bin/env python3
"""PEAD (Post-Earnings Announcement Drift) minimal experiment (protocol v1).

Tests whether A-share stocks drift in the direction of their earnings
announcement after the official `ann_date`.  For each event:
  - entry = open price on ann_date (or next trading day if non-trading)
  - exit  = open price H trading days later (H = 5, 10, 20)
  - excess = stock return - SH000852 return over same window

Groups: All / Positive (netprofit_yoy > 0) / Negative (netprofit_yoy < 0).
Also tests momentum orthogonality: split event stocks by pre-event 20-day
return into quintiles; if post-event excess varies monotonically with
pre-event momentum, the "excess" is momentum exposure, not event info.

Protocol: research/protocols/a_share_pead_protocol_v1.md
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
import pandas as pd
import qlib
from qlib.config import REG_CN
from qlib.data import D

QLIB_DIR = Path.home() / ".qlib/qlib_data/cn_data_2026"
FINA_PATH = Path("data/external/tushare/a_share_financial_pit_v1/normalized/fina_indicator.csv.gz")
BENCHMARK = "SH000852"
HORIZONS = [5, 10, 20]
WINDOW_START = "2022-01-01"
WINDOW_END = "2026-07-31"
OUTPUT_DIR = Path("output/analysis_static/a_share_pead_v1")


def qlib_symbol(code: str) -> str:
    number, suffix = code.split(".")
    return f"{suffix}{number}"


def load_events() -> pd.DataFrame:
    """Load fina_indicator, deduplicate to first ann_date per (ts_code, end_date)."""
    df = pd.read_csv(FINA_PATH, compression="gzip",
                     usecols=["ts_code", "ann_date", "end_date", "netprofit_yoy"])
    df = df.dropna(subset=["ann_date", "ts_code"])
    df["ann_date"] = pd.to_datetime(df["ann_date"].astype(int).astype(str), format="%Y%m%d")
    df = df[(df["ann_date"] >= WINDOW_START) & (df["ann_date"] <= WINDOW_END)]
    # Deduplicate: same (ts_code, end_date) -> keep earliest ann_date (first announcement)
    df = df.sort_values(["ts_code", "end_date", "ann_date"]).drop_duplicates(["ts_code", "end_date"], keep="first")
    # Earnings direction
    df["direction"] = "unknown"
    df.loc[df["netprofit_yoy"] > 0, "direction"] = "positive"
    df.loc[df["netprofit_yoy"] < 0, "direction"] = "negative"
    df["year"] = df["ann_date"].dt.year
    return df.reset_index(drop=True)


def load_prices(codes: list[str], cal: pd.DatetimeIndex) -> tuple[pd.DataFrame, pd.Series]:
    """Load open prices for event stocks + benchmark close, aligned to calendar."""
    qlib_codes = [qlib_symbol(c) for c in codes] + [BENCHMARK]
    frames = []
    for year in range(2021, 2027):
        df = D.features(qlib_codes, ["$open", "$close"], start_time=f"{year}-01-01", end_time=f"{year}-12-31", freq="day")
        frames.append(df)
    raw = pd.concat(frames)
    open_wide = raw["$open"].unstack(level="instrument")
    open_wide.columns = [f"{c[2:]}.{c[:2]}" if c != BENCHMARK else BENCHMARK for c in open_wide.columns]
    open_wide = open_wide.reindex(cal)

    bench_close = raw.xs(BENCHMARK, level="instrument")["$close"].reindex(cal)

    return open_wide, bench_close


def compute_excess(events: pd.DataFrame, open_wide: pd.DataFrame,
                   bench_close: pd.Series, cal: pd.DatetimeIndex) -> pd.DataFrame:
    """For each event, compute H-day excess return for each horizon."""
    cal_list = list(cal)
    cal_pos = {d: i for i, d in enumerate(cal_list)}

    results = []
    for _, ev in events.iterrows():
        ts_code = ev["ts_code"]
        ann_date = ev["ann_date"]

        # Snap ann_date to next trading day if not a trading day
        if ann_date not in cal_pos:
            future = [d for d in cal_list if d >= ann_date]
            if not future:
                continue
            entry_date = future[0]
        else:
            entry_date = ann_date

        entry_pos = cal_pos[entry_date]

        if ts_code not in open_wide.columns:
            continue
        entry_open = open_wide.loc[entry_date, ts_code] if entry_date in open_wide.index else np.nan
        if pd.isna(entry_open) or entry_open <= 0:
            continue

        for h in HORIZONS:
            exit_pos = entry_pos + h
            if exit_pos >= len(cal_list):
                continue
            exit_date = cal_list[exit_pos]
            exit_open = open_wide.loc[exit_date, ts_code] if exit_date in open_wide.index else np.nan
            if pd.isna(exit_open) or exit_open <= 0:
                continue

            stock_ret = exit_open / entry_open - 1.0

            # Benchmark return over same window
            bench_entry = bench_close.iloc[entry_pos] if entry_pos < len(bench_close) else np.nan
            bench_exit = bench_close.iloc[exit_pos] if exit_pos < len(bench_close) else np.nan
            if pd.isna(bench_entry) or pd.isna(bench_exit) or bench_entry <= 0:
                continue
            bench_ret = bench_exit / bench_entry - 1.0

            excess = stock_ret - bench_ret

            results.append({
                "ts_code": ts_code, "ann_date": entry_date, "end_date": ev["end_date"],
                "direction": ev["direction"], "netprofit_yoy": ev["netprofit_yoy"],
                "year": ev["year"], "horizon": h,
                "stock_ret": stock_ret, "bench_ret": bench_ret, "excess": excess,
            })

    return pd.DataFrame(results)


def momentum_orthogonality(events: pd.DataFrame, open_wide: pd.DataFrame,
                           cal: pd.DatetimeIndex) -> pd.DataFrame:
    """Split events by pre-announcement 20-day return; check if post-ann excess
    varies with pre-ann momentum (=> momentum artifact)."""
    cal_list = list(cal)
    cal_pos = {d: i for i, d in enumerate(cal_list)}

    rows = []
    for _, ev in events.iterrows():
        ts_code = ev["ts_code"]
        ann_date = ev["ann_date"]
        if ann_date not in cal_pos:
            future = [d for d in cal_list if d >= ann_date]
            if not future:
                continue
            entry_date = future[0]
        else:
            entry_date = ann_date
        entry_pos = cal_pos[entry_date]
        pre_pos = entry_pos - 20
        if pre_pos < 0 or ts_code not in open_wide.columns:
            continue
        pre_date = cal_list[pre_pos]
        p0 = open_wide.loc[pre_date, ts_code] if pre_date in open_wide.index else np.nan
        p1 = open_wide.loc[entry_date, ts_code] if entry_date in open_wide.index else np.nan
        if pd.isna(p0) or pd.isna(p1) or p0 <= 0:
            continue
        pre_mom = p1 / p0 - 1.0
        rows.append({"ts_code": ts_code, "ann_date": entry_date, "pre_mom_20d": pre_mom,
                     "direction": ev["direction"]})

    if not rows:
        return pd.DataFrame()

    mom_df = pd.DataFrame(rows)
    # 5 quintiles by pre-momentum
    mom_df["mom_q"] = pd.qcut(mom_df["pre_mom_20d"].rank(method="first"), 5, labels=False) + 1

    # Merge with excess (h=10 as representative)
    return mom_df


def t_test(series: pd.Series) -> dict:
    """One-sample t-test: is the mean significantly different from 0?"""
    s = series.dropna()
    if len(s) < 2:
        return {"n": len(s), "mean": np.nan, "std": np.nan, "t": np.nan}
    mean = float(s.mean())
    std = float(s.std(ddof=1))
    t = mean / std * np.sqrt(len(s)) if std > 0 else np.nan
    return {"n": len(s), "mean": mean, "std": std, "t": t}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, default=OUTPUT_DIR)
    args = parser.parse_args()
    out = args.output_dir
    if out.exists() and any(out.iterdir()):
        raise FileExistsError(f"Refusing to overwrite: {out}")
    out.mkdir(parents=True, exist_ok=True)

    qlib.init(provider_uri=str(QLIB_DIR), region=REG_CN)
    cal = pd.DatetimeIndex(pd.to_datetime(pd.read_csv(QLIB_DIR / "calendars" / "day.txt", header=None)[0]))

    print("[1/4] Loading events ...", flush=True)
    events = load_events()
    print(f"      {len(events):,} events ({events.ts_code.nunique():,} stocks)")
    print(f"      direction: {events.direction.value_counts().to_dict()}", flush=True)

    print("[2/4] Loading prices ...", flush=True)
    event_codes = sorted(events["ts_code"].unique())
    open_wide, bench_close = load_prices(event_codes, cal)
    print(f"      open prices: {open_wide.shape}, benchmark: {len(bench_close)} days", flush=True)

    print("[3/4] Computing excess returns ...", flush=True)
    excess_df = compute_excess(events, open_wide, bench_close, cal)
    print(f"      {len(excess_df):,} event-horizon observations", flush=True)

    # --- By horizon x direction ---
    print("[4/4] Analyzing ...", flush=True)
    by_horizon = []
    for h in HORIZONS:
        for direction in ["all", "positive", "negative"]:
            subset = excess_df[(excess_df["horizon"] == h)]
            if direction != "all":
                subset = subset[subset["direction"] == direction]
            stats = t_test(subset["excess"])
            by_horizon.append({
                "horizon": h, "direction": direction,
                "n": stats["n"], "mean_excess": stats["mean"],
                "std": stats["std"], "t": stats["t"],
            })
    by_horizon_df = pd.DataFrame(by_horizon)
    by_horizon_df.to_csv(out / "pead_excess_by_horizon.csv", index=False)
    print(by_horizon_df.to_string(index=False), flush=True)

    # --- Yearly breakdown (h=10) ---
    yearly = []
    for year in sorted(excess_df["year"].unique()):
        for direction in ["all", "positive", "negative"]:
            subset = excess_df[(excess_df["year"] == year) & (excess_df["horizon"] == 10)]
            if direction != "all":
                subset = subset[subset["direction"] == direction]
            stats = t_test(subset["excess"])
            yearly.append({
                "year": year, "direction": direction,
                "n": stats["n"], "mean_excess": stats["mean"], "t": stats["t"],
            })
    yearly_df = pd.DataFrame(yearly)
    yearly_df.to_csv(out / "pead_yearly_breakdown.csv", index=False)

    # --- Momentum orthogonality ---
    mom_df = momentum_orthogonality(events, open_wide, cal)
    if not mom_df.empty:
        # Merge with h=10 excess
        h10 = excess_df[excess_df["horizon"] == 10][["ts_code", "ann_date", "excess"]].copy()
        h10["ann_date"] = pd.to_datetime(h10["ann_date"])
        mom_df["ann_date"] = pd.to_datetime(mom_df["ann_date"])
        merged = mom_df.merge(h10, on=["ts_code", "ann_date"], how="inner")
        mom_results = merged.groupby("mom_q")["excess"].agg(["mean", "count"]).reset_index()
        mom_results.columns = ["momentum_quintile", "mean_excess_h10", "n"]
        mom_results.to_csv(out / "pead_momentum_orthogonality.csv", index=False)
        print("\nMomentum orthogonality (h=10):")
        print(mom_results.to_string(index=False), flush=True)

        # Check monotonicity: does excess increase with momentum quintile?
        q1 = mom_results.iloc[0]["mean_excess_h10"]
        q5 = mom_results.iloc[-1]["mean_excess_h10"]
        mom_spread = q5 - q1
    else:
        mom_results = pd.DataFrame()
        mom_spread = np.nan

    # --- Decision ---
    # Check: All group h=10 t-value
    all_h10 = by_horizon_df[(by_horizon_df["horizon"] == 10) & (by_horizon_df["direction"] == "all")].iloc[0]
    pos_h10 = by_horizon_df[(by_horizon_df["horizon"] == 10) & (by_horizon_df["direction"] == "positive")].iloc[0]
    neg_h10 = by_horizon_df[(by_horizon_df["horizon"] == 10) & (by_horizon_df["direction"] == "negative")].iloc[0]

    significant = abs(all_h10["t"]) > 2
    directions_opposite = (pos_h10["mean_excess"] > 0 and neg_h10["mean_excess"] < 0) or \
                          (pos_h10["mean_excess"] < 0 and neg_h10["mean_excess"] > 0)

    if not significant:
        decision = "pead_not_supported"
    elif not directions_opposite:
        decision = "pead_direction_unclear"
    elif not np.isnan(mom_spread) and abs(mom_spread) > 0.02 and \
         ((mom_results.iloc[0]["mean_excess_h10"] < 0 and mom_results.iloc[-1]["mean_excess_h10"] > 0) or
          (mom_results.iloc[0]["mean_excess_h10"] > 0 and mom_results.iloc[-1]["mean_excess_h10"] < 0)):
        decision = "pead_is_momentum_artifact"
    else:
        decision = "pead_viable"

    decision_json = {
        "decision": decision,
        "all_h10_mean_excess": all_h10["mean_excess"], "all_h10_t": all_h10["t"], "all_h10_n": int(all_h10["n"]),
        "positive_h10_mean_excess": pos_h10["mean_excess"], "positive_h10_t": pos_h10["t"],
        "negative_h10_mean_excess": neg_h10["mean_excess"], "negative_h10_t": neg_h10["t"],
        "directions_opposite": bool(directions_opposite),
        "momentum_spread_q5_q1": mom_spread,
    }
    (out / "decision.json").write_text(json.dumps(decision_json, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    lines = [
        "PEAD（正式财报公告后漂移）实验 v1",
        "=" * 64,
        f"窗口 {WINDOW_START} ~ {WINDOW_END}，事件 {len(events):,} 个",
        f"正向公告 {events.direction.eq('positive').sum():,} / 负向 {events.direction.eq('negative').sum():,}",
        "",
        "分组超额（市场调整，相对 SH000852）：",
        by_horizon_df.to_string(index=False),
        "",
        "分年度超额（h=10）：",
        yearly_df.to_string(index=False),
        "",
    ]
    if not mom_results.empty:
        lines += [
            "动量正交性检验（h=10，按公告前20日收益分5组）：",
            mom_results.to_string(index=False),
            f"Q5-Q1 spread = {mom_spread:.4f}",
            "",
        ]
    lines += [
        f"判定：{decision}",
        "",
        "判定规则：|t|>2 且正负方向相反 -> viable；|t|<2 -> not_supported；",
        "  方向相同 -> direction_unclear；动量单调 -> momentum_artifact",
    ]
    (out / "strategy_report.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("\n" + "\n".join(lines))


if __name__ == "__main__":
    main()
