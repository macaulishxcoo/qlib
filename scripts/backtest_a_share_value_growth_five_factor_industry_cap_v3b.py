#!/usr/bin/env python3
"""Five-factor + industry-cap backtest v3b (custom engine).

v3 failed because masking the signal panel breaks TopkDropoutStrategy's
dropout mechanism.  v3b builds monthly holdings directly (greedy cap-aware
selection) and reconstructs daily portfolio returns from qlib $close,
bypassing TopkDropoutStrategy entirely.  This matches the v2 attribution
script's reconstruction approach.

Four arms: top15_free / top15_cap3 / top30_free / top30_cap3.
Protocol: research/protocols/a_share_value_growth_five_factor_industry_cap_protocol_v3.md
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
    STYLE_DIR,
    QLIB_DIR,
)
from backtest_a_share_value_quality_monthly_dailygrid_v6 import build_daily_grid
from backtest_a_share_value_quality_monthly_sensitivity_v4 import load_amount_avg
from run_daily_signal_pipeline_v1 import st_codes_at, qlib_symbol, load_g2_series, g2_at

ACCOUNT = 100_000_000
BENCHMARK = "SH000852"
BENCH_TS = "000852.SH"
ANNUALIZATION_DAYS = 238
COST_SCENARIOS = {
    "base": {"open_cost": 0.0005, "close_cost": 0.0015},
    "stress": {"open_cost": 0.0010, "close_cost": 0.0030},
}
STAGES = {
    "development": (pd.Timestamp("2016-01-01"), pd.Timestamp("2019-12-31")),
    "confirmation": (pd.Timestamp("2020-01-01"), pd.Timestamp("2022-12-31")),
    "holdout": (pd.Timestamp("2023-01-01"), pd.Timestamp("2025-06-30")),
    "new_coverage": (pd.Timestamp("2025-07-01"), pd.Timestamp("2026-06-30")),
}
BT_START = pd.Timestamp("2016-01-01")
BT_END = pd.Timestamp("2026-06-30")
ST_INTERVALS = Path("data/external/tushare/a_share_st_status_pit_v1/normalized/st_status_intervals.csv.gz")
ARMS = [
    ("top15_free", 15, None),
    ("top15_cap3", 15, 3),
    ("top30_free", 30, None),
    ("top30_cap3", 30, 3),
]


def composite5_score(frame: pd.DataFrame) -> pd.Series:
    factors = ("ep", "bm", "div_yield", "accruals", "g2")
    ranks = pd.concat([frame[f].rank(method="first", pct=True) for f in factors], axis=1)
    n_factors = ranks.notna().sum(axis=1)
    composite = ranks.mean(axis=1)
    composite[n_factors < 4] = np.nan
    return composite


def build_snapshots(fin, fin_g2, grid, industry, size_daily, st, amount_avg) -> dict:
    snapshots = {}
    for _, row in grid.iterrows():
        snap = build_snapshot(fin, row, industry, size_daily)
        if snap.empty:
            continue
        frame = snap.set_index("ts_code")
        frame["g2"] = g2_at(fin_g2, row.rebalance_date).reindex(frame.index)
        frame["composite5"] = composite5_score(frame.reset_index()).set_axis(frame.index)
        frame.loc[frame.index.isin(st_codes_at(st, row.asof_date)), "composite5"] = np.nan
        avg = amount_avg.loc[row.asof_date].reindex(frame.index).to_numpy(dtype=float) * 1000.0
        min_amount_15 = (ACCOUNT // 15) / 0.05
        frame.loc[avg < min_amount_15, "composite5"] = np.nan
        valid = frame.dropna(subset=["composite5", "log_size", "l1_code"])
        if len(valid) < 50:
            continue
        resid = ols_residual(valid["composite5"], valid["l1_code"], valid["log_size"])
        frame["neutral_composite"] = resid.reindex(frame.index)
        snapshots[row.rebalance_date] = frame.reset_index()
    return snapshots


def select_holdings(frame: pd.DataFrame, top_k: int, cap: int | None) -> list[str]:
    """Greedy top-k with optional per-industry cap. Returns ts_code list."""
    ranked = frame.dropna(subset=["neutral_composite"]).sort_values("neutral_composite", ascending=False)
    if cap is None:
        return ranked.head(top_k)["ts_code"].tolist()
    ind_count = {}
    selected = []
    for _, r in ranked.iterrows():
        ind = r["l1_code"]
        if pd.isna(ind):
            ind = "UNKNOWN"
        if ind_count.get(ind, 0) >= cap:
            continue
        ind_count[ind] = ind_count.get(ind, 0) + 1
        selected.append(r["ts_code"])
        if len(selected) >= top_k:
            break
    return selected


def load_close_wide(cal: pd.DatetimeIndex, all_codes: list[str]) -> pd.DataFrame:
    qlib_codes = [qlib_symbol(c) for c in all_codes] + [BENCHMARK]
    frames = []
    for year in range(2015, 2027):
        frames.append(D.features(qlib_codes, ["$close"], start_time=f"{year}-01-01", end_time=f"{year}-12-31", freq="day"))
    raw = pd.concat(frames)["$close"].unstack(level="instrument")
    raw = raw.reindex(cal)
    # Convert stock codes SH600000 -> 600000.SH, keep BENCHMARK as-is
    new_cols = {}
    for c in raw.columns:
        if c == BENCHMARK:
            new_cols[c] = BENCH_TS  # use ts_code format for benchmark too
        else:
            new_cols[c] = f"{c[2:]}.{c[:2]}"
    raw = raw.rename(columns=new_cols)
    return raw


def reconstruct_returns(holdings: dict, close_wide: pd.DataFrame, cal: pd.DatetimeIndex,
                         costs: dict) -> pd.DataFrame:
    """Reconstruct daily portfolio returns with T+1 open execution + costs."""
    rets = close_wide.pct_change(fill_method=None)
    bench = rets[BENCH_TS]
    rdates = sorted(holdings.keys())
    rows = []
    cur_hold = None
    prev_hold = None
    for t in cal:
        if t > BT_END:
            break
        prior = [d for d in rdates if d <= t]
        new_hold = holdings[prior[-1]] if prior else None
        is_rebal = new_hold is not None and (cur_hold is None or new_hold != cur_hold)
        if is_rebal:
            # Turnover cost on rebalance day
            if cur_hold is not None and prev_hold is not None:
                old_set = set(prev_hold)
                new_set = set(new_hold)
                turnover = len(new_set - old_set) + len(old_set - new_set)
                turnover_ratio = turnover / (2 * max(len(new_hold), 1))
            else:
                turnover_ratio = 1.0
            cur_hold = new_hold
            prev_hold = new_hold
        else:
            turnover_ratio = 0.0
        if cur_hold is None or t not in rets.index:
            continue
        port_ret = float(np.nanmean(rets.loc[t].reindex(cur_hold).to_numpy(dtype=float)))
        bench_ret = float(bench.loc[t]) if pd.notna(bench.loc[t]) else np.nan
        cost = turnover_ratio * (costs["open_cost"] + costs["close_cost"])
        rows.append({
            "date": t,
            "return": port_ret - cost,
            "bench": bench_ret,
            "cost": cost,
            "turnover": turnover_ratio,
        })
    return pd.DataFrame(rows).set_index("date")


def risk_metrics(returns: pd.DataFrame, stage: str, start, end) -> dict:
    sample = returns.loc[start:end]
    if sample.empty:
        return {}
    excess = sample["return"] - sample["bench"] - sample["cost"]
    ann_ret = float(excess.mean() * ANNUALIZATION_DAYS)
    ir = float(excess.mean() / excess.std() * np.sqrt(ANNUALIZATION_DAYS)) if excess.std() > 0 else 0
    cum = (1 + excess).cumprod()
    mdd = float(cum.div(cum.cummax()).min() - 1)
    return {"stage": stage, "trading_days": len(sample),
            "net_excess_annualized_return": ann_ret, "net_excess_ir": ir,
            "net_excess_max_drawdown": mdd}


def measure_concentration(snapshots: dict, top_k: int, cap: int | None) -> dict:
    top1_counts, top3_counts = [], []
    for date, frame in snapshots.items():
        sel_codes = select_holdings(frame, top_k, cap)
        if not sel_codes:
            continue
        sel_frame = frame[frame["ts_code"].isin(sel_codes)]
        counts = sel_frame["l1_code"].value_counts()
        top1_counts.append(counts.iloc[0] / len(sel_codes))
        top3_counts.append(counts.head(3).sum() / len(sel_codes))
    return {
        "avg_top1_industry_share": float(np.mean(top1_counts)) if top1_counts else np.nan,
        "avg_top3_industry_share": float(np.mean(top3_counts)) if top3_counts else 0,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path,
                        default=Path("output/analysis_fundamental/a_share_value_growth_five_factor_industry_cap_v3b"))
    args = parser.parse_args()
    out = args.output_dir
    if out.exists() and any(out.iterdir()):
        raise FileExistsError(f"Refusing to overwrite: {out}")
    out.mkdir(parents=True, exist_ok=True)

    qlib.init(provider_uri=str(QLIB_DIR), region=REG_CN)
    calendar = pd.DatetimeIndex(pd.to_datetime(pd.read_csv(QLIB_DIR / "calendars" / "day.txt", header=None)[0]))

    print("[1/4] Loading data + building shared snapshots ...", flush=True)
    fin = load_financials_extended()
    fin_g2 = load_g2_series()
    grid, size_daily = build_daily_grid()
    grid = grid[(grid["rebalance_date"] >= BT_START) & (grid["rebalance_date"] <= BT_END)]
    industry = pd.read_csv(STYLE_DIR / "industry_l1_effective_intervals.csv.gz", compression="gzip", dtype=str)
    industry["in_date"] = pd.to_datetime(industry["in_date"], errors="coerce")
    industry["out_date"] = pd.to_datetime(industry["out_date"], errors="coerce")
    st = pd.read_csv(ST_INTERVALS, compression="gzip", parse_dates=["start_date", "end_date"])
    universe_codes = sorted(size_daily["ts_code"].unique())
    amount_avg = load_amount_avg(universe_codes, calendar)
    snapshots = build_snapshots(fin, fin_g2, grid, industry, size_daily, st, amount_avg)
    print(f"      valid months={len(snapshots)}", flush=True)

    # Pre-load close prices for all stocks ever in any arm's holdings
    print("[2/4] Loading close prices ...", flush=True)
    all_held = set()
    for date, frame in snapshots.items():
        ranked = frame.dropna(subset=["neutral_composite"]).nlargest(50, "neutral_composite")
        all_held.update(ranked["ts_code"].tolist())
    all_held.add(BENCH_TS)
    print(f"      {len(all_held)} unique stocks + benchmark", flush=True)
    close_wide = load_close_wide(calendar, sorted(all_held))
    print(f"      close matrix: {close_wide.shape}", flush=True)

    print(f"[3/4] Running {len(ARMS)} arms ...", flush=True)
    all_bt, all_conc = [], {}
    for name, k, cap in ARMS:
        print(f"  --- {name} (K={k}, cap={cap}) ---", flush=True)
        holdings = {}
        for date, frame in snapshots.items():
            codes = select_holdings(frame, k, cap)
            if codes:
                holdings[date] = codes
        all_conc[name] = measure_concentration(snapshots, k, cap)
        print(f"      months={len(holdings)}, conc1={all_conc[name]['avg_top1_industry_share']:.1%}", flush=True)

        bt_rows = []
        for scenario, costs in COST_SCENARIOS.items():
            returns = reconstruct_returns(holdings, close_wide, calendar, costs)
            for stage, (s0, s1) in list(STAGES.items()) + [("full", (BT_START, BT_END))]:
                m = risk_metrics(returns, stage, s0, s1)
                if m:
                    m["arm"] = name
                    m["cost_scenario"] = scenario
                    bt_rows.append(m)
            hol = next((r for r in bt_rows if r["stage"] == "holdout" and r["cost_scenario"] == scenario), None)
            if hol:
                print(f"      [{scenario}] holdout={hol['net_excess_annualized_return']:.4f} "
                      f"IR={hol['net_excess_ir']:.3f} MDD={hol['net_excess_max_drawdown']:.4f}", flush=True)
        all_bt.extend(bt_rows)

    bt = pd.DataFrame(all_bt)
    bt.to_csv(out / "backtest_summary.csv", index=False)
    conc_df = pd.DataFrame([{"arm": name, **v} for name, v in all_conc.items()])
    conc_df.to_csv(out / "industry_concentration.csv", index=False)

    print("\n行业集中度:")
    print(conc_df.to_string(index=False))
    print("\n四臂对照（stress）:")
    piv = bt[bt["cost_scenario"] == "stress"].pivot_table(
        index="stage", columns="arm",
        values=["net_excess_annualized_return", "net_excess_ir", "net_excess_max_drawdown"])
    print(piv.round(4).to_string())

    print("[4/4] Decision ...", flush=True)
    def pick(arm, stage, col):
        row = bt[(bt["arm"] == arm) & (bt["stage"] == stage) & (bt["cost_scenario"] == "stress")]
        return float(row[col].iloc[0]) if len(row) else np.nan

    decision = {
        "top15_cap3_vs_free_holdout_ir_delta": pick("top15_cap3", "holdout", "net_excess_ir") - pick("top15_free", "holdout", "net_excess_ir"),
        "top15_cap3_vs_free_full_ir_delta": pick("top15_cap3", "full", "net_excess_ir") - pick("top15_free", "full", "net_excess_ir"),
        "top15_cap3_concentration": all_conc.get("top15_cap3", {}),
        "top15_free_concentration": all_conc.get("top15_free", {}),
        "top15_cap3_vs_top30_free_full_ir": pick("top15_cap3", "full", "net_excess_ir") - pick("top30_free", "full", "net_excess_ir"),
        "top30_cap3_vs_top30_free_full_ir_delta": pick("top30_cap3", "full", "net_excess_ir") - pick("top30_free", "full", "net_excess_ir"),
    }
    (out / "decision.json").write_text(json.dumps(decision, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(decision, ensure_ascii=False, indent=2), flush=True)


if __name__ == "__main__":
    main()
