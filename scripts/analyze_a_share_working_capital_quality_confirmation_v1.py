#!/usr/bin/env python3
"""Validate only the confirmation stage after the development gate passed.

No holdout dates appear in this file.  The program refuses to read prices unless
the recorded development decision passed, then reads only 2020--2022 labels.
"""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import qlib
from qlib.config import REG_CN
from qlib.data import D

from analyze_a_share_working_capital_quality_development_v1 import (
    DEVELOPMENT_END,
    DEVELOPMENT_START,
    HORIZONS,
    MAIN_SCORE,
    analyze,
    atomic_csv,
    atomic_json,
    attach_monthly_controls,
    load_stage_labels,
    sha256_file,
    summarize_ic,
)


CONFIRMATION_START = pd.Timestamp("2020-01-01")
CONFIRMATION_END = pd.Timestamp("2022-12-31")


def main() -> None:
    root = Path(__file__).resolve().parents[1]
    output = root / "output/analysis_fundamental/a_share_working_capital_quality_single_factor_v1"
    decision_path = output / "decision.json"
    if not decision_path.is_file():
        raise SystemExit("development decision is missing")
    decision = json.loads(decision_path.read_text(encoding="utf-8"))
    if decision.get("status") != "development_candidate" or not decision.get("development_passed"):
        raise SystemExit("confirmation is not authorized: development gate did not pass")
    protocol = root / "research/protocols/a_share_working_capital_quality_single_factor_validation_protocol_v1.md"
    event_path = root / "data/derived/a_share_working_capital_quality_event_v1/event_panel.csv.gz"
    grid_path = root / "data/external/tushare/a_share_style_pit_v1/normalized/monthly_rebalance_grid.csv.gz"
    industry_path = root / "data/external/tushare/a_share_style_pit_v1/normalized/industry_l1_effective_intervals.csv.gz"
    size_path = root / "data/external/tushare/a_share_style_pit_v1/normalized/monthly_free_float_size.csv.gz"
    qlib_dir = "/root/.qlib/qlib_data/cn_data_2026"
    qlib.init(provider_uri=qlib_dir, region=REG_CN)
    calendar = pd.DatetimeIndex(pd.to_datetime(D.calendar(start_time=CONFIRMATION_START, end_time="2023-04-30", freq="day")))
    events = pd.read_csv(event_path, compression="gzip", parse_dates=["available_date", "effective_date", "expiry_date"])
    grid = pd.read_csv(grid_path, compression="gzip", parse_dates=["rebalance_date", "asof_date"])
    grid = grid.loc[grid["rebalance_date"].between(CONFIRMATION_START, CONFIRMATION_END)].copy()
    industry = pd.read_csv(industry_path, compression="gzip", dtype=str)
    industry["in_date"] = pd.to_datetime(industry["in_date"], errors="coerce")
    industry["out_date"] = pd.to_datetime(industry["out_date"], errors="coerce")
    size = pd.read_csv(size_path, compression="gzip", dtype=str)
    size["asof_date"] = pd.to_datetime(size["asof_date"], errors="coerce")
    size["size_control"] = pd.to_numeric(size["size_control"], errors="coerce")
    snapshots = {row.rebalance_date: attach_monthly_controls(events, row, industry, size) for _, row in grid.iterrows()}
    print(f"confirmation_months={len(snapshots)}", flush=True)
    labeled = load_stage_labels(snapshots, calendar, CONFIRMATION_START)
    monthly, groups, coverage, layers, industries = analyze(labeled, "confirmation")
    summary = summarize_ic(monthly, "confirmation")
    main_row = summary.loc[(summary["score"].eq(MAIN_SCORE)) & (summary["horizon"].eq(40))].iloc[0]
    main_horizons = summary.loc[summary["score"].eq(MAIN_SCORE)].set_index("horizon")
    group_mean = groups.loc[(groups["score"].eq(MAIN_SCORE)) & (groups["horizon"].eq(40)) & (groups["version"].eq("neutral")), "q5_minus_q1"].mean()
    layer_summary = layers.groupby("size_layer", observed=True)["neutral_rank_ic"].mean()
    no_s1 = layer_summary.drop(index="S1", errors="ignore").mean()
    passed = bool(main_row["neutral_rank_ic"] >= 0.01 and (main_horizons["neutral_rank_ic"] > 0).all() and group_mean >= 0 and (layer_summary > 0).sum() >= 3 and no_s1 > 0)
    decision.update({"confirmation_stage_read": True, "confirmation_months": len(grid), "confirmation_passed": passed, "confirmation_main_40d_neutral_rank_ic": float(main_row["neutral_rank_ic"]), "confirmation_main_40d_neutral_q5_minus_q1": float(group_mean), "confirmation_positive_size_layers": int((layer_summary > 0).sum()), "confirmation_excluding_s1_neutral_rank_ic": float(no_s1), "holdout_prices_read": False, "status": "confirmed_candidate" if passed else "hypothesis_not_supported"})
    atomic_csv(monthly, output / "confirmation_monthly_rank_ic.csv.gz")
    atomic_csv(summary, output / "confirmation_rank_ic_summary.csv")
    atomic_csv(groups, output / "confirmation_group_return_summary.csv")
    atomic_csv(layers, output / "confirmation_size_layer_summary.csv")
    atomic_csv(industries, output / "confirmation_industry_distribution_summary.csv")
    atomic_csv(coverage, output / "confirmation_sample_coverage_summary.csv")
    atomic_json(decision, decision_path)
    atomic_json({"stage_read": "confirmation_only", "development_window": [str(DEVELOPMENT_START.date()), str(DEVELOPMENT_END.date())], "confirmation_window": [str(CONFIRMATION_START.date()), str(CONFIRMATION_END.date())], "label": "open(t+H)/open(t)-1", "horizons": list(HORIZONS), "protocol_sha256": sha256_file(protocol), "no_holdout_prices_read": True, "no_model_or_backtest": True}, output / "confirmation_methodology.json")
    report = (
        "沪深非金融 A 股营运资本质量单因子确认期检验 v1\n"
        f"status: {decision['status']}\nconfirmation_months: {len(grid)}\n"
        f"main_40d_neutral_rank_ic: {main_row['neutral_rank_ic']:.6f}\n"
        f"main_40d_neutral_q5_minus_q1: {group_mean:.6f}\n"
        f"positive_size_layers: {int((layer_summary > 0).sum())}\n"
        f"excluding_s1_neutral_rank_ic: {no_s1:.6f}\nholdout_prices_read: False\n"
        "未训练模型、未运行回测。\n"
    )
    (output / "confirmation_validation_report.txt").write_text(report, encoding="utf-8")
    print(report, end="")


if __name__ == "__main__":
    main()
