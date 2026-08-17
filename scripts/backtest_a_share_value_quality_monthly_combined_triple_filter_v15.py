#!/usr/bin/env python3
"""Triple-filter combined backtest v15: value-trap + T5 + overbought(revfilter).

Arms (one data-loading environment):
  baseline     : v8 top-15 identical rules
  vt+t5        : value-trap (deter_any2) + T5 (跌幅上榜) exclusions (v14 adopted)
  vt+t5+revf   : vt+t5 + overbought filter (past-20d ret > +20% among top K+SLACK)

Core question: does adding the overbought filter (which improved MDD -16.6% ->
-13.9% alone) tighten the v14 combined MDD (-27.6%) while keeping most of the
new_coverage improvement (+25.06pp)?

Acceptance (combined arm vs baseline, same dual gate):
  holdout stress net excess >= -0.5pp AND new_coverage stress net excess >= +5pp.
Additionally report the MDD delta triple vs double (the point of this experiment).

Protocols:
  research/protocols/a_share_value_trap_identification_protocol_v1.md
  research/protocols/a_share_negative_event_subtype_protocol_v1.md
  research/protocols/a_share_value_quality_monthly_strategy_protocol_v11.md (revfilter)
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
from backtest_a_share_value_quality_monthly_revfilter_v11 import (
    compute_short_term_return_lookup,
    RET_WINDOW,
    OVERBOUGHT_THRESHOLD,
    SLACK,
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
    """Identical to v14 build_snapshots."""
    snapshots = {}
    for _, row in grid.iterrows():
        snap = build_snapshot(fin, row, industry, size_daily)
        if snap.empty:
            continue
        frame = snap.copy()
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
        if exclude_by_rebalance is not None:
            hits = exclude_by_rebalance.get(row.rebalance_date, set())
            if hits:
                frame.loc[frame["ts_code"].isin(hits), "composite"] = np.nan
        if apply_vt:
            frame.loc[frame["deter_any2"].eq(1), "composite"] = np.nan
        valid = frame.dropna(subset=["composite", "log_size", "l1_code"])
        if len(valid) < 50:
            continue
        resid = ols_residual(valid["composite"], valid["l1_code"], valid["log_size"])
        frame["neutral_composite"] = resid.reindex(frame.index)
        snapshots[row.rebalance_date] = frame
    return snapshots


def apply_overbought_filter(snapshots: dict, calendar: pd.DatetimeIndex) -> tuple[dict, list]:
    """Mask neutral_composite for top-(K+SLACK) candidates with past-20d ret > threshold."""
    ret_lookup = compute_short_term_return_lookup(snapshots, calendar)
    filtered = {}
    exclusion_log = []
    for date, frame in snapshots.items():
        ret_map = ret_lookup.get(date, {})
        candidates = frame.dropna(subset=["neutral_composite"]).nlargest(TOP_K + SLACK, "neutral_composite")
        f = frame.copy()
        for idx, r in candidates.iterrows():
            past_ret = ret_map.get(qlib_symbol(r["ts_code"]), np.nan)
            if pd.notna(past_ret) and past_ret > OVERBOUGHT_THRESHOLD:
                f.loc[idx, "neutral_composite"] = np.nan
                exclusion_log.append({"rebalance_date": date, "ts_code": r["ts_code"], "past_20d_ret": past_ret})
        filtered[date] = f
    return filtered, exclusion_log


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
                        default=Path("output/analysis_fundamental/a_share_value_quality_monthly_strategy_v15_triple_filter"))
    args = parser.parse_args()
    out = args.output_dir
    if out.exists() and any(out.iterdir()):
        raise FileExistsError(f"Refusing to overwrite existing experiment output: {out}")
    out.mkdir(parents=True, exist_ok=True)

    qlib.init(provider_uri=str(QLIB_DIR), region=REG_CN)
    calendar = pd.DatetimeIndex(pd.to_datetime(pd.read_csv(QLIB_DIR / "calendars" / "day.txt", header=None)[0]))

    print("[1/8] Loading financials (+YoY), grid, T5 events ...", flush=True)
    fin = load_financials_with_yoy()
    grid, size_daily = build_daily_grid()
    industry = pd.read_csv(STYLE_DIR / "industry_l1_effective_intervals.csv.gz", compression="gzip", dtype=str)
    industry["in_date"] = pd.to_datetime(industry["in_date"], errors="coerce")
    industry["out_date"] = pd.to_datetime(industry["out_date"], errors="coerce")
    st = pd.read_csv(ST_INTERVALS, compression="gzip", parse_dates=["start_date", "end_date"])
    universe_codes = sorted(size_daily["ts_code"].unique())
    amount_avg = load_amount_avg(universe_codes, calendar)
    t5_events = load_t5_events()
    t5_by_rebalance = build_event_sets(t5_events, calendar, list(grid["rebalance_date"]))
    print(f"      months={len(grid)} t5 events={len(t5_events)}", flush=True)

    print("[2/8] Baseline snapshots ...", flush=True)
    base_snaps = build_snapshots(fin, grid, industry, size_daily, st, amount_avg, False, None)
    print(f"      baseline valid months={len(base_snaps)}", flush=True)
    print("[3/8] vt+t5 snapshots ...", flush=True)
    double_snaps = build_snapshots(fin, grid, industry, size_daily, st, amount_avg, True, t5_by_rebalance)
    print(f"      vt+t5 valid months={len(double_snaps)}", flush=True)

    print("[4/8] Applying overbought filter on vt+t5 (triple arm) ...", flush=True)
    triple_snaps, excl_log = apply_overbought_filter(double_snaps, calendar)
    if excl_log:
        excl = pd.DataFrame(excl_log)
        print(f"      overbought exclusions: {len(excl)} stock-months across {excl['rebalance_date'].nunique()} months", flush=True)
        excl.to_csv(out / "overbought_exclusion_log.csv", index=False)
    else:
        print("      no overbought exclusions", flush=True)

    print("[5/8] Signals ...", flush=True)
    signals = {
        "baseline": signal_from_snapshots(base_snaps, calendar),
        "vt+t5": signal_from_snapshots(double_snaps, calendar),
        "vt+t5+revf": signal_from_snapshots(triple_snaps, calendar),
    }
    for name, sig in signals.items():
        print(f"      {name}: rows={len(sig)}", flush=True)

    print("[6/8] Backtesting ...", flush=True)
    frames = []
    for name, sig in signals.items():
        bt = run_backtest(sig)
        bt["arm"] = name
        frames.append(bt)
    bt = pd.concat(frames, ignore_index=True)
    bt.to_csv(out / "backtest_summary.csv", index=False)
    print(bt.pivot_table(index=["stage", "cost_scenario"], columns="arm",
                         values=["net_excess_annualized_return", "net_excess_ir", "net_excess_max_drawdown"]).to_string())

    print("[7/8] Decision ...", flush=True)
    def pick(arm: str, stage: str, scenario: str, column: str) -> float:
        row = bt[(bt["arm"].eq(arm)) & (bt["stage"].eq(stage)) & (bt["cost_scenario"].eq(scenario))]
        return float(row[column].iloc[0]) if len(row) else np.nan

    hol_b = pick("baseline", "holdout", "stress", "net_excess_annualized_return")
    hol_d = pick("vt+t5", "holdout", "stress", "net_excess_annualized_return")
    hol_t = pick("vt+t5+revf", "holdout", "stress", "net_excess_annualized_return")
    new_b = pick("baseline", "new_coverage", "stress", "net_excess_annualized_return")
    new_d = pick("vt+t5", "new_coverage", "stress", "net_excess_annualized_return")
    new_t = pick("vt+t5+revf", "new_coverage", "stress", "net_excess_annualized_return")
    mdd_d = pick("vt+t5", "holdout", "stress", "net_excess_max_drawdown")
    mdd_t = pick("vt+t5+revf", "holdout", "stress", "net_excess_max_drawdown")

    hol_delta = hol_t - hol_b
    new_delta = new_t - new_b
    holdout_ok = bool(hol_delta >= -0.005)
    new_coverage_ok = bool(new_delta >= 0.05)
    mdd_improved_vs_double = bool(mdd_t > mdd_d)  # higher = shallower drawdown

    if holdout_ok and new_coverage_ok:
        decision = "triple_filter_adopted"
    elif holdout_ok and not new_coverage_ok:
        decision = "triple_filter_neutral_holdout_ok"
    elif not holdout_ok and new_coverage_ok:
        decision = "triple_filter_holdout_erosion"
    else:
        decision = "triple_filter_not_adopted"

    decision_json = {
        "decision": decision,
        "baseline_holdout_stress_net": hol_b,
        "double_holdout_stress_net": hol_d,
        "triple_holdout_stress_net": hol_t,
        "triple_holdout_delta_pp": hol_delta * 100,
        "baseline_new_coverage_stress_net": new_b,
        "double_new_coverage_stress_net": new_d,
        "triple_new_coverage_stress_net": new_t,
        "triple_new_coverage_delta_pp": new_delta * 100,
        "double_holdout_mdd": mdd_d,
        "triple_holdout_mdd": mdd_t,
        "mdd_improved_vs_double": mdd_improved_vs_double,
        "holdout_ok": holdout_ok,
        "new_coverage_ok": new_coverage_ok,
        "top_k": TOP_K,
        "revfilter_params": {"ret_window": RET_WINDOW, "overbought_threshold": OVERBOUGHT_THRESHOLD, "slack": SLACK},
    }
    (out / "decision.json").write_text(json.dumps(decision_json, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    methodology = {
        "protocols": [
            "research/protocols/a_share_value_trap_identification_protocol_v1.md",
            "research/protocols/a_share_negative_event_subtype_protocol_v1.md",
            "research/protocols/a_share_value_quality_monthly_strategy_protocol_v11.md",
        ],
        "arms": {
            "baseline": "v8 top-15",
            "vt+t5": "v8 + deter_any2 + 跌幅上榜 20d 剔除（v14 采用组合）",
            "vt+t5+revf": "vt+t5 + 候选 top(K+SLACK) 中 past-20d ret>+20% 剔除",
        },
        "topk": TOP_K,
        "execution": "TopkDropout t+1 open; limit_threshold 0.095; min_cost 5",
        "cost_scenarios": COST_SCENARIOS,
        "benchmark": BENCHMARK,
        "created_at_utc": pd.Timestamp.utcnow().isoformat(),
    }
    (out / "methodology.json").write_text(json.dumps(methodology, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    lines = [
        "三过滤叠加回测 v15（价值陷阱 + T5 + 超买剔除）",
        "=" * 64,
        "三臂对比（压力费后净超额，相对 SH000852）：",
        bt.pivot_table(index=["stage", "cost_scenario"], columns="arm",
                       values=["net_excess_annualized_return", "net_excess_ir", "net_excess_max_drawdown"]).to_string(),
        "",
        f"三层 vs 基线：holdout {hol_delta*100:+.2f}pp (>=−0.5 → {'通过' if holdout_ok else '不通过'})；"
        f"new_coverage {new_delta*100:+.2f}pp (>=+5 → {'通过' if new_coverage_ok else '不通过'})",
        f"MDD：双层 {mdd_d*100:.1f}% → 三层 {mdd_t*100:.1f}% （revfilter 收窄 MDD → {'是' if mdd_improved_vs_double else '否'}）",
        "",
        f"判定：{decision}",
    ]
    (out / "strategy_report.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("\n".join(lines))


if __name__ == "__main__":
    main()
