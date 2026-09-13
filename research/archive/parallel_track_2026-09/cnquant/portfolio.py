"""Phase E: turn a cross-sectional score into tradable target weights.

This layer exists because the research plan's central empirical claim is that
*portfolio construction decides more than the factor does* at daily frequency on
a ¥500,000 book. Three levers, in order of impact:

1. **Buffered membership.** A name enters the book when it reaches the top
   ``n_holdings`` and is only sold once it falls outside the top
   ``n_holdings * exit_multiple``. Without the buffer, a rank-50-versus-51 flip
   trades two names; with it, most days trade nothing. This is the single
   largest turnover reduction available and it costs almost no signal quality.
2. **Concentration.** 50 names on ¥500k means ~¥10k positions, which trips the
   ¥5 minimum commission on every order. 25-40 names is the sweet spot.
3. **Score hygiene.** Industry and size neutralisation before ranking, so the
   book is not a disguised small-cap or sector bet.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd


@dataclass(frozen=True)
class PortfolioConfig:
    """Construction rules. Defaults are tuned for a ¥500,000 main-board book."""

    #: Names held in a fully invested book. Kept low deliberately: each name
    #: must be large enough that the ¥5 commission floor stops dominating.
    n_holdings: int = 30
    #: Hold a name until it leaves the top ``n_holdings * exit_multiple``.
    #: 1.0 disables the buffer (pure top-N rebalancing); 2.0 is the usual choice.
    exit_multiple: float = 2.0
    #: Cap any single name's weight.
    max_weight: float = 0.08
    #: Names required before a date's row is considered investable at all.
    min_names: int = 10
    #: Target fraction held in cash (0.0 = fully invested).
    cash_buffer: float = 0.0
    #: "equal", "score", or "inverse_vol".
    weighting: str = "equal"
    #: Cap on names per industry, when an industry column is supplied.
    max_per_industry: int = 8


def industry_demean(panel: pd.DataFrame, values, industry) -> pd.Series:
    """Subtract the per-date industry mean (a fixed-effects transform).

    Equivalent to the residual of a regression on industry dummies, without
    building a 3000 x 90 design matrix per date.
    """
    series = pd.Series(np.asarray(values, dtype="float64"), index=panel.index)
    frame = pd.DataFrame(
        {
            "date": np.asarray(panel["date"]),
            "industry": np.asarray(industry),
            "value": series.to_numpy(),
        }
    )
    group_mean = frame.groupby(["date", "industry"], dropna=False)["value"].transform("mean")
    residual = frame["value"] - group_mean
    return pd.Series(residual.to_numpy(), index=panel.index)


def neutralize_scores(
    panel: pd.DataFrame,
    values,
    *,
    industry=None,
    size=None,
) -> pd.Series:
    """Strip industry and size exposure out of a raw score.

    Order matters: industry is removed first as a fixed effect, then size is
    regressed out of the *industry-demeaned* series (and size is demeaned the
    same way), which is what Frisch-Waugh-Lovell requires for the two-step
    result to equal the joint regression.
    """
    residual = pd.Series(np.asarray(values, dtype="float64"), index=panel.index)

    if industry is not None:
        residual = industry_demean(panel, residual, industry)

    if size is not None:
        size_series = pd.Series(np.asarray(size, dtype="float64"), index=panel.index)
        if industry is not None:
            size_series = industry_demean(panel, size_series, industry)
        frame = pd.DataFrame(
            {
                "date": np.asarray(panel["date"]),
                "y": residual.to_numpy(),
                "x": size_series.to_numpy(),
            }
        ).dropna()
        if not frame.empty:
            grouped = frame.groupby("date")
            mean_y = grouped["y"].transform("mean")
            mean_x = grouped["x"].transform("mean")
            var_x = grouped["x"].transform("var")
            covariance = ((frame["y"] - mean_y) * (frame["x"] - mean_x)).groupby(frame["date"]).transform("mean")
            with np.errstate(divide="ignore", invalid="ignore"):
                beta = covariance / var_x
            frame["residual"] = frame["y"] - beta * frame["x"]
            aligned = frame["residual"].reindex(panel.index)
            residual = aligned.where(aligned.notna(), residual)
    return residual


def _select(
    ranked: pd.Series,
    previous: list[str],
    config: PortfolioConfig,
    industry: pd.Series | None,
) -> list[str]:
    """Buffered top-N selection for one date, in rank order.

    The exit window is clamped to a fraction of the candidate pool. Without that
    clamp a small pool degenerates: with 50 candidates, ``n_holdings=30`` and
    ``exit_multiple=2`` the exit window covers all 50 names, every held name is
    always "still inside" it, and the book freezes permanently -- a failure that
    looks like an excellent low-turnover strategy instead of a bug.
    """
    n = config.n_holdings
    if ranked.empty:
        return []

    previous_set = set(previous)
    exit_cut = int(np.ceil(n * config.exit_multiple))
    exit_cut = min(exit_cut, max(n, int(0.6 * len(ranked))))
    exit_ranked = ranked.iloc[:exit_cut]
    keep = [code for code in exit_ranked.index if code in previous_set]

    entry_order = list(ranked.index)
    if len(keep) >= n:
        # ``keep`` is already in rank order (exit_ranked preserves it), so a
        # fully-held book just trims its tail.
        return keep[:n]

    selected: list[str] = []
    industry_count: dict[str, int] = {}
    if industry is not None:
        for code in keep:
            label = industry.get(code)
            industry_count[label] = industry_count.get(label, 0) + 1

    for code in keep:
        selected.append(code)

    for code in entry_order:
        if len(selected) >= n:
            break
        if code in previous_set:
            continue
        if industry is not None:
            label = industry.get(code)
            if industry_count.get(label, 0) >= config.max_per_industry:
                continue
            industry_count[label] = industry_count.get(label, 0) + 1
        selected.append(code)

    return selected


def _weights_for(
    selected: list[str],
    ranked: pd.Series,
    volatility: pd.Series | None,
    config: PortfolioConfig,
) -> dict[str, float]:
    """Raw weights for the selected names, before capping and renormalisation."""
    if not selected:
        return {}

    if config.weighting == "score" and len(selected) > 1:
        scores = ranked.reindex(selected).astype("float64")
        # Shift to positive territory: a composite z-score is centered on zero,
        # so a raw positive-part weight would drop half the book.
        shifted = scores - scores.min() + 1e-6
        raw = shifted / shifted.sum()
    elif config.weighting == "inverse_vol" and volatility is not None:
        vol = volatility.reindex(selected).astype("float64")
        vol = vol.where(vol > 0)
        if vol.notna().sum() >= max(len(selected) // 2, 1):
            inverse = 1.0 / vol.fillna(vol.median())
            raw = inverse / inverse.sum()
        else:
            raw = pd.Series(1.0 / len(selected), index=selected)
    else:
        raw = pd.Series(1.0 / len(selected), index=selected)

    scale = 1.0 - config.cash_buffer
    weights = raw * scale
    if config.max_weight > 0:
        weights = weights.clip(upper=config.max_weight)
        total = float(weights.sum())
        if total > 0:
            weights = weights * (scale / total)
    return {code: float(value) for code, value in weights.items()}


def build_target_weights(
    panel: pd.DataFrame,
    scores: pd.DataFrame,
    *,
    config: PortfolioConfig | None = None,
    industry: pd.Series | None = None,
    volatility: pd.DataFrame | None = None,
) -> pd.DataFrame:
    """Buffered top-N target weights, indexed by signal date.

    Parameters
    ----------
    panel
        Long panel; supplies ``investable`` (and optionally ``industry``).
    scores
        Wide frame (index = date, columns = code). **Higher is better.**
    industry
        Optional mapping ``code -> industry label`` used for the per-industry cap.
    volatility
        Optional wide frame of per-name volatility, for ``weighting="inverse_vol"``.

    Returns
    -------
    Wide frame of target weights. Rows with no eligible candidate are all-NaN,
    which the engine reads as "hold", never as "liquidate".
    """
    config = config or PortfolioConfig()
    frame = panel[["date", "code", "investable"]].drop_duplicates(subset=["date", "code"], keep="last")
    investable = (
        frame.pivot(index="date", columns="code", values="investable")
        .reindex(index=scores.index, columns=scores.columns)
        .fillna(False)
        .astype(bool)
    )

    if industry is None and "industry" in panel.columns:
        mapping = panel.drop_duplicates(subset=["code"], keep="last").set_index("code")["industry"]
        industry = mapping

    weights = pd.DataFrame(np.nan, index=scores.index, columns=scores.columns, dtype="float64")
    previous: list[str] = []

    for date in scores.index:
        row = scores.loc[date]
        eligible = row[investable.loc[date].reindex(row.index).fillna(False)]
        ranked = eligible.dropna().sort_values(ascending=False)
        if len(ranked) < config.min_names:
            # No opinion: emit NaN so the engine holds rather than liquidates.
            # ``previous`` is deliberately preserved so the exit buffer survives
            # a data gap instead of churning the whole book on the far side.
            continue

        selected = _select(ranked, previous, config, industry)
        if not selected:
            previous = []
            continue

        volatility_row = volatility.loc[date] if volatility is not None and date in volatility.index else None
        row_weights = _weights_for(selected, ranked, volatility_row, config)
        target = pd.Series(0.0, index=scores.columns, dtype="float64")
        for code, value in row_weights.items():
            target[code] = value
        weights.loc[date] = target
        previous = selected

    return weights


def turnover_of_weights(weights: pd.DataFrame) -> pd.Series:
    """One-way turnover implied by consecutive target-weight rows.

    Half the sum of absolute weight changes is the same convention the backtest
    engine reports, so the two are directly comparable. An all-NaN row means
    "no opinion: hold", so it is carried forward rather than read as a
    liquidation.
    """
    filled = weights.ffill(axis=0).fillna(0.0)
    delta = filled.diff().abs().sum(axis=1)
    return (delta / 2.0).iloc[1:]
