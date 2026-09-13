"""Phase C factor library.

Two tiers, deliberately:

* **C1 baseline** -- value, size, momentum, volatility, liquidity, lottery. These
  exist here to serve as *controls*: a differentiated factor is only interesting
  if it is orthogonal to these and still carries information.
* **C2 differentiated** -- signals built from the parts of the tape that
  Alpha158 largely ignores: the overnight/intraday decomposition, volume-price
  divergence, price delay, limit-hit behaviour, and turnover acceleration. They
  are cheaper to compute than they are to crowd, which matters because the
  baseline technical factor zoo has been heavily mined since ~2018.

Every factor is a pure function of the Phase A panel, so the whole library is
runnable the moment the data exists. Event and alternative-data factors
(shareholder counts, earnings pre-announcements, institutional visits, margin
balances, block trades) live in a separate module because they need extra
sources.

Sign convention: ``direction = +1`` means a *higher* factor value is expected to
predict a *higher* forward return. The library never flips signs internally --
that is the evaluator's job, and keeping the raw sign visible makes a wrong
prior obvious instead of silently inverted.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

import numpy as np
import pandas as pd

from .ops import (
    cs_rank,
    factor_panel,
    ts_corr,
    ts_delay,
    ts_max,
    ts_mean,
    ts_min,
    ts_pct_change,
    ts_std,
    ts_sum,
)


@dataclass(frozen=True)
class FactorSpec:
    """One factor: metadata plus its computation."""

    name: str
    group: str
    description: str
    direction: int
    compute: Callable[[pd.DataFrame, dict[str, pd.Series]], pd.Series]


# --------------------------------------------------------------------------- #
# shared primitives
# --------------------------------------------------------------------------- #


def _market_return(panel: pd.DataFrame, ret1: pd.Series) -> pd.Series:
    """Equal-weighted cross-sectional mean return, used as the market proxy."""
    return ret1.groupby(panel["date"], sort=False).transform("mean")


def _log_safe(series: pd.Series) -> pd.Series:
    with np.errstate(divide="ignore", invalid="ignore"):
        return np.log(series.where(series > 0))


def _column(panel: pd.DataFrame, name: str) -> pd.Series:
    """Return ``panel[name]``, or an all-NaN Series when the column is absent.

    Absence is an expected *data* condition, not a programming error: baostock
    rejects a whole request when one field name is invalid, so
    :data:`cnquant.config.DAILY_FIELD_LADDER` may legitimately deliver a panel
    without ``turn``, ``amount`` or the fundamental columns. Degrading the
    affected factors to NaN keeps the rest of the library usable and surfaces the
    gap in the coverage report, instead of aborting the entire factor batch with
    a KeyError.
    """
    if name in panel.columns:
        return panel[name]
    return pd.Series(np.nan, index=panel.index, name=name, dtype="float64")


#: Price columns the whole library is meaningless without. These fail loudly.
ESSENTIAL_COLUMNS: tuple[str, ...] = ("adj_close", "adj_open")


def build_context(panel: pd.DataFrame) -> dict[str, pd.Series]:
    """Primitives many factors share. Computed once per batch.

    Raises
    ------
    KeyError
        When an essential price column is missing. Every other column is
        optional and degrades to NaN via :func:`_column`; without adjusted
        prices there is nothing to compute at all, so this fails loudly rather
        than returning a frame of NaNs that looks like a data problem.
    """
    missing = [name for name in ESSENTIAL_COLUMNS if name not in panel.columns]
    if missing:
        raise KeyError(
            "panel is missing essential price columns: " + ", ".join(missing)
            + "\n  rebuild it with cnquant.universe.prepare_panel(); the adjusted"
            " series comes from baostock adjustflag=1"
        )

    close = panel["adj_close"].astype("float64")
    open_ = panel["adj_open"].astype("float64")
    previous_close = ts_delay(panel, close, 1)

    ret1 = ts_pct_change(panel, close, 1)
    context: dict[str, pd.Series] = {
        "close": close,
        "open": open_,
        "previous_close": previous_close,
        "ret1": ret1,
        "overnight_ret": open_ / previous_close - 1.0,
    }
    context["intraday_ret"] = close / open_ - 1.0
    context["market_ret"] = _market_return(panel, ret1)
    return context


# --------------------------------------------------------------------------- #
# C1: baseline factors
# --------------------------------------------------------------------------- #


def _float_market_cap(panel: pd.DataFrame, context: dict) -> pd.Series:
    """Free-float market cap, backed out of turnover.

    baostock reports ``turn`` as a percentage of free float, so
    ``float_shares = volume * 100 / turn`` and ``float_mcap = float_shares * close``.
    This is the only size measure available from daily bars alone, and it is the
    one that matters for the liquidity screen anyway.
    """
    turn = _column(panel, "turn").astype("float64")
    volume = _column(panel, "volume").astype("float64")
    with np.errstate(divide="ignore", invalid="ignore"):
        float_shares = np.where(turn > 0, volume * 100.0 / turn, np.nan)
    return pd.Series(float_shares, index=panel.index) * context["close"]


def _factor_size(panel: pd.DataFrame, context: dict) -> pd.Series:
    return _log_safe(_float_market_cap(panel, context))


def _factor_bp(panel: pd.DataFrame, context: dict) -> pd.Series:
    pb = panel["pbMRQ"].astype("float64") if "pbMRQ" in panel.columns else pd.Series(np.nan, index=panel.index)
    with np.errstate(divide="ignore", invalid="ignore"):
        return 1.0 / pb.where(pb > 0)


def _factor_ep(panel: pd.DataFrame, context: dict) -> pd.Series:
    pe = panel["peTTM"].astype("float64") if "peTTM" in panel.columns else pd.Series(np.nan, index=panel.index)
    with np.errstate(divide="ignore", invalid="ignore"):
        return 1.0 / pe.where(pe > 0)


def _factor_sp(panel: pd.DataFrame, context: dict) -> pd.Series:
    ps = panel["psTTM"].astype("float64") if "psTTM" in panel.columns else pd.Series(np.nan, index=panel.index)
    with np.errstate(divide="ignore", invalid="ignore"):
        return 1.0 / ps.where(ps > 0)


def _factor_mom_12_1(panel: pd.DataFrame, context: dict) -> pd.Series:
    close = context["close"]
    return ts_delay(panel, close, 21) / ts_delay(panel, close, 252) - 1.0


def _factor_reversal_1m(panel: pd.DataFrame, context: dict) -> pd.Series:
    return -(context["close"] / ts_delay(panel, context["close"], 21) - 1.0)


def _factor_volatility_20(panel: pd.DataFrame, context: dict) -> pd.Series:
    return ts_std(panel, context["ret1"], 20)


def _factor_volatility_60(panel: pd.DataFrame, context: dict) -> pd.Series:
    return ts_std(panel, context["ret1"], 60)


def _factor_beta_60(panel: pd.DataFrame, context: dict) -> pd.Series:
    ret1 = context["ret1"]
    market = context["market_ret"]
    covariance = ts_mean(panel, ret1 * market, 60) - ts_mean(panel, ret1, 60) * ts_mean(panel, market, 60)
    variance = ts_mean(panel, market * market, 60) - ts_mean(panel, market, 60) ** 2
    with np.errstate(divide="ignore", invalid="ignore"):
        return covariance / variance


def _factor_idio_vol_60(panel: pd.DataFrame, context: dict) -> pd.Series:
    beta = _factor_beta_60(panel, context)
    residual = context["ret1"] - beta * context["market_ret"]
    return ts_std(panel, residual, 60)


def _factor_turnover_20(panel: pd.DataFrame, context: dict) -> pd.Series:
    return ts_mean(panel, _column(panel, "turn").astype("float64"), 20)


def _factor_turnover_volatility_20(panel: pd.DataFrame, context: dict) -> pd.Series:
    turn = _column(panel, "turn").astype("float64")
    mean = ts_mean(panel, turn, 20)
    with np.errstate(divide="ignore", invalid="ignore"):
        return ts_std(panel, turn, 20) / mean


def _factor_amihud_20(panel: pd.DataFrame, context: dict) -> pd.Series:
    """Amihud illiquidity: average absolute return per yuan traded, scaled by 1e8."""
    amount = _column(panel, "amount").astype("float64")
    with np.errstate(divide="ignore", invalid="ignore"):
        impact = context["ret1"].abs() / amount.where(amount > 0)
    return ts_mean(panel, impact, 20) * 1e8


def _factor_max_ret_20(panel: pd.DataFrame, context: dict) -> pd.Series:
    """MAX / lottery effect: the single best day in the last month."""
    return ts_max(panel, context["ret1"], 20)


def _factor_skew_20(panel: pd.DataFrame, context: dict) -> pd.Series:
    ret1 = context["ret1"]
    return ret1.groupby(panel["code"], sort=False).transform(
        lambda s: s.rolling(20, min_periods=10).skew()
    )


# --------------------------------------------------------------------------- #
# C2: differentiated factors
# --------------------------------------------------------------------------- #


def _factor_overnight_momentum_20(panel: pd.DataFrame, context: dict) -> pd.Series:
    """Cumulative overnight (close-to-open) return over a month."""
    return ts_sum(panel, context["overnight_ret"], 20)


def _factor_intraday_momentum_20(panel: pd.DataFrame, context: dict) -> pd.Series:
    """Cumulative intraday (open-to-close) return over a month."""
    return ts_sum(panel, context["intraday_ret"], 20)


def _factor_overnight_intraday_spread(panel: pd.DataFrame, context: dict) -> pd.Series:
    """Overnight minus intraday momentum.

    The two components of a daily bar are driven by different clienteles
    (overnight gaps by news and retail order imbalance, the intraday session by
    institutional flow). Their divergence is not represented in Alpha158.
    """
    return _factor_overnight_momentum_20(panel, context) - _factor_intraday_momentum_20(panel, context)


def _factor_volume_price_corr_20(panel: pd.DataFrame, context: dict) -> pd.Series:
    """Rolling correlation between return and turnover: crowding / distribution."""
    return ts_corr(panel, context["ret1"], _column(panel, "turn").astype("float64"), 20)


def _factor_price_delay_20(panel: pd.DataFrame, context: dict) -> pd.Series:
    """Lag-1 market beta: how much of today's move is explained by yesterday's market.

    High values indicate a slow-reacting, under-attended name; the classic
    price-delay anomaly predicts higher forward returns for high-delay stocks.
    """
    lagged_market = context["market_ret"].groupby(panel["code"], sort=False).transform(lambda s: s.shift(1))
    return ts_corr(panel, context["ret1"], lagged_market, 20)


def _factor_limit_up_count_20(panel: pd.DataFrame, context: dict) -> pd.Series:
    """Number of limit-up closes in the last month ("涨停基因")."""
    if "close_at_limit_up" not in panel.columns:
        return pd.Series(np.nan, index=panel.index)
    return ts_sum(panel, panel["close_at_limit_up"].astype("float64"), 20, min_periods=10)


def _factor_limit_touch_count_20(panel: pd.DataFrame, context: dict) -> pd.Series:
    """Days the high touched the limit band, whether or not it closed there."""
    if "touched_limit_up" not in panel.columns:
        return pd.Series(np.nan, index=panel.index)
    return ts_sum(panel, panel["touched_limit_up"].astype("float64"), 20, min_periods=10)


def _factor_turnover_acceleration(panel: pd.DataFrame, context: dict) -> pd.Series:
    """Short-horizon turnover relative to its quarterly baseline."""
    turn = _column(panel, "turn").astype("float64")
    with np.errstate(divide="ignore", invalid="ignore"):
        return ts_mean(panel, turn, 5) / ts_mean(panel, turn, 60)


def _factor_amount_acceleration(panel: pd.DataFrame, context: dict) -> pd.Series:
    """Short-horizon traded value relative to its quarterly baseline."""
    amount = _column(panel, "amount").astype("float64")
    with np.errstate(divide="ignore", invalid="ignore"):
        return ts_mean(panel, amount, 5) / ts_mean(panel, amount, 60)


def _factor_intraday_range_20(panel: pd.DataFrame, context: dict) -> pd.Series:
    """Average daily high-low range relative to the previous close."""
    high = _column(panel, "high").astype("float64")
    low = _column(panel, "low").astype("float64")
    preclose = _column(panel, "preclose").astype("float64")
    with np.errstate(divide="ignore", invalid="ignore"):
        span = (high - low) / preclose.where(preclose > 0)
    return ts_mean(panel, span, 20)


def _factor_close_position_20(panel: pd.DataFrame, context: dict) -> pd.Series:
    """Where the close sits inside the trailing month's high-low range, in [0, 1]."""
    high = _column(panel, "high").astype("float64")
    low = _column(panel, "low").astype("float64")
    highest = ts_max(panel, high, 20)
    lowest = ts_min(panel, low, 20)
    with np.errstate(divide="ignore", invalid="ignore"):
        return (context["close"] - lowest) / (highest - lowest).where(highest > lowest)


def _factor_overnight_volatility_20(panel: pd.DataFrame, context: dict) -> pd.Series:
    """Volatility of the overnight component alone."""
    return ts_std(panel, context["overnight_ret"], 20)


def _factor_intraday_volatility_20(panel: pd.DataFrame, context: dict) -> pd.Series:
    """Volatility of the intraday component alone."""
    return ts_std(panel, context["intraday_ret"], 20)


# --------------------------------------------------------------------------- #
# registry
# --------------------------------------------------------------------------- #

SPECS: tuple[FactorSpec, ...] = (
    # -- C1 baseline --------------------------------------------------------
    FactorSpec("size", "size", "log free-float market cap, backed out of turnover", -1, _factor_size),
    FactorSpec("bp", "value", "book-to-price (1 / pbMRQ)", +1, _factor_bp),
    FactorSpec("ep", "value", "earnings yield (1 / peTTM)", +1, _factor_ep),
    FactorSpec("sp", "value", "sales-to-price (1 / psTTM)", +1, _factor_sp),
    FactorSpec("mom_12_1", "momentum", "12-month momentum skipping the last month", +1, _factor_mom_12_1),
    FactorSpec("reversal_1m", "momentum", "negated 1-month return (short-term reversal)", +1, _factor_reversal_1m),
    FactorSpec("volatility_20", "volatility", "20-day realised volatility of daily returns", -1, _factor_volatility_20),
    FactorSpec("volatility_60", "volatility", "60-day realised volatility of daily returns", -1, _factor_volatility_60),
    FactorSpec("beta_60", "volatility", "60-day beta to the equal-weighted market", -1, _factor_beta_60),
    FactorSpec("idio_vol_60", "volatility", "60-day idiosyncratic volatility vs the market", -1, _factor_idio_vol_60),
    FactorSpec("turnover_20", "liquidity", "20-day average turnover", -1, _factor_turnover_20),
    FactorSpec("turnover_volatility_20", "liquidity", "turnover coefficient of variation", -1, _factor_turnover_volatility_20),
    FactorSpec("amihud_20", "liquidity", "Amihud illiquidity, scaled by 1e8", +1, _factor_amihud_20),
    FactorSpec("max_ret_20", "sentiment", "best single day in the last month (MAX / lottery)", -1, _factor_max_ret_20),
    FactorSpec("skew_20", "sentiment", "skewness of daily returns over a month", -1, _factor_skew_20),
    # -- C2 differentiated --------------------------------------------------
    FactorSpec("overnight_momentum_20", "microstructure", "cumulative close-to-open return", +1, _factor_overnight_momentum_20),
    FactorSpec("intraday_momentum_20", "microstructure", "cumulative open-to-close return", +1, _factor_intraday_momentum_20),
    FactorSpec("overnight_intraday_spread", "microstructure", "overnight minus intraday momentum", +1, _factor_overnight_intraday_spread),
    FactorSpec("overnight_volatility_20", "microstructure", "volatility of the overnight component", -1, _factor_overnight_volatility_20),
    FactorSpec("intraday_volatility_20", "microstructure", "volatility of the intraday component", -1, _factor_intraday_volatility_20),
    FactorSpec("volume_price_corr_20", "microstructure", "return-turnover correlation (crowding)", -1, _factor_volume_price_corr_20),
    FactorSpec("price_delay_20", "microstructure", "lag-1 market beta (price delay)", +1, _factor_price_delay_20),
    FactorSpec("limit_up_count_20", "sentiment", "limit-up closes in the last month", +1, _factor_limit_up_count_20),
    FactorSpec("limit_touch_count_20", "sentiment", "days the high touched the limit band", +1, _factor_limit_touch_count_20),
    FactorSpec("turnover_acceleration", "liquidity", "5-day turnover / 60-day turnover", +1, _factor_turnover_acceleration),
    FactorSpec("amount_acceleration", "liquidity", "5-day traded value / 60-day traded value", +1, _factor_amount_acceleration),
    FactorSpec("intraday_range_20", "volatility", "average daily high-low range over preclose", -1, _factor_intraday_range_20),
    FactorSpec("close_position_20", "momentum", "close position within the trailing month range", +1, _factor_close_position_20),
)

REGISTRY: dict[str, FactorSpec] = {spec.name: spec for spec in SPECS}


def build_factors(
    panel: pd.DataFrame,
    names: list[str] | None = None,
    *,
    raw: bool = True,
) -> pd.DataFrame:
    """Compute factors and return a frame keyed by ``(date, code)``.

    **Row order matches the input panel.** Time-series operators need
    ``(code, date)`` order internally, so the computation runs on a re-sorted
    copy and the result is then re-indexed back. Skipping that step is a silent
    look-ahead generator: a caller that aligns features to labels positionally
    would pair each name's factor with a different name's return.

    Parameters
    ----------
    panel
        Output of :func:`cnquant.universe.prepare_panel`.
    names
        Subset of :data:`REGISTRY` to compute. Defaults to all of them.
    raw
        When True the factors are returned raw (not cross-sectionally ranked or
        neutralised). The evaluator ranks them; the portfolio layer neutralises
        them. Keeping this step raw means a factor can be inspected before any
        transform hides what it actually is.
    """
    selected = names or list(REGISTRY)
    unknown = [name for name in selected if name not in REGISTRY]
    if unknown:
        raise KeyError("unknown factor(s): " + ", ".join(unknown))

    frame = factor_panel(panel)
    context = build_context(frame)

    out = frame[["date", "code"]].copy()
    for name in selected:
        out[name] = REGISTRY[name].compute(frame, context)
    if not raw:
        for name in selected:
            out[name] = cs_rank(frame, out[name])

    # Restore the caller's row order.
    if panel.index.is_unique:
        return out.reindex(panel.index)
    return out.sort_index()


def factor_catalog() -> pd.DataFrame:
    """Metadata table for every registered factor."""
    return pd.DataFrame(
        [
            {"name": spec.name, "group": spec.group, "direction": spec.direction,
             "description": spec.description}
            for spec in SPECS
        ]
    )
