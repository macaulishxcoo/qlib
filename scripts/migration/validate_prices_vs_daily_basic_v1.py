#!/usr/bin/env python3
"""Validate the rebuilt qlib store against an independent on-disk source.

The rebuilt store is derived from Tushare ``daily`` x ``adj_factor``. Tushare
``daily_basic`` (already on disk, untouched by the rebuild) carries the *raw*
close for the same name and day. So ``$close / $factor`` from the store must
equal ``daily_basic.close``. Any mismatch means the reconstruction is wrong, not
that the strategy differs.

Read-only.
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

REPO = Path(__file__).resolve().parents[2]
STORE = Path.home() / ".qlib/qlib_data/cn_data_2026"
DAILY_BASIC = REPO / "data/external/tushare/a_share_daily_basic_pit_v1/normalized/daily_basic.csv.gz"

N_SAMPLE = 30
START = "2022-01-01"
END = "2025-06-30"


def qlib_symbol(ts_code: str) -> str:
    number, suffix = ts_code.split(".")
    return f"{suffix}{number}"


def main() -> int:
    import qlib
    from qlib.config import REG_CN
    from qlib.data import D

    qlib.init(provider_uri=str(STORE), region=REG_CN)

    print("=" * 84)
    print(" store vs daily_basic price validation")
    print("=" * 84)

    # A deterministic sample spread across the pool.
    db = pd.read_csv(DAILY_BASIC, compression="gzip",
                     usecols=["ts_code", "trade_date", "close"])
    db = db[(db["trade_date"] >= int(START.replace("-", ""))) & (db["trade_date"] <= int(END.replace("-", "")))]
    codes = sorted(db["ts_code"].unique())
    step = max(len(codes) // N_SAMPLE, 1)
    sample = codes[::step][:N_SAMPLE]
    symbols = [qlib_symbol(c) for c in sample]
    print(f"  sampled {len(symbols)} of {len(codes)} instruments over {START}..{END}")

    frame = D.features(symbols, ["$close", "$factor"], start_time=START, end_time=END, freq="day")
    if frame.empty:
        print("  FAILED: D.features returned nothing")
        return 1

    implied = frame.copy()
    implied["raw_close"] = implied["$close"] / implied["$factor"]
    implied = implied.reset_index()
    implied["ts_code"] = implied["instrument"].map(
        lambda s: f"{s[2:]}.{s[:2]}"
    )
    implied["trade_date"] = pd.to_datetime(implied["datetime"]).dt.strftime("%Y%m%d").astype(int)

    merged = implied.merge(db, on=["ts_code", "trade_date"], how="inner", suffixes=("", "_db"))
    print(f"  matched rows: {len(merged):,} of {len(implied):,} store rows")

    if merged.empty:
        print("  FAILED: no overlapping rows")
        return 1

    diff = (merged["raw_close"] - merged["close"]).abs()
    rel = diff / merged["close"].abs().clip(lower=1e-9)
    print(f"  absolute diff : mean {diff.mean():.6f}  median {diff.median():.6f}  max {diff.max():.6f}")
    print(f"  relative diff : mean {rel.mean():.3e}  p99 {rel.quantile(0.99):.3e}  max {rel.max():.3e}")

    tol = 1e-4
    bad = merged[rel > tol]
    print(f"  rows with relative error > {tol:g}: {len(bad):,} ({len(bad) / len(merged):.4%})")
    if not bad.empty:
        print("  worst offenders:")
        print(bad.nlargest(5, "raw_close")[["ts_code", "trade_date", "raw_close", "close"]].to_string(index=False))
        bad_codes = bad["ts_code"].value_counts()
        print(f"  affected instruments: {len(bad_codes)} of {merged['ts_code'].nunique()}")
        print(bad_codes.head(5).to_string())

    print()
    print("-" * 84)
    ok = len(bad) / len(merged) < 0.01
    if ok:
        print("VALIDATION PASSED: rebuilt prices reproduce the independent raw close")
    else:
        print("VALIDATION FAILED: >1% of rows disagree with daily_basic.close")
    print("-" * 84)
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
