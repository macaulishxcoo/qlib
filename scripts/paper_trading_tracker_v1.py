#!/usr/bin/env python3
"""Paper trading tracker for the value/quality top-15 strategy.

Records daily virtual NAV for the strategy portfolio based on the latest
signal ledger, and computes daily/monthly returns vs the CSI1000 benchmark.

Usage
-----
    conda activate qlib
    # Update paper trading NAV for today (or the latest trading day)
    python scripts/paper_trading_tracker_v1.py --update
    # Show current status
    python scripts/paper_trading_tracker_v1.py --status
    # Initialize with a starting date and capital
    python scripts/paper_trading_tracker_v1.py --init --start-date 2026-07-01 --capital 100000

The tracker reads the latest signal from output/live_ledger/signal_*.csv,
holds that portfolio until the next rebalance signal appears, and records
daily close-to-close returns (equal-weight) vs SH000852.

Records are saved to output/paper_trading/nav_log.csv.
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
BENCHMARK = "SH000852"
LIVE_LEDGER = Path("output/live_ledger")
PAPER_DIR = Path("output/paper_trading")
NAV_FILE = PAPER_DIR / "nav_log.csv"
PORTFOLIO_CAPITAL = 100_000  # 100K strategy allocation


def qlib_symbol(code: str) -> str:
    number, suffix = code.split(".")
    return f"{suffix}{number}"


def load_calendar() -> pd.DatetimeIndex:
    return pd.DatetimeIndex(pd.to_datetime(pd.read_csv(QLIB_DIR / "calendars" / "day.txt", header=None)[0]))


def load_signals(signal_pattern: str = "signal_*.csv") -> pd.DataFrame:
    """Load signal files matching the glob pattern.

    Returns one top-k list per rebalance date.  When multiple files share the
    same rebalance date (e.g. filtered variants), the lexicographically last
    filename wins so the portfolio is never the union of two lists.  Callers
    should pass an explicit pattern (e.g. "signal_*_vt+t5.csv") so the tracked
    strategy arm is unambiguous.
    """
    files = sorted(LIVE_LEDGER.glob(signal_pattern))
    if not files:
        raise SystemExit(f"No signal files found in {LIVE_LEDGER} matching {signal_pattern!r}")
    frames = []
    for f in files:
        df = pd.read_csv(f)
        # Extract date from filename: signal_YYYY-MM-DD[_tag].csv
        date_str = f.stem.replace("signal_", "")[:10]
        df["rebalance_date"] = pd.Timestamp(date_str)
        df["_file"] = f.name
        frames.append(df)
    all_signals = pd.concat(frames, ignore_index=True)
    # Keep only BUY and HOLD (not SELL).
    all_signals = all_signals[all_signals["action"].isin(["BUY", "HOLD"])]
    # Deduplicate per (rebalance_date, ts_code): last file (lexicographic) wins.
    all_signals = all_signals.sort_values("_file").drop_duplicates(
        ["rebalance_date", "ts_code"], keep="last").drop(columns=["_file"])
    return all_signals


def get_holdings_on(date: pd.Timestamp, signals: pd.DataFrame) -> list[str]:
    """Get the list of ts_codes held on a given date (latest rebalance <= date)."""
    valid = signals[signals["rebalance_date"] <= date]
    if valid.empty:
        return []
    latest_rebal = valid["rebalance_date"].max()
    latest = valid[valid["rebalance_date"] == latest_rebal]
    return list(latest["ts_code"])


def load_nav_log() -> pd.DataFrame:
    if NAV_FILE.is_file():
        return pd.read_csv(NAV_FILE, parse_dates=["date"])
    return pd.DataFrame(columns=["date", "nav", "daily_return", "bench_return",
                                  "excess_return", "holdings", "n_holdings",
                                  "is_rebalance_day", "rebalance_date"])


def save_nav_log(df: pd.DataFrame) -> None:
    PAPER_DIR.mkdir(parents=True, exist_ok=True)
    df.to_csv(NAV_FILE, index=False)


def update_nav(start_date: str | None = None, signal_pattern: str = "signal_*.csv") -> None:
    """Update NAV log from the last recorded date (or start_date) to today."""
    qlib.init(provider_uri=str(QLIB_DIR), region=REG_CN)
    cal = load_calendar()
    signals = load_signals(signal_pattern)

    nav_log = load_nav_log()
    today = pd.Timestamp.now().normalize()

    # Determine start point
    if not nav_log.empty:
        last_recorded = nav_log["date"].max()
        # Start from the day after the last recorded
        start = cal[cal > last_recorded]
    elif start_date:
        start_from = pd.Timestamp(start_date)
        start = cal[cal >= start_from]
        # Initialize NAV
        nav_log = pd.DataFrame([{
            "date": start[0] - pd.Timedelta(days=1) if len(start) > 0 else start_from - pd.Timedelta(days=1),
            "nav": float(PORTFOLIO_CAPITAL), "daily_return": 0.0, "bench_return": 0.0,
            "excess_return": 0.0, "holdings": "", "n_holdings": 0,
            "is_rebalance_day": False, "rebalance_date": "",
        }])
        # Actually start from the first trading day
        start = cal[cal >= start_from]
    else:
        raise SystemExit("No existing NAV log. Use --init --start-date YYYY-MM-DD to initialize.")

    if start.empty or start[0] > today:
        print(f"[skip] already up to date (last recorded: {nav_log['date'].max().date() if not nav_log.empty else 'N/A'})")
        return

    # Limit to today
    start = start[start <= today]
    print(f"[update] {len(start)} trading days to process: {start[0].date()} .. {start[-1].date()}")

    # Load close prices for all held stocks + benchmark
    all_holdings = set()
    for d in start:
        holdings = get_holdings_on(d, signals)
        all_holdings.update(holdings)

    if not all_holdings:
        print("[skip] no holdings found in any signal file")
        return

    qlib_codes = [qlib_symbol(c) for c in sorted(all_holdings)] + [BENCHMARK]
    price_start = start[0] - pd.Timedelta(days=10)
    raw = D.features(qlib_codes, ["$close"], start_time=price_start, end_time=start[-1], freq="day")
    close_wide = raw["$close"].unstack(level="instrument")
    close_wide.columns = [f"{c[2:]}.{c[:2]}" if c != BENCHMARK else BENCHMARK for c in close_wide.columns]
    close_wide = close_wide.reindex(cal)

    # Get the starting NAV
    if not nav_log.empty:
        prev_nav = nav_log.iloc[-1]["nav"]
    else:
        prev_nav = float(PORTFOLIO_CAPITAL)

    new_rows = []
    for day in start:
        holdings = get_holdings_on(day, signals)
        if not holdings:
            # No holdings yet, NAV stays flat
            new_rows.append({
                "date": day, "nav": prev_nav, "daily_return": 0.0,
                "bench_return": 0.0, "excess_return": 0.0,
                "holdings": "", "n_holdings": 0,
                "is_rebalance_day": False, "rebalance_date": "",
            })
            continue

        # Daily returns: equal-weight close-to-close
        prev_day = cal[cal < day][-1] if len(cal[cal < day]) > 0 else None
        if prev_day is None or prev_day not in close_wide.index or day not in close_wide.index:
            continue

        day_rets = []
        for code in holdings:
            if code in close_wide.columns:
                p0 = close_wide.loc[prev_day, code]
                p1 = close_wide.loc[day, code]
                if pd.notna(p0) and pd.notna(p1) and p0 > 0:
                    day_rets.append(p1 / p0 - 1.0)
        port_ret = float(np.nanmean(day_rets)) if day_rets else 0.0

        # Benchmark return
        bench_ret = 0.0
        if BENCHMARK in close_wide.columns:
            b0 = close_wide.loc[prev_day, BENCHMARK]
            b1 = close_wide.loc[day, BENCHMARK]
            if pd.notna(b0) and pd.notna(b1) and b0 > 0:
                bench_ret = float(b1 / b0 - 1.0)

        new_nav = prev_nav * (1 + port_ret)
        excess = port_ret - bench_ret

        # Check if this is a rebalance day
        rebal_dates = set(signals["rebalance_date"].unique())
        is_rebal = day in rebal_dates
        rebal_date = str(day.date()) if is_rebal else ""

        new_rows.append({
            "date": day, "nav": round(new_nav, 2),
            "daily_return": round(port_ret, 6), "bench_return": round(bench_ret, 6),
            "excess_return": round(excess, 6),
            "holdings": ";".join(holdings), "n_holdings": len(holdings),
            "is_rebalance_day": is_rebal, "rebalance_date": rebal_date,
        })
        prev_nav = new_nav

    if new_rows:
        new_df = pd.DataFrame(new_rows)
        nav_log = pd.concat([nav_log, new_df], ignore_index=True)
        nav_log = nav_log.drop_duplicates(subset=["date"], keep="last").sort_values("date")
        save_nav_log(nav_log)
        print(f"[done] recorded {len(new_rows)} days. Latest NAV: {prev_nav:.2f}")
    else:
        print("[done] no new days to record")


def show_status() -> None:
    """Print current paper trading status."""
    if not NAV_FILE.is_file():
        print("No NAV log found. Use --init --start-date YYYY-MM-DD to initialize.")
        return

    nav = pd.read_csv(NAV_FILE, parse_dates=["date"])
    if nav.empty:
        print("NAV log is empty.")
        return

    latest = nav.iloc[-1]
    start_nav = float(PORTFOLIO_CAPITAL)
    total_return = (latest["nav"] / start_nav - 1) * 100

    # Compute benchmark total return
    bench_total = (1 + nav["bench_return"]).prod() - 1
    total_excess = total_return - bench_total * 100

    # Max drawdown
    cummax = nav["nav"].cummax()
    drawdown = (nav["nav"] / cummax - 1) * 100
    max_dd = drawdown.min()

    print("=" * 64)
    print("模拟盘状态 (Paper Trading Status)")
    print("=" * 64)
    print(f"初始资金:         {start_nav:>12,.0f} 元")
    print(f"当前净值:         {latest['nav']:>12,.2f} 元")
    print(f"当前持仓数:       {int(latest['n_holdings']):>12d}")
    print(f"最新日期:         {latest['date'].date()}")
    print(f"运行天数:         {len(nav):>12d}")
    print(f"策略累计收益:     {total_return:>+11.2f}%")
    print(f"基准累计收益:     {bench_total*100:>+11.2f}%")
    print(f"累计超额:         {total_excess:>+11.2f}%")
    print(f"最大回撤:         {max_dd:>+11.2f}%")
    print(f"硬止损线 (NAV):   {start_nav * 0.7:>12,.0f} 元 (-30%)")
    print(f"止损状态:         {'⚠️ 已触发!' if latest['nav'] < start_nav * 0.7 else '✅ 正常'}")

    # Last 5 days
    print(f"\n最近 5 天:")
    print(nav.tail(5)[["date", "nav", "daily_return", "bench_return", "excess_return"]].to_string(index=False))


def main() -> None:
    global PORTFOLIO_CAPITAL
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--update", action="store_true", help="Update NAV to latest trading day")
    group.add_argument("--status", action="store_true", help="Show current status")
    group.add_argument("--init", action="store_true", help="Initialize paper trading (requires --start-date)")
    parser.add_argument("--start-date", default=None, help="Start date for --init (YYYY-MM-DD)")
    parser.add_argument("--capital", type=float, default=PORTFOLIO_CAPITAL, help=f"Starting capital (default {PORTFOLIO_CAPITAL})")
    parser.add_argument("--signal-pattern", default="signal_*.csv",
                        help="Glob pattern selecting which live signal files to track "
                             "(e.g. 'signal_*_vt+t5.csv' for the double-filtered arm)")
    args = parser.parse_args()

    if args.status:
        show_status()
    elif args.init:
        if not args.start_date:
            parser.error("--init requires --start-date YYYY-MM-DD")
        PORTFOLIO_CAPITAL = args.capital
        PAPER_DIR.mkdir(parents=True, exist_ok=True)
        # Create initial NAV entry
        init_df = pd.DataFrame([{
            "date": pd.Timestamp(args.start_date) - pd.Timedelta(days=1),
            "nav": float(args.capital), "daily_return": 0.0, "bench_return": 0.0,
            "excess_return": 0.0, "holdings": "", "n_holdings": 0,
            "is_rebalance_day": False, "rebalance_date": "",
        }])
        save_nav_log(init_df)
        print(f"[init] paper trading initialized: start={args.start_date}, capital={args.capital}")
        update_nav(start_date=args.start_date, signal_pattern=args.signal_pattern)
    elif args.update:
        update_nav(signal_pattern=args.signal_pattern)


if __name__ == "__main__":
    main()
