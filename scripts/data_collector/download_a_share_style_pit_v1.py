#!/usr/bin/env python3
"""Collect auditable monthly PIT industry and free-float-size control data.

This collector only downloads industry membership history and the daily_basic
cross section needed before each monthly rebalance.  It does not read returns
or calculate financial signals, labels, models, or backtests.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
import tushare as ts


START_MONTH = "2014-01"
END_MONTH = "2025-06"
ENDPOINT = "daily_basic"
INDUSTRY_ENDPOINT = "index_member_all"


def atomic_csv(frame: pd.DataFrame, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    frame.to_csv(temporary, index=False, compression="gzip" if path.suffix == ".gz" else None)
    os.replace(temporary, path)


def atomic_json(value: object, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(temporary, path)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def load_token() -> str:
    token = os.environ.get("TUSHARE_TOKEN", "").strip()
    if not token:
        token_path = Path.home() / ".config/tushare/token"
        if token_path.is_file():
            token = token_path.read_text(encoding="utf-8").strip()
    if not token:
        raise SystemExit("TUSHARE_TOKEN is not configured")
    return token


def monthly_asof_grid(calendar_path: Path) -> pd.DataFrame:
    calendar = pd.to_datetime(pd.read_csv(calendar_path, header=None)[0], errors="coerce").dropna().sort_values().drop_duplicates()
    months = pd.period_range(START_MONTH, END_MONTH, freq="M")
    rows = []
    for month in months:
        days = calendar[calendar.dt.to_period("M").eq(month)]
        if days.empty:
            raise SystemExit(f"Qlib calendar has no trading day for {month}")
        rebalance = days.iloc[0]
        earlier = calendar[calendar.lt(rebalance)]
        if earlier.empty:
            raise SystemExit(f"Qlib calendar has no preceding day for {rebalance.date()}")
        rows.append({"month": str(month), "rebalance_date": rebalance.strftime("%Y-%m-%d"), "asof_date": earlier.iloc[-1].strftime("%Y-%m-%d")})
    return pd.DataFrame(rows)


def load_universe(snapshot: Path, full_index: Path) -> pd.DataFrame:
    stock_basic = pd.read_csv(snapshot, compression="gzip", dtype=str)
    verified = pd.read_csv(full_index, compression="gzip", dtype=str)
    codes = set(verified["ts_code"])
    universe = stock_basic[stock_basic["ts_code"].isin(codes)].copy()
    if len(universe) != 5385 or universe["ts_code"].nunique() != 5385:
        raise SystemExit("frozen financial PIT universe does not match stock_basic snapshot")
    universe["list_date"] = pd.to_datetime(universe["list_date"], errors="coerce")
    universe["delist_date"] = pd.to_datetime(universe["delist_date"], errors="coerce")
    return universe


def active_codes(universe: pd.DataFrame, asof: pd.Timestamp) -> set[str]:
    active = universe[universe["list_date"].le(asof) & (universe["delist_date"].isna() | universe["delist_date"].gt(asof))]
    return set(active["ts_code"])


def fetch_industry_pages(pro, is_new: str, sleep_seconds: float) -> pd.DataFrame:
    pages = []
    offset = 0
    page_size = 3000
    while True:
        page = pro.query(INDUSTRY_ENDPOINT, is_new=is_new, offset=offset, limit=page_size)
        pages.append(page)
        if len(page) < page_size:
            break
        offset += page_size
        time.sleep(sleep_seconds)
    return pd.concat(pages, ignore_index=True) if pages else pd.DataFrame()


def recover_daily_logs(raw_daily: Path, logs: pd.DataFrame) -> pd.DataFrame:
    """Recover atomically written responses if a process stopped before log flush."""
    completed = set(logs.loc[logs.get("status", pd.Series(dtype=str)).eq("success"), "asof_date"]) if not logs.empty else set()
    recovered = []
    for path in sorted(raw_daily.glob("*.csv.gz")):
        asof = path.stem.removesuffix(".csv")
        if asof in completed:
            continue
        frame = pd.read_csv(path, compression="gzip", dtype=str)
        recovered.append({"endpoint": ENDPOINT, "asof_date": asof, "status": "success", "rows": len(frame), "attempt": "recovered", "request_started_at_utc": "", "error": "", "raw_sha256": sha256_file(path)})
    if recovered:
        logs = pd.concat([logs, pd.DataFrame(recovered)], ignore_index=True)
    return logs


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[2])
    parser.add_argument("--qlib-data-dir", type=Path, default=Path.home() / ".qlib/qlib_data/cn_data_2026")
    parser.add_argument("--sleep-seconds", type=float, default=0.3)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    if args.sleep_seconds < 0:
        raise SystemExit("sleep-seconds must be non-negative")
    root = args.root.resolve()
    data_root = root / "data/external/tushare/a_share_style_pit_v1"
    raw_daily = data_root / "raw/daily_basic"
    raw_industry = data_root / "raw/industry_member_all"
    normalized = data_root / "normalized"
    manifests = data_root / "manifests"
    audit = root / "output/data_audits/a_share_style_pit_v1"
    snapshot = root / "data/external/tushare/a_share_financial_pit_v1/full/raw/batch_0001/stock_basic_snapshot.csv.gz"
    full_index = root / "output/data_audits/a_share_financial_pit_v1/full/full_audit_v1/frozen_universe_index.csv.gz"
    grid = monthly_asof_grid(args.qlib_data_dir / "calendars/day.txt")
    universe = load_universe(snapshot, full_index)
    print(f"months={len(grid)} universe={len(universe)} first_asof={grid.asof_date.iloc[0]} last_asof={grid.asof_date.iloc[-1]}")
    if args.dry_run:
        return

    atomic_csv(grid, normalized / "monthly_rebalance_grid.csv.gz")
    reference = {"stock_basic_snapshot": str(snapshot.relative_to(root)), "stock_basic_snapshot_sha256": sha256_file(snapshot), "frozen_universe_index": str(full_index.relative_to(root)), "frozen_universe_index_sha256": sha256_file(full_index), "universe_companies": len(universe)}
    atomic_json(reference, data_root / "raw/stock_basic_snapshot_reference.json")

    log_path = audit / "request_log.csv"
    logs = pd.read_csv(log_path, dtype=str) if log_path.is_file() else pd.DataFrame()
    logs = recover_daily_logs(raw_daily, logs)
    atomic_csv(logs, log_path)
    pro = ts.pro_api(load_token())

    for _, row in grid.iterrows():
        asof = row.asof_date
        target = raw_daily / f"{asof}.csv.gz"
        existing = logs[(logs.get("endpoint", pd.Series(dtype=str)) == ENDPOINT) & (logs.get("asof_date", pd.Series(dtype=str)) == asof) & (logs.get("status", pd.Series(dtype=str)) == "success")]
        if target.is_file() and not existing.empty:
            continue
        started = datetime.now(timezone.utc).isoformat()
        try:
            frame = pro.daily_basic(trade_date=asof.replace("-", ""))
            frame = frame.copy()
            frame["request_started_at_utc"] = started
            frame["source_endpoint"] = ENDPOINT
            frame["asof_date"] = asof
            atomic_csv(frame, target)
            entry = {"endpoint": ENDPOINT, "asof_date": asof, "status": "success", "rows": len(frame), "attempt": "1", "request_started_at_utc": started, "error": "", "raw_sha256": sha256_file(target)}
            logs = pd.concat([logs, pd.DataFrame([entry])], ignore_index=True)
            atomic_csv(logs, log_path)
            print(f"daily_basic {asof}: rows={len(frame)}", flush=True)
        except Exception as exc:
            entry = {"endpoint": ENDPOINT, "asof_date": asof, "status": "error", "rows": 0, "attempt": "1", "request_started_at_utc": started, "error": f"{type(exc).__name__}: {exc}", "raw_sha256": ""}
            logs = pd.concat([logs, pd.DataFrame([entry])], ignore_index=True)
            atomic_csv(logs, log_path)
            raise SystemExit(f"daily_basic blocked at {asof}: {entry['error']}")
        time.sleep(args.sleep_seconds)

    for is_new in ("Y", "N"):
        target = raw_industry / f"is_new_{is_new}.csv.gz"
        if target.is_file():
            continue
        started = datetime.now(timezone.utc).isoformat()
        try:
            frame = fetch_industry_pages(pro, is_new, args.sleep_seconds)
            frame["request_started_at_utc"] = started
            frame["source_endpoint"] = INDUSTRY_ENDPOINT
            frame["is_new_request"] = is_new
            atomic_csv(frame, target)
            print(f"industry is_new={is_new}: rows={len(frame)}", flush=True)
        except Exception as exc:
            raise SystemExit(f"industry history blocked for is_new={is_new}: {type(exc).__name__}: {exc}")

    raw_y = pd.read_csv(raw_industry / "is_new_Y.csv.gz", compression="gzip", dtype=str)
    raw_n = pd.read_csv(raw_industry / "is_new_N.csv.gz", compression="gzip", dtype=str)
    industry = pd.concat([raw_y, raw_n], ignore_index=True)
    industry = industry[industry["ts_code"].isin(set(universe["ts_code"]))].drop_duplicates().sort_values(["ts_code", "in_date", "out_date"], na_position="last")
    atomic_csv(industry, normalized / "industry_l1_effective_intervals.csv.gz")

    monthly_size = []
    for _, row in grid.iterrows():
        asof = pd.Timestamp(row.asof_date)
        active = active_codes(universe, asof)
        frame = pd.read_csv(raw_daily / f"{row.asof_date}.csv.gz", compression="gzip", dtype=str)
        selected = frame[frame["ts_code"].isin(active)].copy()
        selected["rebalance_date"] = row.rebalance_date
        selected["source_file"] = f"{row.asof_date}.csv.gz"
        monthly_size.append(selected)
    size = pd.concat(monthly_size, ignore_index=True)
    close = pd.to_numeric(size.get("close"), errors="coerce")
    free_share = pd.to_numeric(size.get("free_share"), errors="coerce")
    size["free_float_market_value"] = close * free_share
    size["size_control"] = pd.NA
    valid = size["free_float_market_value"].gt(0)
    size.loc[valid, "size_control"] = size.loc[valid, "free_float_market_value"].map(__import__("math").log)
    atomic_csv(size, normalized / "monthly_free_float_size.csv.gz")

    manifest_path = manifests / "manifest.json"
    # A manifest cannot hash itself: its own contents change when hashes are written.
    files = {
        str(path.relative_to(data_root)): {"bytes": path.stat().st_size, "sha256": sha256_file(path)}
        for path in sorted(data_root.rglob("*"))
        if path.is_file() and path != manifest_path
    }
    atomic_json({"dataset": "a_share_style_pit_v1", "months": len(grid), "universe_companies": len(universe), "source": "Tushare Pro", "files": files}, manifests / "manifest.json")
    print("download completed; run audit_a_share_style_pit_v1.py before use", flush=True)


if __name__ == "__main__":
    main()
