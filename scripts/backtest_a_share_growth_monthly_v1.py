#!/usr/bin/env python3
"""Monthly top-15 backtest of the growth composite strategy (protocol v1).

Identical to v8 (daily-grid monthly rebalance, ST/capacity filters,
industry+size neutralization, T+1 open execution, base/stress costs) with
ONE change: the selection signal is the growth composite
(rank-pct mean of dt_netprofit_yoy and q_sales_yoy, both required) instead
of the value/quality four-factor composite.

Protocol: research/protocols/a_share_growth_monthly_strategy_protocol_v1.md
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
from qlib.data import D

from analyze_a_share_growth_factor_family_v1 import (
    load_growth_financials,
    CLASS_V2,
    FINANCIAL_L1_CODES,
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


def growth_snapshot(fin: pd.DataFrame, cls: pd.DataFrame, row: pd.Series) -> pd.DataFrame:
    """Growth composite snapshot at one rebalance date (see protocol §2)."""
    date = row.rebalance_date
    asof = row.asof_date
    if not cls["asof_date"].eq(asof).any():
        return pd.DataFrame()

    current = fin[fin["available_date"].le(date)].copy()
    current = current.sort_values(["ts_code", "end_date", "available_date"], kind="mergesort") \
        .drop_duplicates(["ts_code", "end_date"], keep="last")
    if current.empty:
        return current
    latest = current.sort_values(["ts_code", "end_date"], kind="mergesort") \
        .drop_duplicates("ts_code", keep="last").set_index("ts_code")

    size_asof = cls[cls["asof_date"].eq(asof)].set_index("ts_code")

    g2 = latest["dt_netprofit_yoy"]
    g3 = latest["q_sales_yoy"]
    both = g2.notna() & g3.notna()
    composite = 0.5 * g2.rank(pct=True) + 0.5 * g3.rank(pct=True)
    composite[~both] = np.nan

    result = pd.DataFrame(index=latest.index)
    result["growth_composite"] = composite
    result["l1_code"] = size_asof["l1_code"].reindex(latest.index)
    result["log_size"] = np.log(size_asof["total_mv"].reindex(latest.index))

    result = result[~result["l1_code"].isin(FINANCIAL_L1_CODES)].copy()
    risk = size_asof["risk_status"].reindex(result.index)
    result = result[risk.isna() | (~risk.isin(["st", "delist_phase"]))].copy()
    return result.reset_index()


def neutralize(frame: pd.DataFrame) -> pd.DataFrame:
    """Industry + log-size OLS residual of growth_composite (same as v8 axis)."""
    valid = frame.dropna(subset=["growth_composite", "log_size", "l1_code"])
    if len(valid) < 50:
        frame["neutral_growth"] = np.nan
        return frame
    dummies = pd.get_dummies(valid["l1_code"], dtype=float)
    if dummies.shape[1] > 0:
        dummies = dummies.iloc[:, 1:]
    design = np.column_stack([np.ones(len(valid)), valid["log_size"].to_numpy(dtype=float),
                              dummies.to_numpy(dtype=float)])
    beta, *_ = np.linalg.lstsq(design, valid["growth_composite"].to_numpy(dtype=float), rcond=None)
    frame["neutral_growth"] = np.nan
    frame.loc[valid.index, "neutral_growth"] = valid["growth_composite"].to_numpy(dtype=float) - design @ beta
    return frame


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path,
                        default=Path("output/analysis_fundamental/a_share_growth_monthly_strategy_v1"))
    args = parser.parse_args()
    out = args.output_dir
    if out.exists() and any(out.iterdir()):
        raise FileExistsError(f"Refusing to overwrite existing experiment output: {out}")
    out.mkdir(parents=True, exist_ok=True)

    qlib.init(provider_uri=str(QLIB_DIR), region=REG_CN)
    calendar = pd.DatetimeIndex(pd.to_datetime(pd.read_csv(QLIB_DIR / "calendars" / "day.txt", header=None)[0]))

    print("[1/5] Loading data ...", flush=True)
    fin = load_growth_financials()
    cls = pd.read_csv(CLASS_V2, compression="gzip")
    cls["asof_date"] = pd.to_datetime(cls["asof_date"], errors="coerce")
    # v8's daily grid (month-end rebalance=asof) -> but classification_v2 asof is
    # month-end too; align grid asof to classification asof (month-end trading day).
    grid, size_daily = build_daily_grid()
    grid = grid[(grid["rebalance_date"] >= BT_START) & (grid["rebalance_date"] <= BT_END)]
    # classification asof dates are month-end trading days from the style PIT grid;
    # map each rebalance_date to the classification asof <= date (use the same month).
    cls_asofs = pd.DatetimeIndex(sorted(cls["asof_date"].unique()))
    grid["asof_date"] = [cls_asofs[cls_asofs.get_indexer([d], method="ffill")[0]] if
                         cls_asofs.get_indexer([d], method="ffill")[0] >= 0 else pd.NaT
                         for d in grid["rebalance_date"]]
    grid = grid.dropna(subset=["asof_date"])
    print(f"      months={len(grid)} {grid['rebalance_date'].min().date()} .. {grid['rebalance_date'].max().date()}", flush=True)

    st = pd.read_csv(ST_INTERVALS, compression="gzip", parse_dates=["start_date", "end_date"])
    universe_codes = sorted(cls["ts_code"].unique())
    amount_avg = load_amount_avg(universe_codes, calendar)

    print(f"[2/5] Building monthly growth snapshots (TOP_K={TOP_K}) ...", flush=True)
    snapshots = {}
    for _, row in grid.iterrows():
        snap = growth_snapshot(fin, cls, row)
        if snap.empty:
            continue
        snap = neutralize(snap)
        snap.loc[snap["ts_code"].isin(st_codes_at(st, row.rebalance_date)), "neutral_growth"] = np.nan
        avg = amount_avg.loc[row.rebalance_date].reindex(snap["ts_code"]).to_numpy(dtype=float) * 1000.0
        snap.loc[avg < NOTIONAL / PARTICIPATION, "neutral_growth"] = np.nan
        if snap["neutral_growth"].notna().sum() >= TOP_K:
            snapshots[row.rebalance_date] = snap
    print(f"      valid months={len(snapshots)}", flush=True)

    print("[3/5] Building daily signal ...", flush=True)
    wide = pd.DataFrame({d: f.set_index("ts_code")["neutral_growth"] for d, f in snapshots.items()}).T
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
        # persist daily report of stress scenario for correlation analysis
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
        item = f[["ts_code", "growth_composite", "neutral_growth", "log_size", "l1_code"]].copy()
        item["rebalance_date"] = date
        panel_rows.append(item)
    pd.concat(panel_rows, ignore_index=True).to_csv(out / "monthly_composite_top15.csv.gz",
                                                    index=False, compression="gzip")

    stress_hol = next(r for r in bt_rows if r["stage"] == "holdout" and r["cost_scenario"] == "stress")
    viable = bool(stress_hol["net_excess_annualized_return"] > 0 and stress_hol["net_excess_ir"] > 0)
    decision = {
        "gate": "holdout(2023-01~2025-06) stress net excess annualized > 0 and IR > 0",
        "holdout_stress_net_excess": stress_hol["net_excess_annualized_return"],
        "holdout_stress_ir": stress_hol["net_excess_ir"],
        "holdout_stress_mdd": stress_hol["net_excess_max_drawdown"],
        "verdict": "growth_top15_viable" if viable else "growth_top15_not_viable",
    }
    (out / "decision.json").write_text(json.dumps(decision, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(decision, ensure_ascii=False, indent=2), flush=True)

    methodology = {
        "protocol": "research/protocols/a_share_growth_monthly_strategy_protocol_v1.md",
        "signal": "growth_composite = 0.5*rank_pct(dt_netprofit_yoy) + 0.5*rank_pct(q_sales_yoy), both required",
        "identical_to_v8_except": "selection signal",
        "top_k": TOP_K, "account": ACCOUNT, "benchmark": BENCHMARK,
        "stages": {k: [v[0].isoformat(), v[1].isoformat()] for k, v in STAGES.items()},
        "created_at_utc": pd.Timestamp.utcnow().isoformat(),
    }
    (out / "methodology.json").write_text(json.dumps(methodology, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
