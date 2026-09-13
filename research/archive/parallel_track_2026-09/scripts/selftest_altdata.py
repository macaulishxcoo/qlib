#!/usr/bin/env python
"""Offline self-test for the Phase C alternative-data layer.

The decisive test is :func:`check_point_in_time`: it proves that
``asof_align`` never attaches a value whose true publication date is after the
signal date, **and** that the obvious naive alternative (aligning on the period
the report describes rather than the day it was published) does exactly that.
Without that contrast the invariant assertion alone would be weak -- it would
pass just as happily against a routine that returns NaN everywhere.

Run::

    python research/scripts/selftest_altdata.py
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from cnquant.altdata import (  # noqa: E402
    AlignmentError,
    asof_align,
    earnings_forecast_score,
    institutional_attention,
    lockup_pressure,
    margin_balance_change,
    shareholder_concentration,
    trailing_count,
    trailing_sum,
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


def make_panel(codes=("sh.600000", "sz.000001"), periods: int = 12) -> pd.DataFrame:
    dates = pd.bdate_range("2024-01-01", periods=periods)
    return pd.DataFrame(
        [{"date": date, "code": code} for date in dates for code in codes]
    ).sort_values(["date", "code"]).reset_index(drop=True)


def main() -> int:
    print("=" * 78)
    print(" Phase C offline self-test (alternative data / point-in-time alignment)")
    print("=" * 78)

    panel = make_panel()
    dates = sorted(panel["date"].unique())

    # ------------------------------------------------------------------ #
    print("\n-- as-of alignment picks the latest publication at or before the date --")
    events = pd.DataFrame(
        [
            {"code": "sh.600000", "pub_date": dates[2], "count": 100.0},
            {"code": "sh.600000", "pub_date": dates[6], "count": 90.0},
        ]
    )
    aligned = asof_align(panel, events, ["count"])
    a = aligned[aligned["code"] == "sh.600000"].reset_index(drop=True)
    check("before any publication the value is NaN", bool(np.isnan(a.loc[0, "count"])))
    check("on the publication day the value is available (inclusive)",
          a.loc[2, "count"] == 100.0 and a.loc[2, "pub_age_days"] == 0,
          f"{a.loc[2, 'count']} age {a.loc[2, 'pub_age_days']}")
    expected_age = int((dates[5] - dates[2]) / np.timedelta64(1, "D"))
    check("a later day keeps the previous publication",
          a.loc[5, "count"] == 100.0 and a.loc[5, "pub_age_days"] == expected_age,
          f"{a.loc[5, 'count']} age {a.loc[5, 'pub_age_days']} (expected {expected_age})")
    check("a new publication replaces the old one",
          a.loc[6, "count"] == 90.0 and a.loc[6, "pub_age_days"] == 0)
    b = aligned[aligned["code"] == "sz.000001"]
    check("a code with no events is NaN throughout", bool(b["count"].isna().all()))
    check("row order matches the panel exactly",
          bool((aligned["code"].to_numpy() == panel["code"].to_numpy()).all()))

    stale = asof_align(panel, events, ["count"], max_age_days=2)
    a_stale = stale[stale["code"] == "sh.600000"].reset_index(drop=True)
    check("max_age_days blanks a stale value", bool(np.isnan(a_stale.loc[5, "count"])))
    check("max_age_days keeps a fresh value", a_stale.loc[2, "count"] == 100.0)

    # ------------------------------------------------------------------ #
    print("\n-- the point-in-time invariant, and the naive alternative --")
    # A report describing period d0 was published at d2; a report describing d5
    # was published at d8. At panel date d6 the honest answer is the d0 report.
    pit_events = pd.DataFrame(
        [
            {"code": "sh.600000", "stat_date": dates[0], "pub_date": dates[2], "value": 10.0},
            {"code": "sh.600000", "stat_date": dates[5], "pub_date": dates[8], "value": 99.0},
        ]
    )
    honest = asof_align(panel, pit_events, ["value"], pub_col="pub_date")
    naive = asof_align(panel, pit_events, ["value"], pub_col="stat_date")

    honest_a = honest[honest["code"] == "sh.600000"].reset_index(drop=True)
    naive_a = naive[naive["code"] == "sh.600000"].reset_index(drop=True)

    check("the honest alignment returns the OLD report at d6",
          honest_a.loc[6, "value"] == 10.0, f"got {honest_a.loc[6, 'value']}")
    check("the naive stat-date alignment returns the FUTURE report at d6",
          naive_a.loc[6, "value"] == 99.0, f"got {naive_a.loc[6, 'value']}")

    true_publication = pit_events.set_index(["code", "stat_date"])["pub_date"]
    naive_pub = pd.MultiIndex.from_arrays([naive["code"], naive["pub_date"]])
    resolved = true_publication.reindex(naive_pub).to_numpy()
    leaked = pd.Series(resolved) > naive["date"].to_numpy()
    check("the naive alignment really uses a not-yet-published source",
          int(np.nansum(leaked)) > 0, f"{int(np.nansum(leaked))} leaked rows")

    live = honest["pub_date"].notna().to_numpy()
    check("every honest value comes from a publication at or before the signal date",
          bool((honest.loc[live, "pub_date"].to_numpy() <= honest.loc[live, "date"].to_numpy()).all()))
    check("no honest value has a negative age", bool((honest.loc[live, "pub_age_days"] >= 0).all()))

    # ------------------------------------------------------------------ #
    print("\n-- trailing event windows --")
    events_window = pd.DataFrame(
        [
            {"code": "sh.600000", "date": dates[1], "amount": 5.0},
            {"code": "sh.600000", "date": dates[2], "amount": 7.0},
            {"code": "sh.600000", "date": dates[5], "amount": 11.0},
        ]
    )
    counts = trailing_count(panel, events_window, window_days=3)
    sums = trailing_sum(panel, events_window, "amount", window_days=3)
    c = counts[panel["code"] == "sh.600000"].reset_index(drop=True)
    s = sums[panel["code"] == "sh.600000"].reset_index(drop=True)
    check("no events before the first one", c.loc[0] == 0.0 and s.loc[0] == 0.0)
    check("one event on the day it happens", c.loc[1] == 1.0 and s.loc[1] == 5.0)
    check("two events inside a 3-day window", c.loc[2] == 2.0 and s.loc[2] == 12.0,
          f"count {c.loc[2]} sum {s.loc[2]}")
    check("the window slides past the older events",
          c.loc[5] == 1.0 and s.loc[5] == 11.0,
          f"count {c.loc[5]} sum {s.loc[5]}")
    check("a partially overlapping window keeps only what is inside",
          c.loc[4] == 1.0 and s.loc[4] == 7.0, f"count {c.loc[4]} sum {s.loc[4]}")
    check("a code with no events counts zero", float(counts[panel["code"] == "sz.000001"].sum()) == 0.0)
    lagged = trailing_count(panel, events_window, window_days=3, lag_days=2)
    lagged_c = lagged[panel["code"] == "sh.600000"].reset_index(drop=True)
    check("lag_days makes a very recent event unusable",
          lagged_c.loc[1] == 0.0 and c.loc[1] == 1.0,
          f"lagged {lagged_c.loc[1]} vs unlagged {c.loc[1]}")

    # ------------------------------------------------------------------ #
    print("\n-- factor constructions --")
    frames = []
    for code, values in (("sh.600000", [1000.0, 900.0, 800.0]), ("sz.000001", [500.0, 550.0, 500.0])):
        for index, value in enumerate(values):
            frames.append({"date": dates[index * 3], "code": code, "pub_date": dates[index * 3],
                           "shareholder_count": value})
    holders = pd.DataFrame(frames)
    concentrated = shareholder_concentration(holders)
    check("shareholder_concentration is positive when holder count falls",
          bool(concentrated.iloc[1] > 0), f"{concentrated.iloc[1]:.4f}")
    check("shareholder_concentration is negative when holder count rises",
          bool(concentrated.iloc[4] < 0), f"{concentrated.iloc[4]:.4f}")
    check("the first observation per code has no change to measure",
          bool(np.isnan(concentrated.iloc[0]) and np.isnan(concentrated.iloc[3])))

    # Ordering is tested with a zero magnitude on every row, so the ladder comes
    # purely from the label mapping rather than from the size of the surprise.
    # The list itself is in non-increasing score order (ties keep their relative
    # position under a stable reverse sort), which is what the assertion checks.
    ladder = pd.DataFrame(
        [
            {"code": "A", "pub_date": dates[0], "forecast_type": label, "forecast_change_pct": 0.0}
            for label in ("预增", "扭亏", "略增", "续盈", "减亏", "不确定", "续亏", "略减", "首亏", "预减")
        ]
    )
    ladder_scores = earnings_forecast_score(ladder)
    check("the forecast ladder is non-increasing from bullish to bearish",
          list(ladder_scores) == sorted(ladder_scores, reverse=True),
          ladder_scores.round(2).to_dict())
    check("an upward pre-announcement scores positive", bool(ladder_scores.iloc[0] > 0))
    check("a turnaround to profit is scored as bullish", bool(ladder_scores.iloc[1] > 0),
          f"{ladder_scores.iloc[1]:.3f}")
    check("a profit warning is scored bearish", bool(ladder_scores.iloc[-1] < 0),
          f"{ladder_scores.iloc[-1]:.3f}")

    magnitude = earnings_forecast_score(pd.DataFrame(
        [
            {"code": "A", "pub_date": dates[0], "forecast_type": "预增", "forecast_change_pct": 0.0},
            {"code": "B", "pub_date": dates[0], "forecast_type": "预增", "forecast_change_pct": 300.0},
        ]
    ))
    check("a bigger surprise scores higher within the same label",
          bool(magnitude.iloc[1] > magnitude.iloc[0]),
          f"{magnitude.iloc[1]:.3f} vs {magnitude.iloc[0]:.3f}")
    check("the magnitude term is bounded (tanh, not linear)",
          bool(magnitude.iloc[1] - magnitude.iloc[0] < 1.0),
          f"delta {magnitude.iloc[1] - magnitude.iloc[0]:.3f}")
    check("an unknown label becomes NaN, not zero",
          bool(np.isnan(earnings_forecast_score(
              pd.DataFrame([{"code": "E", "pub_date": dates[0], "forecast_type": "???"}])
          ).iloc[0])))

    visits = pd.DataFrame([{"code": "A", "visit_count": 9.0}])
    check("institutional_attention normalises to a 90-day rate",
          abs(float(institutional_attention(visits, window_days=90).iloc[0]) - 9.0) < 1e-12)

    balances = pd.DataFrame(
        [{"code": "A", "date": dates[i], "margin_balance": v}
         for i, v in enumerate([100.0, 110.0, 121.0])]
    )
    margin = margin_balance_change(balances, window=1)
    check("margin_balance_change measures the trailing change",
          abs(float(margin.iloc[1]) - 0.10) < 1e-9, f"{margin.iloc[1]:.4f}")

    # A lockup expiry is scheduled and announced in advance, so unlike every other
    # input here it is legitimately forward-looking.
    unlocks = pd.DataFrame([{"code": "sh.600000", "release_date": dates[4], "release_ratio": 0.15}])
    pressure = lockup_pressure(panel, unlocks, window_days=6)
    p = pressure[panel["code"] == "sh.600000"].reset_index(drop=True)
    check("lockup pressure is visible BEFORE the release date",
          p.loc[1] > 0, f"d1={p.loc[1]}")
    check("lockup pressure is zero after the window passes",
          p.loc[10] == 0.0, f"d10={p.loc[10]}")

    # ------------------------------------------------------------------ #
    print("\n-- error handling --")
    for name, call in (
        ("missing publication column",
         lambda: asof_align(panel, pd.DataFrame({"code": ["A"], "x": [1.0]}), ["x"])),
        ("missing value column",
         lambda: asof_align(panel, pd.DataFrame({"code": ["A"], "pub_date": [dates[0]]}), ["x"])),
        ("missing trailing date column",
         lambda: trailing_count(panel, pd.DataFrame({"code": ["A"], "amount": [1.0]}))),
        ("missing lockup date column",
         lambda: lockup_pressure(panel, pd.DataFrame({"code": ["A"], "x": [1.0]}))),
    ):
        try:
            call()
            check(f"{name} raises AlignmentError", False, "no error raised")
        except AlignmentError:
            check(f"{name} raises AlignmentError", True)
        except Exception as exc:  # noqa: BLE001
            check(f"{name} raises AlignmentError", False, f"{type(exc).__name__}: {exc}")

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
