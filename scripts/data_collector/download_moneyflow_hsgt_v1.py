#!/usr/bin/env python3
"""Download daily aggregate northbound capital flow (moneyflow_hsgt) from Tushare.

This is market-level data (total north/south money flow), not individual stocks.
One row per trading day. Used for market-timing signal validation.

Usage
-----
    conda activate qlib
    python scripts/data_collector/download_moneyflow_hsgt_v1.py
"""

from __future__ import annotations

import os
import time
from pathlib import Path

import pandas as pd
import tushare as ts

TOKEN_PATH = Path("/root/.config/tushare/token")
QLIB_DIR = Path.home() / ".qlib/qlib_data/cn_data_2026"
OUTPUT_FILE = Path("data/external/tushare/moneyflow_hsgt_pit_v1/moneyflow_hsgt.csv.gz")
START_DATE = "20160101"


def load_token() -> str:
    if TOKEN_PATH.is_file():
        return TOKEN_PATH.read_text(encoding="utf-8").strip()
    raise SystemExit("Tushare token missing")


def read_calendar() -> list[str]:
    cal = pd.read_csv(QLIB_DIR / "calendars" / "day.txt", header=None)
    return [d.replace("-", "") for d in cal[0].astype(str)]


def main() -> None:
    pro = ts.pro_api(load_token())
    cal_dates = read_calendar()
    # Download in quarterly chunks to avoid API limits
    all_frames = []
    quarters = pd.date_range("2016-01-01", "2026-12-31", freq="QE")
    chunks = [(quarters[i].strftime("%Y%m%d"), quarters[i+1].strftime("%Y%m%d"))
              for i in range(len(quarters)-1)]
    # Add the last partial chunk
    chunks.append(("20260401", "20261231"))

    print(f"[plan] downloading moneyflow_hsgt in {len(chunks)} chunks ...")
    for start, end in chunks:
        try:
            df = pro.moneyflow_hsgt(start_date=start, end_date=end)
            if df is not None and not df.empty:
                all_frames.append(df)
                print(f"  {start}-{end}: {len(df)} rows")
            time.sleep(0.3)
        except Exception as exc:
            print(f"  {start}-{end}: FAILED {exc}")

    if not all_frames:
        print("[error] no data downloaded")
        return

    combined = pd.concat(all_frames, ignore_index=True).drop_duplicates(subset=["trade_date"])
    combined = combined.sort_values("trade_date").reset_index(drop=True)

    OUTPUT_FILE.parent.mkdir(parents=True, exist_ok=True)
    combined.to_csv(OUTPUT_FILE, index=False, compression="gzip")
    print(f"\n[done] {len(combined)} rows -> {OUTPUT_FILE}")
    print(f"  trade_date: {combined.trade_date.min()} ~ {combined.trade_date.max()}")
    print(f"  columns: {list(combined.columns)}")


if __name__ == "__main__":
    main()
