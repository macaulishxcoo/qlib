#!/usr/bin/env python3
"""Neutralized monthly multi-factor strategy backtest (protocol v2).

Takes the V1 composite panel (already saved), residualizes composite against
log-size + SW L1 industry dummies per rebalance cross-section, and backtests
the neutralized signal under identical rules.  Answers whether the V1 holdout
(2023-2025) loss is style exposure or signal decay.

Protocol: research/protocols/a_share_value_quality_monthly_strategy_protocol_v2.md
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

from analyze_a_share_value_quality_level_factors_extension_v1 import ols_residual, QLIB_DIR

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
V1_PANEL_DEFAULT = Path("output/analysis_fundamental/a_share_value_quality_monthly_strategy_v1/monthly_composite_signal.csv.gz")


def qlib_symbol(code: str) -> str:
    number, suffix = code.split(".")
    return f"{suffix}{number}"


def neutral_snapshot(frame: pd.DataFrame) -> pd.DataFrame:
    """Residualize composite against log-size + industry dummies in one cross-section."""
    out = frame.copy()
    valid = out.dropna(subset=["composite", "log_size", "l1_code"])
    if len(valid) < 50:
        out["neutral_composite"] = np.nan
        return out
    resid = ols_residual(valid["composite"], valid["l1_code"], valid["log_size"])
    out["neutral_composite"] = resid.reindex(out.index)
    return out


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, default=Path("output/analysis_fundamental/a_share_value_quality_monthly_strategy_v2_neutral"))
    parser.add_argument("--panel-path", type=Path, default=V1_PANEL_DEFAULT,
                        help="V1 monthly_composite_signal.csv.gz with ts_code/composite/log_size/l1_code")
    args = parser.parse_args()
    out = args.output_dir
    if out.exists() and any(out.iterdir()):
        raise FileExistsError(f"Refusing to overwrite existing experiment output: {out}")
    out.mkdir(parents=True, exist_ok=True)
    if not args.panel_path.exists():
        raise FileNotFoundError(f"V1 panel not found: {args.panel_path} (run the V1 backtest first)")

    print(f"[1/4] Loading V1 panel {args.panel_path.name} ...", flush=True)
    panel = pd.read_csv(args.panel_path, compression="gzip")
    panel["rebalance_date"] = pd.to_datetime(panel["rebalance_date"])
    print(f"      rows={len(panel)} months={panel['rebalance_date'].nunique()}", flush=True)

    print("[2/4] Residualizing composite per month ...", flush=True)
    neutral_parts = []
    for date, frame in panel.groupby("rebalance_date"):
        nf = neutral_snapshot(frame)
        nf["rebalance_date"] = date
        neutral_parts.append(nf)
    neutral = pd.concat(neutral_parts, ignore_index=True)
    neutral.to_csv(out / "monthly_neutral_signal.csv.gz", index=False, compression="gzip")
    print(f"      neutral_composite nonnull={neutral['neutral_composite'].notna().mean():.3f}", flush=True)

    print("[3/4] Building daily signal & backtest ...", flush=True)
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
        gross = risk_analysis(full["return"] - full["bench"], freq="day")["risk"]
        net = risk_analysis(full["return"] - full["bench"] - full["cost"], freq="day")["risk"]
        bt_rows.append({
            "stage": "full", "cost_scenario": scenario,
            "start": str(full.index.min().date()), "end": str(full.index.max().date()),
            "trading_days": int(len(full)),
            "gross_excess_annualized_return": float(gross["annualized_return"]),
            "gross_excess_ir": float(gross["information_ratio"]),
            "net_excess_annualized_return": float(net["annualized_return"]),
            "net_excess_ir": float(net["information_ratio"]),
            "net_excess_max_drawdown": float(net["max_drawdown"]),
            "average_daily_turnover_rate": float(full["turnover"].mean()),
            "annualized_cost_drag": float(full["cost"].mean() * ANNUALIZATION_DAYS),
            "benchmark_annualized_return": bench_ann,
        })
        print(f"      [{scenario}] holdout net="
              f"{next(r for r in bt_rows if r['stage']=='holdout' and r['cost_scenario']==scenario)['net_excess_annualized_return']:.4f} | "
              f"full net={bt_rows[-1]['net_excess_annualized_return']:.4f}", flush=True)

    bt = pd.DataFrame(bt_rows)
    bt.to_csv(out / "backtest_summary.csv", index=False)

    print("[4/4] Yearly summary & decision ...", flush=True)
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

    hol = bt[(bt["stage"].eq("holdout")) & (bt["cost_scenario"].eq("stress"))].iloc[0]
    hol_base = bt[(bt["stage"].eq("holdout")) & (bt["cost_scenario"].eq("base"))].iloc[0]
    if hol["net_excess_annualized_return"] > 0 and hol["net_excess_ir"] > 0:
        decision = "holdout_turned_positive_neutralized"
    elif hol_base["net_excess_annualized_return"] > 0:
        decision = "holdout_positive_base_only"
    else:
        decision = "holdout_still_negative"
    decision_json = {
        "decision": decision,
        "holdout_stress_net_excess_annualized_return": float(hol["net_excess_annualized_return"]),
        "holdout_stress_ir": float(hol["net_excess_ir"]),
        "holdout_base_net_excess_annualized_return": float(hol_base["net_excess_annualized_return"]),
        "holdout_base_ir": float(hol_base["net_excess_ir"]),
    }
    (out / "decision.json").write_text(json.dumps(decision_json, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    methodology = {
        "protocol": "research/protocols/a_share_value_quality_monthly_strategy_protocol_v2.md",
        "neutralization": "per-rebalance OLS residual of composite on log(free-float mv) + SW L1 industry dummies",
        "v1_panel": str(args.panel_path),
        "topk": TOP_K,
        "execution": "TopkDropout t+1 open; limit_threshold 0.095; min_cost 5",
        "benchmark": BENCHMARK,
        "backtest_window": [str(BT_START.date()), str(BT_END.date())],
    }
    (out / "methodology.json").write_text(json.dumps(methodology, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    lines = [
        "价值/质量多因子月度策略中性化对照回测 v2",
        "=" * 64,
        "选股信号：composite 的行业/市值截面 OLS 残差（每月），其余与 v1 完全一致",
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
        "结论边界：ST 过滤缺失与 1 日成交滞后是已知偏差；结果只作风格暴露 vs 信号失效的归因检验。",
    ]
    (out / "strategy_report.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("\n".join(lines))


if __name__ == "__main__":
    main()
