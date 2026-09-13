#!/usr/bin/env python3
"""Run the frozen staged validation for the GROWTH-factor family (proposal v1).

Tests 8 pre-declared growth candidates + 1 control on the same staged
framework as the value/quality extension:

  A. pure growth levels
    g1_rev_yoy        or_yoy (operating revenue YoY)
    g2_dedt_np_yoy    dt_netprofit_yoy
    g3_q_rev_yoy      q_sales_yoy (single-quarter revenue YoY)
    g4_rd_intensity   rd_exp/revenue from income table (missing 2025+)
  B. growth quality
    g5_np_accel       dt_netprofit_yoy(t) - dt_netprofit_yoy(t-1)
    g6_rev_stability  -std(or_yoy, last 8 report periods, >=6)
    g7_rev_x_turnover or_yoy rank * turnover_rate_percentile (confirmation)
  C. domain-restricted
    g8_tech_growth    or_yoy rank within tech L1 {801080,801750,801770}
  control
    g0_tech_dummy     tech L1 membership (no ranking, raw IC only)

Gates (pre-registered in the proposal):
  dev pass:   ic40 > 0.01 and icir40 >= 0.20 and ic20>0 and ic60>0 (neutral)
  conf pass:  ic40 > 0.01
  holdout:    ic40 > 0
Neutralization: log_size + SW L1 industry dummies (same axis as v8).
G8 is ranked within-domain then scored on the full cross-section (domain
stocks only get in-domain ranks; non-tech get NaN => domain-restricted IC).

Protocol: research/protocols/a_share_growth_factor_family_protocol_v1.md
Proposal: research/decisions/a_share_growth_factor_family_proposal_v1.md
"""

from __future__ import annotations

import argparse
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
SCORES = ("g0_tech_dummy", "g1_rev_yoy", "g2_dedt_np_yoy", "g3_q_rev_yoy", "g4_rd_intensity",
          "g5_np_accel", "g6_rev_stability", "g7_rev_x_turnover", "g8_tech_growth")
FINANCIAL_L1_CODES = {"801780.SI", "801790.SI"}
TECH_L1_CODES = {"801080.SI", "801750.SI", "801770.SI"}  # 电子 / 计算机 / 通信
ROOT = Path(__file__).resolve().parents[1]
FIN_TOP = ROOT / "data/external/tushare/a_share_financial_pit_v1/normalized"
FIN_FULL = ROOT / "data/external/tushare/a_share_financial_pit_v1/full/normalized"
STYLE_DIR = ROOT / "data/external/tushare/a_share_style_pit_v1/normalized"
CLASS_V2 = ROOT / "data/derived/a_share_stock_classification_v2/monthly_stock_classification.csv.gz"
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


def load_growth_financials() -> pd.DataFrame:
    """fina_indicator (top merged + full batches, dedup) with YoY columns,
    plus rd_exp from income where available."""
    cols = ["ts_code", "end_date", "available_date", "or_yoy", "dt_netprofit_yoy",
            "q_sales_yoy", "netprofit_yoy"]
    frames = [pd.read_csv(FIN_TOP / "fina_indicator.csv.gz", compression="gzip", usecols=cols)]
    for batch in sorted(FIN_FULL.glob("batch_*")):
        path = batch / "fina_indicator.csv.gz"
        if path.exists():
            frames.append(pd.read_csv(path, compression="gzip", usecols=cols))
    fin = pd.concat(frames, ignore_index=True)
    # top-level file uses "2010-04-20", full batches use "20100420" -- parse both
    for col in ("end_date", "available_date"):
        fin[col] = pd.to_datetime(fin[col].astype(str).str.replace("-", "", regex=False),
                                  format="%Y%m%d", errors="coerce")
    fin = fin.drop_duplicates(["ts_code", "end_date", "available_date"], keep="last")

    # rd_exp (income table, full batches only)
    rd = []
    for batch in sorted(FIN_FULL.glob("batch_*")):
        path = batch / "income.csv.gz"
        if path.exists():
            try:
                rd.append(pd.read_csv(path, compression="gzip",
                                      usecols=["ts_code", "end_date", "available_date", "rd_exp", "revenue"]))
            except ValueError:
                continue
    if rd:
        rd = pd.concat(rd, ignore_index=True)
        for col in ("end_date", "available_date"):
            rd[col] = pd.to_datetime(rd[col].astype(str).str.replace("-", "", regex=False),
                                     format="%Y%m%d", errors="coerce")
        rd = rd.drop_duplicates(["ts_code", "end_date", "available_date"], keep="last")
        fin = fin.merge(rd[["ts_code", "end_date", "available_date", "rd_exp", "revenue"]],
                        on=["ts_code", "end_date", "available_date"], how="left")
    else:
        fin["rd_exp"] = np.nan
        fin["revenue"] = np.nan
    return fin


def build_snapshot(fin: pd.DataFrame, cls: pd.DataFrame, grid_row: pd.Series) -> pd.DataFrame:
    date = grid_row.rebalance_date
    asof = grid_row.asof_date

    # classification_v2 starts 2016-01; months before that have no as-of match.
    # For 2014/2015 dev months, fall back to the earliest classification month
    # is NOT PIT-safe -> those months are skipped (valid months = 2016-01 onward,
    # which still leaves 48 dev months 2016-2019).
    if not cls["asof_date"].eq(asof).any():
        return pd.DataFrame()

    current = fin[fin["available_date"].le(date)].copy()
    current = current.sort_values(["ts_code", "end_date", "available_date"], kind="mergesort") \
        .drop_duplicates(["ts_code", "end_date"], keep="last")
    if current.empty:
        return current

    # latest report per stock
    latest = current.sort_values(["ts_code", "end_date"], kind="mergesort") \
        .drop_duplicates("ts_code", keep="last").set_index("ts_code")

    # g5: previous report per stock (tail(2) of end_date-sorted frame, first of the pair)
    current_sorted = current.sort_values(["ts_code", "end_date"], kind="mergesort")
    prev_map = current_sorted.groupby("ts_code").tail(2).drop_duplicates("ts_code", keep="first").set_index("ts_code")
    prev_yoy = prev_map["dt_netprofit_yoy"]

    # g6: -std(or_yoy, last 8 reports, >=6 non-null)
    stab = {}
    for ts_code, group in current.groupby("ts_code"):
        vals = group["or_yoy"].dropna()
        if len(vals) >= 6:
            stab[ts_code] = -float(vals.tail(8).std(ddof=1))
    stability = pd.Series(stab)

    size_asof = cls[cls["asof_date"].eq(asof)].set_index("ts_code")

    result = pd.DataFrame(index=latest.index)
    result["g1_rev_yoy"] = latest["or_yoy"]
    result["g2_dedt_np_yoy"] = latest["dt_netprofit_yoy"]
    result["g3_q_rev_yoy"] = latest["q_sales_yoy"]
    result["g4_rd_intensity"] = latest["rd_exp"] / latest["revenue"]
    result.loc[(result["g4_rd_intensity"] < 0) | (result["g4_rd_intensity"] > 1), "g4_rd_intensity"] = np.nan
    result["g5_np_accel"] = latest["dt_netprofit_yoy"] - prev_yoy.reindex(latest.index)
    result["g6_rev_stability"] = stability.reindex(latest.index)

    # industry / size / turnover from classification v2
    result["l1_code"] = size_asof["l1_code"].reindex(latest.index)
    result["log_size"] = np.log(size_asof["total_mv"].reindex(latest.index))
    result["size_control"] = size_asof["free_float_mv_percentile"].reindex(latest.index)
    result["turnover_pct"] = size_asof["turnover_rate_percentile"].reindex(latest.index)
    # g7: revenue growth rank x turnover percentile (confirmation interaction)
    rev_rank_all = result["g1_rev_yoy"].rank(pct=True)
    result["g7_rev_x_turnover"] = rev_rank_all * result["turnover_pct"]

    # domain restriction for g8 + control dummy
    tech_mask = result["l1_code"].isin(TECH_L1_CODES)
    result["g8_tech_growth"] = np.nan
    result.loc[tech_mask, "g8_tech_growth"] = result.loc[tech_mask, "g1_rev_yoy"].rank(pct=True)
    result["g0_tech_dummy"] = tech_mask.astype(float)

    # financial exclusion + risk filter
    result = result[~result["l1_code"].isin(FINANCIAL_L1_CODES)].copy()
    risk = size_asof["risk_status"].reindex(result.index)
    result = result[risk.isna() | (~risk.isin(["st", "delist_phase"]))].copy()
    return result.reset_index()


def qlib_symbol(code: str) -> str:
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


def fetch_labels(snapshots: dict[pd.Timestamp, pd.DataFrame], calendar: pd.DatetimeIndex) -> dict[pd.Timestamp, pd.DataFrame]:
    months = sorted(snapshots)
    empty_months = [date for date, frame in snapshots.items() if frame.empty or "ts_code" not in frame.columns]
    snapshots = {date: frame for date, frame in snapshots.items() if date not in empty_months}
    codes = sorted({qlib_symbol(code) for frame in snapshots.values() for code in frame["ts_code"]})
    if not codes:
        return {date: frame.assign(**{f"label_{h}": np.nan for h in HORIZONS}) for date, frame in snapshots.items()}
    max_end = max(
        calendar[calendar.get_loc(date) + max(HORIZONS)]
        for date in months
        if calendar.get_loc(date) + max(HORIZONS) < len(calendar)
    )
    start = min(months)
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


def analyze_stage(snapshots: dict[pd.Timestamp, pd.DataFrame], stage: str):
    monthly_ic, groups, coverage = [], [], []
    min_sample = {"g0_tech_dummy": 100, "g8_tech_growth": 100}
    for date, source in snapshots.items():
        for score_name in SCORES:
            score = source[score_name]
            for horizon in HORIZONS:
                need = min_sample.get(score_name, 100)
                sample = source.assign(score=score).dropna(subset=["score", "l1_code", "size_control", f"label_{horizon}"]).copy()
                if score_name == "g0_tech_dummy":
                    # dummy has no variance after dropna(l1) unless both groups present
                    sample = source.assign(score=score).dropna(subset=["score", "size_control", f"label_{horizon}"]).copy()
                if len(sample) < need:
                    coverage.append({"stage": stage, "rebalance_date": date, "score": score_name,
                                     "horizon": horizon, "complete_sample": len(sample), "valid": False})
                    continue
                if score_name == "g0_tech_dummy":
                    raw_ic = spearman(sample["score"], sample[f"label_{horizon}"])
                    neutral_ic = np.nan  # dummy neutralization not meaningful
                    monthly_ic.append({"stage": stage, "rebalance_date": date, "score": score_name,
                                       "horizon": horizon, "complete_sample": len(sample),
                                       "raw_rank_ic": raw_ic, "neutral_rank_ic": neutral_ic})
                    coverage.append({"stage": stage, "rebalance_date": date, "score": score_name,
                                     "horizon": horizon, "complete_sample": len(sample), "valid": True})
                    continue
                if score_name == "g8_tech_growth":
                    sample = sample[sample["l1_code"].isin(TECH_L1_CODES)]
                    if len(sample) < need:
                        coverage.append({"stage": stage, "rebalance_date": date, "score": score_name,
                                         "horizon": horizon, "complete_sample": len(sample), "valid": False})
                        continue
                residual = ols_residual(sample["score"], sample["l1_code"], sample["log_size"])
                label = sample[f"label_{horizon}"]
                raw_ic, neutral_ic = spearman(sample["score"], label), spearman(residual, label)
                monthly_ic.append({"stage": stage, "rebalance_date": date, "score": score_name,
                                   "horizon": horizon, "complete_sample": len(sample),
                                   "raw_rank_ic": raw_ic, "neutral_rank_ic": neutral_ic})
                coverage.append({"stage": stage, "rebalance_date": date, "score": score_name,
                                 "horizon": horizon, "complete_sample": len(sample), "valid": True})
                for name, values in [("raw", sample["score"]), ("neutral", residual)]:
                    item = sample.assign(_score=values)
                    try:
                        item["_group"] = pd.qcut(item["_score"].rank(method="first"), 5, labels=False) + 1
                    except ValueError:
                        continue
                    means = item.groupby("_group", observed=True)[f"label_{horizon}"].mean().reindex(range(1, 6))
                    groups.append({"stage": stage, "rebalance_date": date, "score": score_name,
                                   "horizon": horizon, "version": name, "group_type": "quintile",
                                   "high_minus_low": means.iloc[-1] - means.iloc[0],
                                   "monotonicity": float((means.diff().dropna().ge(0)).mean())})
    return pd.DataFrame(monthly_ic), pd.DataFrame(groups), pd.DataFrame(coverage)


def summarize_ic(monthly_ic: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for keys, group in monthly_ic.groupby(["stage", "score", "horizon"], observed=True):
        row = dict(zip(["stage", "score", "horizon"], keys))
        for column in ("raw_rank_ic", "neutral_rank_ic"):
            values = group[column].dropna()
            row[column] = values.mean() if len(values) else np.nan
            row[f"{column}_icir"] = values.mean() / values.std(ddof=1) if len(values) > 1 and values.std(ddof=1) else np.nan
            row[f"{column}_positive_ratio"] = (values > 0).mean() if len(values) else np.nan
            row[f"{column}_months"] = len(values)
        rows.append(row)
    return pd.DataFrame(rows)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path,
                        default=Path("output/analysis_fundamental/a_share_growth_factor_family_v1"))
    args = parser.parse_args()
    out = args.output_dir
    if out.exists() and any(out.iterdir()):
        raise FileExistsError(f"Refusing to overwrite existing experiment output: {out}")
    out.mkdir(parents=True, exist_ok=True)

    qlib.init(provider_uri=str(QLIB_DIR), region=REG_CN)
    calendar = pd.DatetimeIndex(pd.to_datetime(pd.read_csv(QLIB_DIR / "calendars" / "day.txt", header=None)[0]))

    print("[1/4] Loading growth financial PIT + classification ...", flush=True)
    fin = load_growth_financials()
    print(f"      fin rows={len(fin)}", flush=True)
    cls = pd.read_csv(CLASS_V2, compression="gzip")
    cls["asof_date"] = pd.to_datetime(cls["asof_date"], errors="coerce")
    grid = pd.read_csv(STYLE_DIR / "monthly_rebalance_grid.csv.gz", compression="gzip",
                       parse_dates=["rebalance_date", "asof_date"])

    monthly_panels, monthly_ic_all, groups_all, coverage_all = [], [], [], []
    for stage in ("development", "confirmation", "holdout"):
        stage_grid = stage_months(grid, stage)
        print(f"[{stage}] {len(stage_grid)} months", flush=True)
        snapshots = {row.rebalance_date: build_snapshot(fin, cls, row) for _, row in stage_grid.iterrows()}
        snapshots = fetch_labels(snapshots, calendar)
        monthly_ic, groups, coverage = analyze_stage(snapshots, stage)
        for date, frame in snapshots.items():
            frame = frame.copy()
            frame["stage"] = stage
            frame["rebalance_date"] = date
            monthly_panels.append(frame)
        monthly_ic_all.append(monthly_ic)
        groups_all.append(groups)
        coverage_all.append(coverage)
        summary = summarize_ic(monthly_ic)
        print(f"      {stage} 40d neutral RankIC:", flush=True)
        print(summary[summary["horizon"].eq(40)][["score", "neutral_rank_ic", "neutral_rank_ic_icir",
                                                  "neutral_rank_ic_positive_ratio"]].round(4).to_string(index=False), flush=True)

    panel = pd.concat(monthly_panels, ignore_index=True)
    monthly_ic = pd.concat(monthly_ic_all, ignore_index=True)
    groups = pd.concat(groups_all, ignore_index=True)
    coverage = pd.concat(coverage_all, ignore_index=True)
    summary = summarize_ic(monthly_ic)

    atomic_csv(panel, out / "monthly_signal_label_panel.csv.gz")
    atomic_csv(monthly_ic, out / "monthly_rank_ic.csv.gz")
    atomic_csv(summary, out / "rank_ic_summary.csv")
    atomic_csv(groups, out / "group_return_summary.csv")
    atomic_csv(coverage, out / "sample_coverage_summary.csv")

    # decision per pre-registered gates
    decision = {}
    for score in SCORES:
        if score == "g0_tech_dummy":
            row = summary[(summary["stage"].eq("development")) & (summary["score"].eq(score)) & (summary["horizon"].eq(40))]
            decision[score] = {"dev_raw_ic40": float(row["raw_rank_ic"].iloc[0]) if len(row) else None,
                               "note": "control: tech-domain industry effect (raw IC only)"}
            continue
        decision[score] = {}
        dev40 = summary[(summary["stage"].eq("development")) & (summary["score"].eq(score)) & (summary["horizon"].eq(40))]
        if dev40.empty:
            decision[score]["development"] = "no_data"
            continue
        ic40 = float(dev40["neutral_rank_ic"].iloc[0])
        icir40 = float(dev40["neutral_rank_ic_icir"].iloc[0])
        ic20 = summary[(summary["stage"].eq("development")) & (summary["score"].eq(score)) & (summary["horizon"].eq(20))]
        ic60 = summary[(summary["stage"].eq("development")) & (summary["score"].eq(score)) & (summary["horizon"].eq(60))]
        dev_pass = bool(ic40 > 0.01 and icir40 >= 0.20 and len(ic20) and ic20["neutral_rank_ic"].iloc[0] > 0
                        and len(ic60) and ic60["neutral_rank_ic"].iloc[0] > 0)
        decision[score].update({"dev_ic40": ic40, "dev_icir40": icir40,
                                "development": "pass" if dev_pass else "fail"})
        if not dev_pass:
            continue
        con = summary[(summary["stage"].eq("confirmation")) & (summary["score"].eq(score)) & (summary["horizon"].eq(40))]
        if con.empty:
            decision[score]["confirmation"] = "no_data"
            continue
        decision[score]["conf_ic40"] = float(con["neutral_rank_ic"].iloc[0])
        decision[score]["confirmation"] = "confirmed" if float(con["neutral_rank_ic"].iloc[0]) > 0.01 else "fail"
        if float(con["neutral_rank_ic"].iloc[0]) <= 0.01:
            continue
        hol = summary[(summary["stage"].eq("holdout")) & (summary["score"].eq(score)) & (summary["horizon"].eq(40))]
        if hol.empty:
            decision[score]["holdout"] = "no_data"
            continue
        decision[score]["hol_ic40"] = float(hol["neutral_rank_ic"].iloc[0])
        decision[score]["holdout"] = "replicated" if float(hol["neutral_rank_ic"].iloc[0]) > 0 else "not_replicated"
    atomic_json(decision, out / "decision.json")

    methodology = {
        "proposal": "research/decisions/a_share_growth_factor_family_proposal_v1.md",
        "protocol": "research/protocols/a_share_growth_factor_family_protocol_v1.md",
        "factors": {
            "g0_tech_dummy": "SW L1 in {801080 electronic, 801750 computer, 801770 telecom} (raw IC only)",
            "g1_rev_yoy": "or_yoy from fina_indicator (PIT by available_date)",
            "g2_dedt_np_yoy": "dt_netprofit_yoy",
            "g3_q_rev_yoy": "q_sales_yoy single-quarter",
            "g4_rd_intensity": "rd_exp/revenue from income (full batches, missing 2025+)",
            "g5_np_accel": "dt_netprofit_yoy(t) - previous report dt_netprofit_yoy",
            "g6_rev_stability": "-std(or_yoy, last 8 reports, >=6 non-null)",
            "g7_rev_x_turnover": "or_yoy cross-sectional rank * turnover_rate_percentile (monthly)",
            "g8_tech_growth": "or_yoy pct-rank within tech L1 domain",
        },
        "gates": {"dev": "neutral ic40>0.01 and icir40>=0.20 and ic20>0 and ic60>0",
                  "confirmation": "ic40>0.01", "holdout": "ic40>0"},
        "neutralization": "log_size + SW L1 dummies (same as v8)",
        "stages": {k: [v[0].isoformat(), v[1].isoformat()] for k, v in STAGES.items()},
        "label": "open-to-open, H in {20,40,60}",
        "created_at_utc": pd.Timestamp.utcnow().isoformat(),
    }
    atomic_json(methodology, out / "methodology.json")

    lines = [
        "A 股成长因子族 staged 验证 v1",
        "=" * 64,
        "各阶段 40 日中性化 Rank IC：",
        summary[summary["horizon"].eq(40)].pivot(index="score", columns="stage", values="neutral_rank_ic").round(4).to_string(),
        "",
        "判定：",
        json.dumps(decision, ensure_ascii=False, indent=2),
    ]
    (out / "validation_report.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("\n".join(lines))


if __name__ == "__main__":
    main()
