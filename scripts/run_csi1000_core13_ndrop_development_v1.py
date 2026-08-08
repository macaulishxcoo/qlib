#!/usr/bin/env python3
"""Run the frozen CSI1000 Core13 n_drop development experiment exactly once.

This script intentionally has no model training and does not read the 2025-2026
confirmation window.  It reconstructs the frozen B model only to create one
shared 2023-2024 prediction file, then evaluates the pre-declared strategy grid.
"""

import argparse
import hashlib
import json
import pickle
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

import qlib
from qlib.backtest import backtest
from qlib.backtest.executor import SimulatorExecutor
from qlib.config import REG_CN
from qlib.contrib.evaluate import risk_analysis
from qlib.contrib.strategy import TopkDropoutStrategy
from qlib.utils import init_instance_by_config


EXPERIMENT_ID = "279845493254805780"
RUN_ID = "87746817d1924ad887b429044c8ec4c2"
DEVELOPMENT_START = pd.Timestamp("2023-01-01")
DEVELOPMENT_END = pd.Timestamp("2024-12-31")
TOP_K = 50
N_DROPS = (5, 10, 20, 40)
BENCHMARK = "SH000852"
ACCOUNT = 100_000_000
ANNUALIZATION_DAYS = 238
AGE_BUCKETS = ("age_1", "age_2_5", "age_6_10", "age_11_20", "age_21_plus")
PERIODS = {
    "full_2023_2024": (pd.Timestamp("2023-01-01"), pd.Timestamp("2024-12-31")),
    "year_2023": (pd.Timestamp("2023-01-01"), pd.Timestamp("2023-12-31")),
    "year_2024": (pd.Timestamp("2024-01-01"), pd.Timestamp("2024-12-31")),
}
COST_SCENARIOS = {
    "base": {"open_cost": 0.0005, "close_cost": 0.0015},
    "stress": {"open_cost": 0.0010, "close_cost": 0.0030},
}


def artifact_dir(mlruns_dir: Path) -> Path:
    """Find the completed model B artifacts without altering them."""
    path = mlruns_dir / EXPERIMENT_ID / RUN_ID / "artifacts"
    required = [path / "params.pkl", path / "task"]
    missing = [str(item) for item in required if not item.is_file()]
    if missing:
        raise FileNotFoundError(f"Missing frozen B artifact(s): {missing}")
    return path


def rebuild_predictions(artifacts: Path) -> pd.Series:
    """Predict the fixed valid segment once; no fitting is performed here."""
    with (artifacts / "params.pkl").open("rb") as file:
        model = pickle.load(file)
    with (artifacts / "task").open("rb") as file:
        task = pickle.load(file)
    dataset = init_instance_by_config(task["dataset"])
    predictions = model.predict(dataset, segment="valid")
    if isinstance(predictions, pd.DataFrame):
        predictions = predictions.iloc[:, 0]
    predictions = predictions.rename("score").sort_index()
    dates = predictions.index.get_level_values("datetime")
    predictions = predictions[(dates >= DEVELOPMENT_START) & (dates <= DEVELOPMENT_END)]
    if predictions.empty:
        raise RuntimeError("Frozen B model generated no 2023-2024 predictions")
    return predictions


def save_frozen_predictions(predictions: pd.Series, output_dir: Path) -> tuple[Path, str]:
    """Persist one common signal file and hash its exact bytes for auditability."""
    path = output_dir / "frozen_valid_predictions.pkl"
    predictions.to_frame().to_pickle(path)
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    return path, digest


def run_backtest(predictions: pd.Series, n_drop: int, costs: dict) -> tuple[pd.DataFrame, dict, pd.DataFrame]:
    """Run one strategy/cost scenario under the protocol's fixed trading rules."""
    strategy = TopkDropoutStrategy(signal=predictions, topk=TOP_K, n_drop=n_drop)
    executor = SimulatorExecutor(time_per_step="day", generate_portfolio_metrics=True)
    portfolio_metrics, indicator_metrics = backtest(
        start_time=DEVELOPMENT_START,
        end_time=DEVELOPMENT_END,
        strategy=strategy,
        executor=executor,
        account=ACCOUNT,
        benchmark=BENCHMARK,
        exchange_kwargs={
            "freq": "day",
            "limit_threshold": 0.095,
            "deal_price": "close",
            "open_cost": costs["open_cost"],
            "close_cost": costs["close_cost"],
            "min_cost": 5,
        },
    )
    report, positions = portfolio_metrics["1day"]
    indicators = indicator_metrics["1day"][0]
    return report, positions, indicators


def age_bucket(age: int) -> str:
    if age == 1:
        return "age_1"
    if age <= 5:
        return "age_2_5"
    if age <= 10:
        return "age_6_10"
    if age <= 20:
        return "age_11_20"
    return "age_21_plus"


def position_weights_and_ages(position: object) -> tuple[pd.Series, pd.Series]:
    """Extract current stock weights and Qlib's consecutive holding-day counters."""
    raw = position.position
    account_value = float(raw["now_account_value"])
    weights = {}
    ages = {}
    for instrument in position.get_stock_list():
        value = raw[instrument]
        weights[instrument] = float(value.get("weight", value["amount"] * value["price"] / account_value))
        ages[instrument] = int(value["count_day"])
    return pd.Series(weights, dtype="float64"), pd.Series(ages, dtype="int64")


def holding_alignment(predictions: pd.Series, report: pd.DataFrame, positions: dict) -> pd.DataFrame:
    """Measure how closely each actual portfolio follows the previous score-date Top50."""
    calendar = pd.DatetimeIndex(report.index).sort_values()
    prediction_dates = set(predictions.index.get_level_values("datetime").unique())
    rows = []
    for index in range(1, len(calendar)):
        signal_date = calendar[index - 1]
        execution_date = calendar[index]
        if signal_date not in prediction_dates or execution_date not in positions:
            continue
        score = predictions.xs(signal_date, level="datetime").dropna()
        if len(score) < TOP_K:
            continue
        weights, ages = position_weights_and_ages(positions[execution_date])
        if weights.empty:
            continue
        top = set(score.nlargest(TOP_K).index)
        ranks = score.rank(method="first", ascending=False)
        held = weights.index
        shared = held.intersection(top)
        row = {
            "signal_date": signal_date,
            "execution_date": execution_date,
            "holding_count": int(len(held)),
            "top50_overlap_ratio": float(len(shared) / TOP_K),
            "mean_held_score_rank_percentile": float(ranks.reindex(held).mean() / len(score)),
            "weighted_mean_holding_age": float((weights * ages).sum() / weights.sum()),
        }
        for bucket in AGE_BUCKETS:
            row[f"{bucket}_weight_share"] = float(weights.loc[ages[ages.map(age_bucket).eq(bucket)].index].sum())
        rows.append(row)
    result = pd.DataFrame(rows).set_index("signal_date").sort_index()
    if result.empty:
        raise RuntimeError("Could not align any backtest positions to frozen predictions")
    return result


def risk_values(returns: pd.Series) -> dict:
    risk = risk_analysis(returns, freq="day")["risk"]
    return {key: float(risk[key]) for key in ["annualized_return", "information_ratio", "max_drawdown"]}


def summarize_strategy(
    report: pd.DataFrame,
    indicators: pd.DataFrame,
    n_drop: int,
    scenario: str,
) -> pd.DataFrame:
    """Compute required whole-period and calendar-year strategy metrics."""
    rows = []
    for period, (start, end) in PERIODS.items():
        sample = report.loc[start:end]
        if sample.empty:
            raise RuntimeError(f"No report data for {n_drop=}, {scenario=}, {period=}")
        gross = risk_values(sample["return"] - sample["bench"])
        net = risk_values(sample["return"] - sample["bench"] - sample["cost"])
        indicator_slice = indicators.reindex(sample.index)
        rows.append(
            {
                "n_drop": n_drop,
                "cost_scenario": scenario,
                "period": period,
                "start_date": sample.index.min().date().isoformat(),
                "end_date": sample.index.max().date().isoformat(),
                "trading_days": int(len(sample)),
                "gross_excess_annualized_return": gross["annualized_return"],
                "net_excess_annualized_return": net["annualized_return"],
                "net_excess_information_ratio": net["information_ratio"],
                "net_excess_max_drawdown": net["max_drawdown"],
                "average_daily_turnover_rate": float(sample["turnover"].mean()),
                "annualized_cost_drag": float(sample["cost"].mean() * ANNUALIZATION_DAYS),
                "total_cost_drag": float(sample["cost"].sum()),
                "mean_order_fill_rate": float(indicator_slice["ffr"].mean()),
                "mean_order_count": float(indicator_slice["count"].mean()),
            }
        )
    return pd.DataFrame(rows)


def summarize_alignment(alignment: pd.DataFrame, n_drop: int, scenario: str) -> pd.DataFrame:
    rows = []
    for period, (start, end) in PERIODS.items():
        sample = alignment.loc[start:end]
        rows.append(
            {
                "n_drop": n_drop,
                "cost_scenario": scenario,
                "period": period,
                "aligned_days": int(len(sample)),
                "mean_top50_overlap_ratio": float(sample["top50_overlap_ratio"].mean()),
                "mean_held_score_rank_percentile": float(sample["mean_held_score_rank_percentile"].mean()),
                "weighted_mean_holding_age": float(sample["weighted_mean_holding_age"].mean()),
                **{bucket: float(sample[f"{bucket}_weight_share"].mean()) for bucket in AGE_BUCKETS},
            }
        )
    return pd.DataFrame(rows)


def decision_table(summary: pd.DataFrame) -> pd.DataFrame:
    """Apply the five pre-declared pressure-cost replacement tests without retuning."""
    stress = summary[summary["cost_scenario"].eq("stress")]
    full = stress[stress["period"].eq("full_2023_2024")].set_index("n_drop")
    years = stress[stress["period"].isin(["year_2023", "year_2024"])]
    baseline = full.loc[5]
    baseline_worst = float(years[years["n_drop"].eq(5)]["net_excess_annualized_return"].min())
    rows = []
    for n_drop in N_DROPS:
        candidate = full.loc[n_drop]
        candidate_years = years[years["n_drop"].eq(n_drop)]
        candidate_worst = float(candidate_years["net_excess_annualized_return"].min())
        yearly_positive = bool((candidate_years["net_excess_annualized_return"] > 0).all())
        ir_gain = float(candidate["net_excess_information_ratio"] - baseline["net_excess_information_ratio"])
        worst_year_gain = candidate_worst - baseline_worst
        drawdown_deterioration = abs(candidate["net_excess_max_drawdown"]) - abs(baseline["net_excess_max_drawdown"])
        turnover_ok = bool(candidate["average_daily_turnover_rate"] <= 0.50)
        passes = bool(
            n_drop != 5
            and yearly_positive
            and ir_gain >= 0.10
            and worst_year_gain >= 0.02
            and drawdown_deterioration <= 0.05
            and turnover_ok
        )
        rows.append(
            {
                "n_drop": n_drop,
                "year_2023_stress_net_excess": float(candidate_years[candidate_years["period"].eq("year_2023")]["net_excess_annualized_return"].iloc[0]),
                "year_2024_stress_net_excess": float(candidate_years[candidate_years["period"].eq("year_2024")]["net_excess_annualized_return"].iloc[0]),
                "both_years_positive": yearly_positive,
                "stress_full_ir": float(candidate["net_excess_information_ratio"]),
                "stress_ir_gain_vs_ndrop5": ir_gain,
                "stress_worst_year_excess": candidate_worst,
                "stress_worst_year_gain_vs_ndrop5": worst_year_gain,
                "stress_max_drawdown": float(candidate["net_excess_max_drawdown"]),
                "stress_drawdown_deterioration_vs_ndrop5": drawdown_deterioration,
                "average_daily_turnover_rate": float(candidate["average_daily_turnover_rate"]),
                "turnover_at_or_below_50pct": turnover_ok,
                "passes_all_replacement_rules": passes,
            }
        )
    return pd.DataFrame(rows)


def pct(value: float) -> str:
    return f"{value * 100:.2f}%"


def write_report(path: Path, summary: pd.DataFrame, alignment: pd.DataFrame, decisions: pd.DataFrame, metadata: dict) -> None:
    """Write the review report; detailed machine-readable figures remain in CSV."""
    full = summary[summary["period"].eq("full_2023_2024")].copy()
    display = full[
        ["n_drop", "cost_scenario", "gross_excess_annualized_return", "net_excess_annualized_return", "net_excess_information_ratio", "net_excess_max_drawdown", "average_daily_turnover_rate", "annualized_cost_drag"]
    ].copy()
    for column in ["gross_excess_annualized_return", "net_excess_annualized_return", "net_excess_max_drawdown", "average_daily_turnover_rate", "annualized_cost_drag"]:
        display[column] = display[column].map(pct)
    display["net_excess_information_ratio"] = display["net_excess_information_ratio"].map(lambda value: f"{value:.3f}")
    yearly = summary[summary["period"].isin(["year_2023", "year_2024"])][
        ["n_drop", "cost_scenario", "period", "net_excess_annualized_return", "net_excess_information_ratio", "net_excess_max_drawdown", "average_daily_turnover_rate"]
    ].copy()
    for column in ["net_excess_annualized_return", "net_excess_max_drawdown", "average_daily_turnover_rate"]:
        yearly[column] = yearly[column].map(pct)
    yearly["net_excess_information_ratio"] = yearly["net_excess_information_ratio"].map(lambda value: f"{value:.3f}")
    aligned = alignment[alignment["period"].eq("full_2023_2024")][
        ["n_drop", "cost_scenario", "mean_top50_overlap_ratio", "mean_held_score_rank_percentile", "weighted_mean_holding_age"]
    ].copy()
    for column in ["mean_top50_overlap_ratio", "mean_held_score_rank_percentile"]:
        aligned[column] = aligned[column].map(pct)
    aligned["weighted_mean_holding_age"] = aligned["weighted_mean_holding_age"].map(lambda value: f"{value:.2f}")
    passing = decisions[decisions["passes_all_replacement_rules"] & decisions["n_drop"].ne(5)]
    if passing.empty:
        conclusion = "没有候选通过全部预先冻结门槛；保留 n_drop=5 仅作为前瞻观察基线，不能视为已验证有效策略。"
    else:
        best = passing.sort_values(
            ["stress_worst_year_excess", "average_daily_turnover_rate", "n_drop"],
            ascending=[False, True, True],
        ).iloc[0]
        conclusion = f"n_drop={int(best['n_drop'])} 通过全部预先冻结门槛，成为唯一可进入严格前瞻观察的候选。"
    lines = [
        "CSI1000 Core13 换仓速度开发实验 v1",
        "=" * 48,
        "",
        "本实验固定已训练的 B_core13 模型、共同 2023-2024 预测、CSI1000 股票池、标签、Top50 和交易限制，仅改变 n_drop 与成本情景。",
        "未重新训练模型、未改因子或标签；未读取或回测 2025-2026。2023-2024 仅为开发期，结论不能作为实盘或样本外证据。",
        f"冻结预测：{metadata['prediction_file']}；SHA256：{metadata['prediction_sha256']}。",
        "",
        "全期结果（费用后均为相对 SH000852 的超额）：",
        display.to_string(index=False),
        "",
        "分年结果：",
        yearly.to_string(index=False),
        "",
        "持仓与最新 Top50 的对齐（越高表示越接近每日最新排名；分数排名百分位越低越好）：",
        aligned.to_string(index=False),
        "",
        "压力成本下的预先冻结判定：",
        decisions.to_string(index=False),
        "",
        f"结论：{conclusion}",
        "本步骤到此结束；不得使用 2025-2026 对此结果二次调参。",
    ]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mlruns-dir", type=Path, default=Path("output/mlruns_static"))
    parser.add_argument("--qlib-data-dir", type=Path, default=Path("~/.qlib/qlib_data/cn_data_2026").expanduser())
    parser.add_argument("--output-dir", type=Path, default=Path("output/analysis_static/csi1000_core13_ndrop_development_v1"))
    args = parser.parse_args()
    # A previously interrupted run can only have written the shared prediction
    # before entering any backtest.  Resume that exact harmless state, but never
    # overwrite a directory containing partial results.
    if args.output_dir.exists() and any(args.output_dir.iterdir()):
        existing = {item.name for item in args.output_dir.iterdir()}
        if existing != {"frozen_valid_predictions.pkl"}:
            raise FileExistsError(f"Refusing to overwrite existing experiment output: {args.output_dir}")
    if not args.qlib_data_dir.is_dir():
        raise FileNotFoundError(f"Qlib data directory not found: {args.qlib_data_dir}")
    args.output_dir.mkdir(parents=True, exist_ok=True)

    qlib.init(provider_uri=str(args.qlib_data_dir), region=REG_CN)
    predictions = rebuild_predictions(artifact_dir(args.mlruns_dir))
    prediction_path, prediction_hash = save_frozen_predictions(predictions, args.output_dir)
    prediction_dates = predictions.index.get_level_values("datetime")

    strategy_rows = []
    alignment_rows = []
    for n_drop in N_DROPS:
        for scenario, costs in COST_SCENARIOS.items():
            report, positions, indicators = run_backtest(predictions, n_drop, costs)
            strategy_rows.append(summarize_strategy(report, indicators, n_drop, scenario))
            alignment_rows.append(summarize_alignment(holding_alignment(predictions, report, positions), n_drop, scenario))

    strategy_summary = pd.concat(strategy_rows, ignore_index=True)
    alignment_summary = pd.concat(alignment_rows, ignore_index=True)
    decisions = decision_table(strategy_summary)
    strategy_summary.to_csv(args.output_dir / "strategy_summary.csv", index=False)
    alignment_summary.to_csv(args.output_dir / "holding_alignment_summary.csv", index=False)
    strategy_summary[strategy_summary["period"].ne("full_2023_2024")].to_csv(args.output_dir / "yearly_summary.csv", index=False)
    decisions.to_csv(args.output_dir / "predeclared_decision.csv", index=False)
    metadata = {
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "protocol": "research/protocols/csi1000_core13_ndrop_development_protocol_v1.md",
        "model": {"experiment_id": EXPERIMENT_ID, "run_id": RUN_ID, "name": "B_core13"},
        "development_window": [DEVELOPMENT_START.date().isoformat(), DEVELOPMENT_END.date().isoformat()],
        "explicitly_excluded_window": ["2025-01-01", "2026-07-23"],
        "prediction_file": prediction_path.name,
        "prediction_sha256": prediction_hash,
        "prediction_rows": int(len(predictions)),
        "prediction_start": prediction_dates.min().date().isoformat(),
        "prediction_end": prediction_dates.max().date().isoformat(),
        "mean_stocks_per_prediction_day": float(predictions.groupby(level="datetime").size().mean()),
        "topk": TOP_K,
        "n_drop_candidates": list(N_DROPS),
        "cost_scenarios": COST_SCENARIOS,
        "annualization_days": ANNUALIZATION_DAYS,
    }
    (args.output_dir / "metadata.json").write_text(json.dumps(metadata, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    write_report(args.output_dir / "ndrop_development_report.txt", strategy_summary, alignment_summary, decisions, metadata)


if __name__ == "__main__":
    main()
