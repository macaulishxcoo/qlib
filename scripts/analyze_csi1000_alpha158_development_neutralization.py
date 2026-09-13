#!/usr/bin/env python3
"""Neutralize de-duplicated CSI1000 Alpha158 candidates on the 2023-2024 development set."""

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

import qlib
from qlib.config import REG_CN
from qlib.contrib.data.loader import Alpha158DL
from qlib.data import D


LABEL_FIELD = "Ref($close, -2)/Ref($close, -1) - 1"
RETAIN_THRESHOLD = 0.02
OBSERVE_THRESHOLD = 0.01
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
    """Load point-in-time daily free-float size and historical industry records."""
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


def build_industry_by_day(industry: pd.DataFrame, trading_days: pd.Series) -> pd.DataFrame:
    """Select the Shenwan level-1 assignment effective on each requested date."""
    records = []
    for date in trading_days.drop_duplicates().sort_values():
        active = industry[
            (industry["in_date"] <= date)
            & (industry["out_date"].isna() | (industry["out_date"] >= date))
        ].copy()
        # Classification migrations can yield overlapping records; the latest record
        # available on the date is the point-in-time assignment.
        active = active.sort_values(["ts_code", "in_date"]).drop_duplicates("ts_code", keep="last")
        active["datetime"] = date
        records.append(active[["ts_code", "datetime", "l1_code"]])
    if not records:
        return pd.DataFrame(columns=["ts_code", "datetime", "l1_code"])
    return pd.concat(records, ignore_index=True)


def spearman_ic(values: np.ndarray, label: np.ndarray) -> float:
    """Return a safe Spearman Rank IC for one complete daily cross section."""
    if len(values) < MIN_CROSS_SECTION_SIZE:
        return np.nan
    value_series = pd.Series(values)
    label_series = pd.Series(label)
    if value_series.nunique() < 2 or label_series.nunique() < 2:
        return np.nan
    return value_series.corr(label_series, method="spearman")


def neutralize_day(day_frame: pd.DataFrame, factors: list[str]) -> list[dict]:
    """Residualize all factors, grouping identical missing-value masks for speed."""
    base = day_frame[["label", "log_free_float_mv", "l1_code"]].dropna().copy()
    date = day_frame["datetime"].iloc[0]
    if len(base) < MIN_CROSS_SECTION_SIZE:
        return [
            {
                "datetime": date,
                "factor": factor,
                "raw_rank_ic": np.nan,
                "neutral_rank_ic": np.nan,
                "sample_count": len(base),
                "industry_count": 0,
                "regressor_count": 0,
            }
            for factor in factors
        ]

    factor_values = day_frame.loc[base.index, factors].apply(pd.to_numeric, errors="coerce").to_numpy(dtype=float)
    labels = base["label"].to_numpy(dtype=float)
    industries = base["l1_code"]
    dummies = pd.get_dummies(industries, dtype=float)
    design = np.column_stack(
        [
            np.ones(len(base)),
            base["log_free_float_mv"].to_numpy(dtype=float),
            dummies.iloc[:, 1:].to_numpy(dtype=float),
        ]
    )
    valid = np.isfinite(factor_values)
    groups: dict[bytes, list[int]] = {}
    for factor_index in range(len(factors)):
        groups.setdefault(valid[:, factor_index].tobytes(), []).append(factor_index)

    results: dict[int, dict] = {}
    for mask_bytes, factor_indices in groups.items():
        mask = np.frombuffer(mask_bytes, dtype=np.bool_)
        sample_count = int(mask.sum())
        if sample_count < MIN_CROSS_SECTION_SIZE:
            for factor_index in factor_indices:
                results[factor_index] = {
                    "datetime": date,
                    "factor": factors[factor_index],
                    "raw_rank_ic": np.nan,
                    "neutral_rank_ic": np.nan,
                    "sample_count": sample_count,
                    "industry_count": int(industries[mask].nunique()),
                    "regressor_count": design.shape[1],
                }
            continue

        design_subset = design[mask]
        value_subset = factor_values[mask][:, factor_indices]
        coefficients, _, _, _ = np.linalg.lstsq(design_subset, value_subset, rcond=None)
        residuals = value_subset - design_subset @ coefficients
        label_subset = labels[mask]
        for local_index, factor_index in enumerate(factor_indices):
            values = value_subset[:, local_index]
            residual = residuals[:, local_index]
            results[factor_index] = {
                "datetime": date,
                "factor": factors[factor_index],
                "raw_rank_ic": spearman_ic(values, label_subset),
                "neutral_rank_ic": spearman_ic(residual, label_subset),
                "sample_count": sample_count,
                "industry_count": int(industries[mask].nunique()),
                "regressor_count": design_subset.shape[1],
            }
    return [results[index] for index in range(len(factors))]


def summarize_year(daily_ic: pd.DataFrame, year: int, factors: list[str]) -> pd.DataFrame:
    """Aggregate raw and neutral Rank IC separately for each development year."""
    rows = []
    period = daily_ic[daily_ic["datetime"].dt.year.eq(year)]
    for factor in factors:
        group = period[period["factor"].eq(factor)]
        valid = group.dropna(subset=["raw_rank_ic", "neutral_rank_ic"])
        raw = valid["raw_rank_ic"]
        neutral = valid["neutral_rank_ic"]
        rows.append(
            {
                "factor": factor,
                "days": int(len(valid)),
                "raw_rank_ic": raw.mean(),
                "raw_rank_icir": raw.mean() / raw.std(ddof=1),
                "neutral_rank_ic": neutral.mean(),
                "neutral_rank_icir": neutral.mean() / neutral.std(ddof=1),
                "raw_positive_ratio": (raw > 0).mean(),
                "neutral_positive_ratio": (neutral > 0).mean(),
                "sample_count_median": int(valid["sample_count"].median()),
                "sample_count_min": int(valid["sample_count"].min()),
                "sample_count_max": int(valid["sample_count"].max()),
                "industry_count_median": int(valid["industry_count"].median()),
            }
        )
    return pd.DataFrame(rows)


def classify_candidates(
    candidate_data: pd.DataFrame,
    summary_2023: pd.DataFrame,
    summary_2024: pd.DataFrame,
) -> pd.DataFrame:
    """Apply v3 thresholds while preserving the original raw-screen class ceiling."""
    result = candidate_data[["factor", "classification", "min_abs_rank_ic"]].rename(
        columns={"classification": "raw_screen_class", "min_abs_rank_ic": "raw_screen_min_abs_rank_ic"}
    )
    result = result.merge(summary_2023, on="factor", suffixes=("", "_2023"))
    result = result.rename(
        columns={column: f"{column}_2023" for column in summary_2023.columns if column != "factor"}
    )
    result = result.merge(summary_2024, on="factor", suffixes=("", "_2024"))
    result = result.rename(
        columns={column: f"{column}_2024" for column in summary_2024.columns if column != "factor"}
    )

    neutral_2023 = result["neutral_rank_ic_2023"]
    neutral_2024 = result["neutral_rank_ic_2024"]
    result["two_year_same_neutral_direction"] = (
        (np.sign(neutral_2023) == np.sign(neutral_2024)) & (np.sign(neutral_2023) != 0)
    )
    result["min_abs_neutral_rank_ic"] = pd.concat(
        [neutral_2023.abs(), neutral_2024.abs()], axis=1
    ).min(axis=1)
    retains = (
        result["raw_screen_class"].eq("retain")
        & result["two_year_same_neutral_direction"]
        & result["min_abs_neutral_rank_ic"].ge(RETAIN_THRESHOLD)
    )
    observes = (
        result["two_year_same_neutral_direction"]
        & result["min_abs_neutral_rank_ic"].ge(OBSERVE_THRESHOLD)
        & ~retains
    )
    result["neutralization_status"] = np.select(
        [retains, observes],
        ["retain_survives", "observe_survives"],
        default="eliminate_after_neutralization",
    )
    result["combined_exposure_assessment"] = np.select(
        [retains, observes],
        ["independent_signal_survives", "weaker_but_survives"],
        default="not_stable_after_combined_neutralization",
    )
    raw_mean_strength = (
        result["raw_rank_ic_2023"].abs() + result["raw_rank_ic_2024"].abs()
    ) / 2
    neutral_mean_strength = (
        result["neutral_rank_ic_2023"].abs() + result["neutral_rank_ic_2024"].abs()
    ) / 2
    result["neutral_to_raw_mean_abs_ic_ratio"] = neutral_mean_strength / raw_mean_strength.replace(0, np.nan)
    return result.sort_values(
        ["neutralization_status", "raw_screen_class", "min_abs_neutral_rank_ic", "factor"],
        ascending=[True, True, False, True],
    ).reset_index(drop=True)


def write_report(path: Path, decisions: pd.DataFrame, metadata: dict) -> None:
    """Write a Chinese review report alongside the complete machine-readable audit."""
    counts = decisions.groupby(["raw_screen_class", "neutralization_status"]).size().to_dict()
    core = decisions[decisions["neutralization_status"].eq("retain_survives")]
    observe = decisions[decisions["neutralization_status"].eq("observe_survives")]
    lines = [
        "CSI1000 Alpha158 开发集行业/自由流通市值中性化验证（2023-2024）",
        "=" * 64,
        "",
        "目的：确认候选因子的预测力不是仅由行业配置或自由流通市值偏好造成。",
        "方法：每个交易日、每个因子做截面 OLS：因子 = 截距 + log(自由流通股本 × 当日收盘价) + 申万一级行业哑变量 + 残差。",
        "比较原始因子与残差的 Rank IC 时，两者始终使用同一批同时具备因子、标签、行业和市值的股票，因此差异不是缺失样本造成。",
        "本步骤只使用冻结的 2023-2024 开发集；不训练模型、不回测、不使用 2025-2026 数据。",
        "",
        f"输入：去重后的核心候选 {metadata['candidate_count']} 个（原 retain {metadata['input_counts'].get('retain', 0)}，原 observe {metadata['input_counts'].get('observe', 0)}）。",
        f"有效标签日期：{metadata['first_date']} 至 {metadata['last_date']}，共 {metadata['trading_days']} 日。",
        f"因子日截面完整样本量：{metadata['sample_count_min']} 至 {metadata['sample_count_max']}，中位数 {metadata['sample_count_median']}；行业数中位数 {metadata['industry_count_median']}。",
        "",
        "预先冻结的判定：",
        "- retain_survives：原始类别为 retain；2023、2024 残差 Rank IC 同方向，且两年绝对值均 >= 0.02。",
        "- observe_survives：同方向且两年绝对值均 >= 0.01，但未达到上条；原始 observe 不因本步骤升级为 retain。",
        "- eliminate_after_neutralization：其他情况。中性化同时去除行业和市值，不能单独归因两者各自的影响。",
        "",
        "结果计数：",
        f"- 原 retain：保留 {counts.get(('retain', 'retain_survives'), 0)}，观察 {counts.get(('retain', 'observe_survives'), 0)}，淘汰 {counts.get(('retain', 'eliminate_after_neutralization'), 0)}。",
        f"- 原 observe：保留 0（按协议不允许升级），观察 {counts.get(('observe', 'observe_survives'), 0)}，淘汰 {counts.get(('observe', 'eliminate_after_neutralization'), 0)}。",
        "",
        "可作为下一阶段核心输入的 retain_survives：",
        "- " + (", ".join(core["factor"].tolist()) if not core.empty else "无"),
        "",
        "仍处于观察的 observe_survives（可在预定义版本 C 单独测试，不能与核心结论混同）：",
        "- " + (", ".join(observe["factor"].tolist()) if not observe.empty else "无"),
        "",
        "全部因子判定：",
    ]
    display = decisions[
        [
            "factor",
            "raw_screen_class",
            "raw_rank_ic_2023",
            "neutral_rank_ic_2023",
            "raw_rank_ic_2024",
            "neutral_rank_ic_2024",
            "min_abs_neutral_rank_ic",
            "neutral_to_raw_mean_abs_ic_ratio",
            "neutralization_status",
        ]
    ]
    lines.append(display.to_string(index=False, float_format=lambda value: f"{value:.4f}"))
    lines += [
        "",
        "下一步尚未执行：在完成审查后，才冻结 A/B/C 的特征集合和完全一致的模型比较配置。",
    ]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--qlib-data-dir", type=Path, required=True)
    parser.add_argument("--auxiliary-data-dir", type=Path, required=True)
    parser.add_argument("--deduplication-dir", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--score-start-date", default="2023-01-01")
    parser.add_argument("--score-end-date", default="2024-12-31")
    args = parser.parse_args()

    source = pd.read_csv(args.deduplication_dir / "factor_deduplication.csv")
    candidates = source[source["deduplication_disposition"].eq("core_candidate")].copy()
    candidates = candidates[candidates["classification"].isin(["retain", "observe"])].copy()
    candidates = candidates.sort_values("factor").reset_index(drop=True)
    factors = candidates["factor"].tolist()
    if not factors:
        raise SystemExit("No core candidates in factor_deduplication.csv")

    source_metadata = json.loads(
        (args.deduplication_dir / "deduplication_methodology.json").read_text(encoding="utf-8")
    )
    warmup_start = source_metadata["warmup_start"]
    fields_by_name = alpha158_fields()
    missing = sorted(set(factors) - set(fields_by_name))
    if missing:
        raise ValueError(f"Alpha158 expressions unavailable for: {missing}")

    qlib.init(provider_uri=str(args.qlib_data_dir), region=REG_CN)
    raw = D.features(
        D.instruments("csi1000"),
        [fields_by_name[factor] for factor in factors] + [LABEL_FIELD],
        start_time=warmup_start,
        end_time=args.score_end_date,
        freq="day",
    )
    raw.columns = factors + ["label"]
    raw = raw[raw.index.get_level_values("datetime") >= pd.Timestamp(args.score_start_date)].copy()
    raw = raw.reset_index().rename(columns={"instrument": "qlib_symbol"})
    raw["datetime"] = pd.to_datetime(raw["datetime"])
    raw["ts_code"] = raw["qlib_symbol"].map(qlib_to_tushare)

    daily_size, industry = load_auxiliary_data(args.auxiliary_data_dir)
    industry_by_day = build_industry_by_day(industry, raw["datetime"])
    frame = raw.merge(
        daily_size[["ts_code", "datetime", "log_free_float_mv"]],
        on=["ts_code", "datetime"],
        how="left",
        validate="many_to_one",
    ).merge(
        industry_by_day,
        on=["ts_code", "datetime"],
        how="left",
        validate="many_to_one",
    )

    daily_rows = []
    for _, day_frame in frame.groupby("datetime", sort=True):
        daily_rows.extend(neutralize_day(day_frame, factors))
    daily_ic = pd.DataFrame(daily_rows)
    valid_daily_ic = daily_ic.dropna(subset=["raw_rank_ic", "neutral_rank_ic"]).copy()
    if valid_daily_ic.empty:
        raise SystemExit("No valid neutralized daily Rank IC values")

    summary_2023 = summarize_year(valid_daily_ic, 2023, factors)
    summary_2024 = summarize_year(valid_daily_ic, 2024, factors)
    decisions = classify_candidates(candidates, summary_2023, summary_2024)

    args.output_dir.mkdir(parents=True, exist_ok=True)
    daily_ic.to_csv(args.output_dir / "neutralization_daily_rank_ic.csv.gz", index=False, compression="gzip")
    summary_2023.to_csv(args.output_dir / "neutralization_summary_2023.csv", index=False)
    summary_2024.to_csv(args.output_dir / "neutralization_summary_2024.csv", index=False)
    decisions.to_csv(args.output_dir / "neutral_factor_decisions.csv", index=False)

    metadata = {
        "purpose": "Development-set industry and free-float-size neutralization of de-duplicated CSI1000 Alpha158 candidates",
        "protocol": "research/protocols/csi1000_alpha158_validation_protocol_v3.md",
        "market": "CSI1000 historical daily constituents",
        "label_expression": LABEL_FIELD,
        "score_start": args.score_start_date,
        "score_end": args.score_end_date,
        "warmup_start": warmup_start,
        "candidate_count": len(factors),
        "input_counts": candidates["classification"].value_counts().to_dict(),
        "neutralization": "factor ~ intercept + log(free_share * close) + Shenwan level-1 industry dummies",
        "complete_case_rule": "For each factor-date, drop only stock-dates missing factor, label, same-date size, or effective industry; raw and residual Rank IC use the same complete-case sample.",
        "first_date": str(valid_daily_ic["datetime"].min().date()),
        "last_date": str(valid_daily_ic["datetime"].max().date()),
        "trading_days": int(valid_daily_ic["datetime"].nunique()),
        "sample_count_min": int(valid_daily_ic["sample_count"].min()),
        "sample_count_median": int(valid_daily_ic["sample_count"].median()),
        "sample_count_max": int(valid_daily_ic["sample_count"].max()),
        "industry_count_median": int(valid_daily_ic["industry_count"].median()),
        "thresholds": {
            "retain": RETAIN_THRESHOLD,
            "observe": OBSERVE_THRESHOLD,
            "minimum_cross_section_size": MIN_CROSS_SECTION_SIZE,
            "original_observe_can_be_promoted": False,
        },
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
    }
    (args.output_dir / "neutralization_methodology.json").write_text(
        json.dumps(metadata, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    write_report(args.output_dir / "neutralization_report.txt", decisions, metadata)

    counts = decisions["neutralization_status"].value_counts().to_dict()
    print(
        "completed|"
        + "|".join(
            f"{key}={counts.get(key, 0)}"
            for key in ["retain_survives", "observe_survives", "eliminate_after_neutralization"]
        )
    )


if __name__ == "__main__":
    main()
