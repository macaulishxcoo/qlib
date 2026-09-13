#!/usr/bin/env python3
"""Moneyflow signal validation (protocol v1).

Tests whether individual-stock capital flow (moneyflow) contains cross-sectional
alpha independent of the value/quality four-factor composite.

Three signals (frozen, no search):
  - net_mf_5d:  5-day cumulative net_mf_amount / total_mv
  - net_mf_20d: 20-day cumulative net_mf_amount / total_mv
  - elg_net_5d: 5-day cumulative (buy_elg - sell_elg) / total_mv

Validation: RankIC (h=5,10,20), orthogonality vs neutral_composite + momentum,
quintile monotonicity.  Signal-layer only -- no portfolio backtest.

Protocol: research/protocols/a_share_moneyflow_signal_protocol_v1.md
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
MONEYFLOW_FILE = Path("data/external/tushare/moneyflow_pit_v1/normalized/moneyflow.csv.gz")
DAILY_BASIC_FILE = Path("data/external/tushare/a_share_daily_basic_pit_v1/normalized/daily_basic.csv.gz")
V8_PANEL = Path("output/analysis_fundamental/a_share_value_quality_monthly_strategy_v8_top15/monthly_composite_top15.csv.gz")
BENCHMARK = "SH000852"
HORIZONS = [5, 10, 20]
OUTPUT_DIR = Path("output/analysis_static/a_share_moneyflow_signal_v1")
WINDOW_START = "2022-01-01"
WINDOW_END = "2026-08-12"


def qlib_symbol(code: str) -> str:
    n, s = code.split(".")
    return f"{s}{n}"


def load_moneyflow() -> pd.DataFrame:
    """Load normalized moneyflow, parse dates, compute derived signals."""
    df = pd.read_csv(MONEYFLOW_FILE, compression="gzip")
    df["trade_date"] = pd.to_datetime(df["trade_date"].astype(str), format="%Y%m%d")
    df = df[(df["trade_date"] >= WINDOW_START) & (df["trade_date"] <= WINDOW_END)].copy()
    # Compute超大单 net = buy_elg_amount - sell_elg_amount
    df["elg_net"] = df["buy_elg_amount"] - df["sell_elg_amount"]
    return df[["ts_code", "trade_date", "net_mf_amount", "elg_net"]].dropna(subset=["ts_code", "trade_date"])


def load_total_mv() -> pd.DataFrame:
    """Load daily total_mv for signal normalization."""
    db = pd.read_csv(DAILY_BASIC_FILE, compression="gzip",
                     usecols=["ts_code", "trade_date", "total_mv"])
    db["trade_date"] = pd.to_datetime(db["trade_date"].astype(str), format="%Y%m%d")
    db = db[(db["trade_date"] >= WINDOW_START) & (db["trade_date"] <= WINDOW_END)]
    return db[["ts_code", "trade_date", "total_mv"]]


def build_signals(mf: pd.DataFrame, mv: pd.DataFrame) -> pd.DataFrame:
    """Merge moneyflow with total_mv, compute 3 normalized signals.

    IMPORTANT: signals are shifted by 1 day (T-1) to avoid lookahead bias.
    moneyflow on date T includes the full day's transactions (open to close),
    so it is only known after T's close.  We shift the signal to T-1 so that
    the signal used for entry on day T's open is from T-1's close.
    """
    df = mf.merge(mv, on=["ts_code", "trade_date"], how="left")
    df = df.dropna(subset=["total_mv"])
    df["total_mv_yuan"] = df["total_mv"] * 1e4  # 万元 -> 元

    # Normalize by total_mv (in 元), so signal is unitless (fraction of market cap)
    df["net_mf_norm"] = df["net_mf_amount"] / df["total_mv_yuan"]
    df["elg_net_norm"] = df["elg_net"] / df["total_mv_yuan"]

    # Sort by ts_code + date for rolling
    df = df.sort_values(["ts_code", "trade_date"]).reset_index(drop=True)

    # Rolling cumulative signals (past N days, INCLUDING current day T).
    # These are the "raw" cumulative signals up to and including day T.
    for code, group in df.groupby("ts_code"):
        df.loc[group.index, "_net_mf_5d"] = group["net_mf_norm"].rolling(5, min_periods=3).sum()
        df.loc[group.index, "_net_mf_20d"] = group["net_mf_norm"].rolling(20, min_periods=10).sum()
        df.loc[group.index, "_elg_net_5d"] = group["elg_net_norm"].rolling(5, min_periods=3).sum()

    # Shift signals by 1 trading day: signal on T uses moneyflow through T-1.
    # This ensures no lookahead: T-1's moneyflow is known at T's open.
    df = df.sort_values(["ts_code", "trade_date"]).reset_index(drop=True)
    for col in ["_net_mf_5d", "_net_mf_20d", "_elg_net_5d"]:
        new_col = col.lstrip("_")
        df[new_col] = df.groupby("ts_code")[col].shift(1)

    return df[["ts_code", "trade_date", "net_mf_5d", "net_mf_20d", "elg_net_5d"]].dropna()


def load_forward_returns(cal: pd.DatetimeIndex, signals: pd.DataFrame) -> pd.DataFrame:
    """Load open prices for signal stocks, compute forward returns at h=5,10,20."""
    all_codes = sorted(signals["ts_code"].unique())
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

    # For each (ts_code, trade_date) in signals, compute forward returns
    result_rows = []
    signal_dates = sorted(signals["trade_date"].unique())
    for date in signal_dates:
        if date not in cal_pos:
            continue
        pos = cal_pos[date]
        day_signals = signals[signals["trade_date"] == date]

        for h in HORIZONS:
            exit_pos = pos + h
            if exit_pos >= len(cal_list):
                continue
            exit_date = cal_list[exit_pos]

            for _, row in day_signals.iterrows():
                code = row["ts_code"]
                if code not in raw.columns:
                    continue
                entry = raw.loc[date, code] if date in raw.index else np.nan
                exit_ = raw.loc[exit_date, code] if exit_date in raw.index else np.nan
                if pd.isna(entry) or pd.isna(exit_) or entry <= 0:
                    continue
                result_rows.append({
                    "ts_code": code, "trade_date": date, "horizon": h,
                    "ret": exit_ / entry - 1.0,
                    "net_mf_5d": row["net_mf_5d"], "net_mf_20d": row["net_mf_20d"],
                    "elg_net_5d": row["elg_net_5d"],
                })

    return pd.DataFrame(result_rows)


def compute_ic(df: pd.DataFrame, signal_col: str, h: int) -> dict:
    """Compute daily RankIC for one signal at one horizon."""
    subset = df[df["horizon"] == h].dropna(subset=[signal_col, "ret"])
    if subset.empty:
        return {"n": 0, "ic_mean": np.nan, "icir": np.nan, "positive_ratio": np.nan}

    daily_ics = subset.groupby("trade_date").apply(
        lambda g: g[signal_col].corr(g["ret"], method="spearman") if len(g) >= 20 else np.nan,
        include_groups=False
    ).dropna()

    if len(daily_ics) < 10:
        return {"n": len(daily_ics), "ic_mean": np.nan, "icir": np.nan, "positive_ratio": np.nan}

    mean = float(daily_ics.mean())
    std = float(daily_ics.std(ddof=1))
    icir = mean / std * np.sqrt(len(daily_ics)) if std > 0 else np.nan
    # Actually ICIR = mean/std (not annualized), following the project convention
    icir = mean / std if std > 0 else np.nan
    pos_ratio = float((daily_ics > 0).mean())
    return {"n": len(daily_ics), "ic_mean": mean, "icir": icir, "positive_ratio": pos_ratio,
            "daily_ics": daily_ics}


def compute_quintile_spread(df: pd.DataFrame, signal_col: str, h: int) -> dict:
    """Q5-Q1 spread and monotonicity."""
    subset = df[df["horizon"] == h].dropna(subset=[signal_col, "ret"])
    if subset.empty:
        return {}
    # Average daily: rank within each day, split into 5 groups, average returns
    daily_spreads = []
    for date, group in subset.groupby("trade_date"):
        if len(group) < 50:
            continue
        group = group.copy()
        group["q"] = pd.qcut(group[signal_col].rank(method="first"), 5, labels=False) + 1
        means = group.groupby("q")["ret"].mean()
        if len(means) == 5:
            daily_spreads.append(means.iloc[-1] - means.iloc[0])

    if not daily_spreads:
        return {"q5_q1": np.nan, "monotonicity": np.nan}

    spreads = pd.Series(daily_spreads)
    return {"q5_q1": float(spreads.mean()), "monotonicity": float((spreads > 0).mean())}


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

    print("[1/4] Loading moneyflow ...", flush=True)
    mf = load_moneyflow()
    print(f"      {len(mf):,} rows, {mf.ts_code.nunique()} stocks, "
          f"{mf.trade_date.min().date()} ~ {mf.trade_date.max().date()}", flush=True)

    print("[2/4] Building signals ...", flush=True)
    mv = load_total_mv()
    signals = build_signals(mf, mv)
    print(f"      {len(signals):,} signal-day observations", flush=True)

    print("[3/4] Loading forward returns ...", flush=True)
    rets = load_forward_returns(cal, signals)
    print(f"      {len(rets):,} return observations", flush=True)

    print("[4/4] Analyzing ...", flush=True)

    # --- IC by signal x horizon ---
    signal_cols = ["net_mf_5d", "net_mf_20d", "elg_net_5d"]
    ic_rows = []
    all_daily_ics = {}
    for sig in signal_cols:
        for h in HORIZONS:
            stats = compute_ic(rets, sig, h)
            ic_rows.append({
                "signal": sig, "horizon": h,
                "n_days": stats["n"], "ic_mean": stats["ic_mean"],
                "icir": stats["icir"], "positive_ratio": stats["positive_ratio"],
            })
            if "daily_ics" in stats:
                all_daily_ics[f"{sig}_h{h}"] = stats["daily_ics"]
    ic_df = pd.DataFrame(ic_rows)
    ic_df.to_csv(out / "ic_by_horizon.csv", index=False)
    print(ic_df.to_string(index=False), flush=True)

    # --- Yearly IC (h=10, best signal if any) ---
    yearly_rows = []
    for sig in signal_cols:
        daily_ics = all_daily_ics.get(f"{sig}_h10")
        if daily_ics is not None:
            for year, group in daily_ics.groupby(daily_ics.index.year):
                yearly_rows.append({
                    "signal": sig, "year": year, "n": len(group),
                    "ic_mean": float(group.mean()), "icir": float(group.mean()/group.std()) if group.std() > 0 else np.nan,
                })
    if yearly_rows:
        pd.DataFrame(yearly_rows).to_csv(out / "ic_yearly.csv", index=False)

    # --- Quintile spread ---
    quintile_rows = []
    for sig in signal_cols:
        for h in HORIZONS:
            stats = compute_quintile_spread(rets, sig, h)
            if stats:
                quintile_rows.append({"signal": sig, "horizon": h, **stats})
    if quintile_rows:
        pd.DataFrame(quintile_rows).to_csv(out / "quintile_spread.csv", index=False)
        print("\nQuintile spread (Q5-Q1, h=10):")
        for r in quintile_rows:
            if r["horizon"] == 10:
                print(f"  {r['signal']}: Q5-Q1={r.get('q5_q1', np.nan):.4f} monotonicity={r.get('monotonicity', np.nan):.2f}")

    # --- Orthogonality vs neutral_composite + momentum ---
    print("\nOrthogonality check:", flush=True)
    ortho_rows = []
    # Load v8 panel (monthly neutral_composite)
    if V8_PANEL.exists():
        panel = pd.read_csv(V8_PANEL, compression="gzip")
        panel["rebalance_date"] = pd.to_datetime(panel["rebalance_date"])
    else:
        panel = pd.DataFrame()

    # Compute momentum (20-day past return) from qlib close
    # For orthogonality, use monthly snapshots matching v8 panel dates
    if not panel.empty:
        # Get signals at month-end dates
        monthly_dates = panel["rebalance_date"].unique()
        for date in monthly_dates:
            date_signals = signals[signals["trade_date"] == date]
            if date_signals.empty:
                continue
            panel_date = panel[panel["rebalance_date"] == date]
            merged = date_signals.merge(panel_date[["ts_code", "neutral_composite"]], on="ts_code", how="inner")
            if len(merged) < 50:
                continue
            for sig in signal_cols:
                if sig in merged.columns and "neutral_composite" in merged.columns:
                    corr_nc = merged[sig].corr(merged["neutral_composite"], method="spearman")
                    ortho_rows.append({"date": date, "signal": sig, "vs": "neutral_composite", "corr": corr_nc})

    # --- Momentum orthogonality (20-day past return) ---
    # Compute on daily basis (not just month-end) for a more robust check
    print("      computing momentum orthogonality (20d past return) ...", flush=True)
    all_codes_list = sorted(signals["ts_code"].unique())
    qlib_codes_mom = [qlib_symbol(c) for c in all_codes_list[:2000]]  # sample to save time
    mom_frames = []
    for year in range(2021, 2027):
        df_mom = D.features(qlib_codes_mom, ["$close"], start_time=f"{year}-01-01", end_time=f"{year}-12-31", freq="day")
        mom_frames.append(df_mom)
    mom_close = pd.concat(mom_frames)["$close"].unstack(level="instrument")
    mom_close.columns = [f"{c[2:]}.{c[:2]}" for c in mom_close.columns]
    mom_close = mom_close.reindex(cal)
    mom_rets = mom_close.pct_change()
    mom_20d = mom_rets.rolling(20, min_periods=10).sum()

    # Sample 100 random dates for momentum correlation
    sample_dates = sorted(signals["trade_date"].unique())
    if len(sample_dates) > 100:
        sample_dates = np.random.choice(sample_dates, 100, replace=False)

    for date in sample_dates:
        date_signals = signals[signals["trade_date"] == date]
        if date_signals.empty or date not in mom_20d.index:
            continue
        day_mom = mom_20d.loc[date]
        merged = date_signals.set_index("ts_code").join(day_mom.rename("mom_20d"), how="inner")
        if len(merged) < 50:
            continue
        for sig in signal_cols:
            if sig in merged.columns:
                corr_mom = merged[sig].corr(merged["mom_20d"], method="spearman")
                ortho_rows.append({"date": date, "signal": sig, "vs": "momentum_20d", "corr": corr_mom})

    ortho_df = pd.DataFrame(ortho_rows)
    if not ortho_df.empty:
        summary = ortho_df.groupby(["signal", "vs"])["corr"].agg(["mean", "std"]).reset_index()
        summary.to_csv(out / "orthogonality.csv", index=False)
        print(summary.to_string(index=False), flush=True)
    else:
        print("  (no overlap with v8 panel dates for orthogonality check)", flush=True)

    # --- Decision ---
    # Check best signal at h=10 (primary horizon)
    best = ic_df[ic_df["horizon"] == 10].sort_values("ic_mean", ascending=False)
    if not best.empty:
        best_row = best.iloc[0]
        best_signal = best_row["signal"]
        best_ic = best_row["ic_mean"]
        best_icir = best_row["icir"]
    else:
        best_signal, best_ic, best_icir = "", np.nan, np.nan

    viable = best_ic > 0.02 and best_icir > 0.3

    # Check orthogonality (both vs neutral_composite and momentum)
    orthogonal = True
    max_corr_nc = np.nan
    max_corr_mom = np.nan
    if not ortho_df.empty:
        nc_corrs = ortho_df[(ortho_df["signal"] == best_signal) & (ortho_df["vs"] == "neutral_composite")]["corr"]
        mom_corrs = ortho_df[(ortho_df["signal"] == best_signal) & (ortho_df["vs"] == "momentum_20d")]["corr"]
        if not nc_corrs.empty:
            max_corr_nc = float(nc_corrs.abs().mean())
            orthogonal = orthogonal and (max_corr_nc < 0.3)
        if not mom_corrs.empty:
            max_corr_mom = float(mom_corrs.abs().mean())
            orthogonal = orthogonal and (max_corr_mom < 0.3)

    if not viable:
        decision = "moneyflow_not_supported"
    elif not orthogonal:
        # Determine which correlation is too high
        if pd.notna(max_corr_mom) and max_corr_mom >= 0.3:
            decision = "moneyflow_is_momentum"
        else:
            decision = "moneyflow_not_orthogonal"
    else:
        decision = "moneyflow_viable"

    decision_json = {
        "decision": decision,
        "best_signal": best_signal,
        "best_ic_h10": best_ic,
        "best_icir_h10": best_icir,
        "max_corr_vs_neutral_composite": max_corr_nc,
        "max_corr_vs_momentum_20d": max_corr_mom,
        "signal_shift": "T-1 (no lookahead: signal from T-1 close, entry at T open)",
    }
    (out / "decision.json").write_text(json.dumps(decision_json, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    lines = [
        "个股资金流向（moneyflow）信号验证 v1",
        "=" * 64,
        f"窗口 {WINDOW_START} ~ {WINDOW_END}",
        f"信号: net_mf_5d, net_mf_20d, elg_net_5d",
        "",
        "RankIC（日频截面 Spearman）：",
        ic_df.to_string(index=False),
        "",
        f"最佳信号 (h=10): {best_signal} IC={best_ic:.4f} ICIR={best_icir:.4f}",
        f"与 neutral_composite |corr|: {max_corr_nc:.4f}" if pd.notna(max_corr_nc) else "与 neutral_composite: 未检测",
        f"与 momentum_20d |corr|: {max_corr_mom:.4f}" if pd.notna(max_corr_mom) else "与 momentum: 未检测",
        "",
        f"判定：{decision}",
        "",
        "判定规则：IC>0.02 且 ICIR>0.3 且 |corr|<0.3 -> viable",
    ]
    (out / "strategy_report.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("\n" + "\n".join(lines))


if __name__ == "__main__":
    main()
