#!/usr/bin/env python3
"""Market-timing signal validation (Direction C, step 1).

Tests 3 market-level indicators for predictive power on future SH000852 returns.
This is TIME-SERIES IC (predicting market direction), not cross-sectional IC.

Signals (frozen, no search):
  - north_flow_5d: 5-day mean of north_money (northbound net inflow), z-scored
  - breadth_5d: 5-day mean of % stocks with positive daily change, z-scored
  - margin_chg_5d: 5-day change rate of aggregate margin balance (rzye), z-scored

All signals use T-1 data to predict returns from T's open (no lookahead).
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
HSGT_FILE = Path("data/external/tushare/moneyflow_hsgt_pit_v1/moneyflow_hsgt.csv.gz")
MARGIN_FILE = Path("data/external/tushare/margin_pit_v1/normalized/margin_detail.csv.gz")
MARKET_DAILY_DIR = Path("data/external/tushare/market_daily_v1")
BENCHMARK = "SH000852"
HORIZONS = [5, 10, 20]
ZSCORE_WINDOW = 250  # ~1 year rolling z-score
OUTPUT_DIR = Path("output/analysis_static/a_share_market_timing_signal_v1")


def load_calendar() -> pd.DatetimeIndex:
    return pd.DatetimeIndex(pd.to_datetime(pd.read_csv(QLIB_DIR / "calendars" / "day.txt", header=None)[0]))


def load_north_flow(cal: pd.DatetimeIndex) -> pd.Series:
    """Load northbound net inflow, indexed by calendar date."""
    df = pd.read_csv(HSGT_FILE, compression="gzip", dtype={"trade_date": str})
    df["date"] = pd.to_datetime(df["trade_date"], format="%Y%m%d")
    df = df.set_index("date").sort_index()
    # north_money is in units of 万元
    north = df["north_money"].astype(float)
    # 5-day rolling mean
    north_5d = north.rolling(5, min_periods=3).mean()
    # Z-score over 250-day window
    z = (north_5d - north_5d.rolling(ZSCORE_WINDOW, min_periods=60).mean()) / \
        north_5d.rolling(ZSCORE_WINDOW, min_periods=60).std()
    return z.reindex(cal)


def load_breadth(cal: pd.DatetimeIndex) -> pd.Series:
    """Compute market breadth = % stocks with positive daily return.

    Uses qlib binary store $change field (post-adjusted daily pct change).
    Queries all instruments in batches to compute daily up/down ratio.
    """
    print("      computing breadth from qlib store ...", flush=True)
    # Get all stock instruments (exclude indexes)
    all_txt = QLIB_DIR / "instruments" / "all.txt"
    syms = pd.read_csv(all_txt, sep="\t", header=None, usecols=[0])[0].tolist()
    stock_syms = [s for s in syms if not s.startswith(("SH000", "SZ399"))]

    # Query in yearly batches to avoid memory issues
    # $change is the daily pct change (already in the store)
    daily_up = pd.Series(dtype=float)
    daily_total = pd.Series(dtype=int)

    for year in range(2016, 2027):
        try:
            df = D.features(stock_syms, ["$change"], start_time=f"{year}-01-01", end_time=f"{year}-12-31", freq="day")
            if df.empty:
                continue
            df = df.reset_index()
            df["up"] = (df["$change"] > 0).astype(int)
            year_daily = df.groupby("datetime")["up"].agg(["sum", "count"])
            year_daily.columns = ["up", "total"]
            daily_up = pd.concat([daily_up, year_daily["up"]])
            daily_total = pd.concat([daily_total, year_daily["total"]])
            print(f"        {year}: {len(year_daily)} days", flush=True)
        except Exception as exc:
            print(f"        {year}: FAILED {exc}", flush=True)

    if daily_up.empty:
        return pd.Series(dtype=float)

    # Combine and compute breadth
    combined = pd.DataFrame({"up": daily_up, "total": daily_total}).dropna()
    combined = combined[~combined.index.duplicated(keep="last")].sort_index()
    breadth = combined["up"] / combined["total"]

    # 5-day rolling mean
    breadth_5d = breadth.rolling(5, min_periods=3).mean()
    # Z-score
    z = (breadth_5d - breadth_5d.rolling(ZSCORE_WINDOW, min_periods=60).mean()) / \
        breadth_5d.rolling(ZSCORE_WINDOW, min_periods=60).std()
    return z.reindex(cal)


def load_margin_chg(cal: pd.DatetimeIndex) -> pd.Series:
    """Compute aggregate margin balance change rate."""
    df = pd.read_csv(MARGIN_FILE, compression="gzip",
                     usecols=["trade_date", "rzye"], dtype={"trade_date": str})
    df["date"] = pd.to_datetime(df["trade_date"], format="%Y%m%d")
    # Sum rzye across all stocks per day
    daily_total = df.groupby("date")["rzye"].sum().sort_index()
    # 5-day change rate
    daily_total_5d_ago = daily_total.shift(5)
    chg_5d = (daily_total - daily_total_5d_ago) / daily_total_5d_ago
    # Z-score
    z = (chg_5d - chg_5d.rolling(ZSCORE_WINDOW, min_periods=60).mean()) / \
        chg_5d.rolling(ZSCORE_WINDOW, min_periods=60).std()
    return z.reindex(cal)


def load_benchmark_returns(cal: pd.DatetimeIndex) -> pd.DataFrame:
    """Load SH000852 open prices, compute forward returns at h=5,10,20."""
    raw = D.features([BENCHMARK], ["$open", "$close"], start_time="2015-01-01", end_time="2026-12-31", freq="day")
    open_ = raw.xs(BENCHMARK, level="instrument")["$open"].reindex(cal)
    close_ = raw.xs(BENCHMARK, level="instrument")["$close"].reindex(cal)

    cal_list = list(cal)
    cal_pos = {d: i for i, d in enumerate(cal_list)}

    rows = []
    for i, date in enumerate(cal_list):
        if i < ZSCORE_WINDOW:
            continue
        entry = open_.iloc[i] if date in open_.index else np.nan
        if pd.isna(entry) or entry <= 0:
            continue
        for h in HORIZONS:
            exit_pos = i + h
            if exit_pos >= len(cal_list):
                continue
            exit_date = cal_list[exit_pos]
            exit_ = open_.iloc[exit_pos] if exit_date in open_.index else np.nan
            if pd.isna(exit_) or exit_ <= 0:
                continue
            rows.append({"date": date, "horizon": h, "ret": exit_ / entry - 1.0})

    return pd.DataFrame(rows)


def compute_ts_ic(signals: dict[str, pd.Series], rets: pd.DataFrame) -> pd.DataFrame:
    """Compute time-series IC: correlation between signal at T-1 and return from T."""
    rows = []
    for sig_name, sig_series in signals.items():
        for h in HORIZONS:
            h_rets = rets[rets["horizon"] == h].set_index("date")["ret"]
            # Align: signal at T-1 predicts return starting at T
            # sig_series is indexed by calendar date; shift by 1 to get T-1 signal
            sig_shifted = sig_series.shift(1)
            aligned = pd.DataFrame({"sig": sig_shifted, "ret": h_rets}).dropna()
            if len(aligned) < 50:
                rows.append({"signal": sig_name, "horizon": h, "n": len(aligned),
                            "ic": np.nan, "icir": np.nan, "positive_ratio": np.nan})
                continue

            # Time-series IC = Spearman correlation between signal and return
            ic = aligned["sig"].corr(aligned["ret"], method="spearman")

            # ICIR: split into non-overlapping windows and compute mean/std of IC
            # Use rolling 20-day windows
            window_size = 20
            ics = []
            for start in range(0, len(aligned) - window_size, window_size):
                chunk = aligned.iloc[start:start + window_size]
                if len(chunk) >= 10:
                    ics.append(chunk["sig"].corr(chunk["ret"], method="spearman"))
            ics = pd.Series(ics).dropna()
            icir = float(ics.mean() / ics.std()) if len(ics) > 5 and ics.std() > 0 else np.nan
            pos_ratio = float((ics > 0).mean()) if len(ics) > 5 else np.nan

            rows.append({"signal": sig_name, "horizon": h, "n": len(aligned),
                        "ic": float(ic), "icir": icir, "positive_ratio": pos_ratio})
    return pd.DataFrame(rows)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, default=OUTPUT_DIR)
    args = parser.parse_args()
    out = args.output_dir
    if out.exists() and any(out.iterdir()):
        raise FileExistsError(f"Refusing to overwrite: {out}")
    out.mkdir(parents=True, exist_ok=True)

    qlib.init(provider_uri=str(QLIB_DIR), region=REG_CN)
    cal = load_calendar()

    print("[1/4] Loading northbound flow ...", flush=True)
    north_z = load_north_flow(cal)
    print(f"      {north_z.notna().sum()} valid days")

    print("[2/4] Loading market breadth ...", flush=True)
    breadth_z = load_breadth(cal)
    print(f"      {breadth_z.notna().sum()} valid days")

    print("[3/4] Loading margin change ...", flush=True)
    margin_z = load_margin_chg(cal)
    print(f"      {margin_z.notna().sum()} valid days")

    print("[4/4] Loading benchmark returns + computing IC ...", flush=True)
    rets = load_benchmark_returns(cal)
    print(f"      {len(rets)} return observations", flush=True)

    signals = {
        "north_flow_5d": north_z,
        "breadth_5d": breadth_z,
        "margin_chg_5d": margin_z,
    }

    ic_df = compute_ts_ic(signals, rets)
    ic_df.to_csv(out / "ic_by_horizon.csv", index=False)
    print(ic_df.to_string(index=False), flush=True)

    # Decision: any signal with h=10 IC > 0.05 and ICIR > 0.3?
    h10 = ic_df[ic_df["horizon"] == 10]
    viable_signals = h10[(h10["ic"].abs() > 0.05) & (h10["icir"].abs() > 0.3)]

    if not viable_signals.empty:
        best = viable_signals.iloc[0]
        decision = "market_timing_viable"
        best_signal = best["signal"]
        best_ic = best["ic"]
        best_icir = best["icir"]
    else:
        decision = "market_timing_not_supported"
        best_signal = ""
        best_ic = np.nan
        best_icir = np.nan

    # Yearly IC breakdown for best signal (h=10)
    yearly_rows = []
    if best_signal:
        sig_shifted = signals[best_signal].shift(1)
        h10_rets = rets[rets["horizon"] == 10].set_index("date")["ret"]
        aligned = pd.DataFrame({"sig": sig_shifted, "ret": h10_rets}).dropna()
        for year, group in aligned.groupby(aligned.index.year):
            if len(group) >= 10:
                ic = group["sig"].corr(group["ret"], method="spearman")
                yearly_rows.append({"year": year, "n": len(group), "ic": float(ic)})
    if yearly_rows:
        pd.DataFrame(yearly_rows).to_csv(out / "ic_yearly.csv", index=False)

    decision_json = {
        "decision": decision,
        "best_signal": best_signal,
        "best_ic_h10": best_ic,
        "best_icir_h10": best_icir,
        "note": "time-series IC (predicting market direction, not cross-sectional)",
        "pit": "signal at T-1, return from T open (no lookahead)",
    }
    (out / "decision.json").write_text(json.dumps(decision_json, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    lines = [
        "市场择时信号验证 v1（方向 C 第一步）",
        "=" * 64,
        f"3 个指标: north_flow_5d, breadth_5d, margin_chg_5d",
        f"时序 IC: 信号 T-1 预测 T 开盘起的 SH000852 收益",
        f"z-score 窗口: {ZSCORE_WINDOW} 日",
        "",
        "时序 IC 结果:",
        ic_df.to_string(index=False),
        "",
    ]
    if yearly_rows:
        lines += [
            f"分年度 IC ({best_signal}, h=10):",
            pd.DataFrame(yearly_rows).to_string(index=False),
            "",
        ]
    lines += [
        f"判定：{decision}",
        f"最佳信号: {best_signal or '无'} IC={best_ic:.4f} ICIR={best_icir:.4f}" if best_signal else "无信号通过",
        "规则: h=10 |IC| > 0.05 且 |ICIR| > 0.3 -> viable",
    ]
    (out / "strategy_report.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("\n" + "\n".join(lines))


if __name__ == "__main__":
    main()
