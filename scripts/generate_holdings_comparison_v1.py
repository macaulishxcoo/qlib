#!/usr/bin/env python3
"""Generate holdings + per-stock returns for two strategies from 2026-06-30 to latest.

Strategy A: v8+v11 (four-factor top-15, current paper trading)
Strategy B: five-factor top-30 + cap3 (new recommended form)

Outputs per-stock P&L for each strategy from the 2026-06-30 signal date.
"""

import json
from pathlib import Path

import numpy as np
import pandas as pd
import qlib
from qlib.config import REG_CN
from qlib.data import D

QLIB_DIR = Path.home() / ".qlib/qlib_data/cn_data_2026"
BT_START = pd.Timestamp("2026-06-30")
BENCH = "SH000852"

# Strategy A: v8+v11 paper trading holdings (from nav_log, as of 2026-06-30 signal)
# These are the 15 stocks actually held in the paper trading account
STRAT_A_HOLDINGS = [
    "601600.SH", "000933.SZ", "603279.SH", "688819.SH", "601728.SH",
    "600050.SH", "600941.SH", "601877.SH", "002322.SZ", "002532.SZ",
    "002483.SZ", "000100.SZ", "600219.SH", "603680.SH", "603508.SH",
]

# Strategy B: five-factor top-30 + cap3 (from pipeline output)
STRAT_B_FILE = Path("output/live_ledger/signal_2026-06-30.csv")


def qlib_symbol(code: str) -> str:
    n, s = code.split(".")
    return f"{s}{n}"


def load_close(codes: list[str], start, end) -> pd.DataFrame:
    qlib_codes = [qlib_symbol(c) for c in codes] + [BENCH]
    raw = D.features(qlib_codes, ["$close"], start_time=start, end_time=end, freq="day")
    wide = raw["$close"].unstack(level="instrument")
    wide.columns = [BENCH if c == BENCH else f"{c[2:]}.{c[:2]}" for c in wide.columns]
    return wide


def per_stock_pnl(holdings: list[str], close: pd.DataFrame) -> pd.DataFrame:
    """Per-stock return from first available close to last."""
    entry = close.loc[BT_START] if BT_START in close.index else close.iloc[0]
    exit_ = close.iloc[-1]
    rows = []
    for code in holdings:
        if code not in close.columns:
            continue
        p0 = entry.get(code, np.nan)
        p1 = exit_.get(code, np.nan)
        if pd.notna(p0) and pd.notna(p1) and p0 > 0:
            ret = p1 / p0 - 1
            rows.append({"ts_code": code, "entry_close": float(p0), "exit_close": float(p1),
                         "return": float(ret), "weight": 1.0 / len(holdings),
                         "contribution": float(ret) * (1.0 / len(holdings))})
        else:
            rows.append({"ts_code": code, "entry_close": np.nan, "exit_close": np.nan,
                         "return": np.nan, "weight": 1.0 / len(holdings), "contribution": np.nan})
    df = pd.DataFrame(rows).sort_values("return", ascending=False)
    df["rank"] = range(1, len(df) + 1)
    return df


def daily_nav(holdings: list[str], close: pd.DataFrame) -> pd.DataFrame:
    """Equal-weight daily portfolio NAV vs benchmark."""
    rets = close.pct_change(fill_method=None)
    port_rets = rets[holdings].mean(axis=1)
    bench_rets = rets[BENCH] if BENCH in rets.columns else pd.Series(0, index=rets.index)
    nav = (1 + port_rets).cumprod()
    bench_nav = (1 + bench_rets).cumprod()
    return pd.DataFrame({"portfolio_nav": nav, "benchmark_nav": bench_nav,
                         "portfolio_return": port_rets, "benchmark_return": bench_rets,
                         "excess_return": port_rets - bench_rets})


def main():
    qlib.init(provider_uri=str(QLIB_DIR), region=REG_CN)
    cal = pd.DatetimeIndex(pd.to_datetime(pd.read_csv(QLIB_DIR / "calendars" / "day.txt", header=None)[0]))
    end_date = cal[-1]
    print(f"Period: {BT_START.date()} -> {end_date.date()}", flush=True)

    # Strategy B holdings
    strat_b = pd.read_csv(STRAT_B_FILE)
    strat_b_holdings = strat_b[strat_b["action"] != "SELL"]["ts_code"].tolist()
    print(f"Strategy A (v8 top-15): {len(STRAT_A_HOLDINGS)} stocks")
    print(f"Strategy B (5-factor top-30+cap3): {len(strat_b_holdings)} stocks", flush=True)

    all_codes = sorted(set(STRAT_A_HOLDINGS + strat_b_holdings))
    print(f"Loading close for {len(all_codes)} stocks + benchmark ...", flush=True)
    close = load_close(all_codes, BT_START, end_date)
    print(f"Close matrix: {close.shape}", flush=True)

    out = Path("output/holdings_comparison_2026")
    out.mkdir(parents=True, exist_ok=True)

    # Per-stock P&L
    print("\n=== Strategy A: v8 four-factor top-15 ===", flush=True)
    pnl_a = per_stock_pnl(STRAT_A_HOLDINGS, close)
    pnl_a.to_csv(out / "strat_a_v8_top15_per_stock.csv", index=False)
    print(pnl_a[["rank", "ts_code", "entry_close", "exit_close", "return", "contribution"]].to_string(index=False), flush=True)
    port_ret_a = pnl_a["contribution"].sum()
    print(f"\nPortfolio equal-weight return: {port_ret_a:+.2%}")

    print("\n=== Strategy B: five-factor top-30 + cap3 ===", flush=True)
    pnl_b = per_stock_pnl(strat_b_holdings, close)
    pnl_b.to_csv(out / "strat_b_5factor_top30cap3_per_stock.csv", index=False)
    print(pnl_b[["rank", "ts_code", "entry_close", "exit_close", "return", "contribution"]].to_string(index=False), flush=True)
    port_ret_b = pnl_b["contribution"].sum()
    print(f"\nPortfolio equal-weight return: {port_ret_b:+.2%}")

    # Benchmark
    if BENCH in close.columns:
        bench_ret = close[BENCH].iloc[-1] / close[BENCH].loc[BT_START] - 1 if BT_START in close.index else np.nan
        print(f"\nBenchmark (CSI 1000) return: {bench_ret:+.2%}")
        print(f"Strategy A excess: {port_ret_a - bench_ret:+.2%}")
        print(f"Strategy B excess: {port_ret_b - bench_ret:+.2%}")

    # Daily NAV
    nav_a = daily_nav(STRAT_A_HOLDINGS, close)
    nav_a.to_csv(out / "strat_a_daily_nav.csv")
    nav_b = daily_nav(strat_b_holdings, close)
    nav_b.to_csv(out / "strat_b_daily_nav.csv")

    # Summary
    summary = {
        "period": f"{BT_START.date()} to {end_date.date()}",
        "strat_a": {"name": "v8 four-factor top-15", "n_stocks": len(STRAT_A_HOLDINGS),
                     "portfolio_return": float(port_ret_a),
                     "benchmark_return": float(bench_ret) if pd.notna(bench_ret) else None,
                     "excess_return": float(port_ret_a - bench_ret) if pd.notna(bench_ret) else None},
        "strat_b": {"name": "5-factor top-30 + cap3", "n_stocks": len(strat_b_holdings),
                     "portfolio_return": float(port_ret_b),
                     "benchmark_return": float(bench_ret) if pd.notna(bench_ret) else None,
                     "excess_return": float(port_ret_b - bench_ret) if pd.notna(bench_ret) else None},
    }
    (out / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"\n=== Summary ===")
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
