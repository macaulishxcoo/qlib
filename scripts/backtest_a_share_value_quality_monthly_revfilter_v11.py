#!/usr/bin/env python3
"""Short-term return reversal filter experiment (protocol v11).

Identical to v8 (daily-grid, four-factor composite, neutralization, ST/capacity
filters, cost model, execution) with one change: after computing neutral_composite
but before top-15 selection, stocks with past-20-day return > +20% are excluded
from the candidate pool (replaced by rank 16, 17, ...).

This tests whether filtering out "overbought" candidates reduces drawdown without
harming alpha.  Signal construction and TopkDropoutStrategy are unchanged --
excluded stocks get neutral_composite = NaN, so they never enter the top-15.

Protocol: research/protocols/a_share_value_quality_monthly_strategy_protocol_v11.md
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
from backtest_a_share_value_quality_monthly_sensitivity_v4 import load_amount_avg
from run_daily_signal_pipeline_v1 import st_codes_at, qlib_symbol

TOP_K = 15
SLACK = 5                      # extra candidates as replacement pool
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

# Filter parameters (frozen by protocol)
RET_WINDOW = 20                # past trading days for return calculation
OVERBOUGHT_THRESHOLD = 0.20    # exclude candidates with past-20d return > +20%


def compute_short_term_return_lookup(snapshots: dict, cal: pd.DatetimeIndex) -> dict:
    """Pre-compute past-20-day return for top-(K+SLACK) candidates at each rebalance date.

    Returns {rebalance_date: {qlib_instrument_id: past_20d_return}}.
    Pattern mirrors v10's compute_vol_lookup.
    """
    # Collect all candidate codes (top K+SLACK per month)
    all_codes = set()
    candidates_by_month = {}
    for date, frame in snapshots.items():
        top = frame.dropna(subset=["neutral_composite"]).nlargest(TOP_K + SLACK, "neutral_composite")
        codes = list(top["ts_code"])
        candidates_by_month[date] = codes
        all_codes.update(codes)

    if not all_codes:
        return {}

    qlib_codes = [qlib_symbol(c) for c in sorted(all_codes)]
    print(f"      loading $close for {len(qlib_codes)} stocks ...", flush=True)

    frames = []
    warm_start = BT_START - pd.Timedelta(days=120)
    for year in range(warm_start.year, BT_END.year + 1):
        df = D.features(qlib_codes, ["$close"], start_time=f"{year}-01-01", end_time=f"{year}-12-31", freq="day")
        frames.append(df)
    raw = pd.concat(frames)["$close"].unstack(level="instrument")
    raw.columns = [f"{c[2:]}.{c[:2]}" for c in raw.columns]
    raw = raw.reindex(cal)

    # For each rebalance date, compute past-20-day return for each candidate
    ret_lookup = {}
    total_excluded = 0
    for date, codes in candidates_by_month.items():
        pos = cal.get_loc(date)
        if pos < RET_WINDOW:
            ret_lookup[date] = {}
            continue
        past_pos = pos - RET_WINDOW
        ret_map = {}
        for code in codes:
            if code in raw.columns:
                p0 = raw.iloc[past_pos].get(code, np.nan)
                p1 = raw.iloc[pos].get(code, np.nan)
                if pd.notna(p0) and pd.notna(p1) and p0 > 0:
                    ret = p1 / p0 - 1.0
                    ret_map[qlib_symbol(code)] = float(ret)
                    if ret > OVERBOUGHT_THRESHOLD:
                        total_excluded += 1
        ret_lookup[date] = ret_map

    print(f"      total overbought exclusions (>{OVERBOUGHT_THRESHOLD:+.0%}): {total_excluded} "
          f"across {len(ret_lookup)} months", flush=True)
    return ret_lookup


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path,
                        default=Path("output/analysis_fundamental/a_share_value_quality_monthly_strategy_v11_revfilter"))
    args = parser.parse_args()
    out = args.output_dir
    if out.exists() and any(out.iterdir()):
        raise FileExistsError(f"Refusing to overwrite existing experiment output: {out}")
    out.mkdir(parents=True, exist_ok=True)

    qlib.init(provider_uri=str(QLIB_DIR), region=REG_CN)
    calendar = pd.DatetimeIndex(pd.to_datetime(pd.read_csv(QLIB_DIR / "calendars" / "day.txt", header=None)[0]))

    from backtest_a_share_value_quality_monthly_dailygrid_v6 import build_daily_grid

    print("[1/7] Loading extended financials & daily grid ...", flush=True)
    fin = load_financials_extended()
    grid, size_daily = build_daily_grid()
    print(f"      months={len(grid)} {grid['rebalance_date'].min().date()} .. {grid['rebalance_date'].max().date()}", flush=True)

    industry = pd.read_csv(STYLE_DIR / "industry_l1_effective_intervals.csv.gz", compression="gzip", dtype=str)
    industry["in_date"] = pd.to_datetime(industry["in_date"], errors="coerce")
    industry["out_date"] = pd.to_datetime(industry["out_date"], errors="coerce")
    st = pd.read_csv(ST_INTERVALS, compression="gzip", parse_dates=["start_date", "end_date"])
    universe_codes = sorted(size_daily["ts_code"].unique())
    amount_avg = load_amount_avg(universe_codes, calendar)

    print(f"[2/7] Building monthly factor snapshots (TOP_K={TOP_K}) ...", flush=True)
    snapshots = {}
    for _, row in grid.iterrows():
        snap = build_snapshot(fin, row, industry, size_daily)
        if snap.empty:
            continue
        frame = snap.copy()
        frame["composite"] = composite_score(frame)
        frame.loc[frame["ts_code"].isin(st_codes_at(st, row.asof_date)), "composite"] = np.nan
        avg = amount_avg.loc[row.asof_date].reindex(frame["ts_code"]).to_numpy(dtype=float) * 1000.0
        min_amount = NOTIONAL / PARTICIPATION
        frame.loc[avg < min_amount, "composite"] = np.nan
        valid = frame.dropna(subset=["composite", "log_size", "l1_code"])
        if len(valid) < 50:
            continue
        resid = ols_residual(valid["composite"], valid["l1_code"], valid["log_size"])
        frame["neutral_composite"] = resid.reindex(frame.index)
        snapshots[row.rebalance_date] = frame
    print(f"      valid months={len(snapshots)}", flush=True)

    print(f"[3/7] Pre-computing {RET_WINDOW}-day returns for top-{TOP_K + SLACK} candidates ...", flush=True)
    ret_lookup = compute_short_term_return_lookup(snapshots, calendar)

    # Apply filter: mask neutral_composite for overbought candidates
    print(f"[4/7] Applying overbought filter (>{OVERBOUGHT_THRESHOLD:+.0%}) ...", flush=True)
    filtered_snapshots = {}
    exclusion_log = []
    for date, frame in snapshots.items():
        ret_map = ret_lookup.get(date, {})
        candidates = frame.dropna(subset=["neutral_composite"]).nlargest(TOP_K + SLACK, "neutral_composite")
        filtered_frame = frame.copy()
        for idx, r in candidates.iterrows():
            qc = qlib_symbol(r["ts_code"])
            past_ret = ret_map.get(qc, np.nan)
            if pd.notna(past_ret) and past_ret > OVERBOUGHT_THRESHOLD:
                filtered_frame.loc[idx, "neutral_composite"] = np.nan
                exclusion_log.append({"rebalance_date": date, "ts_code": r["ts_code"],
                                      "past_20d_ret": past_ret, "neutral_composite": r["neutral_composite"]})
        filtered_snapshots[date] = filtered_frame

    if exclusion_log:
        excl_df = pd.DataFrame(exclusion_log)
        print(f"      excluded {len(excl_df)} stock-months across {excl_df['rebalance_date'].nunique()} months", flush=True)
    else:
        print(f"      no exclusions (threshold {OVERBOUGHT_THRESHOLD:+.0%} not triggered)", flush=True)

    print("[5/7] Building daily signal ...", flush=True)
    wide = pd.DataFrame({d: f.set_index("ts_code")["neutral_composite"] for d, f in filtered_snapshots.items()}).T
    cal_win = calendar[(calendar >= BT_START) & (calendar <= BT_END)]
    wide = wide.reindex(cal_win).ffill()
    long = wide.stack().rename("score").dropna().reset_index()
    long.columns = ["datetime", "ts_code", "score"]
    long["instrument"] = long["ts_code"].map(qlib_symbol)
    signal = long.set_index(["datetime", "instrument"])["score"].sort_index()
    print(f"      signal rows={len(signal)}", flush=True)

    print("[6/7] Backtest ...", flush=True)
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
        bench_ann = float(risk_analysis(report["bench"], freq="day")["risk"]["annualized_return"])
        for stage, (s0, s1) in STAGES.items():
            sample = report.loc[s0:s1]
            if sample.empty:
                continue
            gross = risk_analysis(sample["return"] - sample["bench"], freq="day")["risk"]
            net = risk_analysis(sample["return"] - sample["bench"] - sample["cost"], freq="day")["risk"]
            bt_rows.append({
                "stage": stage, "cost_scenario": scenario,
                "start": str(sample.index.min().date()), "end": str(sample.index.max().date()),
                "trading_days": int(len(sample)),
                "gross_excess_annualized_return": float(gross["annualized_return"]),
                "gross_excess_ir": float(gross["information_ratio"]),
                "net_excess_annualized_return": float(net["annualized_return"]),
                "net_excess_ir": float(net["information_ratio"]),
                "net_excess_max_drawdown": float(net["max_drawdown"]),
                "average_daily_turnover_rate": float(sample["turnover"].mean()),
                "annualized_cost_drag": float(sample["cost"].mean() * ANNUALIZATION_DAYS),
                "benchmark_annualized_return": bench_ann,
            })
        full = report.loc[BT_START:BT_END]
        net = risk_analysis(full["return"] - full["bench"] - full["cost"], freq="day")["risk"]
        bt_rows.append({
            "stage": "full", "cost_scenario": scenario,
            "start": str(full.index.min().date()), "end": str(full.index.max().date()),
            "trading_days": int(len(full)),
            "gross_excess_annualized_return": float(risk_analysis(full["return"] - full["bench"], freq="day")["risk"]["annualized_return"]),
            "gross_excess_ir": float(risk_analysis(full["return"] - full["bench"], freq="day")["risk"]["information_ratio"]),
            "net_excess_annualized_return": float(net["annualized_return"]),
            "net_excess_ir": float(net["information_ratio"]),
            "net_excess_max_drawdown": float(net["max_drawdown"]),
            "average_daily_turnover_rate": float(full["turnover"].mean()),
            "annualized_cost_drag": float(full["cost"].mean() * ANNUALIZATION_DAYS),
            "benchmark_annualized_return": bench_ann,
        })
        hol = next(r for r in bt_rows if r["stage"] == "holdout" and r["cost_scenario"] == scenario)
        print(f"      [{scenario}] holdout net={hol['net_excess_annualized_return']:.4f} "
              f"IR={hol['net_excess_ir']:.3f} MDD={hol['net_excess_max_drawdown']:.4f}", flush=True)

    bt = pd.DataFrame(bt_rows)
    bt.to_csv(out / "backtest_summary.csv", index=False)

    # Yearly summary
    print("[7/7] Yearly summary + decision ...", flush=True)
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
        yearly_rows.append({
            "year": int(year), "trading_days": int(len(sample)),
            "net_excess_annualized_return": float(net["annualized_return"]),
            "net_excess_ir": float(net["information_ratio"]),
        })
    yearly = pd.DataFrame(yearly_rows)
    yearly.to_csv(out / "yearly_summary.csv", index=False)

    # Persist panel
    panel_rows = []
    for date, f in filtered_snapshots.items():
        item = f[["ts_code", "composite", "neutral_composite", "log_size", "l1_code"]].copy()
        item["rebalance_date"] = date
        panel_rows.append(item)
    pd.concat(panel_rows, ignore_index=True).to_csv(out / "monthly_composite_revfilter.csv.gz",
                                                    index=False, compression="gzip")

    # Save exclusion log
    if exclusion_log:
        pd.DataFrame(exclusion_log).to_csv(out / "exclusion_log.csv", index=False)

    # Decision
    hol_stress = bt[(bt["stage"].eq("holdout")) & (bt["cost_scenario"].eq("stress"))].iloc[0]
    hol_base = bt[(bt["stage"].eq("holdout")) & (bt["cost_scenario"].eq("base"))].iloc[0]
    viable = bool(hol_stress["net_excess_annualized_return"] > 0 and hol_stress["net_excess_ir"] > 0)
    improved = bool(hol_stress["net_excess_ir"] > 0.918838)  # v8 holdout stress IR
    lower_risk = bool(abs(hol_stress["net_excess_max_drawdown"]) < abs(-0.166085))  # v8 holdout stress MDD

    if viable and improved and lower_risk:
        decision = "rev_filter_improved"
    elif viable and (improved or lower_risk):
        decision = "rev_filter_partial_improvement"
    elif viable:
        decision = "rev_filter_viable_no_improvement"
    else:
        decision = "rev_filter_not_effective"

    decision_json = {
        "decision": decision,
        "holdout_stress_net": float(hol_stress["net_excess_annualized_return"]),
        "holdout_stress_ir": float(hol_stress["net_excess_ir"]),
        "holdout_stress_mdd": float(hol_stress["net_excess_max_drawdown"]),
        "v8_holdout_stress_ir_reference": 0.918838,
        "v8_holdout_stress_mdd_reference": -0.166085,
        "improved_vs_v8": bool(improved),
        "lower_risk_vs_v8": bool(lower_risk),
        "overbought_threshold": OVERBOUGHT_THRESHOLD,
        "ret_window": RET_WINDOW,
        "total_exclusions": len(exclusion_log) if exclusion_log else 0,
    }
    (out / "decision.json").write_text(json.dumps(decision_json, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    methodology = {
        "protocol": "research/protocols/a_share_value_quality_monthly_strategy_protocol_v11.md",
        "change_from_v8": f"exclude candidates with past-{RET_WINDOW}d return > {OVERBOUGHT_THRESHOLD:+.0%}",
        "ret_window": RET_WINDOW,
        "overbought_threshold": OVERBOUGHT_THRESHOLD,
        "slack": SLACK,
        "topk": TOP_K,
        "benchmark": BENCHMARK,
        "backtest_window": [str(BT_START.date()), str(BT_END.date())],
    }
    (out / "methodology.json").write_text(json.dumps(methodology, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    lines = [
        "价值/质量多因子月度策略 短期收益反转过滤 v11",
        "=" * 64,
        f"与 v8 唯一差异：排除过去{RET_WINDOW}日涨幅>{OVERBOUGHT_THRESHOLD:+.0%}的候选（替补池 {SLACK} 只）",
        f"总排除: {len(exclusion_log) if exclusion_log else 0} 股-月",
        "",
        "回测（费后均为相对 SH000852 超额）：",
        bt.pivot_table(index="stage", columns="cost_scenario",
                       values=["net_excess_annualized_return", "net_excess_ir", "net_excess_max_drawdown"])
          .to_string(),
        "",
        "分年（基准成本费后）：",
        yearly.to_string(index=False),
        "",
        f"封存期对比：v8(无过滤) +10.16%/yr IR=0.92 MDD=-16.6% -> v11(过滤) "
        f"{hol_stress['net_excess_annualized_return']*100:.2f}%/yr IR={hol_stress['net_excess_ir']:.3f} "
        f"MDD={hol_stress['net_excess_max_drawdown']*100:.1f}%",
        f"IR 改善: {'✅' if improved else '❌'} ({hol_stress['net_excess_ir']:.3f} vs 0.919)",
        f"MDD 改善: {'✅' if lower_risk else '❌'} ({hol_stress['net_excess_max_drawdown']*100:.1f}% vs -16.6%)",
        "",
        f"判定：{decision}",
        "新覆盖区(2025-07~2026-06)为观察报告，不构成验证。",
    ]
    (out / "strategy_report.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("\n".join(lines))


if __name__ == "__main__":
    main()
