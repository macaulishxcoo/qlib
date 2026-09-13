"""Alternative-data factors with strict point-in-time alignment.

The price/volume library in :mod:`cnquant.factors` is safe by construction: every
input is observable at the close of the signal date. Event and quarterly data is
not. A financial report carries two dates -- the period it describes (``stat_date``)
and the day it became public (``pub_date``) -- and aligning on the former hands
the strategy roughly a month of free information per quarter. That mistake is the
single largest source of fake alpha in alternative-data research, so this module
separates the two concerns explicitly:

* :func:`asof_align` and :func:`trailing_count` / :func:`trailing_sum` do the
  alignment, and **only ever look backwards from ``pub_date``**.
* The factor functions below are pure functions of an already-aligned frame, so
  they can be tested without any network access.

The network layer that produces the raw event frames lives in
``cnquant/sources.py`` and is deliberately kept separate: it is the part that
needs a live endpoint to verify.
"""

from __future__ import annotations

from collections.abc import Sequence

import numpy as np
import pandas as pd


class AlignmentError(ValueError):
    """Raised when an alignment request cannot be honoured safely."""


# --------------------------------------------------------------------------- #
# point-in-time alignment
# --------------------------------------------------------------------------- #


def asof_align(
    panel: pd.DataFrame,
    events: pd.DataFrame,
    value_columns: Sequence[str],
    *,
    pub_col: str = "pub_date",
    max_age_days: int | None = None,
) -> pd.DataFrame:
    """Attach the most recent *published* event values to each panel row.

    Parameters
    ----------
    panel
        Long panel with ``date`` and ``code``. Must be sorted by ``date``
        (``prepare_panel`` guarantees this).
    events
        One row per publication, with ``code``, ``pub_col`` and the value columns.
        An event published on day ``d`` is usable from ``d`` onwards.
    max_age_days
        Drop the value when the latest usable publication is older than this.
        Without a staleness bound, a name that stopped reporting silently keeps
        its last known value forever.

    Returns
    -------
    A frame aligned to ``panel.index`` carrying the value columns plus ``code``,
    ``pub_date`` (the publication actually used) and ``pub_age_days``. Exposing
    the publication date is what lets a caller assert the invariant
    ``pub_date <= date`` instead of trusting it.
    """
    missing = [name for name in ("date", "code") if name not in panel.columns]
    if missing:
        raise AlignmentError("panel is missing: " + ", ".join(missing))
    if pub_col not in events.columns:
        raise AlignmentError(f"events is missing the publication column {pub_col!r}")
    unknown = [name for name in value_columns if name not in events.columns]
    if unknown:
        raise AlignmentError("events is missing value columns: " + ", ".join(unknown))

    def _empty() -> pd.DataFrame:
        out = pd.DataFrame(np.nan, index=panel.index, columns=list(value_columns))
        out["code"] = panel["code"].to_numpy()
        out["pub_date"] = pd.NaT
        out["pub_age_days"] = np.nan
        return out

    right = events[["code", pub_col, *value_columns]].copy()
    right[pub_col] = pd.to_datetime(right[pub_col], errors="coerce")
    right = right.dropna(subset=[pub_col]).sort_values(pub_col, kind="stable").reset_index(drop=True)
    if right.empty:
        return _empty()

    # merge_asof needs the left frame sorted by the `on` key; `_row` carries the
    # original position so the result can be put back exactly.
    left = panel[["date", "code"]].copy()
    left["_row"] = np.arange(len(left))
    left = left.sort_values("date", kind="stable")

    merged = pd.merge_asof(
        left,
        right,
        left_on="date",
        right_on=pub_col,
        by="code",
        direction="backward",
        allow_exact_matches=True,
    )
    if len(merged) != len(panel):
        raise AlignmentError(
            f"merge_asof changed the row count ({len(merged)} vs {len(panel)}); "
            "the events frame likely has duplicate (code, publication) keys"
        )
    merged["pub_age_days"] = (merged["date"] - merged[pub_col]).dt.days

    if max_age_days is not None:
        merged.loc[merged["pub_age_days"] > max_age_days, list(value_columns)] = np.nan

    # Restore position by `_row` and build the result positionally, so the output
    # index is exactly the caller's panel index whatever it happens to be.
    merged = merged.sort_values("_row", kind="stable")
    result = pd.DataFrame(
        merged[list(value_columns)].to_numpy(), index=panel.index, columns=list(value_columns)
    )
    result["code"] = merged["code"].to_numpy()
    result["pub_date"] = merged[pub_col].to_numpy()
    result["pub_age_days"] = merged["pub_age_days"].to_numpy()
    return result


def trailing_count(
    panel: pd.DataFrame,
    events: pd.DataFrame,
    *,
    date_col: str = "date",
    window_days: int = 90,
    lag_days: int = 0,
) -> pd.Series:
    """Number of events for each code in the ``window_days`` before each panel date.

    Only events dated at or before ``date - lag_days`` count, so an event stream
    whose timestamp is the *event* rather than its *disclosure* can be aligned by
    passing the disclosure lag.
    """
    return _trailing(panel, events, date_col=date_col, window_days=window_days,
                     lag_days=lag_days, values=None)


def trailing_sum(
    panel: pd.DataFrame,
    events: pd.DataFrame,
    value_col: str,
    *,
    date_col: str = "date",
    window_days: int = 90,
    lag_days: int = 0,
) -> pd.Series:
    """Sum of ``value_col`` over events in the trailing window, per code."""
    return _trailing(panel, events, date_col=date_col, window_days=window_days,
                     lag_days=lag_days, values=value_col)


def _trailing(
    panel: pd.DataFrame,
    events: pd.DataFrame,
    *,
    date_col: str,
    window_days: int,
    lag_days: int,
    values: str | None,
) -> pd.Series:
    if date_col not in events.columns:
        raise AlignmentError(f"events is missing the date column {date_col!r}")
    if values is not None and values not in events.columns:
        raise AlignmentError(f"events is missing the value column {values!r}")

    frame = events[["code", date_col, *([values] if values else [])]].copy()
    frame[date_col] = pd.to_datetime(frame[date_col], errors="coerce")
    frame = frame.dropna(subset=[date_col])
    if values is not None:
        frame[values] = pd.to_numeric(frame[values], errors="coerce")
        frame = frame.dropna(subset=[values])

    out = np.zeros(len(panel), dtype="float64") if values is None else np.full(len(panel), np.nan)
    if frame.empty:
        return pd.Series(out, index=panel.index, name=values or "event_count")

    panel_dates = pd.to_datetime(panel["date"]).to_numpy()
    panel_codes = panel["code"].to_numpy()

    for code, group in frame.groupby("code", sort=False):
        rows = np.flatnonzero(panel_codes == code)
        if rows.size == 0:
            continue
        event_times = np.sort(group[date_col].to_numpy())
        event_values = (
            group.sort_values(date_col)[values].to_numpy(dtype="float64")
            if values is not None else None
        )
        cut = panel_dates[rows] - np.timedelta64(int(lag_days), "D")
        # Events at or before (date - lag): right edge is inclusive.
        upper = np.searchsorted(event_times, cut, side="right")
        lower = np.searchsorted(
            event_times, cut - np.timedelta64(int(window_days), "D"), side="right"
        )
        if values is None:
            out[rows] = (upper - lower).astype("float64")
        else:
            if event_values is None or event_values.size == 0:
                continue
            cumulative = np.concatenate([[0.0], np.cumsum(event_values)])
            out[rows] = cumulative[upper] - cumulative[lower]

    return pd.Series(out, index=panel.index, name=values or "event_count")


# --------------------------------------------------------------------------- #
# factor constructions on already-aligned frames
# --------------------------------------------------------------------------- #


def shareholder_concentration(
    aligned: pd.DataFrame,
    *,
    count_col: str = "shareholder_count",
) -> pd.Series:
    """Change in shareholder count: fewer holders means more concentrated chips.

    Returned *negated* so that a higher value is the bullish direction (holder
    count falling), matching the library's sign convention.
    """
    counts = pd.to_numeric(aligned[count_col], errors="coerce")
    with np.errstate(divide="ignore", invalid="ignore"):
        change = counts / counts.groupby(aligned["code"], sort=False).transform(
            lambda s: s.shift(1)
        ) - 1.0
    return (-change).rename("shareholder_concentration")


def earnings_forecast_score(
    aligned: pd.DataFrame,
    *,
    type_col: str = "forecast_type",
    change_col: str = "forecast_change_pct",
) -> pd.Series:
    """Map an earnings pre-announcement into a signed score.

    Pre-announcements are mandatory in China when the result crosses disclosure
    thresholds, which makes them a genuinely informative, widely followed, and
    (unlike price factors) non-crowded signal at the daily horizon.
    """
    mapping = {
        "预增": 2.0, "略增": 1.0, "续盈": 1.0, "扭亏": 2.0,
        "不确定": 0.0, "续亏": -1.0, "首亏": -2.0, "略减": -1.0,
        "预减": -2.0, "减亏": 0.5,
    }
    types = aligned[type_col].astype("string") if type_col in aligned.columns else None
    score = types.map(mapping).astype("float64") if types is not None else pd.Series(
        np.nan, index=aligned.index
    )
    if change_col in aligned.columns:
        magnitude = pd.to_numeric(aligned[change_col], errors="coerce")
        # A bounded magnitude term keeps a single 1000% forecast from dominating.
        score = score + np.tanh(magnitude / 100.0)
    return score.rename("earnings_forecast_score")


def institutional_attention(
    aligned: pd.DataFrame,
    *,
    visit_col: str = "visit_count",
    window_days: int = 90,
) -> pd.Series:
    """Institutional site visits per trailing window.

    Attention is a proxy for both information production and crowding, so this is
    deliberately kept as a raw count rather than being rescaled: the screen will
    decide which sign it carries.
    """
    counts = pd.to_numeric(aligned[visit_col], errors="coerce")
    return (counts / max(window_days, 1) * 90.0).rename("institutional_attention")


def margin_balance_change(
    aligned: pd.DataFrame,
    *,
    balance_col: str = "margin_balance",
    window: int = 20,
) -> pd.Series:
    """Trailing change in margin (financing) balance.

    Rising leverage in a name is a crowding signal, so the raw change is reported
    and the screen decides the sign.
    """
    balances = pd.to_numeric(aligned[balance_col], errors="coerce")
    grouped = balances.groupby(aligned["code"], sort=False)
    lagged = grouped.transform(lambda s: s.shift(window))
    with np.errstate(divide="ignore", invalid="ignore"):
        return (balances / lagged - 1.0).rename("margin_balance_change")


def lockup_pressure(
    panel: pd.DataFrame,
    events: pd.DataFrame,
    *,
    date_col: str = "release_date",
    value_col: str = "release_ratio",
    window_days: int = 60,
) -> pd.Series:
    """Forward-looking share-unlock overhang.

    This is the one deliberately *forward* input in the library: a lockup expiry
    is scheduled and publicly known in advance, so using the announced future
    date is not look-ahead. Everything else here looks strictly backwards.
    """
    if date_col not in events.columns:
        raise AlignmentError(f"events is missing {date_col!r}")
    frame = events[["code", date_col, *([value_col] if value_col in events.columns else [])]].copy()
    frame[date_col] = pd.to_datetime(frame[date_col], errors="coerce")
    frame = frame.dropna(subset=[date_col])

    out = np.zeros(len(panel), dtype="float64")
    if frame.empty:
        return pd.Series(out, index=panel.index, name="lockup_pressure")

    panel_dates = pd.to_datetime(panel["date"]).to_numpy()
    panel_codes = panel["code"].to_numpy()
    has_ratio = value_col in frame.columns

    for code, group in frame.groupby("code", sort=False):
        rows = np.flatnonzero(panel_codes == code)
        if rows.size == 0:
            continue
        times = np.sort(group[date_col].to_numpy())
        weights = (
            group.sort_values(date_col)[value_col].to_numpy(dtype="float64")
            if has_ratio else np.ones(len(group), dtype="float64")
        )
        cumulative = np.concatenate([[0.0], np.cumsum(weights)])
        lower = np.searchsorted(times, panel_dates[rows], side="left")
        upper = np.searchsorted(
            times, panel_dates[rows] + np.timedelta64(int(window_days), "D"), side="right"
        )
        out[rows] = cumulative[upper] - cumulative[lower]

    return pd.Series(out, index=panel.index, name="lockup_pressure")


#: Names of the alternative-data factors this module can produce, and the raw
#: event frame each one needs. ``cnquant/sources.py`` is what supplies those frames.
REQUIRED_SOURCES: dict[str, str] = {
    "shareholder_concentration": "quarterly shareholder counts (code, pub_date, shareholder_count)",
    "earnings_forecast_score": "earnings pre-announcements (code, pub_date, forecast_type, forecast_change_pct)",
    "institutional_attention": "institutional site visits (code, pub_date, visit_count)",
    "margin_balance_change": "daily margin balances (code, date, margin_balance)",
    "lockup_pressure": "share unlock schedule (code, release_date, release_ratio)",
}
