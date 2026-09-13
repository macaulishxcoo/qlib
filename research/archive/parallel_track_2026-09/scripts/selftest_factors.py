#!/usr/bin/env python
"""Offline self-test for the Phase C operator / factor / evaluation layer.

The important test here is the *planted relationship* one: a synthetic panel is
built where the forward 5-day return is known by construction, a factor is
derived from it plus comparable noise, and the evaluator has to recover the
relationship and correctly rank it above the 1-day horizon. If the horizon
wiring, the rank-IC computation, or the quantile bucketing were wrong, that test
would fail while a "does it run" smoke test would still pass.

Run::

    python research/scripts/selftest_factors.py
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from cnquant.config import UniverseRules  # noqa: E402
from cnquant.evaluate import (  # noqa: E402
    forward_returns,
    ic_summary,
    long_side_turnover,
    net_long_excess,
    quantile_monotonicity,
    quantile_returns_by_date,
    rank_ic_by_date,
)
from cnquant.factors import REGISTRY, build_factors, factor_catalog  # noqa: E402
from cnquant.ops import (  # noqa: E402
    cs_neutralize,
    cs_rank,
    cs_zscore,
    factor_panel,
    ts_delay,
    ts_mean,
    ts_pct_change,
)
from cnquant.universe import prepare_panel  # noqa: E402

FAILURES: list[str] = []

# fwd_5 has a ~0.045 standard deviation on this synthetic panel, so the noise
# scale below is what controls the planted factor's information ratio.
DAILY_VOL = 0.02
NOISE_SCALE = 0.03


def check(name: str, condition: bool, detail: str = "") -> None:
    status = "PASS" if condition else "FAIL"
    line = f"[{status}] {name}"
    if detail:
        line += f" -- {detail}"
    print(line)
    if not condition:
        FAILURES.append(f"{name}: {detail}")


def _raises_keyerror(fn) -> bool:
    try:
        fn()
    except KeyError:
        return True
    except Exception:  # noqa: BLE001
        return False
    return False


# --------------------------------------------------------------------------- #
# tiny deterministic panels for the operator tests
# --------------------------------------------------------------------------- #


def tiny_panel() -> pd.DataFrame:
    """Two codes, six days, strictly arithmetic prices."""
    dates = pd.bdate_range("2024-01-01", periods=6)
    rows = []
    for code, start in (("sh.600000", 1.0), ("sz.000001", 10.0)):
        for index, date in enumerate(dates):
            value = start * (index + 1)
            rows.append({"date": date, "code": code, "adj_close": value, "adj_open": value})
    return factor_panel(pd.DataFrame(rows))


def neutralize_panel() -> pd.DataFrame:
    """Eight codes so an OLS residual has real degrees of freedom.

    ``cs_neutralize`` refuses to fit when a date has no more observations than
    parameters; two codes against an intercept plus one exposure is exactly that
    degenerate case.
    """
    dates = pd.bdate_range("2024-01-01", periods=4)
    rows = []
    for index in range(8):
        for date in dates:
            rows.append({"date": date, "code": f"sh.60{index:04d}", "exposure": float(index)})
    return factor_panel(pd.DataFrame(rows))


# --------------------------------------------------------------------------- #
# synthetic market
# --------------------------------------------------------------------------- #


def make_market_panel(n_dates: int = 220, n_codes: int = 90, seed: int = 7):
    """Synthetic panel plus a factor derived from the future 5-day return."""
    rng = np.random.default_rng(seed)
    dates = pd.bdate_range("2020-01-01", periods=n_dates)
    codes = [f"sh.60{i:04d}" for i in range(n_codes)]

    returns = rng.normal(0.0003, DAILY_VOL, size=(n_dates, n_codes))
    close = 10.0 * np.cumprod(1.0 + returns, axis=0)

    # adj_open[t] == adj_close[t-1] makes the tradable forward return exactly
    # close[t+h] / close[t] - 1, which the exactness test below relies on.
    open_ = np.vstack([close[0:1], close[:-1]])

    turn = 1.0 + 0.5 * rng.random((n_dates, n_codes))
    rows = []
    for j, code in enumerate(codes):
        for i, date in enumerate(dates):
            rows.append(
                {
                    "date": date,
                    "code": code,
                    "open": open_[i, j],
                    "high": max(open_[i, j], close[i, j]) * 1.01,
                    "low": min(open_[i, j], close[i, j]) * 0.99,
                    "close": close[i, j],
                    "preclose": open_[i, j],
                    "volume": 1.0e6,
                    "amount": 2.0e7,
                    "turn": turn[i, j],
                    "pctChg": returns[i, j] * 100.0,
                    "tradestatus": 1,
                    "isST": 0,
                    "adj_open": open_[i, j],
                    "adj_close": close[i, j],
                    # Fundamentals are needed by the value factors; without them
                    # bp/ep/sp would be all-NaN and the coverage check collides
                    # with a fixture gap rather than a real defect.
                    "pbMRQ": 1.0 + rng.random(),
                    "peTTM": 10.0 + 20.0 * rng.random(),
                    "psTTM": 1.0 + 5.0 * rng.random(),
                }
            )
    panel = pd.DataFrame(rows)

    basic = pd.DataFrame(
        [{"code": code, "code_name": code, "ipo_date": pd.Timestamp("2000-01-01"),
          "out_date": pd.NaT, "sec_type": "1", "status": 1.0} for code in codes]
    )
    prepared = prepare_panel(panel, basic, UniverseRules())

    forward = forward_returns(prepared, horizons=(1, 5))
    noise = pd.Series(rng.normal(0.0, NOISE_SCALE, len(prepared)))
    planted = (forward["fwd_5"] + noise).rename("planted")
    return prepared, forward, planted


def main() -> int:
    print("=" * 78)
    print(" Phase C offline self-test (ops / factors / evaluation)")
    print("=" * 78)

    # ------------------------------------------------------------------ #
    print("\n-- time-series operators --")
    tiny = tiny_panel()
    close = tiny["adj_close"]
    delayed = ts_delay(tiny, close, 1)
    check("ts_delay shifts within a code and starts each code with NaN",
          np.isnan(delayed.iloc[0]) and abs(delayed.iloc[1] - 1.0) < 1e-12
          and np.isnan(delayed.iloc[6]) and abs(delayed.iloc[7] - 10.0) < 1e-12,
          f"i1={delayed.iloc[1]}, i6={delayed.iloc[6]}, i7={delayed.iloc[7]}")
    change = ts_pct_change(tiny, close, 1)
    check("ts_pct_change at index 1 is 2/1 - 1 = 1.0", abs(change.iloc[1] - 1.0) < 1e-12)
    mean2 = ts_mean(tiny, close, 2, min_periods=1)
    check("ts_mean(window=2) at index 1 is (1+2)/2 = 1.5", abs(mean2.iloc[1] - 1.5) < 1e-12)
    check("ts_mean does not leak across the code boundary", abs(mean2.iloc[6] - 10.0) < 1e-12,
          f"got {mean2.iloc[6]}")

    # ------------------------------------------------------------------ #
    print("\n-- cross-sectional operators --")
    first_date = tiny["date"].iloc[0]
    on_first = (tiny["date"] == first_date).to_numpy()
    ranks = cs_rank(tiny, close).to_numpy()
    check("cs_rank gives 0.5 and 1.0 for the two names on the first date",
          abs(min(ranks[on_first]) - 0.5) < 1e-12 and abs(max(ranks[on_first]) - 1.0) < 1e-12)
    zscores = cs_zscore(tiny, close).to_numpy()
    check("cs_zscore sums to ~0 within a date",
          abs(float(np.nansum(zscores[on_first]))) < 1e-9)

    neutral = neutralize_panel()
    exposure = neutral["exposure"]
    target = 3.0 * exposure + 7.0
    residual = cs_neutralize(neutral, target, [exposure])
    check("cs_neutralize removes a perfectly linear exposure",
          float(np.nanmax(np.abs(residual.to_numpy()))) < 1e-8,
          f"max |residual| = {float(np.nanmax(np.abs(residual.to_numpy()))):.2e}")
    check("cs_neutralize leaves no NaN when a date has enough observations",
          int(residual.isna().sum()) == 0, f"{int(residual.isna().sum())} NaN")

    # ------------------------------------------------------------------ #
    print("\n-- forward returns use the tradable convention --")
    panel, forward, planted = make_market_panel()
    close_wide = panel.pivot(index="date", columns="code", values="adj_close")
    manual = (close_wide.shift(-1) / close_wide - 1.0).stack().rename("manual")
    manual.index.names = ["date", "code"]
    actual = forward.set_index(["date", "code"])["fwd_1"].rename("actual")
    joined = pd.concat([manual, actual], axis=1).dropna()
    check("fwd_1 equals close[t+1]/close[t] - 1 when open[t+1] = close[t]",
          len(joined) > 1000
          and float((joined["manual"] - joined["actual"]).abs().max()) < 1e-10,
          f"n={len(joined)} max diff={float((joined['manual'] - joined['actual']).abs().max()):.2e}")

    # ------------------------------------------------------------------ #
    print("\n-- the planted relationship must be recovered --")
    dates = panel["date"]
    ic_5 = rank_ic_by_date(dates, planted, forward["fwd_5"])
    ic_1 = rank_ic_by_date(dates, planted, forward["fwd_1"])
    summary_5 = ic_summary(ic_5)
    summary_1 = ic_summary(ic_1)
    check("planted factor shows a strong 5-day IC", summary_5["ic_mean"] > 0.2,
          f"IC(5d)={summary_5['ic_mean']:.4f}")
    check("the 5-day IC beats the 1-day IC", summary_5["ic_mean"] > summary_1["ic_mean"],
          f"IC(1d)={summary_1['ic_mean']:.4f}")
    check("IC t-stat is large and positive", summary_5["ic_t_stat"] > 5.0,
          f"t={summary_5['ic_t_stat']:.2f}")
    check("IC is positive on the large majority of dates",
          summary_5["ic_positive_rate"] > 0.9, f"{summary_5['ic_positive_rate']:.3f}")

    quantiles = quantile_returns_by_date(dates, planted, forward["fwd_5"], n_quantiles=10)
    monotonicity = quantile_monotonicity(quantiles)
    check("decile returns are monotone in the planted factor", monotonicity > 0.7,
          f"monotonicity={monotonicity:.3f}")
    check("the top decile beats the bottom decile",
          float(quantiles[10].mean()) > float(quantiles[1].mean()),
          f"top={quantiles[10].mean():.5f} bottom={quantiles[1].mean():.5f}")

    noise_factor = pd.Series(np.random.default_rng(11).normal(0, 1, len(panel)))
    ic_noise = ic_summary(rank_ic_by_date(dates, noise_factor, forward["fwd_5"]))
    check("a pure-noise factor has a near-zero IC", abs(ic_noise["ic_mean"]) < 0.03,
          f"IC={ic_noise['ic_mean']:.4f}")

    # ------------------------------------------------------------------ #
    print("\n-- turnover and cost arithmetic --")
    codes = panel["code"]
    constant = pd.Series(1.0, index=panel.index)
    constant_turnover = long_side_turnover(dates, codes, constant)
    check("a constant signal has no top-decile membership to churn",
          constant_turnover.empty or float(constant_turnover.mean()) < 1e-9,
          f"n={len(constant_turnover)}")

    random_factor = pd.Series(np.random.default_rng(3).normal(0, 1, len(panel)))
    random_turnover = long_side_turnover(dates, codes, random_factor)
    check("a random signal churns the top decile almost completely",
          float(random_turnover.mean()) > 0.8,
          f"mean turnover {float(random_turnover.mean()):.3f}")

    gross = pd.Series(0.0010, index=random_turnover.index)
    costs = net_long_excess(gross, random_turnover)
    expected_cost = float(random_turnover.mean()) * 0.00202 * 244
    check("cost drag equals turnover x round-trip x 244",
          abs(costs["cost_annual"] - expected_cost) < 1e-6,
          f"{costs['cost_annual']:.4f} vs {expected_cost:.4f}")
    check("net return is gross minus cost",
          abs(costs["net_annual"] - (costs["gross_annual"] - costs["cost_annual"])) < 1e-9)
    check("a high-churn random signal is deeply net-negative",
          costs["net_annual"] < 0, f"net {costs['net_annual']:.3f}")

    # ------------------------------------------------------------------ #
    print("\n-- factor library --")
    factor_frame = build_factors(panel)
    check("every registered factor produced a column",
          all(name in factor_frame.columns for name in REGISTRY),
          f"{len(factor_frame.columns) - 2} of {len(REGISTRY)}")
    coverage = {name: float(factor_frame[name].notna().mean()) for name in REGISTRY}
    empty = [name for name, share in coverage.items() if share == 0.0]
    check("no factor is entirely empty", not empty, f"empty: {empty}")
    differentiated = ["overnight_momentum_20", "intraday_momentum_20", "volume_price_corr_20",
                      "price_delay_20", "limit_up_count_20", "turnover_acceleration",
                      "close_position_20", "size"]
    thin = {name: round(coverage[name], 3) for name in differentiated if coverage[name] < 0.5}
    check("the differentiated factors have usable coverage", not thin, f"thin: {thin}")
    check("factor_catalog lists every registered factor",
          len(factor_catalog()) == len(REGISTRY))
    check("build_factors rejects an unknown name",
          _raises_keyerror(lambda: build_factors(panel, ["not_a_factor"])))

    # ------------------------------------------------------------------ #
    print("\n-- a panel without optional columns degrades instead of crashing --")
    # baostock rejects a whole request when one field name is invalid, so the
    # field ladder can legitimately deliver a panel without turnover, amount or
    # the fundamental columns. That must not abort the batch.
    droppable = [c for c in ("turn", "amount", "volume", "pbMRQ", "peTTM", "psTTM",
                             "high", "low", "preclose", "isST", "tradestatus")
                 if c in panel.columns]
    trimmed = panel.drop(columns=droppable)
    trimmed_frame = build_factors(
        trimmed,
        ["turnover_20", "amihud_20", "bp", "intraday_range_20", "close_position_20",
         "overnight_momentum_20", "volatility_20"],
    )
    check("the library survives a panel with no optional columns", True,
          f"dropped {len(droppable)} columns")
    check("factors needing a dropped column become all-NaN",
          bool(trimmed_frame["turnover_20"].isna().all())
          and bool(trimmed_frame["amihud_20"].isna().all())
          and bool(trimmed_frame["bp"].isna().all()),
          "turnover/amihud/bp should be empty")
    check("factors that only need prices still compute",
          bool(trimmed_frame["volatility_20"].notna().any())
          and bool(trimmed_frame["overnight_momentum_20"].notna().any()),
          f"volatility_20 coverage {trimmed_frame['volatility_20'].notna().mean():.2f}")

    try:
        build_factors(panel.drop(columns=["adj_close"]), ["volatility_20"])
        check("dropping an essential price column raises a clear error", False, "no error raised")
    except KeyError as exc:
        check("dropping an essential price column raises a clear error",
              "adj_close" in str(exc), str(exc).splitlines()[0][:90])
    except Exception as exc:  # noqa: BLE001
        check("dropping an essential price column raises a clear error", False,
              f"{type(exc).__name__}: {exc}")

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
