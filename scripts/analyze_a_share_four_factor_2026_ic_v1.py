#!/usr/bin/env python3
"""Monthly IC of the mainline four-factor composite over a configurable window.

Answers: is the underperformance cyclical (IC oscillates with market state,
value defends in drawdowns) or structural failure (IC persistently ~0/negative)?
Uses the frozen mainline functions (build_snapshot / composite_score /
ols_residual / load_financials_extended) over a month-end grid.

Label: open-to-open 40d, market-adjusted by SH000852 open-to-open (approx).

Usage: --start 2023-01-01 --output-dir output/analysis_static/a_share_four_factor_2023_2026_ic_v1
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

from load_financials_extended_v1 import load_financials_extended
from analyze_a_share_value_quality_level_factors_extension_v1 import (
    build_snapshot,
    ols_residual,
    composite_score,
    qlib_symbol,
    STYLE_DIR,
    QLIB_DIR,
)
from backtest_a_share_value_quality_monthly_dailygrid_v6 import build_daily_grid

HORIZON = 40


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--start", type=str, default="2023-01-01",
                        help="窗口起点 YYYY-MM-DD（含）")
    parser.add_argument("--output-dir", type=Path,
                        default=Path("output/analysis_static/a_share_four_factor_2023_2026_ic_v1"))
    args = parser.parse_args()
    start = pd.Timestamp(args.start)
    out = args.output_dir
    if out.exists() and any(out.iterdir()):
        raise FileExistsError(out)
    out.mkdir(parents=True, exist_ok=True)

    qlib.init(provider_uri=str(QLIB_DIR), region=REG_CN)
    calendar = pd.DatetimeIndex(pd.to_datetime(pd.read_csv(QLIB_DIR / "calendars" / "day.txt", header=None)[0]))

    fin = load_financials_extended()
    grid, size_daily = build_daily_grid()
    grid = grid[grid["rebalance_date"] >= start].reset_index(drop=True)
    print(f"months in window: {len(grid)} {grid['rebalance_date'].min().date()} .. {grid['rebalance_date'].max().date()}", flush=True)

    industry = pd.read_csv(STYLE_DIR / "industry_l1_effective_intervals.csv.gz", compression="gzip", dtype=str)
    industry["in_date"] = pd.to_datetime(industry["in_date"], errors="coerce")
    industry["out_date"] = pd.to_datetime(industry["out_date"], errors="coerce")

    snapshots = {}
    for _, row in grid.iterrows():
        snap = build_snapshot(fin, row, industry, size_daily)
        if snap.empty:
            continue
        frame = snap.copy()
        frame["composite"] = composite_score(frame)
        valid = frame.dropna(subset=["composite", "log_size", "l1_code"])
        if len(valid) < 50:
            continue
        resid = ols_residual(valid["composite"], valid["l1_code"], valid["log_size"])
        frame["neutral_composite"] = resid.reindex(frame.index)
        snapshots[row.rebalance_date] = frame
    print(f"valid months: {len(snapshots)}", flush=True)

    # open-to-open 40d labels + benchmark (SH000852) 40d open-to-open
    months = sorted(snapshots)
    codes = sorted({qlib_symbol(c) for f in snapshots.values() for c in f["ts_code"]})
    codes.append("SH000852")
    start = months[0]
    end = calendar[min(calendar.get_loc(months[-1]) + HORIZON, len(calendar) - 1)]
    open_frame = (
        D.features(codes, ["$open"], start_time=start, end_time=end, freq="day")
        .rename(columns={"$open": "open"})
        .reset_index()
    )
    open_frame["ts_code"] = open_frame["instrument"].map(
        lambda s: "SH000852" if s == "SH000852" else f"{s[2:]}.{s[:2]}")
    open_pivot = open_frame.pivot(index="datetime", columns="ts_code", values="open").reindex(calendar)
    bench_open = open_pivot["SH000852"]

    rows = []
    for date, frame in snapshots.items():
        pos = calendar.get_loc(date)
        if pos + HORIZON >= len(calendar):
            continue
        entry = open_pivot.loc[date].reindex(frame["ts_code"]).to_numpy(dtype=float)
        exit_ = open_pivot.iloc[pos + HORIZON].reindex(frame["ts_code"]).to_numpy(dtype=float)
        label = exit_ / entry - 1.0
        label[(entry <= 0) | (exit_ <= 0) | ~np.isfinite(label)] = np.nan
        bench_ret = float(bench_open.iloc[pos + HORIZON] / bench_open.iloc[pos] - 1.0)
        sample = frame.assign(label=label - bench_ret).dropna(subset=["neutral_composite", "label", "l1_code"])
        if len(sample) < 100:
            continue
        ic = sample["neutral_composite"].corr(sample["label"], method="spearman")
        rows.append({"rebalance_date": date, "n": len(sample), "market_adj_40d_rank_ic": ic,
                     "bench_40d": bench_ret})
    result = pd.DataFrame(rows)
    result.to_csv(out / "monthly_ic.csv", index=False)
    print("\n月度 4 因子 composite 中性化 40d 市场调整 RankIC:")
    print(result.to_string(index=False))
    mean_ic = result["market_adj_40d_rank_ic"].mean()
    positive = (result["market_adj_40d_rank_ic"] > 0).mean()
    corr_ic_bench = result["market_adj_40d_rank_ic"].corr(result["bench_40d"])
    print(f"\n均值 IC: {mean_ic:.4f} | IC>0 月占比: {positive:.2%} | 月数: {len(result)}")
    print(f"IC × 市场收益 相关性: {corr_ic_bench:.3f}（负 = 价值在跌市防御/涨市逆风 = 逆周期暴露）")

    # 分年度汇总
    result["year"] = result["rebalance_date"].dt.year
    yearly = result.groupby("year").agg(
        n=("rebalance_date", "count"),
        mean_ic=("market_adj_40d_rank_ic", "mean"),
        positive_ratio=("market_adj_40d_rank_ic", lambda s: (s > 0).mean()),
    ).reset_index()
    print("\n分年度:")
    print(yearly.to_string(index=False))

    (out / "decision.json").write_text(json.dumps({
        "mean_40d_ic": float(mean_ic) if pd.notna(mean_ic) else None,
        "positive_month_ratio": float(positive),
        "corr_ic_vs_market": float(corr_ic_bench) if pd.notna(corr_ic_bench) else None,
        "n_months": int(len(result)),
        "window_start": start.strftime("%Y-%m-%d"),
        "interpretation": {
            "cyclical": "IC 随市场状态正负切换（跌市为正/涨市为负）且长期均值>0 -> 周期性风格逆风，非失效",
            "structural": "IC 持续趋 0 或长期为负 -> 结构性失效",
            "corr_negative_supports_cyclical": "IC×市场收益 负相关 = 价值在跌市防御",
        },
        "months": [{"rebalance_date": r["rebalance_date"].strftime("%Y-%m-%d"),
                    "n": int(r["n"]),
                    "market_adj_40d_rank_ic": float(r["market_adj_40d_rank_ic"]),
                    "bench_40d": float(r["bench_40d"])}
                   for _, r in result.iterrows()],
    }, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
