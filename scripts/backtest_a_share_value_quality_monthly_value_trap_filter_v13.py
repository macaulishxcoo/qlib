#!/usr/bin/env python3
"""Value-trap filter portfolio backtest v13 (protocol v1, combination stage).

Runs the v8 top-15 baseline AND the v8 baseline + deterioration filter
(exclude stocks with deter_any2==1, i.e. >=2 of netprofit/or/ocf YoY < 0) in
the same script, so the two arms share one data-loading environment.

Acceptance (protocol §5.2): filtered vs baseline --
  holdout (2023-2025-06) stress net excess annualized return does NOT drop
    (tolerance >= -0.5pp),
  AND new_coverage (2025-07~2026-06) stress net excess annualized return
    IMPROVES by >= +5pp.

Protocol: research/protocols/a_share_value_trap_identification_protocol_v1.md
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

from load_financials_extended_v1 import load_financials_extended, FIN, _fill_available
from analyze_a_share_value_quality_level_factors_extension_v1 import (
    build_snapshot,
    ols_residual,
    composite_score,
    STYLE_DIR,
    QLIB_DIR,
)
from backtest_a_share_value_quality_monthly_dailygrid_v6 import build_daily_grid
from backtest_a_share_value_quality_monthly_sensitivity_v4 import load_amount_avg
from run_daily_signal_pipeline_v1 import st_codes_at, qlib_symbol
from analyze_a_share_value_trap_identification_v1 import deterioration_flags

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


def load_financials_with_yoy() -> pd.DataFrame:
    fin = load_financials_extended()
    yoy = pd.read_csv(
        FIN / "normalized/fina_indicator.csv.gz",
        usecols=["ts_code", "end_date", "ann_date", "available_date",
                 "netprofit_yoy", "or_yoy", "ocf_yoy", "dt_netprofit_yoy"],
        low_memory=False,
    )
    yoy = _fill_available(yoy)
    yoy = yoy.dropna(subset=["available_date"])
    yoy = yoy.drop_duplicates(["ts_code", "end_date", "available_date"], keep="last")
    return fin.merge(yoy, on=["ts_code", "end_date", "available_date"], how="left")


def build_snapshots(fin, grid, industry, size_daily, st, amount_avg, apply_filter: bool) -> dict:
    snapshots = {}
    for _, row in grid.iterrows():
        snap = build_snapshot(fin, row, industry, size_daily)
        if snap.empty:
            continue
        frame = snap.copy()
        # Merge deterioration flags (external, latest report period under PIT).
        current = fin[fin["available_date"].le(row.rebalance_date)].copy()
        current = current.sort_values(["ts_code", "end_date", "available_date"], kind="mergesort")
        current = current.drop_duplicates(["ts_code", "end_date"], keep="last")
        latest = current.sort_values(["ts_code", "end_date"], kind="mergesort").drop_duplicates("ts_code", keep="last")
        latest = latest.set_index("ts_code")
        flags = deterioration_flags(latest)
        frame = frame.merge(flags.reset_index().rename(columns={"index": "ts_code"}), on="ts_code", how="left")
        # Composite with factor-count gate.
        frame["composite"] = composite_score(frame)
        # ST filter.
        frame.loc[frame["ts_code"].isin(st_codes_at(st, row.asof_date)), "composite"] = np.nan
        # Capacity filter.
        avg = amount_avg.loc[row.asof_date].reindex(frame["ts_code"]).to_numpy(dtype=float) * 1000.0
        min_amount = NOTIONAL / PARTICIPATION
        frame.loc[avg < min_amount, "composite"] = np.nan
        # Value-trap filter (the only change of the filtered arm).
        if apply_filter:
            frame.loc[frame["deter_any2"].eq(1), "composite"] = np.nan
        # Neutralize.
        valid = frame.dropna(subset=["composite", "log_size", "l1_code"])
        if len(valid) < 50:
            continue
        resid = ols_residual(valid["composite"], valid["l1_code"], valid["log_size"])
        frame["neutral_composite"] = resid.reindex(frame.index)
        snapshots[row.rebalance_date] = frame
    return snapshots


def signal_from_snapshots(snapshots: dict, calendar: pd.DatetimeIndex) -> pd.Series:
    wide = pd.DataFrame({d: f.set_index("ts_code")["neutral_composite"] for d, f in snapshots.items()}).T
    cal_win = calendar[(calendar >= BT_START) & (calendar <= BT_END)]
    wide = wide.reindex(cal_win).ffill()
    long = wide.stack().rename("score").dropna().reset_index()
    long.columns = ["datetime", "ts_code", "score"]
    long["instrument"] = long["ts_code"].map(qlib_symbol)
    return long.set_index(["datetime", "instrument"])["score"].sort_index()


def run_backtest(signal: pd.Series) -> pd.DataFrame:
    bt_rows = []
    for scenario, costs in COST_SCENARIOS.items():
        strategy = TopkDropoutStrategy(signal=signal, topk=TOP_K, n_drop=TOP_K)
        report, _ = backtest_daily(
            start_time=BT_START, end_time=BT_END, strategy=strategy,
            account=ACCOUNT, benchmark=BENCHMARK,
            exchange_kwargs={"limit_threshold": 0.095, "deal_price": "open",
                             "open_cost": costs["open_cost"], "close_cost": costs["close_cost"],
                             "min_cost": 5},
        )
        for stage, (s0, s1) in STAGES.items():
            sample = report.loc[s0:s1]
            if sample.empty:
                continue
            gross = risk_analysis(sample["return"] - sample["bench"], freq="day")["risk"]
            net = risk_analysis(sample["return"] - sample["bench"] - sample["cost"], freq="day")["risk"]
            bt_rows.append({
                "stage": stage, "cost_scenario": scenario,
                "trading_days": int(len(sample)),
                "gross_excess_annualized_return": float(gross["annualized_return"]),
                "gross_excess_ir": float(gross["information_ratio"]),
                "net_excess_annualized_return": float(net["annualized_return"]),
                "net_excess_ir": float(net["information_ratio"]),
                "net_excess_max_drawdown": float(net["max_drawdown"]),
                "average_daily_turnover_rate": float(sample["turnover"].mean()),
                "annualized_cost_drag": float(sample["cost"].mean() * ANNUALIZATION_DAYS),
            })
    return pd.DataFrame(bt_rows)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path,
                        default=Path("output/analysis_fundamental/a_share_value_quality_monthly_strategy_v13_value_trap_filter"))
    args = parser.parse_args()
    out = args.output_dir
    if out.exists() and any(out.iterdir()):
        raise FileExistsError(f"Refusing to overwrite existing experiment output: {out}")
    out.mkdir(parents=True, exist_ok=True)

    qlib.init(provider_uri=str(QLIB_DIR), region=REG_CN)
    calendar = pd.DatetimeIndex(pd.to_datetime(pd.read_csv(QLIB_DIR / "calendars" / "day.txt", header=None)[0]))

    print("[1/6] Loading extended financials (+YoY) & daily grid ...", flush=True)
    fin = load_financials_with_yoy()
    grid, size_daily = build_daily_grid()
    print(f"      months={len(grid)} {grid['rebalance_date'].min().date()} .. {grid['rebalance_date'].max().date()}", flush=True)

    industry = pd.read_csv(STYLE_DIR / "industry_l1_effective_intervals.csv.gz", compression="gzip", dtype=str)
    industry["in_date"] = pd.to_datetime(industry["in_date"], errors="coerce")
    industry["out_date"] = pd.to_datetime(industry["out_date"], errors="coerce")
    st = pd.read_csv(ST_INTERVALS, compression="gzip", parse_dates=["start_date", "end_date"])
    universe_codes = sorted(size_daily["ts_code"].unique())
    amount_avg = load_amount_avg(universe_codes, calendar)

    print("[2/6] Building baseline snapshots (no filter) ...", flush=True)
    base_snaps = build_snapshots(fin, grid, industry, size_daily, st, amount_avg, apply_filter=False)
    print(f"      baseline valid months={len(base_snaps)}", flush=True)
    print("[3/6] Building filtered snapshots (deter_any2 excluded) ...", flush=True)
    filt_snaps = build_snapshots(fin, grid, industry, size_daily, st, amount_avg, apply_filter=True)
    print(f"      filtered valid months={len(filt_snaps)}", flush=True)

    print("[4/6] Building signals ...", flush=True)
    base_signal = signal_from_snapshots(base_snaps, calendar)
    filt_signal = signal_from_snapshots(filt_snaps, calendar)
    print(f"      baseline signal rows={len(base_signal)}  filtered rows={len(filt_signal)}", flush=True)

    print("[5/6] Backtesting both arms ...", flush=True)
    base_bt = run_backtest(base_signal)
    base_bt["arm"] = "baseline"
    filt_bt = run_backtest(filt_signal)
    filt_bt["arm"] = "filtered"
    bt = pd.concat([base_bt, filt_bt], ignore_index=True)
    bt.to_csv(out / "backtest_summary.csv", index=False)

    pivot = bt.pivot_table(
        index=["stage", "cost_scenario"], columns="arm",
        values=["net_excess_annualized_return", "net_excess_ir", "net_excess_max_drawdown"],
    )
    print(pivot.to_string())

    print("[6/6] Decision ...", flush=True)
    def pick(arm: str, stage: str, scenario: str, column: str) -> float:
        row = bt[(bt["arm"].eq(arm)) & (bt["stage"].eq(stage)) & (bt["cost_scenario"].eq(scenario))]
        return float(row[column].iloc[0]) if len(row) else np.nan

    hol_base = pick("baseline", "holdout", "stress", "net_excess_annualized_return")
    hol_filt = pick("filtered", "holdout", "stress", "net_excess_annualized_return")
    new_base = pick("baseline", "new_coverage", "stress", "net_excess_annualized_return")
    new_filt = pick("filtered", "new_coverage", "stress", "net_excess_annualized_return")

    holdout_delta = hol_filt - hol_base
    new_coverage_delta = new_filt - new_base
    holdout_ok = bool(holdout_delta >= -0.005)
    new_coverage_ok = bool(new_coverage_delta >= 0.05)

    if holdout_ok and new_coverage_ok:
        decision = "value_trap_filter_adopted"
    elif holdout_ok and not new_coverage_ok:
        decision = "value_trap_filter_neutral_holdout_ok"
    elif not holdout_ok and new_coverage_ok:
        decision = "value_trap_filter_holdout_erosion"
    else:
        decision = "value_trap_filter_not_adopted"

    decision_json = {
        "decision": decision,
        "baseline_holdout_stress_net": hol_base,
        "filtered_holdout_stress_net": hol_filt,
        "holdout_delta_pp": holdout_delta * 100,
        "holdout_ok": holdout_ok,
        "baseline_new_coverage_stress_net": new_base,
        "filtered_new_coverage_stress_net": new_filt,
        "new_coverage_delta_pp": new_coverage_delta * 100,
        "new_coverage_ok": new_coverage_ok,
        "top_k": TOP_K,
    }
    (out / "decision.json").write_text(json.dumps(decision_json, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    methodology = {
        "protocol": "research/protocols/a_share_value_trap_identification_protocol_v1.md",
        "arms": {
            "baseline": "v8 top-15 identical rules (TOP_K=15)",
            "filtered": "v8 + exclude deter_any2==1 (>=2 of netprofit/or/ocf YoY<0) before neutralization",
        },
        "grid": "daily_basic_pit month-end trading day",
        "topk": TOP_K,
        "execution": "TopkDropout t+1 open; limit_threshold 0.095; min_cost 5",
        "cost_scenarios": COST_SCENARIOS,
        "benchmark": BENCHMARK,
        "stages": {k: [v[0].isoformat(), v[1].isoformat()] for k, v in STAGES.items()},
        "backtest_window": [str(BT_START.date()), str(BT_END.date())],
        "created_at_utc": pd.Timestamp.utcnow().isoformat(),
    }
    (out / "methodology.json").write_text(json.dumps(methodology, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    lines = [
        "价值陷阱过滤层组合回测 v13（v8 top-15 基线 vs 基线+过滤层）",
        "=" * 64,
        "对比（压力费后净超额，相对 SH000852）：",
        bt.pivot_table(index=["stage", "cost_scenario"], columns="arm",
                       values=["net_excess_annualized_return", "net_excess_ir", "net_excess_max_drawdown"]).to_string(),
        "",
        f"holdout 变化：{hol_base*100:.2f}% -> {hol_filt*100:.2f}% (delta {holdout_delta*100:+.2f}pp, 门槛 >=-0.5pp → {'通过' if holdout_ok else '不通过'})",
        f"new_coverage 变化：{new_base*100:.2f}% -> {new_filt*100:.2f}% (delta {new_coverage_delta*100:+.2f}pp, 门槛 >=+5pp → {'通过' if new_coverage_ok else '不通过'})",
        "",
        f"判定：{decision}",
    ]
    (out / "strategy_report.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("\n".join(lines))


if __name__ == "__main__":
    main()
