#!/usr/bin/env python3
"""Audit residual redundancy among CSI1000 Alpha158 neutralization survivors."""

import argparse
import json
from datetime import datetime, timezone
from itertools import combinations
from pathlib import Path

import numpy as np
import pandas as pd

import qlib
from qlib.config import REG_CN
from qlib.contrib.data.loader import Alpha158DL
from qlib.data import D


LABEL_FIELD = "Ref($close, -2)/Ref($close, -1) - 1"
RESIDUAL_CORRELATION_THRESHOLD = 0.80
IC_SYNCHRONY_THRESHOLD = 0.70
MIN_CROSS_SECTION_SIZE = 50


def qlib_to_tushare(symbol: str) -> str:
    """Convert Qlib's SH600000 notation to Tushare's 600000.SH notation."""
    return f"{symbol[2:]}.{symbol[:2]}"


def alpha158_fields() -> dict[str, str]:
    """Return raw Alpha158 expressions indexed by their canonical names."""
    fields, names = Alpha158DL.get_feature_config(
        {
            "kbar": {},
            "price": {"windows": [0], "feature": ["OPEN", "HIGH", "LOW", "VWAP"]},
            "rolling": {},
        }
    )
    return dict(zip(names, fields))


def load_auxiliary_data(data_dir: Path) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Load same-date free-float size and point-in-time industry records."""
    daily = pd.read_csv(
        data_dir / "daily_basic_csi1000.csv.gz",
        compression="gzip",
        usecols=["ts_code", "trade_date", "close", "free_share"],
        dtype={"ts_code": str, "trade_date": str},
    )
    daily["datetime"] = pd.to_datetime(daily["trade_date"], format="%Y%m%d")
    daily["log_free_float_mv"] = np.log(
        pd.to_numeric(daily["close"], errors="coerce")
        * pd.to_numeric(daily["free_share"], errors="coerce")
    )
    daily = daily.replace([np.inf, -np.inf], np.nan)
    if daily.duplicated(["ts_code", "datetime"]).any():
        raise ValueError("daily_basic contains duplicate stock-date records")

    industry = pd.read_csv(
        data_dir / "industry_member_history_csi1000.csv.gz",
        compression="gzip",
        usecols=["ts_code", "l1_code", "in_date", "out_date"],
        dtype=str,
    )
    industry["in_date"] = pd.to_datetime(industry["in_date"], format="%Y%m%d", errors="coerce")
    industry["out_date"] = pd.to_datetime(industry["out_date"], format="%Y%m%d", errors="coerce")
    if industry["in_date"].isna().any():
        raise ValueError("industry history contains an unparsable in_date")
    return daily, industry


def build_industry_by_day(industry: pd.DataFrame, dates: pd.Series) -> pd.DataFrame:
    """Return each stock's latest industry record that was effective that day."""
    records = []
    for date in dates.drop_duplicates().sort_values():
        active = industry[
            (industry["in_date"] <= date)
            & (industry["out_date"].isna() | (industry["out_date"] >= date))
        ].copy()
        active = active.sort_values(["ts_code", "in_date"]).drop_duplicates("ts_code", keep="last")
        active["datetime"] = date
        records.append(active[["ts_code", "datetime", "l1_code"]])
    return pd.concat(records, ignore_index=True)


def residualize_day(day_frame: pd.DataFrame, factors: list[str]) -> tuple[pd.DataFrame, int]:
    """Use one common complete-case universe so all pair correlations are comparable."""
    required = factors + ["label", "log_free_float_mv", "l1_code"]
    sample = day_frame[required].apply(lambda column: pd.to_numeric(column, errors="coerce") if column.name != "l1_code" else column)
    sample = sample.dropna().copy()
    if len(sample) < MIN_CROSS_SECTION_SIZE:
        return pd.DataFrame(columns=factors), len(sample)

    dummies = pd.get_dummies(sample["l1_code"], dtype=float)
    design = np.column_stack(
        [
            np.ones(len(sample)),
            sample["log_free_float_mv"].to_numpy(dtype=float),
            dummies.iloc[:, 1:].to_numpy(dtype=float),
        ]
    )
    values = sample[factors].to_numpy(dtype=float)
    coefficients, _, _, _ = np.linalg.lstsq(design, values, rcond=None)
    residuals = values - design @ coefficients
    return pd.DataFrame(residuals, columns=factors), len(sample)


def residual_pair_table(daily_correlations: list[pd.DataFrame], factors: list[str]) -> pd.DataFrame:
    """Summarize daily residual Spearman correlations for every direct factor pair."""
    records = []
    for pair in combinations(factors, 2):
        factor_a, factor_b = pair
        values = pd.Series(
            [correlation.loc[factor_a, factor_b] for correlation in daily_correlations],
            dtype="float64",
        ).dropna()
        records.append(
            {
                "factor_a": factor_a,
                "factor_b": factor_b,
                "daily_cross_section_days": len(values),
                "median_residual_cross_section_spearman": values.median(),
                "median_abs_residual_cross_section_spearman": values.abs().median(),
                "mean_residual_cross_section_spearman": values.mean(),
            }
        )
    return pd.DataFrame(records)


def add_ic_synchrony(pair_table: pd.DataFrame, daily_ic: pd.DataFrame, factors: list[str]) -> pd.DataFrame:
    """Add the separately required daily neutral-IC time-series correlation."""
    ic_wide = (
        daily_ic[daily_ic["factor"].isin(factors)]
        .pivot(index="datetime", columns="factor", values="neutral_rank_ic")
        .reindex(columns=factors)
    )
    rows = []
    for factor_a, factor_b in combinations(factors, 2):
        values = ic_wide[[factor_a, factor_b]].dropna()
        correlation = values.iloc[:, 0].corr(values.iloc[:, 1], method="pearson")
        rows.append(
            {
                "factor_a": factor_a,
                "factor_b": factor_b,
                "daily_neutral_rank_ic_days": len(values),
                "daily_neutral_rank_ic_pearson": correlation,
                "abs_daily_neutral_rank_ic_pearson": abs(correlation) if pd.notna(correlation) else np.nan,
            }
        )
    result = pair_table.merge(pd.DataFrame(rows), on=["factor_a", "factor_b"], validate="one_to_one")
    result["meets_residual_correlation_threshold"] = (
        result["median_abs_residual_cross_section_spearman"] >= RESIDUAL_CORRELATION_THRESHOLD
    )
    result["meets_ic_synchrony_threshold"] = (
        result["abs_daily_neutral_rank_ic_pearson"] >= IC_SYNCHRONY_THRESHOLD
    )
    result["is_redundant_edge"] = (
        result["meets_residual_correlation_threshold"] & result["meets_ic_synchrony_threshold"]
    )
    return result.sort_values(["factor_a", "factor_b"]).reset_index(drop=True)


def connected_components(edges: pd.DataFrame, factors: list[str]) -> list[list[str]]:
    """Build components only from direct edges that passed both thresholds."""
    neighbors = {factor: set() for factor in factors}
    for edge in edges.itertuples(index=False):
        neighbors[edge.factor_a].add(edge.factor_b)
        neighbors[edge.factor_b].add(edge.factor_a)
    components = []
    visited = set()
    for factor in factors:
        if factor in visited:
            continue
        stack = [factor]
        component = []
        while stack:
            current = stack.pop()
            if current in visited:
                continue
            visited.add(current)
            component.append(current)
            stack.extend(neighbors[current] - visited)
        components.append(sorted(component))
    return components


def select_representatives(decisions: pd.DataFrame, edges: pd.DataFrame) -> pd.DataFrame:
    """Keep the strongest factor per direct-edge component, preserving every audit row."""
    result = decisions[[
        "factor",
        "min_abs_neutral_rank_ic",
        "neutral_rank_ic_2024",
    ]].copy()
    factors = result["factor"].tolist()
    result["final_status"] = "final_core_candidate"
    result["representative_factor"] = result["factor"]
    result["selection_reason"] = "no_threshold_qualified_residual_redundancy_edge"
    components = connected_components(edges, factors)
    for component in components:
        if len(component) == 1:
            continue
        group = result[result["factor"].isin(component)].copy()
        group["abs_neutral_rank_ic_2024"] = group["neutral_rank_ic_2024"].abs()
        winner = group.sort_values(
            ["min_abs_neutral_rank_ic", "abs_neutral_rank_ic_2024", "factor"],
            ascending=[False, False, True],
        ).iloc[0]["factor"]
        losers = [factor for factor in component if factor != winner]
        result.loc[result["factor"].eq(winner), "selection_reason"] = "representative_of_redundancy_component"
        result.loc[result["factor"].isin(losers), "final_status"] = "redundant_backup"
        result.loc[result["factor"].isin(losers), "representative_factor"] = winner
        result.loc[result["factor"].isin(losers), "selection_reason"] = f"redundant_with_{winner}"
    return result.sort_values(["final_status", "min_abs_neutral_rank_ic", "factor"], ascending=[True, False, True]).reset_index(drop=True)


def write_report(path: Path, selected: pd.DataFrame, pairs: pd.DataFrame, metadata: dict) -> None:
    """Write the concise review report; pair-level statistics remain in CSV."""
    strong_edges = pairs[pairs["is_redundant_edge"]]
    core = selected[selected["final_status"].eq("final_core_candidate")]
    backup = selected[selected["final_status"].eq("redundant_backup")]
    lines = [
        "CSI1000 Alpha158 中性化核心因子：最终残差冗余审查（2023-2024）",
        "=" * 66,
        "",
        "目的：确认通过行业/自由流通市值中性化的因子之间，是否仍在重复描述同一截面信息。",
        "本步骤只按预先冻结的双重统计门槛标记冗余；不按因子主题、名称或模型重要性删除。",
        "",
        "方法：每天在同一批同时具备 18 个因子、标签、行业和市值的股票上，先回归掉行业与市值，再计算任意残差因子对的截面 Spearman 相关。",
        f"一对因子仅在残差截面相关绝对值中位数 >= {RESIDUAL_CORRELATION_THRESHOLD:.2f}，且逐日中性化 Rank IC 序列相关绝对值 >= {IC_SYNCHRONY_THRESHOLD:.2f} 时视为冗余。",
        f"有效日期：{metadata['first_date']} 至 {metadata['last_date']}，共 {metadata['trading_days']} 日；共同样本量 {metadata['sample_count_min']} 至 {metadata['sample_count_max']}，中位数 {metadata['sample_count_median']}。",
        "",
        f"输入 {metadata['input_factor_count']} 个中性化核心因子；输出最终核心 {len(core)} 个、冗余备份 {len(backup)} 个、双门槛冗余边 {len(strong_edges)} 条。",
        "",
        "最终核心特征（后续固定版本 B 的唯一输入；尚未训练）：",
        "- " + ", ".join(core["factor"].tolist()),
        "",
        "冗余备份：",
    ]
    if backup.empty:
        lines.append("- 无。")
    else:
        for row in backup.itertuples(index=False):
            lines.append(f"- {row.factor} -> {row.representative_factor}")
    lines += ["", "满足双门槛的直接冗余边："]
    if strong_edges.empty:
        lines.append("- 无。")
    else:
        for edge in strong_edges.itertuples(index=False):
            lines.append(
                f"- {edge.factor_a} / {edge.factor_b}: 残差截面相关中位数绝对值 "
                f"{edge.median_abs_residual_cross_section_spearman:.4f}，"
                f"IC 序列相关绝对值 {edge.abs_daily_neutral_rank_ic_pearson:.4f}。"
            )
    lines += ["", "最终判定："]
    lines.append(
        selected[
            [
                "factor",
                "min_abs_neutral_rank_ic",
                "neutral_rank_ic_2024",
                "final_status",
                "representative_factor",
                "selection_reason",
            ]
        ].to_string(index=False, float_format=lambda value: f"{value:.4f}")
    )
    lines += [
        "",
        "下一步尚未执行：只有在审查本清单后，才定义相同训练和策略设置下的 A/B/C 比较实验。",
    ]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--qlib-data-dir", type=Path, required=True)
    parser.add_argument("--auxiliary-data-dir", type=Path, required=True)
    parser.add_argument("--neutralization-dir", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--score-start-date", default="2023-01-01")
    parser.add_argument("--score-end-date", default="2024-12-31")
    args = parser.parse_args()

    decision_data = pd.read_csv(args.neutralization_dir / "neutral_factor_decisions.csv")
    retained = decision_data[decision_data["neutralization_status"].eq("retain_survives")].copy()
    retained = retained.sort_values("factor").reset_index(drop=True)
    factors = retained["factor"].tolist()
    if not factors:
        raise SystemExit("No retain_survives factors in neutral_factor_decisions.csv")
    daily_ic = pd.read_csv(
        args.neutralization_dir / "neutralization_daily_rank_ic.csv.gz",
        compression="gzip",
        parse_dates=["datetime"],
    )
    daily_ic = daily_ic[daily_ic["factor"].isin(factors)].dropna(subset=["neutral_rank_ic"])
    source_metadata = json.loads(
        (args.neutralization_dir / "neutralization_methodology.json").read_text(encoding="utf-8")
    )
    warmup_start = source_metadata["warmup_start"]

    field_by_name = alpha158_fields()
    missing = sorted(set(factors) - set(field_by_name))
    if missing:
        raise ValueError(f"Alpha158 expressions unavailable for: {missing}")
    qlib.init(provider_uri=str(args.qlib_data_dir), region=REG_CN)
    raw = D.features(
        D.instruments("csi1000"),
        [field_by_name[factor] for factor in factors] + [LABEL_FIELD],
        start_time=warmup_start,
        end_time=args.score_end_date,
        freq="day",
    )
    raw.columns = factors + ["label"]
    raw = raw[raw.index.get_level_values("datetime") >= pd.Timestamp(args.score_start_date)].copy()
    raw = raw.reset_index().rename(columns={"instrument": "qlib_symbol"})
    raw["datetime"] = pd.to_datetime(raw["datetime"])
    raw["ts_code"] = raw["qlib_symbol"].map(qlib_to_tushare)

    size_data, industry = load_auxiliary_data(args.auxiliary_data_dir)
    industry_by_day = build_industry_by_day(industry, raw["datetime"])
    frame = raw.merge(
        size_data[["ts_code", "datetime", "log_free_float_mv"]],
        on=["ts_code", "datetime"],
        how="left",
        validate="many_to_one",
    ).merge(
        industry_by_day,
        on=["ts_code", "datetime"],
        how="left",
        validate="many_to_one",
    )

    daily_correlations = []
    samples = []
    for date, day_frame in frame.groupby("datetime", sort=True):
        residuals, sample_count = residualize_day(day_frame, factors)
        if residuals.empty:
            continue
        daily_correlations.append(residuals.corr(method="spearman"))
        samples.append({"datetime": date, "sample_count": sample_count})
    if not daily_correlations:
        raise SystemExit("No valid common cross sections for residual redundancy audit")

    pairs = residual_pair_table(daily_correlations, factors)
    pairs = add_ic_synchrony(pairs, daily_ic, factors)
    selected = select_representatives(retained, pairs[pairs["is_redundant_edge"]])
    ic_wide = (
        daily_ic.pivot(index="datetime", columns="factor", values="neutral_rank_ic")
        .reindex(columns=factors)
    )
    samples = pd.DataFrame(samples)

    args.output_dir.mkdir(parents=True, exist_ok=True)
    pairs.to_csv(args.output_dir / "final_residual_factor_pair_correlation.csv", index=False)
    ic_wide.corr(method="pearson").to_csv(args.output_dir / "final_residual_daily_ic_correlation.csv")
    selected.to_csv(args.output_dir / "final_core_factor_selection.csv", index=False)
    metadata = {
        "purpose": "Final residual-redundancy audit of industry/free-float-size-neutral CSI1000 Alpha158 core factors",
        "protocol": "research/protocols/csi1000_alpha158_validation_protocol_v4.md",
        "market": "CSI1000 historical daily constituents",
        "label_expression": LABEL_FIELD,
        "score_start": args.score_start_date,
        "score_end": args.score_end_date,
        "warmup_start": warmup_start,
        "input_factor_count": len(factors),
        "input_factors": factors,
        "common_complete_case_rule": "Each date requires all input factors, label, same-date log free-float market value, and effective level-1 industry.",
        "first_date": str(samples["datetime"].min().date()),
        "last_date": str(samples["datetime"].max().date()),
        "trading_days": int(samples["datetime"].nunique()),
        "sample_count_min": int(samples["sample_count"].min()),
        "sample_count_median": int(samples["sample_count"].median()),
        "sample_count_max": int(samples["sample_count"].max()),
        "residual_correlation_threshold": RESIDUAL_CORRELATION_THRESHOLD,
        "ic_synchrony_threshold": IC_SYNCHRONY_THRESHOLD,
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
    }
    (args.output_dir / "final_core_selection_methodology.json").write_text(
        json.dumps(metadata, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    write_report(args.output_dir / "final_core_selection_report.txt", selected, pairs, metadata)
    counts = selected["final_status"].value_counts().to_dict()
    print(
        "completed|"
        + "|".join(
            f"{key}={counts.get(key, 0)}" for key in ["final_core_candidate", "redundant_backup"]
        )
    )


if __name__ == "__main__":
    main()
