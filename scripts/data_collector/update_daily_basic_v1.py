#!/usr/bin/env python3
"""Incremental daily_basic (market cap, PE/PB, dividend yield) updater.

Downloads Tushare ``daily_basic`` for trading days not yet present in the raw
per-day CSV directory, then rebuilds the single normalized CSV consumed by the
value/quality strategy (``build_daily_grid`` reads total_mv, total_share, dv_ttm).

The raw store is one ``YYYYMMDD.csv.gz`` per trading day (resumable).  The
normalized file is the concatenation of all raw files (same columns), rebuilt
in full each run (it's ~650MB gzipped but writes in <1 min).

Usage
-----
    conda activate qlib
    # incremental: download missing days + rebuild normalized
    python scripts/data_collector/update_daily_basic_v1.py
    # dry-run: show what would be downloaded
    python scripts/data_collector/update_daily_basic_v1.py --dry-run

Crontab example (run Mon-Fri after close, after market data update):
    45 17 * * 1-5  cd /home/xiaocong/worksapces/qlib && \
        /home/xiaocong/anaconda3/envs/qlib/bin/python \
        scripts/data_collector/update_daily_basic_v1.py \
        >> /home/xiaocong/worksapces/qlib/output/logs_static/daily_basic_update.log 2>&1
"""

from __future__ import annotations

import argparse
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd
import tushare as ts

TOKEN_PATH = Path("/root/.config/tushare/token")
QLIB_DIR = Path.home() / ".qlib/qlib_data/cn_data_2026"
DATA_ROOT = Path("data/external/tushare/a_share_daily_basic_pit_v1")
RAW_DIR = DATA_ROOT / "raw"
NORMALIZED_DIR = DATA_ROOT / "normalized"
NORMALIZED_FILE = NORMALIZED_DIR / "daily_basic.csv.gz"

MAX_RETRY = 3
SLEEP_SECONDS = 0.15


def load_token() -> str:
    token = os.environ.get("TUSHARE_TOKEN")
    if token:
        return token.strip()
    if TOKEN_PATH.is_file():
        token = TOKEN_PATH.read_text(encoding="utf-8").strip()
        if token:
            return token
    raise SystemExit("Tushare token missing: set TUSHARE_TOKEN or populate " + str(TOKEN_PATH))


def read_store_calendar() -> pd.DatetimeIndex:
    path = QLIB_DIR / "calendars" / "day.txt"
    return pd.DatetimeIndex(pd.to_datetime(pd.read_csv(path, header=None)[0]))


def existing_raw_dates() -> set[str]:
    """Return set of YYYYMMDD strings already downloaded."""
    if not RAW_DIR.is_dir():
        return set()
    # f.stem for "20260807.csv.gz" is "20260807.csv" -- strip the .csv suffix
    return {f.name.replace(".csv.gz", "") for f in RAW_DIR.glob("*.csv.gz")}


def fetch_with_retry(pro, trade_date: str) -> pd.DataFrame:
    for attempt in range(MAX_RETRY):
        try:
            return pro.daily_basic(trade_date=trade_date)
        except Exception as exc:
            if attempt == MAX_RETRY - 1:
                raise
            time.sleep(2 * (attempt + 1))
    raise RuntimeError("unreachable")


def download_missing_days(pro, calendar: pd.DatetimeIndex, existing: set[str],
                          dry_run: bool = False) -> list[str]:
    """Download daily_basic for trading days in the store calendar not yet in raw."""
    # Only download from 2016-01-04 onward (start of the strategy backtest window)
    # and up to the last calendar day.
    start = pd.Timestamp("2016-01-01")
    calendar = calendar[(calendar >= start)]
    missing = [d for d in calendar if d.strftime("%Y%m%d") not in existing]
    # Drop today if market hasn't closed yet (before 17:00 CST)
    now_utc = datetime.now(timezone.utc)
    # 17:00 CST = 09:00 UTC
    if now_utc.hour < 9:
        missing = [d for d in missing if d.date() < datetime.now().date()]

    if not missing:
        print(f"[skip] no missing days (raw has {len(existing)} files)")
        return []

    print(f"[plan] {len(missing)} missing days: {missing[0].date()} .. {missing[-1].date()}")
    if dry_run:
        return []

    RAW_DIR.mkdir(parents=True, exist_ok=True)
    downloaded = []
    failed = []
    for day in missing:
        date_str = day.strftime("%Y%m%d")
        target = RAW_DIR / f"{date_str}.csv.gz"
        try:
            frame = fetch_with_retry(pro, date_str)
            if frame is None or frame.empty:
                print(f"  [{date_str}] empty, skip")
                failed.append(date_str)
                continue
            frame.to_csv(target, index=False, compression="gzip")
            downloaded.append(date_str)
            print(f"  [{date_str}] rows={len(frame)} OK")
        except Exception as exc:
            print(f"  [{date_str}] FAILED: {exc}")
            failed.append(date_str)
        time.sleep(SLEEP_SECONDS)

    if failed:
        print(f"[warn] failed days: {len(failed)} -> {failed[:10]}")
    print(f"[fetch] done: {len(downloaded)} downloaded, {len(failed)} failed")
    return downloaded


def rebuild_normalized() -> int:
    """Concatenate all raw per-day files into the single normalized CSV."""
    files = sorted(RAW_DIR.glob("*.csv.gz"))
    if not files:
        print("[normalize] no raw files found")
        return 0

    print(f"[normalize] concatenating {len(files)} raw files ...", flush=True)
    frames = []
    for f in files:
        try:
            df = pd.read_csv(f, compression="gzip")
            frames.append(df)
        except Exception as exc:
            print(f"  [warn] failed to read {f.name}: {exc}")

    if not frames:
        print("[normalize] no readable frames")
        return 0

    combined = pd.concat(frames, ignore_index=True)
    NORMALIZED_DIR.mkdir(parents=True, exist_ok=True)
    # Atomic write: write to temp then rename
    tmp = NORMALIZED_FILE.with_name(f".{NORMALIZED_FILE.name}.{os.getpid()}.tmp")
    combined.to_csv(tmp, index=False, compression="gzip")
    os.replace(tmp, NORMALIZED_FILE)
    print(f"[normalize] wrote {len(combined):,} rows -> {NORMALIZED_FILE}")
    return len(combined)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--dry-run", action="store_true", help="Show plan without downloading")
    parser.add_argument("--normalize-only", action="store_true", help="Skip download, just rebuild normalized")
    parser.add_argument("--sleep-seconds", type=float, default=SLEEP_SECONDS)
    args = parser.parse_args()

    calendar = read_store_calendar()
    print(f"[store] calendar last day: {calendar[-1].date()} ({len(calendar)} days)")

    existing = existing_raw_dates()
    print(f"[raw] {len(existing)} files present")

    if not args.normalize_only:
        pro = ts.pro_api(load_token())
        download_missing_days(pro, calendar, existing, dry_run=args.dry_run)

    if args.dry_run:
        print("[dry-run] skipping normalize")
        return

    # Rebuild normalized from all raw files
    rebuild_normalized()

    # Post-conditions
    new_existing = existing_raw_dates()
    print(f"[verify] raw files: {len(existing)} -> {len(new_existing)}")
    if NORMALIZED_FILE.is_file():
        sample = pd.read_csv(NORMALIZED_FILE, compression="gzip", usecols=["trade_date"])
        print(f"[verify] normalized: {len(sample):,} rows, "
              f"trade_date {sample.trade_date.min()} -> {sample.trade_date.max()}")

    print(f"[{datetime.now(timezone.utc).isoformat()}] update finished")


if __name__ == "__main__":
    main()
