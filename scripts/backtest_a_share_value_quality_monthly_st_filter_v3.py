#!/usr/bin/env python3
"""ST-filtered neutralized monthly strategy backtest (protocol v3).

V1 composite panel + ST/*ST/退市整理 filter (point-in-time via Tushare
namechange intervals at each month's asof_date) + industry/size neutralization
+ identical backtest rules.  Answers whether the neutralized value alpha
survives once value-trap names are removed.

Protocol: research/protocols/a_share_value_quality_monthly_strategy_protocol_v3.md
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
V1_PANEL_DEFAULT = Path("output/analysis_fundamental/a_share_value_quality_monthly_strategy_v1/monthly_composite_signal.csv.gz")


def qlib_symbol(code: str) -> str:
    number, suffix = code.split(".")
    return f"{suffix}{number}"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, default=Path("output/analysis_fundamental/a_share_value_quality_monthly_strategy_v3_st_filtered"))
    parser.add_argument("--panel-path", type=Path, default=V1_PANEL_DEFAULT)
    args = parser.parse_args()
    out = args.output_dir
    if out.exists() and any(out.iterdir()):
        raise FileExistsError(f"Refusing to overwrite existing experiment output: {out}")
    out.mkdir(parents=True, exist_ok=True)

    print("[1/5] Loading V1 panel, ST intervals, grid ...", flush=True)
    panel = pd.read_csv(args.panel_path, compression="gzip")
    panel["rebalance_date"] = pd.to_datetime(panel["rebalance_date"])
    st = pd.read_csv(ST_INTERVALS, compression="gzip", parse_dates=["start_date", "end_date"])
    grid = pd.read_csv(STYLE_DIR / "monthly_rebalance_grid.csv.gz", compression="gzip",
                       parse_dates=["rebalance_date", "asof_date"])
    asof_by_rebal = grid.set_index("rebalance_date")["asof_date"]
    print(f"      panel months={panel['rebalance_date'].nunique()} st_intervals={len(st)}", flush=True)

    print("[2/5] Applying ST/退市整理 filter per month ...", flush=True)
    st_summary = []
    filtered_parts = []
    for date, frame in panel.groupby("rebalance_date"):
        asof = asof_by_rebal.get(date, pd.NaT)
        frame = frame.copy()
        if pd.notna(asof):
            active = st[(st["start_date"] <= asof) & (st["end_date"] >= asof)]
            st_codes = set(active.loc[active["is_st"] | active["is_delist_phase"], "ts_code"])
            n_before = int(frame["composite"].notna().sum())
            frame.loc[frame["ts_code"].isin(st_codes), "composite"] = np.nan
            n_after = int(frame["composite"].notna().sum())
            st_summary.append({
                "rebalance_date": date, "asof_date": asof, "st_filtered": n_before - n_after,
                "st_codes": len(st_codes), "stocks": len(frame),
            })
        frame["rebalance_date"] = date
        filtered_parts.append(frame)
    filtered = pd.concat(filtered_parts, ignore_index=True)
    filtered.to_csv(out / "monthly_st_filtered_signal.csv.gz", index=False, compression="gzip")
    st_sum = pd.DataFrame(st_summary)
    st_sum.to_csv(out / "st_filter_summary.csv", index=False)
    print(f"      mean ST filtered per month={st_sum['st_filtered'].mean():.1f} "
          f"(max {st_sum['st_filtered'].max()})" if len(st_sum) else "      no months", flush=True)

    print("[3/5] Neutralizing composite per month ...", flush=True)
    neutral_parts = []
    for date, frame in filtered.groupby("rebalance_date"):
        out_frame = frame.copy()
        valid = out_frame.dropna(subset=["composite", "log_size", "l1_code"])
        if len(valid) < 50:
            out_frame["neutral_composite"] = np.nan
        else:
            resid = ols_residual(valid["composite"], valid["l1_code"], valid["log_size"])
            out_frame["neutral_composite"] = resid.reindex(out_frame.index)
        out_frame["rebalance_date"] = date
        neutral_parts.append(out_frame)
    neutral = pd.concat(neutral_parts, ignore_index=True)

    print("[4/5] Building daily signal & backtest ...", flush=True)
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
        holdout_net = next(r for r in bt_rows if r["stage"] == "holdout" and r["cost_scenario"] == scenario)
        print(f"      [{scenario}] holdout net={holdout_net['net_excess_annualized_return']:.4f} "
              f"IR={holdout_net['net_excess_ir']:.3f} | full net={bt_rows[-1]['net_excess_annualized_return']:.4f}", flush=True)

    bt = pd.DataFrame(bt_rows)
    bt.to_csv(out / "backtest_summary.csv", index=False)

    print("[5/5] Yearly summary & decision ...", flush=True)
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

    hol_stress = bt[(bt["stage"].eq("holdout")) & (bt["cost_scenario"].eq("stress"))].iloc[0]
    hol_base = bt[(bt["stage"].eq("holdout")) & (bt["cost_scenario"].eq("base"))].iloc[0]
    full_stress = bt[(bt["stage"].eq("full")) & (bt["cost_scenario"].eq("stress"))].iloc[0]
    if hol_stress["net_excess_annualized_return"] > 0 and hol_stress["net_excess_ir"] > 0:
        decision = "alpha_survives_st_filter"
    elif hol_base["net_excess_annualized_return"] > 0:
        decision = "alpha_survives_base_only"
    else:
        decision = "alpha_weakened_by_st_filter"
    decision_json = {
        "decision": decision,
        "holdout_stress_net_excess_annualized_return": float(hol_stress["net_excess_annualized_return"]),
        "holdout_stress_ir": float(hol_stress["net_excess_ir"]),
        "holdout_base_net_excess_annualized_return": float(hol_base["net_excess_annualized_return"]),
        "full_stress_net_excess_annualized_return": float(full_stress["net_excess_annualized_return"]),
        "full_stress_ir": float(full_stress["net_excess_ir"]),
        "mean_st_filtered_per_month": float(st_sum["st_filtered"].mean()) if len(st_sum) else 0.0,
    }
    (out / "decision.json").write_text(json.dumps(decision_json, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    methodology = {
        "protocol": "research/protocols/a_share_value_quality_monthly_strategy_protocol_v3.md",
        "st_source": str(ST_INTERVALS),
        "st_rule": "exclude if is_st or is_delist_phase at asof_date (Tushare namechange intervals)",
        "neutralization": "per-rebalance OLS residual on log(free-float mv) + SW L1 industry dummies",
        "topk": TOP_K,
        "execution": "TopkDropout t+1 open; limit_threshold 0.095; min_cost 5",
        "benchmark": BENCHMARK,
        "backtest_window": [str(BT_START.date()), str(BT_END.date())],
    }
    (out / "methodology.json").write_text(json.dumps(methodology, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    lines = [
        "价值/质量多因子月度策略 ST 过滤对照回测 v3",
        "=" * 64,
        f"ST/退市整理过滤：每月按 asof_date 从 namechange 区间判定，平均每月剔除 {st_sum['st_filtered'].mean():.1f} 只",
        "选股信号：composite → ST 过滤 → 行业/市值截面 OLS 残差；其余与 v2 完全一致",
        "",
        "回测（费后均为相对 SH000852 超额）：",
        bt.pivot_table(index="stage", columns="cost_scenario",
                       values=["net_excess_annualized_return", "net_excess_ir", "net_excess_max_drawdown"])
          .to_string(),
        "",
        "分年（基准成本费后）：",
        yearly.to_string(index=False),
        "",
        f"判定：{decision}",
        "结论边界：成交价仍为开盘价（滑点未单独建模），1 日成交滞后仍存在。",
    ]
    (out / "strategy_report.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("\n".join(lines))


if __name__ == "__main__":
    main()
