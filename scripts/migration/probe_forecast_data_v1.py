#!/usr/bin/env python3
"""Read-only probe of a_share_forecast_v1 before writing a protocol."""

from __future__ import annotations

import gzip
from pathlib import Path

import pandas as pd

REPO = Path(__file__).resolve().parents[2]
FORECAST = REPO / "data/external/tushare/a_share_forecast_v1"


def main() -> int:
    print("=" * 84)
    print(" a_share_forecast_v1 probe")
    print("=" * 84)
    for path in sorted(FORECAST.rglob("*")):
        if path.is_file():
            print(f"  {path.relative_to(REPO)}  {path.stat().st_size / 1e6:.2f} MB")

    frames = []
    for path in sorted(FORECAST.rglob("*.csv.gz")):
        try:
            frame = pd.read_csv(path, compression="gzip", dtype=str, nrows=5000)
        except Exception as exc:  # noqa: BLE001
            print(f"  cannot read {path.name}: {exc}")
            continue
        print(f"\n  {path.name}: columns = {list(frame.columns)}")
        frames.append(frame.head(3))
    if frames:
        sample = pd.concat(frames)
        print("\n  sample rows:")
        print(sample.head(6).to_string(index=False))

    # Full read of the normalised/largest file for real stats.
    candidates = sorted(FORECAST.rglob("*.csv.gz"), key=lambda p: p.stat().st_size, reverse=True)
    if not candidates:
        return 1
    target = candidates[0]
    print(f"\n  full read: {target.relative_to(REPO)}")
    full = pd.read_csv(target, compression="gzip", dtype=str, low_memory=False)
    print(f"  rows: {len(full):,}")
    print(f"  columns ({len(full.columns)}): {list(full.columns)}")
    for column in ("ann_date", "end_date", "type", "p_change_min", "p_change_max",
                   "net_profit_min", "net_profit_max", "change_reason", "ts_code"):
        if column in full.columns:
            series = full[column]
            print(f"    {column:<18} non-null {series.notna().mean():6.2%}  "
                  f"unique {series.nunique():,}  sample {series.dropna().head(3).tolist()}")
    if "type" in full.columns:
        print("\n  type distribution:")
        print(full["type"].value_counts().head(15).to_string())
    if "ann_date" in full.columns:
        dates = pd.to_datetime(full["ann_date"], format="%Y%m%d", errors="coerce")
        print(f"\n  ann_date range: {dates.min()} .. {dates.max()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
