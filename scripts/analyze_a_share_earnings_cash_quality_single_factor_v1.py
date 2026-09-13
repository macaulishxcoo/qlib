#!/usr/bin/env python3
"""Run the frozen staged validation for the earnings/cash-quality hypothesis.

The validator reads Qlib open prices only for the first stage initially.  It
returns before touching confirmation or holdout prices if development does not
meet the protocol's predeclared gate.  It never trains a model or backtests.
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


STAGES = {
    "development": (pd.Timestamp("2014-01-01"), pd.Timestamp("2019-12-31")),
    "confirmation": (pd.Timestamp("2020-01-01"), pd.Timestamp("2022-12-31")),
    "holdout": (pd.Timestamp("2023-01-01"), pd.Timestamp("2025-06-30")),
}
HORIZONS = (20, 40, 60)
SCORES = ("profit_yoy", "revenue_yoy", "cash_support", "earnings_revenue_cash_quality_2of5")
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
    """Residualize a score with an intercept, log-size, and one-hot industries."""
    dummies = pd.get_dummies(industry, dtype=float)
    if dummies.shape[1] > 0:
        dummies = dummies.iloc[:, 1:]
    design = np.column_stack([np.ones(len(score)), size.to_numpy(dtype=float), dummies.to_numpy(dtype=float)])
    beta, *_ = np.linalg.lstsq(design, score.to_numpy(dtype=float), rcond=None)
    return pd.Series(score.to_numpy(dtype=float) - design @ beta, index=score.index)


def stage_months(grid: pd.DataFrame, stage: str) -> pd.DataFrame:
    start, end = STAGES[stage]
    return grid[grid["rebalance_date"].between(start, end)].copy()


def active_snapshot(events: pd.DataFrame, grid_row: pd.Series, industry: pd.DataFrame, size: pd.DataFrame) -> pd.DataFrame:
    date = grid_row.rebalance_date
    current = events[events["effective_date"].le(date) & events["expiry_date"].ge(date)].copy()
    current = current.sort_values(["ts_code", "effective_date", "available_date"], kind="mergesort").drop_duplicates("ts_code", keep="last")
    if current.empty:
        return current
    # Replace announcement-date industry with the frozen monthly as-of mapping.
    current = current.drop(columns=[column for column in ("l1_code", "l1_name") if column in current])
    asof = grid_row.asof_date
    applicable = industry[industry["in_date"].le(asof) & (industry["out_date"].isna() | industry["out_date"].ge(asof))]
    industry_counts = applicable.groupby("ts_code").size()
    applicable = applicable[applicable["ts_code"].isin(industry_counts[industry_counts.eq(1)].index)][["ts_code", "l1_code", "l1_name"]]
    current = current.merge(applicable, on="ts_code", how="left")
    current = current[~current["l1_code"].isin(FINANCIAL_L1_CODES)].copy()
    current = current.merge(size[size["asof_date"].eq(asof)][["ts_code", "size_control"]], on="ts_code", how="left")
    return current


def fetch_labels(snapshots: dict[pd.Timestamp, pd.DataFrame], calendar: pd.DatetimeIndex, stage: str) -> dict[pd.Timestamp, pd.DataFrame]:
    """Read only the exact stage's open prices and map fixed open-to-open labels."""
    months = sorted(snapshots)
    codes = sorted({qlib_symbol(code) for frame in snapshots.values() for code in frame["ts_code"]})
    if not codes:
        return {date: frame.assign(**{f"label_{h}": np.nan for h in HORIZONS}) for date, frame in snapshots.items()}
    max_end = max(calendar[calendar.get_loc(date) + max(HORIZONS)] for date in months if calendar.get_loc(date) + max(HORIZONS) < len(calendar))
    start, _ = STAGES[stage]
    open_frame = D.features(codes, ["$open"], start_time=start, end_time=max_end, freq="day").rename(columns={"$open": "open"}).reset_index()
    open_frame["ts_code"] = open_frame["instrument"].map(lambda symbol: f"{symbol[2:]}.{symbol[:2]}")
    open_pivot = open_frame.pivot(index="datetime", columns="ts_code", values="open").reindex(calendar)
    result = {}
    for date, frame in snapshots.items():
        position = calendar.get_loc(date)
        item = frame.copy()
        for horizon in HORIZONS:
            if position + horizon >= len(calendar):
                item[f"label_{horizon}"] = np.nan
                continue
            entry = open_pivot.loc[date].reindex(item["ts_code"]).to_numpy(dtype=float)
            exit_ = open_pivot.iloc[position + horizon].reindex(item["ts_code"]).to_numpy(dtype=float)
            label = exit_ / entry - 1.0
            label[(entry <= 0) | (exit_ <= 0) | ~np.isfinite(label)] = np.nan
            item[f"label_{horizon}"] = label
        result[date] = item
    return result


def score_series(frame: pd.DataFrame, score: str) -> pd.Series:
    if score == "profit_yoy": return frame["profit_yoy_clipped"]
    if score == "revenue_yoy": return frame["revenue_yoy_clipped"]
    if score == "cash_support": return frame["cash_support_flag"].astype(float)
    return ((frame["profit_yoy_clipped"].rank(method="first", pct=True).ge(.6)) & (frame["revenue_yoy_clipped"].rank(method="first", pct=True).ge(.6)) & frame["cash_support_flag"].eq(True)).astype(float)


def analyze_stage(snapshots: dict[pd.Timestamp, pd.DataFrame], stage: str) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    monthly_ic, groups, coverage, layers = [], [], [], []
    for date, source in snapshots.items():
        for score_name in SCORES:
            score = score_series(source, score_name)
            for horizon in HORIZONS:
                sample = source.assign(score=score).dropna(subset=["score", "l1_code", "size_control", f"label_{horizon}"]).copy()
                if len(sample) < 100:
                    coverage.append({"stage": stage, "rebalance_date": date, "score": score_name, "horizon": horizon, "complete_sample": len(sample), "valid": False})
                    continue
                residual = ols_residual(sample["score"], sample["l1_code"], sample["size_control"])
                label = sample[f"label_{horizon}"]
                raw_ic, neutral_ic = spearman(sample["score"], label), spearman(residual, label)
                monthly_ic.append({"stage": stage, "rebalance_date": date, "score": score_name, "horizon": horizon, "complete_sample": len(sample), "raw_rank_ic": raw_ic, "neutral_rank_ic": neutral_ic})
                coverage.append({"stage": stage, "rebalance_date": date, "score": score_name, "horizon": horizon, "complete_sample": len(sample), "valid": True})
                for name, values in [("raw", sample["score"]), ("neutral", residual)]:
                    item = sample.assign(_score=values)
                    if score_name in ("cash_support", "earnings_revenue_cash_quality_2of5"):
                        mean_one = item.loc[item._score.gt(0), f"label_{horizon}"].mean()
                        mean_zero = item.loc[item._score.le(0), f"label_{horizon}"].mean()
                        groups.append({"stage": stage, "rebalance_date": date, "score": score_name, "horizon": horizon, "version": name, "group_type": "binary", "high_minus_low": mean_one - mean_zero, "monotonicity": np.nan})
                    else:
                        item["_group"] = pd.qcut(item._score.rank(method="first"), 5, labels=False) + 1
                        means = item.groupby("_group", observed=True)[f"label_{horizon}"].mean().reindex(range(1, 6))
                        groups.append({"stage": stage, "rebalance_date": date, "score": score_name, "horizon": horizon, "version": name, "group_type": "quintile", "high_minus_low": means.iloc[-1] - means.iloc[0], "monotonicity": float((means.diff().dropna().ge(0)).mean())})
                if score_name == "earnings_revenue_cash_quality_2of5" and horizon == 40:
                    item = sample.assign(residual=residual)
                    item["size_layer"] = pd.qcut(item["size_control"].rank(method="first"), 5, labels=False) + 1
                    for layer, group in item.groupby("size_layer", observed=True):
                        layers.append({"stage": stage, "rebalance_date": date, "size_layer": f"S{layer}", "complete_sample": len(group), "raw_rank_ic": spearman(group["score"], group[f"label_{horizon}"]), "neutral_rank_ic": spearman(group["residual"], group[f"label_{horizon}"])})
    return pd.DataFrame(monthly_ic), pd.DataFrame(groups), pd.DataFrame(coverage), pd.DataFrame(layers)


def summarize_ic(monthly_ic: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for keys, group in monthly_ic.groupby(["stage", "score", "horizon"], observed=True):
        row = dict(zip(["stage", "score", "horizon"], keys))
        for column in ("raw_rank_ic", "neutral_rank_ic"):
            values = group[column].dropna()
            row[column] = values.mean()
            row[f"{column}_icir"] = values.mean() / values.std(ddof=1) if len(values) > 1 and values.std(ddof=1) else np.nan
            row[f"{column}_positive_ratio"] = (values > 0).mean()
            row[f"{column}_months"] = len(values)
        rows.append(row)
    return pd.DataFrame(rows)


def main() -> None:
    # This script lives directly in scripts/, unlike data_collector scripts.
    root = Path(__file__).resolve().parents[1]
    output = root / "output/analysis_fundamental/a_share_earnings_cash_quality_single_factor_v1"
    event_path = root / "data/derived/a_share_earnings_cash_quality_event_v1/event_panel.csv.gz"
    grid_path = root / "data/external/tushare/a_share_style_pit_v1/normalized/monthly_rebalance_grid.csv.gz"
    industry_path = root / "data/external/tushare/a_share_style_pit_v1/normalized/industry_l1_effective_intervals.csv.gz"
    size_path = root / "data/external/tushare/a_share_style_pit_v1/normalized/monthly_free_float_size.csv.gz"
    qlib_dir = "/root/.qlib/qlib_data/cn_data_2026"
    qlib.init(provider_uri=qlib_dir, region=REG_CN)
    calendar = pd.DatetimeIndex(pd.to_datetime(D.calendar(start_time="2014-01-01", end_time="2025-12-31", freq="day")))
    events = pd.read_csv(event_path, compression="gzip", parse_dates=["available_date", "effective_date", "expiry_date"])
    grid = pd.read_csv(grid_path, compression="gzip", parse_dates=["rebalance_date", "asof_date"])
    industry = pd.read_csv(industry_path, compression="gzip", dtype=str)
    industry["in_date"] = pd.to_datetime(industry["in_date"], errors="coerce")
    industry["out_date"] = pd.to_datetime(industry["out_date"], errors="coerce")
    size = pd.read_csv(size_path, compression="gzip", dtype=str)
    size["asof_date"] = pd.to_datetime(size["asof_date"], errors="coerce")
    size["size_control"] = pd.to_numeric(size["size_control"], errors="coerce")
    all_outputs = []
    decision = {"protocol": str((root / "research/protocols/a_share_earnings_cash_quality_single_factor_validation_protocol_v1.md").relative_to(root)), "protocol_sha256": sha256_file(root / "research/protocols/a_share_earnings_cash_quality_single_factor_validation_protocol_v1.md"), "stages_read": []}
    for stage in ("development", "confirmation", "holdout"):
        stage_grid = stage_months(grid, stage)
        snapshots = {row.rebalance_date: active_snapshot(events, row, industry, size) for _, row in stage_grid.iterrows()}
        print(f"{stage}: snapshots={len(snapshots)}", flush=True)
        labeled = fetch_labels(snapshots, calendar, stage)
        monthly_ic, groups, coverage, layers = analyze_stage(labeled, stage)
        summary = summarize_ic(monthly_ic)
        all_outputs.append((monthly_ic, groups, coverage, layers, summary))
        decision["stages_read"].append(stage)
        main_row = summary[(summary.score.eq("earnings_revenue_cash_quality_2of5")) & (summary.horizon.eq(40))].iloc[0]
        group_mean = groups[(groups.score.eq("earnings_revenue_cash_quality_2of5")) & (groups.horizon.eq(40)) & (groups.version.eq("neutral"))]["high_minus_low"].mean()
        if stage == "development":
            passed = bool(main_row.neutral_rank_ic >= .01 and summary[(summary.score.eq("earnings_revenue_cash_quality_2of5"))]["neutral_rank_ic"].gt(0).all() and group_mean >= 0 and main_row.neutral_rank_ic_icir >= .20)
        elif stage == "confirmation":
            layer_summary = layers.groupby("size_layer", observed=True)["neutral_rank_ic"].mean()
            passed = bool(main_row.neutral_rank_ic >= .01 and summary[(summary.score.eq("earnings_revenue_cash_quality_2of5"))]["neutral_rank_ic"].gt(0).all() and group_mean >= 0 and (layer_summary > 0).sum() >= 3 and layer_summary.drop(index="S1", errors="ignore").mean() > 0)
        else:
            passed = bool(main_row.neutral_rank_ic > 0 and not (summary[(summary.score.eq("earnings_revenue_cash_quality_2of5")) & (summary.horizon.isin([20,60]))]["neutral_rank_ic"] < 0).all() and group_mean >= 0)
        decision[f"{stage}_passed"] = passed
        decision[f"{stage}_main_40d_neutral_rank_ic"] = float(main_row.neutral_rank_ic)
        if not passed:
            decision["status"] = "hypothesis_not_supported_in_development" if stage == "development" else ("hypothesis_not_supported" if stage == "confirmation" else "not_replicated")
            break
    frames = [item[0] for item in all_outputs]; group_frames = [item[1] for item in all_outputs]; coverage_frames = [item[2] for item in all_outputs]; layer_frames = [item[3] for item in all_outputs]; summary_frames = [item[4] for item in all_outputs]
    monthly = pd.concat(frames, ignore_index=True); groups = pd.concat(group_frames, ignore_index=True); coverage = pd.concat(coverage_frames, ignore_index=True); layers = pd.concat(layer_frames, ignore_index=True); summary = pd.concat(summary_frames, ignore_index=True)
    atomic_csv(monthly, output / "monthly_rank_ic.csv.gz")
    atomic_csv(summary, output / "rank_ic_summary.csv")
    atomic_csv(groups, output / "group_return_summary.csv")
    atomic_csv(layers, output / "size_layer_summary.csv")
    atomic_csv(coverage, output / "sample_coverage_summary.csv")
    atomic_json(decision, output / "decision.json")
    atomic_json({"label": "open(t+H)/open(t)-1", "horizons": list(HORIZONS), "qlib_data_dir": qlib_dir, "stages_read": decision["stages_read"], "score_names": list(SCORES), "no_model_or_backtest": True}, output / "methodology.json")
    report = f"财务单因子有效性检验 v1\nstatus: {decision.get('status', 'replicated_for_strategy_design')}\nstages_read: {','.join(decision['stages_read'])}\n未训练模型、未运行回测。\n"
    (output / "validation_report.txt").write_text(report, encoding="utf-8")
    print(report, end="")


if __name__ == "__main__":
    main()
