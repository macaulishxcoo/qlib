#!/usr/bin/env python3
"""Attribute the frozen CSI1000 Core13 portfolio by consecutive holding age."""

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

import qlib
from qlib.config import REG_CN
from qlib.data import D


EXPERIMENT_ID = "279845493254805780"
RUN_ID = "87746817d1924ad887b429044c8ec4c2"
ANNUALIZATION_DAYS = 238
TOP_K = 50
RECONSTRUCTION_TOLERANCE = 1e-5

COMPARISON_START = pd.Timestamp("2025-01-01")
COMPARISON_END = pd.Timestamp("2026-07-21")
PERIODS = {
    "full": (pd.Timestamp("2025-01-01"), pd.Timestamp("2026-07-21")),
    "year_2025": (pd.Timestamp("2025-01-01"), pd.Timestamp("2025-12-31")),
    "year_2026_to_0721": (pd.Timestamp("2026-01-01"), pd.Timestamp("2026-07-21")),
}
AGE_BUCKETS = ("age_1", "age_2_3", "age_4_5", "age_6_10", "age_11_20", "age_21_plus")


def artifact_dir(mlruns_dir: Path) -> Path:
    """Return the completed frozen B run and verify all required artifacts."""
    artifacts = mlruns_dir / EXPERIMENT_ID / RUN_ID / "artifacts"
    required = [
        artifacts / "pred.pkl",
        artifacts / "portfolio_analysis" / "positions_normal_1day.pkl",
        artifacts / "portfolio_analysis" / "report_normal_1day.pkl",
    ]
    missing = [str(path) for path in required if not path.is_file()]
    if missing:
        raise FileNotFoundError(f"Missing frozen Core13 artifact(s): {missing}")
    return artifacts


def age_bucket(age: int) -> str:
    """Map Qlib's consecutive holding-day counter to a stable reporting bucket."""
    if age == 1:
        return "age_1"
    if age <= 3:
        return "age_2_3"
    if age <= 5:
        return "age_4_5"
    if age <= 10:
        return "age_6_10"
    if age <= 20:
        return "age_11_20"
    return "age_21_plus"


def load_inputs(artifacts: Path) -> tuple[pd.Series, dict, pd.DataFrame]:
    """Load the frozen score, actual end-of-day positions, and backtest report."""
    predictions = pd.read_pickle(artifacts / "pred.pkl").iloc[:, 0].rename("score")
    dates = predictions.index.get_level_values("datetime")
    predictions = predictions[(dates >= COMPARISON_START) & (dates <= COMPARISON_END)]
    positions = pd.read_pickle(
        artifacts / "portfolio_analysis" / "positions_normal_1day.pkl"
    )
    report = pd.read_pickle(
        artifacts / "portfolio_analysis" / "report_normal_1day.pkl"
    )
    if predictions.empty or not positions or report.empty:
        raise RuntimeError("Frozen Core13 artifacts contain no usable data")
    return predictions, positions, report


def signal_date_mapping(report: pd.DataFrame, predictions: pd.Series) -> pd.DataFrame:
    """Map score date t to execution t+1 and realized return t+2."""
    calendar = pd.DatetimeIndex(report.index).sort_values()
    locations = {date: index for index, date in enumerate(calendar)}
    signal_dates = pd.DatetimeIndex(
        predictions.index.get_level_values("datetime").unique()
    ).sort_values()
    rows = []
    for signal_date in signal_dates:
        if signal_date not in locations:
            raise RuntimeError(f"Signal date {signal_date.date()} is absent from report calendar")
        location = locations[signal_date]
        if location + 2 >= len(calendar):
            raise RuntimeError(f"No complete execution-return pair after {signal_date.date()}")
        rows.append(
            {
                "signal_date": signal_date,
                "execution_date": calendar[location + 1],
                "realization_date": calendar[location + 2],
            }
        )
    return pd.DataFrame(rows).set_index("signal_date")


def load_realization_closes(positions: dict, qlib_data_dir: Path) -> pd.Series:
    """Load closes for every stock appearing in the frozen portfolio."""
    instruments = set()
    for position in positions.values():
        instruments.update(position.get_stock_list())
    if not instruments:
        raise RuntimeError("Frozen Core13 run has no stock positions")
    qlib.init(provider_uri=str(qlib_data_dir), region=REG_CN)
    closes = D.features(
        sorted(instruments),
        ["$close"],
        start_time=min(positions),
        end_time=max(positions),
        freq="day",
    ).iloc[:, 0]
    closes.name = "realization_close"
    return closes


def build_stock_events(
    predictions: pd.Series,
    positions: dict,
    report: pd.DataFrame,
    closes: pd.Series,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Build one row per held stock and verify it reconstructs saved gross returns."""
    mapping = signal_date_mapping(report, predictions)
    stock_rows = []
    daily_rows = []

    for signal_date, dates in mapping.iterrows():
        execution_date = dates["execution_date"]
        realization_date = dates["realization_date"]
        if execution_date not in positions or realization_date not in positions:
            raise RuntimeError(f"Missing position around {signal_date.date()}")

        score = predictions.xs(signal_date, level="datetime")
        ranks = score.rank(method="first", ascending=False)
        top50 = set(score.nlargest(TOP_K).index)
        current = positions[execution_date].position
        next_stocks = set(positions[realization_date].get_stock_list())
        account_value = float(current["now_account_value"])
        realization_close = closes.xs(realization_date, level="datetime")
        reconstructed_return = 0.0

        for instrument in positions[execution_date].get_stock_list():
            value = current[instrument]
            weight = value.get("weight")
            if weight is None:
                weight = value["amount"] * value["price"] / account_value
            weight = float(weight)
            close = realization_close.get(instrument, np.nan)
            stock_return = 0.0 if pd.isna(close) else float(close / value["price"] - 1.0)
            age = int(value["count_day"])
            reconstructed_return += weight * stock_return
            stock_rows.append(
                {
                    "signal_date": signal_date,
                    "execution_date": execution_date,
                    "realization_date": realization_date,
                    "instrument": instrument,
                    "holding_age": age,
                    "age_bucket": age_bucket(age),
                    "weight": weight,
                    "stock_return": stock_return,
                    "weighted_return_contribution": weight * stock_return,
                    "benchmark_return": float(report.at[realization_date, "bench"]),
                    "current_score": float(score[instrument]) if instrument in score.index else np.nan,
                    "current_score_rank_percentile": (
                        float(ranks[instrument] / len(score)) if instrument in ranks.index else np.nan
                    ),
                    "is_current_top50": instrument in top50,
                    "exits_next_day": instrument not in next_stocks,
                    "realization_close_available": pd.notna(close),
                }
            )

        reported_return = float(report.at[realization_date, "return"])
        daily_rows.append(
            {
                "signal_date": signal_date,
                "execution_date": execution_date,
                "realization_date": realization_date,
                "holding_count": len(positions[execution_date].get_stock_list()),
                "reconstructed_gross_return": reconstructed_return,
                "reported_gross_return": reported_return,
                "reconstruction_residual": reconstructed_return - reported_return,
                "benchmark_return": float(report.at[realization_date, "bench"]),
            }
        )

    stock_events = pd.DataFrame(stock_rows).sort_values(["signal_date", "holding_age", "instrument"])
    daily_total = pd.DataFrame(daily_rows).set_index("signal_date").sort_index()
    max_residual = daily_total["reconstruction_residual"].abs().max()
    if max_residual > RECONSTRUCTION_TOLERANCE:
        raise RuntimeError(
            f"Holding-age reconstruction does not match Qlib return: {max_residual:.3e}"
        )
    return stock_events, daily_total


def build_daily_age_metrics(stock_events: pd.DataFrame) -> pd.DataFrame:
    """Aggregate stock rows to daily age-bucket portfolios."""
    rows = []
    for (signal_date, bucket), group in stock_events.groupby(
        ["signal_date", "age_bucket"], sort=True, observed=True
    ):
        weight = group["weight"].sum()
        contribution = group["weighted_return_contribution"].sum()
        rows.append(
            {
                "signal_date": signal_date,
                "age_bucket": bucket,
                "stock_count": int(len(group)),
                "weight_share": float(weight),
                "gross_return_contribution": float(contribution),
                "normalized_group_return": float(contribution / weight),
                "normalized_group_excess_return": float(
                    contribution / weight - group["benchmark_return"].iloc[0]
                ),
                "mean_holding_age": float(group["holding_age"].mean()),
                "mean_current_score_rank_percentile": float(
                    group["current_score_rank_percentile"].mean()
                ),
                "current_score_coverage": float(group["current_score"].notna().mean()),
                "current_top50_ratio": float(group["is_current_top50"].mean()),
                "next_day_exit_rate": float(group["exits_next_day"].mean()),
            }
        )
    return pd.DataFrame(rows).sort_values(["signal_date", "age_bucket"])


def summarize_age_buckets(
    stock_events: pd.DataFrame,
    daily_age: pd.DataFrame,
    daily_total: pd.DataFrame,
) -> pd.DataFrame:
    """Summarize fixed periods while preserving the portfolio contribution identity."""
    rows = []
    for period, (start, end) in PERIODS.items():
        period_dates = daily_total.loc[start:end].index
        total_days = len(period_dates)
        if not total_days:
            raise RuntimeError(f"No events in {period}")
        stock_period = stock_events[
            stock_events["signal_date"].between(start, end, inclusive="both")
        ]
        daily_period = daily_age[daily_age["signal_date"].isin(period_dates)]
        for bucket in AGE_BUCKETS:
            stock_subset = stock_period[stock_period["age_bucket"].eq(bucket)]
            daily_subset = daily_period[daily_period["age_bucket"].eq(bucket)].set_index(
                "signal_date"
            )
            contribution = daily_subset["gross_return_contribution"].reindex(
                period_dates, fill_value=0.0
            )
            count = daily_subset["stock_count"].reindex(period_dates, fill_value=0.0)
            weight = daily_subset["weight_share"].reindex(period_dates, fill_value=0.0)
            rows.append(
                {
                    "period": period,
                    "age_bucket": bucket,
                    "signal_days": total_days,
                    "active_days": int(len(daily_subset)),
                    "stock_day_observations": int(len(stock_subset)),
                    "mean_holding_count": float(count.mean()),
                    "mean_weight_share": float(weight.mean()),
                    "annualized_portfolio_gross_contribution": float(
                        contribution.mean() * ANNUALIZATION_DAYS
                    ),
                    "normalized_group_annualized_return": float(
                        daily_subset["normalized_group_return"].mean() * ANNUALIZATION_DAYS
                    ),
                    "normalized_group_annualized_excess_return": float(
                        daily_subset["normalized_group_excess_return"].mean()
                        * ANNUALIZATION_DAYS
                    ),
                    "mean_holding_age": float(stock_subset["holding_age"].mean()),
                    "mean_current_score_rank_percentile": float(
                        daily_subset["mean_current_score_rank_percentile"].mean()
                    ),
                    "current_score_coverage": float(
                        daily_subset["current_score_coverage"].mean()
                    ),
                    "current_top50_ratio": float(daily_subset["current_top50_ratio"].mean()),
                    "next_day_exit_rate": float(daily_subset["next_day_exit_rate"].mean()),
                }
            )

        period_rows = rows[-len(AGE_BUCKETS) :]
        bucket_contribution = sum(
            row["annualized_portfolio_gross_contribution"] for row in period_rows
        )
        reported = float(daily_total.loc[start:end, "reported_gross_return"].mean() * ANNUALIZATION_DAYS)
        if not np.isclose(bucket_contribution, reported, atol=1e-12):
            raise RuntimeError(f"Age-bucket contribution identity failed in {period}")
    return pd.DataFrame(rows)


def pct(value: float) -> str:
    return f"{value * 100:.2f}%"


def write_report(
    path: Path,
    summary: pd.DataFrame,
    daily_total: pd.DataFrame,
    metadata: dict,
) -> None:
    """Write a Chinese post-hoc report without making a strategy decision."""
    columns = [
        "age_bucket",
        "mean_holding_count",
        "mean_weight_share",
        "annualized_portfolio_gross_contribution",
        "normalized_group_annualized_excess_return",
        "mean_current_score_rank_percentile",
        "current_top50_ratio",
        "next_day_exit_rate",
    ]
    full = summary[summary["period"].eq("full")][columns].copy()
    yearly = summary[summary["period"].ne("full")][
        [
            "period",
            "age_bucket",
            "mean_weight_share",
            "annualized_portfolio_gross_contribution",
            "normalized_group_annualized_excess_return",
            "current_top50_ratio",
        ]
    ].copy()
    percent_columns = [
        "mean_weight_share",
        "annualized_portfolio_gross_contribution",
        "normalized_group_annualized_excess_return",
        "mean_current_score_rank_percentile",
        "current_top50_ratio",
        "next_day_exit_rate",
    ]
    for frame in (full, yearly):
        for column in percent_columns:
            if column in frame:
                frame[column] = frame[column].map(pct)
    full["mean_holding_count"] = full["mean_holding_count"].map(lambda value: f"{value:.2f}")

    full_summary = summary[summary["period"].eq("full")]
    gross_contribution = full_summary["annualized_portfolio_gross_contribution"].sum()
    max_residual = daily_total["reconstruction_residual"].abs().max()
    lines = [
        "CSI1000 Core13 固定 B：持仓年龄—收益归因审计 v1",
        "=" * 64,
        "",
        "目的：解释 n_drop=5 保留的旧持仓是否持续贡献收益，并判断此前观察到的组合形成优势来自哪些持有年龄。",
        "本报告只读取固定 B 已保存的预测、实际持仓和回测收益；没有重新训练、回测、扫描 n_drop 或修改策略。",
        "",
        "信息边界：2025-2026 已被反复查看，本报告属于事后归因，只能解释既有结果，不能用来选择新的 n_drop 或证明未来有效。",
        f"信号日期：{metadata['signal_start']} 至 {metadata['signal_end']}，共 {metadata['signal_days']} 日。",
        f"Qlib 持仓字段 count_day 直接表示连续持有交易日数；归因重建与保存的每日费用前收益最大误差 {max_residual:.2e}。",
        "",
        "指标解释：",
        "- 仓位占比：该年龄组股票占账户总资产的平均比例。",
        "- 收益贡献：该组每天权重乘收益后对整个账户的贡献，所有年龄组合计等于实际费用前组合收益。",
        "- 组内年化超额：把该年龄组自身归一为 100% 仓位后，相对同期 CSI1000 基准的算术年化收益；用于比较持仓质量，不是可直接相加的组合收益。",
        "- 当前排名百分位越小越好；Top50 比例表示该组仍在当日最新 Top50 中的股票占比。",
        "",
        "全期年龄归因：",
        full.to_string(index=False),
        "",
        f"各年龄组费用前收益贡献合计：{pct(gross_contribution)}。",
        "",
        "分年检查：",
        yearly.to_string(index=False),
        "",
        "结论边界：本报告只回答旧持仓在既有回测中如何贡献收益。是否改变 n_drop，必须在未用于本报告的开发口径中预先声明候选参数和判定门槛后另做实验。",
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
        default=Path("output/analysis_static/csi1000_core13_holding_age_attribution_v1"),
    )
    args = parser.parse_args()

    artifacts = artifact_dir(args.mlruns_dir)
    predictions, positions, report = load_inputs(artifacts)
    closes = load_realization_closes(positions, args.qlib_data_dir)
    stock_events, daily_total = build_stock_events(predictions, positions, report, closes)
    daily_age = build_daily_age_metrics(stock_events)
    summary = summarize_age_buckets(stock_events, daily_age, daily_total)

    signal_dates = pd.DatetimeIndex(
        predictions.index.get_level_values("datetime").unique()
    ).sort_values()
    metadata = {
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "analysis_type": "post-hoc holding-age attribution only; not strategy selection",
        "source_experiment_id": EXPERIMENT_ID,
        "source_run_id": RUN_ID,
        "source_version": "B_core13",
        "signal_start": signal_dates.min().date().isoformat(),
        "signal_end": signal_dates.max().date().isoformat(),
        "signal_days": int(len(signal_dates)),
        "age_source": "Qlib Position stock field count_day",
        "age_buckets": list(AGE_BUCKETS),
        "annualization_days": ANNUALIZATION_DAYS,
        "reconstruction_tolerance": RECONSTRUCTION_TOLERANCE,
    }

    args.output_dir.mkdir(parents=True, exist_ok=True)
    stock_events.to_csv(
        args.output_dir / "stock_holding_age_events.csv.gz", index=False, compression="gzip"
    )
    daily_age.to_csv(
        args.output_dir / "daily_holding_age_metrics.csv.gz", index=False, compression="gzip"
    )
    daily_total.reset_index().to_csv(args.output_dir / "daily_reconstruction.csv", index=False)
    summary.to_csv(args.output_dir / "holding_age_summary.csv", index=False)
    (args.output_dir / "metadata.json").write_text(
        json.dumps(metadata, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    write_report(args.output_dir / "holding_age_report.txt", summary, daily_total, metadata)


if __name__ == "__main__":
    main()
