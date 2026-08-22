#!/usr/bin/env python3
"""Generate holdings + per-stock returns for two strategies with industry cap3.

Strategy A: four-factor (ep/bm/div/accruals) top-15 + cap3
Strategy B: five-factor (+g2) top-30 + cap3

Both use the same industry cap3 constraint (max 3 per SW L1).
Period: 2026-06-30 to latest available trading day.
"""

import json
from pathlib import Path

import numpy as np
import pandas as pd
import qlib
from qlib.config import REG_CN
from qlib.data import D

from load_financials_extended_v1 import load_financials_extended
from analyze_a_share_value_quality_level_factors_extension_v1 import (
    build_snapshot, ols_residual, composite_score, STYLE_DIR, QLIB_DIR,
)
from backtest_a_share_value_quality_monthly_dailygrid_v6 import build_daily_grid
from backtest_a_share_value_quality_monthly_sensitivity_v4 import load_amount_avg
from run_daily_signal_pipeline_v1 import st_codes_at, qlib_symbol, load_g2_series, g2_at

BT_START = pd.Timestamp("2026-06-30")
BENCHMARK = "SH000852"
BENCH_TS = "000852.SH"
PARTICIPATION = 0.05
ACCOUNT = 100_000_000
INDUSTRY_CAP = 3
ST_INTERVALS = Path("data/external/tushare/a_share_st_status_pit_v1/normalized/st_status_intervals.csv.gz")


def composite5_score(frame: pd.DataFrame) -> pd.Series:
    factors = ("ep", "bm", "div_yield", "accruals", "g2")
    ranks = pd.concat([frame[f].rank(method="first", pct=True) for f in factors], axis=1)
    n_factors = ranks.notna().sum(axis=1)
    composite = ranks.mean(axis=1)
    composite[n_factors < 4] = np.nan
    return composite


def select_topk_cap3(frame: pd.DataFrame, top_k: int, score_col: str) -> list[str]:
    """Greedy top-k with per-industry cap=3."""
    ranked = frame.dropna(subset=[score_col, "l1_code"]).nlargest(top_k * 5, score_col)
    ind_count = {}
    selected = []
    for _, r in ranked.iterrows():
        ind = r["l1_code"]
        if ind_count.get(ind, 0) >= INDUSTRY_CAP:
            continue
        ind_count[ind] = ind_count.get(ind, 0) + 1
        selected.append(r["ts_code"])
        if len(selected) >= top_k:
            break
    return selected


def build_signal(fin, fin_g2, grid_row, industry, size_daily, st, amount_avg, five_factor: bool, top_k: int):
    """Build top-k holdings for one rebalance date."""
    snap = build_snapshot(fin, grid_row, industry, size_daily)
    if snap.empty:
        return []
    frame = snap.set_index("ts_code")
    if five_factor and fin_g2 is not None:
        frame["g2"] = g2_at(fin_g2, grid_row.rebalance_date).reindex(frame.index)
        frame["composite"] = composite5_score(frame.reset_index()).set_axis(frame.index)
    else:
        frame["composite"] = composite_score(frame.reset_index()).set_axis(frame.index)

    frame.loc[frame.index.isin(st_codes_at(st, grid_row.asof_date)), "composite"] = np.nan
    notional = ACCOUNT // top_k
    avg = amount_avg.loc[grid_row.asof_date].reindex(frame.index).to_numpy(dtype=float) * 1000.0
    frame.loc[avg < notional / PARTICIPATION, "composite"] = np.nan
    valid = frame.dropna(subset=["composite", "log_size", "l1_code"])
    if len(valid) < 50:
        return []
    resid = ols_residual(valid["composite"], valid["l1_code"], valid["log_size"])
    frame["neutral_composite"] = resid.reindex(frame.index)
    return select_topk_cap3(frame.reset_index(), top_k, "neutral_composite")


def main():
    qlib.init(provider_uri=str(QLIB_DIR), region=REG_CN)
    calendar = pd.DatetimeIndex(pd.to_datetime(pd.read_csv(QLIB_DIR / "calendars" / "day.txt", header=None)[0]))
    end_date = calendar[-1]
    print(f"Period: {BT_START.date()} -> {end_date.date()}", flush=True)

    print("Loading data ...", flush=True)
    fin = load_financials_extended()
    fin_g2 = load_g2_series()
    grid, size_daily = build_daily_grid()
    grid = grid[grid["rebalance_date"] <= BT_START]
    grid_row = grid.iloc[-1]
    industry = pd.read_csv(STYLE_DIR / "industry_l1_effective_intervals.csv.gz", compression="gzip", dtype=str)
    industry["in_date"] = pd.to_datetime(industry["in_date"], errors="coerce")
    industry["out_date"] = pd.to_datetime(industry["out_date"], errors="coerce")
    st = pd.read_csv(ST_INTERVALS, compression="gzip", parse_dates=["start_date", "end_date"])
    amount_avg = load_amount_avg(sorted(size_daily["ts_code"].unique()), calendar)

    # Generate both signals
    print("Generating Strategy A (four-factor top-15 + cap3) ...", flush=True)
    hold_a = build_signal(fin, None, grid_row, industry, size_daily, st, amount_avg, False, 15)
    print(f"  Holdings: {len(hold_a)} stocks", flush=True)

    print("Generating Strategy B (five-factor top-30 + cap3) ...", flush=True)
    hold_b = build_signal(fin, fin_g2, grid_row, industry, size_daily, st, amount_avg, True, 30)
    print(f"  Holdings: {len(hold_b)} stocks", flush=True)

    # Load close prices
    all_codes = sorted(set(hold_a + hold_b + [BENCH_TS]))
    print(f"Loading close for {len(all_codes)} stocks ...", flush=True)
    qlib_codes = [qlib_symbol(c) for c in all_codes if c != BENCH_TS] + [BENCHMARK]
    raw = D.features(qlib_codes, ["$close"], start_time=BT_START, end_time=end_date, freq="day")
    close = raw["$close"].unstack(level="instrument")
    close = close.reindex(calendar[(calendar >= BT_START) & (calendar <= end_date)])
    new_cols = {BENCHMARK: BENCH_TS}
    for c in close.columns:
        if c != BENCHMARK:
            new_cols[c] = f"{c[2:]}.{c[:2]}"
    close = close.rename(columns=new_cols)

    out = Path("output/holdings_comparison_cap3_2026")
    out.mkdir(parents=True, exist_ok=True)

    for name, holdings, k in [("A_4factor_top15_cap3", hold_a, 15),
                               ("B_5factor_top30_cap3", hold_b, 30)]:
        print(f"\n{'='*60}")
        print(f"Strategy {name} ({k} stocks)")
        print(f"{'='*60}")

        # Per-stock P&L
        entry = close.loc[BT_START]
        exit_ = close.iloc[-1]
        rows = []
        for code in holdings:
            if code not in close.columns:
                continue
            p0, p1 = entry.get(code, np.nan), exit_.get(code, np.nan)
            if pd.notna(p0) and pd.notna(p1) and p0 > 0:
                ret = p1 / p0 - 1
                rows.append({"ts_code": code, "entry_close": float(p0), "exit_close": float(p1),
                             "return": float(ret), "weight": 1.0 / k,
                             "contribution": float(ret) * (1.0 / k)})
        pnl = pd.DataFrame(rows).sort_values("return", ascending=False)
        pnl["rank"] = range(1, len(pnl) + 1)

        # Add industry info
        cls = pd.read_csv("data/derived/a_share_stock_classification_v2/monthly_stock_classification.csv.gz",
                          compression="gzip")
        cls_jun = cls[cls["asof_date"].astype(str).str[:10] == "2026-06-30"].set_index("ts_code")
        pnl = pnl.merge(cls_jun[["l1_name", "security_name"]], left_on="ts_code", right_index=True, how="left")

        pnl.to_csv(out / f"strat_{name}_per_stock.csv", index=False)
        print(pnl[["rank", "ts_code", "security_name", "l1_name", "entry_close", "exit_close",
                    "return", "contribution"]].to_string(index=False))
        port_ret = pnl["contribution"].sum()
        bench_ret = close[BENCH_TS].iloc[-1] / close[BENCH_TS].loc[BT_START] - 1
        print(f"\nPortfolio return: {port_ret:+.2%}")
        print(f"Benchmark (CSI 1000): {bench_ret:+.2%}")
        print(f"Excess: {port_ret - bench_ret:+.2%}")

        # Industry distribution
        ind_dist = pnl["l1_name"].value_counts()
        print(f"\nIndustry distribution:")
        for ind, cnt in ind_dist.items():
            print(f"  {ind}: {cnt}/{k} ({cnt/k:.1%})")

        # Daily NAV
        rets = close.pct_change(fill_method=None)
        port_daily = rets[holdings].mean(axis=1)
        bench_daily = rets[BENCH_TS]
        nav = pd.DataFrame({
            "portfolio_return": port_daily,
            "benchmark_return": bench_daily,
            "excess_return": port_daily - bench_daily,
            "portfolio_nav": (1 + port_daily).cumprod(),
            "benchmark_nav": (1 + bench_daily).cumprod(),
        })
        nav.to_csv(out / f"strat_{name}_daily_nav.csv")

    print(f"\nOutput: {out}/", flush=True)


if __name__ == "__main__":
    main()
