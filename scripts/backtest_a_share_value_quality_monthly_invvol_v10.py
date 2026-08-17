#!/usr/bin/env python3
"""Inverse-volatility weighting experiment (protocol v10).

Identical to v8 (daily-grid, four-factor composite, neutralization, ST/capacity
filters, cost model, execution) with one change: portfolio weights are
proportional to 1/sigma (60-day rolling volatility of daily returns) instead of
equal-weight.  Uses WeightStrategyBase instead of TopkDropoutStrategy so that
per-stock weights are honored by the backtest engine.

Protocol: research/protocols/a_share_value_quality_monthly_strategy_protocol_v10.md
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
from qlib.contrib.strategy.signal_strategy import WeightStrategyBase

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

# Volatility parameters (frozen by protocol)
VOL_WINDOW = 60          # trading days
VOL_MIN_PERIODS = 40     # minimum non-NaN returns required


class InverseVolWeightStrategy(WeightStrategyBase):
    """WeightStrategyBase subclass: top-k selection by score, weights ∝ 1/σ.

    The signal (neutral_composite) is used purely for ranking/selection (same as
    TopkDropoutStrategy).  Once the top-k are chosen, weights are assigned
    inversely proportional to each stock's pre-computed 60-day volatility.
    """

    def __init__(self, *, top_k: int, vol_lookup: dict, **kwargs):
        super().__init__(**kwargs)
        self.top_k = top_k
        self.vol_lookup = vol_lookup  # {pd.Timestamp: {qlib_instrument_id: vol}}

    def generate_target_weight_position(self, score, current, trade_start_time, trade_end_time):
        """Return {stock_id: weight} for the top-k stocks, weighted by 1/sigma."""
        if score is None or len(score) == 0:
            return {}

        # Rank and select top-k (score is a pd.Series indexed by stock_id)
        ranked = score.sort_values(ascending=False)
        top_codes = ranked.head(self.top_k).index.tolist()

        # Look up volatilities for this rebalance date
        # trade_start_time is the execution date (T+1); the signal was generated
        # on trade_start_time's previous trading day.  The vol_lookup is keyed
        # by the rebalance date (= signal date = T).  We need to find which
        # rebalance date maps to this trade date.
        trade_date = pd.Timestamp(trade_start_time)
        # Find the most recent rebalance date <= trade_date
        rebal_dates = sorted(self.vol_lookup.keys())
        sig_date = None
        for d in reversed(rebal_dates):
            if d <= trade_date:
                sig_date = d
                break
        if sig_date is None:
            return {}

        vol_map = self.vol_lookup.get(sig_date, {})

        # Compute inverse-vol weights
        inv_vols = {}
        for code in top_codes:
            vol = vol_map.get(code, np.nan)
            if pd.notna(vol) and vol > 0:
                inv_vols[code] = 1.0 / vol
            # else: skip (weight 0)

        if not inv_vols:
            # Fallback: equal weight if all vols missing
            w = 1.0 / len(top_codes)
            return {code: w for code in top_codes}

        total = sum(inv_vols.values())
        return {code: inv_vols[code] / total for code in inv_vols}


def compute_vol_lookup(snapshots: dict, cal: pd.DatetimeIndex) -> dict:
    """Pre-compute 60-day rolling volatility for top-15 stocks at each rebalance date.

    Returns {rebalance_date: {qlib_instrument_id: vol_std}}.
    """
    # Collect all top-15 codes across all months
    all_codes = set()
    top15_by_month = {}
    for date, frame in snapshots.items():
        top = frame.dropna(subset=["neutral_composite"]).nlargest(TOP_K, "neutral_composite")
        codes = list(top["ts_code"])
        top15_by_month[date] = codes
        all_codes.update(codes)

    if not all_codes:
        return {}

    # Load close prices for all these stocks over the full backtest window
    qlib_codes = [qlib_symbol(c) for c in sorted(all_codes)]
    print(f"      loading $close for {len(qlib_codes)} stocks ...", flush=True)

    # Load yearly to avoid memory issues
    frames = []
    warm_start = BT_START - pd.Timedelta(days=120)  # warm-up for rolling
    for year in range(warm_start.year, BT_END.year + 1):
        df = D.features(qlib_codes, ["$close"], start_time=f"{year}-01-01", end_time=f"{year}-12-31", freq="day")
        frames.append(df)
    raw = pd.concat(frames)["$close"].unstack(level="instrument")
    # Map columns back to ts_code format for lookup
    raw.columns = [f"{c[2:]}.{c[:2]}" for c in raw.columns]
    raw = raw.reindex(cal)

    # Compute daily returns
    rets = raw.pct_change()

    # For each rebalance date, get the 60-day rolling std for the top-15
    vol_lookup = {}
    for date, codes in top15_by_month.items():
        pos = cal.get_loc(date)
        # Look back VOL_WINDOW days ending at `date` (inclusive of date's return)
        window = rets.iloc[max(0, pos - VOL_WINDOW + 1) : pos + 1]
        vol_map = {}
        for code in codes:
            if code in window.columns:
                series = window[code].dropna()
                if len(series) >= VOL_MIN_PERIODS:
                    vol_map[qlib_symbol(code)] = float(series.std(ddof=1))
        vol_lookup[date] = vol_map

    return vol_lookup


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path,
                        default=Path("output/analysis_fundamental/a_share_value_quality_monthly_strategy_v10_invvol"))
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

    print("[3/7] Building daily signal ...", flush=True)
    wide = pd.DataFrame({d: f.set_index("ts_code")["neutral_composite"] for d, f in snapshots.items()}).T
    cal_win = calendar[(calendar >= BT_START) & (calendar <= BT_END)]
    wide = wide.reindex(cal_win).ffill()
    long = wide.stack().rename("score").dropna().reset_index()
    long.columns = ["datetime", "ts_code", "score"]
    long["instrument"] = long["ts_code"].map(qlib_symbol)
    signal = long.set_index(["datetime", "instrument"])["score"].sort_index()
    print(f"      signal rows={len(signal)}", flush=True)

    print(f"[4/7] Pre-computing {VOL_WINDOW}-day volatility for top-{TOP_K} ...", flush=True)
    vol_lookup = compute_vol_lookup(snapshots, calendar)
    # Report coverage
    total_stocks = sum(len(v) for v in vol_lookup.values())
    months_with_full = sum(1 for v in vol_lookup.values() if len(v) == TOP_K)
    print(f"      vol_lookup: {len(vol_lookup)} months, {total_stocks} stock-months, "
          f"{months_with_full}/{len(vol_lookup)} months with full {TOP_K} vols", flush=True)

    print("[5/7] Backtest (inverse-vol weighting) ...", flush=True)
    bt_rows = []
    for scenario, costs in COST_SCENARIOS.items():
        strategy = InverseVolWeightStrategy(
            signal=signal, top_k=TOP_K, vol_lookup=vol_lookup,
        )
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

    print("[6/7] Yearly summary ...", flush=True)
    strategy = InverseVolWeightStrategy(signal=signal, top_k=TOP_K, vol_lookup=vol_lookup)
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

    # Persist composite panel with weights
    panel_rows = []
    for date, f in snapshots.items():
        top = f.dropna(subset=["neutral_composite"]).nlargest(TOP_K, "neutral_composite").copy()
        vol_map = vol_lookup.get(date, {})
        # Compute weights
        inv_vols = {}
        for _, r in top.iterrows():
            qc = qlib_symbol(r["ts_code"])
            vol = vol_map.get(qc, np.nan)
            if pd.notna(vol) and vol > 0:
                inv_vols[r["ts_code"]] = 1.0 / vol
        total = sum(inv_vols.values()) if inv_vols else 1
        top["weight"] = top["ts_code"].map(lambda c: inv_vols.get(c, 0) / total if total else 0)
        item = top[["ts_code", "composite", "neutral_composite", "log_size", "l1_code", "weight"]].copy()
        item["rebalance_date"] = date
        panel_rows.append(item)
    pd.concat(panel_rows, ignore_index=True).to_csv(out / "monthly_composite_invvol.csv.gz",
                                                    index=False, compression="gzip")

    print("[7/7] Decision ...", flush=True)
    hol_stress = bt[(bt["stage"].eq("holdout")) & (bt["cost_scenario"].eq("stress"))].iloc[0]
    hol_base = bt[(bt["stage"].eq("holdout")) & (bt["cost_scenario"].eq("base"))].iloc[0]
    viable = bool(hol_stress["net_excess_annualized_return"] > 0 and hol_stress["net_excess_ir"] > 0)
    improved = bool(hol_stress["net_excess_ir"] > 0.918838)  # v8 holdout stress IR
    lower_risk = bool(abs(hol_stress["net_excess_max_drawdown"]) < abs(-0.166085))  # v8 holdout stress MDD

    if viable and improved and lower_risk:
        decision = "invvol_improved"
    elif viable and (improved or lower_risk):
        decision = "invvol_partial_improvement"
    elif viable:
        decision = "invvol_viable_no_improvement"
    else:
        decision = "invvol_not_viable"

    decision_json = {
        "decision": decision,
        "holdout_stress_net": float(hol_stress["net_excess_annualized_return"]),
        "holdout_stress_ir": float(hol_stress["net_excess_ir"]),
        "holdout_stress_mdd": float(hol_stress["net_excess_max_drawdown"]),
        "holdout_base_net": float(hol_base["net_excess_annualized_return"]),
        "v8_holdout_stress_ir_reference": 0.918838,
        "v8_holdout_stress_mdd_reference": -0.166085,
        "improved_vs_v8": bool(improved),
        "lower_risk_vs_v8": bool(lower_risk),
        "top_k": TOP_K,
        "vol_window": VOL_WINDOW,
    }
    (out / "decision.json").write_text(json.dumps(decision_json, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    methodology = {
        "protocol": "research/protocols/a_share_value_quality_monthly_strategy_protocol_v10.md",
        "change_from_v8": "equal-weight -> inverse-volatility weighting (1/sigma, 60-day rolling)",
        "strategy_class": "InverseVolWeightStrategy (WeightStrategyBase subclass)",
        "vol_window": VOL_WINDOW,
        "vol_min_periods": VOL_MIN_PERIODS,
        "topk": TOP_K,
        "benchmark": BENCHMARK,
        "backtest_window": [str(BT_START.date()), str(BT_END.date())],
    }
    (out / "methodology.json").write_text(json.dumps(methodology, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    lines = [
        "价值/质量多因子月度策略 逆波动率加权 v10",
        "=" * 64,
        f"与 v8 唯一差异：等权 -> 逆波动率加权（1/σ, {VOL_WINDOW}日滚动）",
        "",
        "回测（费后均为相对 SH000852 超额）：",
        bt.pivot_table(index="stage", columns="cost_scenario",
                       values=["net_excess_annualized_return", "net_excess_ir", "net_excess_max_drawdown"])
          .to_string(),
        "",
        "分年（基准成本费后）：",
        yearly.to_string(index=False),
        "",
        f"封存期对比：v8(等权) +10.16%/yr IR=0.92 MDD=-16.6% -> v10(逆波动率) "
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
