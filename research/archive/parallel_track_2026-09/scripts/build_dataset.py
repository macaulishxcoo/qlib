#!/usr/bin/env python
"""Phase A CLI: build the clean daily panel for the 沪深主板 universe.

Examples
--------
Smoke test (a handful of names, fast)::

    python research/scripts/build_dataset.py --limit 20 --start 2023-01-01 --end 2024-12-31

Full build (slow, resumable — re-run after an interruption)::

    python research/scripts/build_dataset.py --start 2015-01-01 --end 2025-12-31

Force a refresh of already-cached names::

    python research/scripts/build_dataset.py --refresh
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from cnquant import data as cq_data  # noqa: E402
from cnquant.config import PANEL_DIR, UniverseRules  # noqa: E402
from cnquant.universe import data_quality_report, prepare_panel  # noqa: E402


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--start", default="2015-01-01", help="first trading date (YYYY-MM-DD)")
    parser.add_argument("--end", default="2025-12-31", help="last trading date (YYYY-MM-DD)")
    parser.add_argument("--limit", type=int, default=0, help="only process the first N names (0 = all)")
    parser.add_argument("--refresh", action="store_true", help="ignore cached per-name files")
    parser.add_argument("--include-chinext", action="store_true", help="also include 创业板 (sz.300/301)")
    parser.add_argument("--sleep", type=float, default=0.0, help="seconds to sleep between requests")
    parser.add_argument("--no-progress", action="store_true", help="disable the progress bar")
    parser.add_argument("--out", default="", help="output parquet path (default: data/panel/daily_panel.parquet)")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    started = time.time()
    rules = UniverseRules(include_chinext=args.include_chinext)

    out_path = Path(args.out) if args.out else PANEL_DIR / "daily_panel.parquet"
    basic_path = PANEL_DIR / "universe_basic.parquet"

    print("=" * 78)
    print(" Phase A - build clean daily panel (沪深主板)")
    print("=" * 78)
    print(f"window        : {args.start} .. {args.end}")
    print(f"include 创业板: {args.include_chinext}")
    print(f"cache dir     : {cq_data.CACHE_DIR}")
    print(f"output        : {out_path}")
    print()

    print("[1/5] logging in and fetching reference data ...")
    with cq_data.baostock_session() as bs:
        basic = cq_data.fetch_stock_basic(bs)
        print(f"      securities known to baostock : {len(basic)}")
        if "status" in basic.columns:
            delisted = int((basic["status"] == 0).sum())
            print(f"      of which delisted            : {delisted}")

        industry = pd.DataFrame()
        try:
            industry = cq_data.fetch_industry(bs)
            print(f"      industry rows                : {len(industry)}")
        except Exception as exc:  # noqa: BLE001 - industry is a nice-to-have
            print(f"      industry fetch failed (continuing): {type(exc).__name__}: {exc}")

        universe = cq_data.select_universe_codes(basic, rules)
        print(f"\n[2/5] universe after board filter : {len(universe)} names")
        if "status" in universe.columns:
            print(f"      delisted inside universe     : {int((universe['status'] == 0).sum())}")

        codes = universe["code"].tolist()
        if args.limit:
            codes = codes[: args.limit]
            print(f"      --limit applied              : {len(codes)} names")

        print(f"\n[3/5] downloading daily history for {len(codes)} names (resumable) ...")
        report = cq_data.download_universe(
            codes,
            args.start,
            args.end,
            use_cache=not args.refresh,
            sleep_seconds=args.sleep,
            progress=not args.no_progress,
        )
    print()
    print(report.summary())

    print("\n[4/5] assembling panel ...")
    panel = cq_data.load_cached_panel(codes)
    if panel.empty:
        print("      ERROR: no cached data was produced; nothing to assemble.")
        return 1
    print(f"      raw rows                     : {len(panel):,}")
    print(f"      date range                   : {panel['date'].min().date()} .. {panel['date'].max().date()}")
    print(f"      distinct codes               : {panel['code'].nunique()}")

    panel = prepare_panel(panel, basic, rules, industry)
    investable = int(panel["investable"].sum())
    print(f"      investable rows              : {investable:,} ({investable / len(panel):.1%})")

    print("\n[5/5] writing outputs ...")
    PANEL_DIR.mkdir(parents=True, exist_ok=True)
    panel.to_parquet(out_path, index=False)
    universe.to_parquet(basic_path, index=False)
    print(f"      panel   -> {out_path}")
    print(f"      universe-> {basic_path}")

    quality = data_quality_report(panel)
    quality_path = PANEL_DIR / "data_quality.csv"
    quality.to_csv(quality_path, index=False, encoding="utf-8-sig")
    print(f"      quality -> {quality_path}")

    print("\ncolumn coverage (lowest 12):")
    print(quality.head(12).to_string(index=False))

    print("\nper-year investable breadth:")
    breadth = (
        panel[panel["investable"]]
        .groupby(panel["date"].dt.year)["code"]
        .nunique()
        .rename("investable_names")
    )
    print(breadth.to_string())

    print(f"\ndone in {time.time() - started:,.1f}s")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
