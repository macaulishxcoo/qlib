#!/usr/bin/env python3
"""De-duplicate development-screen Alpha158 candidates without changing their classes."""

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


RAW_CORRELATION_THRESHOLD = 0.95
IC_SYNCHRONY_THRESHOLD = 0.90
CANONICAL_FAMILY_PREFIXES = ("SUM", "VSUM")


def alpha158_definitions() -> tuple[list[str], list[str]]:
    """Return the same raw Alpha158 formula and name ordering as the screen."""
    return Alpha158DL.get_feature_config(
        {
            "kbar": {},
            "price": {"windows": [0], "feature": ["OPEN", "HIGH", "LOW", "VWAP"]},
            "rolling": {},
        }
    )


def equivalent_group(factor: str) -> str | None:
    """Return an algebraic-equivalence family key for SUMP/SUMN/SUMD variants."""
    for prefix in CANONICAL_FAMILY_PREFIXES:
        for member in (f"{prefix}P", f"{prefix}N", f"{prefix}D"):
            if factor.startswith(member) and factor[len(member) :].isdigit():
                return f"{prefix}_change_balance_{factor[len(member):]}"
    return None


def canonical_member(members: list[str]) -> str:
    """Use the centred difference representation where it exists."""
    difference = sorted(member for member in members if "D" in member[:5])
    return difference[0] if difference else sorted(members)[0]


def collect_equivalent_groups(candidates: pd.DataFrame) -> dict[str, list[str]]:
    """Group only candidate formulas; eliminated factors cannot affect this step."""
    groups: dict[str, list[str]] = {}
    for factor in candidates["factor"]:
        group = equivalent_group(factor)
        if group is not None:
            groups.setdefault(group, []).append(factor)
    return {name: sorted(members) for name, members in groups.items() if len(members) > 1}


def daily_pair_correlations(frame: pd.DataFrame, candidates: list[str]) -> dict[tuple[str, str], list[float]]:
    """Calculate each pair's cross-sectional Spearman correlation date by date."""
    values: dict[tuple[str, str], list[float]] = {pair: [] for pair in combinations(sorted(candidates), 2)}
    for _, cross_section in frame.groupby(level="datetime", sort=True):
        correlation = cross_section[candidates].corr(method="spearman")
        for factor_a, factor_b in values:
            values[(factor_a, factor_b)].append(correlation.loc[factor_a, factor_b])
    return values


def noncanonical_equivalent_members(candidates: pd.DataFrame) -> set[str]:
    """Identify exact-equivalence backups before the near-duplicate calculation."""
    backups: set[str] = set()
    for members in collect_equivalent_groups(candidates).values():
        representative = canonical_member(members)
        backups.update(member for member in members if member != representative)
    return backups


def build_pair_table(
    frame: pd.DataFrame,
    daily_ic: pd.DataFrame,
    candidates: pd.DataFrame,
) -> pd.DataFrame:
    """Combine raw-value similarity and daily-IC synchrony for every valid pair."""
    tables = []
    exact_backups = noncanonical_equivalent_members(candidates)
    for classification in ("retain", "observe"):
        factors = sorted(
            candidates.loc[
                candidates["classification"].eq(classification)
                & ~candidates["factor"].isin(exact_backups),
                "factor",
            ].tolist()
        )
        if len(factors) < 2:
            continue
        pair_values = daily_pair_correlations(frame, factors)
        ic_wide = (
            daily_ic[daily_ic["factor"].isin(factors)]
            .pivot(index="datetime", columns="factor", values="rank_ic")
            .reindex(columns=factors)
        )
        rows = []
        for (factor_a, factor_b), correlations in pair_values.items():
            values = pd.Series(correlations, dtype="float64").dropna()
            ic_pair = ic_wide[[factor_a, factor_b]].dropna()
            ic_corr = ic_pair.iloc[:, 0].corr(ic_pair.iloc[:, 1], method="pearson")
            raw_median = values.abs().median() if not values.empty else np.nan
            raw_sign = values.median() if not values.empty else np.nan
            rows.append(
                {
                    "classification": classification,
                    "factor_a": factor_a,
                    "factor_b": factor_b,
                    "daily_cross_section_days": len(values),
                    "median_cross_section_spearman": raw_sign,
                    "median_abs_cross_section_spearman": raw_median,
                    "daily_rank_ic_days": len(ic_pair),
                    "daily_rank_ic_pearson": ic_corr,
                    "abs_daily_rank_ic_pearson": abs(ic_corr) if pd.notna(ic_corr) else np.nan,
                }
            )
        tables.append(pd.DataFrame(rows))
    if not tables:
        return pd.DataFrame(
            columns=[
                "classification",
                "factor_a",
                "factor_b",
                "daily_cross_section_days",
                "median_cross_section_spearman",
                "median_abs_cross_section_spearman",
                "daily_rank_ic_days",
                "daily_rank_ic_pearson",
                "abs_daily_rank_ic_pearson",
                "meets_raw_correlation_threshold",
                "meets_ic_synchrony_threshold",
                "is_high_repeat_pair",
            ]
        )
    pairs = pd.concat(tables, ignore_index=True)
    pairs["meets_raw_correlation_threshold"] = (
        pairs["median_abs_cross_section_spearman"] >= RAW_CORRELATION_THRESHOLD
    )
    pairs["meets_ic_synchrony_threshold"] = pairs["abs_daily_rank_ic_pearson"] >= IC_SYNCHRONY_THRESHOLD
    pairs["is_high_repeat_pair"] = (
        pairs["meets_raw_correlation_threshold"] & pairs["meets_ic_synchrony_threshold"]
    )
    return pairs.sort_values(["classification", "factor_a", "factor_b"]).reset_index(drop=True)


def build_decisions(candidates: pd.DataFrame, pairs: pd.DataFrame) -> pd.DataFrame:
    """Choose representatives deterministically without a transitive-correlation shortcut."""
    result = candidates.copy()
    result["equivalence_group"] = result["factor"].map(equivalent_group)
    result["deduplication_disposition"] = "core_candidate"
    result["representative_factor"] = result["factor"]
    result["reason"] = "No algebraic or threshold-qualified near duplicate found."

    equivalent_groups = collect_equivalent_groups(result)
    for group, members in equivalent_groups.items():
        representative = canonical_member(members)
        non_representatives = [member for member in members if member != representative]
        mask = result["factor"].isin(non_representatives)
        result.loc[mask, "deduplication_disposition"] = "mathematical_equivalent_backup"
        result.loc[mask, "representative_factor"] = representative
        result.loc[mask, "reason"] = f"Algebraic change-balance family {group}; canonical representation is {representative}."

    for classification in ("retain", "observe"):
        group = result[result["classification"].eq(classification)].copy()
        # Equivalent backups must not become representatives for other candidates.
        order = group.sort_values(["min_abs_rank_ic", "factor"], ascending=[False, True])
        selected_cores: list[str] = []
        high_repeat = pairs[
            pairs["classification"].eq(classification) & pairs["is_high_repeat_pair"]
        ]
        pair_lookup = {
            tuple(sorted((row.factor_a, row.factor_b))): row
            for row in high_repeat.itertuples(index=False)
        }
        for factor in order["factor"]:
            current = result.loc[result["factor"].eq(factor), "deduplication_disposition"].iloc[0]
            if current != "core_candidate":
                continue
            core_matches = []
            for representative in selected_cores:
                pair = pair_lookup.get(tuple(sorted((factor, representative))))
                if pair is not None:
                    core_matches.append((representative, pair))
            if not core_matches:
                selected_cores.append(factor)
                continue
            representative, pair = sorted(core_matches, key=lambda item: item[0])[0]
            mask = result["factor"].eq(factor)
            result.loc[mask, "deduplication_disposition"] = "redundant_backup"
            result.loc[mask, "representative_factor"] = representative
            result.loc[mask, "reason"] = (
                "Near duplicate of "
                f"{representative}: median abs cross-sectional Spearman={pair.median_abs_cross_section_spearman:.4f}, "
                f"abs daily Rank-IC Pearson={pair.abs_daily_rank_ic_pearson:.4f}."
            )

    return result.sort_values(["classification", "deduplication_disposition", "factor"]).reset_index(drop=True)


def write_report(path: Path, decisions: pd.DataFrame, pairs: pd.DataFrame, metadata: dict) -> None:
    """Write the concise human-review report; detailed values remain in CSV files."""
    counts = decisions.groupby(["classification", "deduplication_disposition"]).size().to_dict()
    high_repeat = pairs[pairs["is_high_repeat_pair"]]
    lines = [
        "CSI1000 Alpha158 开发集候选因子去重（2023-2024）",
        "=" * 58,
        "",
        "目的：从通过原始有效性筛选的候选中标记重复信息，避免同一量价信号在后续中性化中被重复计数。",
        "本步骤不改变原始 retain/observe 分类，不进行中性化、模型训练或回测。",
        "",
        "方法：",
        "- 先将同窗口 SUMP/SUMN/SUMD 和 VSUMP/VSUMN/VSUMD 标记为代数等价族，统一采用 SUMD/VSUMD 为代表。",
        "- 再在 retain 和 observe 内部分别做两项近重复检验：日截面 Spearman 绝对相关中位数 >= 0.95，且日 Rank IC 序列 Pearson 绝对相关 >= 0.90。",
        "- 只有两项同时达标，较弱候选才标为 redundant_backup；所有备份仍保留在审计文件中。",
        "",
        f"开发集日期：{metadata['score_start']} 至 {metadata['score_end']}，共 {metadata['score_days']} 个交易日。",
        f"输入候选：retain {metadata['input_counts'].get('retain', 0)} 个，observe {metadata['input_counts'].get('observe', 0)} 个。",
        f"输出：retain 核心 {counts.get(('retain', 'core_candidate'), 0)}，代数备份 {counts.get(('retain', 'mathematical_equivalent_backup'), 0)}，近重复备份 {counts.get(('retain', 'redundant_backup'), 0)}；"
        f"observe 核心 {counts.get(('observe', 'core_candidate'), 0)}，代数备份 {counts.get(('observe', 'mathematical_equivalent_backup'), 0)}，近重复备份 {counts.get(('observe', 'redundant_backup'), 0)}。",
        "",
        "核心候选（仍须中性化验证）：",
    ]
    for classification in ("retain", "observe"):
        factors = decisions.loc[
            decisions["classification"].eq(classification)
            & decisions["deduplication_disposition"].eq("core_candidate"),
            "factor",
        ].tolist()
        lines.append(f"- {classification} ({len(factors)}): {', '.join(factors)}")
    lines += ["", "高重复对（不含已知代数等价项）："]
    if high_repeat.empty:
        lines.append("- 无。")
    else:
        for row in high_repeat.itertuples(index=False):
            lines.append(
                f"- {row.classification}: {row.factor_a} / {row.factor_b}; "
                f"截面相关中位数绝对值 {row.median_abs_cross_section_spearman:.4f}，"
                f"IC 序列相关绝对值 {row.abs_daily_rank_ic_pearson:.4f}。"
            )
    lines += [
        "",
        "审查重点：核心候选不是最终因子。下一步只能对这些核心候选做行业和自由流通市值中性化，并检查残差 Rank IC 是否仍存活。",
    ]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--qlib-data-dir", type=Path, required=True)
    parser.add_argument("--screen-dir", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--score-start-date", default="2023-01-01")
    parser.add_argument("--score-end-date", default="2024-12-31")
    args = parser.parse_args()

    decisions_path = args.screen_dir / "factor_decisions.csv"
    daily_ic_path = args.screen_dir / "daily_rank_ic.csv.gz"
    screen_metadata_path = args.screen_dir / "methodology.json"
    candidates = pd.read_csv(decisions_path)
    candidates = candidates[candidates["classification"].isin(["retain", "observe"])].copy()
    daily_ic = pd.read_csv(daily_ic_path, parse_dates=["datetime"])
    daily_ic = daily_ic[daily_ic["factor"].isin(candidates["factor"])].copy()
    screen_metadata = json.loads(screen_metadata_path.read_text(encoding="utf-8"))
    warmup_start = screen_metadata["warmup_start"]

    fields, all_names = alpha158_definitions()
    field_by_name = dict(zip(all_names, fields))
    factor_names = sorted(candidates["factor"].tolist())
    if len(factor_names) != len(set(factor_names)) or not set(factor_names).issubset(field_by_name):
        raise RuntimeError("Candidate factors are not a unique subset of Alpha158")

    qlib.init(provider_uri=str(args.qlib_data_dir), region=REG_CN)
    raw = D.features(
        D.instruments("csi1000"),
        [field_by_name[name] for name in factor_names],
        start_time=warmup_start,
        end_time=args.score_end_date,
        freq="day",
    )
    raw.columns = factor_names
    raw = raw[raw.index.get_level_values("datetime") >= pd.Timestamp(args.score_start_date)].copy()
    pairs = build_pair_table(raw, daily_ic, candidates)
    decisions = build_decisions(candidates, pairs)

    args.output_dir.mkdir(parents=True, exist_ok=True)
    pairs.to_csv(args.output_dir / "candidate_pair_correlation.csv", index=False)
    decisions.to_csv(args.output_dir / "factor_deduplication.csv", index=False)
    metadata = {
        "purpose": "Development-set Alpha158 candidate de-duplication under CSI1000 validation protocol v2",
        "protocol": "research/protocols/csi1000_alpha158_validation_protocol_v2.md",
        "source_screen_dir": str(args.screen_dir),
        "market": "CSI1000 historical daily constituents",
        "score_start": args.score_start_date,
        "score_end": args.score_end_date,
        "warmup_start": warmup_start,
        "score_days": int(raw.index.get_level_values("datetime").nunique()),
        "input_counts": candidates["classification"].value_counts().to_dict(),
        "raw_correlation_threshold": RAW_CORRELATION_THRESHOLD,
        "ic_synchrony_threshold": IC_SYNCHRONY_THRESHOLD,
        "algebraic_families": ["SUMP/SUMN/SUMD", "VSUMP/VSUMN/VSUMD"],
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
    }
    (args.output_dir / "deduplication_methodology.json").write_text(
        json.dumps(metadata, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    write_report(args.output_dir / "deduplication_report.txt", decisions, pairs, metadata)

    counts = decisions.groupby(["classification", "deduplication_disposition"]).size().to_dict()
    print(
        "completed|"
        + "|".join(
            f"{classification}_{disposition}={counts.get((classification, disposition), 0)}"
            for classification in ("retain", "observe")
            for disposition in ("core_candidate", "mathematical_equivalent_backup", "redundant_backup")
        )
    )


if __name__ == "__main__":
    main()
