# CSI1000 Alpha158 Fixed Model Comparison Protocol v1.1

## Status

This is a technical correction to
`csi1000_alpha158_model_comparison_protocol_v1.md`, made after Version B and
Version C failed during handler construction and before either produced a
model, prediction, signal metric, or backtest.  Version A completed once
under v1.

The failure was:

```text
DataHandler.__init__() got an unexpected keyword argument 'fit_start_time'
```

`fit_start_time` and `fit_end_time` are accepted by Qlib's `Alpha158` helper
handler, but not by the explicitly configured `DataHandlerLP` used for the
restricted B/C feature lists.  In v1 the two fields had no effect on Version
A because that handler deliberately used no train-fitted feature processor.
They are therefore removed only from B/C's handler keyword arguments.  The
training, validation, prediction, model, feature lists, label, strategy,
costs, and all other comparison settings are unchanged.

The two failed B/C MLflow run directories contain task metadata only and no
model or result artifacts.  They are moved to `output/mlruns_static/.trash/`
before the corrected run, so each B/C experiment contains exactly one
completed result record.

## Effective fixed design

All requirements, feature definitions, information boundaries, reporting
rules, and decision rules from v1 remain in force.  The effective handler
date range is 2020-01-01 to 2026-07-23 for all versions, while the dataset
segments remain:

| Segment | Dates |
|---|---|
| Training | 2020-01-01 to 2022-12-31 |
| Development / validation | 2023-01-01 to 2024-12-31 |
| Retrospective confirmation | 2025-01-01 to 2026-07-21 |
| Strict forward holdout | 2026-07-24 onward |

The three experiment names remain unchanged:

```text
static_csi1000_cmp_a_full_alpha158_v1
static_csi1000_cmp_b_core13_v1
static_csi1000_cmp_c_core13_observe39_v1
```

The same no-extra-feature-preprocessing rule applies to A, B, and C.  This
correction is an interface compatibility fix, not a model or research-design
change.
