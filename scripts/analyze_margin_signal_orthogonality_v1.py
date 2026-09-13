#!/usr/bin/env python3
"""Margin signal orthogonality & publication-lag alignment checks (protocol v1).

Q1: verify the margin signal uses T-1 (post-disclosure) values, not the same-day
    future-function value.
Q2: cross-sectional Spearman correlation of rzye_zscore / rzye_chg5d with
    price-volume factors (turnover, volume ratio, momentum, volatility).

Protocol: research/protocols/margin_signal_orthogonality_protocol_v1.md
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

MARGIN_DIR = Path("data/external/tushare/margin_pit_v1/raw")
QLIB_DIR = Path.home() / ".qlib/qlib_data/cn_data_2026"


def load_margin() -> pd.DataFrame:
    """Load all margin_detail days into one long frame (ts_code, datetime, rzye...)."""
    frames = []
    for path in sorted(MARGIN_DIR.glob("*.csv.gz")):
        frame = pd.read_csv(path, compression="gzip")
        frames.append(frame)
    out = pd.concat(frames, ignore_index=True)
    # trade_date is read as int (20160104); parse explicitly to avoid the
    # nanoseconds interpretation of pd.to_datetime(int).
    out["datetime"] = pd.to_datetime(out["trade_date"].astype(str), format="%Y%m%d")
    return out[["ts_code", "datetime", "rzye", "rqye", "rzmre", "rzche", "rzrqye"]]


def qlib_symbol(code: str) -> str:
    number, suffix = code.split(".")
    return f"{suffix}{number}"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, default=Path("output/analysis_fundamental/margin_signal_orthogonality_v1"))
    args = parser.parse_args()
    out = args.output_dir
    if out.exists() and any(out.iterdir()):
        raise FileExistsError(f"Refusing to overwrite existing experiment output: {out}")
    out.mkdir(parents=True, exist_ok=True)

    qlib.init(provider_uri=str(QLIB_DIR), region=REG_CN)
    calendar = pd.DatetimeIndex(pd.to_datetime(pd.read_csv(QLIB_DIR / "calendars" / "day.txt", header=None)[0]))

    print("[1/4] Loading margin data ...", flush=True)
    margin = load_margin()
    print(f"      rows={len(margin)} dates={margin['datetime'].nunique()}", flush=True)

    # ---- Q1: publication-lag alignment -----------------------------------------
    print("[2/4] Q1 lag-alignment check ...", flush=True)
    sample_codes = sorted(margin["ts_code"].unique())[:100]
    sample = margin[margin["ts_code"].isin(sample_codes)].copy()
    sample = sample.sort_values(["ts_code", "datetime"])
    sample["rzye_prev"] = sample.groupby("ts_code")["rzye"].shift(1)  # T-1 visible value

    # Merge qlib close for label computation on a few dates.
    cal_2023 = calendar[(calendar >= "2023-01-01") & (calendar <= "2023-06-30")]
    pivot = sample.pivot_table(index="datetime", columns="ts_code", values="rzye")
    pivot_prev = sample.pivot_table(index="datetime", columns="ts_code", values="rzye_prev")

    aligned_ic, misaligned_ic = [], []
    qlib_codes = [qlib_symbol(c) for c in sample_codes]
    close_df = D.features(qlib_codes, ["$close"], start_time="2023-01-01", end_time="2023-07-31", freq="day")
    close_piv = close_df["$close"].unstack(level="instrument")
    close_piv.columns = [f"{c[2:]}.{c[:2]}" for c in close_piv.columns]

    for i in range(len(cal_2023) - 20):
        t0 = cal_2023[i]
        t20 = cal_2023[i + 20]
        if t0 not in pivot.index or t20 not in close_piv.index:
            continue
        p0 = close_piv.loc[t0].reindex(sample_codes)
        p20 = close_piv.loc[t20].reindex(sample_codes)
        label = p20 / p0 - 1
        # aligned uses T-1 balance at signal time T (need balance at t0-1)
        prev_t0 = cal_2023[i - 1] if i > 0 else t0
        if prev_t0 in pivot_prev.index:
            sig_aligned = pivot_prev.loc[prev_t0].reindex(sample_codes)
            sig_mis = pivot.loc[t0].reindex(sample_codes)
            valid = label.notna() & sig_aligned.notna() & sig_mis.notna() & (sig_aligned > 0) & (sig_mis > 0)
            if valid.sum() < 30:
                continue
            aligned_ic.append((sig_aligned[valid]).corr(label[valid], method="spearman"))
            misaligned_ic.append((sig_mis[valid]).corr(label[valid], method="spearman"))

    lag = pd.DataFrame({
        "aligned_t1": pd.Series(aligned_ic),
        "misaligned_t0": pd.Series(misaligned_ic),
    })
    lag.to_csv(out / "lag_alignment_check.csv", index=False)
    aligned_mean = float(pd.Series(aligned_ic).mean())
    mis_mean = float(pd.Series(misaligned_ic).mean())
    print(f"      aligned(t-1): IC={aligned_mean:.4f}  misaligned(t0): IC={mis_mean:.4f}", flush=True)

    # ---- Q2: cross-sectional orthogonality --------------------------------------
    print("[3/4] Q2 cross-sectional correlations ...", flush=True)
    # Build margin signals on the full panel.
    margin_s = margin.sort_values(["ts_code", "datetime"]).copy()
    g = margin_s.groupby("ts_code")
    margin_s["rzye_chg5d"] = g["rzye"].pct_change(5)
    margin_s["rzye_zscore"] = g["rzye"].transform(
        lambda x: (x - x.rolling(250, min_periods=60).mean()) / x.rolling(250, min_periods=60).std()
    )
    # price-volume factors from qlib ($turn / $float_share absent from bundle;
    # turnover computed via external monthly free_share merged below).
    # Restrict to margin-covered stocks: the signal only exists for them, and
    # it keeps the in-memory feature frame small enough to avoid OOM.
    margin_codes = sorted(margin["ts_code"].unique())
    qlib_codes_all = [qlib_symbol(c) for c in margin_codes]
    pv_fields = [
        "Ref($volume, -1)",
        "Ref($volume, -1)/Mean(Ref($volume, -1), 5)",
        "Ref($close, -21)/Ref($close, -1) - 1",
        "Std($close, 20)/Ref($close, -1)",
    ]
    pv_names = ["volume", "vol_ratio", "mom20", "vol20"]
    pv_df = D.features(qlib_codes_all, pv_fields, start_time="2016-01-01", end_time="2026-08-07", freq="day")
    pv_df.columns = pv_names
    pv = pv_df.reset_index()
    pv["ts_code"] = pv["instrument"].map(lambda s: f"{s[2:]}.{s[:2]}")

    # Merge monthly PIT free_share (万股) to compute daily turnover.
    # $volume unit is 手 (100 shares); free_share unit is 万股.
    from analyze_a_share_value_quality_level_factors_extension_v1 import STYLE_DIR
    size = pd.read_csv(STYLE_DIR / "monthly_free_float_size.csv.gz", compression="gzip",
                       usecols=["ts_code", "asof_date", "free_share"])
    size["asof_date"] = pd.to_datetime(size["asof_date"], errors="coerce")
    size["ts_code"] = size["ts_code"].astype(str)
    free_share = size.drop_duplicates(["ts_code", "asof_date"]).pivot_table(
        index="asof_date", columns="ts_code", values="free_share", aggfunc="last"
    ).sort_index().ffill()  # rows=asof (138), cols=ts_code
    # nearest asof <= each pv row's datetime; map to row index into the small
    # (138 x n_codes) matrix to avoid materializing a huge (n_rows x n_codes) frame.
    asof_index = pd.DatetimeIndex(free_share.index)
    row_idx = np.clip(asof_index.searchsorted(pv["datetime"].to_numpy()) - 1, 0, len(asof_index) - 1)
    col_idx = np.clip(np.searchsorted(np.array(free_share.columns), pv["ts_code"].to_numpy()), 0, len(free_share.columns) - 1)
    mat = free_share.to_numpy()
    pv["free_share"] = mat[row_idx, col_idx]
    # turnover = volume(手)*100 / (free_share(万股)*10000)
    pv["turnover"] = pv["volume"] * 100.0 / pv["free_share"] / 1e4
    pv = pv.replace([np.inf, -np.inf], np.nan)

    merged = margin_s[["ts_code", "datetime", "rzye", "rzye_chg5d", "rzye_zscore"]].merge(
        pv[["ts_code", "datetime"] + pv_names], on=["ts_code", "datetime"], how="inner"
    )

    daily_corrs = []
    for date, frame in merged.groupby("datetime"):
        row = {"datetime": date}
        for sig in ("rzye_zscore", "rzye_chg5d"):
            for pv_name in pv_names:
                a = frame[sig]
                b = frame[pv_name]
                valid = a.notna() & b.notna() & np.isfinite(a) & np.isfinite(b)
                if valid.sum() < 100:
                    row[f"{sig}__{pv_name}"] = np.nan
                else:
                    row[f"{sig}__{pv_name}"] = a[valid].corr(b[valid], method="spearman")
        daily_corrs.append(row)
    corr = pd.DataFrame(daily_corrs)
    corr.to_csv(out / "cross_section_correlation.csv.gz", index=False, compression="gzip")

    summary_rows = []
    for col in corr.columns:
        if col == "datetime":
            continue
        values = corr[col].dropna()
        summary_rows.append({
            "pair": col,
            "mean": float(values.mean()),
            "std": float(values.std()),
            "abs_mean_gt_0.4_days_ratio": float((values.abs() > 0.4).mean()),
            "days": int(len(values)),
        })
    summary = pd.DataFrame(summary_rows)
    summary.to_csv(out / "correlation_summary.csv", index=False)
    print(summary.to_string(index=False), flush=True)

    # ---- Decision ---------------------------------------------------------------
    print("[4/4] Decision ...", flush=True)
    zscore_rows = summary[summary["pair"].str.startswith("rzye_zscore__")]
    max_abs = float(zscore_rows["mean"].abs().max())
    lag_ok = bool(abs(aligned_mean) >= abs(mis_mean) * 0.7 or abs(aligned_mean - mis_mean) < 0.005)
    orthogonal = bool(max_abs < 0.4)
    decision = {
        "lag_alignment": "aligned_ok" if lag_ok else "misaligned_suspect",
        "lag_aligned_ic": aligned_mean,
        "lag_misaligned_ic": mis_mean,
        "orthogonality": "orthogonal" if orthogonal else "proxy_of_pv_factor",
        "rzye_zscore_max_abs_corr": max_abs,
        "worst_pair": str(zscore_rows.loc[zscore_rows["mean"].abs().idxmax(), "pair"]) if len(zscore_rows) else None,
    }
    (out / "decision.json").write_text(json.dumps(decision, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    methodology = {
        "protocol": "research/protocols/margin_signal_orthogonality_protocol_v1.md",
        "margin_source": str(MARGIN_DIR),
        "pv_factors": {k: v for k, v in zip(pv_names, pv_fields)},
        "zscore_window": 250, "zscore_min_periods": 60,
        "created_at_utc": pd.Timestamp.utcnow().isoformat(),
    }
    (out / "methodology.json").write_text(json.dumps(methodology, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    lines = [
        "融资融券信号正交性与发布滞后对齐检验 v1",
        "=" * 64,
        "",
        "一、发布滞后对齐：",
        f"  aligned(t-1) IC = {aligned_mean:.4f} | misaligned(t0) IC = {mis_mean:.4f} "
        f"→ {'对齐正确' if lag_ok else '疑似未来函数，需按 t-1 重估'}",
        "",
        "二、截面相关性（rzye_zscore / rzye_chg5d vs 价量因子）：",
        summary.to_string(index=False),
        "",
        f"rzye_zscore 最大 |均值相关| = {max_abs:.3f} → {'正交(可进v5过滤层)' if orthogonal else '价量因子代理(降级)'}",
        "",
        "结论边界：本检验只验证对齐与正交性，不重新估计信号有效性。",
    ]
    (out / "orthogonality_report.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("\n".join(lines))


if __name__ == "__main__":
    main()
