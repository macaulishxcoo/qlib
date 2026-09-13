"""Phase C evaluation: is a factor worth anything, and is it worth anything *after costs*?

Every factor gets the same report, in this order of importance:

1. **Net long-side excess** after turnover and the real cost model. A factor with
   a beautiful IC that dies after costs is a "correct but untradeable" result,
   and the research plan treats it as a rejection, not a partial success.
2. **Rank IC / ICIR and its decay** across 1/5/10/20-day horizons.
3. **Per-year stability**, because a factor that only worked in 2015 is a
   history lesson, not a signal.
4. **Quantile monotonicity**, which distinguishes a factor from a tail accident.
5. **Correlation with the baseline factors**, which says whether it is new
   information or a re-labelled version of something already in the library.

All of it is vectorised over dates so a full-library run stays interactive.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from .config import DEFAULT_COST, TARGET_HORIZONS, CostModel
from .ops import cs_rank, ts_delay

TRADING_DAYS = 244


# --------------------------------------------------------------------------- #
# forward returns
# --------------------------------------------------------------------------- #


def forward_returns(
    panel: pd.DataFrame,
    horizons: tuple[int, ...] = TARGET_HORIZONS,
    *,
    entry: str = "next_open",
) -> pd.DataFrame:
    """Forward returns aligned to the *signal* date.

    ``entry="next_open"`` implements the tradable convention: the signal is formed
    at the close of ``T``, the position is opened at the open of ``T+1``, and it
    is closed at the close of ``T+h``. Using close-to-close instead quietly hands
    the strategy one day of free information.
    """
    close = panel["adj_close"].astype("float64")
    frame = panel[["date", "code"]].copy()

    if entry == "next_open":
        entry_price = ts_delay(panel, panel["adj_open"].astype("float64"), -1)
    elif entry == "close":
        entry_price = close
    else:
        raise ValueError("entry must be 'next_open' or 'close'")

    for horizon in horizons:
        exit_price = ts_delay(panel, close, -horizon)
        with np.errstate(divide="ignore", invalid="ignore"):
            frame[f"fwd_{horizon}"] = exit_price / entry_price - 1.0
    return frame


# --------------------------------------------------------------------------- #
# information coefficient
# --------------------------------------------------------------------------- #


def rank_ic_by_date(
    dates: pd.Series,
    factor: pd.Series,
    forward: pd.Series,
    min_names: int = 30,
) -> pd.Series:
    """Spearman rank IC per date, computed with groupby transforms only."""
    frame = pd.DataFrame(
        {
            "date": np.asarray(dates),
            "factor": np.asarray(factor, dtype="float64"),
            "forward": np.asarray(forward, dtype="float64"),
        }
    ).dropna()
    if frame.empty:
        return pd.Series(dtype="float64")

    grouped = frame.groupby("date", sort=True)
    frame["fr"] = grouped["factor"].rank(pct=True)
    frame["yr"] = grouped["forward"].rank(pct=True)

    grouped = frame.groupby("date", sort=True)
    count = grouped["fr"].transform("size")
    mean_f = grouped["fr"].transform("mean")
    mean_y = grouped["yr"].transform("mean")
    var_f = grouped["fr"].transform("var")
    var_y = grouped["yr"].transform("var")
    covariance = ((frame["fr"] - mean_f) * (frame["yr"] - mean_y)).groupby(frame["date"]).transform("mean")

    with np.errstate(divide="ignore", invalid="ignore"):
        ic = covariance / np.sqrt(var_f * var_y)
    ic = ic.where(count >= min_names)
    return pd.Series(ic.to_numpy(), index=frame.index).groupby(frame["date"]).first().sort_index()


def ic_summary(ic: pd.Series, periods: int = TRADING_DAYS) -> dict[str, float]:
    """Mean IC, ICIR, t-statistic, and the share of dates with a positive IC."""
    clean = pd.Series(ic).replace([np.inf, -np.inf], np.nan).dropna()
    if clean.empty:
        return {"ic_mean": float("nan"), "ic_std": float("nan"), "icir": float("nan"),
                "ic_t_stat": float("nan"), "ic_positive_rate": float("nan"), "ic_n_dates": 0.0}
    std = float(clean.std(ddof=1))
    return {
        "ic_mean": float(clean.mean()),
        "ic_std": std,
        "icir": float(clean.mean() / std) if std > 0 else float("nan"),
        "ic_t_stat": float(clean.mean() / std * np.sqrt(len(clean))) if std > 0 else float("nan"),
        "ic_positive_rate": float((clean > 0).mean()),
        "ic_n_dates": float(len(clean)),
    }


# --------------------------------------------------------------------------- #
# quantile portfolios
# --------------------------------------------------------------------------- #


def quantile_returns_by_date(
    dates: pd.Series,
    factor: pd.Series,
    forward: pd.Series,
    n_quantiles: int = 10,
    min_names: int = 30,
) -> pd.DataFrame:
    """Mean forward return per factor quantile per date.

    Quantile 1 is the lowest factor value, ``n_quantiles`` the highest, so the
    frame can be read directly against the factor's declared ``direction``.
    """
    frame = pd.DataFrame(
        {
            "date": np.asarray(dates),
            "factor": np.asarray(factor, dtype="float64"),
            "forward": np.asarray(forward, dtype="float64"),
        }
    ).dropna()
    if frame.empty:
        return pd.DataFrame()

    counts = frame.groupby("date")["factor"].transform("size")
    frame = frame[counts >= min_names]
    if frame.empty:
        return pd.DataFrame()

    percentile = frame.groupby("date")["factor"].rank(pct=True)
    frame = frame.assign(
        quantile=np.minimum((percentile * n_quantiles).apply(np.ceil).astype("int64"), n_quantiles)
    )
    return frame.groupby(["date", "quantile"])["forward"].mean().unstack("quantile")


def quantile_summary(quantile_returns: pd.DataFrame, periods: int = TRADING_DAYS) -> pd.DataFrame:
    """Per-quantile annualised mean return, hit rate, and the top-minus-bottom spread."""
    if quantile_returns.empty:
        return pd.DataFrame()
    rows = []
    for quantile in quantile_returns.columns:
        series = quantile_returns[quantile].dropna()
        if series.empty:
            continue
        rows.append(
            {
                "quantile": int(quantile),
                "annual_return": float(series.mean() * periods),
                "hit_rate": float((series > 0).mean()),
                "n_dates": int(len(series)),
            }
        )
    summary = pd.DataFrame(rows).set_index("quantile")
    if len(summary) >= 2:
        top = int(summary.index.max())
        bottom = int(summary.index.min())
        spread = (quantile_returns[top] - quantile_returns[bottom]).dropna()
        summary.attrs["long_short_annual"] = float(spread.mean() * periods)
        summary.attrs["long_short_ir"] = (
            float(spread.mean() / spread.std(ddof=1) * np.sqrt(periods)) if spread.std(ddof=1) > 0 else float("nan")
        )
    return summary


def quantile_monotonicity(quantile_returns: pd.DataFrame) -> float:
    """Spearman correlation between quantile index and its mean return.

    +1 means perfectly monotone in the factor's own direction, -1 perfectly
    inverted, 0 means the ordering carries no information.
    """
    if quantile_returns.empty or quantile_returns.shape[1] < 3:
        return float("nan")
    means = quantile_returns.mean()
    positions = pd.Series(np.asarray(means.index, dtype="float64"))
    return float(positions.corr(pd.Series(means.to_numpy()), method="spearman"))


# --------------------------------------------------------------------------- #
# cost-aware long-side evaluation
# --------------------------------------------------------------------------- #


def long_side_turnover(
    dates: pd.Series,
    codes: pd.Series,
    factor: pd.Series,
    *,
    top_fraction: float = 0.1,
    min_names: int = 30,
) -> pd.Series:
    """Fraction of the top-quantile book replaced each day.

    This is the number that decides whether a factor is tradeable: it converts a
    signal's horizon into the cost it will actually pay. Membership is tracked by
    *security code*, not by row position -- using positional ids would report a
    fictional 100% turnover every day.
    """
    frame = pd.DataFrame(
        {
            "date": np.asarray(dates),
            "code": np.asarray(codes),
            "factor": np.asarray(factor, dtype="float64"),
        }
    ).dropna(subset=["factor"])
    counts = frame.groupby("date")["factor"].transform("size")
    frame = frame[counts >= min_names]
    if frame.empty:
        return pd.Series(dtype="float64")

    percentile = frame.groupby("date")["factor"].rank(pct=True, ascending=False)
    held = frame[percentile <= top_fraction]
    per_date = held.groupby("date")["code"].apply(set).sort_index()
    if len(per_date) < 2:
        return pd.Series(dtype="float64")

    turnovers = []
    index = []
    previous: set | None = None
    for date, members in per_date.items():
        if previous:
            turnovers.append(len(members - previous) / len(previous))
            index.append(date)
        previous = members
    return pd.Series(turnovers, index=pd.Index(index, name="date"))


def net_long_excess(
    daily_gross_excess: pd.Series,
    daily_turnover: pd.Series,
    cost: CostModel = DEFAULT_COST,
    periods: int = TRADING_DAYS,
) -> dict[str, float]:
    """Apply round-trip costs to a gross long-side excess series.

    ``daily_turnover`` is the share of the book replaced that day; each unit of
    replacement pays one round trip.
    """
    joined = pd.concat(
        [daily_gross_excess.rename("gross"), daily_turnover.rename("turnover")], axis=1
    ).dropna()
    if joined.empty:
        return {"gross_annual": float("nan"), "cost_annual": float("nan"), "net_annual": float("nan")}
    cost_daily = joined["turnover"] * cost.round_trip
    net = joined["gross"] - cost_daily
    return {
        "gross_annual": float(joined["gross"].mean() * periods),
        "cost_annual": float(cost_daily.mean() * periods),
        "net_annual": float(net.mean() * periods),
        "net_ir": float(net.mean() / net.std(ddof=1) * np.sqrt(periods)) if net.std(ddof=1) > 0 else float("nan"),
        "annual_one_way_turnover": float(joined["turnover"].mean() * periods),
    }


# --------------------------------------------------------------------------- #
# the full report
# --------------------------------------------------------------------------- #


def factor_report(
    panel: pd.DataFrame,
    factor_values: pd.Series,
    *,
    horizons: tuple[int, ...] = (1, 5, 10, 20),
    n_quantiles: int = 10,
    min_names: int = 30,
) -> dict[str, object]:
    """Everything the research plan asks about one factor, in one call."""
    forward = forward_returns(panel, horizons=horizons, entry="next_open")
    dates = panel["date"]

    report: dict[str, object] = {"ic": {}, "quantiles": {}, "years": {}}
    for horizon in horizons:
        column = f"fwd_{horizon}"
        ic = rank_ic_by_date(dates, factor_values, forward[column], min_names=min_names)
        report["ic"][horizon] = ic_summary(ic)

        quantiles = quantile_returns_by_date(dates, factor_values, forward[column],
                                             n_quantiles=n_quantiles, min_names=min_names)
        report["quantiles"][horizon] = {
            "summary": quantile_summary(quantiles),
            "monotonicity": quantile_monotonicity(quantiles),
            "top_minus_bottom_annual": quantiles_summary_spread(quantiles),
        }

        frame = pd.DataFrame({"date": np.asarray(dates), "factor": np.asarray(factor_values),
                              "forward": np.asarray(forward[column], dtype="float64")}).dropna()
        if not frame.empty:
            # Group by an external year Series with an explicit column selection:
            # this avoids the pandas >= 2.2 ``include_groups`` deprecation and
            # keeps working on older releases.
            by_year = (
                frame.groupby(frame["date"].dt.year)[["factor", "forward"]]
                .apply(lambda g: g["factor"].corr(g["forward"], method="spearman"))
            )
            report["years"][horizon] = by_year
    return report


def quantiles_summary_spread(quantile_returns: pd.DataFrame) -> float:
    """Annualised top-minus-bottom mean spread, or NaN when it cannot be formed."""
    if quantile_returns.empty or quantile_returns.shape[1] < 2:
        return float("nan")
    top = int(quantile_returns.columns.max())
    bottom = int(quantile_returns.columns.min())
    spread = (quantile_returns[top] - quantile_returns[bottom]).dropna()
    if spread.empty:
        return float("nan")
    return float(spread.mean() * TRADING_DAYS)


def factor_correlation(
    panel: pd.DataFrame,
    factor_frame: pd.DataFrame,
    names: list[str] | None = None,
) -> pd.DataFrame:
    """Cross-sectional rank correlation between factors, averaged over dates.

    Ranking first and then taking the Pearson correlation of the ranks is exactly
    Spearman, and it avoids putting a datetime column in front of ``.corr()``.
    """
    selected = names or [c for c in factor_frame.columns if c not in {"date", "code"}]
    ranked = factor_frame[selected].apply(lambda column: cs_rank(panel, column))
    ranked.index = pd.Index(pd.Series(factor_frame["date"]).to_numpy(), name="date")
    return ranked.groupby(level="date").corr().groupby(level=1).mean()


# --------------------------------------------------------------------------- #
# cost-aware long-side series
# --------------------------------------------------------------------------- #


def long_side_daily(
    dates: pd.Series,
    codes: pd.Series,
    factor: pd.Series,
    forward: pd.Series,
    *,
    top_fraction: float = 0.1,
    min_names: int = 30,
    cost: CostModel = DEFAULT_COST,
) -> pd.DataFrame:
    """Daily long-side excess and its cost, for one factor.

    Gross excess is the top-fraction mean forward return minus the
    equal-weighted universe mean on the same date, so the number is a
    benchmark-relative return rather than disguised beta.

    Turnover here is the **unbuffered** daily replacement rate, which is the
    pessimistic bound: it is what a factor costs if every rank flip is traded.
    The portfolio layer's exit buffer is what makes the real book cheaper, so
    treat this column as a floor on cost, not a forecast of it.
    """
    frame = pd.DataFrame(
        {
            "date": np.asarray(dates),
            "code": np.asarray(codes),
            "factor": np.asarray(factor, dtype="float64"),
            "forward": np.asarray(forward, dtype="float64"),
        }
    ).dropna()
    if frame.empty:
        return pd.DataFrame(columns=["gross", "turnover", "cost", "net"])

    counts = frame.groupby("date")["factor"].transform("size")
    frame = frame[counts >= min_names]
    if frame.empty:
        return pd.DataFrame(columns=["gross", "turnover", "cost", "net"])

    percentile = frame.groupby("date")["factor"].rank(pct=True, ascending=False)
    top = frame[percentile <= top_fraction]
    gross = top.groupby("date")["forward"].mean() - frame.groupby("date")["forward"].mean()

    turnover = long_side_turnover(dates, codes, factor, top_fraction=top_fraction, min_names=min_names)
    result = pd.DataFrame({"gross": gross})
    result["turnover"] = turnover.reindex(result.index).fillna(0.0)
    result["cost"] = result["turnover"] * cost.round_trip
    result["net"] = result["gross"] - result["cost"]
    return result.dropna(subset=["gross"])


def screen_factors(
    panel: pd.DataFrame,
    factor_frame: pd.DataFrame,
    names: list[str] | None = None,
    *,
    horizons: tuple[int, ...] = (1, 5, 10, 20),
    n_quantiles: int = 10,
    min_names: int = 30,
    cost: CostModel = DEFAULT_COST,
) -> pd.DataFrame:
    """One summary row per factor: IC, stability, monotonicity, cost-aware net.

    This is the Phase C screen. The column that decides whether a factor is worth
    carrying forward is ``net_{h}`` -- the annualised long-side excess **after**
    paying the real cost model on unbuffered turnover.
    """
    selected = names or [c for c in factor_frame.columns if c not in {"date", "code"}]
    forward_all = forward_returns(panel, horizons=horizons, entry="next_open")
    dates = panel["date"]
    codes = panel["code"]

    rows = []
    for name in selected:
        values = factor_frame[name]
        row: dict[str, object] = {"factor": name}
        for horizon in horizons:
            column = f"fwd_{horizon}"
            ic = rank_ic_by_date(dates, values, forward_all[column], min_names=min_names)
            summary = ic_summary(ic)
            quantiles = quantile_returns_by_date(dates, values, forward_all[column],
                                                 n_quantiles=n_quantiles, min_names=min_names)
            row[f"ic_{horizon}"] = summary["ic_mean"]
            row[f"t_{horizon}"] = summary["ic_t_stat"]
            row[f"icpos_{horizon}"] = summary["ic_positive_rate"]
            row[f"ls_{horizon}"] = quantiles_summary_spread(quantiles)
            row[f"mono_{horizon}"] = quantile_monotonicity(quantiles)

            daily = long_side_daily(dates, codes, values, forward_all[column],
                                    min_names=min_names, cost=cost)
            if daily.empty:
                row[f"net_{horizon}"] = float("nan")
                row[f"turn_{horizon}"] = float("nan")
            else:
                row[f"net_{horizon}"] = float(daily["net"].mean() * TRADING_DAYS)
                row[f"turn_{horizon}"] = float(daily["turnover"].mean() * TRADING_DAYS)
        rows.append(row)

    frame = pd.DataFrame(rows).set_index("factor")
    if f"ic_{horizons[0]}" in frame.columns:
        frame = frame.sort_values(f"ic_{horizons[0]}", ascending=False)
    return frame
