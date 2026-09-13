#!/usr/bin/env python
"""Offline self-test for the Phase E portfolio-construction layer.

The load-bearing claims being tested are that the exit buffer actually reduces
turnover, and that the neutraliser actually removes industry and size exposure.
Both are easy to get subtly wrong in ways that only surface later as
unexplained cost drag.

Note on fixture size: the universe must be large relative to
``n_holdings * exit_multiple``. With only 60 candidates and an exit cut of 60,
*every* held name is always inside the exit window, so the buffer freezes the
book permanently and the test would pass for the wrong reason. 300 candidates
against a 60-name exit window reproduces the real top-2% geometry.

Run::

    python research/scripts/selftest_portfolio.py
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from cnquant.portfolio import (  # noqa: E402
    PortfolioConfig,
    build_target_weights,
    industry_demean,
    neutralize_scores,
    turnover_of_weights,
)

FAILURES: list[str] = []
INDUSTRY_OF = ["bank", "tech", "materials"]


def check(name: str, condition: bool, detail: str = "") -> None:
    status = "PASS" if condition else "FAIL"
    line = f"[{status}] {name}"
    if detail:
        line += f" -- {detail}"
    print(line)
    if not condition:
        FAILURES.append(f"{name}: {detail}")


def make_world(n_dates: int = 150, n_codes: int = 300, seed: int = 5):
    """Panel plus a persistent score, so ranks drift instead of reshuffling."""
    rng = np.random.default_rng(seed)
    dates = pd.bdate_range("2021-01-01", periods=n_dates)
    codes = [f"sh.60{i:04d}" for i in range(n_codes)]
    industries = {code: INDUSTRY_OF[i % len(INDUSTRY_OF)] for i, code in enumerate(codes)}

    panel = pd.DataFrame(
        [
            {"date": date, "code": code, "investable": True, "industry": industries[code]}
            for code in codes
            for date in dates
        ]
    )

    scores = np.zeros((n_dates, n_codes))
    scores[0] = rng.normal(0, 1, n_codes)
    for t in range(1, n_dates):
        scores[t] = 0.90 * scores[t - 1] + rng.normal(0, 0.60, n_codes)
    score_frame = pd.DataFrame(scores, index=dates, columns=codes)
    return panel, score_frame, industries, dates, codes


def main() -> int:
    print("=" * 78)
    print(" Phase E offline self-test (portfolio construction)")
    print("=" * 78)

    panel, scores, industries, dates, codes = make_world()

    # ------------------------------------------------------------------ #
    print("\n-- the exit buffer must reduce turnover --")
    unbuffered = build_target_weights(
        panel, scores, config=PortfolioConfig(n_holdings=30, exit_multiple=1.0)
    )
    buffered = build_target_weights(
        panel, scores, config=PortfolioConfig(n_holdings=30, exit_multiple=2.0)
    )
    wide_buffer = build_target_weights(
        panel, scores, config=PortfolioConfig(n_holdings=30, exit_multiple=3.0)
    )
    turn_unbuffered = float(turnover_of_weights(unbuffered).mean())
    turn_buffered = float(turnover_of_weights(buffered).mean())
    turn_wide = float(turnover_of_weights(wide_buffer).mean())
    check("buffering lowers mean daily turnover",
          turn_buffered < turn_unbuffered,
          f"buffered {turn_buffered:.4f} vs unbuffered {turn_unbuffered:.4f}")
    check("a wider buffer lowers it further",
          turn_wide < turn_buffered,
          f"exit=3 {turn_wide:.4f} vs exit=2 {turn_buffered:.4f}")
    check("a 2x buffer cuts turnover by at least 10%",
          turn_buffered < 0.90 * turn_unbuffered,
          f"{turn_buffered / turn_unbuffered:.2%} of unbuffered")
    check("the buffer does not freeze the book entirely",
          turn_buffered > 0.0, f"turnover {turn_buffered:.5f}")

    # ------------------------------------------------------------------ #
    print("\n-- weights are well formed --")
    row = buffered.loc[dates[5]]
    check("a rebalanced row holds exactly n_holdings names",
          int((row > 0).sum()) == 30, f"{int((row > 0).sum())} names")
    check("a rebalanced row has no NaN", not bool(row.isna().any()))
    check("weights sum to 1.0", abs(float(row.sum()) - 1.0) < 1e-9, f"sum={row.sum():.10f}")
    check("unselected names are explicitly zero, not NaN",
          int((row == 0).sum()) == len(codes) - 30, f"{int((row == 0).sum())} zeros")
    check("no weight exceeds max_weight", float(row.max()) <= 0.08 + 1e-12,
          f"max={row.max():.4f}")

    cash_row = build_target_weights(
        panel, scores, config=PortfolioConfig(n_holdings=30, cash_buffer=0.1)
    ).loc[dates[5]]
    check("cash_buffer leaves the intended cash share",
          abs(float(cash_row.sum()) - 0.9) < 1e-9, f"sum={cash_row.sum():.6f}")

    # ------------------------------------------------------------------ #
    print("\n-- insufficient candidates means hold, not liquidate --")
    thin = scores.copy()
    thin.iloc[:, 50:] = np.nan
    thin_weights = build_target_weights(
        panel, thin, config=PortfolioConfig(n_holdings=30, exit_multiple=2.0, min_names=40)
    )
    check("a date with too few candidates emits an all-NaN row",
          bool(thin_weights.iloc[5].isna().all()))
    thin_turnover = turnover_of_weights(thin_weights)
    worst = float(thin_turnover.max()) if len(thin_turnover) else 0.0
    check("turnover treats an all-NaN row as hold, not liquidation", worst <= 1e-9,
          f"max turnover {worst:.4f}")

    # ------------------------------------------------------------------ #
    print("\n-- industry cap --")
    capped = build_target_weights(
        panel, scores,
        config=PortfolioConfig(n_holdings=30, exit_multiple=2.0, max_per_industry=12),
    )
    cap_row = capped.loc[dates[5]]
    counts = pd.Series({code: industries[code] for code in cap_row[cap_row > 0].index}).value_counts()
    check("no industry exceeds max_per_industry names", int(counts.max()) <= 12,
          f"counts={counts.to_dict()}")
    check("the cap still fills the book", int((cap_row > 0).sum()) == 30,
          f"{int((cap_row > 0).sum())} names")

    # ------------------------------------------------------------------ #
    print("\n-- weighting schemes --")
    volatility = pd.DataFrame(
        np.tile(np.linspace(0.01, 0.05, len(codes)), (len(dates), 1)), index=dates, columns=codes
    )
    inverse_vol = build_target_weights(
        panel, scores,
        config=PortfolioConfig(n_holdings=30, exit_multiple=2.0, weighting="inverse_vol"),
        volatility=volatility,
    ).loc[dates[5]]
    held = inverse_vol[inverse_vol > 0]
    low_vol_code = min(held.index, key=lambda code: volatility.loc[dates[5], code])
    high_vol_code = max(held.index, key=lambda code: volatility.loc[dates[5], code])
    check("inverse-vol gives the calmest name the largest weight",
          held[low_vol_code] > held[high_vol_code],
          f"low {held[low_vol_code]:.4f} vs high {held[high_vol_code]:.4f}")
    check("inverse-vol weights still sum to 1", abs(float(inverse_vol.sum()) - 1.0) < 1e-9)

    score_weighted = build_target_weights(
        panel, scores,
        config=PortfolioConfig(n_holdings=30, exit_multiple=2.0, weighting="score"),
    ).loc[dates[5]]
    held_codes = score_weighted[score_weighted > 0].index
    best = scores.loc[dates[5], held_codes].idxmax()
    worst_name = scores.loc[dates[5], held_codes].idxmin()
    check("score weighting ranks the best name above the worst held name",
          score_weighted[best] > score_weighted[worst_name],
          f"{score_weighted[best]:.4f} vs {score_weighted[worst_name]:.4f}")
    check("score weighting still sums to 1", abs(float(score_weighted.sum()) - 1.0) < 1e-9)

    # ------------------------------------------------------------------ #
    print("\n-- industry and size neutralisation --")
    rng = np.random.default_rng(9)
    small_dates = pd.bdate_range("2022-01-03", periods=20)
    small_codes = [f"sz.00{i:04d}" for i in range(60)]
    small_industry = pd.Series(
        {code: INDUSTRY_OF[i % len(INDUSTRY_OF)] for i, code in enumerate(small_codes)}
    )
    small_panel = pd.DataFrame(
        [{"date": date, "code": code} for code in small_codes for date in small_dates]
    )
    industry_labels = small_panel["code"].map(small_industry)
    industry_effect = small_panel["code"].map(
        lambda code: {"bank": 3.0, "tech": -1.0, "materials": 0.5}[small_industry[code]]
    )
    size = pd.Series(rng.normal(10, 1, len(small_panel)), index=small_panel.index)
    raw = industry_effect + 0.8 * size + pd.Series(
        rng.normal(0, 0.1, len(small_panel)), index=small_panel.index
    )

    demeaned = industry_demean(small_panel, raw, industry_labels)
    by_industry = demeaned.groupby(industry_labels.to_numpy()).mean()
    check("industry_demean zeroes every industry mean",
          float(by_industry.abs().max()) < 1e-9,
          f"max |mean| = {float(by_industry.abs().max()):.2e}")

    neutral = neutralize_scores(small_panel, raw, industry=industry_labels, size=size)
    neutral_by_industry = neutral.groupby(industry_labels.to_numpy()).mean()
    first_date_mask = (small_panel["date"] == small_dates[0]).to_numpy()
    within_date_corr = float(
        np.corrcoef(neutral.to_numpy()[first_date_mask], size.to_numpy()[first_date_mask])[0, 1]
    )
    check("neutralised scores have no industry mean left",
          float(neutral_by_industry.abs().max()) < 1e-9,
          f"max |mean| = {float(neutral_by_industry.abs().max()):.2e}")
    check("neutralised scores are uncorrelated with size within a date",
          abs(within_date_corr) < 0.02, f"corr={within_date_corr:.5f}")
    check("neutralisation shrinks rather than destroys the signal",
          float(neutral.std()) > 0.05, f"std={float(neutral.std()):.4f}")

    # ------------------------------------------------------------------ #
    print("\n-- parameter sanity --")
    oversized = build_target_weights(
        panel, scores, config=PortfolioConfig(n_holdings=500, min_names=5)
    ).loc[dates[5]]
    check("n_holdings above the candidate count still returns a book",
          not bool(oversized.isna().all()) and int((oversized > 0).sum()) == len(codes),
          f"{int((oversized > 0).sum())} names")
    check("exit_multiple=1.0 keeps exactly n_holdings names",
          int((unbuffered.loc[dates[5]] > 0).sum()) == 30,
          f"{int((unbuffered.loc[dates[5]] > 0).sum())} names")

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
