#!/usr/bin/env python3
"""Build the monthly A-share classification layer from local PIT inputs.

The output combines three independent dimensions at each completed month end:

* historical Shenwan industry effective at the snapshot date;
* cross-sectional free-float market-value percentile and size bucket;
* CSI 300/500/800/1000 constituent flags and published weights.

No network request is made by this script.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd


DAILY_BASIC = Path("data/external/tushare/a_share_daily_basic_pit_v1/normalized/daily_basic.csv.gz")
INDUSTRY_RAW_DIR = Path("data/external/tushare/a_share_style_pit_v1/raw/industry_member_all")
INDEX_MEMBERSHIP = Path("data/external/tushare/a_share_index_membership_pit_v1/normalized/monthly_index_membership.csv.gz")
STOCK_BASIC = Path("data/external/tushare/a_share_financial_pit_v1/full/raw/batch_0001/stock_basic_snapshot.csv.gz")
OUTPUT_DIR = Path("data/derived/a_share_stock_classification_v1")
INDEX_NAMES = ("csi300", "csi500", "csi800", "csi1000")


def atomic_csv(frame: pd.DataFrame, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    frame.to_csv(temp, index=False, compression="gzip")
    os.replace(temp, path)


def atomic_json(value: object, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temp.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(temp, path)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_month_end_size(path: Path, stock_basic_path: Path, start: str, end: str) -> pd.DataFrame:
    market = pd.read_csv(
        path,
        compression="gzip",
        usecols=["ts_code", "trade_date", "close", "free_share", "total_mv", "circ_mv"],
        dtype={"ts_code": str, "trade_date": str},
    )
    market["market_data_date"] = pd.to_datetime(market.pop("trade_date"), format="%Y%m%d", errors="coerce")
    market = market[market["market_data_date"].le(pd.Timestamp(end))].dropna(subset=["market_data_date"])
    numeric = ["close", "free_share", "total_mv", "circ_mv"]
    market[numeric] = market[numeric].apply(pd.to_numeric, errors="coerce")

    months = market[market["market_data_date"].between(pd.Timestamp(start), pd.Timestamp(end))].copy()
    months["month"] = months["market_data_date"].dt.to_period("M")
    month_ends = months.groupby("month")["market_data_date"].max().rename("asof_date").reset_index(drop=True)

    stocks = pd.read_csv(
        stock_basic_path,
        compression="gzip",
        usecols=["ts_code", "list_date", "delist_date"],
        dtype=str,
    ).drop_duplicates("ts_code", keep="last")
    stocks["list_date"] = pd.to_datetime(stocks["list_date"], format="%Y%m%d", errors="coerce")
    stocks["delist_date"] = pd.to_datetime(stocks["delist_date"], format="%Y%m%d", errors="coerce")
    universe = stocks.merge(month_ends.to_frame(), how="cross")
    universe = universe[
        universe["list_date"].le(universe["asof_date"])
        & (universe["delist_date"].isna() | universe["delist_date"].ge(universe["asof_date"]))
    ][["asof_date", "ts_code"]]

    # daily_basic omits suspended stocks. Use the latest observation known at
    # each month end and expose its age so downstream users can filter staleness.
    frame = pd.merge_asof(
        universe.sort_values(["asof_date", "ts_code"]),
        market.sort_values(["market_data_date", "ts_code"]),
        left_on="asof_date",
        right_on="market_data_date",
        by="ts_code",
        direction="backward",
        allow_exact_matches=True,
    )
    frame["market_data_age_days"] = (frame["asof_date"] - frame["market_data_date"]).dt.days
    frame["size_data_quality"] = np.select(
        [frame["market_data_date"].isna(), frame["market_data_age_days"].gt(31)],
        ["missing", "stale"],
        default="fresh",
    )
    frame["free_float_mv_10k_cny"] = frame["close"] * frame["free_share"]
    valid = frame["free_float_mv_10k_cny"].gt(0)
    frame["free_float_mv_percentile"] = np.nan
    frame.loc[valid, "free_float_mv_percentile"] = frame.loc[valid].groupby("asof_date")["free_float_mv_10k_cny"].rank(pct=True, method="average")
    frame["size_bucket"] = pd.cut(
        frame["free_float_mv_percentile"],
        bins=[0.0, 0.4, 0.8, 1.0],
        labels=["small", "mid", "large"],
        include_lowest=True,
    ).astype("string")
    return frame[[
        "asof_date", "ts_code", "market_data_date", "market_data_age_days", "size_data_quality", "close", "free_share",
        "free_float_mv_10k_cny", "free_float_mv_percentile", "size_bucket", "total_mv", "circ_mv",
    ]].sort_values(["asof_date", "ts_code"]).reset_index(drop=True)


def attach_industry(base: pd.DataFrame, raw_dir: Path) -> pd.DataFrame:
    files = sorted(raw_dir.glob("is_new_*.csv.gz"))
    if not files:
        raise SystemExit(f"industry raw files missing: {raw_dir}")
    industry = pd.concat(
        [
            pd.read_csv(
                path,
                compression="gzip",
                usecols=["ts_code", "l1_code", "l1_name", "in_date", "out_date"],
                dtype=str,
            )
            for path in files
        ],
        ignore_index=True,
    ).drop_duplicates()
    industry["industry_in_date"] = pd.to_datetime(industry.pop("in_date"), format="%Y%m%d", errors="coerce")
    industry["industry_out_date"] = pd.to_datetime(industry.pop("out_date"), format="%Y%m%d", errors="coerce")

    keys = base[["asof_date", "ts_code"]].reset_index(names="row_id")
    candidates = keys.merge(industry, on="ts_code", how="left")
    active = candidates[
        candidates["industry_in_date"].le(candidates["asof_date"])
        & (candidates["industry_out_date"].isna() | candidates["industry_out_date"].ge(candidates["asof_date"]))
    ].copy()
    active = active.sort_values(["row_id", "industry_in_date"]).drop_duplicates("row_id", keep="last")
    columns = ["l1_code", "l1_name", "industry_in_date", "industry_out_date"]
    result = base.join(active.set_index("row_id")[columns], how="left")
    result["industry_gap_fill"] = False
    missing = result["l1_code"].isna()
    if missing.any():
        # The bulk endpoint can expose an old interval's end and a much later
        # replacement start. Preserve the last known label, but mark it.
        prior = candidates[candidates["industry_in_date"].le(candidates["asof_date"])]
        prior = prior.sort_values(["row_id", "industry_in_date"]).drop_duplicates("row_id", keep="last")
        prior = prior.set_index("row_id")[columns]
        fill_ids = result.index[missing]
        for column in columns:
            result.loc[missing, column] = prior.reindex(fill_ids)[column].to_numpy()
        result.loc[missing & result["l1_code"].notna(), "industry_gap_fill"] = True
    return result


def attach_indexes(base: pd.DataFrame, path: Path) -> pd.DataFrame:
    membership = pd.read_csv(path, compression="gzip", dtype={"snapshot_date": str, "ts_code": str})
    membership["asof_date"] = pd.to_datetime(membership["snapshot_date"], format="%Y%m%d", errors="coerce")
    membership["weight"] = pd.to_numeric(membership["weight"], errors="coerce")
    flags = membership.assign(member=True).pivot_table(
        index=["asof_date", "ts_code"], columns="index_name", values="member", aggfunc="any", fill_value=False,
    )
    flags = flags.reindex(columns=INDEX_NAMES, fill_value=False).rename(columns=lambda name: f"is_{name}")
    weights = membership.pivot_table(
        index=["asof_date", "ts_code"], columns="index_name", values="weight", aggfunc="last",
    )
    weights = weights.reindex(columns=INDEX_NAMES).rename(columns=lambda name: f"{name}_weight")
    index_labels = flags.join(weights).reset_index()
    result = base.merge(index_labels, on=["asof_date", "ts_code"], how="left", validate="one_to_one")
    for name in INDEX_NAMES:
        result[f"is_{name}"] = result[f"is_{name}"].eq(True)
    return result


def validate(frame: pd.DataFrame) -> dict:
    if frame.duplicated(["asof_date", "ts_code"]).any():
        raise SystemExit("duplicate classification keys")
    index_counts = {}
    for name, expected in {"csi300": 300, "csi500": 500, "csi800": 800, "csi1000": 1000}.items():
        counts = frame.groupby("asof_date")[f"is_{name}"].sum()
        if not counts.eq(expected).all():
            bad = counts[counts.ne(expected)]
            raise SystemExit(f"unexpected {name} counts: {bad.head().to_dict()}")
        index_counts[name] = {"min": int(counts.min()), "max": int(counts.max())}
    valid_size = frame["free_float_mv_percentile"].notna()
    return {
        "rows": int(len(frame)),
        "months": int(frame["asof_date"].nunique()),
        "stocks": int(frame["ts_code"].nunique()),
        "start": str(frame["asof_date"].min().date()),
        "end": str(frame["asof_date"].max().date()),
        "industry_coverage": float(frame["l1_code"].notna().mean()),
        "industry_gap_fill_rows": int(frame["industry_gap_fill"].sum()),
        "size_coverage": float(valid_size.mean()),
        "size_data_quality_counts": {str(k): int(v) for k, v in frame["size_data_quality"].value_counts().items()},
        "size_bucket_counts": {str(k): int(v) for k, v in frame.loc[valid_size, "size_bucket"].value_counts().items()},
        "index_counts_per_month": index_counts,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--start", default="2016-01-01")
    parser.add_argument("--end", default="2026-07-31")
    parser.add_argument("--output-dir", type=Path, default=OUTPUT_DIR)
    args = parser.parse_args()
    for path in (DAILY_BASIC, INDEX_MEMBERSHIP, STOCK_BASIC):
        if not path.is_file():
            raise SystemExit(f"required input missing: {path}")
    if not INDUSTRY_RAW_DIR.is_dir():
        raise SystemExit(f"required industry input missing: {INDUSTRY_RAW_DIR}")

    print("[1/4] Building month-end free-float size labels ...", flush=True)
    frame = load_month_end_size(DAILY_BASIC, STOCK_BASIC, args.start, args.end)
    print(f"      rows={len(frame)} months={frame['asof_date'].nunique()}", flush=True)
    print("[2/4] Attaching historical Shenwan L1 industries ...", flush=True)
    frame = attach_industry(frame, INDUSTRY_RAW_DIR)
    print("[3/4] Attaching historical index membership ...", flush=True)
    frame = attach_indexes(frame, INDEX_MEMBERSHIP)
    frame = frame.sort_values(["asof_date", "ts_code"]).reset_index(drop=True)
    print("[4/4] Validating and writing ...", flush=True)
    summary = validate(frame)
    output = args.output_dir / "monthly_stock_classification.csv.gz"
    atomic_csv(frame, output)
    manifest = {
        "dataset": "a_share_stock_classification_v1",
        "classification_rules": {
            "size": "within-month free-float market-value percentile: small <=40%, mid 40%-80%, large >80%",
            "industry": "Shenwan L1 interval effective on asof_date",
            "index": "Tushare index_weight snapshot on asof_date",
        },
        "inputs": [str(DAILY_BASIC), str(INDUSTRY_RAW_DIR), str(INDEX_MEMBERSHIP), str(STOCK_BASIC)],
        "summary": summary,
        "file": str(output.name),
        "sha256": sha256(output),
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
    }
    atomic_json(manifest, args.output_dir / "manifest.json")
    print(json.dumps(summary, ensure_ascii=False, indent=2), flush=True)


if __name__ == "__main__":
    main()
