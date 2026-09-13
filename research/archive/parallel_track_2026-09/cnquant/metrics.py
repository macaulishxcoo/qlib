"""Performance statistics for daily strategies.

All functions take *simple daily returns* (not prices) unless the name says
otherwise, and annualise with :data:`TRADING_DAYS_PER_YEAR` = 244, which is the
A-share norm.

The acceptance gates in :mod:`cnquant.config` are expressed in these terms, so
this module is the single place where "does it pass?" is decided.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

#: A-share trading days per year. 244 is the long-run average; 250 would flatter
#: annualised numbers by ~2.5%, which is exactly the kind of quiet inflation a
#: research process should not accept.
TRADING_DAYS_PER_YEAR = 244


def _clean(returns: pd.Series) -> pd.Series:
    return pd.Series(returns).astype("float64").replace([np.inf, -np.inf], np.nan).dropna()


def cumulative_returns(returns: pd.Series) -> pd.Series:
    """Compound a return series into a net-value curve starting at 1.0."""
    clean = _clean(returns)
    return (1.0 + clean).cumprod()


def annualized_return(returns: pd.Series, periods: int = TRADING_DAYS_PER_YEAR) -> float:
    """Geometric annualised return."""
    clean = _clean(returns)
    if clean.empty:
        return float("nan")
    total = float((1.0 + clean).prod())
    years = len(clean) / periods
    if years <= 0:
        return float("nan")
    if total <= 0:
        return -1.0
    return total ** (1.0 / years) - 1.0


def annualized_volatility(returns: pd.Series, periods: int = TRADING_DAYS_PER_YEAR) -> float:
    """Annualised standard deviation of daily returns."""
    clean = _clean(returns)
    if len(clean) < 2:
        return float("nan")
    return float(clean.std(ddof=1) * np.sqrt(periods))


def sharpe_ratio(
    returns: pd.Series,
    risk_free: float = 0.0,
    periods: int = TRADING_DAYS_PER_YEAR,
) -> float:
    """Annualised Sharpe ratio against a flat annual risk-free rate."""
    clean = _clean(returns)
    if len(clean) < 2:
        return float("nan")
    daily_rf = (1.0 + risk_free) ** (1.0 / periods) - 1.0
    excess = clean - daily_rf
    std = float(excess.std(ddof=1))
    if std == 0:
        return float("nan")
    return float(excess.mean() / std * np.sqrt(periods))


def information_ratio(excess_returns: pd.Series, periods: int = TRADING_DAYS_PER_YEAR) -> float:
    """Annualised IR of an excess-return series (mean / std, annualised)."""
    clean = _clean(excess_returns)
    if len(clean) < 2:
        return float("nan")
    std = float(clean.std(ddof=1))
    if std == 0:
        return float("nan")
    return float(clean.mean() / std * np.sqrt(periods))


def drawdown_series(nav: pd.Series) -> pd.Series:
    """Drawdown path of a net-value curve (0 at a new high, negative below)."""
    series = pd.Series(nav).astype("float64").dropna()
    if series.empty:
        return series
    return series / series.cummax() - 1.0


def max_drawdown(nav: pd.Series) -> float:
    """Worst peak-to-trough drawdown of a net-value curve (negative number)."""
    drawdowns = drawdown_series(nav)
    if drawdowns.empty:
        return float("nan")
    return float(drawdowns.min())


def t_statistic(returns: pd.Series) -> float:
    """t-statistic of the mean return being different from zero."""
    clean = _clean(returns)
    if len(clean) < 2:
        return float("nan")
    std = float(clean.std(ddof=1))
    if std == 0:
        return float("nan")
    return float(clean.mean() / std * np.sqrt(len(clean)))


def hit_rate(returns: pd.Series) -> float:
    """Share of periods with a positive return."""
    clean = _clean(returns)
    if clean.empty:
        return float("nan")
    return float((clean > 0).mean())


def rolling_win_rate(
    returns: pd.Series,
    window: int = TRADING_DAYS_PER_YEAR,
    min_periods: int | None = None,
) -> float:
    """Share of rolling windows whose compounded return is positive."""
    clean = _clean(returns)
    min_periods = min_periods or max(window // 2, 1)
    if len(clean) < min_periods:
        return float("nan")
    compounded = (1.0 + clean).rolling(window, min_periods=min_periods).apply(np.prod, raw=True) - 1.0
    compounded = compounded.dropna()
    if compounded.empty:
        return float("nan")
    return float((compounded > 0).mean())


def annual_returns(returns: pd.Series) -> pd.Series:
    """Calendar-year compounded returns."""
    clean = _clean(returns)
    if clean.empty:
        return pd.Series(dtype="float64")
    return clean.groupby(clean.index.year).apply(lambda s: float((1.0 + s).prod() - 1.0))


def summarize(
    returns: pd.Series,
    *,
    benchmark_returns: pd.Series | None = None,
    periods: int = TRADING_DAYS_PER_YEAR,
) -> dict[str, float]:
    """One dictionary covering every acceptance gate in ``ValidationConfig``.

    When ``benchmark_returns`` is supplied, the excess statistics are computed on
    the *daily arithmetic difference* of the two return series, which is the
    standard definition of a benchmark-relative return for a long-only book.
    """
    clean = _clean(returns)
    result: dict[str, float] = {
        "n_days": float(len(clean)),
        "annual_return": annualized_return(clean, periods),
        "annual_volatility": annualized_volatility(clean, periods),
        "sharpe": sharpe_ratio(clean, periods=periods),
        "max_drawdown": max_drawdown(cumulative_returns(clean)),
        "t_stat": t_statistic(clean),
        "hit_rate": hit_rate(clean),
        "rolling_12m_win_rate": rolling_win_rate(clean, window=periods),
    }

    if benchmark_returns is not None:
        benchmark = _clean(benchmark_returns)
        joined = pd.concat([clean.rename("strategy"), benchmark.rename("benchmark")], axis=1).dropna()
        if not joined.empty:
            excess = joined["strategy"] - joined["benchmark"]
            result.update(
                {
                    "benchmark_annual_return": annualized_return(joined["benchmark"], periods),
                    "excess_annual_return": annualized_return(excess, periods),
                    "excess_annual_volatility": annualized_volatility(excess, periods),
                    "information_ratio": information_ratio(excess, periods),
                    "excess_max_drawdown": max_drawdown(cumulative_returns(excess)),
                    "excess_t_stat": t_statistic(excess),
                    "excess_rolling_12m_win_rate": rolling_win_rate(excess, window=periods),
                }
            )
    return result


def gate_report(stats: dict[str, float], thresholds: dict[str, float]) -> pd.DataFrame:
    """Compare a stats dictionary against acceptance thresholds.

    ``thresholds`` maps a stats key to its minimum acceptable value. The
    function deliberately reports every gate rather than a single verdict, so a
    near miss is visible instead of collapsing into "pass"/"fail".
    """
    rows = []
    for key, threshold in thresholds.items():
        value = stats.get(key, float("nan"))
        passed = bool(np.isfinite(value) and value >= threshold)
        rows.append({"metric": key, "value": value, "threshold": threshold, "pass": passed})
    return pd.DataFrame(rows)


#: The acceptance gates from the research plan, in ``summarize`` vocabulary.
ACCEPTANCE_GATES: dict[str, float] = {
    "excess_annual_return": 0.10,
    "information_ratio": 0.80,
    "excess_max_drawdown": -0.15,
    "max_drawdown": -0.25,
    "excess_rolling_12m_win_rate": 0.70,
    "excess_t_stat": 2.0,
}
