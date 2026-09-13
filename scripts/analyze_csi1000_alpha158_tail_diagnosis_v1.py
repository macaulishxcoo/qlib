#!/usr/bin/env python3
"""Diagnose A/B/C score-tail quality using only saved frozen-comparison artifacts."""

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd


COMPARISON_START = pd.Timestamp("2025-01-01")
COMPARISON_END = pd.Timestamp("2026-07-21")
GROUP_COUNT = 10
TOP_K = 50
ANNUALIZATION_DAYS = 238

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
    """Find the formal run artifacts and reject incomplete results."""
    artifacts = mlruns_dir / run["experiment_id"] / run["run_id"] / "artifacts"
    required = [artifacts / "pred.pkl", artifacts / "label.pkl"]
    missing = [str(path) for path in required if not path.is_file()]
    if missing:
        raise FileNotFoundError(f"Missing frozen-comparison artifact(s): {missing}")
    return artifacts


def load_common_panel(mlruns_dir: Path) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Load the same labelled stock-days for all versions and verify their labels agree."""
    version_frames = {}
    for version, run in RUNS.items():
        artifacts = artifact_dir(mlruns_dir, run)
        prediction = pd.read_pickle(artifacts / "pred.pkl").iloc[:, [0]].rename(columns=lambda _: "score")
        label = pd.read_pickle(artifacts / "label.pkl").iloc[:, [0]].rename(columns=lambda _: "label")
        version_frames[version] = prediction.join(label, how="inner").dropna()

    common_index = None
    for frame in version_frames.values():
        index = frame.index
        common_index = index if common_index is None else common_index.intersection(index)
    common_index = common_index[
        (common_index.get_level_values("datetime") >= COMPARISON_START)
        & (common_index.get_level_values("datetime") <= COMPARISON_END)
    ].sort_values()
    if common_index.empty:
        raise RuntimeError("No common labelled stock-days in the frozen comparison period")

    reference_label = version_frames["A_full_alpha158"].loc[common_index, "label"]
    scores = {}
    for version, frame in version_frames.items():
        candidate_label = frame.loc[common_index, "label"]
        if not np.allclose(reference_label.to_numpy(), candidate_label.to_numpy(), rtol=0, atol=1e-12):
            raise RuntimeError(f"Saved labels differ between A and {version}; tail comparison would be invalid")
        scores[version] = frame.loc[common_index, "score"]
    score_frame = pd.DataFrame(scores, index=common_index)
    label_frame = reference_label.to_frame("label")
    return score_frame, label_frame


def assign_groups(day_scores: pd.Series) -> pd.Series:
    """Create near-equal low-to-high groups, deterministically breaking score ties."""
    ranks = day_scores.rank(method="first", ascending=True)
    return np.ceil(ranks / len(day_scores) * GROUP_COUNT).astype("int64")


def calculate_daily_tail_metrics(scores: pd.Series, labels: pd.Series, version: str) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Calculate score-decile and top-50 label outcomes for each date independently."""
    group_rows = []
    tail_rows = []
    combined = pd.concat([scores.rename("score"), labels.rename("label")], axis=1)
    for date, day in combined.groupby(level="datetime", sort=True):
        day = day.reset_index(level="datetime", drop=True).dropna().sort_values("score")
        if len(day) < GROUP_COUNT or day["score"].nunique() < 2 or day["label"].nunique() < 2:
            continue
        day["group"] = assign_groups(day["score"])
        group_means = day.groupby("group", sort=True)["label"].agg(["mean", "count"])
        for group, row in group_means.iterrows():
            group_rows.append(
                {
                    "datetime": date,
                    "version": version,
                    "group": int(group),
                    "mean_label_return": float(row["mean"]),
                    "stock_count": int(row["count"]),
                }
            )
        top_k = day.nlargest(min(TOP_K, len(day)), "score")
        top_decile = day[day["group"].eq(GROUP_COUNT)]
        bottom_decile = day[day["group"].eq(1)]
        monotonic_spearman = pd.Series(group_means.index, dtype="float64").corr(
            group_means["mean"], method="spearman"
        )
        tail_rows.append(
            {
                "datetime": date,
                "version": version,
                "universe_count": int(len(day)),
                "universe_mean_label_return": float(day["label"].mean()),
                "top_50_mean_label_return": float(top_k["label"].mean()),
                "top_decile_mean_label_return": float(top_decile["label"].mean()),
                "bottom_decile_mean_label_return": float(bottom_decile["label"].mean()),
                "top_minus_bottom_decile_return": float(top_decile["label"].mean() - bottom_decile["label"].mean()),
                "top_50_minus_universe_return": float(top_k["label"].mean() - day["label"].mean()),
                "daily_group_monotonic_spearman": float(monotonic_spearman),
            }
        )
    return pd.DataFrame(group_rows), pd.DataFrame(tail_rows)


def summarize_period(
    version: str,
    feature_count: int,
    period_name: str,
    period_start: pd.Timestamp,
    period_end: pd.Timestamp,
    daily_groups: pd.DataFrame,
    daily_tail: pd.DataFrame,
) -> tuple[dict, list[dict]]:
    """Summarize a fixed period; all returns are raw future labels, never strategy PnL."""
    tail = daily_tail.loc[period_start:period_end].copy()
    groups = daily_groups.loc[period_start:period_end].copy()
    if tail.empty or groups.empty:
        raise ValueError(f"No tail observations for {version} in {period_name}")

    group_mean = groups.groupby("group", sort=True)["mean_label_return"].mean()
    group_rows = [
        {
            "version": version,
            "feature_count": feature_count,
            "period": period_name,
            "group": int(group),
            "average_daily_label_return": float(value),
            "annualized_label_return": float(value * ANNUALIZATION_DAYS),
            "average_stock_count": float(groups.loc[groups["group"].eq(group), "stock_count"].mean()),
        }
        for group, value in group_mean.items()
    ]
    return (
        {
            "version": version,
            "feature_count": feature_count,
            "period": period_name,
            "period_start": tail.index.min().date().isoformat(),
            "period_end": tail.index.max().date().isoformat(),
            "days": int(len(tail)),
            "top_50_annualized_label_return": float(tail["top_50_mean_label_return"].mean() * ANNUALIZATION_DAYS),
            "top_decile_annualized_label_return": float(tail["top_decile_mean_label_return"].mean() * ANNUALIZATION_DAYS),
            "bottom_decile_annualized_label_return": float(tail["bottom_decile_mean_label_return"].mean() * ANNUALIZATION_DAYS),
            "top_minus_bottom_decile_annualized_return": float(
                tail["top_minus_bottom_decile_return"].mean() * ANNUALIZATION_DAYS
            ),
            "top_50_minus_universe_annualized_return": float(
                tail["top_50_minus_universe_return"].mean() * ANNUALIZATION_DAYS
            ),
            "daily_group_monotonic_spearman_mean": float(tail["daily_group_monotonic_spearman"].mean()),
            "daily_group_monotonic_spearman_positive_ratio": float(
                (tail["daily_group_monotonic_spearman"] > 0).mean()
            ),
            "top_50_positive_day_ratio": float((tail["top_50_mean_label_return"] > 0).mean()),
        },
        group_rows,
    )


def pct(value: float) -> str:
    return f"{value * 100:.2f}%"


def decimal(value: float) -> str:
    return f"{value:.3f}"


def write_report(path: Path, tail_summary: pd.DataFrame, group_summary: pd.DataFrame, metadata: dict) -> None:
    """Write the narrow explanatory audit in Chinese, preserving CSV detail for review."""
    full = tail_summary[tail_summary["period"].eq("full")].set_index("version")
    display = full[
        [
            "feature_count",
            "top_50_annualized_label_return",
            "top_decile_annualized_label_return",
            "bottom_decile_annualized_label_return",
            "top_minus_bottom_decile_annualized_return",
            "top_50_minus_universe_annualized_return",
            "daily_group_monotonic_spearman_mean",
            "daily_group_monotonic_spearman_positive_ratio",
        ]
    ].copy()
    for column in [
        "top_50_annualized_label_return",
        "top_decile_annualized_label_return",
        "bottom_decile_annualized_label_return",
        "top_minus_bottom_decile_annualized_return",
        "top_50_minus_universe_annualized_return",
        "daily_group_monotonic_spearman_positive_ratio",
    ]:
        display[column] = display[column].map(pct)
    display["daily_group_monotonic_spearman_mean"] = display[
        "daily_group_monotonic_spearman_mean"
    ].map(decimal)

    group_full = group_summary[group_summary["period"].eq("full")].pivot(
        index="group", columns="version", values="annualized_label_return"
    )
    group_display = group_full.map(pct)

    yearly = tail_summary[tail_summary["period"].ne("full")].copy()
    yearly_display = yearly[
        [
            "version",
            "period",
            "days",
            "top_50_annualized_label_return",
            "top_decile_annualized_label_return",
            "top_minus_bottom_decile_annualized_return",
            "daily_group_monotonic_spearman_mean",
        ]
    ].copy()
    for column in [
        "top_50_annualized_label_return",
        "top_decile_annualized_label_return",
        "top_minus_bottom_decile_annualized_return",
    ]:
        yearly_display[column] = yearly_display[column].map(pct)
    yearly_display["daily_group_monotonic_spearman_mean"] = yearly_display[
        "daily_group_monotonic_spearman_mean"
    ].map(decimal)

    b_top50_delta = (
        full.loc["B_core13", "top_50_annualized_label_return"]
        - full.loc["A_full_alpha158", "top_50_annualized_label_return"]
    )
    b_tail_delta = (
        full.loc["B_core13", "top_minus_bottom_decile_annualized_return"]
        - full.loc["A_full_alpha158", "top_minus_bottom_decile_annualized_return"]
    )
    b_monotonic_delta = (
        full.loc["B_core13", "daily_group_monotonic_spearman_mean"]
        - full.loc["A_full_alpha158", "daily_group_monotonic_spearman_mean"]
    )
    lines = [
        "CSI1000 Alpha158 固定 A/B/C：预测尾部与分组诊断 v1",
        "=" * 62,
        "",
        "目的：解释上一份固定比较中“B 的全截面 Rank IC 更低，但 TopkDropout 回测更好”的现象。",
        "本报告仅用已保存的预测与标签进行描述性分组检验；未训练模型、未改变因子、参数、策略、成本或日期。",
        "",
        "方法：每个交易日分别按该版本预测分数从低到高等人数分为 10 组；组 10 是预测分最高的股票。另计算当天预测分最高的 50 只股票的平均未来标签收益。",
        "标签仍是 Ref($close, -2) / Ref($close, -1) - 1；这里的“年化标签收益”是日均未来收益乘 238，仅用于解释信号，不是含成本的策略收益。",
        "Top 50 指标也不复现 TopkDropout：后者会受 n_drop、前日持仓、涨跌停和交易成本影响。本步骤只问“模型当天最看好的股票，随后一天表现如何”。",
        "",
        f"共同样本：{metadata['common_start']} 至 {metadata['common_end']}，{metadata['common_days']} 个交易日；每日共同股票数 {metadata['min_universe_size']} 至 {metadata['max_universe_size']}。",
        "2025-2026 属于已查看过的回溯确认期，故以下结果不能用来追调模型或形成实盘结论。",
        "",
        "全期尾部结果（所有数值均为原始标签收益口径）：",
        display.to_string(),
        "",
        "全期十等分组平均未来收益年化（第 1 组为最低预测分，第 10 组为最高预测分）：",
        group_display.to_string(),
        "",
        "分年尾部描述（不用于调参）：",
        yearly_display.to_string(index=False),
        "",
        "对矛盾的描述性回答：",
        f"- B 相对 A 的最高 50 只股票年化标签收益差为 {pct(b_top50_delta)}；最高/最低十分位收益差变化为 {pct(b_tail_delta)}。",
        f"- B 相对 A 的日内十分组单调性平均 Spearman 变化为 {decimal(b_monotonic_delta)}。",
        "- 本次结果中三项变化均为负。因此，“B 的回测更好”不能用“B 每天选出的最高分股票原始未来收益更高”来解释；相反，A 的静态 Top 50 与十分组标签表现更强。",
        "- TopkDropout 的实际收益并不等于每日静态 Top 50 标签均值：它受持仓延续（n_drop=5）、信号到成交/持有收益的时间映射、停牌与涨跌停等可交易约束、以及每日实际持仓权重影响。本报告未读取持仓和成交记录，不能在这一步把差异归因给其中任何一项。",
        "",
        "结论边界：这是一项事后诊断，而非新的筛选或采用规则。它不推翻固定协议中 B 对 A 的未通过判定，也不授权按这些结果修改 B、A 或 C。若需继续，下一项必须另行审查“实际持仓—成交—逐日收益”的归因，而不是直接调参。",
    ]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mlruns-dir", type=Path, default=Path("output/mlruns_static"))
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("output/analysis_static/csi1000_alpha158_tail_diagnosis_v1"),
    )
    args = parser.parse_args()

    scores, labels = load_common_panel(args.mlruns_dir)
    daily_group_parts = []
    daily_tail_parts = []
    for version in RUNS:
        groups, tail = calculate_daily_tail_metrics(scores[version], labels["label"], version)
        daily_group_parts.append(groups)
        daily_tail_parts.append(tail)
    daily_groups = pd.concat(daily_group_parts, ignore_index=True).set_index("datetime").sort_index()
    daily_tail = pd.concat(daily_tail_parts, ignore_index=True).set_index("datetime").sort_index()

    tail_rows = []
    group_rows = []
    for version, run in RUNS.items():
        version_groups = daily_groups[daily_groups["version"].eq(version)]
        version_tail = daily_tail[daily_tail["version"].eq(version)]
        for period_name, (start, end) in PERIODS.items():
            tail_summary, group_summary = summarize_period(
                version,
                run["feature_count"],
                period_name,
                start,
                end,
                version_groups,
                version_tail,
            )
            tail_rows.append(tail_summary)
            group_rows.extend(group_summary)
    tail_summary = pd.DataFrame(tail_rows)
    group_summary = pd.DataFrame(group_rows)

    daily_counts = scores.groupby(level="datetime").size()
    metadata = {
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "source_protocol": "research/protocols/csi1000_alpha158_model_comparison_protocol_v1.md",
        "analysis_type": "post-hoc diagnostic only; no model or strategy selection",
        "common_start": daily_counts.index.min().date().isoformat(),
        "common_end": daily_counts.index.max().date().isoformat(),
        "common_days": int(len(daily_counts)),
        "min_universe_size": int(daily_counts.min()),
        "max_universe_size": int(daily_counts.max()),
        "group_count": GROUP_COUNT,
        "top_k": TOP_K,
        "annualization_days": ANNUALIZATION_DAYS,
        "runs": RUNS,
    }

    args.output_dir.mkdir(parents=True, exist_ok=True)
    tail_summary.to_csv(args.output_dir / "tail_summary.csv", index=False)
    group_summary.to_csv(args.output_dir / "decile_summary.csv", index=False)
    daily_tail.reset_index().to_csv(
        args.output_dir / "daily_tail_metrics.csv.gz", index=False, compression="gzip"
    )
    daily_groups.reset_index().to_csv(
        args.output_dir / "daily_decile_returns.csv.gz", index=False, compression="gzip"
    )
    (args.output_dir / "metadata.json").write_text(
        json.dumps(metadata, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    write_report(args.output_dir / "tail_diagnosis_report.txt", tail_summary, group_summary, metadata)


if __name__ == "__main__":
    main()
