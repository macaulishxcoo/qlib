#!/usr/bin/env python3
"""Validate only the development stage of the frozen working-capital hypothesis.

This program intentionally has no confirmation or holdout date range.  It
reads Qlib open prices only through the final 60-day label needed by the
2014--2019 development months; it never trains a model or runs a backtest.
"""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path

import numpy as np
import pandas as pd
import qlib
from qlib.config import REG_CN
from qlib.data import D


DEVELOPMENT_START = pd.Timestamp("2014-01-01")
DEVELOPMENT_END = pd.Timestamp("2019-12-31")
HORIZONS = (20, 40, 60)
MAIN_SCORE = "working_capital_quality"
SCORES = (MAIN_SCORE, "receivable_quality", "inventory_quality")
FINANCIAL_L1_CODES = {"801780.SI", "801790.SI"}


def atomic_csv(frame: pd.DataFrame, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    frame.to_csv(temporary, index=False, compression="gzip" if path.suffix == ".gz" else None)
    os.replace(temporary, path)


def atomic_json(value: object, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(temporary, path)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def qlib_symbol(ts_code: str) -> str:
    code, exchange = ts_code.split(".")
    return f"{exchange}{code}"


def spearman(left: pd.Series, right: pd.Series) -> float:
    if len(left) < 2 or left.nunique(dropna=True) < 2 or right.nunique(dropna=True) < 2:
        return np.nan
    return float(left.corr(right, method="spearman"))


def ols_residual(score: pd.Series, industry: pd.Series, size: pd.Series) -> pd.Series:
    """Remove the frozen intercept, size, and level-1 industry exposures."""
    dummies = pd.get_dummies(industry, dtype=float)
    if dummies.shape[1] > 0:
        dummies = dummies.iloc[:, 1:]
    design = np.column_stack([np.ones(len(score)), size.to_numpy(dtype=float), dummies.to_numpy(dtype=float)])
    beta, *_ = np.linalg.lstsq(design, score.to_numpy(dtype=float), rcond=None)
    return pd.Series(score.to_numpy(dtype=float) - design @ beta, index=score.index)


def attach_monthly_controls(events: pd.DataFrame, grid_row: pd.Series, industry: pd.DataFrame, size: pd.DataFrame) -> pd.DataFrame:
    date = grid_row.rebalance_date
    current = events.loc[events["effective_date"].le(date) & events["expiry_date"].ge(date)].copy()
    if current.empty:
        return current
    current = current.sort_values(["ts_code", "effective_date", "available_date"], kind="mergesort").drop_duplicates("ts_code", keep="last")
    asof = grid_row.asof_date
    applicable = industry.loc[industry["in_date"].le(asof) & (industry["out_date"].isna() | industry["out_date"].ge(asof))].copy()
    counts = applicable.groupby("ts_code").size()
    applicable = applicable.loc[applicable["ts_code"].isin(counts[counts.eq(1)].index), ["ts_code", "l1_code", "l1_name"]]
    current = current.drop(columns=[field for field in ("l1_code", "l1_name") if field in current]).merge(applicable, on="ts_code", how="left")
    current = current.loc[~current["l1_code"].isin(FINANCIAL_L1_CODES)].copy()
    month_size = size.loc[size["asof_date"].eq(asof), ["ts_code", "size_control"]]
    return current.merge(month_size, on="ts_code", how="left")


def load_stage_labels(snapshots: dict[pd.Timestamp, pd.DataFrame], calendar: pd.DatetimeIndex, stage_start: pd.Timestamp) -> dict[pd.Timestamp, pd.DataFrame]:
    """Load only one stage's open prices through its final required label."""
    dates = sorted(snapshots)
    instruments = sorted({qlib_symbol(code) for frame in snapshots.values() for code in frame["ts_code"]})
    if not instruments:
        return snapshots
    last_label_date = max(calendar[calendar.get_loc(date) + max(HORIZONS)] for date in dates)
    open_data = D.features(instruments, ["$open"], start_time=stage_start, end_time=last_label_date, freq="day")
    open_data = open_data.rename(columns={"$open": "open"}).reset_index()
    open_data["ts_code"] = open_data["instrument"].map(lambda symbol: f"{symbol[2:]}.{symbol[:2]}")
    opens = open_data.pivot(index="datetime", columns="ts_code", values="open").reindex(calendar)
    labeled: dict[pd.Timestamp, pd.DataFrame] = {}
    for date, snapshot in snapshots.items():
        row = snapshot.copy()
        position = calendar.get_loc(date)
        entry = opens.loc[date].reindex(row["ts_code"]).to_numpy(dtype=float)
        for horizon in HORIZONS:
            exit_ = opens.iloc[position + horizon].reindex(row["ts_code"]).to_numpy(dtype=float)
            label = exit_ / entry - 1.0
            label[(entry <= 0) | (exit_ <= 0) | ~np.isfinite(label)] = np.nan
            row[f"label_{horizon}"] = label
        labeled[date] = row
    return labeled


def score_values(frame: pd.DataFrame) -> dict[str, pd.Series]:
    return {
        MAIN_SCORE: -pd.to_numeric(frame["working_capital_deterioration"], errors="coerce"),
        "receivable_quality": -pd.to_numeric(frame["receivable_deterioration"], errors="coerce"),
        "inventory_quality": -pd.to_numeric(frame["inventory_deterioration"], errors="coerce"),
    }


def analyze(labeled: dict[pd.Timestamp, pd.DataFrame], stage: str) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    monthly, groups, coverage, layers, industry_rows = [], [], [], [], []
    for date, source in labeled.items():
        for score_name, values in score_values(source).items():
            for horizon in HORIZONS:
                sample = source.assign(score=values).replace([np.inf, -np.inf], np.nan).dropna(subset=["score", "l1_code", "size_control", f"label_{horizon}"]).copy()
                if len(sample) < 100:
                    coverage.append({"stage": stage, "rebalance_date": date, "score": score_name, "horizon": horizon, "complete_sample": len(sample), "valid": False})
                    continue
                residual = ols_residual(sample["score"], sample["l1_code"], sample["size_control"])
                label = sample[f"label_{horizon}"]
                monthly.append({"stage": stage, "rebalance_date": date, "score": score_name, "horizon": horizon, "complete_sample": len(sample), "raw_rank_ic": spearman(sample["score"], label), "neutral_rank_ic": spearman(residual, label)})
                coverage.append({"stage": stage, "rebalance_date": date, "score": score_name, "horizon": horizon, "complete_sample": len(sample), "valid": True})
                for version, group_score in (("raw", sample["score"]), ("neutral", residual)):
                    working = sample.assign(_score=group_score)
                    working["_group"] = pd.qcut(working["_score"].rank(method="first"), 5, labels=False) + 1
                    means = working.groupby("_group", observed=True)[f"label_{horizon}"].mean().reindex(range(1, 6))
                    groups.append({"stage": stage, "rebalance_date": date, "score": score_name, "horizon": horizon, "version": version, "q1": means.iloc[0], "q2": means.iloc[1], "q3": means.iloc[2], "q4": means.iloc[3], "q5": means.iloc[4], "q5_minus_q1": means.iloc[4] - means.iloc[0], "monotonicity": float(means.diff().dropna().ge(0).mean())})
                if score_name == MAIN_SCORE and horizon == 40:
                    sized = sample.assign(residual=residual)
                    sized["size_layer"] = pd.qcut(sized["size_control"].rank(method="first"), 5, labels=False) + 1
                    for layer, part in sized.groupby("size_layer", observed=True):
                        layers.append({"stage": stage, "rebalance_date": date, "size_layer": f"S{layer}", "complete_sample": len(part), "raw_rank_ic": spearman(part["score"], part["label_40"]), "neutral_rank_ic": spearman(part["residual"], part["label_40"])})
                    for code, part in sized.groupby("l1_code", observed=True):
                        if len(part) >= 10:
                            industry_rows.append({"stage": stage, "rebalance_date": date, "l1_code": code, "complete_sample": len(part), "raw_rank_ic": spearman(part["score"], part["label_40"])})
    return (pd.DataFrame(monthly), pd.DataFrame(groups), pd.DataFrame(coverage), pd.DataFrame(layers), pd.DataFrame(industry_rows))


def summarize_ic(monthly: pd.DataFrame, stage: str) -> pd.DataFrame:
    rows = []
    for (score, horizon), group in monthly.groupby(["score", "horizon"], observed=True):
        row = {"stage": stage, "score": score, "horizon": horizon}
        for field in ("raw_rank_ic", "neutral_rank_ic"):
            values = group[field].dropna()
            std = values.std(ddof=1) if len(values) > 1 else np.nan
            row[field] = values.mean()
            row[f"{field}_icir"] = values.mean() / std if pd.notna(std) and std != 0 else np.nan
            row[f"{field}_positive_ratio"] = (values > 0).mean()
            row[f"{field}_months"] = len(values)
        rows.append(row)
    return pd.DataFrame(rows)


def main() -> None:
    root = Path(__file__).resolve().parents[1]
    output = root / "output/analysis_fundamental/a_share_working_capital_quality_single_factor_v1"
    protocol = root / "research/protocols/a_share_working_capital_quality_single_factor_validation_protocol_v1.md"
    event_path = root / "data/derived/a_share_working_capital_quality_event_v1/event_panel.csv.gz"
    grid_path = root / "data/external/tushare/a_share_style_pit_v1/normalized/monthly_rebalance_grid.csv.gz"
    industry_path = root / "data/external/tushare/a_share_style_pit_v1/normalized/industry_l1_effective_intervals.csv.gz"
    size_path = root / "data/external/tushare/a_share_style_pit_v1/normalized/monthly_free_float_size.csv.gz"
    qlib_dir = "/root/.qlib/qlib_data/cn_data_2026"
    qlib.init(provider_uri=qlib_dir, region=REG_CN)
    calendar = pd.DatetimeIndex(pd.to_datetime(D.calendar(start_time=DEVELOPMENT_START, end_time="2020-04-30", freq="day")))
    events = pd.read_csv(event_path, compression="gzip", parse_dates=["available_date", "effective_date", "expiry_date"])
    grid = pd.read_csv(grid_path, compression="gzip", parse_dates=["rebalance_date", "asof_date"])
    grid = grid.loc[grid["rebalance_date"].between(DEVELOPMENT_START, DEVELOPMENT_END)].copy()
    industry = pd.read_csv(industry_path, compression="gzip", dtype=str)
    industry["in_date"] = pd.to_datetime(industry["in_date"], errors="coerce")
    industry["out_date"] = pd.to_datetime(industry["out_date"], errors="coerce")
    size = pd.read_csv(size_path, compression="gzip", dtype=str)
    size["asof_date"] = pd.to_datetime(size["asof_date"], errors="coerce")
    size["size_control"] = pd.to_numeric(size["size_control"], errors="coerce")
    snapshots = {row.rebalance_date: attach_monthly_controls(events, row, industry, size) for _, row in grid.iterrows()}
    print(f"development_months={len(snapshots)}", flush=True)
    labeled = load_stage_labels(snapshots, calendar, DEVELOPMENT_START)
    monthly, groups, coverage, layers, industries = analyze(labeled, "development")
    summary = summarize_ic(monthly, "development")
    main = summary.loc[(summary["score"].eq(MAIN_SCORE)) & (summary["horizon"].eq(40))].iloc[0]
    main_horizons = summary.loc[summary["score"].eq(MAIN_SCORE)].set_index("horizon")
    group_mean = groups.loc[(groups["score"].eq(MAIN_SCORE)) & (groups["horizon"].eq(40)) & (groups["version"].eq("neutral")), "q5_minus_q1"].mean()
    passed = bool(main["neutral_rank_ic"] >= 0.01 and (main_horizons["neutral_rank_ic"] > 0).all() and group_mean >= 0 and main["neutral_rank_ic_icir"] >= 0.20)
    status = "development_candidate" if passed else "hypothesis_not_supported_in_development"
    decision = {"protocol": str(protocol.relative_to(root)), "protocol_sha256": sha256_file(protocol), "stage_read": "development_only", "development_months": len(grid), "development_passed": passed, "main_score": MAIN_SCORE, "main_40d_neutral_rank_ic": float(main["neutral_rank_ic"]), "main_40d_neutral_rank_icir": float(main["neutral_rank_ic_icir"]), "main_40d_neutral_q5_minus_q1": float(group_mean), "status": status, "confirmation_or_holdout_prices_read": False}
    atomic_csv(monthly, output / "development_monthly_rank_ic.csv.gz")
    atomic_csv(summary, output / "development_rank_ic_summary.csv")
    atomic_csv(groups, output / "development_group_return_summary.csv")
    atomic_csv(layers, output / "development_size_layer_summary.csv")
    atomic_csv(industries, output / "development_industry_distribution_summary.csv")
    atomic_csv(coverage, output / "development_sample_coverage_summary.csv")
    atomic_json(decision, output / "decision.json")
    atomic_json({"stage_read": "development_only", "label": "open(t+H)/open(t)-1", "horizons": list(HORIZONS), "main_score": MAIN_SCORE, "qlib_data_dir": qlib_dir, "event_panel_sha256": sha256_file(event_path), "protocol_sha256": sha256_file(protocol), "no_model_or_backtest": True}, output / "methodology.json")
    report = (
        "沪深非金融 A 股营运资本质量单因子开发期检验 v1\n"
        f"status: {status}\ndevelopment_months: {len(grid)}\n"
        f"main_40d_neutral_rank_ic: {main['neutral_rank_ic']:.6f}\n"
        f"main_40d_neutral_rank_icir: {main['neutral_rank_ic_icir']:.6f}\n"
        f"main_40d_neutral_q5_minus_q1: {group_mean:.6f}\n"
        "confirmation_or_holdout_prices_read: False\n"
        "未训练模型、未运行回测。\n"
    )
    (output / "validation_report.txt").write_text(report, encoding="utf-8")
    print(report, end="")


if __name__ == "__main__":
    main()
