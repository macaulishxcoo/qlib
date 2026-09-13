#!/usr/bin/env python3
"""Run the frozen staged validation for the value/quality LEVEL-factor extension.

Adds 4 pre-declared candidates (bm, roe_stability, accruals, div_yield) plus the
E/P control on the same framework as the first level-factor validation.  The ep
control must reproduce the first-round result (neutral RankIC diff < 0.01) as a
script regression check.

Protocol: research/protocols/a_share_value_quality_level_factors_extension_protocol_v1.md
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
SCORES = ("ep", "bm", "roe_stability", "accruals", "div_yield")
FINANCIAL_L1_CODES = {"801780.SI", "801790.SI"}
ROOT = Path(__file__).resolve().parents[1]
FIN_BASE = ROOT / "data/external/tushare/a_share_financial_pit_v1/full/normalized"
BAL_BASE = ROOT / "data/external/tushare/a_share_financial_pit_v1/balancesheet_v1/normalized"
STYLE_DIR = ROOT / "data/external/tushare/a_share_style_pit_v1/normalized"
QLIB_DIR = Path.home() / ".qlib/qlib_data/cn_data_2026"
EP_DEV_REFERENCE = 0.08388190674960562  # first-round development 40d neutral RankIC for ep


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


def load_financials() -> pd.DataFrame:
    """Load fina_indicator + cashflow + income + balancesheet into one long PIT frame."""
    def read_all(bases: list[Path], pattern: str, cols: list[str]) -> pd.DataFrame:
        frames = []
        for base in bases:
            for batch in sorted(base.glob("batch_*")):
                path = batch / pattern
                if not path.exists():
                    continue
                frames.append(pd.read_csv(path, compression="gzip", usecols=cols))
        if not frames:
            return pd.DataFrame(columns=cols)
        return pd.concat(frames, ignore_index=True)

    fin = read_all([FIN_BASE], "fina_indicator.csv.gz", ["ts_code", "end_date", "available_date", "profit_dedt", "roe", "bps", "debt_to_assets"])
    cash = read_all([FIN_BASE], "cashflow.csv.gz", ["ts_code", "end_date", "available_date", "n_cashflow_act"])
    income = read_all([FIN_BASE], "income.csv.gz", ["ts_code", "end_date", "available_date", "n_income_attr_p"])
    bal = read_all([BAL_BASE], "balancesheet.csv.gz", ["ts_code", "end_date", "available_date", "total_assets"])

    for frame in (fin, cash, income, bal):
        if frame.empty:
            continue
        frame["end_date"] = pd.to_datetime(frame["end_date"], format="%Y%m%d", errors="coerce")
        frame["available_date"] = pd.to_datetime(frame["available_date"], errors="coerce")
        frame.drop_duplicates(["ts_code", "end_date", "available_date"], keep="last", inplace=True)

    result = fin
    result = result.merge(
        cash[["ts_code", "end_date", "available_date", "n_cashflow_act"]],
        on=["ts_code", "end_date", "available_date"], how="left",
    )
    result = result.merge(
        income[["ts_code", "end_date", "available_date", "n_income_attr_p"]],
        on=["ts_code", "end_date", "available_date"], how="left",
    )
    result = result.merge(
        bal[["ts_code", "end_date", "available_date", "total_assets"]],
        on=["ts_code", "end_date", "available_date"], how="left",
    )
    return result


def ttm_value(frame: pd.DataFrame, value_col: str) -> pd.Series:
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


def roe_volatility(frame: pd.DataFrame) -> pd.Series:
    """-std(roe, last 8 report periods); at least 6 non-null required."""
    result = {}
    for ts_code, group in frame.groupby("ts_code"):
        roe = group["roe"].dropna().sort_index()  # end_date order
        if len(roe) < 6:
            continue
        window = roe.tail(8)
        if len(window) >= 6:
            result[ts_code] = -float(window.std(ddof=1))
    return pd.Series(result)


def build_snapshot(fin: pd.DataFrame, grid_row: pd.Series, industry: pd.DataFrame, size: pd.DataFrame) -> pd.DataFrame:
    date = grid_row.rebalance_date
    asof = grid_row.asof_date
    current = fin[fin["available_date"].le(date)].copy()
    current = current.sort_values(["ts_code", "end_date", "available_date"], kind="mergesort").drop_duplicates(
        ["ts_code", "end_date"], keep="last"
    )
    if current.empty:
        return current

    ep_ttm = ttm_value(current, "profit_dedt")
    cfo_ttm = ttm_value(current, "n_cashflow_act")
    ni_ttm = ttm_value(current, "n_income_attr_p")
    roe_vol = roe_volatility(current)

    latest = current.sort_values(["ts_code", "end_date"], kind="mergesort").drop_duplicates("ts_code", keep="last").copy()
    latest = latest.set_index("ts_code")

    size_asof = size[size["asof_date"].eq(asof)].set_index("ts_code")
    total_mv_yuan = size_asof["total_mv"].reindex(latest.index) * 1e4
    total_share = size_asof["total_share"].reindex(latest.index)

    result = pd.DataFrame(index=latest.index)
    result["ep"] = ep_ttm.reindex(latest.index) / total_mv_yuan
    result["bm"] = (latest["bps"] * total_share * 1e4) / total_mv_yuan
    result["roe_stability"] = roe_vol.reindex(latest.index)
    result["accruals"] = -((ni_ttm.reindex(latest.index) - cfo_ttm.reindex(latest.index)) / latest["total_assets"])
    result["div_yield"] = size_asof["dv_ttm"].reindex(latest.index)

    # Economic-domain constraints.
    result.loc[result["ep"].le(0), "ep"] = np.nan
    result.loc[latest["bps"].le(0), "bm"] = np.nan
    result.loc[ni_ttm.reindex(latest.index).le(0), "accruals"] = np.nan

    # Industry as-of, drop financials.
    applicable = industry[industry["in_date"].le(asof) & (industry["out_date"].isna() | industry["out_date"].ge(asof))]
    counts = applicable.groupby("ts_code").size()
    applicable = applicable[applicable["ts_code"].isin(counts[counts.eq(1)].index)][["ts_code", "l1_code", "l1_name"]]
    result = result.reset_index().merge(applicable, on="ts_code", how="left").set_index("ts_code")
    result = result[~result["l1_code"].isin(FINANCIAL_L1_CODES)].copy()

    result["size_control"] = size_asof["size_control"].reindex(result.index)
    result["total_mv"] = size_asof["total_mv"].reindex(result.index)
    result["log_size"] = np.log(result["total_mv"])
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


def composite_score(frame: pd.DataFrame, factors: tuple = ("ep", "bm", "div_yield", "accruals"),
                    min_factors: int = 3) -> pd.Series:
    """Equal-weight percentile-rank average of the four factors with a factor-count gate.

    Stocks with fewer than ``min_factors`` non-missing factors get NaN (excluded
    from selection).  This prevents single-factor stocks (e.g. loss-makers with
    only a high BM) from scoring ~0.9 and crowding out four-factor stocks (~0.5),
    which was the hidden driver of the 2026 v6 drawdown.
    """
    ranks = pd.concat(
        [frame[f].rank(method="first", pct=True) for f in factors], axis=1
    )
    ranks.columns = [f"{f}_rank" for f in factors]
    n_factors = ranks.notna().sum(axis=1)
    composite = ranks.mean(axis=1)
    composite[n_factors < min_factors] = np.nan
    return composite


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
                if score_name in ("bm", "roe_stability", "accruals", "div_yield") and horizon == 40:
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
    parser.add_argument("--output-dir", type=Path, default=Path("output/analysis_fundamental/a_share_value_quality_level_factors_v1_extension"))
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
        summary = summarize_ic(monthly_ic)
        print(f"      {stage} 40d neutral RankIC:", flush=True)
        print(summary[summary["horizon"].eq(40)][["score", "neutral_rank_ic", "neutral_rank_ic_icir"]].to_string(index=False), flush=True)

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

    # ep control regression check.
    dev_ep = summarize_ic(monthly_ic)[(summarize_ic(monthly_ic)["stage"].eq("development")) & (summarize_ic(monthly_ic)["score"].eq("ep")) & (summarize_ic(monthly_ic)["horizon"].eq(40))]
    ep_control_ok = bool(len(dev_ep) and abs(float(dev_ep["neutral_rank_ic"].iloc[0]) - EP_DEV_REFERENCE) < 0.01)

    summary = summarize_ic(monthly_ic)
    decision = {"ep_control_regression_ok": ep_control_ok}
    for score in ("bm", "roe_stability", "accruals", "div_yield"):
        decision[f"{score}_development"] = "not_reported"
        decision[f"{score}_confirmation"] = "not_reported"
        decision[f"{score}_holdout"] = "not_reported"
    for score in ("bm", "roe_stability", "accruals", "div_yield"):
        dev = summary[(summary["stage"].eq("development")) & (summary["score"].eq(score)) & (summary["horizon"].eq(40))]
        if dev.empty:
            continue
        ic40 = float(dev["neutral_rank_ic"].iloc[0])
        icir40 = float(dev["neutral_rank_ic_icir"].iloc[0])
        ic20 = summary[(summary["stage"].eq("development")) & (summary["score"].eq(score)) & (summary["horizon"].eq(20))]["neutral_rank_ic"]
        ic60 = summary[(summary["stage"].eq("development")) & (summary["score"].eq(score)) & (summary["horizon"].eq(60))]["neutral_rank_ic"]
        dev_pass = bool(ic40 > 0.01 and icir40 >= 0.20 and len(ic20) and ic20.iloc[0] > 0 and len(ic60) and ic60.iloc[0] > 0)
        decision[f"{score}_development"] = "pass" if dev_pass else "fail"
        if not dev_pass:
            continue
        con = summary[(summary["stage"].eq("confirmation")) & (summary["score"].eq(score)) & (summary["horizon"].eq(40))]
        if con.empty:
            continue
        ic40_con = float(con["neutral_rank_ic"].iloc[0])
        decision[f"{score}_confirmation"] = "confirmed" if ic40_con > 0.01 else "fail"
        if ic40_con <= 0.01:
            continue
        hol = summary[(summary["stage"].eq("holdout")) & (summary["score"].eq(score)) & (summary["horizon"].eq(40))]
        if hol.empty:
            continue
        decision[f"{score}_holdout"] = "replicated" if float(hol["neutral_rank_ic"].iloc[0]) > 0 else "not_replicated"
    atomic_json(decision, out / "decision.json")

    methodology = {
        "protocol": "research/protocols/a_share_value_quality_level_factors_extension_protocol_v1.md",
        "qlib_data_dir": str(QLIB_DIR),
        "label": "open-to-open r_H(t)=open(t+H)/open(t)-1, H in {20,40,60}",
        "ttm_rule": "TTM = latest cumulative - same period last year + last year annual",
        "factors": {
            "ep": "profit_dedt TTM / total_mv (yuan), control",
            "bm": "bps (latest PIT) * total_share / total_mv",
            "roe_stability": "-std(roe, last 8 report periods), >=6 non-null",
            "accruals": "-(NI TTM - CFO TTM)/total_assets, positive-NI constraint",
            "div_yield": "dv_ttm from monthly size PIT",
        },
        "financial_excluded_l1": sorted(FINANCIAL_L1_CODES),
        "stages": {k: [v[0].isoformat(), v[1].isoformat()] for k, v in STAGES.items()},
        "ep_development_40d_neutral_reference": EP_DEV_REFERENCE,
        "created_at_utc": pd.Timestamp.utcnow().isoformat(),
    }
    atomic_json(methodology, out / "methodology.json")

    lines = [
        "沪深非金融 A 股价值/质量水平因子同族扩展验证 v1",
        "=" * 64,
        f"E/P 对照复现（开发期 40d 中性 RankIC）：{dev_ep['neutral_rank_ic'].iloc[0]:.4f} vs 参考 {EP_DEV_REFERENCE:.4f} "
        f"→ {'通过' if ep_control_ok else '失败'}" if len(dev_ep) else "E/P 对照无开发期数据",
        "",
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
