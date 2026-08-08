# CSI1000 Alpha158 Research Validation Protocol v1

## Status and purpose

This protocol freezes the time split and comparison rules for the next CSI1000
factor-model experiments.  Its purpose is to prevent the same future-return
labels from being used both to select factors and to claim out-of-sample model
performance.

The prior 2025-01-01 to 2026-07-23 Alpha158 analysis remains a useful
exploratory diagnosis.  It identified low-volatility, volume-contraction,
reversal, close-strength, and price-volume signals as candidates.  It must not
be used to select a factor set and then evaluate that same factor set as if the
period were unseen.

## Frozen data and label conventions

| Item | Frozen convention |
|---|---|
| Market | CSI1000, using each day's historical Qlib index constituents |
| Qlib data source | `~/.qlib/qlib_data/cn_data_2026` |
| Frequency | Daily |
| Factor family | Qlib Alpha158 raw formulas, with no future data in factor inputs |
| Prediction label | `Ref($close, -2) / Ref($close, -1) - 1` |
| Factor warm-up | Request at least 60 trading days before an analysis segment; exclude warm-up days from all statistics |
| Industry | Point-in-time Shenwan level-1 industry, using `in_date` and `out_date` |
| Size | `log(free_share * close)` from same-day Tushare `daily_basic` data |
| Missing values | Drop a stock-date if its factor, label, industry, or size value is unavailable; never backfill with a later classification or value |

The label needs two later closes.  Therefore, if Qlib data ends on a given
date, the final two calendar entries cannot contribute to IC statistics.

## Frozen chronological split

| Role | Score/evaluation dates | Permitted use | Forbidden use |
|---|---|---|---|
| Model training history | 2020-01-01 to 2022-12-31 | Fit fixed candidate models | Selecting from 2025-2026 results |
| Development set | 2023-01-01 to 2024-12-31 | Re-run factor screening, neutralization, redundancy checks, and choose model/strategy settings | Calling performance a final out-of-sample result |
| Retrospective confirmation | 2025-01-01 to 2026-07-21 | Compare frozen versions A/B/C once; report as retrospective because it was previously inspected | Further factor, model, or strategy tuning |
| Strict forward holdout | First newly collected trading date after 2026-07-23 onward | Final frozen-strategy evaluation or paper trading | Any prior tuning or selection |

`2025-01-01` to `2026-07-21` is long enough for a useful historical check
(about 374 valid label days), but it is not a clean blind test because this
project has already used it for exploratory factor selection.  It must be
labelled "retrospective confirmation" in every later report.

The strict forward holdout starts only after the strategy version is frozen and
the Qlib/Tushare data have been updated beyond 2026-07-23.  Its exact end date
will be determined by future data availability, not by backfilling a result.

## Development-stage factor procedure

Run the following procedure only on the 2023-2024 development set:

### Frozen screening thresholds

Split the development set into calendar years 2023 and 2024.  For each raw
Alpha158 factor, calculate daily cross-sectional Spearman Rank IC and take the
mean separately in each year.  Apply these rules before inspecting any model
results:

| Classification | Rule |
|---|---|
| Retain | Both annual mean Rank IC values have the same non-zero sign, and both `abs(Rank IC) >= 0.02` |
| Observe | Both annual mean Rank IC values have the same non-zero sign, and both `abs(Rank IC) >= 0.01`, but the retain rule is not met |
| Eliminate | All other cases |

The comparison uses the weaker year's absolute Rank IC, not a two-year average.
This prevents a strong 2023 result from hiding a weak or reversed 2024 result.

1. Calculate each Alpha158 raw factor's daily cross-sectional Spearman Rank IC
   against the frozen label.
2. Apply the frozen screening thresholds above, and retain all daily IC and
   coverage statistics for audit.
3. Remove mathematical equivalents and near-duplicate formulas.
4. On each date, neutralize every remaining factor with:

   ```text
   factor = intercept + beta * log(free_share * close) + level-1 industry dummies + residual
   ```

5. Recalculate Rank IC using residuals.  Keep the complete audit trail of raw
   IC, residual IC, coverage, and all excluded stock-dates.
6. Check residual-factor redundancy without deleting by theme alone.  A factor
   can only be marked as a redundant backup when both its residual correlation
   and its daily-IC synchrony meet the pre-declared threshold.

The current 10-factor set from the 2025-2026 exploratory analysis is not
frozen as the development result.  It is a hypothesis to be tested again on
2023-2024 under this procedure.

## Frozen comparison experiment design

After the development-stage factor procedure is complete, compare only these
pre-defined versions on identical model, data, and strategy settings:

| Version | Features | Purpose |
|---|---|---|
| A | Full Alpha158 | Existing baseline |
| B | Core factors selected only from 2023-2024 | Test whether validated selection adds value |
| C | Core factors plus development-set observation factors, if any | Test whether borderline factors are complementary |

The following must be identical among A, B, and C unless the experiment is
explicitly about that item: training dates, validation dates, LightGBM
hyperparameters, label, CSI1000 universe, benchmark, TopkDropout parameters,
cost assumptions, and backtest dates.

On the retrospective-confirmation period, select no new factors and tune no
parameters.  Report Rank IC, Rank ICIR, net excess return, information ratio,
maximum excess drawdown, turnover, and cost sensitivity.  A version is not
accepted merely because it wins one metric or one subperiod.

## Change control

Any change to this protocol requires a new versioned file and a written reason
before the affected experiment is run.  Existing output remains attached to
the protocol version that produced it.

## Next authorized action

The raw-factor screen has been completed at
`output/analysis_static/csi1000_alpha158_development_screen_2023-01-01_2024-12-31/`.
Review its retained and observed factors.  After review, remove only
mathematical equivalents and near-duplicate formulas from those candidates.
Do not neutralize, train, or backtest until the de-duplication result has been
reviewed.
