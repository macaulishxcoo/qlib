#!/usr/bin/env python3
"""Summarize the frozen CSI1000 Alpha158 A/B/C comparison without retuning."""

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

from qlib.contrib.evaluate import risk_analysis


COMPARISON_START = pd.Timestamp("2025-01-01")
COMPARISON_END = pd.Timestamp("2026-07-21")
ANNUALIZATION_FREQ = "day"

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
    """Return the formal artifact directory and fail clearly if it is incomplete."""
    path = mlruns_dir / run["experiment_id"] / run["run_id"] / "artifacts"
    required = [
        path / "pred.pkl",
        path / "label.pkl",
        path / "portfolio_analysis" / "report_normal_1day.pkl",
    ]
    missing = [str(item) for item in required if not item.is_file()]
    if missing:
        raise FileNotFoundError(f"Missing formal run artifact(s): {missing}")
    return path


def daily_rank_ic(prediction: pd.DataFrame, label: pd.DataFrame) -> pd.Series:
    """Recompute daily Spearman IC from saved scores and labels on their common rows."""
    joined = prediction.iloc[:, [0]].join(label.iloc[:, [0]], how="inner")
    joined.columns = ["score", "label"]
    records = []
    for date, cross_section in joined.groupby(level="datetime", sort=True):
        sample = cross_section.dropna()
        if len(sample) < 2 or sample["score"].nunique() < 2 or sample["label"].nunique() < 2:
            value = np.nan
        else:
            value = sample["score"].corr(sample["label"], method="spearman")
        records.append((date, value))
    return pd.Series(dict(records), name="rank_ic").sort_index()


def metric_row(
    version: str,
    feature_count: int,
    period_name: str,
    period_start: pd.Timestamp,
    period_end: pd.Timestamp,
    rank_ic: pd.Series,
    report: pd.DataFrame,
) -> dict:
    """Apply Qlib's existing arithmetic risk metric to one fixed calendar slice."""
    ic_slice = rank_ic.loc[period_start:period_end].dropna()
    report_slice = report.loc[period_start:period_end].copy()
    if ic_slice.empty or report_slice.empty:
        raise ValueError(f"{version} has no common data for {period_name}")

    excess_after_cost = report_slice["return"] - report_slice["bench"] - report_slice["cost"]
    risk = risk_analysis(excess_after_cost, freq=ANNUALIZATION_FREQ)["risk"]

    # The cumulative columns are account-currency values; differencing preserves a subperiod's own trades.
    daily_turnover_amount = report["total_turnover"].diff().fillna(report["total_turnover"])
    daily_cost_amount = report["total_cost"].diff().fillna(report["total_cost"])
    return {
        "version": version,
        "feature_count": feature_count,
        "period": period_name,
        "period_start": ic_slice.index.min().date().isoformat(),
        "period_end": ic_slice.index.max().date().isoformat(),
        "rank_ic_days": int(len(ic_slice)),
        "rank_ic": float(ic_slice.mean()),
        "rank_icir": float(ic_slice.mean() / ic_slice.std(ddof=1)),
        "fee_after_excess_annualized_return": float(risk["annualized_return"]),
        "fee_after_excess_information_ratio": float(risk["information_ratio"]),
        "fee_after_excess_max_drawdown": float(risk["max_drawdown"]),
        "cumulative_turnover_rate": float(report_slice["turnover"].sum()),
        "average_daily_turnover_rate": float(report_slice["turnover"].mean()),
        "cost_drag_rate_sum": float(report_slice["cost"].sum()),
        "average_daily_cost_rate": float(report_slice["cost"].mean()),
        "total_turnover_currency": float(daily_turnover_amount.loc[period_start:period_end].sum()),
        "total_cost_currency": float(daily_cost_amount.loc[period_start:period_end].sum()),
    }


def candidate_rule(left: pd.Series, right: pd.Series) -> dict:
    """Evaluate the pre-declared rule: left is the candidate, right is its baseline."""
    rank_ic_change = left["rank_ic"] - right["rank_ic"]
    annual_return_change = (
        left["fee_after_excess_annualized_return"] - right["fee_after_excess_annualized_return"]
    )
    information_ratio_change = (
        left["fee_after_excess_information_ratio"] - right["fee_after_excess_information_ratio"]
    )
    drawdown_deterioration = abs(left["fee_after_excess_max_drawdown"]) - abs(
        right["fee_after_excess_max_drawdown"]
    )
    passed = (
        rank_ic_change >= 0
        and annual_return_change >= 0
        and information_ratio_change >= 0
        and drawdown_deterioration <= 0.05
    )
    return {
        "candidate": left.name,
        "baseline": right.name,
        "rank_ic_change": float(rank_ic_change),
        "fee_after_excess_annualized_return_change": float(annual_return_change),
        "fee_after_excess_information_ratio_change": float(information_ratio_change),
        "max_drawdown_deterioration": float(drawdown_deterioration),
        "passes_predeclared_rule": bool(passed),
    }


def percentage(value: float) -> str:
    return f"{value * 100:.2f}%"


def number(value: float) -> str:
    return f"{value:.3f}"


def write_report(path: Path, metrics: pd.DataFrame, decisions: pd.DataFrame, metadata: dict) -> None:
    """Write a reviewable Chinese report; machine-readable values remain in CSV files."""
    full = metrics[metrics["period"].eq("full")].set_index("version")
    display = full[
        [
            "feature_count",
            "rank_ic",
            "rank_icir",
            "fee_after_excess_annualized_return",
            "fee_after_excess_information_ratio",
            "fee_after_excess_max_drawdown",
            "cumulative_turnover_rate",
            "cost_drag_rate_sum",
        ]
    ].copy()
    for column in [
        "rank_ic",
        "fee_after_excess_annualized_return",
        "fee_after_excess_max_drawdown",
        "cumulative_turnover_rate",
        "cost_drag_rate_sum",
    ]:
        display[column] = display[column].map(percentage)
    for column in ["rank_icir", "fee_after_excess_information_ratio"]:
        display[column] = display[column].map(number)

    yearly = metrics[metrics["period"].ne("full")].copy()
    yearly_display = yearly[
        [
            "version",
            "period",
            "rank_ic_days",
            "rank_ic",
            "rank_icir",
            "fee_after_excess_annualized_return",
            "fee_after_excess_information_ratio",
            "fee_after_excess_max_drawdown",
        ]
    ].copy()
    for column in ["rank_ic", "fee_after_excess_annualized_return", "fee_after_excess_max_drawdown"]:
        yearly_display[column] = yearly_display[column].map(percentage)
    for column in ["rank_icir", "fee_after_excess_information_ratio"]:
        yearly_display[column] = yearly_display[column].map(number)

    b_vs_a = decisions[
        (decisions["candidate"].eq("B_core13")) & (decisions["baseline"].eq("A_full_alpha158"))
    ].iloc[0]
    c_vs_a = decisions[
        (decisions["candidate"].eq("C_core13_observe39")) & (decisions["baseline"].eq("A_full_alpha158"))
    ].iloc[0]
    c_vs_b = decisions[
        (decisions["candidate"].eq("C_core13_observe39")) & (decisions["baseline"].eq("B_core13"))
    ].iloc[0]

    b_conclusion = "通过" if b_vs_a["passes_predeclared_rule"] else "未通过"
    c_conclusion = "通过" if (c_vs_a["passes_predeclared_rule"] and c_vs_b["passes_predeclared_rule"]) else "未通过"
    lines = [
        "CSI1000 Alpha158 固定 A/B/C 模型比较 v1：回溯确认汇总",
        "=" * 66,
        "",
        "本报告只读取三次已完成的固定运行产物并重新计算指标；未训练模型、未改因子、未改参数或策略。",
        "目的：检验开发期筛出的 13 个核心因子（B）是否相对全量 Alpha158（A）构成候选改善；C 仅诊断 39 个观察因子是否有增量。",
        "",
        "信息边界：2023-2024 用于因子开发；本报告的 2025-2026 是已被查看过的回溯确认，不能作为严格样本外或实盘证据。",
        "因此，任何版本均不得因本报告而再调整因子、模型、策略、成本或日期。严格前瞻观察从 2026-07-24 后开始。",
        "",
        f"共同有效标签期：{metadata['common_start']} 至 {metadata['common_end']}，共 {metadata['common_label_days']} 个交易日。",
        "2026-07-22、2026-07-23 有预测/回测记录但没有对应标签，已从全部比较指标中剔除。",
        "",
        "全期结果（费用后超额；Qlib 算术累计口径，日频年化系数 238）：",
        display.to_string(),
        "",
        "分年切片（仅稳定性描述，不用于调参）：",
        yearly_display.to_string(index=False),
        "",
        "预先冻结的判定：候选版本需相对基准同时满足 Rank IC、费用后年化超额、费用后 IR 均不下降，且最大超额回撤恶化不超过 5 个百分点。",
        f"- B 对 A：{b_conclusion}。Rank IC 变化 {percentage(b_vs_a['rank_ic_change'])}；费用后年化超额变化 {percentage(b_vs_a['fee_after_excess_annualized_return_change'])}；IR 变化 {number(b_vs_a['fee_after_excess_information_ratio_change'])}；回撤恶化 {percentage(b_vs_a['max_drawdown_deterioration'])}。",
        f"- C 对 A：{'通过' if c_vs_a['passes_predeclared_rule'] else '未通过'}；C 对 B：{'通过' if c_vs_b['passes_predeclared_rule'] else '未通过'}；故 C 的诊断性采用条件 {c_conclusion}。",
        "",
        "解释边界：若 B 通过，它仅是一个“候选改善版本”，说明在这一次冻结的回溯比较中，筛选后的输入与固定策略的组合优于基线；这不证明未来持续有效，也不等同于可实盘交易。",
        "下一步需要用户审查此报告后再单独决定；本步骤不授权下一项实验。",
        "",
        "字段说明：累计换手率为 report_normal_1day.pkl 中 daily turnover 之和；成本拖累为 daily cost 之和；货币换手/成本在 comparison_metrics.csv 中以 total_turnover/total_cost 的逐日增量汇总，方便审计。",
    ]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mlruns-dir", type=Path, default=Path("output/mlruns_static"))
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("output/analysis_static/csi1000_alpha158_model_comparison_v1"),
    )
    args = parser.parse_args()

    results = {}
    rank_ics = {}
    label_dates_by_version = {}
    report_dates_by_version = {}
    for version, run in RUNS.items():
        artifacts = artifact_dir(args.mlruns_dir, run)
        prediction = pd.read_pickle(artifacts / "pred.pkl")
        label = pd.read_pickle(artifacts / "label.pkl")
        report = pd.read_pickle(artifacts / "portfolio_analysis" / "report_normal_1day.pkl")
        rank_ic = daily_rank_ic(prediction, label)
        label_dates_by_version[version] = set(rank_ic.dropna().index)
        report_dates_by_version[version] = set(report.index)
        results[version] = report
        rank_ics[version] = rank_ic

    common_dates = set.intersection(*label_dates_by_version.values())
    common_dates &= set.intersection(*report_dates_by_version.values())
    common_dates = sorted(
        date for date in common_dates if COMPARISON_START <= date <= COMPARISON_END
    )
    if not common_dates:
        raise RuntimeError("No common labelled report dates in the frozen comparison window")
    common_index = pd.DatetimeIndex(common_dates, name="datetime")

    metric_rows = []
    daily_ic_rows = []
    for version, run in RUNS.items():
        rank_ic = rank_ics[version].reindex(common_index)
        report = results[version].reindex(common_index)
        if rank_ic.isna().any() or report.isna().all(axis=None):
            raise RuntimeError(f"{version} is missing data on the common comparison dates")
        for period_name, (period_start, period_end) in PERIODS.items():
            metric_rows.append(
                metric_row(
                    version,
                    run["feature_count"],
                    period_name,
                    period_start,
                    period_end,
                    rank_ic,
                    report,
                )
            )
        daily_ic_rows.append(pd.DataFrame({"datetime": common_index, "version": version, "rank_ic": rank_ic.to_numpy()}))

    metrics = pd.DataFrame(metric_rows)
    full_metrics = metrics[metrics["period"].eq("full")].set_index("version")
    decisions = pd.DataFrame(
        [
            candidate_rule(full_metrics.loc["B_core13"], full_metrics.loc["A_full_alpha158"]),
            candidate_rule(full_metrics.loc["C_core13_observe39"], full_metrics.loc["A_full_alpha158"]),
            candidate_rule(full_metrics.loc["C_core13_observe39"], full_metrics.loc["B_core13"]),
        ]
    )

    args.output_dir.mkdir(parents=True, exist_ok=True)
    metrics.to_csv(args.output_dir / "comparison_metrics.csv", index=False)
    decisions.to_csv(args.output_dir / "predeclared_decisions.csv", index=False)
    pd.concat(daily_ic_rows, ignore_index=True).to_csv(
        args.output_dir / "daily_rank_ic_common_period.csv.gz", index=False, compression="gzip"
    )
    metadata = {
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "protocol": "research/protocols/csi1000_alpha158_model_comparison_protocol_v1.md",
        "technical_correction": "research/protocols/csi1000_alpha158_model_comparison_protocol_v1_1.md",
        "comparison_window_requested": [COMPARISON_START.date().isoformat(), COMPARISON_END.date().isoformat()],
        "common_start": common_index.min().date().isoformat(),
        "common_end": common_index.max().date().isoformat(),
        "common_label_days": int(len(common_index)),
        "annualization": "qlib.contrib.evaluate.risk_analysis(freq='day'); arithmetic accumulation; 238 days",
        "runs": RUNS,
    }
    (args.output_dir / "metadata.json").write_text(
        json.dumps(metadata, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    write_report(args.output_dir / "comparison_report.txt", metrics, decisions, metadata)


if __name__ == "__main__":
    main()
