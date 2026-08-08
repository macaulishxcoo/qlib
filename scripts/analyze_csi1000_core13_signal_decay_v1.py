#!/usr/bin/env python3
"""Diagnose the development-period horizon and persistence of the frozen CSI1000 core13 model."""

import argparse
import json
import pickle
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

import qlib
from qlib.config import REG_CN
from qlib.data import D
from qlib.utils import init_instance_by_config


DEVELOPMENT_START = pd.Timestamp("2023-01-01")
DEVELOPMENT_END = pd.Timestamp("2024-12-31")
HORIZONS = (1, 3, 5, 10)
TOP_K = 50
ANNUALIZATION_DAYS = 238

EXPERIMENT_ID = "279845493254805780"
RUN_ID = "87746817d1924ad887b429044c8ec4c2"

PERIODS = {
    "full_2023_2024": (pd.Timestamp("2023-01-01"), pd.Timestamp("2024-12-31")),
    "year_2023": (pd.Timestamp("2023-01-01"), pd.Timestamp("2023-12-31")),
    "year_2024": (pd.Timestamp("2024-01-01"), pd.Timestamp("2024-12-31")),
}


def formal_artifact_dir(mlruns_dir: Path) -> Path:
    """Return the completed B run used by the already frozen A/B/C comparison."""
    artifacts = mlruns_dir / EXPERIMENT_ID / RUN_ID / "artifacts"
    required = [artifacts / "params.pkl", artifacts / "task"]
    missing = [str(path) for path in required if not path.is_file()]
    if missing:
        raise FileNotFoundError(f"Missing frozen B artifact(s): {missing}")
    return artifacts


def load_development_predictions(artifacts: Path) -> pd.Series:
    """Rebuild only the saved dataset handler and predict valid with the saved fitted model."""
    with (artifacts / "params.pkl").open("rb") as file:
        model = pickle.load(file)
    with (artifacts / "task").open("rb") as file:
        task = pickle.load(file)
    dataset = init_instance_by_config(task["dataset"])
    predictions = model.predict(dataset, segment="valid").rename("score")
    dates = predictions.index.get_level_values("datetime")
    predictions = predictions[(dates >= DEVELOPMENT_START) & (dates <= DEVELOPMENT_END)]
    if predictions.empty:
        raise RuntimeError("Saved B model produced no development-period predictions")
    return predictions


def return_expressions() -> tuple[list[str], list[str]]:
    """Define cumulative holding return and exact marginal future-day return after t+1 execution."""
    expressions = []
    names = []
    for horizon in HORIZONS:
        expressions.extend(
            [
                f"Ref($close,-{horizon + 1})/Ref($close,-1)-1",
                f"Ref($close,-{horizon + 1})/Ref($close,-{horizon})-1",
            ]
        )
        names.extend([f"cumulative_h{horizon}", f"marginal_h{horizon}"])
    return expressions, names


def load_forward_returns() -> pd.DataFrame:
    """Load point-in-time CSI1000 members and returns whose entry is the t+1 close."""
    expressions, names = return_expressions()
    returns = D.features(
        D.instruments("csi1000"),
        expressions,
        start_time=DEVELOPMENT_START,
        end_time=DEVELOPMENT_END,
        freq="day",
    )
    returns.columns = names
    return returns


def rank_ic(sample: pd.DataFrame) -> float:
    """Return daily cross-sectional Spearman IC after complete-case filtering."""
    sample = sample.dropna()
    if len(sample) < 50 or sample.iloc[:, 0].nunique() < 2 or sample.iloc[:, 1].nunique() < 2:
        return np.nan
    return float(sample.iloc[:, 0].corr(sample.iloc[:, 1], method="spearman"))


def daily_horizon_metrics(panel: pd.DataFrame) -> pd.DataFrame:
    """Measure cumulative and exact future-day IC plus cumulative Top 50 separation."""
    rows = []
    for date, day in panel.groupby(level="datetime", sort=True):
        score = day["score"]
        for horizon in HORIZONS:
            cumulative = day[f"cumulative_h{horizon}"]
            marginal = day[f"marginal_h{horizon}"]
            cumulative_sample = pd.concat([score, cumulative], axis=1).dropna()
            marginal_sample = pd.concat([score, marginal], axis=1).dropna()
            if len(cumulative_sample) >= TOP_K:
                ranked = cumulative_sample.sort_values("score", ascending=False)
                top_return = float(ranked.iloc[:TOP_K, 1].mean())
                bottom_return = float(ranked.iloc[-TOP_K:, 1].mean())
                universe_return = float(ranked.iloc[:, 1].mean())
            else:
                top_return = bottom_return = universe_return = np.nan
            rows.append(
                {
                    "datetime": date,
                    "horizon": horizon,
                    "cumulative_rank_ic": rank_ic(cumulative_sample),
                    "marginal_rank_ic": rank_ic(marginal_sample),
                    "cumulative_sample_count": int(len(cumulative_sample)),
                    "marginal_sample_count": int(len(marginal_sample)),
                    "cumulative_top50_return": top_return,
                    "cumulative_bottom50_return": bottom_return,
                    "cumulative_universe_return": universe_return,
                    "cumulative_top50_excess": top_return - universe_return,
                    "cumulative_top_minus_bottom": top_return - bottom_return,
                }
            )
    return pd.DataFrame(rows).set_index("datetime").sort_index()


def summarize_horizons(daily: pd.DataFrame) -> pd.DataFrame:
    """Summarize the frozen periods; horizon returns are scaled by their holding length."""
    rows = []
    for period, (start, end) in PERIODS.items():
        period_data = daily.loc[start:end]
        for horizon in HORIZONS:
            subset = period_data[period_data["horizon"].eq(horizon)]
            cumulative_ic = subset["cumulative_rank_ic"].dropna()
            marginal_ic = subset["marginal_rank_ic"].dropna()
            scale = ANNUALIZATION_DAYS / horizon
            rows.append(
                {
                    "period": period,
                    "horizon": horizon,
                    "days": int(len(subset)),
                    "cumulative_rank_ic": float(cumulative_ic.mean()),
                    "cumulative_rank_icir": float(cumulative_ic.mean() / cumulative_ic.std(ddof=1)),
                    "cumulative_rank_ic_positive_ratio": float((cumulative_ic > 0).mean()),
                    "marginal_rank_ic": float(marginal_ic.mean()),
                    "marginal_rank_icir": float(marginal_ic.mean() / marginal_ic.std(ddof=1)),
                    "marginal_rank_ic_positive_ratio": float((marginal_ic > 0).mean()),
                    "top50_annualized_cumulative_return": float(
                        subset["cumulative_top50_return"].mean() * scale
                    ),
                    "top50_excess_annualized_return": float(
                        subset["cumulative_top50_excess"].mean() * scale
                    ),
                    "top_minus_bottom_annualized_return": float(
                        subset["cumulative_top_minus_bottom"].mean() * scale
                    ),
                    "median_cumulative_sample_count": float(
                        subset["cumulative_sample_count"].median()
                    ),
                }
            )
    return pd.DataFrame(rows)


def score_persistence(predictions: pd.Series) -> pd.DataFrame:
    """Measure rank persistence and Top 50 membership persistence at fixed trading-day lags."""
    wide = predictions.unstack("instrument").sort_index()
    rows = []
    for lag in HORIZONS:
        for index in range(len(wide) - lag):
            first = wide.iloc[index].dropna()
            second = wide.iloc[index + lag].dropna()
            common = first.index.intersection(second.index)
            if len(common) < 50:
                continue
            first = first.loc[common]
            second = second.loc[common]
            first_top = set(first.nlargest(TOP_K).index)
            second_top = set(second.nlargest(TOP_K).index)
            overlap = len(first_top.intersection(second_top))
            rows.append(
                {
                    "start_date": wide.index[index],
                    "end_date": wide.index[index + lag],
                    "lag": lag,
                    "common_stock_count": int(len(common)),
                    "score_rank_spearman": float(first.corr(second, method="spearman")),
                    "top50_overlap_count": overlap,
                    "top50_overlap_ratio": float(overlap / TOP_K),
                    "top50_replacements_needed": int(TOP_K - overlap),
                }
            )
    return pd.DataFrame(rows)


def summarize_persistence(daily: pd.DataFrame) -> pd.DataFrame:
    """Summarize score and membership persistence by lag and start-year."""
    rows = []
    scopes = {
        "full_2023_2024": daily,
        "year_2023": daily[daily["start_date"].dt.year.eq(2023)],
        "year_2024": daily[daily["start_date"].dt.year.eq(2024)],
    }
    for period, period_data in scopes.items():
        for lag in HORIZONS:
            subset = period_data[period_data["lag"].eq(lag)]
            rows.append(
                {
                    "period": period,
                    "lag": lag,
                    "pairs": int(len(subset)),
                    "mean_score_rank_spearman": float(subset["score_rank_spearman"].mean()),
                    "median_score_rank_spearman": float(subset["score_rank_spearman"].median()),
                    "mean_top50_overlap_ratio": float(subset["top50_overlap_ratio"].mean()),
                    "mean_top50_replacements_needed": float(
                        subset["top50_replacements_needed"].mean()
                    ),
                }
            )
    return pd.DataFrame(rows)


def pct(value: float) -> str:
    return f"{value * 100:.2f}%"


def decimal(value: float) -> str:
    return f"{value:.4f}"


def write_report(
    path: Path,
    horizon_summary: pd.DataFrame,
    persistence_summary: pd.DataFrame,
    metadata: dict,
) -> None:
    """Write the development-only diagnostic without making a strategy choice."""
    full = horizon_summary[horizon_summary["period"].eq("full_2023_2024")].copy()
    full_display = full[
        [
            "horizon",
            "cumulative_rank_ic",
            "cumulative_rank_icir",
            "marginal_rank_ic",
            "marginal_rank_icir",
            "top50_excess_annualized_return",
            "top_minus_bottom_annualized_return",
        ]
    ].copy()
    for column in ["cumulative_rank_ic", "marginal_rank_ic"]:
        full_display[column] = full_display[column].map(pct)
    for column in ["cumulative_rank_icir", "marginal_rank_icir"]:
        full_display[column] = full_display[column].map(decimal)
    for column in ["top50_excess_annualized_return", "top_minus_bottom_annualized_return"]:
        full_display[column] = full_display[column].map(pct)

    yearly = horizon_summary[horizon_summary["period"].ne("full_2023_2024")][
        ["period", "horizon", "cumulative_rank_ic", "marginal_rank_ic", "top50_excess_annualized_return"]
    ].copy()
    yearly["cumulative_rank_ic"] = yearly["cumulative_rank_ic"].map(pct)
    yearly["marginal_rank_ic"] = yearly["marginal_rank_ic"].map(pct)
    yearly["top50_excess_annualized_return"] = yearly["top50_excess_annualized_return"].map(pct)

    persistence = persistence_summary[
        persistence_summary["period"].eq("full_2023_2024")
    ][
        ["lag", "mean_score_rank_spearman", "mean_top50_overlap_ratio", "mean_top50_replacements_needed"]
    ].copy()
    persistence["mean_score_rank_spearman"] = persistence["mean_score_rank_spearman"].map(decimal)
    persistence["mean_top50_overlap_ratio"] = persistence["mean_top50_overlap_ratio"].map(pct)
    persistence["mean_top50_replacements_needed"] = persistence[
        "mean_top50_replacements_needed"
    ].map(lambda value: f"{value:.2f}")

    one_day = full.set_index("horizon").loc[1]
    ten_day = full.set_index("horizon").loc[10]
    one_day_persistence = persistence_summary[
        (persistence_summary["period"].eq("full_2023_2024"))
        & (persistence_summary["lag"].eq(1))
    ].iloc[0]
    lines = [
        "CSI1000 Core13 固定模型：开发期信号衰减与持有周期诊断 v1",
        "=" * 66,
        "",
        "目的：判断一日收益标签训练出的固定 B 模型，其预测信息能持续多久，以及 n_drop=5 的慢速换仓是否与信号寿命匹配。",
        "本步骤读取正式 B 运行保存的已拟合模型，在 2023-2024 valid 段生成分数；没有重新训练、回测或扫描策略参数。",
        "",
        "信息边界：2023-2024 曾用于 LightGBM early stopping 和因子开发，因此这里只能诊断信号周期，不能作为样本外收益证据。2025-2026 未用于本步骤。",
        f"有效预测日期：{metadata['prediction_start']} 至 {metadata['prediction_end']}，共 {metadata['prediction_days']} 日；每日预测股票数 {metadata['min_prediction_count']} 至 {metadata['max_prediction_count']}。",
        "",
        "口径：",
        "- 累计 h 日收益：在信号 t 后，于 t+1 收盘执行，持有 h 个交易日后的累计收益。",
        "- 边际第 h 日收益：只统计持有期第 h 个交易日自身的收益，用于判断信号何时真正衰减。",
        "- Top 50 超额为每日预测最高 50 只相对当日 CSI1000 样本平均收益；h>1 的收益存在重叠，只用于描述，不把 ICIR 当独立样本显著性。",
        "",
        "全开发期不同持有期限：",
        full_display.to_string(index=False),
        "",
        "分年稳定性：",
        yearly.to_string(index=False),
        "",
        "分数和 Top 50 名单稳定性：",
        persistence.to_string(index=False),
        "",
        "与 n_drop=5 的直接关系：",
        f"- 相邻两天 Top 50 平均重合率 {pct(one_day_persistence['mean_top50_overlap_ratio'])}，即若要每天精确跟踪最新 Top 50，平均需替换 {one_day_persistence['mean_top50_replacements_needed']:.2f} 只股票。",
        "- n_drop=5 每天最多主动替换约 5 只，只有当上述所需替换数接近 5、或边际预测力能维持约 10 天时，慢速组合才与信号自然匹配。",
        "",
        "关键诊断数值：",
        f"- 1 日累计/边际 Rank IC 均为 {pct(one_day['cumulative_rank_ic'])}；Top 50 年化超额 {pct(one_day['top50_excess_annualized_return'])}。",
        f"- 持有至 10 日的累计 Rank IC {pct(ten_day['cumulative_rank_ic'])}，但第 10 日自身的边际 Rank IC {pct(ten_day['marginal_rank_ic'])}。累计值不能替代边际值判断信号寿命。",
        "",
        "结论边界：本报告只提供周期诊断。是否停止 Core13、改变标签或调整 n_drop，必须由用户审查这些固定结果后另行决定；本步骤不授权任何参数修改。",
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
        default=Path("output/analysis_static/csi1000_core13_signal_decay_development_v1"),
    )
    args = parser.parse_args()

    qlib.init(provider_uri=str(args.qlib_data_dir), region=REG_CN)
    artifacts = formal_artifact_dir(args.mlruns_dir)
    predictions = load_development_predictions(artifacts)
    returns = load_forward_returns()
    panel = predictions.to_frame().join(returns, how="inner")
    daily = daily_horizon_metrics(panel)
    horizon_summary = summarize_horizons(daily)
    persistence_daily = score_persistence(predictions)
    persistence_summary = summarize_persistence(persistence_daily)

    prediction_counts = predictions.groupby(level="datetime").size()
    metadata = {
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "analysis_type": "development-only signal horizon diagnosis; not out-of-sample performance",
        "source_experiment_id": EXPERIMENT_ID,
        "source_run_id": RUN_ID,
        "source_version": "B_core13",
        "source_model_training": "2020-01-01 to 2022-12-31",
        "source_model_validation_and_early_stopping": "2023-01-01 to 2024-12-31",
        "prediction_start": predictions.index.get_level_values("datetime").min().date().isoformat(),
        "prediction_end": predictions.index.get_level_values("datetime").max().date().isoformat(),
        "prediction_days": int(len(prediction_counts)),
        "min_prediction_count": int(prediction_counts.min()),
        "max_prediction_count": int(prediction_counts.max()),
        "horizons": list(HORIZONS),
        "top_k": TOP_K,
        "annualization_days": ANNUALIZATION_DAYS,
        "return_entry_timing": "t+1 close",
    }

    args.output_dir.mkdir(parents=True, exist_ok=True)
    daily.reset_index().to_csv(
        args.output_dir / "daily_horizon_metrics.csv.gz", index=False, compression="gzip"
    )
    horizon_summary.to_csv(args.output_dir / "horizon_summary.csv", index=False)
    persistence_daily.to_csv(
        args.output_dir / "daily_score_persistence.csv.gz", index=False, compression="gzip"
    )
    persistence_summary.to_csv(args.output_dir / "score_persistence_summary.csv", index=False)
    (args.output_dir / "metadata.json").write_text(
        json.dumps(metadata, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    write_report(
        args.output_dir / "signal_decay_report.txt",
        horizon_summary,
        persistence_summary,
        metadata,
    )


if __name__ == "__main__":
    main()
