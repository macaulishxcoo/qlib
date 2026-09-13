#!/usr/bin/env python
"""End-to-end integration self-test across every phase, offline.

Each module has its own self-test, but those do not catch an *interface*
mismatch between modules -- a wrong index, a differently named column, a
wide-vs-long confusion. This test wires the whole stack together on a synthetic
world where a known signal genuinely predicts forward returns:

    prepare_panel -> build_factors -> walk_forward_splits -> run_walk_forward
        -> scores_from_predictions -> build_target_weights -> run_backtest

and then asserts that the out-of-sample signal survives all the way through to
the net-value curve. If any seam is wrong, the prediction IC collapses to zero
long before the backtest step.

The synthetic world is built so that ``r[t+5] = beta * latent[t] + noise``, which
makes the 5-day forward return partially predictable from ``latent[t]`` by
construction.

Run::

    python research/scripts/selftest_integration.py
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from cnquant.backtest import run_backtest  # noqa: E402
from cnquant.config import BacktestConfig, CostModel, UniverseRules  # noqa: E402
from cnquant.evaluate import forward_returns, ic_summary, rank_ic_by_date  # noqa: E402
from cnquant.factors import build_factors  # noqa: E402
from cnquant.portfolio import PortfolioConfig, build_target_weights, turnover_of_weights  # noqa: E402
from cnquant.universe import prepare_panel  # noqa: E402
from cnquant.walkforward import (  # noqa: E402
    assert_no_leakage,
    run_walk_forward,
    scores_from_predictions,
    walk_forward_splits,
)

FAILURES: list[str] = []

N_DATES = 800
N_CODES = 120
LATENT_VOL = 0.02
RETURN_VOL = 0.02
BETA = 1.5
FEATURE_NOISE = 0.02

FREE_COST = CostModel(
    commission_rate=0.0,
    commission_min=0.0,
    stamp_duty_sell=0.0,
    transfer_fee=0.0,
    slippage_one_way=0.0,
)


def check(name: str, condition: bool, detail: str = "") -> None:
    status = "PASS" if condition else "FAIL"
    line = f"[{status}] {name}"
    if detail:
        line += f" -- {detail}"
    print(line)
    if not condition:
        FAILURES.append(f"{name}: {detail}")


def make_world(seed: int = 21):
    """Prices where ``r[t+5] = BETA * latent[t] + noise``."""
    rng = np.random.default_rng(seed)
    dates = pd.bdate_range("2019-01-01", periods=N_DATES)
    codes = [f"sh.60{i:04d}" for i in range(N_CODES)]

    latent = rng.normal(0.0, LATENT_VOL, size=(N_DATES, N_CODES))
    returns = rng.normal(0.0, RETURN_VOL, size=(N_DATES, N_CODES))
    returns[5:] = returns[5:] + BETA * latent[:-5]
    close = 10.0 * np.cumprod(1.0 + returns, axis=0)
    open_ = np.vstack([close[0:1], close[:-1]])

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
                    "amount": 3.0e7,
                    "turn": 1.0,
                    "pctChg": returns[i, j] * 100.0,
                    "tradestatus": 1,
                    "isST": 0,
                    "adj_open": open_[i, j],
                    "adj_close": close[i, j],
                    "pbMRQ": 1.5,
                    "peTTM": 20.0,
                    "psTTM": 2.0,
                }
            )
    panel = pd.DataFrame(rows)
    basic = pd.DataFrame(
        [{"code": code, "code_name": code, "ipo_date": pd.Timestamp("2000-01-01"),
          "out_date": pd.NaT, "sec_type": "1", "status": 1.0} for code in codes]
    )
    prepared = prepare_panel(panel, basic, UniverseRules())
    observed = latent + rng.normal(0.0, FEATURE_NOISE, size=(N_DATES, N_CODES))

    # Align by (date, code) explicitly. prepare_panel re-sorts the panel, so
    # flattening the latent matrix positionally would pair each name's signal
    # with a different name's return.
    lookup = pd.DataFrame(observed, index=dates, columns=codes).stack()
    lookup.index.names = ["date", "code"]
    keys = pd.MultiIndex.from_arrays([prepared["date"], prepared["code"]])
    observed_series = pd.Series(
        lookup.reindex(keys).to_numpy(), index=prepared.index, name="observed_signal"
    )
    return prepared, observed_series


def fit_ols(features: pd.DataFrame, label: pd.Series):
    matrix = np.column_stack([np.ones(len(features)), features.to_numpy(dtype="float64")])
    coefficients, *_ = np.linalg.lstsq(matrix, label.to_numpy(dtype="float64"), rcond=None)
    return coefficients


def predict_ols(coefficients, features: pd.DataFrame) -> np.ndarray:
    matrix = np.column_stack([np.ones(len(features)), features.to_numpy(dtype="float64")])
    return matrix @ coefficients


def main() -> int:
    print("=" * 78)
    print(" End-to-end integration self-test (all phases, offline)")
    print("=" * 78)

    panel, observed = make_world()
    print(f"panel: {len(panel):,} rows, {panel['code'].nunique()} codes, "
          f"{panel['date'].min().date()} .. {panel['date'].max().date()}")

    # ------------------------------------------------------------------ #
    print("\n-- Phase A/C: factors compute on the prepared panel --")
    factor_frame = build_factors(panel)
    factor_frame["observed_signal"] = observed
    check("factor frame is row-aligned with the panel",
          len(factor_frame) == len(panel)
          and bool((factor_frame["date"].to_numpy() == panel["date"].to_numpy()).all()))
    check("the observed signal has full coverage",
          float(factor_frame["observed_signal"].notna().mean()) > 0.99)
    library_columns = [c for c in factor_frame.columns if c not in {"date", "code", "observed_signal"}]
    coverage = float(factor_frame[library_columns].notna().to_numpy().mean())
    check("the factor library is mostly populated on this fixture", coverage > 0.5,
          f"{coverage:.1%} populated")

    # ------------------------------------------------------------------ #
    print("\n-- Phase F: walk-forward splits do not leak --")
    forward = forward_returns(panel, horizons=(5,))
    label = forward["fwd_5"]
    splits = walk_forward_splits(panel["date"], train_years=1, test_years=1, embargo_days=10)
    check("at least two folds are produced", len(splits) >= 2, f"{len(splits)} folds")
    try:
        assert_no_leakage(splits)
        check("no fold leaks training data into its test window", True)
    except ValueError as exc:
        check("no fold leaks training data into its test window", False, str(exc))
    if splits:
        print(f"       {splits[0].describe()}")
    embargo_ok = all(
        (split.test_start - split.train_end).days >= 10 for split in splits
    )
    check("every fold keeps a >=10 calendar-day embargo", embargo_ok)

    # ------------------------------------------------------------------ #
    print("\n-- Phase D: out-of-sample predictions --")
    predictions = run_walk_forward(
        panel, factor_frame, label,
        feature_columns=["observed_signal"],
        fit=fit_ols, predict=predict_ols, splits=splits,
    )
    check("predictions cover the out-of-sample rows",
          int(predictions.notna().sum()) > 1000,
          f"{int(predictions.notna().sum()):,} predictions")
    ic = ic_summary(rank_ic_by_date(panel["date"], predictions, label))
    check("out-of-sample predictions retain a positive IC", ic["ic_mean"] > 0.10,
          f"IC={ic['ic_mean']:.4f}, t={ic['ic_t_stat']:.1f}")

    first_fold_train = panel["date"].isin(splits[0].train_dates).to_numpy()
    check("the first fold's training window carries no predictions",
          int(predictions[first_fold_train].notna().sum()) == 0,
          f"{int(predictions[first_fold_train].notna().sum())} leaked predictions")

    ceiling = ic_summary(rank_ic_by_date(panel["date"], observed, label))
    check("the OOS IC is close to the achievable ceiling",
          ic["ic_mean"] > 0.7 * ceiling["ic_mean"],
          f"OOS {ic['ic_mean']:.4f} vs ceiling {ceiling['ic_mean']:.4f}")

    # ------------------------------------------------------------------ #
    print("\n-- Phase E: predictions become target weights --")
    scores = scores_from_predictions(panel, predictions)
    check("scores reshape into a date x code frame",
          scores.shape[0] > 100 and scores.shape[1] == N_CODES,
          f"shape {scores.shape}")
    weights = build_target_weights(
        panel, scores, config=PortfolioConfig(n_holdings=20, exit_multiple=2.0)
    )
    # Only the walk-forward test windows can produce a book; the earlier
    # training-only dates are legitimately empty.
    test_dates = pd.DatetimeIndex(sorted({date for split in splits for date in split.test_dates}))
    in_test = scores.index.isin(test_dates)
    populated = int(weights.loc[in_test].notna().all(axis=1).sum())
    check("most out-of-sample dates produce a fully specified book",
          populated > 0.8 * int(in_test.sum()),
          f"{populated}/{int(in_test.sum())} rows")
    check("target weights sum to 1 where specified",
          float((weights.dropna(how="all").sum(axis=1) - 1.0).abs().max()) < 1e-6)
    implied_turnover = turnover_of_weights(weights)
    check("implied daily turnover is plausible, not degenerate",
          0.02 < float(implied_turnover.mean()) < 0.60,
          f"mean {float(implied_turnover.mean()):.4f}")

    # ------------------------------------------------------------------ #
    print("\n-- Phase B: the engine consumes those weights --")
    costless = run_backtest(
        panel, weights,
        config=BacktestConfig(initial_capital=500_000.0),
        cost=FREE_COST,
        rebalance_every=5,
    )
    check("nav is finite and positive everywhere",
          bool(np.isfinite(costless.nav.to_numpy()).all()) and bool((costless.nav > 0).all()))
    check("trades were actually executed", len(costless.trades) > 100,
          f"{len(costless.trades)} trades")
    check("a costless run on a planted signal makes money",
          float(costless.stats["annual_return"]) > 0.0,
          f"annual {costless.stats['annual_return']:.2%}")
    check("rebalance_every=5 keeps annual turnover near the 244/5 ceiling",
          float(costless.stats["annual_one_way_turnover"]) < 60.0,
          f"{costless.stats['annual_one_way_turnover']:.1f}x per year")

    expensive = run_backtest(
        panel, weights,
        config=BacktestConfig(initial_capital=500_000.0),
        rebalance_every=5,
    )
    check("paying real costs lowers the result",
          float(expensive.stats["annual_return"]) < float(costless.stats["annual_return"]),
          f"with costs {expensive.stats['annual_return']:.2%} "
          f"vs costless {costless.stats['annual_return']:.2%}")
    check("total cost is a plausible share of capital",
          0.0 < float(expensive.stats["total_cost_share_of_capital"]) < 1.0,
          f"{expensive.stats['total_cost_share_of_capital']:.1%} of capital over the sample")
    check("every expected statistic is present",
          all(key in expensive.stats for key in
              ("annual_return", "information_ratio", "max_drawdown", "annual_one_way_turnover",
               "total_cost_cny", "rolling_12m_win_rate")))

    # ------------------------------------------------------------------ #
    print("\n-- the engine rejects a misaligned panel --")
    try:
        run_backtest(panel.sample(frac=0.5, random_state=1), weights, cost=FREE_COST)
        check("a truncated panel is handled without a crash", True)
    except Exception as exc:  # noqa: BLE001
        check("a truncated panel is handled without a crash", False,
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
