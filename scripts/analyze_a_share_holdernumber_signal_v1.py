#!/usr/bin/env python3
"""Shareholder count (holder_num) signal validation.

Signal: quarterly holder_num change ratio (holder_num decrease = chip concentration = bullish).
PIT-safe: uses ann_date (disclosure date) as the signal availability date; entry
on the next trading day's open after ann_date.

Validation: RankIC (h=20/40/60 trading days), orthogonality vs neutral_composite +
momentum, quintile monotonicity.  Signal-layer only.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
import pandas as pd
import qlib
from qlib.config import REG_CN
from qlib.data import D

QLIB_DIR = Path.home() / ".qlib/qlib_data/cn_data_2026"
HOLDER_FILE = Path("data/external/tushare/holdernumber_pit_v1/normalized/holdernumber.csv.gz")
V8_PANEL = Path("output/analysis_fundamental/a_share_value_quality_monthly_strategy_v8_top15/monthly_composite_top15.csv.gz")
HORIZONS = [20, 40, 60]
OUTPUT_DIR = Path("output/analysis_static/a_share_holdernumber_signal_v1")


def qlib_symbol(code: str) -> str:
    n, s = code.split(".")
    return f"{s}{n}"


def load_holder_data() -> pd.DataFrame:
    """Load holder_num, compute quarterly change ratio."""
    df = pd.read_csv(HOLDER_FILE, compression="gzip", dtype={"ts_code": str, "ann_date": str, "end_date": str})
    df["ann_date"] = pd.to_datetime(df["ann_date"], format="%Y%m%d", errors="coerce")
    df["end_date"] = pd.to_datetime(df["end_date"], format="%Y%m%d", errors="coerce")
    df = df.dropna(subset=["ann_date", "holder_num"]).sort_values(["ts_code", "end_date", "ann_date"])
    # Deduplicate: same (ts_code, end_date) keep latest ann_date
    df = df.drop_duplicates(["ts_code", "end_date"], keep="last")

    # Compute change ratio vs previous quarter
    df = df.sort_values(["ts_code", "end_date"]).reset_index(drop=True)
    df["prev_holder_num"] = df.groupby("ts_code")["holder_num"].shift(1)
    df["holder_change"] = (df["holder_num"] - df["prev_holder_num"]) / df["prev_holder_num"]
    # Signal: negative change (fewer holders = concentrated = bullish)
    df["signal"] = -df["holder_change"]  # negate so positive = bullish

    return df.dropna(subset=["signal"])[["ts_code", "ann_date", "end_date", "holder_num", "holder_change", "signal"]]


def load_forward_returns(cal: pd.DatetimeIndex, events: pd.DataFrame) -> pd.DataFrame:
    """Compute forward returns from the day AFTER ann_date (PIT-safe)."""
    all_codes = sorted(events["ts_code"].unique())
    qlib_codes = [qlib_symbol(c) for c in all_codes]
    print(f"      loading $open for {len(qlib_codes)} stocks ...", flush=True)

    frames = []
    for year in range(2021, 2027):
        df = D.features(qlib_codes, ["$open"], start_time=f"{year}-01-01", end_time=f"{year}-12-31", freq="day")
        frames.append(df)
    raw = pd.concat(frames)["$open"].unstack(level="instrument")
    raw.columns = [f"{c[2:]}.{c[:2]}" for c in raw.columns]
    raw = raw.reindex(cal)

    cal_list = list(cal)
    cal_pos = {d: i for i, d in enumerate(cal_list)}

    result_rows = []
    for _, ev in events.iterrows():
        ann_date = ev["ann_date"]
        # Entry = next trading day after ann_date
        future_days = [d for d in cal_list if d > ann_date]
        if not future_days:
            continue
        entry_date = future_days[0]
        entry_pos = cal_pos[entry_date]

        code = ev["ts_code"]
        if code not in raw.columns:
            continue
        entry = raw.loc[entry_date, code] if entry_date in raw.index else np.nan
        if pd.isna(entry) or entry <= 0:
            continue

        for h in HORIZONS:
            exit_pos = entry_pos + h
            if exit_pos >= len(cal_list):
                continue
            exit_date = cal_list[exit_pos]
            exit_ = raw.loc[exit_date, code] if exit_date in raw.index else np.nan
            if pd.isna(exit_) or exit_ <= 0:
                continue
            result_rows.append({
                "ts_code": code, "ann_date": ann_date, "entry_date": entry_date,
                "horizon": h, "ret": exit_ / entry - 1.0, "signal": ev["signal"],
                "holder_change": ev["holder_change"],
            })

    return pd.DataFrame(result_rows)


def compute_ic(df: pd.DataFrame, signal_col: str, h: int) -> dict:
    subset = df[df["horizon"] == h].dropna(subset=[signal_col, "ret"])
    if subset.empty:
        return {"n": 0, "ic_mean": np.nan, "icir": np.nan, "positive_ratio": np.nan}

    # IC = cross-sectional spearman per event date
    daily_ics = subset.groupby("ann_date").apply(
        lambda g: g[signal_col].corr(g["ret"], method="spearman") if len(g) >= 20 else np.nan,
        include_groups=False
    ).dropna()

    if len(daily_ics) < 5:
        return {"n": len(daily_ics), "ic_mean": np.nan, "icir": np.nan, "positive_ratio": np.nan}

    mean = float(daily_ics.mean())
    std = float(daily_ics.std(ddof=1))
    icir = mean / std if std > 0 else np.nan
    return {"n": len(daily_ics), "ic_mean": mean, "icir": icir,
            "positive_ratio": float((daily_ics > 0).mean())}


def compute_quintile(df: pd.DataFrame, signal_col: str, h: int) -> dict:
    subset = df[df["horizon"] == h].dropna(subset=[signal_col, "ret"])
    if subset.empty:
        return {}
    spreads = []
    for date, group in subset.groupby("ann_date"):
        if len(group) < 30:
            continue
        group = group.copy()
        group["q"] = pd.qcut(group[signal_col].rank(method="first"), 5, labels=False) + 1
        means = group.groupby("q")["ret"].mean()
        if len(means) == 5:
            spreads.append(means.iloc[-1] - means.iloc[0])
    if not spreads:
        return {"q5_q1": np.nan, "monotonicity": np.nan}
    s = pd.Series(spreads)
    return {"q5_q1": float(s.mean()), "monotonicity": float((s > 0).mean())}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, default=OUTPUT_DIR)
    args = parser.parse_args()
    out = args.output_dir
    if out.exists() and any(out.iterdir()):
        raise FileExistsError(f"Refusing to overwrite: {out}")
    out.mkdir(parents=True, exist_ok=True)

    qlib.init(provider_uri=str(QLIB_DIR), region=REG_CN)
    cal = pd.DatetimeIndex(pd.to_datetime(pd.read_csv(QLIB_DIR / "calendars" / "day.txt", header=None)[0]))

    print("[1/3] Loading holder_num ...", flush=True)
    events = load_holder_data()
    print(f"      {len(events):,} events, {events.ts_code.nunique()} stocks")
    print(f"      ann_date range: {events.ann_date.min().date()} ~ {events.ann_date.max().date()}")
    print(f"      signal stats: mean={events.signal.mean():.4f} std={events.signal.std():.4f}")

    print("[2/3] Loading forward returns (PIT: entry = next day after ann_date) ...", flush=True)
    rets = load_forward_returns(cal, events)
    print(f"      {len(rets):,} return observations")

    print("[3/3] Analyzing ...", flush=True)

    # IC
    ic_rows = []
    for h in HORIZONS:
        stats = compute_ic(rets, "signal", h)
        ic_rows.append({"signal": "holder_change_neg", "horizon": h, **stats})
    ic_df = pd.DataFrame(ic_rows)
    ic_df.to_csv(out / "ic_by_horizon.csv", index=False)
    print(ic_df.to_string(index=False), flush=True)

    # Quintile
    quintile_rows = []
    for h in HORIZONS:
        stats = compute_quintile(rets, "signal", h)
        if stats:
            quintile_rows.append({"horizon": h, **stats})
    if quintile_rows:
        pd.DataFrame(quintile_rows).to_csv(out / "quintile_spread.csv", index=False)
        print("\nQuintile spread:")
        for r in quintile_rows:
            print(f"  h={r['horizon']}: Q5-Q1={r.get('q5_q1', np.nan):.4f} monotonicity={r.get('monotonicity', np.nan):.2f}")

    # Orthogonality vs neutral_composite (monthly)
    ortho_rows = []
    if V8_PANEL.exists():
        panel = pd.read_csv(V8_PANEL, compression="gzip")
        panel["rebalance_date"] = pd.to_datetime(panel["rebalance_date"])

        # Match: for each month-end, find holder_num events with ann_date <= month-end
        # that are the latest for that stock
        monthly_dates = sorted(panel["rebalance_date"].unique())
        for mdate in monthly_dates:
            # Get latest holder event per stock up to this date
            valid_events = events[events["ann_date"] <= mdate]
            if valid_events.empty:
                continue
            latest = valid_events.sort_values(["ts_code", "ann_date"]).groupby("ts_code").last().reset_index()
            panel_date = panel[panel["rebalance_date"] == mdate]
            merged = latest.merge(panel_date[["ts_code", "neutral_composite"]], on="ts_code", how="inner")
            if len(merged) < 30:
                continue
            corr = merged["signal"].corr(merged["neutral_composite"], method="spearman")
            ortho_rows.append({"date": mdate, "vs": "neutral_composite", "corr": corr})

    ortho_df = pd.DataFrame(ortho_rows)
    if not ortho_df.empty:
        summary = ortho_df.groupby("vs")["corr"].agg(["mean", "std"]).reset_index()
        summary.to_csv(out / "orthogonality.csv", index=False)
        print(f"\nOrthogonality vs neutral_composite:")
        print(summary.to_string(index=False))
        max_corr_nc = float(ortho_df["corr"].abs().mean())
    else:
        max_corr_nc = np.nan
        print("\n(no overlap for orthogonality check)")

    # Decision
    best_h = 40  # primary horizon (quarterly signal, mid-range)
    best_row = ic_df[ic_df["horizon"] == best_h]
    if not best_row.empty:
        best_ic = best_row.iloc[0]["ic_mean"]
        best_icir = best_row.iloc[0]["icir"]
    else:
        best_ic, best_icir = np.nan, np.nan

    viable = pd.notna(best_ic) and best_ic > 0.01 and pd.notna(best_icir) and best_icir > 0.3
    orthogonal = pd.isna(max_corr_nc) or max_corr_nc < 0.3

    if not viable:
        decision = "holdernumber_not_supported"
    elif not orthogonal:
        decision = "holdernumber_not_orthogonal"
    else:
        decision = "holdernumber_viable"

    decision_json = {
        "decision": decision,
        "best_ic_h40": best_ic,
        "best_icir_h40": best_icir,
        "max_corr_vs_neutral_composite": max_corr_nc,
        "n_events": len(events),
        "pit_note": "entry = next trading day after ann_date (no lookahead)",
    }
    (out / "decision.json").write_text(json.dumps(decision_json, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    lines = [
        "股东户数信号验证 v1",
        "=" * 64,
        f"事件数: {len(events):,}, 股票数: {events.ts_code.nunique()}",
        f"信号: holder_change_neg (股东户数环比下降 = 看涨)",
        f"PIT: 入场 = ann_date 后第一个交易日开盘",
        "",
        "RankIC:",
        ic_df.to_string(index=False),
        "",
        f"h=40: IC={best_ic:.4f} ICIR={best_icir:.4f}" if pd.notna(best_ic) else "h=40: N/A",
        f"与 neutral_composite |corr|: {max_corr_nc:.4f}" if pd.notna(max_corr_nc) else "正交性: 未检测",
        "",
        f"判定：{decision}",
        "规则: IC>0.01 且 ICIR>0.3 且 |corr|<0.3 -> viable (门槛低于日频因季度频率)",
    ]
    (out / "strategy_report.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("\n" + "\n".join(lines))


if __name__ == "__main__":
    main()
