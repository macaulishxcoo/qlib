# CSI1000 Alpha158 Research Validation Protocol v4

## Status and inherited rules

This version retains the frozen conventions in
`csi1000_alpha158_validation_protocol_v3.md`: CSI1000 historical
constituents, daily Alpha158 factors, the label
`Ref($close, -2) / Ref($close, -1) - 1`, 2023-2024 as the only development
set, and 2025-2026-07-21 as retrospective confirmation only.

The completed development process has produced 18 factors with stable
industry/free-float-size-neutral Rank IC (`retain_survives`).  This version
defines their final residual-redundancy audit before any model comparison.
It does not authorise training, model-based feature selection, a backtest, or
use of 2025-2026 labels.

## Input

Use only the 18 rows marked `retain_survives` in
`output/analysis_static/csi1000_alpha158_development_screen_2023-01-01_2024-12-31/neutral_factor_decisions.csv`.
The 39 `observe_survives` factors remain available only for the separately
pre-defined future Version C comparison; they cannot participate in selecting
the final core set here.

## Final residual-redundancy test

For each development trading date, use the common complete-case stock sample:
stock-dates must have all 18 factor values, the frozen future-return label,
same-day log free-float market value, and their point-in-time Shenwan level-1
industry.  Regress all 18 factor columns simultaneously on the same design
matrix:

```text
intercept + log(free_share * close) + level-1 industry dummies
```

For every pair of factor residual columns, calculate that date's
cross-sectional Spearman correlation, then take the median absolute value
across all development dates.  Separately, obtain the two factors' already
computed daily neutral Rank-IC series and calculate their Pearson correlation
over the same valid label dates.

A pair is a statistically redundant edge only if both quantities meet the
pre-declared thresholds:

```text
median(abs(daily residual cross-sectional Spearman correlation)) >= 0.80
abs(Pearson correlation of daily neutral Rank-IC series) >= 0.70
```

Build connected components only from those direct edges.  In a component with
more than one factor, keep the representative with the largest
`min_abs_neutral_rank_ic`; break ties with the largest absolute 2024 neutral
Rank IC, then alphabetical name.  All other factors in the component are
marked `redundant_backup`.  A component has no transitive implication beyond
its direct edges: every qualifying pair remains explicitly listed.

## Outcomes

- `final_core_candidate`: survives neutralisation and has no stronger
  representative in a threshold-qualified residual-redundancy component.
- `redundant_backup`: survives neutralisation but is a weaker representative
  of the same residual information component.

This designation creates the frozen feature set for later A/B/C experiments;
it does not claim that a smaller set will outperform all Alpha158 features.
That claim requires the later fixed-comparison experiment.

## Required outputs

Write, alongside the prior development artifacts:

- `final_residual_factor_pair_correlation.csv`
- `final_residual_daily_ic_correlation.csv`
- `final_core_factor_selection.csv`
- `final_core_selection_methodology.json`
- `final_core_selection_report.txt`

Every original input factor and every pair must remain in the audit files.

## Next authorised action

Run this residual-redundancy audit once and review the frozen final core set.
Only after review may a separate protocol define the identical A/B/C training
and retrospective-confirmation experiments.
