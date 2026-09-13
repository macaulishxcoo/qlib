#!/usr/bin/env python3
"""Repair Qlib binary bars damaged by DumpDataUpdate's suspended-stock append bug.

Background
----------
``dump_bin.py DumpDataUpdate`` appends raw float values to the end of each field's
``.day.bin``. It assumes the incremental window has a row for every trading day.
When a stock is suspended for part of the window, Tushare has no row for those
days, so the append writes fewer floats than the calendar expects.  Every value
after the first suspended day is then read at the WRONG date (off-by-N shift),
or the tail of the window is missing entirely.

This script rebuilds the incremental window (default 2026-07-24 .. 2026-08-07) of
every stock that has raw CSV data, using the raw (already adjusted) values aligned
to the global calendar, NaN for suspended days, and rewrites the affected field
bins.  History before the window is preserved untouched.

Usage
-----
    conda activate qlib
    # audit only
    python scripts/data_collector/repair_market_data_update_v1.py --check
    # audit + repair damaged stocks
    python scripts/data_collector/repair_market_data_update_v1.py --repair
"""

import argparse
import sys
from pathlib import Path

import numpy as np
import pandas as pd

DEFAULT_QLIB_DIR = Path.home() / ".qlib/qlib_data/cn_data_2026"
DEFAULT_RAW_DIR = Path(__file__).resolve().parents[2] / "data/external/tushare/market_daily_v1"
DEFAULT_START = "2026-07-24"
DEFAULT_END = "2026-08-07"

BIN_FIELDS = ["open", "high", "low", "close", "volume", "amount", "change", "factor", "vwap", "adjclose"]


def read_field_bin(fd: Path, field: str) -> np.ndarray:
    path = fd / f"{field}.day.bin"
    if not path.is_file():
        return np.array([], dtype="<f4")
    return np.frombuffer(path.read_bytes(), dtype="<f4")


def audit_stock(fd: Path, raw_df: pd.DataFrame, calendar: pd.DatetimeIndex,
                win_dates: pd.DatetimeIndex) -> list:
    """Return a list of mismatch descriptions for one stock, or [] if clean.

    A stock is damaged if any window day present in raw CSV has a bin value that
    is not NaN and differs from the raw value (or is NaN where raw has a value).
    """
    close_bin = read_field_bin(fd, "close")
    if len(close_bin) < 2:
        return ["no close bin"]
    start_idx = int(close_bin[0])
    vals = close_bin[1:]
    raw_map = dict(zip(raw_df["date"], raw_df["close"]))
    issues = []
    for d in win_dates:
        bin_pos = calendar.get_loc(d) - start_idx
        bin_v = vals[bin_pos] if 0 <= bin_pos < len(vals) else np.nan
        if d in raw_map:
            exp = float(raw_map[d])
            if np.isnan(bin_v) or abs(bin_v - exp) / exp > 1e-3:
                issues.append(f"{d.date()}:{bin_v:.4f}!={exp:.4f}")
    return issues


def repair_stock(fd: Path, raw_df: pd.DataFrame, calendar: pd.DatetimeIndex,
                 win_dates: pd.DatetimeIndex, win_start: pd.Timestamp) -> None:
    """Rebuild the incremental window of every field bin from raw values."""
    start_idx = int(read_field_bin(fd, "close")[0])
    win_pos0 = calendar.get_loc(win_start) - start_idx  # first window position in bin
    for field in BIN_FIELDS:
        path = fd / f"{field}.day.bin"
        old = read_field_bin(fd, field)
        header = old[:1] if len(old) else np.array([start_idx], dtype="<f4")
        old_vals = old[1:] if len(old) > 1 else np.array([], dtype="<f4")

        # new length = max(old length, win_pos0 + len(win_dates))
        new_len = max(len(old_vals), win_pos0 + len(win_dates))
        new_vals = np.full(new_len, np.nan, dtype="<f4")
        if len(old_vals):
            new_vals[: len(old_vals)] = old_vals
        # fill window from raw (NaN where raw has no row, i.e. suspended)
        raw_map = dict(zip(raw_df["date"], raw_df[field]))
        for i, d in enumerate(win_dates):
            pos = win_pos0 + i
            if pos < 0:
                continue
            new_vals[pos] = raw_map.get(d, np.nan)
        np.concatenate([header, new_vals]).astype("<f4").tofile(path)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--qlib-dir", type=Path, default=DEFAULT_QLIB_DIR)
    parser.add_argument("--raw-dir", type=Path, default=DEFAULT_RAW_DIR)
    parser.add_argument("--start-date", default=DEFAULT_START)
    parser.add_argument("--end-date", default=DEFAULT_END)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--check", action="store_true", help="audit only, report damaged stocks")
    mode.add_argument("--repair", action="store_true", help="audit and repair damaged stocks")
    args = parser.parse_args()

    calendar = pd.DatetimeIndex(pd.to_datetime(pd.read_csv(args.qlib_dir / "calendars" / "day.txt", header=None)[0]))
    win_start = pd.Timestamp(args.start_date)
    win_end = pd.Timestamp(args.end_date)
    win_dates = calendar[(calendar >= win_start) & (calendar <= win_end)]

    damaged = []
    checked = 0
    for csv_path in sorted((args.raw_dir).glob("*.csv")):
        sym = csv_path.stem.upper()
        fd = args.qlib_dir / "features" / sym.lower()
        if not fd.is_dir():
            continue
        rdf = pd.read_csv(csv_path)
        rdf["date"] = pd.to_datetime(rdf["date"])
        if rdf["date"].max() < win_start:
            continue
        checked += 1
        issues = audit_stock(fd, rdf, calendar, win_dates)
        if issues:
            damaged.append((sym, issues))
            if args.repair:
                repair_stock(fd, rdf, calendar, win_dates, win_start)

    print(f"checked {checked} stocks with raw data in [{args.start_date}, {args.end_date}]")
    print(f"damaged: {len(damaged)}")
    for sym, iss in damaged:
        print(f"  {sym}: {'; '.join(iss[:5])}{' ...' if len(iss) > 5 else ''}")
    if args.repair:
        # re-audit to confirm the repair
        still_bad = 0
        for csv_path in sorted((args.raw_dir).glob("*.csv")):
            sym = csv_path.stem.upper()
            fd = args.qlib_dir / "features" / sym.lower()
            if not fd.is_dir():
                continue
            rdf = pd.read_csv(csv_path)
            rdf["date"] = pd.to_datetime(rdf["date"])
            if rdf["date"].max() < win_start:
                continue
            if audit_stock(fd, rdf, calendar, win_dates):
                still_bad += 1
        print(f"after repair, remaining damaged: {still_bad}")
        sys.exit(0 if still_bad == 0 else 1)
    sys.exit(0 if not damaged else 1)


if __name__ == "__main__":
    main()
