#!/usr/bin/env python3
"""Margin-filtered monthly strategy backtest (protocol v5).

V1 composite panel + ST/退市整理 filter + margin rzye-zscore>2 exclusion
(T-1 visible at each month's asof_date) + industry/size neutralization +
identical backtest rules.  Compares against the v3 baseline to measure the
incremental robustness of the margin leverage-crowding filter.

Protocol: research/protocols/a_share_value_quality_monthly_strategy_protocol_v5.md
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

from analyze_a_share_value_quality_level_factors_extension_v1 import ols_residual, QLIB_DIR, STYLE_DIR

TOP_K = 50
ACCOUNT = 100_000_000
BENCHMARK = "SH000852"
BT_START = pd.Timestamp("2014-01-01")
BT_END = pd.Timestamp("2025-06-30")
ANNUALIZATION_DAYS = 238
COST_SCENARIOS = {
    "base": {"open_cost": 0.0005, "close_cost": 0.0015},
    "stress": {"open_cost": 0.0010, "close_cost": 0.0030},
}
STAGES = {
    "development": (pd.Timestamp("2014-01-01"), pd.Timestamp("2019-12-31")),
    "confirmation": (pd.Timestamp("2020-01-01"), pd.Timestamp("2022-12-31")),
    "holdout": (pd.Timestamp("2023-01-01"), pd.Timestamp("2025-06-30")),
}
ST_INTERVALS = Path("data/external/tushare/a_share_st_status_pit_v1/normalized/st_status_intervals.csv.gz")
MARGIN_DIR = Path("data/external/tushare/margin_pit_v1/raw")
V1_PANEL_DEFAULT = Path("output/analysis_fundamental/a_share_value_quality_monthly_strategy_v1/monthly_composite_signal.csv.gz")
Z_THRESHOLD = 2.0
Z_ALT = 1.5
ZSCORE_WINDOW = 250
ZSCORE_MIN_PERIODS = 60


def qlib_symbol(code: str) -> str:
    number, suffix = code.split(".")
    return f"{suffix}{number}"


def load_margin() -> pd.DataFrame:
    frames = []
    for path in sorted(MARGIN_DIR.glob("*.csv.gz")):
        frame = pd.read_csv(path, compression="gzip", usecols=["trade_date", "ts_code", "rzye"])
        frames.append(frame)
    out = pd.concat(frames, ignore_index=True)
    out["datetime"] = pd.to_datetime(out["trade_date"].astype(str), format="%Y%m%d")
    return out[["ts_code", "datetime", "rzye"]]


def compute_margin_zscore(margin: pd.DataFrame) -> pd.DataFrame:
    """250-day rolling z-score of rzye per stock (>=60 valid obs)."""
    margin = margin.sort_values(["ts_code", "datetime"]).copy()
    g = margin.groupby("ts_code")["rzye"]
    roll_mean = g.transform(lambda x: x.rolling(ZSCORE_WINDOW, min_periods=ZSCORE_MIN_PERIODS).mean())
    roll_std = g.transform(lambda x: x.rolling(ZSCORE_WINDOW, min_periods=ZSCORE_MIN_PERIODS).std())
    margin["rzye_zscore"] = (margin["rzye"] - roll_mean) / roll_std
    margin["rzye_zscore"] = margin["rzye_zscore"].replace([np.inf, -np.inf], np.nan)
    return margin[["ts_code", "datetime", "rzye_zscore"]]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, default=Path("output/analysis_fundamental/a_share_value_quality_monthly_strategy_v5_margin_filtered"))
    parser.add_argument("--panel-path", type=Path, default=V1_PANEL_DEFAULT)
    args = parser.parse_args()
    out = args.output_dir
    if out.exists() and any(out.iterdir()):
        raise FileExistsError(f"Refusing to overwrite existing experiment output: {out}")
    out.mkdir(parents=True, exist_ok=True)

    print("[1/6] Loading V1 panel, ST, margin, grid ...", flush=True)
    panel = pd.read_csv(args.panel_path, compression="gzip")
    panel["rebalance_date"] = pd.to_datetime(panel["rebalance_date"])
    st = pd.read_csv(ST_INTERVALS, compression="gzip", parse_dates=["start_date", "end_date"])
    margin = load_margin()
    grid = pd.read_csv(STYLE_DIR / "monthly_rebalance_grid.csv.gz", compression="gzip",
                       parse_dates=["rebalance_date", "asof_date"])
    asof_by_rebal = grid.set_index("rebalance_date")["asof_date"]
    print(f"      panel months={panel['rebalance_date'].nunique()} margin rows={len(margin)}", flush=True)

    print("[2/6] Computing margin z-score ...", flush=True)
    zs = compute_margin_zscore(margin)
    zs_pivot = zs.pivot_table(index="datetime", columns="ts_code", values="rzye_zscore")
    print(f"      zscore pivot {zs_pivot.shape}", flush=True)

    print("[3/6] Applying ST + margin filters per month ...", flush=True)
    filter_summary = []
    filtered_parts = []
    for date, frame in panel.groupby("rebalance_date"):
        asof = asof_by_rebal.get(date, pd.NaT)
        frame = frame.copy()
        if pd.notna(asof):
            active = st[(st["start_date"] <= asof) & (st["end_date"] >= asof)]
            st_codes = set(active.loc[active["is_st"] | active["is_delist_phase"], "ts_code"])
            frame.loc[frame["ts_code"].isin(st_codes), "composite"] = np.nan
            # margin z-score at the asof date (T-1 visible); pivot rows are trading days.
            # Align to frame's ts_code column via numpy mask (frame index is RangeIndex).
            z_at = zs_pivot.reindex([asof]).iloc[0].reindex(frame["ts_code"]).to_numpy(dtype=float)
            n_before = int(frame["composite"].notna().sum())
            mask = (z_at > Z_THRESHOLD) & np.isfinite(z_at)
            frame.loc[mask, "composite"] = np.nan
            n_after = int(frame["composite"].notna().sum())
            filter_summary.append({
                "rebalance_date": date, "asof_date": asof,
                "margin_filtered": n_before - n_after,
                "margin_z_gt_2": int(((z_at > Z_THRESHOLD) & np.isfinite(z_at)).sum()),
                "margin_z_gt_1_5": int(((z_at > Z_ALT) & np.isfinite(z_at)).sum()),
                "stocks": len(frame),
            })
        frame["rebalance_date"] = date
        filtered_parts.append(frame)
    filtered = pd.concat(filtered_parts, ignore_index=True)
    filtered.to_csv(out / "monthly_margin_filtered_signal.csv.gz", index=False, compression="gzip")
    fsum = pd.DataFrame(filter_summary)
    fsum.to_csv(out / "margin_filter_summary.csv", index=False)
    print(f"      mean margin(z>2) excluded/month={fsum['margin_filtered'].mean():.1f} "
          f"(z>1.5: {fsum['margin_z_gt_1_5'].mean():.1f})" if len(fsum) else "      no months", flush=True)

    print("[4/6] Neutralizing composite per month ...", flush=True)
    neutral_parts = []
    for date, frame in filtered.groupby("rebalance_date"):
        of = frame.copy()
        valid = of.dropna(subset=["composite", "log_size", "l1_code"])
        if len(valid) < 50:
            of["neutral_composite"] = np.nan
        else:
            resid = ols_residual(valid["composite"], valid["l1_code"], valid["log_size"])
            of["neutral_composite"] = resid.reindex(of.index)
        of["rebalance_date"] = date
        neutral_parts.append(of)
    neutral = pd.concat(neutral_parts, ignore_index=True)

    print("[5/6] Building daily signal & backtest ...", flush=True)
    qlib.init(provider_uri=str(QLIB_DIR), region=REG_CN)
    calendar = pd.DatetimeIndex(pd.to_datetime(pd.read_csv(QLIB_DIR / "calendars" / "day.txt", header=None)[0]))
    cal_win = calendar[(calendar >= BT_START) & (calendar <= BT_END)]
    wide = neutral.pivot_table(index="rebalance_date", columns="ts_code", values="neutral_composite")
    wide.index = pd.to_datetime(wide.index)
    wide = wide.reindex(cal_win).ffill()
    long = wide.stack().rename("score").dropna().reset_index()
    long.columns = ["datetime", "ts_code", "score"]
    long["instrument"] = long["ts_code"].map(qlib_symbol)
    signal = long.set_index(["datetime", "instrument"])["score"].sort_index()
    print(f"      signal rows={len(signal)}", flush=True)

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
              f"IR={hol['net_excess_ir']:.3f} | full net={bt_rows[-1]['net_excess_annualized_return']:.4f}", flush=True)

    bt = pd.DataFrame(bt_rows)
    bt.to_csv(out / "backtest_summary.csv", index=False)

    print("[6/6] Yearly summary & decision ...", flush=True)
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

    # Compare with v3 baseline (fixed numbers from its strategy_report.txt).
    v3 = {
        "full_base": 0.105117, "full_stress": 0.099943, "full_base_ir": 0.891323, "full_stress_ir": 0.847603,
        "holdout_base": 0.097840, "holdout_stress": 0.093085, "holdout_base_ir": 0.697504,
        "holdout_stress_ir": 0.663738, "full_base_mdd": -0.265530, "holdout_base_mdd": -0.218341,
    }
    full_stress = bt[(bt["stage"].eq("full")) & (bt["cost_scenario"].eq("stress"))].iloc[0]
    hol_stress = bt[(bt["stage"].eq("holdout")) & (bt["cost_scenario"].eq("stress"))].iloc[0]
    hol_base = bt[(bt["stage"].eq("holdout")) & (bt["cost_scenario"].eq("base"))].iloc[0]
    full_base = bt[(bt["stage"].eq("full")) & (bt["cost_scenario"].eq("base"))].iloc[0]

    hol_improved = hol_stress["net_excess_annualized_return"] > v3["holdout_stress"]
    hol_ir_ok = hol_stress["net_excess_ir"] >= v3["holdout_stress_ir"]
    mdd_improved = abs(full_base["net_excess_max_drawdown"]) <= abs(v3["full_base_mdd"])
    if hol_improved and (hol_ir_ok or mdd_improved):
        decision = "margin_filter_improves_robustness"
    elif hol_stress["net_excess_annualized_return"] > 0:
        decision = "margin_filter_neutral_positive"
    else:
        decision = "margin_filter_no_improvement"

    decision_json = {
        "decision": decision,
        "v5_holdout_stress_net": float(hol_stress["net_excess_annualized_return"]),
        "v3_holdout_stress_net": v3["holdout_stress"],
        "v5_holdout_stress_ir": float(hol_stress["net_excess_ir"]),
        "v3_holdout_stress_ir": v3["holdout_stress_ir"],
        "v5_full_base_mdd": float(full_base["net_excess_max_drawdown"]),
        "v3_full_base_mdd": v3["full_base_mdd"],
        "v5_full_stress_net": float(full_stress["net_excess_annualized_return"]),
        "v3_full_stress_net": v3["full_stress"],
        "mean_margin_filtered_per_month": float(fsum["margin_filtered"].mean()) if len(fsum) else 0.0,
    }
    (out / "decision.json").write_text(json.dumps(decision_json, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    methodology = {
        "protocol": "research/protocols/a_share_value_quality_monthly_strategy_protocol_v5.md",
        "margin_filter": f"rzye 250d z-score > {Z_THRESHOLD} excluded at asof_date (T-1 visible)",
        "st_filter": "namechange is_st or is_delist_phase at asof_date",
        "neutralization": "per-rebalance OLS residual on log(free-float mv) + SW L1 industry dummies",
        "topk": TOP_K,
        "execution": "TopkDropout t+1 open; limit_threshold 0.095; min_cost 5",
        "benchmark": BENCHMARK,
        "backtest_window": [str(BT_START.date()), str(BT_END.date())],
    }
    (out / "methodology.json").write_text(json.dumps(methodology, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    lines = [
        "价值/质量多因子月度策略 margin 过滤层对照回测 v5",
        "=" * 64,
        f"过滤管线：composite → ST/退市剔除 → margin rzye-z>2 剔除（T-1可见，月均剔除 {fsum['margin_filtered'].mean():.1f} 只）→ 行业/市值中性化",
        "",
        "回测（费后均为相对 SH000852 超额）：",
        bt.pivot_table(index="stage", columns="cost_scenario",
                       values=["net_excess_annualized_return", "net_excess_ir", "net_excess_max_drawdown"])
          .to_string(),
        "",
        "分年（基准成本费后）：",
        yearly.to_string(index=False),
        "",
        "v3 vs v5 对比（压力成本费后）：",
        f"  封存期：v3={v3['holdout_stress']*100:.2f}%/yr IR={v3['holdout_stress_ir']:.3f} → "
        f"v5={hol_stress['net_excess_annualized_return']*100:.2f}%/yr IR={hol_stress['net_excess_ir']:.3f}",
        f"  全期：v3={v3['full_stress']*100:.2f}%/yr IR={v3['full_stress_ir']:.3f} → "
        f"v5={full_stress['net_excess_annualized_return']*100:.2f}%/yr IR={full_stress['net_excess_ir']:.3f}",
        f"  全期回撤：v3={v3['full_base_mdd']*100:.2f}% → v5={full_base['net_excess_max_drawdown']*100:.2f}%",
        "",
        f"判定：{decision}",
        "结论边界：margin 剔除为 T-1 保守对齐；z=2.0 为预先冻结阈值。",
    ]
    (out / "strategy_report.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("\n".join(lines))


if __name__ == "__main__":
    main()
