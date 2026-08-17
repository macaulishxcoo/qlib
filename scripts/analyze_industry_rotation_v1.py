#!/usr/bin/env python3
"""Industry rotation signal validation + backtest.

Tests momentum vs reversal at the industry level using 30 SW Level-1 indices.
Monthly rebalance: rank industries by past-N-day return, hold top-3 equal weight.

Signals (frozen, no search):
  - mom_20d:  past 20-day return (momentum)
  - rev_20d: -past 20-day return (reversal)
  - mom_60d:  past 60-day return (medium-term momentum)

Validation: IC (rank correlation with next-month return) + portfolio backtest
(top-3 hold 1 month, equal weight, vs equal-weight all-30 benchmark).
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd

DATA_FILE = Path("data/external/tushare/sw_industry_index_v1/normalized/sw_industry_daily.csv.gz")
OUTPUT_DIR = Path("output/analysis_static/a_share_industry_rotation_v1")

SIGNALS = {"mom_20d": 20, "rev_20d": 20, "mom_60d": 60}
TOP_N = 3          # hold top-3 industries
REBALANCE_FREQ = "M"  # monthly
COST = 0.002      # 0.2% round-trip cost per rebalance


def load_data() -> pd.DataFrame:
    df = pd.read_csv(DATA_FILE, compression="gzip", dtype={"trade_date": str})
    df["date"] = pd.to_datetime(df["trade_date"], format="%Y%m%d")
    df = df.sort_values(["ts_code", "date"]).reset_index(drop=True)
    return df[["ts_code", "industry_name", "date", "close", "pct_chg"]]


def build_monthly_returns(df: pd.DataFrame) -> pd.DataFrame:
    """Compute monthly returns for each industry."""
    df = df.copy()
    df = df.set_index("date")
    # Resample to month-end close
    monthly = df.groupby("ts_code")["close"].resample("M").last().reset_index()
    monthly["month"] = monthly["date"].dt.to_period("M")
    monthly = monthly.sort_values(["ts_code", "date"]).reset_index(drop=True)
    monthly["monthly_ret"] = monthly.groupby("ts_code")["close"].pct_change()
    return monthly.dropna(subset=["monthly_ret"])


def compute_signals(df: pd.DataFrame) -> pd.DataFrame:
    """Compute past-N-day return signals at each month-end."""
    daily = df.copy()
    # For each industry, compute past 20d and 60d returns at month-end
    monthly_ends = daily.groupby("date").size()  # trading days
    # Get month-end trading days
    daily["month"] = daily["date"].dt.to_period("M")
    month_end_dates = daily.groupby("month")["date"].max().sort_values()

    results = []
    for me_date in month_end_dates:
        if me_date < pd.Timestamp("2016-01-01"):
            continue
        day_data = daily[daily["date"] == me_date].set_index("ts_code")
        if len(day_data) < 20:
            continue

        for signal_name, lookback in SIGNALS.items():
            # Get past N trading days ending at me_date
            past_data = daily[daily["date"] <= me_date].sort_values("date")
            for ts_code in day_data.index:
                stock_hist = past_data[past_data["ts_code"] == ts_code].tail(lookback + 1)
                if len(stock_hist) < lookback:
                    continue
                p0 = stock_hist["close"].iloc[0]
                p1 = stock_hist["close"].iloc[-1]
                if p0 > 0:
                    ret = p1 / p0 - 1.0
                    signal_val = -ret if signal_name.startswith("rev") else ret
                    results.append({
                        "date": me_date, "ts_code": ts_code,
                        "industry": day_data.loc[ts_code, "industry_name"],
                        "signal": signal_name, "value": signal_val,
                    })

    return pd.DataFrame(results)


def backtest_rotation(monthly: pd.DataFrame, signals: pd.DataFrame,
                      signal_name: str, top_n: int = TOP_N) -> pd.DataFrame:
    """Backtest: each month, rank by signal, hold top-N for 1 month."""
    sig = signals[signals["signal"] == signal_name].copy()
    sig = sig.sort_values(["date", "value"], ascending=[True, False])

    # For each month-end, pick top-N and compute next-month return
    monthly_ret = monthly[["ts_code", "date", "monthly_ret"]].copy()
    monthly_ret["month"] = monthly_ret["date"].dt.to_period("M")

    portfolio_returns = []
    for me_date, group in sig.groupby("date"):
        top = group.head(top_n)
        next_month = (pd.Timestamp(me_date).to_period("M") + 1).to_timestamp()
        # Find the monthly return for these industries in the NEXT month
        next_rets = monthly_ret[monthly_ret["date"].dt.to_period("M") == next_month.to_period("M")]
        held_rets = next_rets[next_rets["ts_code"].isin(top["ts_code"])]
        if len(held_rets) >= 1:
            port_ret = held_rets["monthly_ret"].mean()
            portfolio_returns.append({
                "date": me_date, "signal": signal_name,
                "port_ret": float(port_ret),
                "n_held": len(held_rets),
                "industries": ", ".join(top["industry"].tolist()),
            })

    return pd.DataFrame(portfolio_returns)


def compute_ic(signals: pd.DataFrame, monthly: pd.DataFrame, signal_name: str) -> dict:
    """Rank IC: correlation between signal rank and next-month return rank."""
    sig = signals[signals["signal"] == signal_name].copy()
    monthly_ret = monthly[["ts_code", "date", "monthly_ret"]].copy()

    ics = []
    for me_date, group in sig.groupby("date"):
        next_month = (pd.Timestamp(me_date).to_period("M") + 1).to_timestamp()
        next_rets = monthly_ret[monthly_ret["date"].dt.to_period("M") == next_month.to_period("M")]
        merged = group.merge(next_rets[["ts_code", "monthly_ret"]], on="ts_code", how="inner")
        if len(merged) >= 10:
            ic = merged["value"].corr(merged["monthly_ret"], method="spearman")
            ics.append({"date": me_date, "ic": ic})

    if not ics:
        return {"signal": signal_name, "ic_mean": np.nan, "icir": np.nan, "positive_ratio": np.nan}

    ic_series = pd.Series([x["ic"] for x in ics])
    mean = float(ic_series.mean())
    std = float(ic_series.std(ddof=1))
    return {
        "signal": signal_name, "n": len(ic_series),
        "ic_mean": mean, "icir": mean / std if std > 0 else np.nan,
        "positive_ratio": float((ic_series > 0).mean()),
    }


def main():
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    print("[1/4] Loading data ...", flush=True)
    df = load_data()
    print(f"      {len(df):,} rows, {df.ts_code.nunique()} industries, "
          f"{df.date.min().date()} ~ {df.date.max().date()}")

    print("[2/4] Building monthly returns ...", flush=True)
    monthly = build_monthly_returns(df)
    print(f"      {len(monthly):,} month-industry observations")

    print("[3/4] Computing signals + IC ...", flush=True)
    signals = compute_signals(df)
    print(f"      {len(signals):,} signal observations")

    # IC
    ic_rows = []
    for sig_name in SIGNALS:
        ic = compute_ic(signals, monthly, sig_name)
        ic_rows.append(ic)
    ic_df = pd.DataFrame(ic_rows)
    ic_df.to_csv(OUTPUT_DIR / "ic_by_signal.csv", index=False)
    print(ic_df.to_string(index=False))

    print("[4/4] Backtesting rotation strategies ...", flush=True)
    # Backtest each signal
    all_benchmarks = monthly.groupby("date")["monthly_ret"].mean().reset_index()
    all_benchmarks.columns = ["date", "bench_ret"]

    bt_rows = []
    yearly_rows = []
    for sig_name in SIGNALS:
        port = backtest_rotation(monthly, signals, sig_name)
        if port.empty:
            continue
        port = port.merge(all_benchmarks, on="date", how="left")
        port["excess"] = port["port_ret"] - port["bench_ret"]
        port["excess_net"] = port["excess"] - COST  # round-trip cost

        # Stats
        excess = port["excess_net"].dropna()
        ann_ret = float(excess.mean() * 12)
        ann_vol = float(excess.std() * np.sqrt(12))
        ir = ann_ret / ann_vol if ann_vol > 0 else np.nan
        cum_excess = float((1 + excess).prod() - 1)

        bt_rows.append({
            "signal": sig_name, "n_months": len(port),
            "ann_excess": ann_ret, "ir": ir,
            "cum_excess": cum_excess,
            "best_month": float(excess.max()), "worst_month": float(excess.min()),
            "positive_ratio": float((excess > 0).mean()),
        })

        # Yearly
        port["year"] = pd.to_datetime(port["date"]).dt.year
        for year, yr in port.groupby("year"):
            yr_excess = yr["excess_net"].dropna()
            if len(yr_excess) >= 3:
                yearly_rows.append({
                    "signal": sig_name, "year": int(year),
                    "excess": float(yr_excess.mean() * 12),
                    "ir": float(yr_excess.mean() / yr_excess.std() * np.sqrt(12)) if yr_excess.std() > 0 else np.nan,
                })

    bt_df = pd.DataFrame(bt_rows)
    bt_df.to_csv(OUTPUT_DIR / "backtest_summary.csv", index=False)
    print(bt_df.to_string(index=False))

    yearly_df = pd.DataFrame(yearly_rows)
    if not yearly_df.empty:
        yearly_df.to_csv(OUTPUT_DIR / "yearly_breakdown.csv", index=False)
        print("\nYearly breakdown:")
        print(yearly_df.pivot(index="year", columns="signal", values="excess").to_string())

    # Decision
    best = bt_df.sort_values("ir", ascending=False).iloc[0] if not bt_df.empty else None
    if best is not None and pd.notna(best["ir"]) and best["ir"] > 0.5:
        decision = "industry_rotation_viable"
    elif best is not None and pd.notna(best["ir"]) and best["ir"] > 0:
        decision = "industry_rotation_weak"
    else:
        decision = "industry_rotation_not_supported"

    decision_json = {
        "decision": decision,
        "best_signal": best["signal"] if best is not None else None,
        "best_ir": float(best["ir"]) if best is not None else np.nan,
        "best_ann_excess": float(best["ann_excess"]) if best is not None else np.nan,
        "cost": COST,
        "top_n": TOP_N,
        "n_industries": 30,
    }
    (OUTPUT_DIR / "decision.json").write_text(
        json.dumps(decision_json, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    lines = [
        "行业轮动信号验证 v1",
        "=" * 64,
        f"30 个申万一级行业指数，月度调仓，持 top-{TOP_N}，成本 {COST:.1%}",
        "",
        "Rank IC（信号排名 vs 下月收益排名）：",
        ic_df.to_string(index=False),
        "",
        "回测（年化超额 vs 等权 30 行业基准，扣成本）：",
        bt_df.to_string(index=False),
        "",
    ]
    if not yearly_df.empty:
        lines += ["分年超额：", yearly_df.pivot(index="year", columns="signal", values="excess").to_string(), ""]
    lines += [f"判定：{decision}"]
    (OUTPUT_DIR / "strategy_report.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("\n" + "\n".join(lines))


if __name__ == "__main__":
    main()
