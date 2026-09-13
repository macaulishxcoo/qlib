#!/usr/bin/env python3
"""Check redundancy among Alpha158 factors that passed neutralization validation."""

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
CORRELATION_THRESHOLD = 0.80
IC_CORRELATION_THRESHOLD = 0.70


def qlib_to_tushare(symbol: str) -> str:
    """Convert Qlib's SH600000 notation to Tushare's 600000.SH notation."""
    return f"{symbol[2:]}.{symbol[:2]}"


def alpha158_fields(factors: list[str]) -> dict[str, str]:
    """Read the unprocessed Alpha158 expressions used in the prior validation."""
    fields, names = Alpha158DL.get_feature_config(
        {
            "kbar": {},
            "price": {"windows": [0], "feature": ["OPEN", "HIGH", "LOW", "VWAP"]},
            "rolling": {},
        }
    )
    field_map = dict(zip(names, fields))
    missing = sorted(set(factors) - set(field_map))
    if missing:
        raise RuntimeError(f"Alpha158 definitions missing: {missing}")
    return field_map


def load_auxiliary_data(data_dir: Path) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Load the already-validated point-in-time size and industry data."""
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


def build_industry_by_day(industry: pd.DataFrame, dates: pd.Series) -> pd.DataFrame:
    """Return the industry that was effective for each stock on every date."""
    records = []
    for date in dates.drop_duplicates().sort_values():
        active = industry[
            (industry["in_date"] <= date)
            & (industry["out_date"].isna() | (industry["out_date"] >= date))
        ].copy()
        active = active.sort_values(["ts_code", "in_date"]).drop_duplicates(
            "ts_code", keep="last"
        )
        active["datetime"] = date
        records.append(active[["ts_code", "datetime", "l1_code"]])
    return pd.concat(records, ignore_index=True)


def daily_residuals(frame: pd.DataFrame, factors: list[str]) -> pd.DataFrame:
    """Residualize every selected factor on the same daily common stock sample."""
    required = factors + ["label", "log_free_float_mv", "l1_code"]
    sample = frame[required].dropna().copy()
    if len(sample) < 50:
        return pd.DataFrame(columns=factors)
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
    residual = values - design @ coefficients
    result = pd.DataFrame(residual, columns=factors, index=sample.index)
    result["label"] = sample["label"]
    return result


def pairwise_summary(daily_correlations: list[pd.DataFrame], factors: list[str]) -> pd.DataFrame:
    """Summarize daily cross-sectional residual Rank correlations for every pair."""
    records = []
    for corr in daily_correlations:
        for left_index, left in enumerate(factors):
            for right in factors[left_index + 1 :]:
                records.append(
                    {
                        "factor_left": left,
                        "factor_right": right,
                        "rank_correlation": corr.loc[left, right],
                    }
                )
    daily = pd.DataFrame(records)
    result = (
        daily.groupby(["factor_left", "factor_right"], sort=False)["rank_correlation"]
        .agg(
            mean_rank_correlation="mean",
            median_rank_correlation="median",
            median_abs_rank_correlation=lambda x: x.abs().median(),
            p90_abs_rank_correlation=lambda x: x.abs().quantile(0.90),
            same_sign_ratio=lambda x: (np.sign(x) == np.sign(x.median())).mean(),
        )
        .reset_index()
    )
    return result


def factor_theme(factor: str) -> str:
    """Use economic interpretation only for the report, never as a deletion rule."""
    if factor in {"KLEN", "STD5", "STD10", "STD20"}:
        return "low_volatility"
    if factor in {"VSUMD30", "VSUMD60", "VMA60"}:
        return "volume_contraction"
    if factor == "HIGH0":
        return "close_strength"
    if factor == "SUMD30":
        return "medium_term_reversal"
    if factor == "CORD10":
        return "price_volume_relation"
    return "other"


def connected_components(edges: pd.DataFrame, factors: list[str]) -> list[list[str]]:
    """Build components only from pairs meeting both redundancy thresholds."""
    neighbors = {factor: set() for factor in factors}
    for row in edges.itertuples(index=False):
        neighbors[row.factor_left].add(row.factor_right)
        neighbors[row.factor_right].add(row.factor_left)

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
        components.append(sorted(component, key=factors.index))
    return components


def write_report(
    path: Path,
    decisions: pd.DataFrame,
    pair_summary: pd.DataFrame,
    strong_edges: pd.DataFrame,
    metadata: dict,
) -> None:
    """Write a concise Chinese explanation of the non-destructive selection decision."""
    lines = [
        "CSI1000 Alpha158 中性化保留因子：冗余性审查与最终候选集",
        "=" * 62,
        "",
        "目的：检查通过行业/市值中性化验证的因子是否仍然重复描述同一截面信息。",
        "本步骤不按主题名称删因子；只有统计相关性与逐日 IC 同步性都达到严格门槛，才建议缩减。",
        "",
        "方法：",
        "1. 每个交易日，在相同股票样本上将每个因子回归到 log(自由流通市值) 和一级行业哑变量，取残差。",
        "2. 计算任意两个残差因子的当日 Spearman 截面相关；汇总 374 个有效标签日的中位数绝对相关。",
        "3. 读取此前已计算的逐日中性化 Rank IC，计算两个因子 IC 序列的 Pearson 相关。",
        f"4. 仅当中位数绝对截面相关 >= {CORRELATION_THRESHOLD:.2f} 且 |逐日 IC 相关| >= {IC_CORRELATION_THRESHOLD:.2f} 时，认定为冗余候选。",
        "",
        f"有效日期：{metadata['first_date']} 至 {metadata['last_date']}，共 {metadata['trading_days']} 日；",
        f"共同样本量：每日 {metadata['sample_count_min']} 至 {metadata['sample_count_max']}，中位数 {metadata['sample_count_median']}。",
        "",
        "因子判定：",
    ]
    display = decisions[
        [
            "factor",
            "theme",
            "neutral_rank_ic_2025",
            "neutral_rank_ic_2026",
            "min_abs_neutral_rank_ic",
            "final_status",
            "selection_reason",
        ]
    ]
    lines.append(display.to_string(index=False, float_format=lambda x: f"{x:.4f}"))
    lines += ["", "满足双重冗余门槛的因子对："]
    if strong_edges.empty:
        lines.append("无。所有 10 个通过中性化门槛的因子暂时保留为核心候选。")
    else:
        lines.append(
            strong_edges[
                [
                    "factor_left",
                    "factor_right",
                    "median_abs_rank_correlation",
                    "ic_correlation",
                ]
            ].to_string(index=False, float_format=lambda x: f"{x:.4f}")
        )
    lines += [
        "",
        "注意：最终核心候选集不是实盘模型输入的最终定论。后续会在相同样本外窗口比较完整 Alpha158、10 因子集与任何缩减集，",
        "只有样本外结果证明缩减更优或等价，才会在训练配置中使用缩减集。",
    ]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--qlib-data-dir", type=Path, required=True)
    parser.add_argument("--auxiliary-data-dir", type=Path, required=True)
    parser.add_argument("--neutralization-dir", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--start-date", default="2025-01-01")
    parser.add_argument("--end-date", default="2026-07-23")
    args = parser.parse_args()

    decisions = pd.read_csv(args.neutralization_dir / "factor_decisions.csv")
    retained = decisions[decisions["classification"].eq("retain")].copy()
    factors = retained["factor"].tolist()
    if not factors:
        raise SystemExit("No retained factors found in factor_decisions.csv")
    daily_ic = pd.read_csv(
        args.neutralization_dir / "daily_rank_ic.csv.gz",
        compression="gzip",
        parse_dates=["datetime"],
    ).dropna(subset=["neutral_rank_ic"])

    qlib.init(provider_uri=str(args.qlib_data_dir), region=REG_CN)
    fields_by_name = alpha158_fields(factors)
    fields = [fields_by_name[factor] for factor in factors] + [LABEL_FIELD]
    raw = D.features(
        D.instruments("csi1000"),
        fields,
        start_time=args.start_date,
        end_time=args.end_date,
        freq="day",
    )
    raw.columns = factors + ["label"]
    raw = raw.reset_index().rename(columns={"instrument": "qlib_symbol"})
    raw["datetime"] = pd.to_datetime(raw["datetime"])
    raw["ts_code"] = raw["qlib_symbol"].map(qlib_to_tushare)

    daily_size, industry = load_auxiliary_data(args.auxiliary_data_dir)
    industry_by_day = build_industry_by_day(industry, raw["datetime"])
    frame = raw.merge(
        daily_size[["ts_code", "datetime", "log_free_float_mv"]],
        on=["ts_code", "datetime"],
        how="left",
    ).merge(industry_by_day, on=["ts_code", "datetime"], how="left")

    daily_correlations = []
    samples = []
    for date, day_frame in frame.groupby("datetime", sort=True):
        residual = daily_residuals(day_frame, factors)
        if residual.empty:
            continue
        daily_correlations.append(residual[factors].corr(method="spearman"))
        samples.append({"datetime": date, "sample_count": len(residual)})
    if not daily_correlations:
        raise SystemExit("No valid common cross sections for redundancy analysis")

    pair_summary = pairwise_summary(daily_correlations, factors)
    ic_wide = daily_ic[daily_ic["factor"].isin(factors)].pivot(
        index="datetime", columns="factor", values="neutral_rank_ic"
    )[factors]
    ic_corr = ic_wide.corr(method="pearson")
    ic_corr_records = []
    for left_index, left in enumerate(factors):
        for right in factors[left_index + 1 :]:
            ic_corr_records.append(
                {
                    "factor_left": left,
                    "factor_right": right,
                    "ic_correlation": ic_corr.loc[left, right],
                }
            )
    ic_corr_long = pd.DataFrame(ic_corr_records)
    pair_summary = pair_summary.merge(
        ic_corr_long, on=["factor_left", "factor_right"], how="left"
    )
    pair_summary["is_redundant_pair"] = (
        pair_summary["median_abs_rank_correlation"] >= CORRELATION_THRESHOLD
    ) & (pair_summary["ic_correlation"].abs() >= IC_CORRELATION_THRESHOLD)
    pair_summary = pair_summary.sort_values(
        ["is_redundant_pair", "median_abs_rank_correlation"], ascending=[False, False]
    ).reset_index(drop=True)
    strong_edges = pair_summary[pair_summary["is_redundant_pair"]].copy()

    components = connected_components(strong_edges, factors)
    retained["theme"] = retained["factor"].map(factor_theme)
    retained["final_status"] = "core_candidate"
    retained["selection_reason"] = "no_pair_meets_both_redundancy_thresholds"
    for component in components:
        if len(component) < 2:
            continue
        group = retained[retained["factor"].isin(component)].copy()
        winner = group.sort_values(
            ["min_abs_neutral_rank_ic", "neutral_rank_ic_2026"],
            key=lambda series: series.abs(),
            ascending=False,
        ).iloc[0]["factor"]
        losers = set(component) - {winner}
        retained.loc[retained["factor"].eq(winner), "selection_reason"] = (
            "representative_of_redundant_group"
        )
        retained.loc[retained["factor"].isin(losers), "final_status"] = "redundant_backup"
        retained.loc[retained["factor"].isin(losers), "selection_reason"] = (
            f"redundant_with_{winner}"
        )

    retained = retained[
        [
            "factor",
            "theme",
            "neutral_rank_ic_2025",
            "neutral_rank_ic_2026",
            "min_abs_neutral_rank_ic",
            "final_status",
            "selection_reason",
        ]
    ]
    args.output_dir.mkdir(parents=True, exist_ok=True)
    pair_summary.to_csv(args.output_dir / "neutral_factor_pair_correlation.csv", index=False)
    ic_corr.to_csv(args.output_dir / "neutral_factor_daily_ic_correlation.csv")
    retained.to_csv(args.output_dir / "final_factor_selection.csv", index=False)

    sample_data = pd.DataFrame(samples)
    metadata = {
        "purpose": "Check statistical redundancy among Alpha158 factors retained after industry/size neutralization",
        "factors": factors,
        "first_date": str(sample_data["datetime"].min().date()),
        "last_date": str(sample_data["datetime"].max().date()),
        "trading_days": int(sample_data["datetime"].nunique()),
        "sample_count_min": int(sample_data["sample_count"].min()),
        "sample_count_median": int(sample_data["sample_count"].median()),
        "sample_count_max": int(sample_data["sample_count"].max()),
        "factor_value_correlation": "Daily cross-sectional Spearman correlation of industry/size-neutral factor residuals; summary uses median absolute correlation.",
        "ic_correlation": "Pearson correlation of prior daily neutral Rank IC time series.",
        "redundancy_rule": {
            "median_abs_residual_rank_correlation_gte": CORRELATION_THRESHOLD,
            "abs_daily_neutral_rank_ic_correlation_gte": IC_CORRELATION_THRESHOLD,
            "both_required": True,
        },
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
    }
    (args.output_dir / "final_selection_methodology.json").write_text(
        json.dumps(metadata, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    write_report(
        args.output_dir / "final_factor_selection_report.txt",
        retained,
        pair_summary,
        strong_edges,
        metadata,
    )
    print(
        f"completed|core_candidate={(retained['final_status'] == 'core_candidate').sum()}"
        f"|redundant_backup={(retained['final_status'] == 'redundant_backup').sum()}"
        f"|redundant_pairs={len(strong_edges)}"
    )


if __name__ == "__main__":
    main()
