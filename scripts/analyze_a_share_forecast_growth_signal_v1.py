#!/usr/bin/env python3
"""Forecast-growth signal test: does it add information BEYOND the five factors?

Protocol: research/protocols/a_share_forecast_growth_signal_protocol_v1.md
Frozen before data.

The control set is the project's own frozen construction, reused verbatim via
build_snapshot (ep / bm / div_yield / accruals / log_size / industry) plus g2.
The primary endpoint is the RankIC of the *residual* of fg_mid after regressing
out those controls, because the question is incremental value, not raw IC.

Note the boundary with the closed P1 line (positive_event_subtype): P1 tested the
forecast CATEGORY as an event; this tests the forecast MAGNITUDE as a factor.
"""

from __future__ import annotations

import importlib.util
import json
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
FORECAST_DIR = ROOT / "data/external/tushare/a_share_forecast_v1/raw"
OUT = ROOT / "output/analysis_fundamental/a_share_forecast_growth_signal_v1"

SAMPLE_START = pd.Timestamp("2022-01-01")
SAMPLE_END = pd.Timestamp("2026-06-30")
STALE_DAYS = 180
HORIZONS = (1, 5, 10, 20)
PRIMARY_HORIZON = 5
RESID_IC_MIN = 0.02
RESID_ICIR_MIN = 0.30
YEAR_BLOCK_AGREEMENT = 3          # out of 4 annual blocks must share the sign
CONTROLS = ("ep", "bm", "div_yield", "accruals", "g2", "log_size")


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def log(message: str) -> None:
    print(message, flush=True)


def main() -> int:
    import qlib
    from qlib.config import REG_CN
    from qlib.data import D

    if OUT.exists() and any(OUT.iterdir()):
        raise SystemExit(f"refusing to overwrite existing output: {OUT}")
    OUT.mkdir(parents=True, exist_ok=True)

    started = datetime.now(timezone.utc)
    ext = load_module("ext", ROOT / "scripts/analyze_a_share_value_quality_level_factors_extension_v1.py")
    finext = load_module("finext", ROOT / "scripts/load_financials_extended_v1.py")
    pipe = load_module("pipe", ROOT / "scripts/run_daily_signal_pipeline_v1.py")

    qlib.init(provider_uri=str(ext.QLIB_DIR), region=REG_CN)
    calendar = pd.DatetimeIndex(pd.to_datetime(pd.read_csv(ext.QLIB_DIR / "calendars" / "day.txt", header=None)[0]))

    # ------------------------------------------------------------------ #
    log("[1/5] loading frozen controls + forecast data")
    fin = finext.load_financials_extended()
    log(f"      financial rows={len(fin):,}")
    grid = pd.read_csv(ext.STYLE_DIR / "monthly_rebalance_grid.csv.gz", compression="gzip",
                       parse_dates=["rebalance_date", "asof_date"])
    industry = pd.read_csv(ext.STYLE_DIR / "industry_l1_effective_intervals.csv.gz",
                           compression="gzip", dtype=str)
    industry["in_date"] = pd.to_datetime(industry["in_date"], errors="coerce")
    industry["out_date"] = pd.to_datetime(industry["out_date"], errors="coerce")
    size = pd.read_csv(ext.STYLE_DIR / "monthly_free_float_size.csv.gz", compression="gzip")
    size["asof_date"] = pd.to_datetime(size["asof_date"], errors="coerce")

    grid = grid[(grid["rebalance_date"] >= SAMPLE_START) & (grid["rebalance_date"] <= SAMPLE_END)].copy()
    grid = grid.sort_values("rebalance_date").reset_index(drop=True)
    log(f"      grid rows in sample: {len(grid)}"

        f"  {grid['rebalance_date'].min().date()}..{grid['rebalance_date'].max().date()}")

    parts = []
    for path in sorted(FORECAST_DIR.glob("*.csv.gz")):
        try:
            parts.append(pd.read_csv(path, compression="gzip", dtype={"ts_code": str, "ann_date": str,
                                                                      "end_date": str, "type": str}))
        except Exception:  # noqa: BLE001 - a corrupt day file must not kill the run
            continue
    forecast = pd.concat(parts, ignore_index=True)
    forecast["ann_date"] = pd.to_datetime(forecast["ann_date"], format="%Y%m%d", errors="coerce")
    forecast["end_date"] = pd.to_datetime(forecast["end_date"], format="%Y%m%d", errors="coerce")
    for column in ("p_change_min", "p_change_max"):
        forecast[column] = pd.to_numeric(forecast[column], errors="coerce")
    forecast["fg_mid"] = (forecast["p_change_min"] + forecast["p_change_max"]) / 2.0
    forecast["fg_min"] = forecast["p_change_min"]
    forecast = forecast.dropna(subset=["ann_date", "end_date"])
    log(f"      forecast rows={len(forecast):,}  {forecast['ann_date'].min().date()}..{forecast['ann_date'].max().date()}")

    fin_g2 = pipe.load_g2_series()

    # ------------------------------------------------------------------ #
    log("[2/5] building the snapshot panel")
    frames = []
    for _, row in grid.iterrows():
        snapshot = ext.build_snapshot(fin, row, industry, size)
        if snapshot.empty:
            continue
        snapshot = snapshot.copy()
        snapshot["rebalance_date"] = row.rebalance_date
        snapshot["asof_date"] = row.asof_date
        snapshot["g2"] = pipe.g2_at(fin_g2, row.asof_date).reindex(snapshot["ts_code"]).to_numpy()

        # PIT forecast: latest end_date announced at or before asof, deduped to the
        # latest announcement, and rejected when staler than STALE_DAYS.
        current = forecast[forecast["ann_date"].le(row.asof_date)]
        current = current.sort_values(["ts_code", "end_date", "ann_date"], kind="mergesort")
        current = current.drop_duplicates(["ts_code", "end_date"], keep="last")
        current = current.sort_values(["ts_code", "end_date"], kind="mergesort")
        current = current.drop_duplicates("ts_code", keep="last")
        current["age_days"] = (row.asof_date - current["ann_date"]).dt.days
        current = current[current["age_days"].le(STALE_DAYS)]
        lookup = current.set_index("ts_code")
        snapshot["fg_mid"] = lookup["fg_mid"].reindex(snapshot["ts_code"]).to_numpy()
        snapshot["fg_min"] = lookup["fg_min"].reindex(snapshot["ts_code"]).to_numpy()
        snapshot["fg_age_days"] = lookup["age_days"].reindex(snapshot["ts_code"]).to_numpy()
        frames.append(snapshot)

    panel = pd.concat(frames, ignore_index=True)
    log(f"      panel rows={len(panel):,}  dates={panel['rebalance_date'].nunique()}"
        f"  fg coverage={panel['fg_mid'].notna().mean():.2%}")

    # ------------------------------------------------------------------ #
    log("[3/5] fetching open prices and building open-to-open labels")
    symbols = sorted({pipe.qlib_symbol(c) for c in panel["ts_code"].unique()
                      if isinstance(c, str) and "." in c})
    price = D.features(symbols, ["$open"], start_time="2022-01-01", end_time="2026-09-01", freq="day")
    open_wide = price["$open"].unstack(level="instrument")
    open_wide.index = pd.DatetimeIndex(open_wide.index)
    log(f"      open panel {open_wide.shape}")

    trade_days = open_wide.index
    # Position of the first trading day strictly after each rebalance date.
    next_pos = {}
    for date in panel["rebalance_date"].unique():
        later = trade_days[trade_days > pd.Timestamp(date)]
        if len(later):
            next_pos[pd.Timestamp(date)] = trade_days.get_loc(later[0])

    symbols_in_panel = panel["ts_code"].map(
        lambda c: pipe.qlib_symbol(c) if isinstance(c, str) and "." in c else None)
    panel["_symbol"] = symbols_in_panel
    for horizon in HORIZONS:
        panel[f"label_{horizon}"] = np.nan
    for date, group in panel.groupby("rebalance_date", sort=False):
        entry_pos = next_pos.get(pd.Timestamp(date))
        if entry_pos is None:
            continue
        index = group.index
        entry = open_wide.iloc[entry_pos].reindex(group["_symbol"].to_numpy()).to_numpy(dtype="float64")
        okay_entry = np.isfinite(entry) & (entry > 0)
        for horizon in HORIZONS:
            exit_pos = entry_pos + horizon
            if exit_pos >= len(trade_days):
                continue
            exit_ = open_wide.iloc[exit_pos].reindex(group["_symbol"].to_numpy()).to_numpy(dtype="float64")
            values = np.where(okay_entry & np.isfinite(exit_), exit_ / np.where(okay_entry, entry, 1.0) - 1.0, np.nan)
            panel.loc[index, f"label_{horizon}"] = values
    log("      labels built: " + ", ".join(
        f"h{h}={panel[f'label_{h}'].notna().mean():.1%}" for h in HORIZONS))

    panel.to_csv(OUT / "snapshot_panel.csv.gz", index=False, compression="gzip")

    # ------------------------------------------------------------------ #
    log("[4/5] endpoints")

    def rank_ic_by_date(frame: pd.DataFrame, x_col: str, y_col: str) -> pd.Series:
        tmp = frame[["rebalance_date", x_col, y_col]].dropna()
        if tmp.empty:
            return pd.Series(dtype="float64")
        tmp = tmp.rename(columns={x_col: "x", y_col: "y"})
        grp = tmp.groupby("rebalance_date", sort=True)
        tmp["xr"] = grp["x"].rank(pct=True)
        tmp["yr"] = grp["y"].rank(pct=True)
        g2 = tmp.groupby("rebalance_date", sort=True)
        n = g2["xr"].transform("size")
        mx, my = g2["xr"].transform("mean"), g2["yr"].transform("mean")
        vx, vy = g2["xr"].transform("var"), g2["yr"].transform("var")
        cov = ((tmp["xr"] - mx) * (tmp["yr"] - my)).groupby(tmp["rebalance_date"]).transform("mean")
        with np.errstate(divide="ignore", invalid="ignore"):
            ic = cov / np.sqrt(vx * vy)
        ic = ic.where(n >= 30)
        return pd.Series(ic.to_numpy(), index=tmp.index).groupby(tmp["rebalance_date"]).first().sort_index()

    def summarize(series: pd.Series, label: str) -> dict:
        clean = series.dropna()
        if len(clean) < 8:
            return {"endpoint": label, "n_dates": int(len(clean))}
        std = float(clean.std(ddof=1))
        mean = float(clean.mean())
        by_year = clean.groupby(clean.index.year).mean()
        return {
            "endpoint": label, "n_dates": int(len(clean)),
            "ic_mean": mean, "ic_std": std,
            "icir": mean / std if std > 0 else np.nan,
            "t_stat": mean / std * np.sqrt(len(clean)) if std > 0 else np.nan,
            "positive_rate": float((clean > 0).mean()),
            "abs_ic_mean": abs(mean), "abs_icir": abs(mean / std) if std > 0 else np.nan,
            "year_sign_agreement": int((np.sign(by_year) == np.sign(mean)).sum()),
            "n_year_blocks": int(len(by_year)),
        }

    # Residualise fg_mid on the frozen controls, cross-sectionally per date.
    #
    # NA policy (the protocol froze the control SET, not how to treat missing
    # control values): controls are standardised on their observed values and a
    # missing entry is set to the cross-sectional mean, i.e. 0 after
    # standardisation, so it contributes nothing to that row's fitted value.
    # Dropping rows instead would collapse the sample: `accruals` is only
    # observed for ~1% of rows, which would take 219k rows down to ~1.3k.
    resid_parts = []
    coverage_rows = []
    for date, group in panel.groupby("rebalance_date"):
        valid = group.dropna(subset=["fg_mid"]).copy()
        if len(valid) < 50:
            continue
        matrix = [np.ones(len(valid))]
        for control in CONTROLS:
            column = valid[control].to_numpy(dtype="float64")
            observed = np.isfinite(column)
            coverage_rows.append({"rebalance_date": date, "control": control,
                                  "observed_share": float(observed.mean())})
            if observed.sum() < 10:
                matrix.append(np.zeros(len(valid)))
                continue
            centre = float(np.nanmean(column))
            spread = float(np.nanstd(column))
            standardised = (column - centre) / spread if spread > 0 else column * 0.0
            standardised[~observed] = 0.0
            matrix.append(standardised)
        dummies = pd.get_dummies(valid["l1_code"].astype(str), drop_first=True).to_numpy(dtype="float64")
        design = np.column_stack(matrix + ([dummies] if dummies.size else []))
        y = valid["fg_mid"].to_numpy(dtype="float64")
        coefficients, *_ = np.linalg.lstsq(design, y, rcond=None)
        valid["fg_mid_resid"] = y - design @ coefficients
        resid_parts.append(valid)
    residual = pd.concat(resid_parts, ignore_index=True)
    log(f"      residualised rows={len(residual):,} of {len(panel):,}")
    coverage_frame = pd.DataFrame(coverage_rows)
    if not coverage_frame.empty:
        summary_cov = (coverage_frame.groupby("control")["observed_share"].mean()
                       .sort_values(ascending=False))
        log("      control coverage (mean across dates):")
        for name, share in summary_cov.items():
            log(f"        {name:<12}{share:7.2%}")

    ic_rows, ic_series = [], {}
    for horizon in HORIZONS:
        for name, column in (("fg_mid", "fg_mid"), ("fg_min", "fg_min"), ("fg_resid", "fg_mid_resid")):
            series = rank_ic_by_date(residual if column.endswith("resid") else panel,
                                     column, f"label_{horizon}")
            ic_series[f"{name}__h{horizon}"] = series
            ic_rows.append({**summarize(series, f"{name}__h{horizon}"), "signal": name, "horizon": horizon})
    ic_frame = pd.DataFrame(ic_rows)
    ic_frame.to_csv(OUT / "ic_summary.csv", index=False, encoding="utf-8-sig")
    pd.DataFrame(ic_series).to_csv(OUT / "ic_by_date.csv.gz", compression="gzip")
    print(ic_frame.to_string(index=False))

    corr_rows = []
    for control in ("g2", *CONTROLS):
        pair = panel[["fg_mid", control]].dropna()
        corr_rows.append({"pair": f"fg_mid~{control}", "n": len(pair),
                          "pearson": float(pair["fg_mid"].corr(pair[control])) if len(pair) > 2 else np.nan,
                          "spearman": float(pair["fg_mid"].corr(pair[control], method="spearman")) if len(pair) > 2 else np.nan})
    corr_frame = pd.DataFrame(corr_rows)
    corr_frame.to_csv(OUT / "residual_diagnostics.csv", index=False, encoding="utf-8-sig")
    print()
    print(corr_frame.to_string(index=False))

    # ------------------------------------------------------------------ #
    log("[5/5] decision")
    primary = ic_frame[(ic_frame["signal"] == "fg_resid") & (ic_frame["horizon"] == PRIMARY_HORIZON)]
    if primary.empty:
        decision = {"overall": "not_supported", "reason": "primary endpoint could not be computed"}
    else:
        row = primary.iloc[0]
        agreement = row["year_sign_agreement"]
        agreement = int(agreement) if np.isfinite(agreement) else 0
        blocks = row["n_year_blocks"]
        blocks = int(blocks) if np.isfinite(blocks) else 0
        passes = (np.isfinite(row["abs_ic_mean"]) and np.isfinite(row["abs_icir"])
                  and row["abs_ic_mean"] >= RESID_IC_MIN and row["abs_icir"] >= RESID_ICIR_MIN
                  and agreement >= YEAR_BLOCK_AGREEMENT)
        decision = {
            "overall": "incremental_supported" if passes else "not_supported",
            "primary_endpoint": f"fg_resid h={PRIMARY_HORIZON}",
            "abs_ic_mean": float(row["abs_ic_mean"]) if np.isfinite(row["abs_ic_mean"]) else None,
            "abs_icir": float(row["abs_icir"]) if np.isfinite(row["abs_icir"]) else None,
            "ic_min_required": RESID_IC_MIN,
            "icir_min_required": RESID_ICIR_MIN,
            "year_sign_agreement": agreement,
            "year_blocks": blocks,
            "reason": ("residual IC and ICIR clear the frozen bar with stable sign"
                       if passes else
                       f"residual |IC|={row['abs_ic_mean']:.4f} (need {RESID_IC_MIN}), "
                       f"|ICIR|={row['abs_icir']:.3f} (need {RESID_ICIR_MIN}), "
                       f"year agreement {agreement}/{blocks} (need {YEAR_BLOCK_AGREEMENT})"),
        }
    decision["controls"] = list(CONTROLS)
    decision["protocol"] = "research/protocols/a_share_forecast_growth_signal_protocol_v1.md"
    decision["sample"] = {"start": str(SAMPLE_START.date()), "end": str(SAMPLE_END.date()),
                          "grid_dates": int(grid["rebalance_date"].nunique()),
                          "panel_rows": int(len(panel))}
    (OUT / "decision.json").write_text(json.dumps(decision, indent=2, ensure_ascii=False), encoding="utf-8")
    (OUT / "methodology.json").write_text(json.dumps({
        "generated_utc": started.isoformat(),
        "finished_utc": datetime.now(timezone.utc).isoformat(),
        "signal": "fg_mid = (p_change_min+p_change_max)/2, PIT ann_date<=asof, dedup latest end_date then latest ann_date",
        "staleness_days": STALE_DAYS,
        "label": "open(t+1+h)/open(t+1)-1",
        "horizons": list(HORIZONS),
        "controls": list(CONTROLS),
        "control_source": "analyze_a_share_value_quality_level_factors_extension_v1.build_snapshot + run_daily_signal_pipeline_v1.g2_at",
        "boundary_vs_closed_line": "P1 (positive_event_subtype) tested the forecast CATEGORY as an event; this tests MAGNITUDE as a factor",
    }, indent=2, ensure_ascii=False), encoding="utf-8")

    print()
    print("=" * 78)
    print(" decision")
    print("=" * 78)
    print(json.dumps(decision, indent=2, ensure_ascii=False))
    log("DONE")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
