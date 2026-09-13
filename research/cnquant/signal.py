"""Phase D: combine individual factors into one tradable cross-sectional score.

Three combiners, deliberately ordered from least to most dangerous:

* ``equal`` -- sign each factor by its *prior* direction and average the
  cross-sectional ranks. No fitting, so it cannot overfit, and it is the honest
  baseline every fancier method has to beat.
* ``ic_weighted`` -- weight each factor by the rolling mean of its realised rank
  IC, **shifted by the label horizon**. The shift is not a detail: the IC at date
  ``t`` depends on the return realised at ``t + h``, so an unshifted rolling mean
  silently reads the future.
* ``lightgbm`` -- a gradient-boosted model exposed as ``(fit, predict)``
  callables for :func:`cnquant.walkforward.run_walk_forward`, so it is validated
  through the same purged/embargoed folds as everything else.

Memory note
-----------
The daily panel is ~7.5M rows (3000 names x 2500 days). A dense
``rows x factors`` rank frame for 20 factors is ~1.2 GB, so nothing here ever
materialises one: the composite is accumulated factor by factor, and per-date
weights are broadcast through an integer lookup rather than a row reindex.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

import numpy as np
import pandas as pd

from .evaluate import forward_returns, rank_ic_by_date
from .factors import REGISTRY
from .ops import cs_rank


@dataclass(frozen=True)
class SignalConfig:
    """How factors become one score."""

    #: "equal", "ic_weighted", or "lightgbm".
    method: str = "ic_weighted"
    #: Label horizon in trading days. Must match the portfolio's holding period.
    horizon: int = 5
    #: Rolling window (trading days) for the IC estimate.
    ic_lookback_days: int = 504
    ic_min_periods: int = 252
    #: Drop factors whose rolling |IC| never clears this.
    min_abs_ic: float = 0.005
    #: Cap on how many factors may enter the composite.
    max_factors: int = 20


# --------------------------------------------------------------------------- #
# per-date weights
# --------------------------------------------------------------------------- #


def ic_by_date(
    panel: pd.DataFrame,
    factor_frame: pd.DataFrame,
    names: Sequence[str],
    horizon: int | None = None,
    *,
    min_names: int = 30,
) -> pd.DataFrame:
    """Per-date rank IC of every named factor against the tradable forward return.

    Result is small: one row per trading date, one column per factor.
    """
    horizon = horizon or SignalConfig().horizon
    forward = forward_returns(panel, horizons=(horizon,))[f"fwd_{horizon}"]
    dates = panel["date"]
    columns = {
        name: rank_ic_by_date(dates, factor_frame[name], forward, min_names=min_names)
        for name in names
    }
    return pd.DataFrame(columns).sort_index()


def rolling_ic_weights(
    ic: pd.DataFrame,
    *,
    horizon: int = 5,
    lookback_days: int = 504,
    min_periods: int = 252,
    min_abs_ic: float = 0.005,
    max_factors: int = 20,
) -> pd.DataFrame:
    """Tradable IC weights: a shifted rolling mean, then a top-N cut.

    ``shift(horizon)`` is what makes the weights usable. Without it the window
    ending at ``t`` contains the IC of a label that is only realised at
    ``t + horizon`` -- look-ahead that produces excellent backtests and no live
    performance whatsoever.
    """
    if ic.empty:
        return ic
    shifted = ic.shift(horizon)
    weights = shifted.rolling(lookback_days, min_periods=min_periods).mean()

    # Keep only the strongest factors so a wide but weak library cannot dilute
    # the composite into the market.
    magnitude = weights.abs()
    rank = magnitude.rank(axis=1, ascending=False, method="first")
    weights = weights.where(rank <= max_factors)
    return weights.where(magnitude >= min_abs_ic)


def equal_weights(names: Sequence[str]) -> pd.Series:
    """Prior-direction weights as a single ``factor -> weight`` row.

    Uses the declared ``direction`` metadata rather than any fitted quantity,
    which is the whole point of keeping it as an honest baseline.
    """
    signs = pd.Series(
        {name: float(REGISTRY[name].direction) if name in REGISTRY else 1.0 for name in names},
        dtype="float64",
    )
    total = float(signs.abs().sum()) or 1.0
    return signs / total


# --------------------------------------------------------------------------- #
# composite
# --------------------------------------------------------------------------- #


def _broadcast_weights(dates: np.ndarray, weights: pd.DataFrame, name: str) -> np.ndarray:
    """Map a per-date weight series onto row positions using one integer lookup."""
    if name not in weights.columns:
        return np.full(len(dates), np.nan, dtype="float64")
    positions = pd.Index(weights.index).get_indexer(dates)
    values = weights[name].to_numpy(dtype="float64")
    safe = np.maximum(positions, 0)
    return np.where(positions >= 0, values[safe], np.nan)


def composite_score(
    panel: pd.DataFrame,
    factor_frame: pd.DataFrame,
    names: Sequence[str],
    weights: pd.Series | pd.DataFrame,
) -> pd.Series:
    """Weighted sum of cross-sectional factor ranks, accumulated in place.

    ``weights`` may be a constant ``factor -> weight`` Series or a per-date
    ``DataFrame``. Ranks are centred on zero before combining, so a weighted sum
    cannot acquire a spurious long bias from the ranks themselves.

    A row where no factor has both a rank and a weight gets ``NaN``, which the
    portfolio layer reads as "no opinion" rather than as a neutral score.
    """
    missing = [name for name in names if name not in factor_frame.columns]
    if missing:
        raise KeyError("factor frame is missing: " + ", ".join(missing))

    if isinstance(weights, pd.DataFrame):
        dates = panel["date"].to_numpy()
        weight_columns = {name: _broadcast_weights(dates, weights, name) for name in names}
    else:
        weight_columns = {
            name: np.full(len(panel), float(weights.get(name, np.nan)), dtype="float64")
            for name in names
        }

    total = np.zeros(len(panel), dtype="float64")
    counted = np.zeros(len(panel), dtype="int32")
    for name in names:
        weight = weight_columns[name]
        if not np.isfinite(weight).any():
            continue
        ranks = (cs_rank(panel, factor_frame[name]) - 0.5).to_numpy(dtype="float64")
        valid = np.isfinite(ranks) & np.isfinite(weight)
        total[valid] += ranks[valid] * weight[valid]
        counted[valid] += 1

    score = np.where(counted > 0, total, np.nan)
    return pd.Series(score, index=panel.index, name="score")


def neutralize_score(
    panel: pd.DataFrame,
    score: pd.Series,
    *,
    industry=None,
    size=None,
) -> pd.Series:
    """Industry/size-neutralise a composite score before it reaches the portfolio.

    Delegates to the portfolio module so the two layers cannot drift into two
    different definitions of "neutral".
    """
    from .portfolio import neutralize_scores  # noqa: PLC0415 - avoid a circular import

    return neutralize_scores(panel, score, industry=industry, size=size)


# --------------------------------------------------------------------------- #
# LightGBM, exposed for the purged walk-forward driver
# --------------------------------------------------------------------------- #


def lightgbm_model(
    *,
    params: dict | None = None,
    num_boost_round: int = 300,
    early_stopping_rounds: int | None = 30,
    validation_fraction: float = 0.15,
):
    """Return ``(fit, predict)`` callables for :func:`run_walk_forward`.

    A chronological tail of the training window is held out for early stopping.
    A random split here would leak, because neighbouring days carry overlapping
    forward labels.
    """
    def fit(features: pd.DataFrame, label: pd.Series):
        import lightgbm as lgb  # noqa: PLC0415 - optional heavy import

        settings = {
            "objective": "regression",
            "metric": "l2",
            "learning_rate": 0.03,
            "num_leaves": 31,
            "min_data_in_leaf": 200,
            "feature_fraction": 0.7,
            "bagging_fraction": 0.7,
            "bagging_freq": 1,
            "lambda_l2": 1.0,
            "verbosity": -1,
            "num_threads": 0,
        }
        settings.update(params or {})

        matrix = features.to_numpy(dtype="float64")
        target = label.to_numpy(dtype="float64")
        cut = int(len(matrix) * (1.0 - validation_fraction))
        if cut < 100 or len(matrix) - cut < 50:
            return lgb.train(settings, lgb.Dataset(matrix, label=target),
                             num_boost_round=num_boost_round)

        train_set = lgb.Dataset(matrix[:cut], label=target[:cut])
        valid_set = lgb.Dataset(matrix[cut:], label=target[cut:], reference=train_set)
        callbacks = []
        if early_stopping_rounds:
            callbacks.append(lgb.early_stopping(early_stopping_rounds, verbose=False))
        return lgb.train(
            settings, train_set,
            num_boost_round=num_boost_round,
            valid_sets=[valid_set],
            callbacks=callbacks,
        )

    def predict(model, features: pd.DataFrame) -> np.ndarray:
        best = getattr(model, "best_iteration", None)
        return np.asarray(
            model.predict(features.to_numpy(dtype="float64"), num_iteration=best),
            dtype="float64",
        )

    return fit, predict


def default_feature_names(factor_frame: pd.DataFrame, exclude: Sequence[str] = ()) -> list[str]:
    """All factor columns, minus bookkeeping columns and any explicit exclusions."""
    blocked = {"date", "code", *exclude}
    return [column for column in factor_frame.columns if column not in blocked]
