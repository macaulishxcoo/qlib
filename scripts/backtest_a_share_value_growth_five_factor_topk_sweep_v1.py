#!/usr/bin/env python3
"""Top-K sensitivity sweep for the five-factor strategy.

Runs the five-factor (ep+bm+div+accruals+g2) top-K strategy for K in
{15,25,30,50} under identical rules (same composite5, same ST/capacity
filters, same neutralization, same costs/execution).  One script, one
data environment, four arms -- to answer:
  1. Does widening from 15 reduce industry concentration naturally?
  2. Does IR recover toward v6's top-50 level (1.33 on four-factor)?
  3. Is there a sweet spot that balances IR, MDD, and concentration?

Protocol: research/protocols/a_share_value_growth_five_factor_topk_sensitivity_protocol_v1.md
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
from run_daily_signal_pipeline_v1 import st_codes_at, qlib_symbol

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
FIN_TOP = Path("data/external/tushare/a_share_financial_pit_v1/normalized/fina_indicator.csv.gz")
TOP_K_VALUES = [15, 25, 30, 50]


def load_g2() -> pd.DataFrame:
    g2 = pd.read_csv(FIN_TOP, compression="gzip",
                     usecols=["ts_code", "end_date", "available_date", "dt_netprofit_yoy"])
    for col in ("end_date", "available_date"):
        g2[col] = pd.to_datetime(g2[col].astype(str).str.replace("-", "", regex=False),
                                 format="%Y%m%d", errors="coerce")
    return g2.drop_duplicates(["ts_code", "end_date", "available_date"], keep="last")


def g2_at(fin_g2: pd.DataFrame, date: pd.Timestamp) -> pd.Series:
    cur = fin_g2[fin_g2["available_date"].le(date)]
    cur = cur.sort_values(["ts_code", "end_date", "available_date"], kind="mergesort") \
        .drop_duplicates(["ts_code", "end_date"], keep="last")
    latest = cur.sort_values("end_date", kind="mergesort").drop_duplicates("ts_code", keep="last")
    return latest.set_index("ts_code")["dt_netprofit_yoy"]


def composite5_score(frame: pd.DataFrame) -> pd.Series:
    factors = ("ep", "bm", "div_yield", "accruals", "g2")
    ranks = pd.concat([frame[f].rank(method="first", pct=True) for f in factors], axis=1)
    n_factors = ranks.notna().sum(axis=1)
    composite = ranks.mean(axis=1)
    composite[n_factors < 4] = np.nan
    return composite


def build_snapshots(fin, fin_g2, grid, industry, size_daily, st, amount_avg) -> dict:
    """Build five-factor snapshots with neutralization (TOP_K-independent)."""
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
        # Use the tightest capacity filter (top-15's NOTIONAL) so all arms
        # share the same eligible universe; selection count differs only by TOP_K.
        min_amount_15 = (ACCOUNT // 15) / PARTICIPATION
        frame.loc[avg < min_amount_15, "composite5"] = np.nan
        valid = frame.dropna(subset=["composite5", "log_size", "l1_code"])
        if len(valid) < 50:
            continue
        resid = ols_residual(valid["composite5"], valid["l1_code"], valid["log_size"])
        frame["neutral_composite"] = resid.reindex(frame.index)
        snapshots[row.rebalance_date] = frame.reset_index()
    return snapshots


def signal_from_snapshots(snapshots: dict, calendar: pd.DatetimeIndex, top_k: int) -> pd.Series:
    """Full signal panel; TopkDropoutStrategy selects top-k itself."""
    wide = pd.DataFrame({d: f.set_index("ts_code")["neutral_composite"] for d, f in snapshots.items()}).T
    cal_win = calendar[(calendar >= BT_START) & (calendar <= BT_END)]
    wide = wide.reindex(cal_win).ffill()
    long = wide.stack().rename("score").dropna().reset_index()
    long.columns = ["datetime", "ts_code", "score"]
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
                "top_k": top_k, "stage": stage, "cost_scenario": scenario,
                "trading_days": int(len(sample)),
                "net_excess_annualized_return": float(net["annualized_return"]),
                "net_excess_ir": float(net["information_ratio"]),
                "net_excess_max_drawdown": float(net["max_drawdown"]),
                "average_daily_turnover_rate": float(sample["turnover"].mean()),
            })
    return pd.DataFrame(bt_rows)


def measure_concentration(snapshots: dict, top_k: int) -> dict:
    """Average industry concentration of the top-k holdings across months."""
    top1_counts = []
    top3_counts = []
    for date, frame in snapshots.items():
        top = frame.dropna(subset=["neutral_composite"]).nlargest(top_k, "neutral_composite")
        if top.empty:
            continue
        ind_counts = top["l1_code"].value_counts()
        top1_counts.append(ind_counts.iloc[0] / top_k if len(ind_counts) else 0)
        top3_counts.append(ind_counts.head(3).sum() / top_k if len(ind_counts) else 0)
    return {
        "avg_top1_industry_share": float(np.mean(top1_counts)) if top1_counts else np.nan,
        "avg_top3_industry_share": float(np.mean(top3_counts)) if top3_counts else 0,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path,
                        default=Path("output/analysis_fundamental/a_share_value_growth_five_factor_topk_sweep_v1"))
    args = parser.parse_args()
    out = args.output_dir
    if out.exists() and any(out.iterdir()):
        raise FileExistsError(f"Refusing to overwrite existing experiment output: {out}")
    out.mkdir(parents=True, exist_ok=True)

    qlib.init(provider_uri=str(QLIB_DIR), region=REG_CN)
    calendar = pd.DatetimeIndex(pd.to_datetime(pd.read_csv(QLIB_DIR / "calendars" / "day.txt", header=None)[0]))

    print("[1/3] Loading data + building five-factor snapshots (shared) ...", flush=True)
    fin = load_financials_extended()
    fin_g2 = load_g2()
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

    print(f"[2/3] Backtesting TOP_K={TOP_K_VALUES} ...", flush=True)
    all_bt = []
    concentration = {}
    for k in TOP_K_VALUES:
        print(f"  --- TOP_K={k} ---", flush=True)
        sig = signal_from_snapshots(snapshots, calendar, k)
        print(f"      signal rows={len(sig)}", flush=True)
        bt = run_backtest(sig, k)
        all_bt.append(bt)
        concentration[k] = measure_concentration(snapshots, k)
        hol = bt[(bt["stage"] == "holdout") & (bt["cost_scenario"] == "stress")].iloc[0]
        nc = bt[(bt["stage"] == "new_coverage") & (bt["cost_scenario"] == "stress")].iloc[0]
        fl = bt[(bt["stage"] == "full") & (bt["cost_scenario"] == "stress")].iloc[0]
        print(f"      holdout={hol['net_excess_annualized_return']:.4f} IR={hol['net_excess_ir']:.3f} "
              f"MDD={hol['net_excess_max_drawdown']:.4f}", flush=True)
        print(f"      new_cov={nc['net_excess_annualized_return']:.4f} full_IR={fl['net_excess_ir']:.3f}", flush=True)

    bt = pd.concat(all_bt, ignore_index=True)
    bt.to_csv(out / "backtest_summary.csv", index=False)

    # concentration table
    conc_rows = [{"top_k": k, **v} for k, v in concentration.items()]
    conc_df = pd.DataFrame(conc_rows)
    conc_df.to_csv(out / "industry_concentration.csv", index=False)
    print("\n行业集中度:")
    print(conc_df.to_string(index=False))

    print("\n四组对照（stress 费后）:")
    piv = bt[bt["cost_scenario"] == "stress"].pivot_table(
        index="stage", columns="top_k",
        values=["net_excess_annualized_return", "net_excess_ir", "net_excess_max_drawdown"])
    print(piv.round(4).to_string())

    print("[3/3] Decision ...", flush=True)
    # Find best by holdout IR and by full IR
    stress = bt[bt["cost_scenario"] == "stress"]
    holdout_irs = stress[stress["stage"] == "holdout"].set_index("top_k")["net_excess_ir"]
    full_irs = stress[stress["stage"] == "full"].set_index("top_k")["net_excess_ir"]
    best_holdout_k = int(holdout_irs.idxmax())
    best_full_k = int(full_irs.idxmax())

    decision = {
        "arms": TOP_K_VALUES,
        "holdout_ir_by_k": {int(k): float(v) for k, v in holdout_irs.items()},
        "full_ir_by_k": {int(k): float(v) for k, v in full_irs.items()},
        "best_holdout_k": best_holdout_k,
        "best_full_k": best_full_k,
        "concentration": {int(k): v for k, v in concentration.items()},
        "note": "capacity filter uses top-15 NOTIONAL for all arms (shared universe)",
    }
    (out / "decision.json").write_text(json.dumps(decision, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(decision, ensure_ascii=False, indent=2), flush=True)


if __name__ == "__main__":
    main()
