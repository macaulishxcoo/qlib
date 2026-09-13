#!/usr/bin/env python3
"""Download stk_holdernumber (shareholder count) quarterly data from Tushare.

Downloads per-quarter (by end_date) for all stocks, then computes the signal:
holder_num change ratio vs previous quarter.  Stores raw per-quarter files
and a normalized concatenated CSV.

Usage
-----
    conda activate qlib
    python scripts/data_collector/download_holdernumber_v1.py
"""

from __future__ import annotations

import argparse
import os
import time
from pathlib import Path

import pandas as pd
import tushare as ts

TOKEN_PATH = Path.home() / ".config/tushare/token"
DATA_ROOT = Path("data/external/tushare/holdernumber_pit_v1")
RAW_DIR = DATA_ROOT / "raw"
NORMALIZED_DIR = DATA_ROOT / "normalized"
NORMALIZED_FILE = NORMALIZED_DIR / "holdernumber.csv.gz"

MAX_RETRY = 3
SLEEP = 0.3

# Quarterly end_dates from 2021Q1 to 2025Q4
QUARTERS = [
    "20210331", "20210630", "20210930", "20211231",
    "20220331", "20220630", "20220930", "20221231",
    "20230331", "20230630", "20230930", "20231231",
    "20240331", "20240630", "20240930", "20241231",
    "20250331", "20250630", "20250930", "20251231",
]


def load_token() -> str:
    if TOKEN_PATH.is_file():
        return TOKEN_PATH.read_text(encoding="utf-8").strip()
    raise SystemExit("Tushare token missing")


def fetch_with_retry(pro, **kwargs) -> pd.DataFrame:
    for attempt in range(MAX_RETRY):
        try:
            return pro.stk_holdernumber(**kwargs)
        except Exception as exc:
            if attempt == MAX_RETRY - 1:
                raise
            time.sleep(2 * (attempt + 1))
    raise RuntimeError("unreachable")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    pro = ts.pro_api(load_token())
    RAW_DIR.mkdir(parents=True, exist_ok=True)

    all_frames = []
    for q in QUARTERS:
        target = RAW_DIR / f"{q}.csv.gz"
        if target.is_file():
            df = pd.read_csv(target, compression="gzip")
        else:
            if args.dry_run:
                print(f"[dry-run] would download end_date={q}")
                continue
            try:
                df = fetch_with_retry(pro, end_date=q)
                if df is not None and not df.empty:
                    df.to_csv(target, index=False, compression="gzip")
                else:
                    print(f"  [{q}] empty")
                    continue
            except Exception as exc:
                print(f"  [{q}] FAILED: {exc}")
                continue
            time.sleep(SLEEP)

        valid = df.dropna(subset=["holder_num"])
        print(f"  {q}: {len(df)} rows, {len(valid)} valid")
        all_frames.append(valid)

    if not all_frames or args.dry_run:
        return

    combined = pd.concat(all_frames, ignore_index=True)
    # Deduplicate: same (ts_code, end_date) keep latest ann_date
    combined = combined.sort_values(["ts_code", "end_date", "ann_date"])
    combined = combined.drop_duplicates(["ts_code", "end_date"], keep="last")

    NORMALIZED_DIR.mkdir(parents=True, exist_ok=True)
    tmp = NORMALIZED_FILE.with_name(f".{NORMALIZED_FILE.name}.{os.getpid()}.tmp")
    combined.to_csv(tmp, index=False, compression="gzip")
    os.replace(tmp, NORMALIZED_FILE)
    print(f"\n[normalize] wrote {len(combined):,} rows -> {NORMALIZED_FILE}")
    print(f"  stocks: {combined.ts_code.nunique()}, quarters: {combined.end_date.nunique()}")
    print(f"  end_date range: {combined.end_date.min()} ~ {combined.end_date.max()}")


if __name__ == "__main__":
    main()
