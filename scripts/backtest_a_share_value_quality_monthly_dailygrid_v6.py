#!/usr/bin/env python3
"""Daily-basis monthly-grid revalidation of the value/quality strategy (protocol v6).

Replaces the monthly-PIT market-cap grid with a daily-basis month-end grid from
a_share_daily_basic_pit_v1 (2016-2026), keeping every other v4 rule identical.
Primary judgement: holdout 2023-2025-06 net excess under stress cost stays
positive with IR>0.  If yes, the production pipeline switches to the daily grid
and covers the latest trading day.

Protocol: research/protocols/a_share_value_quality_monthly_strategy_protocol_v6.md
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
from backtest_a_share_value_quality_monthly_sensitivity_v4 import load_amount_avg, NOTIONAL
from run_daily_signal_pipeline_v1 import st_codes_at, qlib_symbol

TOP_K = 50
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
DAILY_BASIC = Path("data/external/tushare/a_share_daily_basic_pit_v1/normalized/daily_basic.csv.gz")
ST_INTERVALS = Path("data/external/tushare/a_share_st_status_pit_v1/normalized/st_status_intervals.csv.gz")


def build_daily_grid(end: pd.Timestamp | None = None) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Month-end grid + daily size frame from daily_basic_pit.

    Returns (grid, size_daily):
      grid: DataFrame[rebalance_date, asof_date] with both = month-end trading day
      size_daily: DataFrame[ts_code, asof_date, total_mv, total_share, dv_ttm]

    `end` overrides the frozen backtest end (BT_END).  Backtest scripts keep the
    default (BT_END) for reproducibility; the production signal pipeline passes
    the latest calendar date so month-end rebalances keep extending to new data.
    """
    db = pd.read_csv(DAILY_BASIC, compression="gzip",
                     usecols=["trade_date", "ts_code", "total_mv", "total_share", "dv_ttm"])
    db["datetime"] = pd.to_datetime(db["trade_date"].astype(str), format="%Y%m%d")
    db["month"] = db["datetime"].dt.to_period("M")
    month_end = db.groupby("month")["datetime"].max()
    # Keep months within [BT_START, end].
    grid_end = BT_END if end is None else pd.Timestamp(end)
    month_end = month_end[month_end.between(BT_START, grid_end)]
    grid = pd.DataFrame({
        "rebalance_date": month_end.values,
        "asof_date": month_end.values,
    })
    size_daily = db[db["datetime"].isin(month_end.values)].copy()
    size_daily["asof_date"] = size_daily["datetime"]
    size_daily = size_daily[["ts_code", "asof_date", "total_mv", "total_share", "dv_ttm"]]
    # build_snapshot expects a size_control column (the monthly style PIT size
    # layer); daily_basic lacks it.  Fill with the cross-sectional percentile of
    # total_mv as a placeholder: only build_snapshot reads it internally, the
    # neutralization in v6 uses log(total_mv) directly.
    size_daily["size_control"] = size_daily.groupby("asof_date")["total_mv"].rank(pct=True)
    return grid, size_daily


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, default=Path("output/analysis_fundamental/a_share_value_quality_monthly_strategy_v6_dailygrid"))
    args = parser.parse_args()
    out = args.output_dir
    if out.exists() and any(out.iterdir()):
        raise FileExistsError(f"Refusing to overwrite existing experiment output: {out}")
    out.mkdir(parents=True, exist_ok=True)

    qlib.init(provider_uri=str(QLIB_DIR), region=REG_CN)
    calendar = pd.DatetimeIndex(pd.to_datetime(pd.read_csv(QLIB_DIR / "calendars" / "day.txt", header=None)[0]))

    print("[1/6] Loading extended financials & daily grid ...", flush=True)
    fin = load_financials_extended()
    grid, size_daily = build_daily_grid()
    print(f"      months={len(grid)} {grid['rebalance_date'].min().date()} .. {grid['rebalance_date'].max().date()}", flush=True)

    industry = pd.read_csv(STYLE_DIR / "industry_l1_effective_intervals.csv.gz", compression="gzip", dtype=str)
    industry["in_date"] = pd.to_datetime(industry["in_date"], errors="coerce")
    industry["out_date"] = pd.to_datetime(industry["out_date"], errors="coerce")
    st = pd.read_csv(ST_INTERVALS, compression="gzip", parse_dates=["start_date", "end_date"])
    # amount for capacity: universe from daily_basic codes (cheaper than v1 panel).
    universe_codes = sorted(size_daily["ts_code"].unique())
    amount_avg = load_amount_avg(universe_codes, calendar)

    print("[2/6] Building monthly factor snapshots ...", flush=True)
    snapshots = {}
    for _, row in grid.iterrows():
        snap = build_snapshot(fin, row, industry, size_daily)
        if snap.empty:
            continue
        frame = snap.copy()
        # Composite with factor-count gate (>=3 factors) to exclude missing-factor
        # stocks whose single high rank would otherwise crowd into top50.
        frame["composite"] = composite_score(frame)
        # ST filter
        frame.loc[frame["ts_code"].isin(st_codes_at(st, row.asof_date)), "composite"] = np.nan
        # Capacity filter
        avg = amount_avg.loc[row.asof_date].reindex(frame["ts_code"]).to_numpy(dtype=float) * 1000.0
        min_amount = NOTIONAL / PARTICIPATION
        frame.loc[avg < min_amount, "composite"] = np.nan
        # Neutralize
        valid = frame.dropna(subset=["composite", "log_size", "l1_code"])
        if len(valid) < 50:
            continue
        resid = ols_residual(valid["composite"], valid["l1_code"], valid["log_size"])
        frame["neutral_composite"] = resid.reindex(frame.index)
        snapshots[row.rebalance_date] = frame
    print(f"      valid months={len(snapshots)}", flush=True)

    print("[3/6] Building daily signal ...", flush=True)
    wide = pd.DataFrame({d: f.set_index("ts_code")["neutral_composite"] for d, f in snapshots.items()}).T
    cal_win = calendar[(calendar >= BT_START) & (calendar <= BT_END)]
    wide = wide.reindex(cal_win).ffill()
    long = wide.stack().rename("score").dropna().reset_index()
    long.columns = ["datetime", "ts_code", "score"]
    long["instrument"] = long["ts_code"].map(qlib_symbol)
    signal = long.set_index(["datetime", "instrument"])["score"].sort_index()
    print(f"      signal rows={len(signal)}", flush=True)

    print("[4/6] Backtest ...", flush=True)
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
              f"IR={hol['net_excess_ir']:.3f}", flush=True)

    bt = pd.DataFrame(bt_rows)
    bt.to_csv(out / "backtest_summary.csv", index=False)

    print("[5/6] Yearly summary ...", flush=True)
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

    # Persist composite panel
    panel_rows = []
    for date, f in snapshots.items():
        item = f[["ts_code", "composite", "neutral_composite", "log_size", "l1_code"]].copy()
        item["rebalance_date"] = date
        panel_rows.append(item)
    pd.concat(panel_rows, ignore_index=True).to_csv(out / "monthly_composite_dailygrid.csv.gz",
                                                    index=False, compression="gzip")

    print("[6/6] Decision ...", flush=True)
    hol_stress = bt[(bt["stage"].eq("holdout")) & (bt["cost_scenario"].eq("stress"))].iloc[0]
    hol_base = bt[(bt["stage"].eq("holdout")) & (bt["cost_scenario"].eq("base"))].iloc[0]
    viable = bool(hol_stress["net_excess_annualized_return"] > 0 and hol_stress["net_excess_ir"] > 0)
    decision = "dailygrid_viable" if viable else "dailygrid_not_viable"
    decision_json = {
        "decision": decision,
        "holdout_stress_net": float(hol_stress["net_excess_annualized_return"]),
        "holdout_stress_ir": float(hol_stress["net_excess_ir"]),
        "holdout_base_net": float(hol_base["net_excess_annualized_return"]),
        "v3_holdout_stress_net_reference": 0.093085,  # from v3 report
        "v3_holdout_stress_ir_reference": 0.663738,
    }
    (out / "decision.json").write_text(json.dumps(decision_json, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    methodology = {
        "protocol": "research/protocols/a_share_value_quality_monthly_strategy_protocol_v6.md",
        "grid": "daily_basic_pit month-end trading day (rebalance_date=asof_date=month-end)",
        "mv_source": "daily_basic total_mv (万元->元), dv_ttm daily, total_share daily",
        "neutralization_size": "log(total_mv)",
        "financial": "load_financials_extended (to 2026Q2)",
        "st_filter": "namechange is_st or is_delist_phase",
        "capacity": f"single-stock notional {NOTIONAL} / 20d avg amount <= {PARTICIPATION}",
        "topk": TOP_K,
        "execution": "TopkDropout t+1 open; limit_threshold 0.095; min_cost 5",
        "benchmark": BENCHMARK,
        "backtest_window": [str(BT_START.date()), str(BT_END.date())],
    }
    (out / "methodology.json").write_text(json.dumps(methodology, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    lines = [
        "价值/质量多因子月度策略 日频市值网格重验 v6",
        "=" * 64,
        "网格：daily_basic 月末最后交易日（rebalance=asof=月末）；市值用日频 total_mv",
        "",
        "回测（费后均为相对 SH000852 超额）：",
        bt.pivot_table(index="stage", columns="cost_scenario",
                       values=["net_excess_annualized_return", "net_excess_ir", "net_excess_max_drawdown"])
          .to_string(),
        "",
        "分年（基准成本费后）：",
        yearly.to_string(index=False),
        "",
        "封存期对比：v3(月度网格) 压力费后 +9.31%/yr IR=0.664 → v6(日频网格) "
        f"{hol_stress['net_excess_annualized_return']*100:.2f}%/yr IR={hol_stress['net_excess_ir']:.3f}",
        "",
        f"判定：{decision}",
        "新覆盖区(2025-07~2026-06)为观察报告，不构成验证。",
    ]
    (out / "strategy_report.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("\n".join(lines))


if __name__ == "__main__":
    main()
