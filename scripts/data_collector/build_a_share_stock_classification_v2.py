#!/usr/bin/env python3
"""Extend the v1 monthly stock classification layer with structural risk labels.

V2 adds Shenwan L2/L3, security/board metadata, PIT ST/delist status, and
month-end trading/liquidity labels.  It only reads already local data.
"""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

from build_a_share_stock_classification_v1 import (
    DAILY_BASIC,
    INDEX_MEMBERSHIP,
    INDUSTRY_RAW_DIR,
    STOCK_BASIC,
    atomic_csv,
    atomic_json,
    attach_indexes,
    load_month_end_size,
    sha256,
    validate,
)


ST_INTERVALS = Path("data/external/tushare/a_share_st_status_pit_v1/normalized/st_status_intervals.csv.gz")
OUTPUT_DIR = Path("data/derived/a_share_stock_classification_v2")


def attach_industry_levels(base: pd.DataFrame) -> pd.DataFrame:
    files = sorted(INDUSTRY_RAW_DIR.glob("is_new_*.csv.gz"))
    industry = pd.concat(
        [pd.read_csv(path, compression="gzip", usecols=["ts_code", "l1_code", "l1_name", "l2_code", "l2_name", "l3_code", "l3_name", "in_date", "out_date"], dtype=str) for path in files],
        ignore_index=True,
    ).drop_duplicates()
    industry["industry_in_date"] = pd.to_datetime(industry.pop("in_date"), format="%Y%m%d", errors="coerce")
    industry["industry_out_date"] = pd.to_datetime(industry.pop("out_date"), format="%Y%m%d", errors="coerce")
    label_columns = ["l1_code", "l1_name", "l2_code", "l2_name", "l3_code", "l3_name", "industry_in_date", "industry_out_date"]

    keys = base[["asof_date", "ts_code"]].reset_index(names="row_id")
    candidates = keys.merge(industry, on="ts_code", how="left")
    active = candidates[
        candidates["industry_in_date"].le(candidates["asof_date"])
        & (candidates["industry_out_date"].isna() | candidates["industry_out_date"].ge(candidates["asof_date"]))
    ].sort_values(["row_id", "industry_in_date"]).drop_duplicates("row_id", keep="last")
    result = base.join(active.set_index("row_id")[label_columns], how="left")
    result["industry_gap_fill"] = False
    missing = result["l1_code"].isna()
    if missing.any():
        prior = candidates[candidates["industry_in_date"].le(candidates["asof_date"])]
        prior = prior.sort_values(["row_id", "industry_in_date"]).drop_duplicates("row_id", keep="last").set_index("row_id")[label_columns]
        ids = result.index[missing]
        for column in label_columns:
            result.loc[missing, column] = prior.reindex(ids)[column].to_numpy()
        result.loc[missing & result["l1_code"].notna(), "industry_gap_fill"] = True
    return result


def attach_security_and_board(base: pd.DataFrame) -> pd.DataFrame:
    security = pd.read_csv(
        STOCK_BASIC, compression="gzip", usecols=["ts_code", "name", "exchange", "market", "list_date", "delist_date", "list_status"], dtype=str,
    ).drop_duplicates("ts_code", keep="last")
    security = security.rename(columns={"name": "security_name", "market": "market_board"})
    security["list_date"] = pd.to_datetime(security["list_date"], format="%Y%m%d", errors="coerce")
    security["delist_date"] = pd.to_datetime(security["delist_date"], format="%Y%m%d", errors="coerce")
    result = base.merge(security, on="ts_code", how="left", validate="many_to_one")
    result["board"] = np.select(
        [result["exchange"].eq("BSE"), result["market_board"].eq("创业板"), result["market_board"].eq("科创板"), result["exchange"].eq("SSE"), result["exchange"].eq("SZSE")],
        ["bse", "chinext", "star", "sse_main", "szse_main"], default="other",
    )
    result["listing_age_days"] = (result["asof_date"] - result["list_date"]).dt.days
    return result


def attach_st_status(base: pd.DataFrame) -> pd.DataFrame:
    st = pd.read_csv(ST_INTERVALS, compression="gzip", usecols=["ts_code", "start_date", "end_date", "is_st", "is_delist_phase"], dtype=str)
    st["start_date"] = pd.to_datetime(st["start_date"], errors="coerce")
    st["end_date"] = pd.to_datetime(st["end_date"], errors="coerce")
    st["is_st"] = st["is_st"].eq("True")
    st["is_delist_phase"] = st["is_delist_phase"].eq("True")
    keys = base[["asof_date", "ts_code"]].reset_index(names="row_id")
    candidates = keys.merge(st, on="ts_code", how="left")
    active = candidates[candidates["start_date"].le(candidates["asof_date"]) & candidates["end_date"].ge(candidates["asof_date"])]
    flags = active.groupby("row_id")[["is_st", "is_delist_phase"]].max()
    result = base.join(flags, how="left")
    result[["is_st", "is_delist_phase"]] = result[["is_st", "is_delist_phase"]].fillna(False).astype(bool)
    result["risk_status"] = np.select(
        [result["is_delist_phase"], result["is_st"]], ["delist_phase", "st"], default="normal",
    )
    return result


def attach_trading_and_turnover(base: pd.DataFrame, start: str, end: str) -> pd.DataFrame:
    raw = pd.read_csv(
        DAILY_BASIC, compression="gzip", usecols=["ts_code", "trade_date", "turnover_rate", "turnover_rate_f", "volume_ratio"], dtype={"ts_code": str, "trade_date": str},
    )
    raw["asof_date"] = pd.to_datetime(raw.pop("trade_date"), format="%Y%m%d", errors="coerce")
    raw = raw[raw["asof_date"].between(pd.Timestamp(start), pd.Timestamp(end))].copy()
    raw["month"] = raw["asof_date"].dt.to_period("M")
    raw = raw[raw["asof_date"].eq(raw.groupby("month")["asof_date"].transform("max"))].copy()
    for column in ("turnover_rate", "turnover_rate_f", "volume_ratio"):
        raw[column] = pd.to_numeric(raw[column], errors="coerce")
    raw["turnover_rate_percentile"] = raw.groupby("asof_date")["turnover_rate_f"].rank(pct=True, method="average")
    raw["turnover_liquidity_bucket"] = pd.cut(
        raw["turnover_rate_percentile"], [0, 0.3, 0.7, 1], labels=["low", "normal", "high"], include_lowest=True,
    ).astype("string")
    raw = raw.drop(columns="month")
    result = base.merge(raw, on=["asof_date", "ts_code"], how="left", validate="one_to_one")
    result["is_suspended_asof"] = result["market_data_age_days"].gt(0) & result["market_data_age_days"].notna()
    result["trading_status"] = np.select(
        [result["market_data_age_days"].isna(), result["is_suspended_asof"]], ["no_market_data", "suspended"], default="trading",
    )
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--start", default="2016-01-01")
    parser.add_argument("--end", default="2026-07-31")
    parser.add_argument("--output-dir", type=Path, default=OUTPUT_DIR)
    args = parser.parse_args()
    for path in (DAILY_BASIC, INDEX_MEMBERSHIP, STOCK_BASIC, ST_INTERVALS):
        if not path.is_file():
            raise SystemExit(f"required input missing: {path}")
    if not INDUSTRY_RAW_DIR.is_dir():
        raise SystemExit(f"required industry input missing: {INDUSTRY_RAW_DIR}")

    print("[1/6] Loading month-end size universe ...", flush=True)
    frame = load_month_end_size(DAILY_BASIC, STOCK_BASIC, args.start, args.end)
    print("[2/6] Attaching Shenwan L1/L2/L3 history ...", flush=True)
    frame = attach_industry_levels(frame)
    print("[3/6] Attaching security and board labels ...", flush=True)
    frame = attach_security_and_board(frame)
    print("[4/6] Attaching PIT ST/delist status ...", flush=True)
    frame = attach_st_status(frame)
    print("[5/6] Attaching trading and turnover labels ...", flush=True)
    frame = attach_trading_and_turnover(frame, args.start, args.end)
    print("[6/6] Attaching historical index membership and writing ...", flush=True)
    frame = attach_indexes(frame, INDEX_MEMBERSHIP).sort_values(["asof_date", "ts_code"]).reset_index(drop=True)
    summary = validate(frame)
    summary.update({
        "boards": {str(k): int(v) for k, v in frame["board"].value_counts().items()},
        "risk_status_counts": {str(k): int(v) for k, v in frame["risk_status"].value_counts().items()},
        "trading_status_counts": {str(k): int(v) for k, v in frame["trading_status"].value_counts().items()},
        "industry_l2_coverage": float(frame["l2_code"].notna().mean()),
        "industry_l3_coverage": float(frame["l3_code"].notna().mean()),
    })
    output = args.output_dir / "monthly_stock_classification.csv.gz"
    atomic_csv(frame, output)
    atomic_json({
        "dataset": "a_share_stock_classification_v2",
        "rules": {
            "size": "within-month free-float market-value percentile: small <=40%, mid 40%-80%, large >80%",
            "industry": "Shenwan L1/L2/L3 effective on asof_date; gap fills are explicitly marked",
            "board": "stock_basic exchange + market snapshot; board is treated as stable per security",
            "risk": "ST and delist-phase intervals effective on asof_date",
            "trading": "suspended when daily_basic has no record on the month-end trading day",
            "turnover": "month-end free-float turnover-rate percentile; not a 20-day amount capacity measure",
        },
        "inputs": [str(DAILY_BASIC), str(INDUSTRY_RAW_DIR), str(STOCK_BASIC), str(ST_INTERVALS), str(INDEX_MEMBERSHIP)],
        "summary": summary,
        "file": output.name,
        "sha256": sha256(output),
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
    }, args.output_dir / "manifest.json")
    print(json.dumps(summary, ensure_ascii=False, indent=2), flush=True)


if __name__ == "__main__":
    main()
