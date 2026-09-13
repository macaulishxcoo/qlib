#!/usr/bin/env python3
"""Download recent (2025-Q1 onward) income/cashflow/balancesheet PIT records.

The fina_indicator recent records already cover 2026-Q2, but the three
statements (needed for the accruals factor) were only collected up to 2025-06.
This collector pulls the missing recent statements per stock, stored under
a_share_financial_pit_v1/recent_3tables/ in the same file-per-stock style as
the fina_indicator recent directory, with ann_date as the disclosure date.

Only stocks that already have a fina_indicator recent file are fetched (no
duplicate universe discovery).  Already-downloaded files are skipped, so the
script is resumable.
"""

from __future__ import annotations

import os
import time
from pathlib import Path

import pandas as pd
import tushare as ts

FIN_RECENT = Path("data/external/tushare/a_share_financial_pit_v1/recent")
OUT_DIR = Path("data/external/tushare/a_share_financial_pit_v1/recent_3tables")
ENDPOINT_COLS = {
    "income": ["ts_code", "end_date", "ann_date", "n_income_attr_p", "revenue", "total_revenue"],
    "cashflow": ["ts_code", "end_date", "ann_date", "n_cashflow_act"],
    "balancesheet": ["ts_code", "end_date", "ann_date", "total_assets"],
}
START_END = "20250331"  # keep reports from 2025-Q1 onwards


def load_token() -> str:
    token = os.environ.get("TUSHARE_TOKEN", "").strip()
    if not token:
        p = Path.home() / ".config/tushare/token"
        if p.is_file():
            token = p.read_text(encoding="utf-8").strip()
    if not token:
        raise RuntimeError("No Tushare token")
    return token


def stock_key_to_ts_code(stock_key: str) -> str:
    """'600210_SH' -> '600210.SH'"""
    code, exchange = stock_key.split("_")
    return f"{code}.{exchange}"


def _query_with_retry(pro, endpoint: str, ts_code: str, retries: int = 8):
    """Query one endpoint with backoff on Tushare rate limits (200/min)."""
    for attempt in range(retries):
        try:
            return pro.query(endpoint, ts_code=ts_code, start_date=START_END)
        except Exception as exc:
            if "频率超限" in str(exc) or "frequency" in str(exc).lower():
                time.sleep(65)  # wait for the rate window to reset
                continue
            print(f"  {endpoint} {ts_code}: {type(exc).__name__} {str(exc)[:60]}", flush=True)
            time.sleep(1.0)
            continue
    print(f"  {endpoint} {ts_code}: gave up after {retries} retries", flush=True)
    return pd.DataFrame()


def main() -> None:
    pro = ts.pro_api(load_token())
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    files = sorted(FIN_RECENT.glob("*.csv.gz"))
    print(f"universe: {len(files)} stocks from fina_indicator recent", flush=True)

    done_total = 0
    for path in files:
        stock_key = path.name.removesuffix(".csv.gz")  # Path.stem strips only .gz
        ts_code = stock_key_to_ts_code(stock_key)
        for endpoint, cols in ENDPOINT_COLS.items():
            out_path = OUT_DIR / f"{endpoint}_{stock_key}.csv.gz"
            if out_path.exists():
                continue
            frame = _query_with_retry(pro, endpoint, ts_code)
            if frame is None or frame.empty:
                continue
            frame = frame[[c for c in cols if c in frame.columns]]
            frame.to_csv(out_path, index=False, compression="gzip")
            # Tushare limit is 200 calls/min per endpoint; 0.35s keeps us safe.
            time.sleep(0.35)
        done_total += 1
        if done_total % 200 == 0:
            print(f"progress: {done_total}/{len(files)} stocks", flush=True)

    counts = {ep: len(list(OUT_DIR.glob(f"{ep}_*.csv.gz"))) for ep in ENDPOINT_COLS}
    print(f"completed|{counts}", flush=True)


if __name__ == "__main__":
    main()
