# CSI1000 Alpha158 Research Validation Protocol v2

## Status and change reason

This version retains the frozen market, data, label, chronological split, and
raw-factor screening rules from
`csi1000_alpha158_validation_protocol_v1.md`.  It adds the operational
definition for the next authorised step: de-duplicating factors that passed
the 2023-2024 raw screen.

This change is made before running de-duplication because v1 required the
step but did not pre-declare numerical thresholds.  It does not alter any
already-completed raw-screen result, and it does not authorise
neutralisation, model fitting, or backtesting.

## Inherited frozen conventions

| Item | Convention |
|---|---|
| Market | CSI1000, using each day's historical Qlib index constituents |
| Qlib data source | `~/.qlib/qlib_data/cn_data_2026` |
| Frequency | Daily |
| Factor family | Qlib Alpha158 raw formulas, with no future data in factor inputs |
| Label | `Ref($close, -2) / Ref($close, -1) - 1` |
| Development set | 2023-01-01 to 2024-12-31 |
| Future use | 2025-01-01 to 2026-07-21 is retrospective confirmation only; dates after 2026-07-23 are the strict forward holdout |

The v1 raw-screen classifications remain the input to this step: 49
`retain` candidates, 53 `observe` candidates, and 56 eliminated factors.
Only retain and observe candidates are analysed here.  Their original class
is never upgraded or changed by de-duplication.

## De-duplication procedure

### 1. Algebraically equivalent families

For every common window, the following Alpha158 price-change family has one
underlying quantity expressed three ways:

```text
SUMN = 1 - SUMP
SUMD = 2 * SUMP - 1
```

The corresponding volume-change family has the same relationship:

```text
VSUMN = 1 - VSUMP
VSUMD = 2 * VSUMP - 1
```

The formulas use a `1e-12` denominator stabiliser, so the identities are
understood up to insignificant numerical differences when the denominator is
zero.  For each family and window, retain `SUMD` or `VSUMD` as the canonical
representation when it is present, and mark the other present members as
`mathematical_equivalent_backup`.  This is a bookkeeping choice, not an
effectiveness judgement.

### 2. Near-duplicate test

After the preceding canonicalisation, assess retain and observe candidates
separately.  For each pair in the same original class:

1. On each of the 484 development dates, calculate the Spearman correlation
   between the pair's cross-sectional raw factor values, after dropping
   missing values for that pair.
2. Take the median of the absolute daily correlations.
3. Calculate the ordinary Pearson correlation between the two 484-element
   daily Rank-IC sequences produced by the already completed raw screen, and
   take its absolute value.  This measures whether the two factors succeed
   and fail on the same dates, rather than merely sharing a similar static
   distribution.

A pair is a high-repeat pair only when both conditions hold:

```text
median(abs(daily cross-sectional Spearman correlation)) >= 0.95
abs(Pearson correlation of daily Rank-IC sequences) >= 0.90
```

Factors are processed from stronger to weaker by the raw screen's weaker-year
absolute Rank IC (with alphabetical order only as a deterministic tie-break).
A factor is marked `redundant_backup` only if it passes both thresholds
against an already-selected core candidate in its own original class.  The
stronger factor is recorded as its representative.  This greedy rule avoids
declaring two factors redundant merely through a chain where they do not
themselves meet the threshold.

### 3. Outputs and interpretation

Every original candidate remains in the audit files.  The possible outcomes
are `core_candidate`, `mathematical_equivalent_backup`, and
`redundant_backup`.  A core candidate is not a final factor: all core
candidates still require the next authorised step, point-in-time
industry/free-float-size neutralisation and residual Rank-IC verification.

The de-duplication step cannot use 2025-2026 labels, neutralised values,
model feature importance, or backtest returns.

## Next authorised action

Run the de-duplication computation once and review its audit tables.  Only
after review may the surviving core candidates enter development-set
industry/size neutralisation.
