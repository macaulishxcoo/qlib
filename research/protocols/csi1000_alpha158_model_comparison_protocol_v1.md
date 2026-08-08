# CSI1000 Alpha158 Fixed Model Comparison Protocol v1

## Purpose and status

This protocol freezes the first model comparison after the 2023-2024
development-stage factor process.  It tests a narrow proposition:

```text
Does the final 13-factor core set produce a more useful CSI1000 prediction
and TopkDropout result than the full Alpha158 baseline under identical
training, validation, strategy, and cost settings?
```

It also records a pre-defined diagnostic Version C that adds the 39
development-stage observation factors.  This protocol creates configurations
only.  It does not authorise a training run; no result exists until the three
frozen configurations are explicitly run.

## Information boundaries

| Period | Role in this experiment | Permitted use |
|---|---|---|
| 2020-01-01 to 2022-12-31 | Training | Fit all three fixed LightGBM models |
| 2023-01-01 to 2024-12-31 | Development / validation | The sole period used to select factors and early-stop models |
| 2025-01-01 to 2026-07-21 | Retrospective confirmation | One fixed A/B/C comparison only |
| 2026-07-24 onward | Strict forward holdout | Final frozen-strategy observation or paper trading |

The 2025-2026 period has already been inspected during earlier exploratory
work.  It is therefore **retrospective confirmation**, not a statistically
clean out-of-sample test.  No factor, model, strategy, cost, or date change
may be chosen based on its A/B/C outcome.  Any change requires a new protocol
and a new future holdout period.

## Fixed common configuration

All versions use the following unchanged settings:

| Item | Frozen value |
|---|---|
| Market / benchmark | CSI1000 / `SH000852` |
| Qlib data | `~/.qlib/qlib_data/cn_data_2026` |
| Label | `Ref($close, -2) / Ref($close, -1) - 1` |
| Handler dates | 2020-01-01 to 2026-07-23; no feature transformation beyond Qlib's raw Alpha158 handling |
| Model | LightGBM MSE: learning rate 0.1, max depth 8, 250 leaves, 0.9 row/column subsample, lambda L1 205.6999, lambda L2 580.9768, 20 threads |
| Training / validation | 2020-2022 / 2023-2024 |
| Prediction segment | 2025-01-01 to 2026-07-23; its final two unlabelled dates are excluded from signal metrics |
| Strategy | `TopkDropoutStrategy(topk=50, n_drop=5)` |
| Execution | close price; limit threshold 9.5%; buy cost 0.05%; sell cost 0.15%; minimum commission 5 |
| Artifacts | `output/mlruns_static/`; three experiment names below; no default `mlruns/` directory |

The execution assumptions are intentionally unchanged from the prior CSI1000
baseline.  They are a comparison constant, not a claim that 9.5% price-limit
or low fixed costs perfectly model all CSI1000 constituents.  Cost sensitivity
is a separate later experiment, not a tunable input to this comparison.

## Fixed versions

| Version | Experiment name | Features | Role |
|---|---|---:|---|
| A | `static_csi1000_cmp_a_full_alpha158_v1` | all 158 raw Alpha158 features | Existing-factor baseline |
| B | `static_csi1000_cmp_b_core13_v1` | 13 final development-selected core features | Primary test of selection value |
| C | `static_csi1000_cmp_c_core13_observe39_v1` | B plus 39 neutralisation observation features (52 total) | Diagnostic: whether borderline features add information |

Version B's 13 features are fixed by
`final_core_factor_selection.csv` under validation protocol v4:

```text
STD5, KLEN, STD10, STD60, STD20, MIN60, HIGH0, CORD20, CORR10,
MAX5, KUP, CORR20, CORD10
```

Version C adds exactly the 39 `observe_survives` rows in
`neutral_factor_decisions.csv`; it does not include eliminated, mathematical-
equivalent, or redundancy-backup factors.

For B and C, `DataHandlerLP` explicitly loads only the named raw Alpha158
expressions.  It uses the same feature preprocessing as Qlib's `Alpha158`
handler: no additional feature transformation.  It uses the same learning
pipeline as `Alpha158` (`DropnaLabel`, cross-sectional label Z-score
normalisation).  This avoids hidden preprocessing differences between the
variants.

## Mandatory reporting and decision rules

Report for each version over the exact common label period 2025-01-01 through
2026-07-21: Rank IC, Rank ICIR, fee-after excess annual return, information
ratio, maximum excess drawdown, turnover, and total cost.  Also report the
same metrics for calendar year 2025 and 2026-01-01 through 2026-07-21 without
tuning from those splits.

The primary comparison is B against A.  B is a candidate improvement only if
it has non-negative changes in Rank IC, fee-after annualised excess return,
and information ratio, while not increasing maximum excess drawdown by more
than 5 percentage points.  Version C is diagnostic only: it cannot be adopted
unless it also passes the B-versus-A rule and outperforms B under the same
criteria.  A single metric or a single year cannot override this rule.

Regardless of this retrospective result, no version becomes a tradable
strategy until a frozen choice accumulates a strict forward holdout or paper-
trading record from data after 2026-07-23.

## Authorized next action

Review the three configuration files and this protocol.  After explicit
approval, run each configuration exactly once into `output/mlruns_static/` and
write a non-tuning comparison report.  Do not alter a configuration after
viewing the first run's result.
