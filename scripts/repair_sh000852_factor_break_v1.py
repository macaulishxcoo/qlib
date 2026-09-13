#!/usr/bin/env python3
"""Repair the 2026-07-24 index factor break in the Qlib binary store.

Background
----------
``update_daily_market_data_v1.py::build_index_rows()`` writes *raw* Tushare
index prices into the store without multiplying by the store's constant
``factor``.  The historical store (pre-2026-07-24) stores
``close = raw_close * factor`` (e.g. SH000852 ~7.27), but the incremental
window from 2026-07-24 onward stores raw points (~6995), creating a ~96000%
single-day jump for every index.

This script rebuilds the affected window for all broken indices by re-deriving
``close/open/high/low/vwap = raw * factor`` and ``adjclose = raw`` from the
existing raw CSVs (``data/external/tushare/market_daily_v1/*.csv``), leaving
pre-window history untouched.

Usage
-----
    conda activate qlib
    # audit only
    python scripts/repair_sh000852_factor_break_v1.py --check
    # audit + repair
    python scripts/repair_sh000852_factor_break_v1.py --repair
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np
import pandas as pd

DEFAULT_QLIB_DIR = Path.home() / ".qlib/qlib_data/cn_data_2026"
DEFAULT_RAW_DIR = Path("/home/xiaocong/worksapces/qlib/data/external/tushare/market_daily_v1")

# Fields that represent *prices* and must be scaled by factor.
PRICE_FIELDS = ("open", "high", "low", "close", "vwap")
# Fields stored as-is (raw or already correct).
RAW_FIELDS = ("volume", "amount", "change", "factor", "adjclose")
ALL_FIELDS = PRICE_FIELDS + RAW_FIELDS

# Jump threshold: a single-day |pct change| > 20% flags a break.
BREAK_THRESHOLD = 0.20


def read_calendar(qlib_dir: Path) -> list[str]:
    return [l.strip() for l in open(qlib_dir / "calendars" / "day.txt")]


def read_field_bin(fd: Path, field: str) -> np.ndarray:
    path = fd / f"{field}.day.bin"
    if not path.is_file():
        return np.array([], dtype="<f4")
    return np.frombuffer(path.read_bytes(), dtype="<f4")


def detect_break(cal: list[str], close_vals: np.ndarray, start_idx: int,
                 threshold: float = BREAK_THRESHOLD) -> pd.Timestamp | None:
    """Return the first date where |day-over-day close change| > threshold."""
    for i in range(1, len(close_vals)):
        prev, curr = close_vals[i - 1], close_vals[i]
        if prev > 0 and not np.isnan(prev) and not np.isnan(curr):
            if abs(curr / prev - 1) > threshold:
                cal_pos = start_idx + i
                if cal_pos < len(cal):
                    return pd.Timestamp(cal[cal_pos])
    return None


def get_factor(fd: Path) -> float:
    """Read the constant factor from its bin (last non-NaN value)."""
    vals = read_field_bin(fd, "factor")
    if len(vals) < 2:
        return np.nan
    for v in vals[1:][::-1]:
        if not np.isnan(v):
            return float(v)
    return np.nan


def repair_index(fd: Path, raw_csv: Path, cal: list[str],
                 win_start: pd.Timestamp, win_end: pd.Timestamp) -> int:
    """Rebuild the price fields for the broken window from raw CSV * factor.

    Returns the number of calendar days repaired.
    """
    factor = get_factor(fd)
    if np.isnan(factor) or factor == 0:
        raise ValueError(f"Cannot read valid factor for {fd.name}")

    close_bin = read_field_bin(fd, "close")
    start_idx = int(close_bin[0])

    # Window dates in the calendar.
    win_dates = [d for d in cal if win_start <= pd.Timestamp(d) <= win_end]
    if not win_dates:
        return 0

    # Load raw CSV.
    raw = pd.read_csv(raw_csv)
    raw["date"] = pd.to_datetime(raw["date"])
    raw_map = {row["date"]: row for _, row in raw.iterrows()}

    for field in ALL_FIELDS:
        old = read_field_bin(fd, field)
        header = old[:1] if len(old) else np.array([start_idx], dtype="<f4")
        old_vals = old[1:] if len(old) > 1 else np.array([], dtype="<f4")
        new_len = max(len(old_vals), (cal.index(str(win_dates[-1])) - start_idx) + 1)
        new_vals = np.full(new_len, np.nan, dtype="<f4")
        if len(old_vals):
            new_vals[: len(old_vals)] = old_vals

        for d_str in win_dates:
            d = pd.Timestamp(d_str)
            pos = cal.index(d_str) - start_idx
            if pos < 0 or pos >= new_len:
                continue
            if d not in raw_map:
                continue  # suspended / missing -> stays NaN
            row = raw_map[d]
            if field in PRICE_FIELDS:
                new_vals[pos] = float(row[field]) * factor
            elif field == "adjclose":
                new_vals[pos] = float(row["close"])  # adjclose = raw close
            else:
                new_vals[pos] = float(row[field])

        np.concatenate([header, new_vals]).astype("<f4").tofile(fd / f"{field}.day.bin")

    return len(win_dates)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--qlib-dir", type=Path, default=DEFAULT_QLIB_DIR)
    parser.add_argument("--raw-dir", type=Path, default=DEFAULT_RAW_DIR)
    parser.add_argument("--start-date", default="2026-07-24",
                        help="Window start (default: 2026-07-24)")
    parser.add_argument("--end-date", default="2026-08-07",
                        help="Window end (default: latest raw data)")
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--check", action="store_true", help="audit only, report broken indices")
    mode.add_argument("--repair", action="store_true", help="audit and repair broken indices")
    args = parser.parse_args()

    cal = read_calendar(args.qlib_dir)
    win_start = pd.Timestamp(args.start_date)
    win_end = pd.Timestamp(args.end_date)

    # Find all index symbols.
    all_txt = args.qlib_dir / "instruments" / "all.txt"
    syms = pd.read_csv(all_txt, sep="\t", header=None, usecols=[0])[0].tolist()
    idx_syms = [s for s in syms if s.startswith(("SH000", "SZ399"))]

    broken = []
    for sym in idx_syms:
        fd = args.qlib_dir / "features" / sym.lower()
        if not fd.is_dir():
            continue
        close_raw = read_field_bin(fd, "close")
        if len(close_raw) < 2:
            continue
        si = int(close_raw[0])
        close_vals = close_raw[1:]
        break_date = detect_break(cal, close_vals, si)
        if break_date is not None:
            broken.append((sym, break_date))

    print(f"Checked {len(idx_syms)} indices; broken: {len(broken)}")
    for sym, bd in broken:
        print(f"  {sym}: break at {bd.date()}")

    if args.repair and broken:
        repaired_total = 0
        for sym, _ in broken:
            fd = args.qlib_dir / "features" / sym.lower()
            raw_csv = args.raw_dir / f"{sym.lower()}.csv"
            if not raw_csv.is_file():
                print(f"  {sym}: raw CSV not found ({raw_csv}), skipping")
                continue
            n = repair_index(fd, raw_csv, cal, win_start, win_end)
            print(f"  {sym}: repaired {n} days (factor={get_factor(fd):.10f})")
            repaired_total += n
        print(f"\nRepaired {len(broken)} indices, {repaired_total} index-days total.")

        # Re-audit to confirm.
        still_broken = []
        for sym, _ in broken:
            fd = args.qlib_dir / "features" / sym.lower()
            close_raw = read_field_bin(fd, "close")
            si = int(close_raw[0])
            close_vals = close_raw[1:]
            if detect_break(cal, close_vals, si) is not None:
                still_broken.append(sym)
        if still_broken:
            print(f"WARNING: {len(still_broken)} indices still broken: {still_broken}")
            sys.exit(1)
        else:
            print("Post-repair audit: all indices clean (no >20% single-day jumps).")

    if args.check and broken:
        sys.exit(1)
    sys.exit(0)


if __name__ == "__main__":
    main()
