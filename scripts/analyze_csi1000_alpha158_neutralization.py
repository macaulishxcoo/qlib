#!/usr/bin/env python3
"""Evaluate whether selected Alpha158 factors survive industry/size neutralization."""

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


CANDIDATE_FACTORS = [
    "KLEN",
    "STD5",
    "STD10",
    "STD20",
    "HIGH0",
    "LOW0",
    "MIN5",
    "MIN60",
    "SUMD30",
    "SUMD60",
    "VSUMD30",
    "VSUMD60",
    "CORR5",
    "CORR10",
    "CORR20",
    "CORR30",
    "CORD5",
    "CORD10",
    "VMA60",
    "IMXD30",
    "IMXD60",
    "BETA60",
]
LABEL_FIELD = "Ref($close, -2)/Ref($close, -1) - 1"


def qlib_to_tushare(symbol: str) -> str:
    """Convert Qlib's SH600000 notation into Tushare's 600000.SH notation."""
    return f"{symbol[2:]}.{symbol[:2]}"


def alpha158_fields() -> dict[str, str]:
    """Return the unprocessed Alpha158 expression for every named factor."""
    fields, names = Alpha158DL.get_feature_config(
        {
            "kbar": {},
            "price": {"windows": [0], "feature": ["OPEN", "HIGH", "LOW", "VWAP"]},
            "rolling": {},
        }
    )
    field_map = dict(zip(names, fields))
    missing = sorted(set(CANDIDATE_FACTORS) - set(field_map))
    if missing:
        raise RuntimeError(f"Alpha158 definitions missing: {missing}")
    return field_map


def load_auxiliary_data(data_dir: Path) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Load market-cap data and point-in-time industry records downloaded from Tushare."""
    daily = pd.read_csv(
        data_dir / "daily_basic_csi1000.csv.gz",
        compression="gzip",
        usecols=["ts_code", "trade_date", "close", "free_share"],
        dtype={"ts_code": str, "trade_date": str},
    )
    daily["datetime"] = pd.to_datetime(daily["trade_date"])
    daily["log_free_float_mv"] = np.log(
        pd.to_numeric(daily["close"], errors="coerce")
        * pd.to_numeric(daily["free_share"], errors="coerce")
    )
    daily = daily.replace([np.inf, -np.inf], np.nan)

    industry = pd.read_csv(
        data_dir / "industry_member_history_csi1000.csv.gz",
        compression="gzip",
        usecols=["ts_code", "l1_code", "in_date", "out_date"],
        dtype=str,
    )
    industry["in_date"] = pd.to_datetime(industry["in_date"])
    industry["out_date"] = pd.to_datetime(industry["out_date"], errors="coerce")
    return daily, industry


def build_industry_by_day(
    industry: pd.DataFrame, trading_days: pd.Series
) -> pd.DataFrame:
    """Select the industry record that was effective on each requested day."""
    records = []
    for date in trading_days.drop_duplicates().sort_values():
        active = industry[
            (industry["in_date"] <= date)
            & (industry["out_date"].isna() | (industry["out_date"] >= date))
        ].copy()
        # A small number of records overlap during classification changes. The newest
        # effective record is the classification available on that date.
        active = active.sort_values(["ts_code", "in_date"]).drop_duplicates(
            "ts_code", keep="last"
        )
        active["datetime"] = date
        records.append(active[["ts_code", "datetime", "l1_code"]])
    return pd.concat(records, ignore_index=True)


def rank_ic(score: pd.Series, label: pd.Series) -> float:
    """Spearman cross-sectional correlation, returning NaN for degenerate samples."""
    if score.nunique() < 2 or label.nunique() < 2:
        return np.nan
    return score.corr(label, method="spearman")


def neutralize_factor(frame: pd.DataFrame, factor: str) -> tuple[float, float, int]:
    """Regress a daily factor cross section on log size and industry dummies."""
    sample = frame[[factor, "label", "log_free_float_mv", "l1_code"]].dropna()
    if len(sample) < 50:
        return np.nan, np.nan, len(sample)

    industry_dummies = pd.get_dummies(sample["l1_code"], dtype=float)
    # Drop one industry dummy: together with the intercept this avoids collinearity.
    design = np.column_stack(
        [
            np.ones(len(sample)),
            sample["log_free_float_mv"].to_numpy(dtype=float),
            industry_dummies.iloc[:, 1:].to_numpy(dtype=float),
        ]
    )
    values = sample[factor].to_numpy(dtype=float)
    coefficients, _, _, _ = np.linalg.lstsq(design, values, rcond=None)
    residual = values - design @ coefficients
    return (
        rank_ic(sample[factor], sample["label"]),
        rank_ic(pd.Series(residual, index=sample.index), sample["label"]),
        len(sample),
    )


def summarize_period(daily_ic: pd.DataFrame, start: str, end: str) -> pd.DataFrame:
    """Aggregate daily Rank IC statistics for an inclusive calendar period."""
    period = daily_ic[(daily_ic["datetime"] >= start) & (daily_ic["datetime"] <= end)]
    rows = []
    for factor, group in period.groupby("factor", sort=False):
        raw = group["raw_rank_ic"].dropna()
        neutral = group["neutral_rank_ic"].dropna()
        rows.append(
            {
                "factor": factor,
                "days": int(len(neutral)),
                "raw_rank_ic": raw.mean(),
                "raw_rank_icir": raw.mean() / raw.std(ddof=1),
                "neutral_rank_ic": neutral.mean(),
                "neutral_rank_icir": neutral.mean() / neutral.std(ddof=1),
                "neutral_ic_positive_ratio": (neutral > 0).mean(),
                "sample_count_median": int(group["sample_count"].median()),
                "sample_count_min": int(group["sample_count"].min()),
                "sample_count_max": int(group["sample_count"].max()),
            }
        )
    if not rows:
        # Keep the schema stable for smoke tests or incomplete calendar periods.
        return pd.DataFrame({"factor": CANDIDATE_FACTORS})
    result = pd.DataFrame(rows).set_index("factor").reindex(CANDIDATE_FACTORS).reset_index()
    return result


def classify(summary_2025: pd.DataFrame, summary_2026: pd.DataFrame) -> pd.DataFrame:
    """Apply the previously agreed two-period Rank IC screening thresholds."""
    merged = summary_2025.merge(summary_2026, on="factor", suffixes=("_2025", "_2026"))
    ic_2025 = merged["neutral_rank_ic_2025"]
    ic_2026 = merged["neutral_rank_ic_2026"]
    same_direction = np.sign(ic_2025) == np.sign(ic_2026)
    magnitude = pd.concat([ic_2025.abs(), ic_2026.abs()], axis=1).min(axis=1)

    merged["two_period_same_direction"] = same_direction
    merged["min_abs_neutral_rank_ic"] = magnitude
    merged["classification"] = np.select(
        [same_direction & (magnitude >= 0.02), same_direction & (magnitude >= 0.01)],
        ["retain", "observe"],
        default="eliminate",
    )
    raw_mean_abs = (
        merged["raw_rank_ic_2025"].abs() + merged["raw_rank_ic_2026"].abs()
    ) / 2
    neutral_mean_abs = (
        merged["neutral_rank_ic_2025"].abs() + merged["neutral_rank_ic_2026"].abs()
    ) / 2
    merged["mean_abs_ic_retention_ratio"] = neutral_mean_abs / raw_mean_abs.replace(0, np.nan)
    merged["combined_exposure_assessment"] = np.select(
        [
            merged["classification"].eq("retain"),
            merged["mean_abs_ic_retention_ratio"] < 0.5,
        ],
        ["independent_signal_survives", "mostly_industry_or_size_exposure"],
        default="partially_exposure_dependent_or_insufficient",
    )
    return merged


def write_report(
    report_path: Path,
    result: pd.DataFrame,
    metadata: dict,
) -> None:
    """Write a compact, reviewable Chinese report alongside the machine-readable CSVs."""
    lines = [
        "CSI1000 Alpha158 候选因子行业/自由流通市值中性化验证",
        "=" * 58,
        "",
        "目的：检验候选因子的预测力是否只是行业或自由流通市值暴露。",
        "方法：每个交易日做截面 OLS 回归：因子值 ~ 截距 + log(自由流通股本 × 收盘价) + 一级申万行业哑变量；",
        "取回归残差，与原标签分别计算 Spearman Rank IC。",
        "标签：Ref($close, -2) / Ref($close, -1) - 1，与此前 Alpha158 单因子诊断一致。",
        "股票池：按 Qlib CSI1000 历史成分；缺失因子、标签、行业或市值的股票日严格剔除。",
        "",
        f"实际分析日期：{metadata['first_date']} 至 {metadata['last_date']}；共 {metadata['trading_days']} 个有效交易日。",
        f"中性化日截面样本量（所有因子汇总）：{metadata['sample_count_min']} 至 {metadata['sample_count_max']}，中位数 {metadata['sample_count_median']}。",
        "判定：两段期间方向一致且两段 |中性化 Rank IC| >= 0.02 为保留；>= 0.01 为观察；其他淘汰。",
        "",
        "结果：",
    ]
    display_columns = [
        "factor",
        "raw_rank_ic_2025",
        "neutral_rank_ic_2025",
        "raw_rank_ic_2026",
        "neutral_rank_ic_2026",
        "mean_abs_ic_retention_ratio",
        "classification",
        "combined_exposure_assessment",
    ]
    lines.append(result[display_columns].to_string(index=False, float_format=lambda x: f"{x:.4f}"))
    lines += [
        "",
        "说明：combined_exposure_assessment 只判断行业与市值合并后的影响，不能把二者的贡献单独归因。",
        "结果仅用于确定下一版候选因子集；本步骤不训练模型、不回测，也不构成实盘依据。",
    ]
    report_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--qlib-data-dir", type=Path, required=True)
    parser.add_argument("--auxiliary-data-dir", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--start-date", default="2025-01-01")
    parser.add_argument("--end-date", default="2026-07-23")
    args = parser.parse_args()

    args.output_dir.mkdir(parents=True, exist_ok=True)
    qlib.init(provider_uri=str(args.qlib_data_dir), region=REG_CN)

    fields_by_name = alpha158_fields()
    fields = [fields_by_name[name] for name in CANDIDATE_FACTORS] + [LABEL_FIELD]
    raw = D.features(
        D.instruments("csi1000"),
        fields,
        start_time=args.start_date,
        end_time=args.end_date,
        freq="day",
    )
    raw.columns = CANDIDATE_FACTORS + ["label"]
    raw = raw.reset_index().rename(columns={"instrument": "qlib_symbol"})
    raw["ts_code"] = raw["qlib_symbol"].map(qlib_to_tushare)
    raw["datetime"] = pd.to_datetime(raw["datetime"])

    daily, industry = load_auxiliary_data(args.auxiliary_data_dir)
    industry_by_day = build_industry_by_day(industry, raw["datetime"])
    frame = raw.merge(
        daily[["ts_code", "datetime", "log_free_float_mv"]],
        on=["ts_code", "datetime"],
        how="left",
    ).merge(industry_by_day, on=["ts_code", "datetime"], how="left")

    daily_rows = []
    for date, day_frame in frame.groupby("datetime", sort=True):
        for factor in CANDIDATE_FACTORS:
            raw_ic, neutral_ic, sample_count = neutralize_factor(day_frame, factor)
            daily_rows.append(
                {
                    "datetime": date,
                    "factor": factor,
                    "raw_rank_ic": raw_ic,
                    "neutral_rank_ic": neutral_ic,
                    "sample_count": sample_count,
                }
            )
    daily_ic = pd.DataFrame(daily_rows)
    daily_ic.to_csv(args.output_dir / "daily_rank_ic.csv.gz", index=False, compression="gzip")

    # The last dates can lack a forward-return label because the Qlib calendar ends.
    # Exclude them from all period and sample-coverage statistics.
    valid_daily_ic = daily_ic.dropna(subset=["raw_rank_ic", "neutral_rank_ic"]).copy()
    summary_2025 = summarize_period(valid_daily_ic, "2025-01-01", "2025-12-31")
    summary_2026 = summarize_period(valid_daily_ic, "2026-01-01", args.end_date)
    summary_2025.to_csv(args.output_dir / "summary_2025.csv", index=False)
    summary_2026.to_csv(args.output_dir / "summary_2026_to_2026-07-23.csv", index=False)

    result = classify(summary_2025, summary_2026)
    result.to_csv(args.output_dir / "factor_decisions.csv", index=False)
    metadata = {
        "purpose": "Industry and free-float market-cap neutralization validation for selected Alpha158 factors",
        "candidate_factors": CANDIDATE_FACTORS,
        "label_expression": LABEL_FIELD,
        "neutralization": "factor ~ intercept + log(free_share * close) + Shenwan level-1 industry dummies",
        "periods": {"2025": ["2025-01-01", "2025-12-31"], "2026": ["2026-01-01", args.end_date]},
        "first_date": str(valid_daily_ic["datetime"].min().date()),
        "last_date": str(valid_daily_ic["datetime"].max().date()),
        "trading_days": int(valid_daily_ic["datetime"].nunique()),
        "sample_count_min": int(valid_daily_ic["sample_count"].min()),
        "sample_count_median": int(valid_daily_ic["sample_count"].median()),
        "sample_count_max": int(valid_daily_ic["sample_count"].max()),
        "classification_rule": {
            "retain": "same direction in 2025/2026 and abs(neutral Rank IC) >= 0.02 in both periods",
            "observe": "same direction in 2025/2026 and abs(neutral Rank IC) >= 0.01 in both periods",
            "eliminate": "all other cases",
        },
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
    }
    (args.output_dir / "methodology.json").write_text(
        json.dumps(metadata, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    write_report(args.output_dir / "neutralization_report.txt", result, metadata)

    counts = result["classification"].value_counts().to_dict()
    print(
        "completed|"
        + "|".join(f"{key}={counts.get(key, 0)}" for key in ["retain", "observe", "eliminate"])
    )


if __name__ == "__main__":
    main()
