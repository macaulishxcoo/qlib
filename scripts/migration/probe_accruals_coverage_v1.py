#!/usr/bin/env python3
"""Why is accruals coverage only ~2.6% in build_snapshot?

Read-only. Loads the same extended financial frame the strategy uses and reports
coverage at each step of the accruals chain:
    n_income_attr_p (NI)  ->  n_cashflow_act (CFO)  ->  total_assets  ->  TTM
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def main() -> int:
    finext = load_module("finext", ROOT / "scripts/load_financials_extended_v1.py")
    ext = load_module("ext", ROOT / "scripts/analyze_a_share_value_quality_level_factors_extension_v1.py")

    fin = finext.load_financials_extended()
    print("=" * 80)
    print(" financial frame coverage")
    print("=" * 80)
    print(f"  rows: {len(fin):,}   instruments: {fin['ts_code'].nunique():,}")
    for column in ("n_income_attr_p", "n_cashflow_act", "total_assets", "profit_dedt",
                   "bps", "dt_netprofit_yoy"):
        if column in fin.columns:
            print(f"  {column:<20} non-null {fin[column].notna().mean():7.2%}")
        else:
            print(f"  {column:<20} ABSENT")
    print(f"  end_date range: {pd.to_datetime(fin['end_date']).min()} .. {pd.to_datetime(fin['end_date']).max()}")
    print(f"  available_date non-null: {fin['available_date'].notna().mean():.2%}")

    # How many (ts_code) have >= 4 usable quarters, which TTM needs?
    fin = fin.copy()
    fin["end_date"] = pd.to_datetime(fin["end_date"], errors="coerce")
    per_code_q = fin.dropna(subset=["end_date"]).groupby("ts_code")["end_date"].nunique()
    print(f"\n  instruments with >=4 distinct end_dates: {(per_code_q >= 4).sum():,} / {len(per_code_q):,}")
    per_code_ni = fin.dropna(subset=["end_date", "n_income_attr_p"]).groupby("ts_code")["end_date"].nunique()
    print(f"  instruments with >=4 end_dates having NI : {(per_code_ni >= 4).sum():,}")
    if "total_assets" in fin.columns:
        per_code_ta = fin.dropna(subset=["end_date", "total_assets"]).groupby("ts_code")["end_date"].nunique()
        print(f"  instruments with >=4 end_dates having TA : {(per_code_ta >= 4).sum():,}")

    # Reproduce the module's TTM to see where it dies.
    print("\n  TTM step (using the module's own ttm_value):")
    sample = fin[fin["end_date"] >= pd.Timestamp("2023-01-01")]
    for name, column in (("ni_ttm", "n_income_attr_p"), ("cfo_ttm", "n_cashflow_act"),
                         ("ep_ttm", "profit_dedt")):
        try:
            values = ext.ttm_value(sample, column)
            print(f"    {name:<10} non-null {values.notna().mean():7.2%}  (n={values.notna().sum():,})")
        except Exception as exc:  # noqa: BLE001
            print(f"    {name:<10} FAILED: {type(exc).__name__}: {exc}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
