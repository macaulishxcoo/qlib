#!/usr/bin/env python3
"""Download resumable month-end CSI constituent snapshots from Tushare.

Each snapshot records the constituents and published index weights returned by
``index_weight`` on the last available trading day of a month.  The resulting
files are point-in-time classification inputs: membership must always be joined
using its snapshot date, never today's constituent list.

The default run is deliberately small (one month).  Use ``--max-months`` for
resumable batches; re-running skips successful snapshots recorded in the
request log.
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


INDEXES = {
    "csi300": "000300.SH",
    "csi500": "000905.SH",
    "csi800": "000906.SH",
    "csi1000": "000852.SH",
}
TOKEN_PATH = Path("/root/.config/tushare/token")


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


def load_token() -> str:
    token = os.environ.get("TUSHARE_TOKEN", "").strip()
    if not token and TOKEN_PATH.is_file():
        token = TOKEN_PATH.read_text(encoding="utf-8").strip()
    if not token:
        raise SystemExit("Tushare token missing: set TUSHARE_TOKEN or populate " + str(TOKEN_PATH))
    return token


def fetch_index_weight(pro, index_code: str, snapshot_date: str, retries: int, sleep_seconds: float) -> pd.DataFrame:
    """Fetch one snapshot with bounded retries for transient network errors."""
    for attempt in range(1, retries + 1):
        try:
            return pro.index_weight(index_code=index_code, start_date=snapshot_date, end_date=snapshot_date)
        except Exception:
            if attempt == retries:
                raise
            time.sleep(max(sleep_seconds, 1.0) * attempt)
    raise AssertionError("unreachable")


def month_end_trading_days(daily_basic: Path, start: str, end: str) -> pd.Series:
    dates = pd.read_csv(daily_basic, compression="gzip", usecols=["trade_date"], dtype={"trade_date": str})
    dates["date"] = pd.to_datetime(dates["trade_date"], format="%Y%m%d", errors="coerce")
    dates = dates.dropna(subset=["date"])
    dates = dates[dates["date"].between(pd.Timestamp(start), pd.Timestamp(end))]
    return dates.groupby(dates["date"].dt.to_period("M"))["date"].max().sort_values().reset_index(drop=True)


def finalize_dataset(output: Path, request_log: pd.DataFrame, start: str, end: str) -> None:
    successful = request_log[request_log["status"].eq("success")].drop_duplicates("snapshot_date", keep="last")
    parts = []
    for row in successful.itertuples(index=False):
        path = output / row.file
        if not path.is_file():
            raise SystemExit(f"successful snapshot file missing: {path}")
        parts.append(pd.read_csv(path, compression="gzip", dtype={"snapshot_date": str, "trade_date": str}))
    if not parts:
        return
    history = pd.concat(parts, ignore_index=True)
    history = history.rename(columns={"con_code": "ts_code"})
    history = history[["snapshot_date", "index_name", "index_code", "ts_code", "trade_date", "weight"]]
    history = history.sort_values(["snapshot_date", "index_name", "ts_code"])
    if history.duplicated(["snapshot_date", "index_name", "ts_code"]).any():
        raise SystemExit("duplicate index membership keys in consolidated history")
    normalized = output / "normalized/monthly_index_membership.csv.gz"
    atomic_csv(history, normalized)
    atomic_json({
        "dataset": "a_share_index_membership_pit_v1",
        "source": "Tushare Pro index_weight",
        "snapshot_rule": "last completed trading day of each calendar month",
        "indexes": INDEXES,
        "date_range_requested": {"start": start, "end": end},
        "successful_snapshots": int(history["snapshot_date"].nunique()),
        "rows": int(len(history)),
        "normalized_file": str(normalized.relative_to(output)),
        "normalized_sha256": sha256(normalized),
        "last_updated_utc": datetime.now(timezone.utc).isoformat(),
    }, output / "manifest.json")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--start", default="2016-01-01")
    parser.add_argument("--end", default="2026-08-31")
    parser.add_argument("--max-months", type=int, default=1, help="new months to fetch; omit for all pending months")
    parser.add_argument("--sleep-seconds", type=float, default=0.25)
    parser.add_argument("--retries", type=int, default=3)
    parser.add_argument("--output-dir", type=Path, default=Path("data/external/tushare/a_share_index_membership_pit_v1"))
    parser.add_argument("--daily-basic", type=Path, default=Path("data/external/tushare/a_share_daily_basic_pit_v1/normalized/daily_basic.csv.gz"))
    args = parser.parse_args()
    if args.max_months is not None and args.max_months < 1:
        raise SystemExit("--max-months must be positive or omitted")
    if args.retries < 1:
        raise SystemExit("--retries must be positive")
    if not args.daily_basic.is_file():
        raise SystemExit(f"daily_basic missing: {args.daily_basic}")

    output = args.output_dir
    raw_dir = output / "raw"
    manifest_path = output / "manifest.json"
    request_log_path = output / "request_log.csv.gz"
    request_log = pd.read_csv(request_log_path, compression="gzip", dtype=str) if request_log_path.is_file() else pd.DataFrame()
    if {"status", "snapshot_date"}.issubset(request_log.columns):
        completed = set(request_log.loc[request_log["status"].eq("success"), "snapshot_date"])
    else:
        completed = set()
    dates = month_end_trading_days(args.daily_basic, args.start, args.end)
    pending = [date for date in dates if date.strftime("%Y%m%d") not in completed]
    if args.max_months is not None:
        pending = pending[: args.max_months]
    print(f"available_months={len(dates)} completed={len(completed)} pending_this_run={len(pending)}")
    if not pending:
        if not request_log.empty:
            finalize_dataset(output, request_log, args.start, args.end)
        return

    pro = ts.pro_api(load_token())
    log_rows = []
    for date in pending:
        snapshot_date = date.strftime("%Y%m%d")
        parts = []
        try:
            for index_name, index_code in INDEXES.items():
                frame = fetch_index_weight(pro, index_code, snapshot_date, args.retries, args.sleep_seconds)
                if frame.empty:
                    raise RuntimeError(f"{index_code} returned no snapshot for {snapshot_date}")
                frame = frame.copy()
                frame["index_name"] = index_name
                frame["snapshot_date"] = snapshot_date
                parts.append(frame)
                time.sleep(args.sleep_seconds)
            snapshot = pd.concat(parts, ignore_index=True).sort_values(["index_name", "con_code"])
            target = raw_dir / f"{snapshot_date}.csv.gz"
            atomic_csv(snapshot, target)
            counts = snapshot.groupby("index_name")["con_code"].nunique().to_dict()
            if counts != {"csi300": 300, "csi500": 500, "csi800": 800, "csi1000": 1000}:
                raise RuntimeError(f"unexpected constituent counts: {counts}")
            log_rows.append({"snapshot_date": snapshot_date, "status": "success", "rows": len(snapshot), "file": str(target.relative_to(output)), "sha256": sha256(target), "error": "", "downloaded_at_utc": datetime.now(timezone.utc).isoformat()})
            request_log = pd.concat([request_log, pd.DataFrame([log_rows[-1]])], ignore_index=True)
            atomic_csv(request_log, request_log_path)
            print(f"{snapshot_date}: {counts}", flush=True)
        except Exception as exc:
            log_rows.append({"snapshot_date": snapshot_date, "status": "error", "rows": 0, "file": "", "sha256": "", "error": f"{type(exc).__name__}: {exc}", "downloaded_at_utc": datetime.now(timezone.utc).isoformat()})
            request_log = pd.concat([request_log, pd.DataFrame([log_rows[-1]])], ignore_index=True)
            atomic_csv(request_log, request_log_path)
            raise SystemExit(f"download stopped at {snapshot_date}: {type(exc).__name__}: {exc}")

    finalize_dataset(output, request_log, args.start, args.end)


if __name__ == "__main__":
    main()
