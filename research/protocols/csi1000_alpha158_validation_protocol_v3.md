# CSI1000 Alpha158 Research Validation Protocol v3

## Status and inherited rules

This version retains all frozen conventions from
`csi1000_alpha158_validation_protocol_v2.md`: CSI1000 historical
constituents, daily frequency, Alpha158 raw formulas, the label
`Ref($close, -2) / Ref($close, -1) - 1`, and the chronological split of
2020-2022 training history, 2023-2024 development, retrospective-only
2025-2026-07-21 confirmation, and post-2026-07-23 strict forward holdout.

The 2023-2024 raw screen and v2 de-duplication are complete.  This version
defines the next authorised development-stage action before it is run:
industry and free-float-size neutralisation of the 81 de-duplicated core
candidates.  It does not authorise model fitting or any backtest.

## Input candidates

Use only rows whose `deduplication_disposition` is `core_candidate` in
`output/analysis_static/csi1000_alpha158_development_screen_2023-01-01_2024-12-31/factor_deduplication.csv`:

| Original raw-screen class | Core candidates entering this step |
|---|---:|
| retain | 39 |
| observe | 42 |
| total | 81 |

All mathematical-equivalent and near-duplicate backups remain in their audit
table but cannot enter this computation.  Neutralisation does not promote an
original `observe` candidate to `retain`.

## Point-in-time neutralisation

For every factor and every trading date in the 2023-2024 development set,
use the stock's same-date factor value and estimate the cross-sectional OLS
regression:

```text
factor = intercept
       + beta_size * log(free_share * close)
       + Shenwan level-1 industry dummy coefficients
       + residual
```

`free_share` and `close` come from the same-date Tushare `daily_basic`
record.  The Shenwan level-1 industry assignment uses the historical
`in_date` / `out_date` record effective on that date.  One industry dummy is
omitted with the intercept to avoid perfect collinearity.

For each factor-date, drop only stock-dates that lack the factor, label,
same-date size, or effective industry.  Calculate raw Rank IC and residual
Rank IC on exactly this same complete-case sample.  This ensures that the
change from raw to residual Rank IC reflects removing industry/size exposure,
not a change in the evaluated stock set.  A cross section with fewer than 50
complete stocks is invalid and is reported rather than filled.

Summarise the daily residual Rank IC independently for calendar years 2023
and 2024.  The same lower-strength, same-direction rule used in the raw
screen is applied to the residual values:

```text
same non-zero annual residual Rank-IC sign
and min(abs(mean residual Rank IC in 2023), abs(mean residual Rank IC in 2024))
```

## Decision rule

| Neutralisation result | Rule | Meaning |
|---|---|---|
| `retain_survives` | Original class is `retain`; residual signs agree; both annual absolute residual Rank IC values are at least 0.02 | Independent core candidate for the next model comparison |
| `observe_survives` | Residual signs agree; both annual absolute residual Rank IC values are at least 0.01; but it is not `retain_survives` | Borderline candidate; original observe candidates remain observe even when their residual IC is high |
| `eliminate_after_neutralization` | All other cases | No stable combined industry/size-neutral signal on the development set |

The report additionally labels the *combined* effect as follows:

- `independent_signal_survives` for `retain_survives`;
- `weaker_but_survives` for `observe_survives`;
- `not_stable_after_combined_neutralization` otherwise.

This regression removes industry and size jointly.  It cannot quantify how
much of a change in IC came from industry versus size individually; no such
separate attribution will be claimed.

## Required audit outputs

Write the result beside the existing development-screen artifacts, with names
that do not overwrite raw-screen files:

- `neutralization_daily_rank_ic.csv.gz`
- `neutralization_summary_2023.csv`
- `neutralization_summary_2024.csv`
- `neutral_factor_decisions.csv`
- `neutralization_methodology.json`
- `neutralization_report.txt`

The report must state the exact coverage and complete-case sample sizes.  It
must not use 2025-2026 labels, model importance, feature selection by model,
or returns from a trading strategy.

## Next authorised action

Run this neutralisation calculation once and review the decision table.
Only after review may `retain_survives` and, separately, `observe_survives`
be considered as pre-defined inputs to the frozen A/B/C model-comparison
design.
