#!/usr/bin/env python3
"""Value-trap identification: in-domain deterioration filter test (protocol v1).

Within the mainline's "cheap" domain (composite neutralized residual top 50%),
do stocks flagged by financial deterioration (netprofit/or/ocf YoY < 0) earn
significantly less over 20/40/60 days than equally-cheap but stable stocks?

Reuses the mainline's frozen functions (build_snapshot, composite_score,
ols_residual, load_financials_extended, build_daily_grid) without modifying them.
YoY columns are merged externally and the deterioration flags are computed per
month-end snapshot under PIT alignment (available_date <= rebalance_date).

Protocol: research/protocols/a_share_value_trap_identification_protocol_v1.md
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

from load_financials_extended_v1 import load_financials_extended, FIN, _fill_available
from analyze_a_share_value_quality_level_factors_extension_v1 import (
    build_snapshot,
    ols_residual,
    composite_score,
    qlib_symbol,
    STYLE_DIR,
    QLIB_DIR,
)
from backtest_a_share_value_quality_monthly_dailygrid_v6 import build_daily_grid

STAGES = {
    "development": (pd.Timestamp("2016-01-01"), pd.Timestamp("2019-12-31")),
    "confirmation": (pd.Timestamp("2020-01-01"), pd.Timestamp("2022-12-31")),
    "holdout": (pd.Timestamp("2023-01-01"), pd.Timestamp("2025-06-30")),
    "new_coverage": (pd.Timestamp("2025-07-01"), pd.Timestamp("2026-06-30")),
}
HORIZONS = (20, 40, 60)
DOMAIN_QUANTILE = 0.50
YOY_COLS = ["netprofit_yoy", "or_yoy", "ocf_yoy", "dt_netprofit_yoy"]


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


def load_financials_with_yoy() -> pd.DataFrame:
    """Extended financial frame plus the four YoY deterioration columns.

    The YoY columns live in the same merged fina_indicator file; they are read
    separately and merged on (ts_code, end_date, available_date) so the frozen
    load_financials_extended is not modified.
    """
    fin = load_financials_extended()
    yoy = pd.read_csv(
        FIN / "normalized/fina_indicator.csv.gz",
        usecols=["ts_code", "end_date", "ann_date", "available_date", *YOY_COLS],
        low_memory=False,
    )
    yoy = _fill_available(yoy)
    yoy = yoy.dropna(subset=["available_date"])
    yoy = yoy.drop_duplicates(["ts_code", "end_date", "available_date"], keep="last")
    return fin.merge(yoy, on=["ts_code", "end_date", "available_date"], how="left")


def deterioration_flags(latest: pd.DataFrame) -> pd.DataFrame:
    """Compute the four frozen deterioration flags from a per-code latest frame.

    `latest` must carry the YoY columns at the newest report period per code.
    Missing YoY => NaN for that sub-signal (not filled with 0).  deter_any2
    requires at least 2 non-missing sub-signals.
    """
    out = pd.DataFrame(index=latest.index)
    out["deter_ni"] = (latest["netprofit_yoy"] < 0).astype(float)
    out["deter_or"] = (latest["or_yoy"] < 0).astype(float)
    out["deter_ocf"] = (latest["ocf_yoy"] < 0).astype(float)
    out["deter_ni_dedt"] = (latest["dt_netprofit_yoy"] < 0).astype(float)
    n_observed = out[["deter_ni", "deter_or", "deter_ocf"]].notna().sum(axis=1)
    n_hit = out[["deter_ni", "deter_or", "deter_ocf"]].sum(axis=1)
    any2 = pd.Series(np.nan, index=latest.index)
    any2[n_observed >= 2] = (n_hit[n_observed >= 2] >= 2).astype(float)
    out["deter_any2"] = any2
    return out


def fetch_open_labels(snapshots: dict[pd.Timestamp, pd.DataFrame], calendar: pd.DatetimeIndex) -> dict[pd.Timestamp, pd.DataFrame]:
    """Append open-to-open r_H labels for H in HORIZONS to each snapshot."""
    months = sorted(snapshots)
    codes = sorted({qlib_symbol(code) for frame in snapshots.values() for code in frame["ts_code"]})
    if not codes:
        return {d: f.assign(**{f"label_{h}": np.nan for h in HORIZONS}) for d, f in snapshots.items()}
    start = months[0]
    max_end = max(
        calendar[min(calendar.get_loc(date) + max(HORIZONS), len(calendar) - 1)]
        for date in months
    )
    open_frame = (
        D.features(codes, ["$open"], start_time=start, end_time=max_end, freq="day")
        .rename(columns={"$open": "open"})
        .reset_index()
    )
    open_frame["ts_code"] = open_frame["instrument"].map(lambda s: f"{s[2:]}.{s[:2]}")
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


def ttest(series: pd.Series) -> float:
    values = series.dropna()
    if len(values) < 2:
        return np.nan
    return float(values.mean() / values.std(ddof=1) * np.sqrt(len(values)))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path,
                        default=Path("output/analysis_fundamental/a_share_value_trap_identification_v1"))
    args = parser.parse_args()
    out = args.output_dir
    if out.exists() and any(out.iterdir()):
        raise FileExistsError(f"Refusing to overwrite existing experiment output: {out}")
    out.mkdir(parents=True, exist_ok=True)

    qlib.init(provider_uri=str(QLIB_DIR), region=REG_CN)
    calendar = pd.DatetimeIndex(pd.to_datetime(pd.read_csv(QLIB_DIR / "calendars" / "day.txt", header=None)[0]))

    print("[1/5] Loading extended financials (+YoY) & daily grid ...", flush=True)
    fin = load_financials_with_yoy()
    grid, size_daily = build_daily_grid()
    print(f"      fin rows={len(fin)}  months={len(grid)} "
          f"{grid['rebalance_date'].min().date()} .. {grid['rebalance_date'].max().date()}", flush=True)

    industry = pd.read_csv(STYLE_DIR / "industry_l1_effective_intervals.csv.gz", compression="gzip", dtype=str)
    industry["in_date"] = pd.to_datetime(industry["in_date"], errors="coerce")
    industry["out_date"] = pd.to_datetime(industry["out_date"], errors="coerce")

    print("[2/5] Building monthly snapshots with deterioration flags ...", flush=True)
    snapshots = {}
    for _, row in grid.iterrows():
        snap = build_snapshot(fin, row, industry, size_daily)
        if snap.empty:
            continue
        # Latest report period per code under the same PIT alignment as build_snapshot.
        current = fin[fin["available_date"].le(row.rebalance_date)].copy()
        current = current.sort_values(["ts_code", "end_date", "available_date"], kind="mergesort")
        current = current.drop_duplicates(["ts_code", "end_date"], keep="last")
        latest = current.sort_values(["ts_code", "end_date"], kind="mergesort").drop_duplicates("ts_code", keep="last")
        latest = latest.set_index("ts_code")
        flags = deterioration_flags(latest)
        frame = snap.merge(flags.reset_index().rename(columns={"index": "ts_code"}), on="ts_code", how="left")
        frame["composite"] = composite_score(frame)
        valid = frame.dropna(subset=["composite", "log_size", "l1_code"])
        if len(valid) < 50:
            continue
        resid = ols_residual(valid["composite"], valid["l1_code"], valid["log_size"])
        frame["neutral_composite"] = resid.reindex(frame.index)
        # Domain: neutralized composite top 50% (mainline selection domain).
        domain_rank = frame["neutral_composite"].rank(pct=True)
        frame["in_domain"] = (domain_rank >= 1 - DOMAIN_QUANTILE) & frame["neutral_composite"].notna()
        snapshots[row.rebalance_date] = frame
    print(f"      valid months={len(snapshots)}", flush=True)

    print("[3/5] Fetching open-to-open labels ...", flush=True)
    snapshots = fetch_open_labels(snapshots, calendar)

    print("[4/5] Running main & secondary tests ...", flush=True)
    panel_rows, diff_rows, single_rows, layer_rows = [], [], [], []
    for date, frame in snapshots.items():
        stage = next((s for s, (a, b) in STAGES.items() if a <= date <= b), None)
        dom = frame[frame["in_domain"]].copy()
        if dom.empty or len(dom) < 100:
            continue
        for horizon in HORIZONS:
            label = f"label_{horizon}"
            sample = dom.dropna(subset=["deter_any2", label]).copy()
            if len(sample) < 100:
                continue
            # Neutralize the label with industry + log_size (same residual basis as mainline).
            neutral = ols_residual(sample[label], sample["l1_code"], sample["log_size"])
            sample["neutral_label"] = neutral
            group_means = sample.groupby("deter_any2")["neutral_label"].mean()
            diff = group_means.get(1.0, np.nan) - group_means.get(0.0, np.nan)
            diff_rows.append({"rebalance_date": date, "stage": stage, "horizon": horizon,
                              "deteriorated_n": int((sample["deter_any2"] == 1).sum()),
                              "stable_n": int((sample["deter_any2"] == 0).sum()),
                              "group_mean_diff": diff,
                              "deteriorated_mean": group_means.get(1.0, np.nan),
                              "stable_mean": group_means.get(0.0, np.nan)})
            for code, name in [("deter_ni", "deter_ni"), ("deter_or", "deter_or"),
                               ("deter_ocf", "deter_ocf"), ("deter_any2", "deter_any2")]:
                s = sample.dropna(subset=[code, label]).copy()
                if len(s) < 100:
                    continue
                s["neutral_label"] = ols_residual(s[label], s["l1_code"], s["log_size"])
                gm = s.groupby(code)["neutral_label"].mean()
                single_rows.append({"rebalance_date": date, "stage": stage, "horizon": horizon,
                                    "signal": name,
                                    "flagged_n": int((s[code] == 1).sum()),
                                    "group_mean_diff": gm.get(1.0, np.nan) - gm.get(0.0, np.nan)})
            # Size layers within domain, main horizon only.
            if horizon == 40 and "size_control" in sample.columns:
                sample["size_layer"] = pd.qcut(sample["size_control"].rank(method="first"), 5, labels=False) + 1
                for layer, group in sample.groupby("size_layer", observed=True):
                    g2 = group.dropna(subset=["deter_any2", label]).copy()
                    if len(g2) < 20:
                        continue
                    g2["neutral_label"] = ols_residual(g2[label], g2["l1_code"], g2["log_size"])
                    gm = g2.groupby("deter_any2")["neutral_label"].mean()
                    layer_rows.append({"rebalance_date": date, "stage": stage, "size_layer": f"S{layer}",
                                       "deteriorated_n": int((g2["deter_any2"] == 1).sum()),
                                       "group_mean_diff": gm.get(1.0, np.nan) - gm.get(0.0, np.nan)})
        for horizon in HORIZONS:
            label = f"label_{horizon}"
            item = dom.dropna(subset=["deter_any2", label]).copy()
            if len(item) < 100:
                continue
            item["neutral_label"] = ols_residual(item[label], item["l1_code"], item["log_size"])
            sub = item[["ts_code", "deter_any2", "neutral_label"]].rename(columns={"deter_any2": "flagged"})
            sub["rebalance_date"] = date
            sub["stage"] = stage
            sub["horizon"] = horizon
            panel_rows.append(sub)
    panel = pd.concat(panel_rows, ignore_index=True)
    diffs = pd.DataFrame(diff_rows)
    singles = pd.DataFrame(single_rows)
    layers = pd.DataFrame(layer_rows)

    def summarize_diffs(frame: pd.DataFrame) -> pd.DataFrame:
        rows = []
        for keys, group in frame.groupby(["stage", "horizon"], observed=True):
            series = group["group_mean_diff"].dropna()
            rows.append({"stage": keys[0], "horizon": keys[1], "months": len(series),
                         "mean_group_diff": series.mean(),
                         "median_group_diff": series.median(),
                         "t_stat": ttest(series),
                         "negative_ratio": (series < 0).mean() if len(series) else np.nan,
                         "deteriorated_month_mean": group["deteriorated_n"].mean(),
                         "stable_month_mean": group["stable_n"].mean()})
        return pd.DataFrame(rows)

    diff_summary = summarize_diffs(diffs)
    print("\nMain test: domain-internal deterioration vs stable, neutralized 40d diff (per stage):")
    print(diff_summary[diff_summary["horizon"].eq(40)][["stage", "months", "mean_group_diff", "t_stat", "negative_ratio"]].to_string(index=False))

    atomic_csv(panel, out / "monthly_signal_label_panel.csv.gz")
    atomic_csv(diff_summary, out / "group_mean_diff_summary.csv")
    atomic_csv(singles, out / "signal_single_monthly.csv.gz")
    atomic_csv(layers, out / "size_layer_monthly.csv.gz")

    print("[5/5] Decision & artifacts ...", flush=True)
    key = diff_summary[diff_summary["horizon"].eq(40)].set_index("stage")
    decision = {}
    for stage in STAGES:
        if stage in key.index:
            row = key.loc[stage]
            decision[f"{stage}_mean_diff"] = round(float(row["mean_group_diff"]), 5)
            decision[f"{stage}_t"] = round(float(row["t_stat"]), 3) if pd.notna(row["t_stat"]) else None
            decision[f"{stage}_negative_ratio"] = round(float(row["negative_ratio"]), 3) if pd.notna(row["negative_ratio"]) else None
    neg = [s for s in ("development", "confirmation", "holdout") if decision.get(f"{s}_mean_diff") is not None and decision[f"{s}_mean_diff"] < 0]
    ic_layer_pass = bool(len(neg) >= 2 and any(decision.get(f"{s}_t") is not None and decision[f"{s}_t"] < -2 for s in STAGES))
    decision["ic_layer_pass"] = ic_layer_pass
    decision["negative_stages"] = neg
    atomic_json(decision, out / "decision.json")

    methodology = {
        "protocol": "research/protocols/a_share_value_trap_identification_protocol_v1.md",
        "qlib_data_dir": str(QLIB_DIR),
        "label": "open-to-open r_H(t)=open(t+H)/open(t)-1, H in {20,40,60}",
        "domain": "neutralized composite (industry OLS + log_size residual) top 50%",
        "signals": {
            "deter_ni": "netprofit_yoy < 0",
            "deter_or": "or_yoy < 0",
            "deter_ocf": "ocf_yoy < 0",
            "deter_ni_dedt": "dt_netprofit_yoy < 0 (observation only)",
            "deter_any2": ">=2 of {ni, or, ocf} flagged, >=2 observed (primary)",
        },
        "pit_rule": "available_date <= rebalance_date, latest version per code",
        "neutralization": "label OLS residual on industry + log_size",
        "stages": {k: [v[0].isoformat(), v[1].isoformat()] for k, v in STAGES.items()},
        "created_at_utc": pd.Timestamp.utcnow().isoformat(),
    }
    atomic_json(methodology, out / "methodology.json")

    lines = [
        "价值陷阱识别 v1（域内恶化过滤检验）",
        "=" * 64,
        "主检验：域内 deter_any2 恶化组 vs 稳定组 中性化收益差（负 = 恶化组跑输）",
        diff_summary.to_string(index=False),
        "",
        "判定：",
        json.dumps(decision, ensure_ascii=False, indent=2),
    ]
    (out / "validation_report.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("\n".join(lines))


if __name__ == "__main__":
    main()
