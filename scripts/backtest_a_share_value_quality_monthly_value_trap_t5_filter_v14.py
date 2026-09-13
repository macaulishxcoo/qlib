#!/usr/bin/env python3
"""Value-trap + T5 negative-event combined filter backtest v14.

Runs four arms in one script so they share one data-loading environment:
  baseline : v8 top-15 identical rules (TOP_K=15)
  vt       : baseline + exclude deter_any2==1 (value trap, financial YoY < 0, v13)
  t5       : baseline + exclude 跌幅上榜 events within past 20 trading days (v12)
  vt+t5    : baseline + both filters (the combined layer under test)

Acceptance (same dual-gate as v12/v13, combined arm vs baseline):
  holdout (2023-2025-06) stress net excess annualized return does NOT drop
    (tolerance >= -0.5pp),
  AND new_coverage (2025-07~2026-06) stress net excess annualized return
    IMPROVES by >= +5pp.
Additionally report combined vs the better single filter (t5) for the
incremental contribution.

Protocols:
  research/protocols/a_share_value_trap_identification_protocol_v1.md (vt)
  research/protocols/a_share_negative_event_subtype_protocol_v1.md (t5)
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
    composite_score,
    STYLE_DIR,
    QLIB_DIR,
)
from backtest_a_share_value_quality_monthly_dailygrid_v6 import build_daily_grid
from backtest_a_share_value_quality_monthly_sensitivity_v4 import load_amount_avg
from run_daily_signal_pipeline_v1 import st_codes_at, qlib_symbol
from backtest_a_share_value_quality_monthly_value_trap_filter_v13 import (
    load_financials_with_yoy,
    deterioration_flags,
)
from backtest_a_share_value_quality_monthly_negative_event_filter_v12 import (
    load_t5_events,
    build_event_sets,
)

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


def build_snapshots(fin, grid, industry, size_daily, st, amount_avg,
                    apply_vt: bool,
                    exclude_by_rebalance: dict[pd.Timestamp, set[str]] | None) -> dict:
    snapshots = {}
    for _, row in grid.iterrows():
        snap = build_snapshot(fin, row, industry, size_daily)
        if snap.empty:
            continue
        frame = snap.copy()
        # Value-trap filter (external YoY flags, latest report period under PIT).
        if apply_vt:
            current = fin[fin["available_date"].le(row.rebalance_date)].copy()
            current = current.sort_values(["ts_code", "end_date", "available_date"], kind="mergesort")
            current = current.drop_duplicates(["ts_code", "end_date"], keep="last")
            latest = current.sort_values(["ts_code", "end_date"], kind="mergesort").drop_duplicates("ts_code", keep="last")
            latest = latest.set_index("ts_code")
            flags = deterioration_flags(latest)
            frame = frame.merge(flags.reset_index().rename(columns={"index": "ts_code"}), on="ts_code", how="left")
        frame["composite"] = composite_score(frame)
        frame.loc[frame["ts_code"].isin(st_codes_at(st, row.asof_date)), "composite"] = np.nan
        avg = amount_avg.loc[row.asof_date].reindex(frame["ts_code"]).to_numpy(dtype=float) * 1000.0
        min_amount = NOTIONAL / PARTICIPATION
        frame.loc[avg < min_amount, "composite"] = np.nan
        # T5 event exclusion layer.
        if exclude_by_rebalance is not None:
            hits = exclude_by_rebalance.get(row.rebalance_date, set())
            if hits:
                frame.loc[frame["ts_code"].isin(hits), "composite"] = np.nan
        # Value-trap exclusion layer (after merge, before neutralization).
        if apply_vt:
            frame.loc[frame["deter_any2"].eq(1), "composite"] = np.nan
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
                        default=Path("output/analysis_fundamental/a_share_value_quality_monthly_strategy_v14_value_trap_t5_filter"))
    args = parser.parse_args()
    out = args.output_dir
    if out.exists() and any(out.iterdir()):
        raise FileExistsError(f"Refusing to overwrite existing experiment output: {out}")
    out.mkdir(parents=True, exist_ok=True)

    qlib.init(provider_uri=str(QLIB_DIR), region=REG_CN)
    calendar = pd.DatetimeIndex(pd.to_datetime(pd.read_csv(QLIB_DIR / "calendars" / "day.txt", header=None)[0]))

    print("[1/8] Loading extended financials (+YoY), grid, events ...", flush=True)
    fin = load_financials_with_yoy()
    grid, size_daily = build_daily_grid()
    print(f"      months={len(grid)} {grid['rebalance_date'].min().date()} .. {grid['rebalance_date'].max().date()}", flush=True)

    industry = pd.read_csv(STYLE_DIR / "industry_l1_effective_intervals.csv.gz", compression="gzip", dtype=str)
    industry["in_date"] = pd.to_datetime(industry["in_date"], errors="coerce")
    industry["out_date"] = pd.to_datetime(industry["out_date"], errors="coerce")
    st = pd.read_csv(ST_INTERVALS, compression="gzip", parse_dates=["start_date", "end_date"])
    universe_codes = sorted(size_daily["ts_code"].unique())
    amount_avg = load_amount_avg(universe_codes, calendar)

    print("      loading T5 跌幅上榜 events ...", flush=True)
    t5_events = load_t5_events()
    t5_by_rebalance = build_event_sets(t5_events, calendar, list(grid["rebalance_date"]))
    print(f"      t5 events={len(t5_events)}  rebalance days with hits={sum(1 for v in t5_by_rebalance.values() if v)}", flush=True)

    print("[2/8] Building baseline snapshots ...", flush=True)
    base_snaps = build_snapshots(fin, grid, industry, size_daily, st, amount_avg,
                                 apply_vt=False, exclude_by_rebalance=None)
    print(f"      baseline valid months={len(base_snaps)}", flush=True)
    print("[3/8] Building vt-only snapshots ...", flush=True)
    vt_snaps = build_snapshots(fin, grid, industry, size_daily, st, amount_avg,
                               apply_vt=True, exclude_by_rebalance=None)
    print(f"      vt valid months={len(vt_snaps)}", flush=True)
    print("[4/8] Building t5-only snapshots ...", flush=True)
    t5_snaps = build_snapshots(fin, grid, industry, size_daily, st, amount_avg,
                               apply_vt=False, exclude_by_rebalance=t5_by_rebalance)
    print(f"      t5 valid months={len(t5_snaps)}", flush=True)
    print("[5/8] Building combined (vt+t5) snapshots ...", flush=True)
    both_snaps = build_snapshots(fin, grid, industry, size_daily, st, amount_avg,
                                 apply_vt=True, exclude_by_rebalance=t5_by_rebalance)
    print(f"      combined valid months={len(both_snaps)}", flush=True)

    print("[6/8] Building signals ...", flush=True)
    signals = {
        "baseline": signal_from_snapshots(base_snaps, calendar),
        "vt": signal_from_snapshots(vt_snaps, calendar),
        "t5": signal_from_snapshots(t5_snaps, calendar),
        "vt+t5": signal_from_snapshots(both_snaps, calendar),
    }
    for name, sig in signals.items():
        print(f"      {name}: signal rows={len(sig)}", flush=True)

    print("[7/8] Backtesting all arms ...", flush=True)
    frames = []
    for name, sig in signals.items():
        bt = run_backtest(sig)
        bt["arm"] = name
        frames.append(bt)
    bt = pd.concat(frames, ignore_index=True)
    bt.to_csv(out / "backtest_summary.csv", index=False)

    pivot = bt.pivot_table(
        index=["stage", "cost_scenario"], columns="arm",
        values=["net_excess_annualized_return", "net_excess_ir", "net_excess_max_drawdown"],
    )
    print(pivot.to_string())

    print("[8/8] Decision ...", flush=True)
    def pick(arm: str, stage: str, scenario: str, column: str) -> float:
        row = bt[(bt["arm"].eq(arm)) & (bt["stage"].eq(stage)) & (bt["cost_scenario"].eq(scenario))]
        return float(row[column].iloc[0]) if len(row) else np.nan

    def deltas(arm: str) -> dict:
        return {
            "holdout_delta_pp": (pick(arm, "holdout", "stress", "net_excess_annualized_return")
                                 - pick("baseline", "holdout", "stress", "net_excess_annualized_return")) * 100,
            "new_coverage_delta_pp": (pick(arm, "new_coverage", "stress", "net_excess_annualized_return")
                                      - pick("baseline", "new_coverage", "stress", "net_excess_annualized_return")) * 100,
        }

    vt_d = deltas("vt")
    t5_d = deltas("t5")
    both_d = deltas("vt+t5")

    holdout_ok = bool(both_d["holdout_delta_pp"] >= -0.5)
    new_coverage_ok = bool(both_d["new_coverage_delta_pp"] >= 5.0)

    # Combined vs best single filter (t5) incremental contribution.
    both_vs_t5 = both_d["new_coverage_delta_pp"] - t5_d["new_coverage_delta_pp"]

    if holdout_ok and new_coverage_ok:
        decision = "combined_filter_adopted"
    elif holdout_ok and not new_coverage_ok:
        decision = "combined_filter_neutral_holdout_ok"
    elif not holdout_ok and new_coverage_ok:
        decision = "combined_filter_holdout_erosion"
    else:
        decision = "combined_filter_not_adopted"

    decision_json = {
        "decision": decision,
        "baseline_holdout_stress_net": pick("baseline", "holdout", "stress", "net_excess_annualized_return"),
        "vt_holdout_stress_net": pick("vt", "holdout", "stress", "net_excess_annualized_return"),
        "t5_holdout_stress_net": pick("t5", "holdout", "stress", "net_excess_annualized_return"),
        "combined_holdout_stress_net": pick("vt+t5", "holdout", "stress", "net_excess_annualized_return"),
        "baseline_new_coverage_stress_net": pick("baseline", "new_coverage", "stress", "net_excess_annualized_return"),
        "vt_new_coverage_stress_net": pick("vt", "new_coverage", "stress", "net_excess_annualized_return"),
        "t5_new_coverage_stress_net": pick("t5", "new_coverage", "stress", "net_excess_annualized_return"),
        "combined_new_coverage_stress_net": pick("vt+t5", "new_coverage", "stress", "net_excess_annualized_return"),
        "combined_holdout_delta_pp": both_d["holdout_delta_pp"],
        "combined_new_coverage_delta_pp": both_d["new_coverage_delta_pp"],
        "combined_vs_t5_new_coverage_delta_pp": both_vs_t5,
        "holdout_ok": holdout_ok,
        "new_coverage_ok": new_coverage_ok,
        "reference_vt_deltas": vt_d,
        "reference_t5_deltas": t5_d,
        "top_k": TOP_K,
    }
    (out / "decision.json").write_text(json.dumps(decision_json, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    methodology = {
        "protocols": [
            "research/protocols/a_share_value_trap_identification_protocol_v1.md",
            "research/protocols/a_share_negative_event_subtype_protocol_v1.md",
        ],
        "arms": {
            "baseline": "v8 top-15 identical rules",
            "vt": "baseline + exclude deter_any2==1 (financial YoY<0 >=2 of 3)",
            "t5": "baseline + exclude 跌幅上榜 events within 20 trading days",
            "vt+t5": "baseline + both filters",
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
        "价值陷阱 + T5 负面事件双过滤叠加回测 v14",
        "=" * 64,
        "四臂对比（压力费后净超额，相对 SH000852）：",
        bt.pivot_table(index=["stage", "cost_scenario"], columns="arm",
                       values=["net_excess_annualized_return", "net_excess_ir", "net_excess_max_drawdown"]).to_string(),
        "",
        f"vs 基线：holdout delta {both_d['holdout_delta_pp']:+.2f}pp (门槛 >=-0.5 → {'通过' if holdout_ok else '不通过'})；"
        f"new_coverage delta {both_d['new_coverage_delta_pp']:+.2f}pp (门槛 >=+5 → {'通过' if new_coverage_ok else '不通过'})",
        f"叠加 vs T5 单层（new_coverage 增量）：{both_vs_t5:+.2f}pp",
        "",
        f"判定：{decision}",
    ]
    (out / "strategy_report.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("\n".join(lines))


if __name__ == "__main__":
    main()
