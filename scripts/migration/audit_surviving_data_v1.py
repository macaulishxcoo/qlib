#!/usr/bin/env python3
"""Correct inventory of the data assets that survived the move to this machine.

Read-only, compact output. Handles both layouts the repo uses:

* a single consolidated ``<name>.csv.gz``, and
* ``batch_NNNN/<name>.csv.gz`` shards (the financial PIT tables use this),
* plus large files split into ``.partNN`` chunks awaiting reassembly.

Run with any interpreter that has pandas::

    <python> scripts/migration/audit_surviving_data_v1.py
"""

from __future__ import annotations

import gzip
from pathlib import Path

import pandas as pd

REPO = Path(__file__).resolve().parents[2]
TUSHARE = REPO / "data" / "external" / "tushare"


def human(num_bytes: float) -> str:
    for unit, scale in (("GB", 1 << 30), ("MB", 1 << 20), ("KB", 1 << 10)):
        if num_bytes >= scale:
            return f"{num_bytes / scale:.2f} {unit}"
    return f"{num_bytes:.0f} B"


def dir_size(path: Path) -> int:
    if not path.exists():
        return -1
    if path.is_file():
        return path.stat().st_size
    return sum(f.stat().st_size for f in path.rglob("*") if f.is_file())


def locate(root: Path, name: str) -> tuple[str, list[Path]]:
    """Find ``name`` as a consolidated file or as batch shards under ``root``."""
    if not root.exists():
        return "MISSING", []
    direct = root / name
    if direct.is_file():
        return "single", [direct]
    shards = sorted(root.glob(f"*/{name}")) + sorted(root.glob(f"*/*/{name}"))
    if shards:
        return f"{len(shards)} shards", shards
    nested = sorted(root.rglob(name))
    if nested:
        return f"{len(nested)} nested", nested
    return "MISSING", []


def header_of(path: Path) -> list[str]:
    with gzip.open(path, "rt", encoding="utf-8", errors="replace") as handle:
        return handle.readline().rstrip("\n").split(",")


def main() -> int:
    print("=" * 92)
    print(" Surviving-data inventory")
    print("=" * 92)

    # ---------------------------------------------------------------- #
    print("\n[A] chunked files (git-tracked .partNN awaiting reassembly)")
    # The three chunked files are the ones the repo documents; verify the
    # reassembled targets directly rather than re-parsing the manifest schema.
    for original in (
        "data/external/tushare/a_share_daily_basic_pit_v1/normalized/daily_basic.csv.gz",
        "data/external/tushare/moneyflow_pit_v1/normalized/moneyflow.csv.gz",
        "data/external/tushare/margin_pit_v1/normalized/margin_detail.csv.gz",
    ):
        target = REPO / original
        if target.exists():
            parts = sorted(target.parent.glob(target.name + ".part*"))
            print(f"  [OK     ] {original}  {human(target.stat().st_size)}"
                  f"  ({len(parts)} parts still present)")
        else:
            print(f"  [PENDING] {original}  -- run scripts/data_collector/reassemble_large_data_v1.py")

    # ---------------------------------------------------------------- #
    print("\n[B] datasets")
    datasets = [
        ("daily_basic (close/mv/valuation)",
         TUSHARE / "a_share_daily_basic_pit_v1/normalized", "daily_basic.csv.gz"),
        ("financial fina_indicator", TUSHARE / "a_share_financial_pit_v1/full/normalized", "fina_indicator.csv.gz"),
        ("financial cashflow", TUSHARE / "a_share_financial_pit_v1/full/normalized", "cashflow.csv.gz"),
        ("financial income", TUSHARE / "a_share_financial_pit_v1/full/normalized", "income.csv.gz"),
        ("financial balancesheet", TUSHARE / "a_share_financial_pit_v1/balancesheet_v1/normalized", "balancesheet.csv.gz"),
        ("financial fina_indicator (consolidated)", TUSHARE / "a_share_financial_pit_v1/normalized", "fina_indicator.csv.gz"),
        ("ST status intervals", TUSHARE / "a_share_st_status_pit_v1/normalized", "st_status_intervals.csv.gz"),
        ("style: monthly free float size", TUSHARE / "a_share_style_pit_v1/normalized", "monthly_free_float_size.csv.gz"),
        ("style: industry L1 intervals", TUSHARE / "a_share_style_pit_v1/normalized", "industry_l1_effective_intervals.csv.gz"),
        ("style: monthly rebalance grid", TUSHARE / "a_share_style_pit_v1/normalized", "monthly_rebalance_grid.csv.gz"),
        ("margin detail", TUSHARE / "margin_pit_v1/normalized", "margin_detail.csv.gz"),
        ("moneyflow", TUSHARE / "moneyflow_pit_v1/normalized", "moneyflow.csv.gz"),
        ("sw industry index", TUSHARE / "sw_industry_index_v1/normalized", "sw_industry_daily.csv.gz"),
    ]
    for label, root, name in datasets:
        state, paths = locate(root, name)
        if not paths:
            print(f"  {label:<42} MISSING  ({root.relative_to(REPO)}/{name})")
            continue
        total = sum(p.stat().st_size for p in paths)
        cols = header_of(paths[0])
        print(f"  {label:<42} {state:<10} {human(total):>9}  {len(cols)} cols")
        print(f"      dir : {paths[0].parent.relative_to(REPO)}")
        print(f"      cols: {', '.join(cols[:14])}{' ...' if len(cols) > 14 else ''}")

    # ---------------------------------------------------------------- #
    print("\n[C] directory-level sizes")
    for label, path in (
        ("data/external/tushare", TUSHARE),
        ("data/derived", REPO / "data/derived"),
        ("*** ~/.qlib/qlib_data/cn_data_2026 ***", Path.home() / ".qlib/qlib_data/cn_data_2026"),
        ("*** market_daily_v1 ***", TUSHARE / "market_daily_v1"),
    ):
        size = dir_size(path)
        print(f"  {label:<46} {'MISSING' if size < 0 else human(size)}")

    # ---------------------------------------------------------------- #
    print("\n[D] the strategy's key inputs, in the layout the scripts expect")
    db = TUSHARE / "a_share_daily_basic_pit_v1/normalized/daily_basic.csv.gz"
    if db.exists():
        frame = pd.read_csv(db, compression="gzip", usecols=["ts_code", "trade_date", "close", "total_mv"])
        frame["trade_date"] = pd.to_datetime(frame["trade_date"], format="%Y%m%d", errors="coerce")
        print(f"  daily_basic rows      : {len(frame):,}")
        print(f"  daily_basic span      : {frame['trade_date'].min().date()} .. {frame['trade_date'].max().date()}")
        print(f"  instruments / days    : {frame['ts_code'].nunique():,} / {frame['trade_date'].nunique():,}")
        print(f"  close / total_mv null : {frame['close'].isna().mean():.4%} / {frame['total_mv'].isna().mean():.4%}")
        del frame

    print("\n" + "=" * 92)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
