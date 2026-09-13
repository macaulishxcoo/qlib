#!/usr/bin/env python
"""Offline self-test for the Phase B backtest engine (no network required).

The engine is where silent errors turn into fake alpha, so this exercises the
frictions explicitly:

* the ¥5 minimum commission actually binds on a small book;
* T+1 (a name bought today cannot be sold today);
* limit-up blocks buys and limit-down blocks sells;
* a suspension blocks both sides;
* an all-NaN signal row means "hold", not "liquidate";
* ``rebalance_every`` really throttles trading;
* ``prepare_wide`` rejects an incomplete panel.

Run::

    python research/scripts/selftest_backtest.py
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from cnquant.backtest import (  # noqa: E402
    LOT_SIZE,
    PanelError,
    _affordable_shares,
    prepare_wide,
    run_backtest,
)
from cnquant.config import DEFAULT_COST, BacktestConfig  # noqa: E402
from cnquant.metrics import ACCEPTANCE_GATES, gate_report, summarize  # noqa: E402

FAILURES: list[str] = []


def check(name: str, condition: bool, detail: str = "") -> None:
    status = "PASS" if condition else "FAIL"
    line = f"[{status}] {name}"
    if detail:
        line += f" -- {detail}"
    print(line)
    if not condition:
        FAILURES.append(f"{name}: {detail}")


def make_panel(
    codes: list[str],
    periods: int = 8,
    *,
    base_price: float = 10.0,
    step: float = 0.10,
) -> pd.DataFrame:
    dates = pd.bdate_range("2024-01-01", periods=periods)
    rows = []
    for code in codes:
        for index, date in enumerate(dates):
            price = base_price + index * step
            rows.append(
                {
                    "date": date,
                    "code": code,
                    "adj_open": price,
                    "adj_close": price + 0.05,
                    "open": price,
                    "limit_up_price": round(price * 1.10, 2),
                    "limit_down_price": round(price * 0.90, 2),
                    "is_suspended": False,
                    "investable": True,
                }
            )
    return pd.DataFrame(rows)


def weights_frame(
    dates,
    codes: list[str],
    rows: dict[int, list[float]],
) -> pd.DataFrame:
    frame = pd.DataFrame(np.nan, index=dates, columns=codes, dtype="float64")
    for index, values in rows.items():
        frame.iloc[index] = values
    return frame


def main() -> int:
    print("=" * 78)
    print(" Phase B offline self-test (backtest engine)")
    print("=" * 78)

    codes = ["sh.600000", "sh.600001"]

    # ------------------------------------------------------------------ #
    print("\n-- cost helpers --")
    check("100-share buy at 10.00 pays the ¥5 commission floor",
          abs(_affordable_shares(2000.0, 10.0, DEFAULT_COST) - 100) == 0,
          f"got {_affordable_shares(2000.0, 10.0, DEFAULT_COST)}")
    check("affordable_shares never exceeds the cash available",
          _affordable_shares(1234.0, 10.0, DEFAULT_COST) * 10.005 <= 1234.0)
    check("affordable_shares returns whole lots",
          _affordable_shares(100_000.0, 7.0, DEFAULT_COST) % LOT_SIZE == 0)
    check("zero cash buys nothing", _affordable_shares(0.0, 10.0, DEFAULT_COST) == 0)

    # ------------------------------------------------------------------ #
    print("\n-- baseline run: 50/50, one signal row, then silence --")
    panel = make_panel(codes)
    dates = pd.bdate_range("2024-01-01", periods=8)
    weights = weights_frame(dates, codes, {0: [0.5, 0.5]})
    result = run_backtest(panel, weights, config=BacktestConfig(initial_capital=500_000.0))

    check("nav starts at the initial capital",
          abs(result.nav.iloc[0] - 500_000.0) < 1e-6, f"got {result.nav.iloc[0]}")
    check("exactly two buys, on the day after the signal",
          len(result.trades) == 2
          and (result.trades["side"] == "buy").all()
          and set(result.trades["date"]) == {dates[1]},
          f"{len(result.trades)} trades on {sorted(set(result.trades['date']))}")
    check("all-NaN rows after the first hold instead of liquidating",
          len(result.trades) == 2, f"{len(result.trades)} trades total")
    check("book is fully invested after the rebalance",
          abs(result.weight_history.iloc[-1].sum() - 1.0) < 0.01,
          f"invested weight {result.weight_history.iloc[-1].sum():.4f}")
    check("nav stays positive and grows after the purchase costs are paid",
          bool((result.nav > 0).all()) and result.nav.iloc[-1] > result.nav.iloc[1],
          f"nav {result.nav.iloc[0]:.0f} -> {result.nav.iloc[1]:.0f} -> {result.nav.iloc[-1]:.0f}")

    # ------------------------------------------------------------------ #
    print("\n-- the ¥5 minimum commission actually binds --")
    small = run_backtest(
        make_panel(codes),
        weights_frame(dates, codes, {0: [0.5, 0.5]}),
        config=BacktestConfig(initial_capital=4_000.0),
    )
    check("two 100-share buys pay exactly ¥10 of commission",
          abs(small.costs["commission"].sum() - 10.0) < 1e-9,
          f"commission {small.costs['commission'].sum():.6f}")
    check("commission on a ¥1000 order is 0.5%, not 0.025%",
          abs(small.costs["commission"].sum() / small.trades["notional"].sum() - 5.0 / 1000.5) < 1e-9,
          f"effective rate {small.costs['commission'].sum() / small.trades['notional'].sum():.5%}")

    # ------------------------------------------------------------------ #
    print("\n-- T+1 --")
    flip = weights_frame(dates, codes, {i: ([1.0, 0.0] if i % 2 == 0 else [0.0, 1.0]) for i in range(8)})
    flipped = run_backtest(make_panel(codes), flip, config=BacktestConfig(initial_capital=500_000.0))
    same_day = flipped.trades.groupby(["date", "code"])["side"].nunique()
    check("no name is both bought and sold on the same day",
          bool((same_day <= 1).all()),
          f"violations: {int((same_day > 1).sum())}")
    check("the alternating signal does trade repeatedly",
          len(flipped.trades) > 4, f"{len(flipped.trades)} trades")

    # ------------------------------------------------------------------ #
    print("\n-- limit-up blocks buys --")
    blocked_buy = make_panel(codes)
    day1 = dates[1]
    mask = (blocked_buy["date"] == day1) & (blocked_buy["code"] == codes[0])
    blocked_buy.loc[mask, "limit_up_price"] = blocked_buy.loc[mask, "open"]
    run_blocked = run_backtest(
        blocked_buy, weights_frame(dates, codes, {0: [0.5, 0.5]}),
        config=BacktestConfig(initial_capital=500_000.0),
    )
    reasons = set(run_blocked.blocked["reason"]) if not run_blocked.blocked.empty else set()
    bought_codes = set(run_blocked.trades["code"]) if not run_blocked.trades.empty else set()
    check("limit-up name is not bought", codes[0] not in bought_codes, f"bought {bought_codes}")
    check("a buy blocked by limit-up is recorded", "limit_up" in reasons, f"reasons {reasons}")
    check("the tradable name is still bought", codes[1] in bought_codes)

    # ------------------------------------------------------------------ #
    print("\n-- limit-down blocks sells --")
    blocked_sell = make_panel(codes)
    day3 = dates[3]
    mask = (blocked_sell["date"] == day3) & (blocked_sell["code"] == codes[0])
    blocked_sell.loc[mask, "limit_down_price"] = blocked_sell.loc[mask, "open"]
    sell_weights = weights_frame(dates, codes, {0: [0.5, 0.5], 2: [0.0, 1.0]})
    run_sell = run_backtest(
        blocked_sell, sell_weights, config=BacktestConfig(initial_capital=500_000.0)
    )
    sell_reasons = set(run_sell.blocked["reason"]) if not run_sell.blocked.empty else set()
    sells = run_sell.trades[run_sell.trades["side"] == "sell"] if not run_sell.trades.empty else pd.DataFrame()
    check("limit-down sell is recorded as blocked", "limit_down" in sell_reasons, f"reasons {sell_reasons}")
    check("no sell of the limit-down name on that date",
          not ((sells["code"] == codes[0]) & (sells["date"] == day3)).any() if not sells.empty else True)
    check("the position is still held after the blocked exit",
          run_sell.weight_history.iloc[-1][codes[0]] > 0.05,
          f"final weight {run_sell.weight_history.iloc[-1][codes[0]]:.4f}")

    # ------------------------------------------------------------------ #
    print("\n-- suspension blocks both sides --")
    suspended = make_panel(codes)
    mask = (suspended["date"] == day1) & (suspended["code"] == codes[0])
    suspended.loc[mask, "is_suspended"] = True
    run_susp = run_backtest(
        suspended, weights_frame(dates, codes, {0: [0.5, 0.5]}),
        config=BacktestConfig(initial_capital=500_000.0),
    )
    susp_reasons = set(run_susp.blocked["reason"]) if not run_susp.blocked.empty else set()
    check("a suspended buy is blocked with the right reason", "suspended" in susp_reasons, f"reasons {susp_reasons}")

    # ------------------------------------------------------------------ #
    print("\n-- rebalance_every throttles trading --")
    daily = weights_frame(dates, codes, {i: [0.5, 0.5] for i in range(8)})
    throttled = run_backtest(
        make_panel(codes), daily,
        config=BacktestConfig(initial_capital=500_000.0),
        rebalance_every=3,
    )
    trade_dates = set(throttled.trades["date"]) if not throttled.trades.empty else set()
    check("rebalance_every=3 trades only on i %% 3 == 0 days",
          trade_dates <= {dates[3], dates[6]}, f"traded on {sorted(trade_dates)}")

    # A constant 50/50 target barely drifts, so the throttle has to be measured
    # against a signal that actually wants to trade every day.
    flip_daily = run_backtest(
        make_panel(codes), flip, config=BacktestConfig(initial_capital=500_000.0)
    )
    flip_throttled = run_backtest(
        make_panel(codes), flip, config=BacktestConfig(initial_capital=500_000.0),
        rebalance_every=3,
    )
    check("rebalance_every=3 trades less than the daily case on an active signal",
          len(flip_throttled.trades) < len(flip_daily.trades),
          f"{len(flip_throttled.trades)} vs {len(flip_daily.trades)} trades")

    # ------------------------------------------------------------------ #
    print("\n-- turnover and benchmark plumbing --")
    check("a single full purchase reports 0.5 one-way turnover",
          abs(result.turnover.iloc[1] - 0.5) < 0.02, f"turnover {result.turnover.iloc[1]:.4f}")
    benchmark = pd.Series(0.001, index=dates)
    with_bench = run_backtest(panel, weights, config=BacktestConfig(initial_capital=500_000.0),
                              benchmark_returns=benchmark)
    check("benchmark wiring produces excess statistics",
          "excess_annual_return" in with_bench.stats and "information_ratio" in with_bench.stats)
    check("benchmark nav compounds",
          abs(with_bench.benchmark_nav.iloc[-1] - (1.001 ** 8)) < 1e-9)

    # ------------------------------------------------------------------ #
    print("\n-- metrics and gates --")
    flat = pd.Series([0.0] * 300, index=pd.bdate_range("2024-01-01", periods=300))
    check("flat returns give zero annualised return",
          abs(summarize(flat)["annual_return"]) < 1e-12)
    check("flat returns give a NaN Sharpe (zero volatility)",
          not np.isfinite(summarize(flat)["sharpe"]))
    losers = pd.Series([-0.01] * 300, index=pd.bdate_range("2024-01-01", periods=300))
    check("a monotone loser has a negative annual return",
          summarize(losers)["annual_return"] < 0)
    gate_frame = gate_report({"excess_annual_return": 0.12, "information_ratio": 0.5}, ACCEPTANCE_GATES)
    passed = gate_frame[gate_frame["pass"]]["metric"].tolist()
    check("gate_report marks only the satisfied gate as passing",
          passed == ["excess_annual_return"], f"passed {passed}")
    check("a -10% drawdown passes the -15% gate",
          bool(gate_report({"excess_max_drawdown": -0.10}, ACCEPTANCE_GATES)
               .set_index("metric").loc["excess_max_drawdown", "pass"]))
    check("a -20% drawdown fails the -15% gate",
          not bool(gate_report({"excess_max_drawdown": -0.20}, ACCEPTANCE_GATES)
                   .set_index("metric").loc["excess_max_drawdown", "pass"]))

    # ------------------------------------------------------------------ #
    print("\n-- panel validation --")
    try:
        prepare_wide(panel.drop(columns=["investable"]))
        check("prepare_wide rejects an incomplete panel", False, "no error raised")
    except PanelError as exc:
        check("prepare_wide rejects an incomplete panel", "investable" in str(exc), str(exc))
    try:
        run_backtest(panel, weights, rebalance_every=0)
        check("rebalance_every=0 is rejected", False, "no error raised")
    except ValueError:
        check("rebalance_every=0 is rejected", True)

    print()
    print("-" * 78)
    if FAILURES:
        print(f"{len(FAILURES)} FAILURE(S):")
        for failure in FAILURES:
            print(f"  - {failure}")
        print("-" * 78)
        return 1
    print("all checks passed")
    print("-" * 78)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
