#!/usr/bin/env python
"""Offline self-test for the Phase A universe logic (no network, no baostock).

Exercises the parts of the pipeline that are easy to get subtly wrong and that
silently inflate backtest returns when they are wrong: limit-price rounding,
suspension marking, ST exclusion, listing-age and delisting filters, and the
liquidity/capacity screen.

Run::

    python research/scripts/selftest_core.py
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from cnquant.config import DEFAULT_COST, UniverseRules  # noqa: E402
from cnquant.universe import (  # noqa: E402
    build_investable_mask,
    mark_limit_prices,
    mark_tradability,
    prepare_panel,
    preflight_panel,
    round_half_up,
)

FAILURES: list[str] = []


def check(name: str, condition: bool, detail: str = "") -> None:
    status = "PASS" if condition else "FAIL"
    line = f"[{status}] {name}"
    if detail:
        line += f" -- {detail}"
    print(line)
    if not condition:
        FAILURES.append(f"{name}: {detail}")


def make_raw_panel() -> pd.DataFrame:
    """Three synthetic names covering the interesting filter cases."""
    dates = pd.bdate_range("2024-01-01", periods=40)

    def rows(code: str, base: float, *, st: int = 0, suspended_on: int | None = None,
             amount: float = 5.0e7, limit_up_on: int | None = None) -> list[dict]:
        out = []
        for index, date in enumerate(dates):
            preclose = base + index * 0.01
            is_suspended = suspended_on is not None and index == suspended_on
            close = preclose * 1.10 if limit_up_on is not None and index == limit_up_on else preclose * 1.01
            high = max(close, preclose * 1.02)
            low = min(close, preclose * 0.98)
            out.append(
                {
                    "date": date,
                    "code": code,
                    "open": preclose * 1.005,
                    "high": high,
                    "low": low,
                    "close": close,
                    "preclose": preclose,
                    "volume": 0.0 if is_suspended else 1.0e6,
                    "amount": 0.0 if is_suspended else amount,
                    "turn": 1.0,
                    "pctChg": (close / preclose - 1.0) * 100.0,
                    "tradestatus": 0 if is_suspended else 1,
                    "isST": st,
                    "adj_open": preclose * 1.005,
                    "adj_close": close,
                }
            )
        return out

    raw = (
        rows("sh.600000", 10.0)                       # healthy main-board name
        + rows("sz.000001", 5.0, st=1)                # ST name -> excluded
        + rows("sz.000002", 8.0, suspended_on=5,
               amount=1.0e6, limit_up_on=12)          # illiquid, one suspension, one limit-up
    )
    return pd.DataFrame(raw)


def make_basic() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {"code": "sh.600000", "code_name": "A", "ipo_date": pd.Timestamp("2000-01-01"),
             "out_date": pd.NaT, "sec_type": "1", "status": 1.0},
            {"code": "sz.000001", "code_name": "B", "ipo_date": pd.Timestamp("2000-01-01"),
             "out_date": pd.NaT, "sec_type": "1", "status": 1.0},
            {"code": "sz.000002", "code_name": "C", "ipo_date": pd.Timestamp("2024-01-25"),
             "out_date": pd.Timestamp("2024-02-15"), "sec_type": "1", "status": 0.0},
        ]
    )


def main() -> int:
    print("=" * 78)
    print(" Phase A offline self-test")
    print("=" * 78)

    # --- rounding -----------------------------------------------------------
    check("round_half_up(11.055) == 11.06 (decimal tie, not float floor)",
          float(round_half_up(pd.Series([11.055])).iloc[0]) == 11.06,
          f"got {float(round_half_up(pd.Series([11.055])).iloc[0])}")
    check("round_half_up(9.045) == 9.05 (decimal tie)",
          float(round_half_up(pd.Series([9.045])).iloc[0]) == 9.05,
          f"got {float(round_half_up(pd.Series([9.045])).iloc[0])}")
    check("round_half_up is not banker's rounding",
          float(round_half_up(pd.Series([0.125])).iloc[0]) == 0.13)
    check("round_half_up leaves genuine non-ties alone",
          float(round_half_up(pd.Series([11.054])).iloc[0]) == 11.05
          and float(round_half_up(pd.Series([11.056])).iloc[0]) == 11.06)
    check("round_half_up preserves the Series index",
          list(round_half_up(pd.Series([1.0, 2.0], index=[7, 9])).index) == [7, 9])

    # --- cost model ---------------------------------------------------------
    expected_round_trip = 2 * (0.00025 + 0.00001 + 0.0005) + 0.0005
    check("cost model round_trip == 0.202%",
          abs(DEFAULT_COST.round_trip - expected_round_trip) < 1e-12,
          f"{DEFAULT_COST.round_trip:.6f}")
    doubled = DEFAULT_COST.scaled(2.0)
    check("2x cost stress doubles slippage", abs(doubled.slippage_one_way - 0.001) < 1e-12)
    check("2x cost stress keeps the ¥5 commission floor", doubled.commission_min == 5.0)

    # --- limit prices -------------------------------------------------------
    raw = make_raw_panel()
    basic = make_basic()
    limits = mark_limit_prices(raw)
    first = limits[limits["code"] == "sh.600000"].iloc[0]
    check("non-ST limit up: preclose 10.00 -> 11.00",
          abs(first["preclose"] - 10.0) < 1e-9 and abs(first["limit_up_price"] - 11.00) < 1e-9,
          f"preclose={first['preclose']:.4f} limit_up={first['limit_up_price']}")
    check("non-ST limit down: preclose 10.00 -> 9.00",
          abs(first["limit_down_price"] - 9.00) < 1e-9,
          f"limit_down={first['limit_down_price']}")

    st_first = limits[limits["code"] == "sz.000001"].iloc[0]
    check("ST band is 5%: preclose 5.00 -> 5.25 / 4.75",
          abs(st_first["preclose"] - 5.0) < 1e-9
          and abs(st_first["limit_up_price"] - 5.25) < 1e-9
          and abs(st_first["limit_down_price"] - 4.75) < 1e-9,
          f"st limit_up={st_first['limit_up_price']} limit_down={st_first['limit_down_price']}")

    # A 5.00 preclose must give 5.50 for a non-ST name; this proves the band is
    # actually read from isST rather than being a hard-coded 10%.
    probe_raw = pd.DataFrame(
        [
            {
                "date": pd.Timestamp("2024-01-02"), "code": "sh.600001", "open": 5.0,
                "high": 5.0, "low": 5.0, "close": 5.0, "preclose": 5.0,
                "volume": 1.0e6, "amount": 5.0e7, "turn": 1.0, "pctChg": 0.0,
                "tradestatus": 1, "isST": 0, "adj_close": 5.0,
            }
        ]
    )
    probe = mark_limit_prices(probe_raw).iloc[0]
    check("same preclose 5.00 -> 5.50 when not ST (band is data-driven)",
          abs(probe["limit_up_price"] - 5.50) < 1e-9,
          f"got {probe['limit_up_price']}")

    # --- tradability --------------------------------------------------------
    marked = mark_tradability(limits)    suspended = marked[(marked["code"] == "sz.000002") & (marked["tradestatus"] == 0)]
    check("suspended day is flagged", len(suspended) == 1 and bool(suspended["is_suspended"].iloc[0]))
    check("suspended day cannot be bought or sold",
          bool(suspended["cannot_buy_today"].iloc[0]) and bool(suspended["cannot_sell_today"].iloc[0]))

    limit_up_day = marked[(marked["code"] == "sz.000002") & (marked["isST"] == 0) & marked["close_at_limit_up"]]
    check("limit-up close blocks same-day buying",
          len(limit_up_day) == 1 and bool(limit_up_day["cannot_buy_today"].iloc[0]))

    # --- full pipeline ------------------------------------------------------
    panel = prepare_panel(raw, basic, UniverseRules(), industry=None)

    st_rows = panel[(panel["code"] == "sz.000001") & (panel["date"] >= pd.Timestamp("2024-02-01"))]
    check("ST names are never investable", not st_rows["investable"].any(),
          f"{int(st_rows['investable'].sum())} investable ST rows")

    illiquid = panel[(panel["code"] == "sz.000002") & (panel["date"] >= pd.Timestamp("2024-02-01"))]
    check("¥1e6 ADV fails the ¥5e6 screen", not illiquid["investable"].any(),
          f"{int(illiquid['investable'].sum())} investable illiquid rows")

    young = panel[(panel["code"] == "sz.000002") & (panel["date"] < pd.Timestamp("2024-02-15"))]
    check("listing age < 60 days is excluded", not young["investable"].any(),
          f"{int(young['investable'].sum())} investable young rows")

    delisted = panel[(panel["code"] == "sz.000002") & (panel["date"] > pd.Timestamp("2024-02-15"))]
    check("post-delisting rows are excluded", not delisted["investable"].any(),
          f"{int(delisted['investable'].sum())} investable post-delisting rows")

    healthy = panel[(panel["code"] == "sh.600000") & (panel["date"] >= pd.Timestamp("2024-03-01"))]
    check("healthy name is investable", bool(healthy["investable"].all()),
          f"{int(healthy['investable'].sum())}/{len(healthy)} rows investable")

    # --- include_chinext is a real switch, not a no-op ----------------------
    chinext_basic = pd.concat(
        [basic, pd.DataFrame([{"code": "sz.300001", "code_name": "D",
                               "ipo_date": pd.Timestamp("2010-01-01"), "out_date": pd.NaT,
                               "sec_type": "1", "status": 1.0}])],
        ignore_index=True,
    )
    from cnquant.data import classify_board, select_universe_codes  # noqa: PLC0415

    check("classify_board(sz.300001) == chinext", classify_board("sz.300001") == "chinext")
    check("classify_board(sh.688001) == excluded", classify_board("sh.688001") == "excluded")
    check("classify_board(sh.600000) == main", classify_board("sh.600000") == "main")
    check("创业板 excluded by default",
          "sz.300001" not in set(select_universe_codes(chinext_basic, UniverseRules())["code"]))
    check("创业板 included on request",
          "sz.300001" in set(
              select_universe_codes(chinext_basic, UniverseRules(include_chinext=True))["code"]
          ))
    check("科创板 never enters the universe",
          "sh.688001" not in set(
              select_universe_codes(
                  pd.concat([chinext_basic, pd.DataFrame([{"code": "sh.688001", "code_name": "E",
                                                          "ipo_date": pd.Timestamp("2020-01-01"),
                                                          "out_date": pd.NaT, "sec_type": "1",
                                                          "status": 1.0}])], ignore_index=True),
                  UniverseRules(include_chinext=True),
              )["code"]
          ))

    # --- mask is a pure function of the rule object -------------------------
    strict = build_investable_mask(panel, UniverseRules(min_avg_amount=1.0e12))
    check("absurd liquidity floor empties the universe", int(strict.sum()) == 0)

    # --- panel preflight ----------------------------------------------------
    print("\n-- panel preflight --")
    errors, warnings = preflight_panel(panel)
    check("a well-formed panel passes preflight", not errors, "; ".join(errors))
    check("preflight warns about the optional columns a fixture lacks",
          any("optional" in w for w in warnings), f"{len(warnings)} warnings")

    missing_required = panel.drop(columns=["adj_close"])
    errors, _ = preflight_panel(missing_required)
    check("preflight catches a missing required column",
          any("adj_close" in e for e in errors), "; ".join(errors))

    duplicated = pd.concat([panel, panel.head(1)], ignore_index=True)
    errors, _ = preflight_panel(duplicated)
    check("preflight catches duplicate (date, code) rows",
          any("duplicate" in e for e in errors), "; ".join(errors))

    errors, _ = preflight_panel(panel.iloc[0:0])
    check("preflight catches an empty panel", any("empty" in e for e in errors))

    errors, _ = preflight_panel(panel.assign(investable=False))
    check("preflight catches an entirely uninvestable panel",
          any("investable" in e for e in errors), "; ".join(errors))

    _, thin_warnings = preflight_panel(panel.drop(columns=["turn", "amount"]))
    check("preflight warns rather than errors on missing optional columns",
          any("turn" in w for w in thin_warnings), "; ".join(thin_warnings))

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
