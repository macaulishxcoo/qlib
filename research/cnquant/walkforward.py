"""Phase F: purged, embargoed walk-forward validation.

A single train/test split is the fastest way to believe a strategy that does not
work. This module produces the rolling windows the research plan requires, with
an embargo between train and test so that a label spanning ``h`` days cannot leak
across the boundary.

The driver is deliberately model-agnostic: it takes ``fit`` and ``predict``
callables, so the same loop validates a linear composite and a gradient-boosted
model without changing the validation logic.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass

import numpy as np
import pandas as pd


@dataclass(frozen=True)
class Split:
    """One walk-forward fold."""

    fold: int
    train_start: pd.Timestamp
    train_end: pd.Timestamp
    test_start: pd.Timestamp
    test_end: pd.Timestamp
    train_dates: pd.DatetimeIndex
    test_dates: pd.DatetimeIndex

    def describe(self) -> str:
        return (
            f"fold {self.fold}: train {self.train_start.date()}..{self.train_end.date()} "
            f"({len(self.train_dates)}d) -> test {self.test_start.date()}..{self.test_end.date()} "
            f"({len(self.test_dates)}d)"
        )


def walk_forward_splits(
    dates: Sequence[pd.Timestamp] | pd.DatetimeIndex,
    *,
    train_years: int = 3,
    test_years: int = 1,
    embargo_days: int = 10,
    first_test_start: str | pd.Timestamp | None = None,
) -> list[Split]:
    """Rolling train/test folds over ``dates``.

    The training window ends ``embargo_days`` trading days before the test window
    opens. Without that gap a 5- or 10-day forward label computed near the end of
    the training window is partly *observed* inside the test window, which is
    look-ahead leakage that inflates every reported number.
    """
    index = pd.DatetimeIndex(pd.Series(pd.to_datetime(list(dates))).dropna().unique()).sort_values()
    if len(index) == 0:
        return []

    start = index.min()
    end = index.max()
    cursor = pd.Timestamp(first_test_start) if first_test_start is not None else start + pd.DateOffset(years=train_years)

    splits: list[Split] = []
    fold = 0
    while cursor < end:
        test_stop = min(cursor + pd.DateOffset(years=test_years), end + pd.Timedelta(days=1))
        train_all = index[index < cursor]
        train_dates = train_all[:-embargo_days] if embargo_days > 0 and len(train_all) > embargo_days else train_all
        test_dates = index[(index >= cursor) & (index < test_stop)]
        if len(train_dates) > 0 and len(test_dates) > 0:
            fold += 1
            splits.append(
                Split(
                    fold=fold,
                    train_start=train_dates.min(),
                    train_end=train_dates.max(),
                    test_start=test_dates.min(),
                    test_end=test_dates.max(),
                    train_dates=train_dates,
                    test_dates=test_dates,
                )
            )
        cursor = test_stop
    return splits


def assert_no_leakage(splits: Sequence[Split]) -> None:
    """Raise when any fold's train window overlaps or touches its test window."""
    for split in splits:
        if len(split.train_dates) == 0 or len(split.test_dates) == 0:
            raise ValueError(f"{split.describe()}: empty window")
        if split.train_end >= split.test_start:
            raise ValueError(
                f"{split.describe()}: training data reaches into the test window "
                f"(train_end {split.train_end} >= test_start {split.test_start})"
            )


def run_walk_forward(
    panel: pd.DataFrame,
    feature_frame: pd.DataFrame,
    label: pd.Series,
    *,
    feature_columns: Sequence[str],
    fit: Callable[[pd.DataFrame, pd.Series], object],
    predict: Callable[[object, pd.DataFrame], np.ndarray],
    splits: Sequence[Split],
) -> pd.Series:
    """Train on each fold's train window and collect out-of-sample predictions.

    Returns one prediction per ``(date, code)`` row covered by the test windows,
    indexed like ``panel``. Rows outside every test window are dropped, so the
    result is a genuine out-of-sample series rather than a stitched in-sample one.
    """
    dates = pd.to_datetime(panel["date"])
    pieces: list[pd.Series] = []

    for split in splits:
        train_mask = dates.isin(split.train_dates).to_numpy()
        test_mask = dates.isin(split.test_dates).to_numpy()
        if not train_mask.any() or not test_mask.any():
            continue

        train_x = feature_frame.loc[train_mask, list(feature_columns)]
        train_y = label.loc[train_mask]
        valid = train_x.notna().all(axis=1) & train_y.notna()
        if int(valid.sum()) < 100:
            continue

        model = fit(train_x[valid], train_y[valid])

        test_x = feature_frame.loc[test_mask, list(feature_columns)]
        predictions = np.full(int(test_mask.sum()), np.nan, dtype="float64")
        usable = test_x.notna().all(axis=1).to_numpy()
        if usable.any():
            predictions[usable] = predict(model, test_x[usable])
        pieces.append(pd.Series(predictions, index=panel.index[test_mask], name=f"fold{split.fold}"))

    if not pieces:
        return pd.Series(np.nan, index=panel.index, name="prediction")
    combined = pd.concat(pieces).sort_index()
    combined = combined[~combined.index.duplicated(keep="first")]
    return combined.reindex(panel.index).rename("prediction")


def scores_from_predictions(
    panel: pd.DataFrame,
    predictions: pd.Series,
) -> pd.DataFrame:
    """Reshape a per-row prediction series into the wide frame the rest of the stack wants."""
    frame = pd.DataFrame(
        {
            "date": np.asarray(panel["date"]),
            "code": np.asarray(panel["code"]),
            "score": np.asarray(predictions, dtype="float64"),
        }
    )
    return frame.pivot_table(index="date", columns="code", values="score", aggfunc="last").sort_index()
