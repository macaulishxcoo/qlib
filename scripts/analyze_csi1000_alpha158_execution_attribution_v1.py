#!/usr/bin/env python3
"""Audit how frozen CSI1000 A/B/C signals became actual TopkDropout returns."""

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

import qlib
from qlib.config import REG_CN
from qlib.data import D


COMPARISON_START = pd.Timestamp("2025-01-01")
COMPARISON_END = pd.Timestamp("2026-07-21")
TOP_K = 50
ANNUALIZATION_DAYS = 238
RECONSTRUCTION_TOLERANCE = 1e-5

RUNS = {
    "A_full_alpha158": {
        "experiment_id": "330634061802022404",
        "run_id": "49417dce2cf7436db1ac856084c6d8c6",
        "feature_count": 158,
        "description": "A: full raw Alpha158 baseline",
    },
    "B_core13": {
        "experiment_id": "279845493254805780",
        "run_id": "87746817d1924ad887b429044c8ec4c2",
        "feature_count": 13,
        "description": "B: 13 development-selected core factors",
    },
    "C_core13_observe39": {
        "experiment_id": "408082498063824291",
        "run_id": "3f7853fb4a4d4acb86a689d6bb12a70b",
        "feature_count": 52,
        "description": "C: B plus 39 development-stage observation factors",
    },
}

PERIODS = {
    "full": (pd.Timestamp("2025-01-01"), pd.Timestamp("2026-07-21")),
    "year_2025": (pd.Timestamp("2025-01-01"), pd.Timestamp("2025-12-31")),
    "year_2026_to_0721": (pd.Timestamp("2026-01-01"), pd.Timestamp("2026-07-21")),
}


def artifact_dir(mlruns_dir: Path, run: dict) -> Path:
    """Find the completed frozen-run artifacts required for a read-only audit."""
    artifacts = mlruns_dir / run["experiment_id"] / run["run_id"] / "artifacts"
    required = [
        artifacts / "pred.pkl",
        artifacts / "label.pkl",
        artifacts / "portfolio_analysis" / "report_normal_1day.pkl",
        artifacts / "portfolio_analysis" / "positions_normal_1day.pkl",
        artifacts / "portfolio_analysis" / "indicators_normal_1day.pkl",
    ]
    missing = [str(path) for path in required if not path.is_file()]
    if missing:
        raise FileNotFoundError(f"Missing completed-run artifact(s): {missing}")
    return artifacts


def load_common_signal_panel(mlruns_dir: Path) -> tuple[pd.DataFrame, pd.Series]:
    """Return the common labelled stock-days and verify labels are identical across A/B/C."""
    panels = {}
    for version, run in RUNS.items():
        artifacts = artifact_dir(mlruns_dir, run)
        score = pd.read_pickle(artifacts / "pred.pkl").iloc[:, 0].rename("score")
        label = pd.read_pickle(artifacts / "label.pkl").iloc[:, 0].rename("label")
        panels[version] = pd.concat([score, label], axis=1).dropna()

    common_index = None
    for panel in panels.values():
        common_index = panel.index if common_index is None else common_index.intersection(panel.index)
    common_index = common_index[
        (common_index.get_level_values("datetime") >= COMPARISON_START)
        & (common_index.get_level_values("datetime") <= COMPARISON_END)
    ].sort_values()
    if common_index.empty:
        raise RuntimeError("No common labelled stock-days in the frozen comparison period")

    reference_label = panels["A_full_alpha158"].loc[common_index, "label"]
    scores = {}
    for version, panel in panels.items():
        candidate_label = panel.loc[common_index, "label"]
        if not np.allclose(reference_label.to_numpy(), candidate_label.to_numpy(), rtol=0, atol=1e-12):
            raise RuntimeError(f"Saved labels differ between A and {version}; attribution would be invalid")
        scores[version] = panel.loc[common_index, "score"]
    return pd.DataFrame(scores, index=common_index), reference_label


def position_snapshot(position: object) -> tuple[pd.Series, pd.Series, float]:
    """Extract end-of-day asset weights, marked prices, and cash weight."""
    raw = position.position
    account_value = float(raw["now_account_value"])
    weights = {}
    prices = {}
    for instrument, value in raw.items():
        if instrument in {"cash", "cash_delay", "now_account_value"}:
            continue
        weight = value.get("weight")
        if weight is None:
            weight = value["amount"] * value["price"] / account_value
        weights[instrument] = float(weight)
        prices[instrument] = float(value["price"])
    return (
        pd.Series(weights, dtype="float64"),
        pd.Series(prices, dtype="float64"),
        float(raw["cash"] / account_value),
    )


def load_actual_stock_closes(mlruns_dir: Path, qlib_data_dir: Path) -> pd.Series:
    """Load closes for every stock that any saved portfolio actually held."""
    instruments = set()
    dates = set()
    for run in RUNS.values():
        artifacts = artifact_dir(mlruns_dir, run)
        positions = pd.read_pickle(artifacts / "portfolio_analysis" / "positions_normal_1day.pkl")
        for date, position in positions.items():
            dates.add(pd.Timestamp(date))
            instruments.update(position.get_stock_list())
    if not instruments or not dates:
        raise RuntimeError("Saved runs contain no dated stock positions")

    qlib.init(provider_uri=str(qlib_data_dir), region=REG_CN)
    field = "$close"
    closes = D.features(
        sorted(instruments),
        [field],
        start_time=min(dates),
        end_time=max(dates),
        freq="day",
    ).iloc[:, 0]
    closes.name = "actual_stock_close"
    return closes


def build_signal_date_mapping(report: pd.DataFrame, signal_dates: pd.DatetimeIndex) -> pd.DataFrame:
    """Map score date t to execution t+1 and realized return t+2 for this daily Qlib run."""
    calendar = pd.DatetimeIndex(report.index).sort_values()
    locations = {date: index for index, date in enumerate(calendar)}
    records = []
    for signal_date in signal_dates:
        if signal_date not in locations:
            raise RuntimeError(f"Score date {signal_date.date()} is absent from the backtest calendar")
        location = locations[signal_date]
        if location + 2 >= len(calendar):
            raise RuntimeError(f"Backtest lacks execution/realization dates after {signal_date.date()}")
        records.append(
            {
                "signal_date": signal_date,
                "execution_date": calendar[location + 1],
                "realization_date": calendar[location + 2],
            }
        )
    return pd.DataFrame(records).set_index("signal_date")


def event_rows_for_version(
    version: str,
    scores: pd.Series,
    labels: pd.Series,
    actual_stock_closes: pd.Series,
    artifacts: Path,
) -> pd.DataFrame:
    """Join signal t, actual position t+1, and report return t+2 for one frozen version."""
    report = pd.read_pickle(artifacts / "portfolio_analysis" / "report_normal_1day.pkl")
    positions = pd.read_pickle(artifacts / "portfolio_analysis" / "positions_normal_1day.pkl")
    indicators = pd.read_pickle(artifacts / "portfolio_analysis" / "indicators_normal_1day.pkl")
    signal_dates = pd.DatetimeIndex(scores.index.get_level_values("datetime").unique()).sort_values()
    mapping = build_signal_date_mapping(report, signal_dates)
    rows = []

    for signal_date in signal_dates:
        execution_date = mapping.at[signal_date, "execution_date"]
        realization_date = mapping.at[signal_date, "realization_date"]
        if execution_date not in positions:
            raise RuntimeError(f"{version} has no saved position on {execution_date.date()}")

        score = scores.xs(signal_date, level="datetime")
        label = labels.xs(signal_date, level="datetime")
        weights, execution_prices, cash_weight = position_snapshot(positions[execution_date])
        realization_closes = actual_stock_closes.xs(realization_date, level="datetime").reindex(weights.index)
        held_return = realization_closes / execution_prices - 1.0
        held_score = score.reindex(weights.index)
        static_top = score.nlargest(TOP_K).index
        static_top_label = label.reindex(static_top)
        rank = score.rank(method="first", ascending=False)

        # Qlib keeps the previous closing price when a holding is suspended; its contribution is zero.
        reconstructed_return = float((weights * held_return.fillna(0.0)).sum())
        reported_return = float(report.at[realization_date, "return"])
        indicator = indicators.loc[execution_date]
        overlap = weights.index.intersection(static_top)
        rows.append(
            {
                "signal_date": signal_date,
                "version": version,
                "execution_date": execution_date,
                "realization_date": realization_date,
                "universe_count": int(len(score)),
                "holding_count": int(len(weights)),
                "stock_weight": float(weights.sum()),
                "cash_weight": cash_weight,
                "actual_close_coverage_weight": float(weights.loc[realization_closes.notna()].sum()),
                "static_top50_label_return": float(static_top_label.mean()),
                "actual_equal_weight_holding_return": float(held_return.mean()),
                "actual_weighted_holding_return": reconstructed_return,
                "portfolio_formation_gap_vs_static_top50": float(
                    reconstructed_return - static_top_label.mean()
                ),
                "actual_top50_overlap_count": int(len(overlap)),
                "actual_top50_overlap_of_holdings": float(len(overlap) / len(weights)) if len(weights) else np.nan,
                "actual_top50_overlap_of_static_top50": float(len(overlap) / TOP_K),
                "mean_held_score_rank_percentile": float(rank.reindex(weights.index).mean() / len(score)),
                "score_coverage_of_holdings": float(held_score.notna().mean()),
                "reconstructed_gross_return": reconstructed_return,
                "reported_gross_return": reported_return,
                "gross_return_reconstruction_residual": float(reconstructed_return - reported_return),
                "realized_benchmark_return": float(report.at[realization_date, "bench"]),
                "execution_turnover_rate": float(report.at[execution_date, "turnover"]),
                "execution_cost_rate": float(report.at[execution_date, "cost"]),
                "execution_order_count": float(indicator["count"]),
                "execution_deal_amount": float(indicator["deal_amount"]),
                "execution_fill_rate": float(indicator["ffr"]) if pd.notna(indicator["ffr"]) else np.nan,
            }
        )
    return pd.DataFrame(rows).set_index("signal_date").sort_index()


def summarize_period(events: pd.DataFrame, feature_count: int, version: str, period: str, start: pd.Timestamp, end: pd.Timestamp) -> dict:
    """Summarize a score-date period using only arithmetic means, not a new backtest."""
    subset = events.loc[start:end]
    if subset.empty:
        raise ValueError(f"No event rows for {version} in {period}")
    return {
        "version": version,
        "feature_count": feature_count,
        "period": period,
        "signal_start": subset.index.min().date().isoformat(),
        "signal_end": subset.index.max().date().isoformat(),
        "events": int(len(subset)),
        "static_top50_annualized_label_return": float(subset["static_top50_label_return"].mean() * ANNUALIZATION_DAYS),
        "actual_weighted_holding_annualized_gross_return": float(
            subset["actual_weighted_holding_return"].mean() * ANNUALIZATION_DAYS
        ),
        "portfolio_formation_gap_annualized": float(
            subset["portfolio_formation_gap_vs_static_top50"].mean() * ANNUALIZATION_DAYS
        ),
        "realized_benchmark_annualized_return": float(
            subset["realized_benchmark_return"].mean() * ANNUALIZATION_DAYS
        ),
        "gross_excess_annualized_return": float(
            (subset["reconstructed_gross_return"] - subset["realized_benchmark_return"]).mean()
            * ANNUALIZATION_DAYS
        ),
        "execution_cost_annualized_drag": float(subset["execution_cost_rate"].mean() * ANNUALIZATION_DAYS),
        "signal_aligned_fee_after_excess_annualized_return": float(
            (
                subset["reconstructed_gross_return"]
                - subset["realized_benchmark_return"]
                - subset["execution_cost_rate"]
            ).mean()
            * ANNUALIZATION_DAYS
        ),
        "mean_stock_weight": float(subset["stock_weight"].mean()),
        "mean_cash_weight": float(subset["cash_weight"].mean()),
        "mean_holding_count": float(subset["holding_count"].mean()),
        "mean_actual_top50_overlap": float(subset["actual_top50_overlap_of_static_top50"].mean()),
        "mean_held_score_rank_percentile": float(subset["mean_held_score_rank_percentile"].mean()),
        "mean_execution_turnover_rate": float(subset["execution_turnover_rate"].mean()),
        "mean_execution_order_count": float(subset["execution_order_count"].mean()),
        "mean_execution_fill_rate": float(subset["execution_fill_rate"].mean()),
        "max_abs_gross_return_reconstruction_residual": float(
            subset["gross_return_reconstruction_residual"].abs().max()
        ),
    }


def comparison_row(summary: pd.DataFrame, candidate: str, baseline: str) -> dict:
    """Decompose a candidate-minus-baseline difference into static selection, formation, and cost."""
    left = summary.loc[candidate]
    right = summary.loc[baseline]
    static_delta = (
        left["static_top50_annualized_label_return"] - right["static_top50_annualized_label_return"]
    )
    formation_delta = left["portfolio_formation_gap_annualized"] - right["portfolio_formation_gap_annualized"]
    gross_delta = (
        left["actual_weighted_holding_annualized_gross_return"]
        - right["actual_weighted_holding_annualized_gross_return"]
    )
    cost_saving = right["execution_cost_annualized_drag"] - left["execution_cost_annualized_drag"]
    net_delta = (
        left["signal_aligned_fee_after_excess_annualized_return"]
        - right["signal_aligned_fee_after_excess_annualized_return"]
    )
    if not np.isclose(static_delta + formation_delta, gross_delta, atol=1e-12):
        raise RuntimeError("Attribution identity failed for gross-return decomposition")
    if not np.isclose(gross_delta + cost_saving, net_delta, atol=1e-12):
        raise RuntimeError("Attribution identity failed for fee-after decomposition")
    return {
        "candidate": candidate,
        "baseline": baseline,
        "static_top50_selection_delta": float(static_delta),
        "portfolio_formation_gap_delta": float(formation_delta),
        "actual_weighted_holding_gross_return_delta": float(gross_delta),
        "execution_cost_saving": float(cost_saving),
        "signal_aligned_fee_after_excess_return_delta": float(net_delta),
        "top50_overlap_delta": float(
            left["mean_actual_top50_overlap"] - right["mean_actual_top50_overlap"]
        ),
        "turnover_delta": float(
            left["mean_execution_turnover_rate"] - right["mean_execution_turnover_rate"]
        ),
    }


def pct(value: float) -> str:
    return f"{value * 100:.2f}%"


def decimal(value: float) -> str:
    return f"{value:.3f}"


def write_report(path: Path, summary: pd.DataFrame, comparisons: pd.DataFrame, metadata: dict) -> None:
    """Write a concise Chinese audit report while retaining all event-level rows in CSV."""
    full = summary[summary["period"].eq("full")].set_index("version")
    display = full[
        [
            "feature_count",
            "static_top50_annualized_label_return",
            "actual_weighted_holding_annualized_gross_return",
            "portfolio_formation_gap_annualized",
            "gross_excess_annualized_return",
            "execution_cost_annualized_drag",
            "signal_aligned_fee_after_excess_annualized_return",
            "mean_actual_top50_overlap",
            "mean_execution_turnover_rate",
        ]
    ].copy()
    for column in [
        "static_top50_annualized_label_return",
        "actual_weighted_holding_annualized_gross_return",
        "portfolio_formation_gap_annualized",
        "gross_excess_annualized_return",
        "execution_cost_annualized_drag",
        "signal_aligned_fee_after_excess_annualized_return",
        "mean_actual_top50_overlap",
        "mean_execution_turnover_rate",
    ]:
        display[column] = display[column].map(pct)

    yearly = summary[summary["period"].ne("full")][
        [
            "version",
            "period",
            "events",
            "static_top50_annualized_label_return",
            "actual_weighted_holding_annualized_gross_return",
            "portfolio_formation_gap_annualized",
            "signal_aligned_fee_after_excess_annualized_return",
        ]
    ].copy()
    for column in [
        "static_top50_annualized_label_return",
        "actual_weighted_holding_annualized_gross_return",
        "portfolio_formation_gap_annualized",
        "signal_aligned_fee_after_excess_annualized_return",
    ]:
        yearly[column] = yearly[column].map(pct)

    b_vs_a = comparisons[
        (comparisons["candidate"].eq("B_core13")) & (comparisons["baseline"].eq("A_full_alpha158"))
    ].iloc[0]
    c_vs_a = comparisons[
        (comparisons["candidate"].eq("C_core13_observe39"))
        & (comparisons["baseline"].eq("A_full_alpha158"))
    ].iloc[0]
    max_residual = full["max_abs_gross_return_reconstruction_residual"].max()
    fill_rates = full["mean_execution_fill_rate"]

    lines = [
        "CSI1000 Alpha158 固定 A/B/C：实际持仓—成交—收益归因审计 v1",
        "=" * 70,
        "",
        "目的：解释 B 的回测收益为何可能与其静态 Top 50 / 全截面排序表现不同，并核查收益是否能由已保存的实际持仓重建。",
        "本报告只读取固定 A/B/C 的预测、标签、持仓、成交指标与回测报告；没有重跑回测、训练或修改因子、模型、策略、成本和日期。",
        "",
        "时间映射（由 Qlib TopkDropout 源码和保存结果共同核验）：预测分数在 t 日读取，订单在下一交易日 t+1 执行，t+1 日收盘后的实际持仓在下一交易日 t+2 产生价格收益。",
        "标签 Ref($close,-2)/Ref($close,-1)-1 标在 t 日，正是从 t+1 收盘到 t+2 收盘的收益。因此，本审计以每个标签日 t 为单位，配对 t+1 实际持仓和 t+2 回测收益。",
        f"共同信号日期：{metadata['signal_start']} 至 {metadata['signal_end']}，共 {metadata['signal_days']} 日；每日共同股票数 {metadata['min_universe_size']} 至 {metadata['max_universe_size']}。",
        f"持仓权重乘同一 Qlib 行情源的 t+1 至 t+2 收盘收益后，与 Qlib 报告的 t+2 费用前收益的最大绝对残差为 {max_residual:.2e}（阈值 {RECONSTRUCTION_TOLERANCE:.0e}），归因重建通过。",
        "",
        "指标定义：静态 Top 50 是 t 日预测分最高的 50 只股票的等权标签平均；实际持仓收益是 t+1 收盘持仓权重乘随后一期收盘收益。对已不在当日 CSI1000 信号样本、但组合仍继续持有的股票，直接从同一 Qlib 行情源读取收盘价，不把缺失标签错误地当作零收益。两者之差称为“组合形成缺口”，包含 n_drop=5 的持仓延续、实际权重和现金比例，不能被误称为模型预测误差。",
        "费用后超额为信号日对齐的算术均值：实际持仓 t+2 收益 - t+2 基准收益 - t+1 执行成本。它用于总收益归因，不与原 Qlib 按自然日记录的 IR/回撤指标混用。",
        "",
        "全期归因（均为年化算术均值；静态标签收益不是策略收益）：",
        display.to_string(),
        "",
        "B 对 A 的收益分解：",
        f"- 静态 Top 50 选择差异：{pct(b_vs_a['static_top50_selection_delta'])}。负值表示 B 当天最高分 50 只的原始标签表现低于 A。",
        f"- 组合形成缺口差异：{pct(b_vs_a['portfolio_formation_gap_delta'])}。这是持仓延续、实际权重与现金配置共同造成的差异。",
        f"- 实际持仓费用前年化收益差异：{pct(b_vs_a['actual_weighted_holding_gross_return_delta'])}，等于前两项之和。",
        f"- 年化执行成本节省：{pct(b_vs_a['execution_cost_saving'])}；信号日对齐的费用后超额差异：{pct(b_vs_a['signal_aligned_fee_after_excess_return_delta'])}。",
        f"- 实际持仓与当天静态 Top 50 的平均重合率变化：{pct(b_vs_a['top50_overlap_delta'])}；日均换手率变化：{pct(b_vs_a['turnover_delta'])}。",
        "",
        "C 对 A 的同口径诊断：",
        f"- 静态选择差异 {pct(c_vs_a['static_top50_selection_delta'])}；组合形成缺口差异 {pct(c_vs_a['portfolio_formation_gap_delta'])}；费用后超额差异 {pct(c_vs_a['signal_aligned_fee_after_excess_return_delta'])}。",
        "",
        "分年描述（仍是回溯确认，不用于调参）：",
        yearly.to_string(index=False),
        "",
        "成交约束能确认与不能确认的部分：",
        f"- 已提交订单的平均成交完成率（ffr）为 A {decimal(fill_rates['A_full_alpha158'])}、B {decimal(fill_rates['B_core13'])}、C {decimal(fill_rates['C_core13_observe39'])}；已提交订单在该口径下均被成交。",
        "- 但 TopkDropout 在创建订单前会先检查停牌和涨跌停并跳过不可交易股票，保存的 indicators_normal_1day.pkl 没有“原始意图订单”日志。因此 ffr=1 不能证明没有停牌/涨跌停影响，也不能量化被跳过的候选股票数。",
        "",
        "结论边界：本审计只能说明回测收益由实际持仓路径而非每天静态 Top 50 单独决定；它不是采用 B 的新证据，不推翻 B 对 A 的预先冻结判定，也不授权修改任何版本。下一步如需继续，须先审查本报告并决定是否为未来前瞻观察冻结一个版本。",
    ]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mlruns-dir", type=Path, default=Path("output/mlruns_static"))
    parser.add_argument(
        "--qlib-data-dir",
        type=Path,
        default=Path("~/.qlib/qlib_data/cn_data_2026").expanduser(),
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("output/analysis_static/csi1000_alpha158_execution_attribution_v1"),
    )
    args = parser.parse_args()

    all_scores, labels = load_common_signal_panel(args.mlruns_dir)
    actual_stock_closes = load_actual_stock_closes(args.mlruns_dir, args.qlib_data_dir)
    events_by_version = {}
    for version, run in RUNS.items():
        artifacts = artifact_dir(args.mlruns_dir, run)
        events_by_version[version] = event_rows_for_version(
            version,
            all_scores[version],
            labels,
            actual_stock_closes,
            artifacts,
        )

    event_rows = pd.concat(events_by_version.values(), keys=events_by_version.keys(), names=["run", "signal_date"])
    event_rows = event_rows.reset_index(level="run", drop=True).reset_index().sort_values(["version", "signal_date"])
    max_residual = event_rows["gross_return_reconstruction_residual"].abs().max()
    if max_residual > RECONSTRUCTION_TOLERANCE:
        raise RuntimeError(
            f"Actual holdings do not reproduce saved gross returns: max residual {max_residual:.3e}"
        )

    summary_rows = []
    for version, run in RUNS.items():
        events = events_by_version[version]
        for period, (start, end) in PERIODS.items():
            summary_rows.append(summarize_period(events, run["feature_count"], version, period, start, end))
    summary = pd.DataFrame(summary_rows)
    full_summary = summary[summary["period"].eq("full")].set_index("version")
    comparisons = pd.DataFrame(
        [
            comparison_row(full_summary, "B_core13", "A_full_alpha158"),
            comparison_row(full_summary, "C_core13_observe39", "A_full_alpha158"),
            comparison_row(full_summary, "C_core13_observe39", "B_core13"),
        ]
    )

    signal_dates = pd.DatetimeIndex(all_scores.index.get_level_values("datetime").unique()).sort_values()
    universe_counts = all_scores.groupby(level="datetime").size()
    metadata = {
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "source_protocol": "research/protocols/csi1000_alpha158_model_comparison_protocol_v1.md",
        "analysis_type": "post-hoc execution attribution only; no model or strategy selection",
        "signal_start": signal_dates.min().date().isoformat(),
        "signal_end": signal_dates.max().date().isoformat(),
        "signal_days": int(len(signal_dates)),
        "min_universe_size": int(universe_counts.min()),
        "max_universe_size": int(universe_counts.max()),
        "top_k": TOP_K,
        "annualization_days": ANNUALIZATION_DAYS,
        "gross_return_reconstruction_tolerance": RECONSTRUCTION_TOLERANCE,
        "runs": RUNS,
    }

    args.output_dir.mkdir(parents=True, exist_ok=True)
    event_rows.to_csv(args.output_dir / "signal_event_attribution.csv.gz", index=False, compression="gzip")
    summary.to_csv(args.output_dir / "attribution_summary.csv", index=False)
    comparisons.to_csv(args.output_dir / "candidate_baseline_attribution.csv", index=False)
    (args.output_dir / "metadata.json").write_text(
        json.dumps(metadata, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    write_report(args.output_dir / "execution_attribution_report.txt", summary, comparisons, metadata)


if __name__ == "__main__":
    main()
