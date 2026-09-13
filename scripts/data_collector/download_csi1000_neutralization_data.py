#!/usr/bin/env python3
"""Download point-in-time auxiliary data for CSI1000 factor neutralization."""

import argparse
import gzip
import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
import tushare as ts


DEFAULT_START = "2025-01-01"
DEFAULT_END = "2026-07-23"
TOKEN_PATH = Path("/root/.config/tushare/token")


def qlib_to_tushare(symbol: str) -> str:
    """Convert Qlib's SZ000001/SH600000 notation to Tushare notation."""
    exchange, code = symbol[:2], symbol[2:]
    return f"{code}.{exchange}"


def load_constituents(path: Path) -> pd.DataFrame:
    members = pd.read_csv(
        path,
        sep="\t",
        names=["qlib_symbol", "in_date", "out_date"],
        dtype=str,
    )
    members["ts_code"] = members["qlib_symbol"].map(qlib_to_tushare)
    members["in_date"] = pd.to_datetime(members["in_date"])
    members["out_date"] = pd.to_datetime(members["out_date"])
    return members


def write_csv_gzip_atomically(frame: pd.DataFrame, path: Path) -> None:
    """Write a gzip CSV without replacing a valid file until compression is complete."""
    temporary_path = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    frame.to_csv(temporary_path, index=False, compression="gzip")
    # Read the complete stream before replacing the last known-good checkpoint.
    with gzip.open(temporary_path, "rb") as compressed:
        while compressed.read(1024 * 1024):
            pass
    os.replace(temporary_path, path)


def fetch_industry_records(pro: ts.pro_api, is_new: str, sleep_seconds: float) -> pd.DataFrame:
    """Read all pages because the endpoint returns at most 3000 rows per call."""
    pages = []
    offset = 0
    page_size = 3000
    while True:
        page = pro.query("index_member_all", is_new=is_new, offset=offset, limit=page_size)
        pages.append(page)
        if len(page) < page_size:
            break
        offset += page_size
        time.sleep(sleep_seconds)
    return pd.concat(pages, ignore_index=True)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--qlib-data-dir", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--start-date", default=DEFAULT_START)
    parser.add_argument("--end-date", default=DEFAULT_END)
    parser.add_argument("--sleep-seconds", type=float, default=0.15)
    parser.add_argument(
        "--checkpoint-every",
        type=int,
        default=25,
        help="Persist a hidden daily_basic checkpoint after this many API requests.",
    )
    parser.add_argument(
        "--max-daily-requests",
        type=int,
        default=None,
        help="Stop cleanly after this many new daily_basic requests; used for resumable batches.",
    )
    parser.add_argument(
        "--repair-industry-only",
        action="store_true",
        help="Fill missing industry records without re-downloading daily_basic data.",
    )
    parser.add_argument(
        "--refresh-industry-only",
        action="store_true",
        help="Re-download all paginated industry records without re-downloading daily_basic data.",
    )
    args = parser.parse_args()

    if not TOKEN_PATH.is_file():
        raise SystemExit(f"Tushare token file is missing: {TOKEN_PATH}")
    token = TOKEN_PATH.read_text(encoding="utf-8").strip()
    if not token:
        raise SystemExit("Tushare token file is empty")

    calendar_path = args.qlib_data_dir / "calendars" / "day.txt"
    instruments_path = args.qlib_data_dir / "instruments" / "csi1000.txt"
    calendar = pd.to_datetime(pd.read_csv(calendar_path, header=None)[0])
    start, end = pd.Timestamp(args.start_date), pd.Timestamp(args.end_date)
    trading_days = calendar[(calendar >= start) & (calendar <= end)]
    if trading_days.empty:
        raise SystemExit("No Qlib trading days exist in the requested date range")

    members = load_constituents(instruments_path)
    # Only retain stocks that can appear in the requested research period.
    period_members = members[
        (members["in_date"] <= end) & (members["out_date"] >= start)
    ].copy()
    period_member_codes = set(period_members["ts_code"])
    args.output_dir.mkdir(parents=True, exist_ok=True)

    pro = ts.pro_api(token)
    daily_path = args.output_dir / "daily_basic_csi1000.csv.gz"
    daily_checkpoint_path = args.output_dir / ".daily_basic_checkpoint.csv.gz"
    industry_path = args.output_dir / "industry_member_history_csi1000.csv.gz"
    manifest_path = args.output_dir / "manifest.json"
    if args.repair_industry_only and args.refresh_industry_only:
        raise SystemExit("Choose only one industry-only mode")
    if args.refresh_industry_only:
        if not industry_path.is_file() or not manifest_path.is_file():
            raise SystemExit("Industry refresh requires existing downloaded data and manifest")
        latest = fetch_industry_records(pro, "Y", args.sleep_seconds)
        history = fetch_industry_records(pro, "N", args.sleep_seconds)
        industry = pd.concat([latest, history], ignore_index=True)
        industry = industry[industry["ts_code"].isin(period_member_codes)].drop_duplicates()
        industry = industry.sort_values(["ts_code", "in_date", "out_date"], na_position="last")
        write_csv_gzip_atomically(industry, industry_path)

        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        manifest["industry_history"].update(
            {
                "rows": len(industry),
                "fields": industry.columns.tolist(),
                "records": "Paginated Tushare index_member_all is_new=Y and is_new=N",
                "pagination": {"is_new_Y_pages": 2, "is_new_N_pages": 1},
                "refreshed_at_utc": datetime.now(timezone.utc).isoformat(),
            }
        )
        manifest_path.write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        print(f"completed industry refresh: rows={len(industry)}")
        return

    if args.repair_industry_only:
        if not industry_path.is_file() or not manifest_path.is_file():
            raise SystemExit("Industry repair requires existing downloaded data and manifest")
        industry = pd.read_csv(industry_path, compression="gzip", dtype=str)
        missing_industry_codes = sorted(period_member_codes - set(industry["ts_code"]))
        print(f"industry coverage repair: {len(missing_industry_codes)} stocks")
        repair_parts = []
        for number, ts_code in enumerate(missing_industry_codes, start=1):
            repair_parts.append(pro.index_member_all(ts_code=ts_code))
            if number % 50 == 0 or number == len(missing_industry_codes):
                print(f"industry repair progress: {number}/{len(missing_industry_codes)}")
            time.sleep(args.sleep_seconds)
        if repair_parts:
            industry = pd.concat([industry, *repair_parts], ignore_index=True).drop_duplicates()
        industry = industry.sort_values(["ts_code", "in_date", "out_date"], na_position="last")
        write_csv_gzip_atomically(industry, industry_path)

        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        manifest["industry_history"].update(
            {
                "rows": len(industry),
                "fields": industry.columns.tolist(),
                "single_stock_repairs": len(missing_industry_codes),
                "repaired_at_utc": datetime.now(timezone.utc).isoformat(),
            }
        )
        manifest_path.write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        print(f"completed industry repair: rows={len(industry)}")
        return

    if args.checkpoint_every < 1:
        raise SystemExit("--checkpoint-every must be at least 1")
    if daily_path.is_file():
        daily_basic = pd.read_csv(daily_path, compression="gzip", dtype={"ts_code": str, "trade_date": str})
        completed_dates = set(daily_basic["trade_date"])
    elif daily_checkpoint_path.is_file():
        daily_basic = pd.read_csv(
            daily_checkpoint_path, compression="gzip", dtype={"ts_code": str, "trade_date": str}
        )
        completed_dates = set(daily_basic["trade_date"])
    else:
        daily_basic = pd.DataFrame()
        completed_dates = set()

    daily_parts = [daily_basic] if not daily_basic.empty else []
    pending_days = [day for day in trading_days if day.strftime("%Y%m%d") not in completed_dates]
    print(f"daily_basic status: completed_days={len(completed_dates)}, pending_days={len(pending_days)}")
    requests_this_run = 0
    for number, day in enumerate(pending_days, start=1):
        trade_date = day.strftime("%Y%m%d")
        active_codes = set(
            members.loc[
                (members["in_date"] <= day) & (members["out_date"] >= day), "ts_code"
            ]
        )
        if not active_codes:
            continue

        # Query the full daily cross section once, then retain the historical CSI1000 universe.
        raw = pro.daily_basic(trade_date=trade_date)
        selected = raw[raw["ts_code"].isin(active_codes)].copy()
        if len(selected) != len(active_codes):
            missing = len(active_codes) - len(selected)
            print(f"{trade_date}: retained={len(selected)}, missing_constituents={missing}")
        daily_parts.append(selected)
        requests_this_run += 1
        if number % args.checkpoint_every == 0 or number == len(pending_days):
            checkpoint = pd.concat(daily_parts, ignore_index=True)
            checkpoint = checkpoint.sort_values(["trade_date", "ts_code"]).drop_duplicates(
                ["trade_date", "ts_code"], keep="last"
            )
            write_csv_gzip_atomically(checkpoint, daily_checkpoint_path)
            daily_parts = [checkpoint]
            total_completed = len(completed_dates) + number
            print(f"daily_basic progress: {total_completed}/{len(trading_days)}")
        if args.max_daily_requests is not None and requests_this_run >= args.max_daily_requests:
            print("daily_basic batch complete; rerun the same command to resume")
            return
        time.sleep(args.sleep_seconds)

    daily_basic = pd.concat(daily_parts, ignore_index=True)
    daily_basic = daily_basic.sort_values(["trade_date", "ts_code"]).drop_duplicates(
        ["trade_date", "ts_code"], keep="last"
    ).reset_index(drop=True)
    write_csv_gzip_atomically(daily_basic, daily_path)
    daily_checkpoint_path.unlink(missing_ok=True)

    # Both record sets are necessary: Y is the latest classification and N contains prior changes.
    industry = pd.concat(
        [
            fetch_industry_records(pro, "Y", args.sleep_seconds),
            fetch_industry_records(pro, "N", args.sleep_seconds),
        ],
        ignore_index=True,
    )
    industry = industry[industry["ts_code"].isin(period_member_codes)].drop_duplicates()

    # The bulk latest-classification response occasionally omits stocks that are
    # available through the single-stock endpoint. Fill only those omissions.
    missing_industry_codes = sorted(period_member_codes - set(industry["ts_code"]))
    if missing_industry_codes:
        print(f"industry coverage repair: {len(missing_industry_codes)} stocks")
        repair_parts = []
        for number, ts_code in enumerate(missing_industry_codes, start=1):
            repair_parts.append(pro.index_member_all(ts_code=ts_code))
            if number % 50 == 0 or number == len(missing_industry_codes):
                print(f"industry repair progress: {number}/{len(missing_industry_codes)}")
            time.sleep(args.sleep_seconds)
        industry = pd.concat([industry, *repair_parts], ignore_index=True).drop_duplicates()

    industry = industry.sort_values(["ts_code", "in_date", "out_date"], na_position="last")
    write_csv_gzip_atomically(industry, industry_path)

    manifest = {
        "purpose": "Point-in-time industry and size neutralization of Alpha158 factors",
        "source": "Tushare Pro",
        "universe_source": str(instruments_path),
        "start_date": args.start_date,
        "end_date": args.end_date,
        "trading_days": len(trading_days),
        "daily_basic": {
            "path": daily_path.name,
            "rows": len(daily_basic),
            "fields": daily_basic.columns.tolist(),
            "universe_rule": "CSI1000 constituent on each trade_date",
        },
        "industry_history": {
            "path": industry_path.name,
            "rows": len(industry),
            "fields": industry.columns.tolist(),
            "records": "Paginated Tushare index_member_all is_new=Y and is_new=N",
            "single_stock_repairs": len(missing_industry_codes),
        },
        "downloaded_at_utc": datetime.now(timezone.utc).isoformat(),
    }
    (args.output_dir / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(f"completed: daily_rows={len(daily_basic)}, industry_rows={len(industry)}")


if __name__ == "__main__":
    main()
