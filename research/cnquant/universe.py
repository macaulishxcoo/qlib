"""Point-in-time universe construction and tradability marking.

This module answers, for every ``(date, code)`` pair, three questions the
backtest depends on and that a naive panel leaves implicit:

1. **Was this name part of the investable universe on that date?**
   (listing age, delisting date, board, ST status)
2. **Was it liquid enough for a ¥500k book?**
3. **Was it actually tradable that day?**
   (suspended, limit-up, limit-down)

Getting (3) wrong is what makes a daily A-share backtest look far better than
reality: you cannot buy a name that opened limit-up, and you cannot sell one
that opened limit-down.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from .config import UniverseRules


def round_half_up(values, decimals: int = 2):
    """Exchange-style rounding (half away from zero), unlike numpy's banker's rounding.

    A naive ``np.floor(x * 100 + 0.5) / 100`` is wrong for decimal ties because the
    product is not exactly representable: ``11.055`` is stored as
    ``11.054999999999999716``, so the floor yields ``11.05`` where the exchange
    publishes ``11.06``. A magnitude-relative epsilon restores the intended tie
    behaviour without affecting genuine non-ties (limit prices derive from a
    2-decimal ``preclose``, so a true value never sits within 1e-9 of a tie).
    """
    factor = 10.0 ** decimals
    is_series = isinstance(values, pd.Series)
    array = np.asarray(values, dtype="float64")
    scaled = array * factor
    epsilon = np.abs(scaled) * 1e-12 + 1e-9
    rounded = np.where(
        scaled >= 0,
        np.floor(scaled + 0.5 + epsilon),
        np.ceil(scaled - 0.5 - epsilon),
    ) / factor
    if is_series:
        return pd.Series(rounded, index=values.index, name=values.name)
    return rounded


def add_listing_age(panel: pd.DataFrame, basic: pd.DataFrame) -> pd.DataFrame:
    """Attach ``ipo_date``/``out_date`` and a calendar-day listing age."""
    out = panel.merge(
        basic[["code", "ipo_date", "out_date"]].drop_duplicates(subset=["code"]),
        on="code",
        how="left",
    ).reset_index(drop=True)
    # A merge can only produce a unique RangeIndex after the reset above, which
    # matters because later steps align Series on this index.
    out["listed_days"] = (out["date"] - out["ipo_date"]).dt.days
    # Calendar days is a conservative proxy; it only ever *includes* more names
    # than a trading-day count would, so the 60-day filter stays honest.
    out["is_delisted_on_date"] = out["out_date"].notna() & (out["date"] > out["out_date"])
    return out


def mark_limit_prices(panel: pd.DataFrame) -> pd.DataFrame:
    """Compute daily limit-up/limit-down prices and hit flags from ``preclose``.

    Uses **unadjusted** prices, because that is what the exchange's price band is
    defined on. When ``preclose`` is missing, the previous unadjusted close is
    used as a fallback.
    """
    out = panel.sort_values(["code", "date"]).copy()

    preclose = out["preclose"] if "preclose" in out.columns else pd.Series(np.nan, index=out.index)
    if "close" in out.columns:
        fallback = out.groupby("code", sort=False)["close"].shift(1)
        preclose = preclose.fillna(fallback)
    out["preclose_used"] = preclose

    is_st = out["isST"].fillna(0).astype(bool) if "isST" in out.columns else pd.Series(False, index=out.index)
    band = np.where(is_st, 0.05, 0.10)

    out["limit_up_price"] = round_half_up(out["preclose_used"] * (1.0 + band))
    out["limit_down_price"] = round_half_up(out["preclose_used"] * (1.0 - band))

    tolerance = 0.002
    if "high" in out.columns:
        out["touched_limit_up"] = out["high"] >= out["limit_up_price"] * (1 - tolerance)
        out["touched_limit_down"] = out["low"] <= out["limit_down_price"] * (1 + tolerance)
    if "close" in out.columns:
        out["close_at_limit_up"] = out["close"] >= out["limit_up_price"] * (1 - tolerance)
        out["close_at_limit_down"] = out["close"] <= out["limit_down_price"] * (1 + tolerance)
    return out


def mark_tradability(panel: pd.DataFrame) -> pd.DataFrame:
    """Flag suspension and one-word limit moves that block execution."""
    out = panel.copy()

    if "tradestatus" in out.columns:
        suspended = out["tradestatus"].fillna(0).astype(int) != 1
    else:
        suspended = out["volume"].fillna(0) <= 0 if "volume" in out.columns else pd.Series(False, index=out.index)
    out["is_suspended"] = suspended

    # A name that closes at the limit is treated as unbuyable on the next open
    # unless the open itself moves off the band; the engine re-checks with the
    # real next-day open. These flags are the *same-day* screen.
    out["cannot_buy_today"] = out["is_suspended"] | out.get(
        "close_at_limit_up", pd.Series(False, index=out.index)
    )
    out["cannot_sell_today"] = out["is_suspended"] | out.get(
        "close_at_limit_down", pd.Series(False, index=out.index)
    )
    return out


def add_liquidity(panel: pd.DataFrame, rules: UniverseRules | None = None) -> pd.DataFrame:
    """Rolling average traded value, used for the capacity filter."""
    rules = rules or UniverseRules()
    out = panel.sort_values(["code", "date"]).copy()
    if "amount" not in out.columns:
        out["avg_amount"] = np.nan
        return out
    window = max(int(rules.amount_lookback_days), 1)
    out["avg_amount"] = (
        out.groupby("code", sort=False)["amount"]
        .transform(lambda s: s.rolling(window, min_periods=max(window // 2, 1)).mean())
    )
    return out


def build_investable_mask(panel: pd.DataFrame, rules: UniverseRules | None = None) -> pd.Series:
    """Boolean mask: may this ``(date, code)`` be held/opened under the rules?"""
    rules = rules or UniverseRules()
    mask = pd.Series(True, index=panel.index)

    mask &= ~panel.get("is_delisted_on_date", pd.Series(False, index=panel.index)).fillna(False)
    mask &= panel.get("listed_days", pd.Series(np.inf, index=panel.index)).fillna(-1) >= rules.min_listing_days

    if rules.exclude_st and "isST" in panel.columns:
        mask &= panel["isST"].fillna(0).astype(int) == 0
    if rules.exclude_suspended:
        mask &= ~panel.get("is_suspended", pd.Series(False, index=panel.index)).fillna(False)
    if rules.min_avg_amount > 0:
        mask &= panel.get("avg_amount", pd.Series(np.inf, index=panel.index)).fillna(0) >= rules.min_avg_amount

    return mask.fillna(False)


def prepare_panel(
    raw_panel: pd.DataFrame,
    basic: pd.DataFrame,
    rules: UniverseRules | None = None,
    industry: pd.DataFrame | None = None,
) -> pd.DataFrame:
    """Full Phase A pipeline: annotate, mark tradability, filter, and score quality."""
    rules = rules or UniverseRules()
    panel = add_listing_age(raw_panel, basic)
    panel = mark_limit_prices(panel)
    panel = mark_tradability(panel)
    panel = add_liquidity(panel, rules)
    if industry is not None and not industry.empty and "industry" in industry.columns:
        panel = panel.merge(industry[["code", "industry"]], on="code", how="left").reset_index(drop=True)
    panel["investable"] = build_investable_mask(panel, rules)
    return panel.sort_values(["date", "code"]).reset_index(drop=True)


def data_quality_report(panel: pd.DataFrame) -> pd.DataFrame:
    """One row per column: coverage, and the share of usable observations."""
    rows = []
    total = len(panel)
    for column in panel.columns:
        series = panel[column]
        non_null = int(series.notna().sum())
        rows.append(
            {
                "column": column,
                "dtype": str(series.dtype),
                "non_null": non_null,
                "coverage": (non_null / total) if total else 0.0,
                "n_unique": int(series.nunique(dropna=True)),
            }
        )
    return pd.DataFrame(rows).sort_values("coverage")


# --------------------------------------------------------------------------- #
# preflight
# --------------------------------------------------------------------------- #

#: Columns the whole stack needs. Missing any of these is a hard error.
PANEL_REQUIRED: tuple[str, ...] = (
    "date",
    "code",
    "adj_open",
    "adj_close",
    "open",
    "limit_up_price",
    "limit_down_price",
    "is_suspended",
    "investable",
)

#: Columns that unlock particular factor families. Absence is a warning: the
#: affected factors degrade to NaN rather than aborting the batch.
PANEL_OPTIONAL: tuple[str, ...] = (
    "high",
    "low",
    "preclose",
    "volume",
    "amount",
    "turn",
    "isST",
    "tradestatus",
    "pbMRQ",
    "peTTM",
    "psTTM",
    "avg_amount",
    "industry",
    "close_at_limit_up",
    "touched_limit_up",
)


def preflight_panel(panel: pd.DataFrame) -> tuple[list[str], list[str]]:
    """Validate a panel before the expensive stages run.

    Returns
    -------
    ``(errors, warnings)``. Errors mean the run cannot produce a meaningful
    answer; warnings mean it will run but with reduced coverage, and they name
    which factor families are lost so a surprising all-NaN column is never a
    mystery.
    """
    errors: list[str] = []
    warnings: list[str] = []

    if panel is None or len(panel) == 0:
        return ["panel is empty"], []

    missing_required = [name for name in PANEL_REQUIRED if name not in panel.columns]
    if missing_required:
        errors.append(
            "missing required columns: " + ", ".join(missing_required)
            + " (build the panel with cnquant.universe.prepare_panel)"
        )

    missing_optional = [name for name in PANEL_OPTIONAL if name not in panel.columns]
    if missing_optional:
        warnings.append(
            "missing optional columns: " + ", ".join(missing_optional)
            + " -- the factors that depend on them will be all-NaN"
        )

    if "date" in panel.columns:
        if panel["date"].isna().any():
            errors.append(f"{int(panel['date'].isna().sum())} rows have a null date")
    if "code" in panel.columns:
        if panel["code"].isna().any():
            errors.append(f"{int(panel['code'].isna().sum())} rows have a null code")

    if {"date", "code"}.issubset(panel.columns):
        duplicates = int(panel.duplicated(subset=["date", "code"]).sum())
        if duplicates:
            errors.append(
                f"{duplicates} duplicate (date, code) rows; every downstream pivot"
                " assumes one row per name per day"
            )

    if "investable" in panel.columns:
        share = float(panel["investable"].fillna(False).mean())
        if share == 0.0:
            errors.append(
                "no row is investable; the liquidity/ST/listing filters have removed"
                " the entire universe"
            )
        elif share < 0.2:
            warnings.append(
                f"only {share:.1%} of rows are investable; the filters may be too strict"
            )

    if "adj_is_fallback" in panel.columns:
        fallback = float(panel["adj_is_fallback"].fillna(False).mean())
        if fallback > 0.5:
            warnings.append(
                f"{fallback:.0%} of rows have no adjusted price series; returns will"
                " be computed on unadjusted prices and corporate actions will leak in"
            )

    if {"limit_up_price", "preclose_used"}.issubset(panel.columns):
        if panel["limit_up_price"].isna().mean() > 0.5:
            warnings.append(
                "limit_up_price is mostly null; limit-up buy blocking will barely bind"
            )

    return errors, warnings
