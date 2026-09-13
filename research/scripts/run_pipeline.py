#!/usr/bin/env python
"""End-to-end research pipeline: panel -> factors -> screen -> signal -> portfolio -> report.

Typical first run (no network, validates every stage on synthetic data)::

    python research/scripts/run_pipeline.py --synthetic

Then a real smoke run on a small slice of real data::

    python research/scripts/run_pipeline.py --limit-codes 60 --start 2021-01-01

Full run::

    python research/scripts/run_pipeline.py --start 2015-01-01 --end 2025-12-31 --method ic_weighted

Artifacts land in ``research/reports/<run-name>/``: the factor screen, the
performance summary, the acceptance-gate table, the per-year breakdown, the NAV
curve, and the run's exact configuration.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from cnquant import data as cq_data  # noqa: E402
from cnquant.backtest import run_backtest  # noqa: E402
from cnquant.config import (  # noqa: E402
    BENCHMARK_CODE,
    COST_STRESS_FACTORS,
    DEFAULT_COST,
    PANEL_DIR,
    REPORT_DIR,
    BacktestConfig,
    UniverseRules,
)
from cnquant.evaluate import forward_returns, ic_summary, rank_ic_by_date, screen_factors  # noqa: E402
from cnquant.factors import REGISTRY, build_factors, factor_catalog  # noqa: E402
from cnquant.metrics import ACCEPTANCE_GATES, annual_returns, gate_report  # noqa: E402
from cnquant.portfolio import PortfolioConfig, build_target_weights, turnover_of_weights  # noqa: E402
from cnquant.signal import (  # noqa: E402
    SignalConfig,
    composite_score,
    equal_weights,
    ic_by_date,
    neutralize_score,
    rolling_ic_weights,
)
from cnquant.universe import preflight_panel, prepare_panel  # noqa: E402


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    source = parser.add_argument_group("data source")
    source.add_argument("--panel", default="", help="use an existing panel parquet instead of building")
    source.add_argument("--synthetic", action="store_true", help="generate an offline synthetic panel")
    source.add_argument("--start", default="2015-01-01")
    source.add_argument("--end", default="2025-12-31")
    source.add_argument("--limit-codes", type=int, default=0, help="use only the first N universe codes")
    source.add_argument("--include-chinext", action="store_true")

    stages = parser.add_argument_group("stages")
    stages.add_argument("--skip-screen", action="store_true", help="reuse the saved factor screen")
    stages.add_argument("--factors", default="", help="comma-separated factor subset (default: all)")

    model = parser.add_argument_group("signal")
    model.add_argument("--method", default="ic_weighted", choices=["equal", "ic_weighted"],
                       help="composite method for the linear path")
    model.add_argument("--horizon", type=int, default=5, help="label horizon in trading days")
    model.add_argument("--ic-lookback", type=int, default=504)
    model.add_argument("--max-factors", type=int, default=20)
    model.add_argument("--no-neutralize", action="store_true")

    book = parser.add_argument_group("portfolio")
    book.add_argument("--n-holdings", type=int, default=30)
    book.add_argument("--exit-multiple", type=float, default=2.0)
    book.add_argument("--weighting", default="equal", choices=["equal", "score", "inverse_vol"])
    book.add_argument("--rebalance-every", type=int, default=5)
    book.add_argument("--capital", type=float, default=500_000.0)

    parser.add_argument("--name", default="", help="run name (default: a timestamp)")
    parser.add_argument("--seed", type=int, default=42)
    return parser.parse_args(argv)


# --------------------------------------------------------------------------- #
# synthetic source
# --------------------------------------------------------------------------- #


def synthetic_panel(n_dates: int = 700, n_codes: int = 150, seed: int = 42) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Offline panel with a planted 5-day signal, so every stage has something to find."""
    rng = np.random.default_rng(seed)
    dates = pd.bdate_range("2019-01-01", periods=n_dates)
    codes = [f"sh.60{i:04d}" for i in range(n_codes)]

    latent = rng.normal(0.0, 0.02, size=(n_dates, n_codes))
    returns = rng.normal(0.0002, 0.02, size=(n_dates, n_codes))
    returns[5:] = returns[5:] + 1.2 * latent[:-5]
    close = 10.0 * np.cumprod(1.0 + returns, axis=0)
    open_ = np.vstack([close[0:1], close[:-1]])

    rows = []
    for j, code in enumerate(codes):
        for i, date in enumerate(dates):
            rows.append(
                {
                    "date": date, "code": code,
                    "open": open_[i, j], "close": close[i, j],
                    "high": max(open_[i, j], close[i, j]) * 1.01,
                    "low": min(open_[i, j], close[i, j]) * 0.99,
                    "preclose": open_[i, j],
                    "volume": 1.0e6, "amount": 3.0e7, "turn": 1.0,
                    "pctChg": returns[i, j] * 100.0,
                    "tradestatus": 1, "isST": 0,
                    "adj_open": open_[i, j], "adj_close": close[i, j],
                    "pbMRQ": 1.5, "peTTM": 20.0, "psTTM": 2.0,
                }
            )
    basic = pd.DataFrame(
        [{"code": code, "code_name": code, "ipo_date": pd.Timestamp("2000-01-01"),
          "out_date": pd.NaT, "sec_type": "1", "status": 1.0} for code in codes]
    )
    return pd.DataFrame(rows), basic


def _to_wide(panel: pd.DataFrame, values: pd.Series, name: str = "value") -> pd.DataFrame:
    """Reshape a row-aligned Series into a ``date x code`` frame.

    Uses ``drop_duplicates`` + ``pivot`` rather than ``pivot_table``: on a
    7.5M-row panel the generic aggregating path is roughly an order of magnitude
    slower for what is already a unique key.
    """
    frame = pd.DataFrame(
        {
            "date": np.asarray(panel["date"]),
            "code": np.asarray(panel["code"]),
            name: np.asarray(values, dtype="float64"),
        }
    ).drop_duplicates(subset=["date", "code"], keep="last")
    return frame.pivot(index="date", columns="code", values=name).sort_index()


# --------------------------------------------------------------------------- #
# stages
# --------------------------------------------------------------------------- #


def load_panel(args: argparse.Namespace, log) -> tuple[pd.DataFrame, pd.DataFrame, pd.Series | None]:
    """Return ``(panel, basic, benchmark_returns)``."""
    rules = UniverseRules(include_chinext=args.include_chinext)

    if args.synthetic:
        log("building an offline synthetic panel (no network)")
        raw, basic = synthetic_panel(seed=args.seed)
        panel = prepare_panel(raw, basic, rules)
        return panel, basic, None

    if args.panel:
        log(f"loading panel from {args.panel}")
        panel = pd.read_parquet(args.panel)
        basic_path = PANEL_DIR / "universe_basic.parquet"
        basic = pd.read_parquet(basic_path) if basic_path.exists() else panel[["code"]].drop_duplicates()
        return panel, basic, None

    log("fetching reference data from baostock")
    with cq_data.baostock_session() as bs:
        basic = cq_data.fetch_stock_basic(bs)
        universe = cq_data.select_universe_codes(basic, rules)
        codes = universe["code"].tolist()
        if args.limit_codes:
            codes = codes[: args.limit_codes]
        log(f"universe: {len(codes)} names")

        log("downloading daily history (resumable)")
        report = cq_data.download_universe(codes, args.start, args.end)
        log(report.summary())

        benchmark_returns = None
        try:
            frames = cq_data.fetch_daily(bs, BENCHMARK_CODE, args.start, args.end)
            bench = frames["back"] if not frames["back"].empty else frames["none"]
            if not bench.empty and "close" in bench.columns:
                series = bench.set_index("date")["close"].astype("float64")
                benchmark_returns = series.pct_change().rename("benchmark")
                log(f"benchmark {BENCHMARK_CODE}: {len(series)} observations")
        except Exception as exc:  # noqa: BLE001 - the benchmark is optional
            log(f"benchmark unavailable ({type(exc).__name__}: {exc}); reporting absolute returns only")

    panel = cq_data.load_cached_panel(codes)
    if panel.empty:
        raise SystemExit("no cached data was produced; run build_dataset.py first")
    panel = prepare_panel(panel, basic, rules)
    return panel, basic, benchmark_returns


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    started = time.time()
    run_name = args.name or time.strftime("run-%Y%m%d-%H%M%S")
    out_dir = REPORT_DIR / run_name
    out_dir.mkdir(parents=True, exist_ok=True)

    def log(message: str) -> None:
        print(f"[{time.time() - started:7.1f}s] {message}", flush=True)

    log(f"run '{run_name}' -> {out_dir}")
    (out_dir / "config.json").write_text(json.dumps(vars(args), indent=2), encoding="utf-8")

    # ---------------------------------------------------------------- #
    panel, basic, benchmark_returns = load_panel(args, log)
    if benchmark_returns is None:
        # Without a benchmark there is no excess return, and every acceptance
        # gate would silently report NaN. Fall back to the equal-weighted
        # universe, which is also the honest comparison for a long-only book.
        if "pctChg" in panel.columns:
            benchmark_returns = (panel.groupby("date")["pctChg"].mean() / 100.0).rename("benchmark")
            log("no index benchmark available; using the equal-weighted universe as the benchmark")
        else:
            log("WARNING: no benchmark available and no pctChg column; excess gates will be NaN")
    log(f"panel: {len(panel):,} rows, {panel['code'].nunique()} codes, "
        f"{panel['date'].min().date()} .. {panel['date'].max().date()}")
    investable_share = float(panel["investable"].mean())
    log(f"investable share: {investable_share:.1%}")

    errors, warnings = preflight_panel(panel)
    for message in warnings:
        log(f"WARNING: {message}")
    if errors:
        for message in errors:
            log(f"ERROR: {message}")
        raise SystemExit(
            "panel preflight failed; fix the data before running the expensive stages"
        )
    log("panel preflight passed")

    selected = [name for name in (args.factors.split(",") if args.factors else []) if name]
    if not selected:
        selected = list(REGISTRY)

    # ---------------------------------------------------------------- #
    log(f"computing {len(selected)} factors")
    factor_frame = build_factors(panel, selected)
    factor_frame.to_parquet(out_dir / "factors.parquet", index=False)
    factor_catalog().to_csv(out_dir / "factor_catalog.csv", index=False, encoding="utf-8-sig")
    log("factors written")

    # ---------------------------------------------------------------- #
    screen_path = out_dir / "factor_screen.csv"
    if args.skip_screen and screen_path.exists():
        screen = pd.read_csv(screen_path, index_col=0)
        log("reusing the saved factor screen")
    else:
        log("screening factors (this is the slow stage)")
        horizons = tuple(sorted({1, args.horizon, 10}))
        screen = screen_factors(panel, factor_frame, selected, horizons=horizons)
        screen.to_csv(screen_path, encoding="utf-8-sig")
        log("screen written")
    print(screen.head(15).to_string())

    # ---------------------------------------------------------------- #
    signal_config = SignalConfig(
        method=args.method,
        horizon=args.horizon,
        ic_lookback_days=args.ic_lookback,
        max_factors=args.max_factors,
    )
    if args.method == "equal":
        log("building an equal-weight (prior-direction) composite")
        weights = equal_weights(selected)
    else:
        log("building rolling IC weights")
        ic = ic_by_date(panel, factor_frame, selected, horizon=args.horizon)
        weights = rolling_ic_weights(
            ic, horizon=args.horizon, lookback_days=args.ic_lookback,
            min_periods=max(signal_config.ic_min_periods, 60),
            min_abs_ic=signal_config.min_abs_ic, max_factors=args.max_factors,
        )
        weights.to_parquet(out_dir / "ic_weights.parquet")

    score = composite_score(panel, factor_frame, selected, weights)
    check_ic = ic_summary(rank_ic_by_date(
        panel["date"], score, forward_returns(panel, horizons=(args.horizon,))[f"fwd_{args.horizon}"]
    ))
    log(f"composite score rank IC ({args.horizon}d): {check_ic['ic_mean']:.4f} "
        f"(t={check_ic['ic_t_stat']:.1f})")
    if check_ic["ic_mean"] <= 0:
        log("WARNING: the composite has a non-positive IC; the book below will not be informative")

    if not args.no_neutralize:
        log("neutralising the score against industry and size")
        size = np.log(panel["avg_amount"].where(panel["avg_amount"] > 0)) if "avg_amount" in panel.columns else None
        score = neutralize_score(
            panel, score,
            industry=panel["industry"] if "industry" in panel.columns else None,
            size=size,
        )

    scores_wide = _to_wide(panel, score)

    # ---------------------------------------------------------------- #
    log("building target weights")
    volatility = None
    if args.weighting == "inverse_vol" and "volatility_20" in factor_frame.columns:
        volatility = _to_wide(panel, factor_frame["volatility_20"], name="vol")
    weights_wide = build_target_weights(
        panel, scores_wide,
        config=PortfolioConfig(
            n_holdings=args.n_holdings,
            exit_multiple=args.exit_multiple,
            weighting=args.weighting,
        ),
        volatility=volatility,
    )
    implied = turnover_of_weights(weights_wide)
    if len(implied):
        log(f"daily target turnover {implied.mean():.4f} one-way; "
            f"the engine trades every {args.rebalance_every} day(s)")

    # ---------------------------------------------------------------- #
    log("running the backtest under cost stress")
    summary_rows = []
    results = {}
    for factor in COST_STRESS_FACTORS:
        cost = DEFAULT_COST if factor == 1.0 else DEFAULT_COST.scaled(factor)
        result = run_backtest(
            panel, weights_wide,
            config=BacktestConfig(initial_capital=args.capital),
            cost=cost,
            benchmark_returns=benchmark_returns,
            rebalance_every=args.rebalance_every,
        )
        results[factor] = result
        row = {"cost_multiplier": factor, **result.stats}
        summary_rows.append(row)
        log(f"  {factor:g}x cost -> annual {result.stats['annual_return']:.2%}, "
            f"excess {result.stats.get('excess_annual_return', float('nan')):.2%}, "
            f"IR {result.stats.get('information_ratio', float('nan')):.2f}")

    summary = pd.DataFrame(summary_rows).set_index("cost_multiplier")
    summary.to_csv(out_dir / "performance.csv", encoding="utf-8-sig")

    baseline = results[1.0]
    gates = gate_report(baseline.stats, ACCEPTANCE_GATES)
    gates.to_csv(out_dir / "acceptance_gates.csv", index=False, encoding="utf-8-sig")
    print()
    print("acceptance gates at 1x cost:")
    print(gates.to_string(index=False))

    print()
    print("2x cost stress (the acceptance bar):")
    print(summary.loc[2.0].to_string() if 2.0 in summary.index else summary.to_string())

    per_year = pd.DataFrame({
        "strategy": annual_returns(baseline.daily_returns),
        "benchmark": annual_returns(baseline.benchmark_returns) if baseline.benchmark_returns is not None else np.nan,
    })
    per_year.to_csv(out_dir / "per_year.csv", encoding="utf-8-sig")
    print()
    print("per-year returns:")
    print(per_year.to_string())

    print()
    print("cost decomposition (1x):")
    print(baseline.cost_summary().to_string())

    baseline.nav.to_frame("nav").to_csv(out_dir / "nav.csv", encoding="utf-8-sig")
    if baseline.excess_returns is not None:
        baseline.excess_returns.to_frame("excess").to_csv(out_dir / "excess.csv", encoding="utf-8-sig")
    weights_wide.to_parquet(out_dir / "target_weights.parquet")
    if not baseline.blocked.empty:
        baseline.blocked.groupby(["reason", "side"]).size().rename("count").to_csv(
            out_dir / "blocked_orders.csv", encoding="utf-8-sig"
        )
        log(f"blocked orders: {len(baseline.blocked):,} (limit-up/down or suspension)")

    log(f"done in {time.time() - started:,.1f}s; artifacts in {out_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
