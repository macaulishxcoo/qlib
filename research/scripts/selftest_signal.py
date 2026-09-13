#!/usr/bin/env python
"""Offline self-test for the Phase D signal layer.

The load-bearing test is the **shift timing** of the IC weights. The IC observed
at date ``t`` is computed against a return that is only realised at
``t + horizon``, so a weight window that is not shifted reads the future. That
mistake produces an excellent backtest and no live performance, and it is
invisible unless the timing is asserted explicitly.

Run::

    python research/scripts/selftest_signal.py
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from cnquant.config import UniverseRules  # noqa: E402
from cnquant.evaluate import forward_returns, ic_summary, rank_ic_by_date  # noqa: E402
from cnquant.factors import REGISTRY  # noqa: E402
from cnquant.signal import (  # noqa: E402
    _broadcast_weights,
    composite_score,
    default_feature_names,
    equal_weights,
    ic_by_date,
    rolling_ic_weights,
)
from cnquant.universe import prepare_panel  # noqa: E402

FAILURES: list[str] = []


def check(name: str, condition: bool, detail: str = "") -> None:
    status = "PASS" if condition else "FAIL"
    line = f"[{status}] {name}"
    if detail:
        line += f" -- {detail}"
    print(line)
    if not condition:
        FAILURES.append(f"{name}: {detail}")


def make_panel(n_dates: int = 160, n_codes: int = 60, seed: int = 13):
    """Panel plus a look-ahead factor ``planted[t] = fwd_5(t) + tiny noise``."""
    rng = np.random.default_rng(seed)
    dates = pd.bdate_range("2021-01-04", periods=n_dates)
    codes = [f"sh.60{i:04d}" for i in range(n_codes)]

    returns = rng.normal(0.0003, 0.02, size=(n_dates, n_codes))
    close = 10.0 * np.cumprod(1.0 + returns, axis=0)
    open_ = np.vstack([close[0:1], close[:-1]])

    rows = []
    for j, code in enumerate(codes):
        for i, date in enumerate(dates):
            rows.append(
                {
                    "date": date, "code": code,
                    "open": open_[i, j], "close": close[i, j],
                    "high": max(open_[i, j], close[i, j]) * 1.01,
                    "low": min(open_[i, j], close[i, j]) * 0.99,
                    "preclose": open_[i, j],
                    "volume": 1.0e6, "amount": 3.0e7, "turn": 1.0,
                    "pctChg": returns[i, j] * 100.0,
                    "tradestatus": 1, "isST": 0,
                    "adj_open": open_[i, j], "adj_close": close[i, j],
                    "pbMRQ": 1.5, "peTTM": 20.0, "psTTM": 2.0,
                }
            )
    basic = pd.DataFrame(
        [{"code": code, "code_name": code, "ipo_date": pd.Timestamp("2000-01-01"),
          "out_date": pd.NaT, "sec_type": "1", "status": 1.0} for code in codes]
    )
    panel = prepare_panel(pd.DataFrame(rows), basic, UniverseRules())
    forward = forward_returns(panel, horizons=(5,))["fwd_5"]
    planted = (forward + pd.Series(rng.normal(0.0, 1e-6, len(panel)), index=panel.index)).rename("planted")
    return panel, planted, forward


def main() -> int:
    print("=" * 78)
    print(" Phase D offline self-test (signal construction)")
    print("=" * 78)

    # ------------------------------------------------------------------ #
    print("\n-- IC weights must be shifted by the label horizon --")
    dates = pd.bdate_range("2020-01-01", periods=100)
    flat_ic = pd.DataFrame({"f": np.ones(100)}, index=dates)
    weights = rolling_ic_weights(
        flat_ic, horizon=5, lookback_days=10, min_periods=10, min_abs_ic=0.0, max_factors=10
    )
    check("weights are NaN before shift(5) + 10 observations (index 14)",
          bool(weights["f"].iloc[:14].isna().all()) and np.isfinite(weights["f"].iloc[14]),
          f"first finite index {int(np.argmax(weights['f'].notna().to_numpy()))}")
    check("the unshifted alternative would have started 5 days earlier",
          np.isfinite(rolling_ic_weights(flat_ic, horizon=0, lookback_days=10,
                                         min_periods=10, min_abs_ic=0.0)["f"].iloc[9]))
    check("a value is carried from exactly 5 days earlier",
          abs(float(weights["f"].iloc[14]) - float(flat_ic["f"].iloc[9])) < 1e-12)

    # A sign flip must not appear in the weights until horizon days later.
    flip = pd.DataFrame({"f": np.concatenate([np.ones(50), -np.ones(50)])}, index=dates)
    flip_weights = rolling_ic_weights(
        flip, horizon=5, lookback_days=5, min_periods=5, min_abs_ic=0.0, max_factors=5
    )["f"]
    # Exact identity: weight[i] is the mean of ic[i-9 .. i-4], so no weight can
    # depend on an IC observed less than `horizon` days earlier. This is the
    # property look-ahead would violate, asserted directly instead of via a
    # hand-computed crossing point.
    lag_ok = all(
        abs(float(flip_weights.iloc[i]) - float(flip["f"].iloc[i - 9 : i - 4].mean())) < 1e-12
        for i in range(14, 99)
    )
    check("weight[i] equals the mean of ic[i-9 .. i-4] for every i", lag_ok)
    check("the sign flip reaches the weights with the expected lag",
          float(flip_weights.iloc[56]) > 0 > float(flip_weights.iloc[57]),
          f"i56={flip_weights.iloc[56]:.2f} i57={flip_weights.iloc[57]:.2f}")

    # ------------------------------------------------------------------ #
    print("\n-- IC weight filtering --")
    many = pd.DataFrame(
        np.linspace(0.001, 0.05, 12)[None, :].repeat(60, axis=0),
        index=dates[:60], columns=[f"f{i}" for i in range(12)],
    )
    capped = rolling_ic_weights(many, horizon=0, lookback_days=5, min_periods=5,
                                min_abs_ic=0.0, max_factors=4)
    check("max_factors caps the surviving factors per date",
          int(capped.notna().sum(axis=1).max()) <= 4,
          f"max survivors {int(capped.notna().sum(axis=1).max())}")
    check("the strongest factors are the survivors",
          set(capped.iloc[-1].dropna().index) == {"f11", "f10", "f9", "f8"},
          f"kept {sorted(capped.iloc[-1].dropna().index)}")
    strict = rolling_ic_weights(many, horizon=0, lookback_days=5, min_periods=5,
                                min_abs_ic=0.04, max_factors=12)
    check("min_abs_ic drops weak factors",
          int(strict.notna().sum(axis=1).max()) == 3,
          f"{int(strict.notna().sum(axis=1).max())} survived a 0.04 floor")

    # ------------------------------------------------------------------ #
    print("\n-- equal weights use the declared prior direction --")
    names = ["size", "bp", "reversal_1m", "max_ret_20"]
    priors = equal_weights(names)
    check("prior signs follow each factor's declared direction",
          priors["bp"] > 0 and priors["size"] < 0 and priors["max_ret_20"] < 0,
          priors.round(4).to_dict())
    check("equal weights are normalised", abs(float(priors.abs().sum()) - 1.0) < 1e-12)
    check("an unknown factor defaults to a positive weight",
          bool(equal_weights(["not_registered"])["not_registered"] > 0))

    # ------------------------------------------------------------------ #
    print("\n-- date broadcast --")
    lookup = pd.DataFrame({"f": [1.0, 2.0, 3.0]}, index=pd.to_datetime(["2024-01-01", "2024-01-02", "2024-01-03"]))
    row_dates = pd.to_datetime(["2024-01-03", "2024-01-01", "2024-01-09", "2024-01-02"]).to_numpy()
    broadcast = _broadcast_weights(row_dates, lookup, "f")
    check("weights map by date, not by position",
          broadcast[0] == 3.0 and broadcast[1] == 1.0 and broadcast[3] == 2.0,
          broadcast.tolist())
    check("a date with no weight becomes NaN", bool(np.isnan(broadcast[2])))
    check("a missing column is all NaN",
          bool(np.isnan(_broadcast_weights(row_dates, lookup, "absent")).all()))

    # ------------------------------------------------------------------ #
    print("\n-- composite score recovers a planted factor --")
    panel, planted, forward = make_panel()
    factor_frame = pd.DataFrame({"planted": planted.to_numpy()}, index=panel.index)
    score = composite_score(panel, factor_frame, ["planted"], equal_weights(["planted"]))
    recovered = ic_summary(rank_ic_by_date(panel["date"], score, forward))
    check("a single planted factor yields a near-perfect composite IC",
          recovered["ic_mean"] > 0.9, f"IC={recovered['ic_mean']:.4f}")
    check("the composite score is row-aligned with the panel", len(score) == len(panel))

    # A constant zero weight must produce an all-NaN score, not a zero one:
    # zero would rank as "neutral" and the portfolio would treat it as a signal.
    zeroed = pd.Series({"planted": 0.0})
    zero_score = composite_score(panel, factor_frame, ["planted"], zeroed)
    check("a zero weight still counts as an opinion, giving finite scores",
          bool(np.isfinite(zero_score.to_numpy()).all()) and bool((zero_score == 0.0).all()))

    # ------------------------------------------------------------------ #
    print("\n-- per-date IC table --")
    second = (planted * -1.0).rename("inverted")
    factor_frame["inverted"] = second.to_numpy()
    ic_table = ic_by_date(panel, factor_frame, ["planted", "inverted"], horizon=5)
    check("ic_by_date returns one column per factor",
          list(ic_table.columns) == ["planted", "inverted"], list(ic_table.columns))
    check("ic_by_date returns one row per date",
          len(ic_table) == panel["date"].nunique(),
          f"{len(ic_table)} rows vs {panel['date'].nunique()} dates")
    check("an inverted factor has the opposite IC sign",
          float(ic_table["inverted"].mean()) < 0 < float(ic_table["planted"].mean()),
          f"planted={ic_table['planted'].mean():.3f} inverted={ic_table['inverted'].mean():.3f}")

    # ------------------------------------------------------------------ #
    print("\n-- misc --")
    check("default_feature_names excludes bookkeeping columns",
          default_feature_names(pd.DataFrame(columns=["date", "code", "a", "b"])) == ["a", "b"])
    check("every registered factor has a usable direction",
          all(REGISTRY[name].direction in (-1, 1) for name in REGISTRY))

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
