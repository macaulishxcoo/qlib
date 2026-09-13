#!/usr/bin/env python3
"""Five-factor + industry-cap sensitivity (protocol v3).

Four arms in one data environment:
  top15_free   : five-factor top-15, no industry cap (= v2 top-15)
  top15_cap3   : five-factor top-15, max 3 stocks per SW L1 industry
  top30_free   : five-factor top-30, no cap (= sweep top-30)
  top30_cap3   : five-factor top-30, max 3 per industry (additional)

Industry cap is a greedy post-selection constraint: rank by neutral_composite
descending, accept if the stock's industry has < cap members already accepted,
skip otherwise.  Equal weight among the selected.

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
from qlib.contrib.evaluate import backtest_daily, risk_analysis
from qlib.contrib.strategy import TopkDropoutStrategy

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

PARTICIPATION = 0.05
ACCOUNT = 100_000_000
BENCHMARK = "SH000852"
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
        min_amount_15 = (ACCOUNT // 15) / PARTICIPATION
        frame.loc[avg < min_amount_15, "composite5"] = np.nan
        valid = frame.dropna(subset=["composite5", "log_size", "l1_code"])
        if len(valid) < 50:
            continue
        resid = ols_residual(valid["composite5"], valid["l1_code"], valid["log_size"])
        frame["neutral_composite"] = resid.reindex(frame.index)
        snapshots[row.rebalance_date] = frame.reset_index()
    return snapshots


def select_with_industry_cap(frame: pd.DataFrame, top_k: int, cap: int | None) -> pd.DataFrame:
    """Greedy top-k with per-industry cap.  Returns selected rows sorted by score."""
    ranked = frame.dropna(subset=["neutral_composite"]).nlargest(
        top_k * 5 if cap else top_k, "neutral_composite"
    )
    if cap is None:
        selected = ranked.head(top_k)
    else:
        ind_count = {}
        selected_rows = []
        for idx, r in ranked.iterrows():
            ind = r["l1_code"]
            if ind_count.get(ind, 0) >= cap:
                continue
            ind_count[ind] = ind_count.get(ind, 0) + 1
            selected_rows.append(idx)
            if len(selected_rows) >= top_k:
                break
        selected = ranked.loc[selected_rows]
    return selected


def signal_from_snapshots(snapshots: dict, calendar: pd.DatetimeIndex,
                          top_k: int, cap: int | None) -> pd.Series:
    """Build full signal panel. For capped arms, mask over-cap candidates to -999
    so TopkDropoutStrategy skips them naturally while substitutes keep normal scores."""
    cal_win = calendar[(calendar >= BT_START) & (calendar <= BT_END)]
    cols = {}
    for date, frame in snapshots.items():
        scores = frame.set_index("ts_code")["neutral_composite"].copy()
        if cap is not None:
            ranked = frame.dropna(subset=["neutral_composite"]).sort_values(
                "neutral_composite", ascending=False)
            ind_count = {}
            for _, r in ranked.iterrows():
                ind = r["l1_code"]
                if pd.isna(ind):
                    ind = "UNKNOWN"
                if ind_count.get(ind, 0) >= cap:
                    scores[r["ts_code"]] = -999.0  # mask over-cap candidate
                else:
                    ind_count[ind] = ind_count.get(ind, 0) + 1
        cols[date] = scores
    if not cols:
        return pd.Series(dtype=float)
    wide = pd.DataFrame(cols).T  # rows=rebalance_date, cols=ts_code
    wide = wide.reindex(cal_win).ffill()
    # Drop the -999 masked ones so they don't appear in the signal at all
    # (TopkDropout treats them as very low score, effectively skipped)
    long = wide.stack().rename("score").reset_index()
    long.columns = ["datetime", "ts_code", "score"]
    long = long[long["score"] != -999.0]  # remove masked candidates
    long["instrument"] = long["ts_code"].map(qlib_symbol)
    return long.set_index(["datetime", "instrument"])["score"].sort_index()


def run_backtest(signal: pd.Series, top_k: int) -> pd.DataFrame:
    bt_rows = []
    for scenario, costs in COST_SCENARIOS.items():
        strategy = TopkDropoutStrategy(signal=signal, topk=top_k, n_drop=top_k)
        report, _ = backtest_daily(
            start_time=BT_START, end_time=BT_END, strategy=strategy,
            account=ACCOUNT, benchmark=BENCHMARK,
            exchange_kwargs={"limit_threshold": 0.095, "deal_price": "open",
                             "open_cost": costs["open_cost"], "close_cost": costs["close_cost"],
                             "min_cost": 5},
        )
        for stage, (s0, s1) in list(STAGES.items()) + [("full", (BT_START, BT_END))]:
            sample = report.loc[s0:s1]
            if sample.empty:
                continue
            net = risk_analysis(sample["return"] - sample["bench"] - sample["cost"], freq="day")["risk"]
            bt_rows.append({
                "stage": stage, "cost_scenario": scenario,
                "trading_days": int(len(sample)),
                "net_excess_annualized_return": float(net["annualized_return"]),
                "net_excess_ir": float(net["information_ratio"]),
                "net_excess_max_drawdown": float(net["max_drawdown"]),
            })
    return pd.DataFrame(bt_rows)


def measure_concentration(snapshots: dict, top_k: int, cap: int | None) -> dict:
    top1_counts, top3_counts = [], []
    for date, frame in snapshots.items():
        sel = select_with_industry_cap(frame, top_k, cap)
        if sel.empty:
            continue
        counts = sel["l1_code"].value_counts()
        top1_counts.append(counts.iloc[0] / len(sel))
        top3_counts.append(counts.head(3).sum() / len(sel))
    return {
        "avg_top1_industry_share": float(np.mean(top1_counts)) if top1_counts else np.nan,
        "avg_top3_industry_share": float(np.mean(top3_counts)) if top3_counts else 0,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path,
                        default=Path("output/analysis_fundamental/a_share_value_growth_five_factor_industry_cap_v3"))
    args = parser.parse_args()
    out = args.output_dir
    if out.exists() and any(out.iterdir()):
        raise FileExistsError(f"Refusing to overwrite: {out}")
    out.mkdir(parents=True, exist_ok=True)

    qlib.init(provider_uri=str(QLIB_DIR), region=REG_CN)
    calendar = pd.DatetimeIndex(pd.to_datetime(pd.read_csv(QLIB_DIR / "calendars" / "day.txt", header=None)[0]))

    print("[1/3] Loading data + building shared snapshots ...", flush=True)
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

    print(f"[2/3] Backtesting {len(ARMS)} arms ...", flush=True)
    all_bt, all_conc = [], {}
    for name, k, cap in ARMS:
        print(f"  --- {name} (K={k}, cap={cap}) ---", flush=True)
        sig = signal_from_snapshots(snapshots, calendar, k, cap)
        print(f"      signal rows={len(sig)}", flush=True)
        bt = run_backtest(sig, k)
        bt["arm"] = name
        all_bt.append(bt)
        all_conc[name] = measure_concentration(snapshots, k, cap)
        hol = bt[(bt["stage"] == "holdout") & (bt["cost_scenario"] == "stress")]
        fl = bt[(bt["stage"] == "full") & (bt["cost_scenario"] == "stress")]
        if len(hol):
            print(f"      holdout={hol.iloc[0]['net_excess_annualized_return']:.4f} "
                  f"IR={hol.iloc[0]['net_excess_ir']:.3f} MDD={hol.iloc[0]['net_excess_max_drawdown']:.4f}", flush=True)
        if len(fl):
            print(f"      full_IR={fl.iloc[0]['net_excess_ir']:.3f}", flush=True)

    bt = pd.concat(all_bt, ignore_index=True)
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

    print("[3/3] Decision ...", flush=True)
    def pick(arm, stage, col):
        row = bt[(bt["arm"] == arm) & (bt["stage"] == stage) & (bt["cost_scenario"] == "stress")]
        return float(row[col].iloc[0]) if len(row) else np.nan

    decision = {
        "top15_cap3_vs_free_holdout_ir_delta": pick("top15_cap3", "holdout", "net_excess_ir") - pick("top15_free", "holdout", "net_excess_ir"),
        "top15_cap3_vs_free_full_ir_delta": pick("top15_cap3", "full", "net_excess_ir") - pick("top15_free", "full", "net_excess_ir"),
        "top15_cap3_concentration": all_conc.get("top15_cap3", {}),
        "top15_free_concentration": all_conc.get("top15_free", {}),
        "top15_cap3_vs_top30_free_full_ir": pick("top15_cap3", "full", "net_excess_ir") - pick("top30_free", "full", "net_excess_ir"),
    }
    (out / "decision.json").write_text(json.dumps(decision, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(decision, ensure_ascii=False, indent=2), flush=True)


if __name__ == "__main__":
    main()
