#!/usr/bin/env python3
"""Extended financial loader: merge recent_3tables & merged fina_indicator into
the PIT frame used by the signal pipeline, extending coverage to 2026-Q2.

Existing validator scripts keep reading the frozen `full/normalized` batches;
this loader is for the production pipeline only.  It returns the same schema
as `load_financials` (ts_code, end_date, available_date, profit_dedt, roe,
bps, debt_to_assets, n_cashflow_act, n_income_attr_p, total_assets).
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

FIN = Path("data/external/tushare/a_share_financial_pit_v1")
FULL = FIN / "full/normalized"
# The balancesheet statement is NOT in full/normalized/batch_*: that tree holds
# only cashflow / fina_indicator / income. Balancesheet was downloaded into its
# own tree, which is what the frozen validator loader
# (analyze_a_share_value_quality_level_factors_extension_v1.load_financials,
# BAL_BASE) reads. Pointing at FULL here silently produced an all-NaN
# total_assets and therefore an almost entirely missing `accruals` leg.
BAL_FULL = FIN / "balancesheet_v1/normalized"
RECENT_3T = FIN / "recent_3tables"


def _read_batches(base: Path, table: str, cols: list[str]) -> pd.DataFrame:
    frames = []
    for batch in sorted(base.glob("batch_*")):
        path = batch / f"{table}.csv.gz"
        if path.exists():
            frames.append(pd.read_csv(path, compression="gzip", usecols=cols))
    return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame(columns=cols)


def _read_full(table: str, cols: list[str]) -> pd.DataFrame:
    return _read_batches(FULL, table, cols)


def _read_recent_3tables(table: str, cols: list[str]) -> pd.DataFrame:
    frames = []
    for path in sorted(RECENT_3T.glob(f"{table}_*.csv.gz")):
        frames.append(pd.read_csv(path, compression="gzip"))
    return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame(columns=cols)


def _fill_available(frame: pd.DataFrame) -> pd.DataFrame:
    """available_date may be missing on recent records; use ann_date (disclosure day).

    ann_date can be int (20260429), float (20250419.0) or str; the float needs
    the trailing '.0' stripped before parsing with format="%Y%m%d".
    """
    frame["available_date"] = pd.to_datetime(frame["available_date"], errors="coerce")
    numeric = pd.to_numeric(frame["ann_date"], errors="coerce")
    ann_str = numeric.astype("Int64").astype(str).str.replace("<NA>", "", regex=False)
    ann = pd.to_datetime(ann_str, format="%Y%m%d", errors="coerce")
    frame["available_date"] = frame["available_date"].fillna(ann)
    frame["end_date"] = pd.to_datetime(frame["end_date"].astype(str), format="%Y%m%d", errors="coerce")
    return frame


def load_financials_extended() -> pd.DataFrame:
    """Return the extended PIT financial frame with coverage through 2026-Q2.

    fina_indicator: merged top-level normalized file (includes recent), with
    available_date backfilled from ann_date.
    cashflow / income / balancesheet: full batches + recent_3tables, deduped by
    (ts_code, end_date, available_date) keeping the latest version.
    """
    # ---- fina_indicator: top-level merged file ----
    fin_path = FIN / "normalized/fina_indicator.csv.gz"
    if not fin_path.exists():
        raise FileNotFoundError(fin_path)
    fin = pd.read_csv(fin_path, compression="gzip", low_memory=False)
    fin = fin[["ts_code", "end_date", "ann_date", "available_date", "profit_dedt", "roe", "bps", "debt_to_assets"]]
    fin = _fill_available(fin)
    fin = fin.dropna(subset=["available_date"])
    fin = fin.drop_duplicates(["ts_code", "end_date", "available_date"], keep="last")

    # ---- three statements ----
    def load_stmt(table: str, cols: list[str], base: Path | None = None) -> pd.DataFrame:
        full = _read_batches(base or FULL, table, cols)
        recent = _read_recent_3tables(table, cols)
        frame = pd.concat([full, recent], ignore_index=True)
        frame = _fill_available(frame)
        frame = frame.dropna(subset=["available_date"])
        return frame.drop_duplicates(["ts_code", "end_date", "available_date"], keep="last")

    cash = load_stmt("cashflow", ["ts_code", "end_date", "ann_date", "available_date", "n_cashflow_act"])
    income = load_stmt("income", ["ts_code", "end_date", "ann_date", "available_date", "n_income_attr_p"])
    bal = load_stmt("balancesheet", ["ts_code", "end_date", "ann_date", "available_date", "total_assets"],
                    base=BAL_FULL)

    result = fin
    result = result.merge(
        cash[["ts_code", "end_date", "available_date", "n_cashflow_act"]],
        on=["ts_code", "end_date", "available_date"], how="left",
    )
    result = result.merge(
        income[["ts_code", "end_date", "available_date", "n_income_attr_p"]],
        on=["ts_code", "end_date", "available_date"], how="left",
    )
    result = result.merge(
        bal[["ts_code", "end_date", "available_date", "total_assets"]],
        on=["ts_code", "end_date", "available_date"], how="left",
    )
    return result


if __name__ == "__main__":
    frame = load_financials_extended()
    print("rows:", len(frame))
    print("available_date:", frame["available_date"].min(), "->", frame["available_date"].max())
    print("end_date:", frame["end_date"].min(), "->", frame["end_date"].max())
    recent = frame[frame["available_date"] >= "2025-07-01"]
    print("available>=2025-07:", len(recent))
    if len(recent):
        print("  n_cashflow_act nonnull:", round(recent["n_cashflow_act"].notna().mean(), 3))
        print("  n_income_attr_p nonnull:", round(recent["n_income_attr_p"].notna().mean(), 3))
        print("  total_assets nonnull:", round(recent["total_assets"].notna().mean(), 3))
        print("  profit_dedt nonnull:", round(recent["profit_dedt"].notna().mean(), 3))
