#!/usr/bin/env python3
"""Five-factor + T5 + overbought dual-filter backtest v16.

Based on v15 (triple-filter), with TWO changes:
  1. Base signal is the five-factor composite (ep+bm+div+accruals+g2,
     >=4/5 gate) instead of the four-factor composite.
  2. Arms are baseline / t5 / t5+revf (NO vt layer), since v14 proved vt
     adds +4.73pp on four-factor; here we test the never-measured
     revfilter+t5 two-layer combo on the five-factor base.

Acceptance (dual arm vs baseline, same dual gate as v14/v15):
  holdout stress net excess delta >= -0.5pp AND new_coverage delta >= +5pp.
Additionally report MDD delta (v15's holdout erosion mechanism re-test).

Protocol: research/protocols/a_share_value_growth_five_factor_strategy_protocol_v16.md
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
FIN_TOP = Path("data/external/tushare/a_share_financial_pit_v1/normalized/fina_indicator.csv.gz")


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
    """Five-factor rank-mean with >=4-of-5 non-missing gate (same as v2)."""
    factors = ("ep", "bm", "div_yield", "accruals", "g2")
    ranks = pd.concat([frame[f].rank(method="first", pct=True) for f in factors], axis=1)
    n_factors = ranks.notna().sum(axis=1)
    composite = ranks.mean(axis=1)
    composite[n_factors < 4] = np.nan
    return composite


def build_snapshots(fin, fin_g2, grid, industry, size_daily, st, amount_avg,
                    exclude_by_rebalance: dict[pd.Timestamp, set[str]] | None) -> dict:
    """Five-factor snapshots with optional T5 exclusion (mask composite5)."""
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
        frame.loc[avg < NOTIONAL / PARTICIPATION, "composite5"] = np.nan
        if exclude_by_rebalance is not None:
            hits = exclude_by_rebalance.get(row.rebalance_date, set())
            if hits:
                frame.loc[frame.index.isin(hits), "composite5"] = np.nan
        valid = frame.dropna(subset=["composite5", "log_size", "l1_code"])
        if len(valid) < 50:
            continue
        resid = ols_residual(valid["composite5"], valid["l1_code"], valid["log_size"])
        frame["neutral_composite"] = resid.reindex(frame.index)
        snapshots[row.rebalance_date] = frame.reset_index()
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
            net = risk_analysis(sample["return"] - sample["bench"] - sample["cost"], freq="day")["risk"]
            bt_rows.append({
                "stage": stage, "cost_scenario": scenario,
                "trading_days": int(len(sample)),
                "net_excess_annualized_return": float(net["annualized_return"]),
                "net_excess_ir": float(net["information_ratio"]),
                "net_excess_max_drawdown": float(net["max_drawdown"]),
                "average_daily_turnover_rate": float(sample["turnover"].mean()),
            })
    return pd.DataFrame(bt_rows)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path,
                        default=Path("output/analysis_fundamental/a_share_value_growth_five_factor_strategy_v16_t5_revf"))
    args = parser.parse_args()
    out = args.output_dir
    if out.exists() and any(out.iterdir()):
        raise FileExistsError(f"Refusing to overwrite existing experiment output: {out}")
    out.mkdir(parents=True, exist_ok=True)

    qlib.init(provider_uri=str(QLIB_DIR), region=REG_CN)
    calendar = pd.DatetimeIndex(pd.to_datetime(pd.read_csv(QLIB_DIR / "calendars" / "day.txt", header=None)[0]))

    print("[1/7] Loading data ...", flush=True)
    fin = load_financials_extended()
    fin_g2 = load_g2()
    grid, size_daily = build_daily_grid()
    industry = pd.read_csv(STYLE_DIR / "industry_l1_effective_intervals.csv.gz", compression="gzip", dtype=str)
    industry["in_date"] = pd.to_datetime(industry["in_date"], errors="coerce")
    industry["out_date"] = pd.to_datetime(industry["out_date"].astype(str).str.replace("-", "", regex=False),
                                          format="%Y%m%d", errors="coerce") if industry["out_date"].dtype == object else pd.to_datetime(industry["out_date"], errors="coerce")
    industry["out_date"] = pd.to_datetime(industry["out_date"], errors="coerce")
    st = pd.read_csv(ST_INTERVALS, compression="gzip", parse_dates=["start_date", "end_date"])
    universe_codes = sorted(size_daily["ts_code"].unique())
    amount_avg = load_amount_avg(universe_codes, calendar)
    t5_events = load_t5_events()
    t5_by_rebalance = build_event_sets(t5_events, calendar, list(grid["rebalance_date"]))
    print(f"      months={len(grid)} t5 events={len(t5_events)}", flush=True)

    print("[2/7] Baseline (five-factor, no filter) snapshots ...", flush=True)
    base_snaps = build_snapshots(fin, fin_g2, grid, industry, size_daily, st, amount_avg, None)
    print(f"      baseline valid months={len(base_snaps)}", flush=True)

    print("[3/7] T5-only snapshots ...", flush=True)
    t5_snaps = build_snapshots(fin, fin_g2, grid, industry, size_daily, st, amount_avg, t5_by_rebalance)
    print(f"      t5 valid months={len(t5_snaps)}", flush=True)

    print("[4/7] Applying overbought filter on t5 (dual arm) ...", flush=True)
    dual_snaps, excl_log = apply_overbought_filter(t5_snaps, calendar)
    if excl_log:
        excl = pd.DataFrame(excl_log)
        print(f"      overbought exclusions: {len(excl)} stock-months across {excl['rebalance_date'].nunique()} months", flush=True)
        excl.to_csv(out / "overbought_exclusion_log.csv", index=False)
    else:
        print("      no overbought exclusions", flush=True)

    print("[5/7] Signals ...", flush=True)
    signals = {
        "baseline": signal_from_snapshots(base_snaps, calendar),
        "t5": signal_from_snapshots(t5_snaps, calendar),
        "t5+revf": signal_from_snapshots(dual_snaps, calendar),
    }
    for name, sig in signals.items():
        print(f"      {name}: rows={len(sig)}", flush=True)

    print("[6/7] Backtesting ...", flush=True)
    frames = []
    for name, sig in signals.items():
        bt = run_backtest(sig)
        bt["arm"] = name
        frames.append(bt)
    bt = pd.concat(frames, ignore_index=True)
    bt.to_csv(out / "backtest_summary.csv", index=False)
    print(bt.pivot_table(index=["stage", "cost_scenario"], columns="arm",
                         values=["net_excess_annualized_return", "net_excess_ir", "net_excess_max_drawdown"]).to_string())

    print("[7/7] Decision ...", flush=True)
    def pick(arm: str, stage: str, scenario: str, column: str) -> float:
        row = bt[(bt["arm"].eq(arm)) & (bt["stage"].eq(stage)) & (bt["cost_scenario"].eq(scenario))]
        return float(row[column].iloc[0]) if len(row) else np.nan

    hol_b = pick("baseline", "holdout", "stress", "net_excess_annualized_return")
    hol_t5 = pick("t5", "holdout", "stress", "net_excess_annualized_return")
    hol_d = pick("t5+revf", "holdout", "stress", "net_excess_annualized_return")
    new_b = pick("baseline", "new_coverage", "stress", "net_excess_annualized_return")
    new_t5 = pick("t5", "new_coverage", "stress", "net_excess_annualized_return")
    new_d = pick("t5+revf", "new_coverage", "stress", "net_excess_annualized_return")
    mdd_b = pick("baseline", "holdout", "stress", "net_excess_max_drawdown")
    mdd_t5 = pick("t5", "holdout", "stress", "net_excess_max_drawdown")
    mdd_d = pick("t5+revf", "holdout", "stress", "net_excess_max_drawdown")

    hol_delta = hol_d - hol_b
    new_delta = new_d - new_b
    revf_increment = new_d - new_t5  # revfilter's independent contribution on top of t5
    holdout_ok = bool(hol_delta >= -0.005)
    new_coverage_ok = bool(new_delta >= 0.05)

    if holdout_ok and new_coverage_ok:
        decision = "dual_filter_adopted"
    elif holdout_ok and not new_coverage_ok:
        decision = "dual_filter_neutral_holdout_ok"
    elif not holdout_ok and new_coverage_ok:
        decision = "holdout_erosion_closed"
    else:
        decision = "dual_filter_not_adopted"

    decision_json = {
        "decision": decision,
        "baseline_holdout_stress_net": hol_b,
        "t5_holdout_stress_net": hol_t5,
        "dual_holdout_stress_net": hol_d,
        "dual_holdout_delta_pp": hol_delta * 100,
        "baseline_new_coverage_stress_net": new_b,
        "t5_new_coverage_stress_net": new_t5,
        "dual_new_coverage_stress_net": new_d,
        "dual_new_coverage_delta_pp": new_delta * 100,
        "revf_increment_on_t5_pp": revf_increment * 100,
        "baseline_holdout_mdd": mdd_b,
        "t5_holdout_mdd": mdd_t5,
        "dual_holdout_mdd": mdd_d,
        "holdout_ok": holdout_ok,
        "new_coverage_ok": new_coverage_ok,
        "top_k": TOP_K,
        "revfilter_params": {"ret_window": RET_WINDOW, "overbought_threshold": OVERBOUGHT_THRESHOLD, "slack": SLACK},
        "v15_reference": "four-factor triple holdout erosion -1.18pp / MDD -33.0%",
    }
    (out / "decision.json").write_text(json.dumps(decision_json, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    methodology = {
        "protocol": "research/protocols/a_share_value_growth_five_factor_strategy_protocol_v16.md",
        "base_signal": "five-factor composite (ep,bm,div_yield,accruals,g2), >=4/5 gate",
        "arms": {
            "baseline": "five-factor, no filter (= v2)",
            "t5": "five-factor + T5 跌幅上榜 20d 剔除 (mask composite5)",
            "t5+revf": "t5 + 超买剔除 top(K+SLACK) past-20d ret>+20% (mask neutral_composite)",
        },
        "topk": TOP_K,
        "execution": "TopkDropout t+1 open; limit_threshold 0.095; min_cost 5",
        "cost_scenarios": COST_SCENARIOS,
        "benchmark": BENCHMARK,
        "created_at_utc": pd.Timestamp.utcnow().isoformat(),
    }
    (out / "methodology.json").write_text(json.dumps(methodology, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    lines = [
        "五因子 + T5 + 超买 双层过滤回测 v16",
        "=" * 64,
        "三臂对比（压力费后净超额，相对 SH000852）：",
        bt.pivot_table(index=["stage", "cost_scenario"], columns="arm",
                       values=["net_excess_annualized_return", "net_excess_ir", "net_excess_max_drawdown"]).to_string(),
        "",
        f"双层 vs 基线：holdout {hol_delta*100:+.2f}pp (>=−0.5 -> {'通过' if holdout_ok else '不通过'})；"
        f"new_coverage {new_delta*100:+.2f}pp (>=+5 -> {'通过' if new_coverage_ok else '不通过'})",
        f"revfilter 在 t5 之上的独立增量：new_coverage {revf_increment*100:+.2f}pp",
        f"MDD：基线 {mdd_b*100:.1f}% -> t5 {mdd_t5*100:.1f}% -> 双层 {mdd_d*100:.1f}%",
        "",
        f"判定：{decision}",
    ]
    (out / "strategy_report.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("\n".join(lines))


if __name__ == "__main__":
    main()
