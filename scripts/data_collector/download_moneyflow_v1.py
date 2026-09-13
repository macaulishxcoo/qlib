#!/usr/bin/env python3
"""Download daily moneyflow (individual stock capital flow) from Tushare.

Downloads ``moneyflow`` for all trading days not yet present, storing one
``YYYYMMDD.csv.gz`` per day (resumable).  Then rebuilds the single normalized
concatenated CSV.

Usage
-----
    conda activate qlib
    python scripts/data_collector/download_moneyflow_v1.py
    python scripts/data_collector/download_moneyflow_v1.py --dry-run
"""

from __future__ import annotations

import argparse
import os
import time
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
import tushare as ts

TOKEN_PATH = Path.home() / ".config/tushare/token"
QLIB_DIR = Path.home() / ".qlib/qlib_data/cn_data_2026"
DATA_ROOT = Path("data/external/tushare/moneyflow_pit_v1")
RAW_DIR = DATA_ROOT / "raw"
NORMALIZED_DIR = DATA_ROOT / "normalized"
NORMALIZED_FILE = NORMALIZED_DIR / "moneyflow.csv.gz"

MAX_RETRY = 3
SLEEP_SECONDS = 0.2
START_DATE = "20220101"


def load_token() -> str:
    token = os.environ.get("TUSHARE_TOKEN")
    if token:
        return token.strip()
    if TOKEN_PATH.is_file():
        return TOKEN_PATH.read_text(encoding="utf-8").strip()
    raise SystemExit("Tushare token missing")


def read_calendar() -> pd.DatetimeIndex:
    return pd.DatetimeIndex(pd.to_datetime(pd.read_csv(QLIB_DIR / "calendars" / "day.txt", header=None)[0]))


def existing_raw_dates() -> set[str]:
    if not RAW_DIR.is_dir():
        return set()
    return {f.name.replace(".csv.gz", "") for f in RAW_DIR.glob("*.csv.gz")}


def fetch_with_retry(pro, trade_date: str) -> pd.DataFrame:
    for attempt in range(MAX_RETRY):
        try:
            return pro.moneyflow(trade_date=trade_date)
        except Exception as exc:
            if attempt == MAX_RETRY - 1:
                raise
            time.sleep(2 * (attempt + 1))
    raise RuntimeError("unreachable")


def download_missing(pro, calendar: pd.DatetimeIndex, existing: set[str], dry_run: bool) -> list[str]:
    start = pd.Timestamp(START_DATE)
    calendar = calendar[calendar >= start]
    # Don't download today if market hasn't closed (before 17:00 CST = 09:00 UTC)
    now = datetime.now(timezone.utc)
    if now.hour < 9:
        calendar = calendar[calendar.date < datetime.now().date()]

    missing = [d for d in calendar if d.strftime("%Y%m%d") not in existing]
    if not missing:
        print(f"[skip] no missing days (raw has {len(existing)} files)")
        return []

    print(f"[plan] {len(missing)} missing days: {missing[0].date()} .. {missing[-1].date()}")
    if dry_run:
        return []

    RAW_DIR.mkdir(parents=True, exist_ok=True)
    downloaded, failed = [], []
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
            if len(downloaded) % 50 == 0:
                print(f"  ... {len(downloaded)} downloaded", flush=True)
        except Exception as exc:
            print(f"  [{date_str}] FAILED: {exc}")
            failed.append(date_str)
        time.sleep(SLEEP_SECONDS)

    if failed:
        print(f"[warn] failed: {len(failed)} -> {failed[:10]}")
    print(f"[fetch] done: {len(downloaded)} downloaded, {len(failed)} failed")
    return downloaded


def rebuild_normalized() -> int:
    files = sorted(RAW_DIR.glob("*.csv.gz"))
    if not files:
        print("[normalize] no raw files")
        return 0
    print(f"[normalize] concatenating {len(files)} files ...", flush=True)
    frames = []
    for f in files:
        try:
            frames.append(pd.read_csv(f, compression="gzip"))
        except Exception as exc:
            print(f"  [warn] read failed {f.name}: {exc}")
    if not frames:
        return 0
    combined = pd.concat(frames, ignore_index=True)
    NORMALIZED_DIR.mkdir(parents=True, exist_ok=True)
    tmp = NORMALIZED_FILE.with_name(f".{NORMALIZED_FILE.name}.{os.getpid()}.tmp")
    combined.to_csv(tmp, index=False, compression="gzip")
    os.replace(tmp, NORMALIZED_FILE)
    print(f"[normalize] wrote {len(combined):,} rows -> {NORMALIZED_FILE}")
    return len(combined)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--normalize-only", action="store_true")
    parser.add_argument("--sleep-seconds", type=float, default=SLEEP_SECONDS)
    args = parser.parse_args()

    calendar = read_calendar()
    print(f"[store] calendar: {calendar[0].date()} .. {calendar[-1].date()} ({len(calendar)} days)")
    existing = existing_raw_dates()
    print(f"[raw] {len(existing)} files present")

    if not args.normalize_only:
        pro = ts.pro_api(load_token())
        download_missing(pro, calendar, existing, args.dry_run)

    if args.dry_run:
        return

    rebuild_normalized()

    new_existing = existing_raw_dates()
    print(f"[verify] raw files: {len(existing)} -> {len(new_existing)}")
    if NORMALIZED_FILE.is_file():
        sample = pd.read_csv(NORMALIZED_FILE, compression="gzip", usecols=["trade_date"])
        print(f"[verify] normalized: {len(sample):,} rows, {sample.trade_date.min()} -> {sample.trade_date.max()}")
    print(f"[{datetime.now(timezone.utc).isoformat()}] done")


if __name__ == "__main__":
    main()
