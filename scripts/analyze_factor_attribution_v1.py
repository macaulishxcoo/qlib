#!/usr/bin/env python3
"""Factor attribution for the v8 value/quality top-15 strategy.

Decomposes the strategy's daily excess returns into:
  - HML (High Minus Low book-to-market factor)
  - SMB (Small Minus Big size factor)
  - MOM (20-day momentum factor)
  - Pure alpha (regression intercept)

If the intercept is statistically significant and positive, the strategy
has genuine stock-picking alpha beyond style exposure.  If it's near zero,
the strategy is essentially a value/small-cap/momentum factor replication.

Method:
  1. Reconstruct daily strategy returns from the v8 panel (holdings + close prices)
  2. Construct daily HML/SMB/MOM factor returns from the full market universe
  3. Run OLS: strategy_excess = alpha + b_hml*HML + b_smb*SMB + b_mom*MOM + epsilon
  4. Report alpha (annualized), t-stat, R², and factor loadings
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd
import qlib
from qlib.config import REG_CN
from qlib.data import D
from scipy import stats

QLIB_DIR = Path.home() / ".qlib/qlib_data/cn_data_2026"
DAILY_BASIC = Path("data/external/tushare/a_share_daily_basic_pit_v1/normalized/daily_basic.csv.gz")
V8_PANEL = Path("output/analysis_fundamental/a_share_value_quality_monthly_strategy_v8_top15/monthly_composite_top15.csv.gz")
BENCHMARK = "SH000852"
BT_START = pd.Timestamp("2016-01-01")
BT_END = pd.Timestamp("2026-06-30")
OUTPUT_DIR = Path("output/analysis_static/a_share_factor_attribution_v1")
STAGES = {
    "development": ("2016-01-01", "2019-12-31"),
    "confirmation": ("2020-01-01", "2022-12-31"),
    "holdout": ("2023-01-01", "2025-06-30"),
    "new_coverage": ("2025-07-01", "2026-06-30"),
    "full": ("2016-01-01", "2026-06-30"),
}


def qlib_symbol(code: str) -> str:
    n, s = code.split(".")
    return f"{s}{n}"


def load_calendar() -> pd.DatetimeIndex:
    return pd.DatetimeIndex(pd.to_datetime(pd.read_csv(QLIB_DIR / "calendars" / "day.txt", header=None)[0]))


def reconstruct_strategy_returns(panel: pd.DataFrame, cal: pd.DatetimeIndex) -> pd.Series:
    """Reconstruct daily equal-weight close-to-close returns from v8 panel."""
    # Get top-15 holdings per month
    top15_by_month = {}
    for date, group in panel.groupby("rebalance_date"):
        top = group.dropna(subset=["neutral_composite"]).nlargest(15, "neutral_composite")
        top15_by_month[pd.Timestamp(date)] = list(top["ts_code"])

    # Load close prices for all held stocks + benchmark
    all_codes = sorted({c for codes in top15_by_month.values() for c in codes})
    qlib_codes = [qlib_symbol(c) for c in all_codes] + [BENCHMARK]
    print(f"      loading $close for {len(all_codes)} stocks + benchmark ...", flush=True)

    frames = []
    for year in range(2015, 2027):
        df = D.features(qlib_codes, ["$close"], start_time=f"{year}-01-01", end_time=f"{year}-12-31", freq="day")
        frames.append(df)
    raw = pd.concat(frames)["$close"].unstack(level="instrument")
    close_wide = pd.DataFrame()
    for col in raw.columns:
        if col == BENCHMARK:
            close_wide[BENCHMARK] = raw[col]
        else:
            close_wide[f"{col[2:]}.{col[:2]}"] = raw[col]
    close_wide = close_wide.reindex(cal)
    rets = close_wide.pct_change()

    # Build daily portfolio returns
    rebal_dates = sorted(top15_by_month.keys())
    trading_days = cal[(cal >= BT_START) & (cal <= BT_END)]
    bench = rets[BENCHMARK]

    daily_excess = []
    current = None
    for day in trading_days:
        if day in rebal_dates:
            current = top15_by_month[day]
        if current is None or day not in rets.index:
            continue
        day_rets = rets.loc[day].reindex(current).to_numpy(dtype=float)
        port = np.nanmean(day_rets)
        b = bench.loc[day] if day in bench.index and pd.notna(bench.loc[day]) else np.nan
        daily_excess.append({"date": day, "excess": port - b})

    return pd.DataFrame(daily_excess).set_index("date")["excess"]


def construct_factor_returns(cal: pd.DatetimeIndex) -> pd.DataFrame:
    """Construct daily HML, SMB, MOM factor returns from daily_basic.

    HML: long high-BM / short low-BM (30/30 percentile split, equal weight)
    SMB: long small / short big (30/30 percentile split by total_mv)
    MOM: long high-20d-return / short low-20d-return (30/30 split)
    """
    print("      loading daily_basic for factor construction ...", flush=True)
    db = pd.read_csv(DAILY_BASIC, compression="gzip",
                     usecols=["ts_code", "trade_date", "total_mv", "pb"])
    db["trade_date"] = pd.to_datetime(db["trade_date"].astype(str), format="%Y%m%d")
    db = db[(db["trade_date"] >= BT_START - pd.Timedelta(days=60)) & (db["trade_date"] <= BT_END)]
    # BM = 1/PB (book-to-market ratio)
    db["bm"] = 1.0 / db["pb"].clip(lower=0.01)

    # Load close for momentum (sample: use all stocks in daily_basic)
    print("      loading $close for momentum factor (this may take a while) ...", flush=True)
    all_codes = sorted(db["ts_code"].unique())
    # Sample to 2000 stocks to keep it manageable
    if len(all_codes) > 2000:
        np.random.seed(42)
        all_codes = list(np.random.choice(all_codes, 2000, replace=False))

    qlib_codes = [qlib_symbol(c) for c in all_codes] + [BENCHMARK]
    close_frames = []
    for year in range(2015, 2027):
        df = D.features(qlib_codes, ["$close"], start_time=f"{year}-01-01", end_time=f"{year}-12-31", freq="day")
        close_frames.append(df)
    raw_close = pd.concat(frames)["$close"].unstack(level="instrument") if False else pd.concat(close_frames)["$close"].unstack(level="instrument")
    close_wide = pd.DataFrame()
    for col in raw_close.columns:
        if col == BENCHMARK:
            close_wide[BENCHMARK] = raw_close[col]
        else:
            close_wide[f"{col[2:]}.{col[:2]}"] = raw_close[col]
    close_wide = close_wide.reindex(cal)
    daily_rets = close_wide.pct_change()
    mom_20d = daily_rets.rolling(20, min_periods=10).sum()

    # For each trading day, construct factor portfolios
    trading_days = cal[(cal >= BT_START) & (cal <= BT_END)]
    factor_returns = []

    for day in trading_days:
        if day not in close_wide.index:
            continue
        day_db = db[db["trade_date"] == day]
        if len(day_db) < 200:
            continue

        # Merge BM and size from daily_basic with momentum from price data
        day_data = day_db[["ts_code", "bm", "total_mv"]].set_index("ts_code")
        if day in mom_20d.index:
            day_data["mom"] = mom_20d.loc[day]
        day_data = day_data.dropna(subset=["bm", "total_mv"])

        if len(day_data) < 200:
            continue

        # Get next-day returns for factor portfolio returns
        day_pos = cal.get_loc(day)
        if day_pos + 1 >= len(cal):
            continue
        next_day = cal[day_pos + 1]
        if next_day not in daily_rets.index or day not in daily_rets.index:
            continue

        next_rets = daily_rets.loc[next_day]

        # HML: top 30% BM vs bottom 30% BM
        bm_q = day_data["bm"].quantile([0.30, 0.70])
        hi_bm = day_data[day_data["bm"] >= bm_q[0.70]].index
        lo_bm = day_data[day_data["bm"] <= bm_q[0.30]].index
        hi_rets = next_rets.reindex(hi_bm).dropna()
        lo_rets = next_rets.reindex(lo_bm).dropna()
        hml = float(hi_rets.mean() - lo_rets.mean()) if len(hi_rets) > 10 and len(lo_rets) > 10 else np.nan

        # SMB: bottom 30% size vs top 30% size
        mv_q = day_data["total_mv"].quantile([0.30, 0.70])
        small = day_data[day_data["total_mv"] <= mv_q[0.30]].index
        big = day_data[day_data["total_mv"] >= mv_q[0.70]].index
        small_rets = next_rets.reindex(small).dropna()
        big_rets = next_rets.reindex(big).dropna()
        smb = float(small_rets.mean() - big_rets.mean()) if len(small_rets) > 10 and len(big_rets) > 10 else np.nan

        # MOM: top 30% 20d-return vs bottom 30%
        if "mom" in day_data.columns:
            mom_data = day_data.dropna(subset=["mom"])
            if len(mom_data) > 200:
                mom_q = mom_data["mom"].quantile([0.30, 0.70])
                hi_mom = mom_data[mom_data["mom"] >= mom_q[0.70]].index
                lo_mom = mom_data[mom_data["mom"] <= mom_q[0.30]].index
                hi_mom_rets = next_rets.reindex(hi_mom).dropna()
                lo_mom_rets = next_rets.reindex(lo_mom).dropna()
                mom_ret = float(hi_mom_rets.mean() - lo_mom_rets.mean()) if len(hi_mom_rets) > 10 and len(lo_mom_rets) > 10 else np.nan
            else:
                mom_ret = np.nan
        else:
            mom_ret = np.nan

        factor_returns.append({"date": day, "HML": hml, "SMB": smb, "MOM": mom_ret})

    return pd.DataFrame(factor_returns).set_index("date")


def run_regression(excess: pd.Series, factors: pd.DataFrame, label: str,
                   start: str | None = None, end: str | None = None) -> dict:
    """OLS regression: excess = alpha + b*HML + b*SMB + b*MOM + epsilon."""
    # Slice by stage window
    if start and end:
        excess = excess.loc[start:end]
    aligned = pd.DataFrame({"excess": excess}).join(factors).dropna()
    if len(aligned) < 50:
        return {"label": label, "n": len(aligned), "error": "insufficient data"}

    Y = aligned["excess"].values
    X = aligned[["HML", "SMB", "MOM"]].values
    X_with_const = np.column_stack([np.ones(len(X)), X])

    beta, residuals, rank, sv = np.linalg.lstsq(X_with_const, Y, rcond=None)
    Y_pred = X_with_const @ beta
    ss_res = np.sum((Y - Y_pred) ** 2)
    ss_tot = np.sum((Y - Y.mean()) ** 2)
    r_squared = 1 - ss_res / ss_tot if ss_tot > 0 else 0

    # t-stats
    n = len(Y)
    k = X_with_const.shape[1]
    mse = ss_res / (n - k) if n > k else np.nan
    cov = mse * np.linalg.inv(X_with_const.T @ X_with_const)
    se = np.sqrt(np.diag(cov))
    t_stats = beta / se

    # Alpha annualized
    alpha_daily = beta[0]
    alpha_annual = alpha_daily * 238

    return {
        "label": label, "n": n,
        "alpha_daily": float(alpha_daily),
        "alpha_annual": float(alpha_annual),
        "alpha_t": float(t_stats[0]),
        "alpha_pvalue": float(2 * (1 - stats.t.cdf(abs(t_stats[0]), df=n - k))),
        "hml_beta": float(beta[1]), "hml_t": float(t_stats[1]),
        "smb_beta": float(beta[2]), "smb_t": float(t_stats[2]),
        "mom_beta": float(beta[3]), "mom_t": float(t_stats[3]),
        "r_squared": float(r_squared),
    }


def main():
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    qlib.init(provider_uri=str(QLIB_DIR), region=REG_CN)
    cal = load_calendar()

    print("[1/3] Reconstructing strategy daily excess returns ...", flush=True)
    panel = pd.read_csv(V8_PANEL, compression="gzip")
    panel["rebalance_date"] = pd.to_datetime(panel["rebalance_date"])
    strategy_excess = reconstruct_strategy_returns(panel, cal)
    print(f"      {len(strategy_excess)} trading days, "
          f"{strategy_excess.index.min().date()} ~ {strategy_excess.index.max().date()}", flush=True)

    print("[2/3] Constructing HML/SMB/MOM factor returns ...", flush=True)
    factors = construct_factor_returns(cal)
    print(f"      {len(factors)} factor days", flush=True)

    print("[3/3] Running factor attribution regression ...", flush=True)
    results = []
    for stage, (s0, s1) in STAGES.items():
        r = run_regression(strategy_excess, factors, stage, start=s0, end=s1)
        results.append(r)

    results_df = pd.DataFrame(results)
    results_df.to_csv(OUTPUT_DIR / "attribution_by_stage.csv", index=False)
    print(results_df.to_string(index=False), flush=True)

    # Interpretation
    full = next(r for r in results if r["label"] == "full")
    holdout = next(r for r in results if r["label"] == "holdout")

    print("\n" + "=" * 70)
    print("因子归因解读")
    print("=" * 70)

    for label, r in [("全期", full), ("封存期", holdout)]:
        if "error" in r:
            print(f"\n{label}: {r['error']}")
            continue
        alpha_sig = "显著" if r["alpha_pvalue"] < 0.05 else "不显著"
        print(f"\n{label} ({r['n']} 天):")
        print(f"  Pure Alpha (年化): {r['alpha_annual']:+.2%}  t={r['alpha_t']:.2f}  p={r['alpha_pvalue']:.4f}  [{alpha_sig}]")
        print(f"  HML loading: {r['hml_beta']:.3f}  t={r['hml_t']:.2f}")
        print(f"  SMB loading: {r['smb_beta']:.3f}  t={r['smb_t']:.2f}")
        print(f"  MOM loading: {r['mom_beta']:.3f}  t={r['mom_t']:.2f}")
        print(f"  R²: {r['r_squared']:.3f}")

    # Decision
    alpha_annual = full.get("alpha_annual", 0)
    alpha_pval = full.get("alpha_pvalue", 1)
    alpha_sig = alpha_pval < 0.05 and alpha_annual > 0

    if alpha_sig:
        interpretation = "策略存在统计显著的 pure alpha（超越风格暴露的真实选股能力）"
    elif alpha_annual > 0 and alpha_pval < 0.10:
        interpretation = "策略存在弱显著的 pure alpha，但证据不够强"
    else:
        interpretation = "策略的收益主要来自风格暴露（价值/规模/动量），pure alpha 不显著"

    (OUTPUT_DIR / "decision.json").write_text(
        json.dumps({"interpretation": interpretation,
                    "full_alpha_annual": alpha_annual,
                    "full_alpha_pvalue": alpha_pval,
                    "full_r_squared": full.get("r_squared"),
                    "holdout_alpha_annual": holdout.get("alpha_annual"),
                    "holdout_alpha_pvalue": holdout.get("alpha_pvalue"),
                    }, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    print(f"\n结论：{interpretation}")


if __name__ == "__main__":
    main()
