#!/usr/bin/env python3
"""Five-factor (value/quality + growth) monthly top-15 backtest (protocol v2).

Identical to v8 with ONE change: composite_score uses five factors
(ep, bm, div_yield, accruals + g2 dt_netprofit_yoy) with a >=4-of-5
non-missing gate (vs v8's >=3-of-4).  Everything else (ST/capacity filters,
neutralization, top-15, costs, execution) is copied from v8.

Protocol: research/protocols/a_share_value_growth_five_factor_strategy_protocol_v2.md
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
from backtest_a_share_value_quality_monthly_sensitivity_v4 import load_amount_avg
from backtest_a_share_value_quality_monthly_dailygrid_v6 import build_daily_grid
from run_daily_signal_pipeline_v1 import st_codes_at, qlib_symbol

TOP_K = 15
PARTICIPATION = 0.05
ACCOUNT = 100_000_000
NOTIONAL = ACCOUNT // TOP_K
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

V8_HOLDOUT_IR_STRESS = 0.919   # v8 decision.json reference
V8_FULL_IR_STRESS = 0.611
V8_NEWCOV_EXCESS_STRESS = -0.3501


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
    """Five-factor rank-mean with >=4-of-5 non-missing gate (see protocol §2)."""
    factors = ("ep", "bm", "div_yield", "accruals", "g2")
    ranks = pd.concat([frame[f].rank(method="first", pct=True) for f in factors], axis=1)
    n_factors = ranks.notna().sum(axis=1)
    composite = ranks.mean(axis=1)
    composite[n_factors < 4] = np.nan
    return composite


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path,
                        default=Path("output/analysis_fundamental/a_share_value_growth_five_factor_strategy_v2"))
    args = parser.parse_args()
    out = args.output_dir
    if out.exists() and any(out.iterdir()):
        raise FileExistsError(f"Refusing to overwrite existing experiment output: {out}")
    out.mkdir(parents=True, exist_ok=True)

    qlib.init(provider_uri=str(QLIB_DIR), region=REG_CN)
    calendar = pd.DatetimeIndex(pd.to_datetime(pd.read_csv(QLIB_DIR / "calendars" / "day.txt", header=None)[0]))

    print("[1/5] Loading data ...", flush=True)
    fin = load_financials_extended()
    fin_g2 = load_g2()
    grid, size_daily = build_daily_grid()
    grid = grid[(grid["rebalance_date"] >= BT_START) & (grid["rebalance_date"] <= BT_END)]
    print(f"      months={len(grid)} {grid['rebalance_date'].min().date()} .. {grid['rebalance_date'].max().date()}", flush=True)

    industry = pd.read_csv(STYLE_DIR / "industry_l1_effective_intervals.csv.gz", compression="gzip", dtype=str)
    industry["in_date"] = pd.to_datetime(industry["in_date"], errors="coerce")
    industry["out_date"] = pd.to_datetime(industry["out_date"], errors="coerce")
    st = pd.read_csv(ST_INTERVALS, compression="gzip", parse_dates=["start_date", "end_date"])
    universe_codes = sorted(size_daily["ts_code"].unique())
    amount_avg = load_amount_avg(universe_codes, calendar)

    print(f"[2/5] Building monthly five-factor snapshots (TOP_K={TOP_K}) ...", flush=True)
    snapshots = {}
    for _, row in grid.iterrows():
        snap = build_snapshot(fin, row, industry, size_daily)
        if snap.empty:
            continue
        snap = snap.set_index("ts_code")
        snap["g2"] = g2_at(fin_g2, row.rebalance_date).reindex(snap.index)
        snap["composite5"] = composite5_score(snap.reset_index()).set_axis(snap.index)
        frame = snap.reset_index()
        frame.loc[frame["ts_code"].isin(st_codes_at(st, row.rebalance_date)), "composite5"] = np.nan
        avg = amount_avg.loc[row.rebalance_date].reindex(frame["ts_code"]).to_numpy(dtype=float) * 1000.0
        frame.loc[avg < NOTIONAL / PARTICIPATION, "composite5"] = np.nan
        valid = frame.dropna(subset=["composite5", "log_size", "l1_code"])
        if len(valid) < 50:
            continue
        resid = ols_residual(valid["composite5"], valid["l1_code"], valid["log_size"])
        frame["neutral_composite"] = resid.reindex(frame.index)
        snapshots[row.rebalance_date] = frame
    print(f"      valid months={len(snapshots)}", flush=True)

    print("[3/5] Building daily signal ...", flush=True)
    wide = pd.DataFrame({d: f.set_index("ts_code")["neutral_composite"] for d, f in snapshots.items()}).T
    cal_win = calendar[(calendar >= BT_START) & (calendar <= BT_END)]
    wide = wide.reindex(cal_win).ffill()
    long = wide.stack().rename("score").dropna().reset_index()
    long.columns = ["datetime", "ts_code", "score"]
    long["instrument"] = long["ts_code"].map(qlib_symbol)
    signal = long.set_index(["datetime", "instrument"])["score"].sort_index()
    print(f"      signal rows={len(signal)}", flush=True)

    print("[4/5] Backtest (base & stress) ...", flush=True)
    bt_rows = []
    for scenario, costs in COST_SCENARIOS.items():
        strategy = TopkDropoutStrategy(signal=signal, topk=TOP_K, n_drop=TOP_K)
        report, _ = backtest_daily(
            start_time=BT_START, end_time=BT_END, strategy=strategy,
            account=ACCOUNT, benchmark=BENCHMARK,
            exchange_kwargs={
                "limit_threshold": 0.095, "deal_price": "open",
                "open_cost": costs["open_cost"], "close_cost": costs["close_cost"],
                "min_cost": 5,
            },
        )
        for stage, (s0, s1) in list(STAGES.items()) + [("full", (BT_START, BT_END))]:
            sample = report.loc[s0:s1]
            if sample.empty:
                continue
            net = risk_analysis(sample["return"] - sample["bench"] - sample["cost"], freq="day")["risk"]
            bt_rows.append({
                "stage": stage, "cost_scenario": scenario,
                "start": str(sample.index.min().date()), "end": str(sample.index.max().date()),
                "trading_days": int(len(sample)),
                "net_excess_annualized_return": float(net["annualized_return"]),
                "net_excess_ir": float(net["information_ratio"]),
                "net_excess_max_drawdown": float(net["max_drawdown"]),
                "average_daily_turnover_rate": float(sample["turnover"].mean()),
            })
        hol = next(r for r in bt_rows if r["stage"] == "holdout" and r["cost_scenario"] == scenario)
        print(f"      [{scenario}] holdout net={hol['net_excess_annualized_return']:.4f} "
              f"IR={hol['net_excess_ir']:.3f} MDD={hol['net_excess_max_drawdown']:.4f}", flush=True)
        if scenario == "stress":
            report.loc[:, ["return", "bench", "cost"]].to_csv(out / "daily_report_stress.csv")

    bt = pd.DataFrame(bt_rows)
    bt.to_csv(out / "backtest_summary.csv", index=False)

    print("[5/5] Yearly summary + decision ...", flush=True)
    strategy = TopkDropoutStrategy(signal=signal, topk=TOP_K, n_drop=TOP_K)
    report_full, _ = backtest_daily(
        start_time=BT_START, end_time=BT_END, strategy=strategy, account=ACCOUNT, benchmark=BENCHMARK,
        exchange_kwargs={"limit_threshold": 0.095, "deal_price": "open",
                         "open_cost": COST_SCENARIOS["base"]["open_cost"],
                         "close_cost": COST_SCENARIOS["base"]["close_cost"], "min_cost": 5},
    )
    yearly_rows = []
    for year, sample in report_full.loc[BT_START:BT_END].groupby(report_full.loc[BT_START:BT_END].index.year):
        if len(sample) < 50:
            continue
        net = risk_analysis(sample["return"] - sample["bench"] - sample["cost"], freq="day")["risk"]
        yearly_rows.append({"year": int(year), "trading_days": int(len(sample)),
                            "net_excess_annualized_return": float(net["annualized_return"]),
                            "net_excess_ir": float(net["information_ratio"])})
    yearly = pd.DataFrame(yearly_rows)
    yearly.to_csv(out / "yearly_summary.csv", index=False)

    panel_rows = []
    for date, f in snapshots.items():
        item = f[["ts_code", "composite5", "neutral_composite", "log_size", "l1_code"]].copy()
        item["rebalance_date"] = date
        panel_rows.append(item)
    pd.concat(panel_rows, ignore_index=True).to_csv(out / "monthly_composite_top15.csv.gz",
                                                    index=False, compression="gzip")

    stress = {r["stage"]: r for r in bt_rows if r["cost_scenario"] == "stress"}
    hol = stress["holdout"]
    viable = bool(hol["net_excess_annualized_return"] > 0 and hol["net_excess_ir"] > 0)
    improved = bool(viable and hol["net_excess_ir"] > V8_HOLDOUT_IR_STRESS)
    robust_improved = bool(stress["full"]["net_excess_ir"] > V8_FULL_IR_STRESS
                           and stress["new_coverage"]["net_excess_annualized_return"] > V8_NEWCOV_EXCESS_STRESS)
    if improved:
        verdict = "improved"
    elif robust_improved:
        verdict = "regime_robust_improved"
    elif viable:
        verdict = "five_factor_viable_no_improvement"
    else:
        verdict = "no_improvement_closed"
    decision = {
        "gate_viable": "holdout stress net excess > 0 and IR > 0",
        "gate_improved": f"holdout stress IR > v8 {V8_HOLDOUT_IR_STRESS}",
        "gate_regime_robust": f"full IR > v8 {V8_FULL_IR_STRESS} and new_coverage excess > v8 {V8_NEWCOV_EXCESS_STRESS}",
        "holdout_stress": {k: hol[k] for k in ("net_excess_annualized_return", "net_excess_ir", "net_excess_max_drawdown")},
        "full_stress": {k: stress["full"][k] for k in ("net_excess_annualized_return", "net_excess_ir", "net_excess_max_drawdown")},
        "new_coverage_stress": {k: stress["new_coverage"][k] for k in ("net_excess_annualized_return", "net_excess_ir")},
        "verdict": verdict,
    }
    (out / "decision.json").write_text(json.dumps(decision, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(decision, ensure_ascii=False, indent=2), flush=True)

    methodology = {
        "protocol": "research/protocols/a_share_value_growth_five_factor_strategy_protocol_v2.md",
        "signal": "composite5 = mean(rank_pct(ep, bm, div_yield, accruals, g2)), >=4 of 5 non-missing",
        "g2": "dt_netprofit_yoy from fina_indicator PIT (available_date <= rebalance)",
        "identical_to_v8_except": "composite factors 4->5, gate 3->4",
        "top_k": TOP_K, "account": ACCOUNT, "benchmark": BENCHMARK,
        "stages": {k: [v[0].isoformat(), v[1].isoformat()] for k, v in STAGES.items()},
        "v8_references": {"holdout_ir_stress": V8_HOLDOUT_IR_STRESS,
                          "full_ir_stress": V8_FULL_IR_STRESS,
                          "new_coverage_excess_stress": V8_NEWCOV_EXCESS_STRESS},
        "created_at_utc": pd.Timestamp.utcnow().isoformat(),
    }
    (out / "methodology.json").write_text(json.dumps(methodology, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
