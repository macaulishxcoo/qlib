"""Cross-sectional and time-series operators for factor construction.

Contract
--------
Every function takes the *long* panel plus a ``Series`` aligned to
``panel.index``. **Time-series operators require the panel to be sorted by
``(code, date)``** -- call :func:`factor_panel` once at the start of a factor
batch. Cross-sectional operators group by ``date`` and are order-independent.

Why row-aligned Series instead of wide frames: the daily panel is ~7.5M rows
(3000 names x 2500 days). A ``date x code`` wide frame per field costs ~60 MB
each and a factor batch needs a dozen of them; row-aligned groupby transforms
keep peak memory near the size of the panel itself.
"""

from __future__ import annotations

import numpy as np
import pandas as pd


def factor_panel(panel: pd.DataFrame) -> pd.DataFrame:
    """Return the panel ordered by ``(code, date)`` for time-series operators.

    The caller's index is preserved -- only the row *order* changes. Callers that
    need their own order back restore it with ``.reindex(panel.index)`` (see
    :func:`cnquant.factors.build_factors`); dropping the index here instead would
    make that restoration impossible and silently misalign every consumer that
    works positionally.
    """
    return panel.sort_values(["code", "date"])


def _as_series(panel: pd.DataFrame, values) -> pd.Series:
    if isinstance(values, pd.Series):
        if len(values) != len(panel):
            raise ValueError(f"series length {len(values)} does not match panel length {len(panel)}")
        return values
    return panel[values]


def ts_mean(panel: pd.DataFrame, values, window: int, min_periods: int | None = None) -> pd.Series:
    """Rolling mean per code."""
    series = _as_series(panel, values)
    periods = min_periods if min_periods is not None else max(window // 2, 1)
    return series.groupby(panel["code"], sort=False).transform(
        lambda s: s.rolling(window, min_periods=periods).mean()
    )


def ts_std(panel: pd.DataFrame, values, window: int, min_periods: int | None = None) -> pd.Series:
    """Rolling sample standard deviation per code."""
    series = _as_series(panel, values)
    periods = min_periods if min_periods is not None else max(window // 2, 1)
    return series.groupby(panel["code"], sort=False).transform(
        lambda s: s.rolling(window, min_periods=periods).std()
    )


def ts_sum(panel: pd.DataFrame, values, window: int, min_periods: int | None = None) -> pd.Series:
    """Rolling sum per code."""
    series = _as_series(panel, values)
    periods = min_periods if min_periods is not None else max(window // 2, 1)
    return series.groupby(panel["code"], sort=False).transform(
        lambda s: s.rolling(window, min_periods=periods).sum()
    )


def ts_max(panel: pd.DataFrame, values, window: int, min_periods: int | None = None) -> pd.Series:
    """Rolling maximum per code."""
    series = _as_series(panel, values)
    periods = min_periods if min_periods is not None else max(window // 2, 1)
    return series.groupby(panel["code"], sort=False).transform(
        lambda s: s.rolling(window, min_periods=periods).max()
    )


def ts_min(panel: pd.DataFrame, values, window: int, min_periods: int | None = None) -> pd.Series:
    """Rolling minimum per code."""
    series = _as_series(panel, values)
    periods = min_periods if min_periods is not None else max(window // 2, 1)
    return series.groupby(panel["code"], sort=False).transform(
        lambda s: s.rolling(window, min_periods=periods).min()
    )


def ts_rank(panel: pd.DataFrame, values, window: int) -> pd.Series:
    """Rank of the latest value inside its own trailing window, in ``[0, 1]``.

    A pure-pandas rolling rank; slow but exact. Used sparingly.
    """
    series = _as_series(panel, values)
    periods = max(window // 2, 1)
    return series.groupby(panel["code"], sort=False).transform(
        lambda s: s.rolling(window, min_periods=periods).apply(
            lambda w: float(pd.Series(w).rank(pct=True).iloc[-1]), raw=False
        )
    )


def ts_corr(panel: pd.DataFrame, left, right, window: int) -> pd.Series:
    """Rolling Pearson correlation between two per-code series.

    Computed from rolling means rather than a ``groupby.apply`` so it stays
    vectorised and behaves identically across pandas versions. The population
    vs sample covariance distinction cancels in the ratio.
    """
    a = _as_series(panel, left).astype("float64")
    b = _as_series(panel, right).astype("float64")
    mean_a = ts_mean(panel, a, window)
    mean_b = ts_mean(panel, b, window)
    mean_ab = ts_mean(panel, a * b, window)
    mean_aa = ts_mean(panel, a * a, window)
    mean_bb = ts_mean(panel, b * b, window)
    covariance = mean_ab - mean_a * mean_b
    variance_a = mean_aa - mean_a * mean_a
    variance_b = mean_bb - mean_b * mean_b
    with np.errstate(divide="ignore", invalid="ignore"):
        return covariance / np.sqrt(variance_a * variance_b)


def ts_delay(panel: pd.DataFrame, values, periods: int = 1) -> pd.Series:
    """Value ``periods`` trading days ago, per code."""
    series = _as_series(panel, values)
    return series.groupby(panel["code"], sort=False).transform(lambda s: s.shift(periods))


def ts_delta(panel: pd.DataFrame, values, periods: int = 1) -> pd.Series:
    """Change against ``periods`` trading days ago, per code."""
    series = _as_series(panel, values)
    return series - ts_delay(panel, series, periods)


def ts_pct_change(panel: pd.DataFrame, values, periods: int = 1) -> pd.Series:
    """Simple return over ``periods`` trading days, per code."""
    series = _as_series(panel, values)
    previous = ts_delay(panel, series, periods)
    with np.errstate(divide="ignore", invalid="ignore"):
        return series / previous - 1.0


def cs_rank(panel: pd.DataFrame, values) -> pd.Series:
    """Cross-sectional percentile rank in ``[0, 1]`` for each date."""
    series = _as_series(panel, values)
    return series.groupby(panel["date"], sort=False).rank(pct=True)


def cs_zscore(panel: pd.DataFrame, values, clip: float | None = 3.0) -> pd.Series:
    """Cross-sectional z-score for each date, optionally clipped."""
    series = _as_series(panel, values)
    grouped = series.groupby(panel["date"], sort=False)
    mean = grouped.transform("mean")
    std = grouped.transform("std")
    with np.errstate(divide="ignore", invalid="ignore"):
        zscore = (series - mean) / std
    if clip is not None:
        zscore = zscore.clip(-clip, clip)
    return zscore


def cs_demean(panel: pd.DataFrame, values) -> pd.Series:
    """Cross-sectional demean for each date."""
    series = _as_series(panel, values)
    return series - series.groupby(panel["date"], sort=False).transform("mean")


def cs_winsorize(panel: pd.DataFrame, values, lower: float = 0.01, upper: float = 0.99) -> pd.Series:
    """Cross-sectional winsorisation by quantile for each date."""
    series = _as_series(panel, values)
    grouped = series.groupby(panel["date"], sort=False)
    low = grouped.transform(lambda s: s.quantile(lower))
    high = grouped.transform(lambda s: s.quantile(upper))
    return series.clip(lower=low, upper=high)


def cs_neutralize(
    panel: pd.DataFrame,
    values,
    exposures: list[pd.Series],
    *,
    add_constant: bool = True,
) -> pd.Series:
    """Cross-sectional OLS residual of ``values`` on ``exposures``, per date.

    Used to strip industry / size / beta exposure out of a raw factor before it
    is allowed anywhere near portfolio construction. Returns the residual,
    aligned to ``panel.index``.
    """
    series = _as_series(panel, values).astype("float64")
    frame = pd.DataFrame({"y": series.to_numpy(), "date": panel["date"].to_numpy()})
    for index, exposure in enumerate(exposures):
        frame[f"x{index}"] = _as_series(panel, exposure).to_numpy()

    columns = [f"x{index}" for index in range(len(exposures))]
    pieces: list[pd.Series] = []
    for _, group in frame.groupby("date", sort=False):
        y = group["y"].to_numpy(dtype="float64")
        matrix = group[columns].to_numpy(dtype="float64")
        if add_constant:
            matrix = np.column_stack([np.ones(len(group)), matrix])
        mask = np.isfinite(y) & np.isfinite(matrix).all(axis=1)
        residual = np.full(len(group), np.nan)
        if mask.sum() > matrix.shape[1] + 1:
            coefficients, *_ = np.linalg.lstsq(matrix[mask], y[mask], rcond=None)
            residual[mask] = y[mask] - matrix[mask] @ coefficients
        pieces.append(pd.Series(residual, index=group.index))
    if not pieces:
        return pd.Series(np.nan, index=panel.index)
    return pd.concat(pieces).sort_index()
