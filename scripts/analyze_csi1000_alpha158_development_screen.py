#!/usr/bin/env python3
"""Screen raw Alpha158 factors using the frozen 2023-2024 development split."""

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


def alpha158_definitions() -> tuple[list[str], list[str]]:
    """Get all 158 raw expressions and their canonical Alpha158 names."""
    return Alpha158DL.get_feature_config(
        {
            "kbar": {},
            "price": {"windows": [0], "feature": ["OPEN", "HIGH", "LOW", "VWAP"]},
            "rolling": {},
        }
    )


def previous_trading_day(calendar: pd.Series, date: pd.Timestamp, count: int) -> pd.Timestamp:
    """Return the date ``count`` trading sessions before the given date."""
    past = calendar[calendar < date]
    if len(past) < count:
        raise ValueError(f"Calendar has fewer than {count} days before {date.date()}")
    return past.iloc[-count]


def rank_ic_by_day(frame: pd.DataFrame, factor_names: list[str]) -> pd.DataFrame:
    """Calculate a Spearman Rank IC for every factor on each daily cross section."""
    records = []
    for date, cross_section in frame.groupby(level="datetime", sort=True):
        label = cross_section["label"]
        for factor in factor_names:
            sample = pd.concat([cross_section[factor], label], axis=1).dropna()
            if len(sample) < 50 or sample.iloc[:, 0].nunique() < 2 or sample["label"].nunique() < 2:
                ic = np.nan
                sample_count = len(sample)
            else:
                ic = sample.iloc[:, 0].corr(sample["label"], method="spearman")
                sample_count = len(sample)
            records.append(
                {
                    "datetime": date,
                    "factor": factor,
                    "rank_ic": ic,
                    "sample_count": sample_count,
                }
            )
    return pd.DataFrame(records)


def summarize_year(daily_ic: pd.DataFrame, year: int, factors: list[str]) -> pd.DataFrame:
    """Aggregate each factor's valid daily IC observations for one calendar year."""
    period = daily_ic[daily_ic["datetime"].dt.year.eq(year)]
    rows = []
    for factor in factors:
        group = period[period["factor"].eq(factor)]
        values = group["rank_ic"].dropna()
        rows.append(
            {
                "factor": factor,
                "days": int(len(values)),
                "rank_ic": values.mean(),
                "rank_icir": values.mean() / values.std(ddof=1),
                "positive_ratio": (values > 0).mean(),
                "sample_count_median": int(group["sample_count"].median()),
                "sample_count_min": int(group["sample_count"].min()),
                "sample_count_max": int(group["sample_count"].max()),
            }
        )
    return pd.DataFrame(rows)


def classify(summary_2023: pd.DataFrame, summary_2024: pd.DataFrame) -> pd.DataFrame:
    """Apply the v1 protocol's pre-declared two-year stability thresholds."""
    result = summary_2023.merge(summary_2024, on="factor", suffixes=("_2023", "_2024"))
    ic_2023 = result["rank_ic_2023"]
    ic_2024 = result["rank_ic_2024"]
    same_direction = (np.sign(ic_2023) == np.sign(ic_2024)) & (np.sign(ic_2023) != 0)
    minimum_strength = pd.concat([ic_2023.abs(), ic_2024.abs()], axis=1).min(axis=1)

    result["two_year_same_direction"] = same_direction
    result["min_abs_rank_ic"] = minimum_strength
    result["classification"] = np.select(
        [
            same_direction & (minimum_strength >= RETAIN_THRESHOLD),
            same_direction & (minimum_strength >= OBSERVE_THRESHOLD),
        ],
        ["retain", "observe"],
        default="eliminate",
    )
    return result


def write_report(path: Path, decisions: pd.DataFrame, metadata: dict) -> None:
    """Write a compact Chinese report explaining the pre-declared screen."""
    counts = decisions["classification"].value_counts().to_dict()
    lines = [
        "CSI1000 Alpha158 开发集原始因子有效性筛选（2023-2024）",
        "=" * 58,
        "",
        "目的：在未用于后续回溯确认的开发集上，重新筛选可进入中性化验证的 Alpha158 原始因子。",
        "标签：Ref($close, -2) / Ref($close, -1) - 1。每个交易日分别计算因子与标签的截面 Spearman Rank IC。",
        "预热：从 2022-10-10 读取数据以覆盖最长 60 日滚动窗口，但仅统计 2023-2024 年的 IC。",
        "股票池：Qlib CSI1000 每日历史成分；因子或标签缺失的股票日不参与该因子的当日 IC。",
        "",
        "冻结判定规则：",
        "- 保留：2023、2024 年平均 Rank IC 同方向，且两年绝对值均 >= 0.02。",
        "- 观察：同方向，且两年绝对值均 >= 0.01，但未达到保留门槛。",
        "- 淘汰：其他情况。分类使用较弱年份，不使用两年平均掩盖衰减。",
        "",
        f"有效标签日期：{metadata['first_score_date']} 至 {metadata['last_score_date']}，共 {metadata['score_days']} 日。",
        f"每个因子日截面样本量：{metadata['sample_count_min']} 至 {metadata['sample_count_max']}，中位数 {metadata['sample_count_median']}。",
        f"结果计数：保留 {counts.get('retain', 0)}，观察 {counts.get('observe', 0)}，淘汰 {counts.get('eliminate', 0)}。",
        "",
        "全部因子结果：",
    ]
    display = decisions[
        [
            "factor",
            "rank_ic_2023",
            "rank_icir_2023",
            "rank_ic_2024",
            "rank_icir_2024",
            "min_abs_rank_ic",
            "classification",
        ]
    ].sort_values(["classification", "min_abs_rank_ic"], ascending=[True, False])
    lines.append(display.to_string(index=False, float_format=lambda x: f"{x:.4f}"))
    lines += [
        "",
        "本步骤未进行行业/市值中性化、数学去重、模型训练或回测。",
        "通过保留或观察门槛的因子仍须接受后续中性化与冗余审查。",
    ]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--qlib-data-dir", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--score-start-date", default="2023-01-01")
    parser.add_argument("--score-end-date", default="2024-12-31")
    parser.add_argument("--warmup-trading-days", type=int, default=60)
    args = parser.parse_args()

    score_start = pd.Timestamp(args.score_start_date)
    score_end = pd.Timestamp(args.score_end_date)
    calendar = pd.to_datetime(pd.read_csv(args.qlib_data_dir / "calendars" / "day.txt", header=None)[0])
    warmup_start = previous_trading_day(calendar, score_start, args.warmup_trading_days)

    fields, factor_names = alpha158_definitions()
    if len(fields) != 158 or len(factor_names) != 158 or len(set(factor_names)) != 158:
        raise RuntimeError("Alpha158 definition does not contain 158 unique factors")

    qlib.init(provider_uri=str(args.qlib_data_dir), region=REG_CN)
    raw = D.features(
        D.instruments("csi1000"),
        fields + [LABEL_FIELD],
        start_time=warmup_start,
        end_time=score_end,
        freq="day",
    )
    raw.columns = factor_names + ["label"]
    score_frame = raw[(raw.index.get_level_values("datetime") >= score_start)].copy()
    daily_ic = rank_ic_by_day(score_frame, factor_names)
    valid_daily_ic = daily_ic.dropna(subset=["rank_ic"]).copy()

    summary_2023 = summarize_year(valid_daily_ic, 2023, factor_names)
    summary_2024 = summarize_year(valid_daily_ic, 2024, factor_names)
    decisions = classify(summary_2023, summary_2024)

    args.output_dir.mkdir(parents=True, exist_ok=True)
    daily_ic.to_csv(args.output_dir / "daily_rank_ic.csv.gz", index=False, compression="gzip")
    summary_2023.to_csv(args.output_dir / "summary_2023.csv", index=False)
    summary_2024.to_csv(args.output_dir / "summary_2024.csv", index=False)
    decisions.to_csv(args.output_dir / "factor_decisions.csv", index=False)

    metadata = {
        "purpose": "Development-set raw Alpha158 factor screening under CSI1000 validation protocol v1",
        "protocol": "research/protocols/csi1000_alpha158_validation_protocol_v1.md",
        "market": "CSI1000 historical daily constituents",
        "label_expression": LABEL_FIELD,
        "warmup_start": str(warmup_start.date()),
        "score_start": args.score_start_date,
        "score_end": args.score_end_date,
        "first_score_date": str(valid_daily_ic["datetime"].min().date()),
        "last_score_date": str(valid_daily_ic["datetime"].max().date()),
        "score_days": int(valid_daily_ic["datetime"].nunique()),
        "alpha158_factor_count": len(factor_names),
        "sample_count_min": int(valid_daily_ic["sample_count"].min()),
        "sample_count_median": int(valid_daily_ic["sample_count"].median()),
        "sample_count_max": int(valid_daily_ic["sample_count"].max()),
        "classification_rule": {
            "retain": "same non-zero sign in 2023/2024 and abs(mean Rank IC) >= 0.02 in both years",
            "observe": "same non-zero sign in 2023/2024 and abs(mean Rank IC) >= 0.01 in both years, but not retain",
            "eliminate": "all other cases",
        },
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
    }
    (args.output_dir / "methodology.json").write_text(
        json.dumps(metadata, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    write_report(args.output_dir / "development_screen_report.txt", decisions, metadata)

    counts = decisions["classification"].value_counts().to_dict()
    print(
        "completed|"
        + "|".join(f"{key}={counts.get(key, 0)}" for key in ["retain", "observe", "eliminate"])
    )


if __name__ == "__main__":
    main()
