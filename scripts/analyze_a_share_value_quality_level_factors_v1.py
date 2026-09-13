#!/usr/bin/env python3
"""Run the frozen staged validation for value & earnings-quality LEVEL factors.

Level factors (E/P, CFO/NI, leverage) differ from the closed YoY-change
hypotheses.  The validator reads Qlib open prices stage by stage, returns
before touching later-stage prices if the development gate fails, and never
trains a model or backtests.

Protocol: research/protocols/a_share_value_quality_level_factors_validation_protocol_v1.md
Proposal: research/decisions/a_share_value_quality_level_factors_proposal_v1.md
"""

from __future__ import annotations

import argparse
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
    "holdout": (pd.Timestamp("2023-01-01"), pd.Timestamp("2025-05-30")),
}
HORIZONS = (20, 40, 60)
SCORES = ("ep", "cfo_ni", "lev")
FINANCIAL_L1_CODES = {"801780.SI", "801790.SI"}  # 银行、非银金融
ROOT = Path(__file__).resolve().parents[1]
FIN_BASE = ROOT / "data/external/tushare/a_share_financial_pit_v1/full/normalized"
STYLE_DIR = ROOT / "data/external/tushare/a_share_style_pit_v1/normalized"
QLIB_DIR = Path.home() / ".qlib/qlib_data/cn_data_2026"


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


def load_financials() -> pd.DataFrame:
    """Load fina_indicator/cashflow/income PIT records into one long frame.

    Returns columns:
      ts_code, end_date, available_date, profit_dedt, n_cashflow_act,
      n_income, roe, debt_to_assets
    """
    frames = []
    for batch in sorted(FIN_BASE.glob("batch_*")):
        path = batch / "fina_indicator.csv.gz"
        if not path.exists():
            continue
        frame = pd.read_csv(
            path,
            compression="gzip",
            usecols=["ts_code", "end_date", "available_date", "profit_dedt", "roe", "debt_to_assets"],
        )
        frames.append(frame)
    fin = pd.concat(frames, ignore_index=True)

    cash_frames = []
    for batch in sorted(FIN_BASE.glob("batch_*")):
        path = batch / "cashflow.csv.gz"
        if not path.exists():
            continue
        frame = pd.read_csv(
            path,
            compression="gzip",
            usecols=["ts_code", "end_date", "available_date", "n_cashflow_act"],
        )
        cash_frames.append(frame)
    cash = pd.concat(cash_frames, ignore_index=True)

    income_frames = []
    for batch in sorted(FIN_BASE.glob("batch_*")):
        path = batch / "income.csv.gz"
        if not path.exists():
            continue
        frame = pd.read_csv(
            path,
            compression="gzip",
            usecols=["ts_code", "end_date", "available_date", "n_income_attr_p"],
        )
        income_frames.append(frame)
    income = pd.concat(income_frames, ignore_index=True)

    for frame in (fin, cash, income):
        frame["end_date"] = pd.to_datetime(frame["end_date"], format="%Y%m%d", errors="coerce")
        frame["available_date"] = pd.to_datetime(frame["available_date"], errors="coerce")

    result = fin.merge(
        cash[["ts_code", "end_date", "available_date", "n_cashflow_act"]],
        on=["ts_code", "end_date", "available_date"],
        how="left",
    ).merge(
        income[["ts_code", "end_date", "available_date", "n_income_attr_p"]],
        on=["ts_code", "end_date", "available_date"],
        how="left",
    )
    return result


def ttm_value(frame: pd.DataFrame, value_col: str) -> pd.Series:
    """Compute TTM for a cumulative value column at each stock's latest report period.

    TTM = latest cumulative - same period last year + last year annual.
    When the latest period is an annual report, same-period-last-year equals
    last-year-annual, so TTM collapses to the annual value.
    """
    result = {}
    for ts_code, group in frame.groupby("ts_code"):
        latest_end = group["end_date"].max()
        yoy_end = latest_end - pd.DateOffset(years=1)
        prior_end = pd.Timestamp(f"{latest_end.year - 1}-12-31")
        latest = group.loc[group["end_date"].eq(latest_end), value_col].dropna()
        yoy = group.loc[group["end_date"].eq(yoy_end), value_col].dropna()
        prior = group.loc[group["end_date"].eq(prior_end), value_col].dropna()
        if latest.empty or yoy.empty or prior.empty:
            continue
        result[ts_code] = float(latest.iloc[0] - yoy.iloc[0] + prior.iloc[0])
    return pd.Series(result)


def build_snapshot(fin: pd.DataFrame, grid_row: pd.Series, industry: pd.DataFrame, size: pd.DataFrame) -> pd.DataFrame:
    """Build the month-end cross-sectional level-factor snapshot at one rebalance date."""
    date = grid_row.rebalance_date
    asof = grid_row.asof_date

    # PIT: only records disclosed on/before the signal date.
    current = fin[fin["available_date"].le(date)].copy()

    # Dedupe revision versions: latest available_date per (ts_code, end_date).
    current = current.sort_values(["ts_code", "end_date", "available_date"], kind="mergesort").drop_duplicates(
        ["ts_code", "end_date"], keep="last"
    )
    if current.empty:
        return current

    ep_ttm = ttm_value(current, "profit_dedt")
    cfo_ttm = ttm_value(current, "n_cashflow_act")
    ni_ttm = ttm_value(current, "n_income_attr_p")

    latest = current.sort_values(["ts_code", "end_date"], kind="mergesort").drop_duplicates("ts_code", keep="last").copy()
    latest = latest.set_index("ts_code")

    result = pd.DataFrame(index=latest.index)
    # total_mv 单位是万元，profit_dedt 单位是元；统一为元后再取比值。
    total_mv_yuan = size[size["asof_date"].eq(asof)].set_index("ts_code")["total_mv"].reindex(latest.index) * 1e4
    result["ep"] = ep_ttm.reindex(latest.index) / total_mv_yuan
    result["cfo_ni"] = cfo_ttm.reindex(latest.index) / ni_ttm.reindex(latest.index)
    result["lev"] = latest["debt_to_assets"]

    # Economic-domain constraints documented in the protocol.
    result.loc[result["ep"].le(0), "ep"] = np.nan            # E/P meaningful only for profitable TTM
    result.loc[ni_ttm.reindex(latest.index).le(0), "cfo_ni"] = np.nan  # CFO/NI meaningful only for positive net income

    # Industry (as-of), drop financials.
    applicable = industry[industry["in_date"].le(asof) & (industry["out_date"].isna() | industry["out_date"].ge(asof))]
    counts = applicable.groupby("ts_code").size()
    applicable = applicable[applicable["ts_code"].isin(counts[counts.eq(1)].index)][["ts_code", "l1_code", "l1_name"]]
    result = result.reset_index().merge(applicable, on="ts_code", how="left").set_index("ts_code")
    result = result[~result["l1_code"].isin(FINANCIAL_L1_CODES)].copy()

    # Size layer.
    size_layer = size[size["asof_date"].eq(asof)].set_index("ts_code")
    result["size_control"] = size_layer["size_control"].reindex(result.index)
    result["total_mv"] = size_layer["total_mv"].reindex(result.index)
    result["log_size"] = np.log(result["total_mv"])
    return result.reset_index()


def qlib_symbol(code: str) -> str:
    """'600519.SH' -> 'SH600519'"""
    number, suffix = code.split(".")
    return f"{suffix}{number}"


def spearman(left: pd.Series, right: pd.Series) -> float:
    if len(left) < 2 or left.nunique(dropna=True) < 2 or right.nunique(dropna=True) < 2:
        return np.nan
    return float(left.corr(right, method="spearman"))


def ols_residual(score: pd.Series, industry: pd.Series, size: pd.Series) -> pd.Series:
    dummies = pd.get_dummies(industry, dtype=float)
    if dummies.shape[1] > 0:
        dummies = dummies.iloc[:, 1:]
    design = np.column_stack([np.ones(len(score)), size.to_numpy(dtype=float), dummies.to_numpy(dtype=float)])
    beta, *_ = np.linalg.lstsq(design, score.to_numpy(dtype=float), rcond=None)
    return pd.Series(score.to_numpy(dtype=float) - design @ beta, index=score.index)


def stage_months(grid: pd.DataFrame, stage: str) -> pd.DataFrame:
    start, end = STAGES[stage]
    return grid[grid["rebalance_date"].between(start, end)].copy()


def fetch_labels(snapshots: dict[pd.Timestamp, pd.DataFrame], calendar: pd.DatetimeIndex, stage: str) -> dict[pd.Timestamp, pd.DataFrame]:
    months = sorted(snapshots)
    codes = sorted({qlib_symbol(code) for frame in snapshots.values() for code in frame["ts_code"]})
    if not codes:
        return {date: frame.assign(**{f"label_{h}": np.nan for h in HORIZONS}) for date, frame in snapshots.items()}
    max_end = max(
        calendar[calendar.get_loc(date) + max(HORIZONS)]
        for date in months
        if calendar.get_loc(date) + max(HORIZONS) < len(calendar)
    )
    start, _ = STAGES[stage]
    open_frame = (
        D.features(codes, ["$open"], start_time=start, end_time=max_end, freq="day")
        .rename(columns={"$open": "open"})
        .reset_index()
    )
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


def analyze_stage(snapshots: dict[pd.Timestamp, pd.DataFrame], stage: str) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    monthly_ic, groups, coverage, layers = [], [], [], []
    for date, source in snapshots.items():
        for score_name in SCORES:
            score = source[score_name]
            for horizon in HORIZONS:
                sample = source.assign(score=score).dropna(subset=["score", "l1_code", "size_control", f"label_{horizon}"]).copy()
                if len(sample) < 100:
                    coverage.append({"stage": stage, "rebalance_date": date, "score": score_name, "horizon": horizon, "complete_sample": len(sample), "valid": False})
                    continue
                residual = ols_residual(sample["score"], sample["l1_code"], sample["log_size"])
                label = sample[f"label_{horizon}"]
                raw_ic, neutral_ic = spearman(sample["score"], label), spearman(residual, label)
                monthly_ic.append({"stage": stage, "rebalance_date": date, "score": score_name, "horizon": horizon, "complete_sample": len(sample), "raw_rank_ic": raw_ic, "neutral_rank_ic": neutral_ic})
                coverage.append({"stage": stage, "rebalance_date": date, "score": score_name, "horizon": horizon, "complete_sample": len(sample), "valid": True})
                for name, values in [("raw", sample["score"]), ("neutral", residual)]:
                    item = sample.assign(_score=values)
                    item["_group"] = pd.qcut(item._score.rank(method="first"), 5, labels=False) + 1
                    means = item.groupby("_group", observed=True)[f"label_{horizon}"].mean().reindex(range(1, 6))
                    groups.append({"stage": stage, "rebalance_date": date, "score": score_name, "horizon": horizon, "version": name, "group_type": "quintile", "high_minus_low": means.iloc[-1] - means.iloc[0], "monotonicity": float((means.diff().dropna().ge(0)).mean())})
                if score_name in ("ep", "cfo_ni") and horizon == 40:
                    item = sample.assign(residual=residual)
                    item["size_layer"] = pd.qcut(item["size_control"].rank(method="first"), 5, labels=False) + 1
                    for layer, group in item.groupby("size_layer", observed=True):
                        layers.append({"stage": stage, "rebalance_date": date, "score": score_name, "size_layer": f"S{layer}", "complete_sample": len(group), "raw_rank_ic": spearman(group["score"], group[f"label_{horizon}"]), "neutral_rank_ic": spearman(group["residual"], group[f"label_{horizon}"])})
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
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, default=Path("output/analysis_fundamental/a_share_value_quality_level_factors_v1"))
    args = parser.parse_args()
    out = args.output_dir
    if out.exists() and any(out.iterdir()):
        raise FileExistsError(f"Refusing to overwrite existing experiment output: {out}")
    out.mkdir(parents=True, exist_ok=True)

    qlib.init(provider_uri=str(QLIB_DIR), region=REG_CN)
    calendar = pd.DatetimeIndex(pd.to_datetime(pd.read_csv(QLIB_DIR / "calendars" / "day.txt", header=None)[0]))

    print("[1/5] Loading financial PIT tables ...", flush=True)
    fin = load_financials()
    print(f"      fin rows={len(fin)}", flush=True)

    grid = pd.read_csv(STYLE_DIR / "monthly_rebalance_grid.csv.gz", compression="gzip", parse_dates=["rebalance_date", "asof_date"])
    industry = pd.read_csv(STYLE_DIR / "industry_l1_effective_intervals.csv.gz", compression="gzip", dtype=str)
    industry["in_date"] = pd.to_datetime(industry["in_date"], errors="coerce")
    industry["out_date"] = pd.to_datetime(industry["out_date"], errors="coerce")
    size = pd.read_csv(STYLE_DIR / "monthly_free_float_size.csv.gz", compression="gzip")
    size["asof_date"] = pd.to_datetime(size["asof_date"], errors="coerce")

    monthly_panels, monthly_ic_all, groups_all, coverage_all, layers_all = [], [], [], [], []
    stages_run = []
    for stage in ("development", "confirmation", "holdout"):
        stage_grid = stage_months(grid, stage)
        print(f"[{stage}] {len(stage_grid)} months", flush=True)
        snapshots = {row.rebalance_date: build_snapshot(fin, row, industry, size) for _, row in stage_grid.iterrows()}
        snapshots = fetch_labels(snapshots, calendar, stage)
        monthly_ic, groups, coverage, layers = analyze_stage(snapshots, stage)
        for date, frame in snapshots.items():
            frame = frame.copy()
            frame["stage"] = stage
            frame["rebalance_date"] = date
            monthly_panels.append(frame)
        monthly_ic_all.append(monthly_ic)
        groups_all.append(groups)
        coverage_all.append(coverage)
        layers_all.append(layers)
        stages_run.append(stage)
        summary = summarize_ic(monthly_ic)
        print(f"      dev gate check for stage {stage}:", flush=True)
        print(summary[summary["horizon"].eq(40)][["score", "neutral_rank_ic", "neutral_rank_ic_icir"]].to_string(index=False), flush=True)
        if stage == "development":
            ep_dev = summary[(summary["score"].eq("ep")) & (summary["horizon"].eq(40))]
            cfo_dev = summary[(summary["score"].eq("cfo_ni")) & (summary["horizon"].eq(40))]
            ep_pass = bool(len(ep_dev) and ep_dev["neutral_rank_ic"].iloc[0] > 0.01 and ep_dev["neutral_rank_ic_icir"].iloc[0] >= 0.20)
            cfo_pass = bool(len(cfo_dev) and cfo_dev["neutral_rank_ic"].iloc[0] > 0.01 and cfo_dev["neutral_rank_ic_icir"].iloc[0] >= 0.20)
            print(f"      development gate: ep={ep_pass}, cfo_ni={cfo_pass}", flush=True)

    panel = pd.concat(monthly_panels, ignore_index=True)
    monthly_ic = pd.concat(monthly_ic_all, ignore_index=True)
    groups = pd.concat(groups_all, ignore_index=True)
    coverage = pd.concat(coverage_all, ignore_index=True)
    layers = pd.concat(layers_all, ignore_index=True)

    atomic_csv(panel, out / "monthly_signal_label_panel.csv.gz")
    atomic_csv(monthly_ic, out / "monthly_rank_ic.csv.gz")
    atomic_csv(summarize_ic(monthly_ic), out / "rank_ic_summary.csv")
    atomic_csv(groups, out / "group_return_summary.csv")
    atomic_csv(layers, out / "size_layer_summary.csv")
    atomic_csv(coverage, out / "sample_coverage_summary.csv")

    summary = summarize_ic(monthly_ic)
    decision = {
        "development_ep": "not_reported",
        "development_cfo_ni": "not_reported",
        "confirmed_ep": "not_reported",
        "confirmed_cfo_ni": "not_reported",
    }
    for stage in ("development", "confirmation", "holdout"):
        for score in ("ep", "cfo_ni"):
            row = summary[(summary["stage"].eq(stage)) & (summary["score"].eq(score)) & (summary["horizon"].eq(40))]
            if row.empty:
                continue
            ic = float(row["neutral_rank_ic"].iloc[0])
            icir = float(row["neutral_rank_ic_icir"].iloc[0])
            key = f"{stage}_{score}"
            if stage == "development":
                decision[key] = "pass" if ic > 0.01 and icir >= 0.20 else "fail"
            elif stage == "confirmation" and decision[f"development_{score}"] == "pass":
                decision[key] = "confirmed" if ic > 0.01 else "fail"
            elif stage == "holdout" and decision[f"confirmation_{score}"] == "confirmed":
                decision[key] = "replicated" if ic > 0 else "not_replicated"
            else:
                decision[key] = "skipped"
    atomic_json(decision, out / "decision.json")

    methodology = {
        "protocol": "research/protocols/a_share_value_quality_level_factors_validation_protocol_v1.md",
        "qlib_data_dir": str(QLIB_DIR),
        "label": "open-to-open r_H(t) = open(t+H)/open(t)-1, H in {20,40,60}",
        "ttm_rule": "TTM = latest cumulative - same period last year + last year annual; annual reports collapse to annual value",
        "ep_denominator": "total_mv (month-end PIT)",
        "cfo_ni": "n_cashflow_act TTM / n_income_attr_p TTM, positive-income constraint",
        "economic_constraints": {"ep": ">0 only", "cfo_ni": "net income TTM > 0 only"},
        "financial_excluded_l1": sorted(FINANCIAL_L1_CODES),
        "stages": {k: [v[0].isoformat(), v[1].isoformat()] for k, v in STAGES.items()},
        "created_at_utc": pd.Timestamp.utcnow().isoformat(),
    }
    atomic_json(methodology, out / "methodology.json")
    print("done|", json.dumps(decision, ensure_ascii=False))


if __name__ == "__main__":
    import argparse

    main()
