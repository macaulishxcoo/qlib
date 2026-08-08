#!/usr/bin/env python3
"""Incremental daily market-data updater for the main Qlib store (cn_data_2026).

What it does
------------
Appends the latest trading days from Tushare into ``~/.qlib/qlib_data/cn_data_2026``
(the same store consumed by the Alpha158 LightGBM pipeline) plus auxiliary files
needed by Stage-2 signal filtering (turnover, float market cap, limit list, stock
basics). It is the Stage-1 data-pipeline piece of the ROADMAP.

The Qlib store uses *backward-adjusted* prices, which was verified empirically:
``qlib_close = tushare_close_raw * qlib_factor`` and
``qlib_vwap = (amount*10/vol) * qlib_factor`` (factor changes on ex-dates).
Appending raw Tushare prices directly would therefore create a discontinuity at
every ex-date.  This script re-derives the adjusted prices for every new day:

    factor_q   = ts_adj_factor * K_stock          # K_stock calibrated per stock
    close      = ts_close      * factor_q
    open/high/low = ts_*       * factor_q
    vwap       = amount*10/vol * factor_q
    adjclose   = ts_close      * ts_adj_factor    # == close / K_stock
    change     = ts_pct_chg / 100
    volume     = ts_vol   (raw lots)
    amount     = ts_amount (raw 1e3 CNY)

``K_stock = close_bin_last / adjclose_bin_last`` is measured from the existing
binary store itself (zero extra API calls) and cached to ``aux/k_factor_stock.csv``.
Each stock has its own K (verified: sh600000 0.0391, sz000001 0.0025, sh600519 0.0281),
so a single global ratio would be wrong.

Index bars (SH000xxx / SZ399xxx, used only as backtest benchmark) come from
Tushare ``index_daily``; their ``factor`` is a constant and prices are NOT adjusted.

Binary append uses the official ``DumpDataUpdate`` from ``scripts/dump_bin.py``;
suspended stocks (no row on a given day) are backfilled with NaN by its reindex,
and newly listed stocks are dumped in full automatically.

Usage
-----
    conda activate qlib
    # incremental update for all trading days since the store's last calendar day
    python scripts/data_collector/update_daily_market_data_v1.py
    # limit to a specific end date (e.g. dry run with one new day)
    python scripts/data_collector/update_daily_market_data_v1.py --end-date 2026-07-24

crontab example (run Mon-Fri after close; adjust times to your Tushare availability):
    # qlib daily market update, 17:35 CST
    35 17 * * 1-5  cd /home/xiaocong/worksapces/qlib && \
        /home/xiaocong/anaconda3/envs/qlib/bin/python \
        scripts/data_collector/update_daily_market_data_v1.py \
        >> /home/xiaocong/worksapces/qlib/output/logs_static/daily_update.log 2>&1
"""

import argparse
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd
import tushare as ts

TOKEN_PATH = Path("/root/.config/tushare/token")
DEFAULT_QLIB_DIR = Path.home() / ".qlib/qlib_data/cn_data_2026"
DEFAULT_RAW_DIR = Path("/home/xiaocong/worksapces/qlib/data/external/tushare/market_daily_v1")

# Fields present in the Qlib binary store; the raw CSV uses the same names so that
# DumpDataUpdate appends them directly.
STOCK_BIN_FIELDS = ["open", "high", "low", "close", "volume", "amount", "change", "factor", "vwap", "adjclose"]
DUMP_EXCLUDE_FIELDS = "symbol,date"

# Tushare daily() has no vwap: vwap = amount(1e3 CNY) * 10 / vol(lots of 100).
# Index volume unit differs from stocks, so index vwap is filled with close instead.
VWAP_SCALE = 10.0

MAX_RETRY = 3


def load_token() -> str:
    """Prefer TUSHARE_TOKEN env var, fall back to the token file."""
    token = os.environ.get("TUSHARE_TOKEN")
    if token:
        return token.strip()
    if TOKEN_PATH.is_file():
        token = TOKEN_PATH.read_text(encoding="utf-8").strip()
        if token:
            return token
    raise SystemExit("Tushare token missing: set TUSHARE_TOKEN or populate " + str(TOKEN_PATH))


def ts_code_to_qlib(ts_code: str) -> str:
    """'600000.SH' -> 'SH600000'; supports SH/SZ/BJ. BJ codes appear as 92xxxxx etc."""
    code, exchange = ts_code.split(".")
    return f"{exchange.upper()}{code}"


def read_store_calendar(qlib_dir: Path) -> pd.DatetimeIndex:
    path = qlib_dir / "calendars" / "day.txt"
    return pd.DatetimeIndex(pd.to_datetime(pd.read_csv(path, header=None)[0]))


def read_field_tail(features_dir: Path, field: str, n: int = 2000) -> np.ndarray:
    """Read the tail of one daily bin (header + last n values) without loading it all."""
    path = features_dir / f"{field}.day.bin"
    if not path.is_file():
        return np.array([], dtype="<f4")
    size = path.stat().st_size
    if size <= 4:
        return np.array([], dtype="<f4")
    nbytes = min(size, 4 * (n + 1))
    with path.open("rb") as fp:
        fp.seek(size - nbytes)
        raw = fp.read(nbytes)
    arr = np.frombuffer(raw, dtype="<f4")
    # The file's first 4 bytes are start_index; if we seeked past it, we only have values.
    return arr


def last_non_nan(features_dir: Path, field: str) -> float:
    """Last non-NaN value of a field's bin (scanning the tail backwards)."""
    arr = read_field_tail(features_dir, field, n=2000)
    for v in arr[::-1]:
        if not np.isnan(v):
            return float(v)
    return np.nan


def calibrate_k_stock(qlib_dir: Path, cache_path: Path, refresh: bool) -> pd.DataFrame:
    """K_stock = close_bin_last / adjclose_bin_last for every store instrument.

    Reads only the tail of each stock's close/adjclose bins, so a full 6k-stock
    store is calibrated in seconds without any Tushare request.
    """
    if cache_path.is_file() and not refresh:
        return pd.read_csv(cache_path, dtype={"symbol": str, "k": float})

    all_txt = qlib_dir / "instruments" / "all.txt"
    if not all_txt.is_file():
        raise SystemExit(f"instruments/all.txt not found in {qlib_dir}")
    symbols = pd.read_csv(all_txt, sep="\t", header=None, usecols=[0])[0].tolist()

    rows = []
    skipped = 0
    for sym in symbols:
        fd = qlib_dir / "features" / sym.lower()
        if not fd.is_dir():
            skipped += 1
            continue
        close_last = last_non_nan(fd, "close")
        adjclose_last = last_non_nan(fd, "adjclose")
        if np.isnan(close_last) or np.isnan(adjclose_last) or adjclose_last == 0:
            skipped += 1
            continue
        rows.append({"symbol": sym, "k": close_last / adjclose_last})
    table = pd.DataFrame(rows)
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    table.to_csv(cache_path, index=False)
    print(f"[calibrate] K_stock table: {len(table)} rows (skipped {skipped}) -> {cache_path}")
    return table


def fetch_with_retry(pro, query: str, **kwargs) -> pd.DataFrame:
    """Single Tushare request with retry; raises on persistent failure."""
    for attempt in range(MAX_RETRY):
        try:
            return pro.query(query, **kwargs)
        except Exception as exc:  # noqa: BLE001 - surface any API failure
            if attempt == MAX_RETRY - 1:
                raise
            time.sleep(2 * (attempt + 1))
    raise RuntimeError("unreachable")


def build_stock_rows(daily: pd.DataFrame, adj: pd.DataFrame, k_map: dict) -> pd.DataFrame:
    """Convert one day's stock daily + adj_factor into adjusted rows for raw CSV."""
    d = daily.merge(adj[["ts_code", "adj_factor"]], on="ts_code", how="left")
    d["symbol"] = d["ts_code"].map(ts_code_to_qlib)
    d["date"] = pd.to_datetime(d["trade_date"]).dt.strftime("%Y-%m-%d")
    d["k"] = d["symbol"].map(k_map).fillna(1.0)  # new stocks default to K=1
    d["factor"] = d["adj_factor"] * d["k"]
    d["close"] = d["close"] * d["factor"]
    d["open"] = d["open"] * d["factor"]
    d["high"] = d["high"] * d["factor"]
    d["low"] = d["low"] * d["factor"]
    d["vwap"] = d["amount"] * VWAP_SCALE / d["vol"] * d["factor"]
    d["adjclose"] = d["close"] / d["k"]
    d["change"] = d["pct_chg"] / 100.0
    d["volume"] = d["vol"]
    return d[["symbol", "date"] + STOCK_BIN_FIELDS]


def build_index_rows(idx: pd.DataFrame, existing_factors: dict) -> pd.DataFrame:
    """Convert one day's index bars to rows; factor stays constant, prices raw."""
    idx = idx.copy()
    idx["symbol"] = idx["ts_code"].map(ts_code_to_qlib)
    idx["date"] = pd.to_datetime(idx["trade_date"]).dt.strftime("%Y-%m-%d")
    idx["factor"] = idx["symbol"].map(existing_factors)
    idx["adjclose"] = idx["close"] / idx["factor"]
    idx["change"] = idx["pct_chg"] / 100.0
    idx["vwap"] = idx["close"]  # index volume unit differs; benchmark uses close only
    idx["volume"] = idx["vol"]
    return idx[["symbol", "date"] + STOCK_BIN_FIELDS]


def append_rows(raw_dir: Path, rows: pd.DataFrame) -> None:
    """Append one day's rows to per-symbol CSV files under raw_dir.

    Rows already present for the same symbol+date are skipped so that re-running
    after a partial failure never duplicates data (DumpDataUpdate also drops
    duplicate dates, but keeping the raw CSV clean matters for audits).
    """
    for symbol, grp in rows.groupby("symbol", sort=False):
        path = raw_dir / f"{symbol.lower()}.csv"
        if path.exists():
            existing = pd.read_csv(path, usecols=["date"])
            known = set(existing["date"].astype(str))
        else:
            known = set()
        fresh = grp[~grp["date"].astype(str).isin(known)]
        if fresh.empty:
            continue
        fresh.to_csv(path, mode="a", header=not path.exists(), index=False)


def fetch_existing_index_factors(qlib_dir: Path, calendar: pd.DatetimeIndex) -> dict:
    """Constant factor value per index, taken from its bin tail (last non-NaN)."""
    out = {}
    all_txt = qlib_dir / "instruments" / "all.txt"
    symbols = pd.read_csv(all_txt, sep="\t", header=None, usecols=[0])[0].tolist()
    for sym in symbols:
        if sym.startswith(("SH000", "SZ399")):
            fd = qlib_dir / "features" / sym.lower()
            if fd.is_dir():
                val = last_non_nan(fd, "factor")
                if not np.isnan(val):
                    out[sym] = val
    return out


def get_recent_trading_days(pro, end_date: str, start_after: str) -> list:
    """Trading days in (start_after, end_date] from Tushare trade_cal (exchange=SSE)."""
    cal = fetch_with_retry(
        pro,
        "trade_cal",
        exchange="SSE",
        start_date=start_after.replace("-", ""),
        end_date=end_date.replace("-", ""),
    )
    cal = cal[cal["is_open"] == 1]
    days = sorted(pd.to_datetime(cal["cal_date"]).dt.strftime("%Y-%m-%d").tolist())
    return [d for d in days if d > start_after]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--qlib-dir", type=Path, default=DEFAULT_QLIB_DIR)
    parser.add_argument("--raw-dir", type=Path, default=DEFAULT_RAW_DIR)
    parser.add_argument("--end-date", default=None, help="Last trading day to fetch (default: latest available)")
    parser.add_argument("--sleep-seconds", type=float, default=0.15)
    parser.add_argument("--refresh-k", action="store_true", help="Re-calibrate K_stock from the store")
    parser.add_argument("--dry-run", action="store_true", help="Print the plan without fetching")
    args = parser.parse_args()

    raw_dir = args.raw_dir
    aux_dir = raw_dir / "aux"
    raw_dir.mkdir(parents=True, exist_ok=True)
    aux_dir.mkdir(parents=True, exist_ok=True)

    calendar = read_store_calendar(args.qlib_dir)
    last_store_day = calendar[-1].strftime("%Y-%m-%d")
    print(f"[store] calendar last day: {last_store_day} ({len(calendar)} days)")

    pro = ts.pro_api(load_token())
    end_date = args.end_date or datetime.now().strftime("%Y-%m-%d")

    days = get_recent_trading_days(pro, end_date, last_store_day)
    if not days:
        print("[skip] no new trading days after", last_store_day)
        return
    print(f"[plan] {len(days)} new trading days: {days[0]} .. {days[-1]}")

    # Resume: drop days already checkpointed (not yet dumped to bin).
    checkpoint = aux_dir / "completed_dates.csv"
    if checkpoint.is_file():
        done = set(pd.read_csv(checkpoint, header=None)[0].tolist())
        days = [d for d in days if d not in done]
        if not days:
            print("[skip] all days already checkpointed")
            return
        print(f"[resume] {len(days)} days remaining after checkpoint")

    if args.dry_run:
        print("[dry-run] would fetch", len(days), "days")
        return

    k_table = calibrate_k_stock(args.qlib_dir, aux_dir / "k_factor_stock.csv", args.refresh_k)
    k_map = dict(zip(k_table["symbol"], k_table["k"]))
    existing_index_factors = fetch_existing_index_factors(args.qlib_dir, calendar)

    completed, failed = [], []
    for day in days:
        day_compact = day.replace("-", "")
        try:
            daily = fetch_with_retry(pro, "daily", trade_date=day_compact)
            if daily.empty:
                print(f"[{day}] daily empty, skip")
                failed.append(day)
                continue
            adj = fetch_with_retry(pro, "adj_factor", trade_date=day_compact)
            stock_rows = build_stock_rows(daily, adj, k_map)
            append_rows(raw_dir, stock_rows)

            idx = fetch_with_retry(pro, "index_daily", trade_date=day_compact)
            if not idx.empty:
                idx = idx[idx["ts_code"].isin(
                    {s[2:] + "." + s[:2] for s in existing_index_factors}
                )]
                index_rows = build_index_rows(idx, existing_index_factors)
                append_rows(raw_dir, index_rows)
            completed.append(day)
            print(f"[{day}] stocks={len(stock_rows)} indices={0 if idx.empty else len(idx)} OK")
        except Exception as exc:  # noqa: BLE001
            failed.append(day)
            print(f"[{day}] FAILED: {exc}")
        time.sleep(args.sleep_seconds)

    # Checkpoint is persisted only after a successful dump+repair (below), so a
    # failed dump causes the next run to retry rather than skip the days.
    if failed:
        pd.Series(failed).to_csv(aux_dir / "failed_dates.csv", index=False, header=False)
        print(f"[warn] failed days: {failed} (see aux/failed_dates.csv)")

    print(f"[fetch] done: {len(completed)} days OK, {len(failed)} failed")

    # ---- Dump raw CSVs into the Qlib binary store (incremental) ----
    if completed:
        try:
            import sys as _sys

            _sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # scripts/
            from dump_bin import DumpDataUpdate

            updater = DumpDataUpdate(
                data_path=str(raw_dir),
                qlib_dir=str(args.qlib_dir),
                freq="day",
                max_workers=16,
                date_field_name="date",
                symbol_field_name="symbol",
                file_suffix=".csv",
                exclude_fields=DUMP_EXCLUDE_FIELDS,
            )
            updater.dump()
            print(f"[dump] appended {len(completed)} days into {args.qlib_dir}")
        except Exception as exc:  # noqa: BLE001
            print(f"[dump] FAILED: {exc}\nRaw CSV kept in {raw_dir}; re-run after fixing.")
            sys.exit(1)

        # DumpDataUpdate appends raw floats and assumes a row for every calendar
        # day; suspended stocks leave the window shifted (off-by-N) or missing.
        # Rebuild the appended window for every stock from the raw CSVs so that
        # suspended days become NaN at the correct positions.
        repair_module = Path(__file__).with_name("repair_market_data_update_v1.py")
        if repair_module.is_file():
            from repair_market_data_update_v1 import repair_stock

            new_calendar = pd.DatetimeIndex(
                pd.to_datetime(pd.read_csv(args.qlib_dir / "calendars" / "day.txt", header=None)[0])
            )
            win_start = pd.Timestamp(days[0])
            win_dates = new_calendar[
                (new_calendar >= win_start) & (new_calendar <= pd.Timestamp(completed[-1]))
            ]
            repaired = 0
            for csv_path in sorted(raw_dir.glob("*.csv")):
                fd = args.qlib_dir / "features" / csv_path.stem.lower()
                if not fd.is_dir():
                    continue
                rdf = pd.read_csv(csv_path)
                rdf["date"] = pd.to_datetime(rdf["date"])
                if rdf["date"].max() < win_start:
                    continue
                repair_stock(fd, rdf, new_calendar, win_dates, win_start)
                repaired += 1
            print(f"[repair] rebuilt appended window for {repaired} stocks (suspended-day fix)")
        else:
            print("[warn] repair_market_data_update_v1.py not found; suspended-day fix skipped")

        # Mark the days as completed only now that the store is consistent.
        prev = []
        if checkpoint.is_file():
            prev = pd.read_csv(checkpoint, header=None)[0].tolist()
        pd.Series(prev + completed).drop_duplicates().to_csv(checkpoint, index=False, header=False)
        print(f"[checkpoint] recorded {len(completed)} days in aux/completed_dates.csv")

    # ---- Post-conditions ----
    if completed:
        new_cal = read_store_calendar(args.qlib_dir)
        print(f"[verify] store calendar now ends {new_cal[-1].strftime('%Y-%m-%d')} ({len(new_cal)} days)")
        if new_cal[-1].strftime("%Y-%m-%d") != completed[-1]:
            print("[warn] store last day != fetched last day; check aux/failed_dates.csv")

    print(f"[{datetime.now(timezone.utc).isoformat()}] update finished")


if __name__ == "__main__":
    main()
