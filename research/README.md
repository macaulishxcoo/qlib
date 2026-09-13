# CN Daily-Frequency Quant Research (沪深主板)

This directory is a **self-contained research track** added on top of the existing `qlib`
checkout. Nothing here modifies the qlib source tree.

Goal: find a **daily-frequency** (1-day / 5-day / 10-day horizon) A-share strategy on the
**Shanghai + Shenzhen main board** (universe excludes 科创板 `688***`, 创业板 `300***`,
北交所 `4*****` / `8*****`), with a starting capital of **¥500,000**, that delivers
**≥ 10% annualized excess return over the benchmark after all costs**.

## Status

| Item | State |
| --- | --- |
| Environment (Python venv, data libs) | **blocked** — DSH shell cannot spawn any child process |
| Data foundation (Phase A code) | written, **not yet executed** |
| Simulator / cost model (Phase B code) | written, **not yet executed** |
| Factor library + evaluation (Phase C code) | written, **not yet executed** |
| Offline self-tests (Phases A/B/C logic) | written, **not yet executed** |
| Signal model (Phase D) | not started |
| Portfolio construction (Phase E) | not started |
| Walk-forward validation (Phase F) | not started |

## Read these first

1. [`docs/RESEARCH_PLAN.md`](docs/RESEARCH_PLAN.md) — success criteria, why previous
   experiments likely failed, and the full research route.
2. [`docs/ENVIRONMENT.md`](docs/ENVIRONMENT.md) — how to fix the broken shell and set up
   the Python environment.

## Quick start (once the shell works)

```powershell
pwsh -NoProfile -File .\research\scripts\bootstrap_env.ps1
$py = ".\.research\.venv\Scripts\python.exe"
& $py .\research\scripts\selftest_core.py         # Phase A logic, no network
& $py .\research\scripts\selftest_backtest.py     # Phase B engine, no network
& $py .\research\scripts\selftest_factors.py      # Phase C factors, no network
& $py .\research\scripts\selftest_portfolio.py    # Phase E construction, no network
& $py .\research\scripts\selftest_signal.py       # Phase D signal, no network
& $py .\research\scripts\selftest_altdata.py      # point-in-time alt-data, no network
& $py .\research\scripts\selftest_integration.py  # end-to-end, no network
& $py .\research\scripts\run_pipeline.py --synthetic   # whole pipeline, no network
& $py .\research\scripts\verify_env.py            # interpreter, packages, live data
& $py .\research\scripts\build_dataset.py --limit 20
```

## Layout

```
research/
  README.md
  docs/
    RESEARCH_PLAN.md           # criteria, hypotheses, route, factor roadmap, validation
    ENVIRONMENT.md             # environment + shell troubleshooting
  cnquant/
    config.py                  # universe rules, cost model, acceptance thresholds
    data.py                    # baostock ingestion (resumable, two price modes)
    universe.py                # limit prices, tradability, liquidity, investable mask
    backtest.py                # Phase B engine: T+1, limits, ¥5 commission floor
    metrics.py                 # performance stats + acceptance gates
    ops.py                     # cross-sectional / time-series factor operators
    factors.py                 # Phase C factor library (C1 baseline + C2 differentiated)
    evaluate.py                # IC, decay, quantiles, factor screen, cost-aware net
    signal.py                  # Phase D composites: equal / IC-weighted / LightGBM
    portfolio.py               # Phase E buffered selection, neutralisation, weighting
    walkforward.py             # Phase F purged walk-forward splits + OOS driver
    altdata.py                 # point-in-time alignment + event/quarterly factor maths
  scripts/
    bootstrap_env.ps1          # create venv, install deps
    verify_env.py              # verify interpreter, packages, and live data sources
    build_dataset.py           # Phase A CLI: build the clean daily panel
    run_pipeline.py            # the whole pipeline in one command (--synthetic works offline)
    selftest_core.py           # offline self-test: universe/cost logic
    selftest_backtest.py       # offline self-test: engine frictions
    selftest_factors.py        # offline self-test: planted-relationship IC recovery
    selftest_portfolio.py      # offline self-test: buffer, caps, neutralisation
    selftest_signal.py         # offline self-test: IC-weight shift timing
    selftest_altdata.py        # offline self-test: point-in-time alignment invariant
    selftest_integration.py    # offline self-test: whole stack end to end
    diagnose_windows_shell.ps1 # pin down the 0xC0000142 child-process failure
```
