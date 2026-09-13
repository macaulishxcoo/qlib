#!/usr/bin/env python3
"""Rebuild the missing daily market data on this machine.

Two artifacts are absent here and both are required by the strategy scripts:

1. ``data/external/tushare/market_daily_v1/`` -- raw per-day OHLCV
2. ``~/.qlib/qlib_data/cn_data_2026``         -- the qlib binary store

This script reconstructs both from Tushare, following the adjustment convention
already documented in ``scripts/data_collector/update_daily_market_data_v1.py``::

    qlib_close      = ts_close * adj_factor * K     (K = 1.0 for a fresh build)
    qlib_open/high/low = ts_*  * adj_factor * K
    qlib_vwap       = amount * 10 / vol * adj_factor * K
    qlib_adjclose   = ts_close * adj_factor
    qlib_factor     = adj_factor * K

``K`` is a per-stock constant scale the original store calibrated against its own
binary (`close_last / adjclose_last`). A fresh build has nothing to calibrate
against, so K = 1.0: **returns are identical to the old store, absolute price
levels are not.** That only matters for the ¥5 minimum-cost floor, which is
irrelevant at the account sizes these backtests use.

Stages (each resumable):

    raw   download Tushare ``daily`` + ``adj_factor`` per trading day
    csv   pivot the raw files into one qlib-format CSV per instrument
    idx   download the CSI1000 (SH000852) index series
    bin   run scripts/dump_bin.py to produce the qlib binary store
    inst  write instruments/{all,csi300,csi500,csi800,csi1000}.txt
    all   everything, in order

Usage::

    python scripts/migration/build_market_data_v1.py --stage raw --start 2015-01-01
    python scripts/migration/build_market_data_v1.py --stage all
"""

from __future__ import annotations

import argparse
import gzip
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

REPO = Path(__file__).resolve().parents[2]
RAW_DIR = REPO / "data/external/tushare/market_daily_v1/raw"
CSV_DIR = REPO / "data/qlib_build/csv"
STORE_DIR = Path.home() / ".qlib/qlib_data/cn_data_2026"
TOKEN_PATH = Path.home() / ".config/tushare/token"
INDEX_MEMBERSHIP = REPO / "data/external/tushare/a_share_index_membership_pit_v1"

STOCK_FIELDS = ["open", "high", "low", "close", "volume", "amount", "change", "factor", "vwap", "adjclose"]
BENCHMARK_TS_CODE = "000852.SH"
BENCHMARK_QLIB = "SH000852"


def log(message: str) -> None:
    print(f"[{time.strftime('%H:%M:%S')}] {message}", flush=True)


def load_token() -> str:
    if TOKEN_PATH.is_file():
        token = TOKEN_PATH.read_text(encoding="utf-8").strip()
        if token:
            return token
    raise SystemExit(f"tushare token not found at {TOKEN_PATH}")


def api():
    import tushare as ts

    return ts.pro_api(load_token())


def fetch(pro, endpoint: str, attempts: int = 5, **kwargs) -> pd.DataFrame:
    """Call one Tushare endpoint with backoff; returns an empty frame on failure."""
    last: Exception | None = None
    for attempt in range(1, attempts + 1):
        try:
            frame = getattr(pro, endpoint)(**kwargs)
            if frame is not None and not frame.empty:
                return frame
            return pd.DataFrame()
        except Exception as exc:  # noqa: BLE001 - rate limits surface as generic errors
            last = exc
            time.sleep(min(2 ** attempt, 30))
    log(f"    {endpoint}{kwargs} failed after {attempts} attempts: {type(last).__name__}: {last}")
    return pd.DataFrame()


def trading_days(pro, start: str, end: str) -> list[str]:
    frame = fetch(pro, "trade_cal", exchange="SSE", start_date=start.replace("-", ""),
                  end_date=end.replace("-", ""), is_open="1")
    if frame.empty:
        raise SystemExit("could not fetch the trading calendar")
    return sorted(frame["cal_date"].astype(str))


# --------------------------------------------------------------------------- #
# stage: raw
# --------------------------------------------------------------------------- #


def stage_raw(pro, start: str, end: str, sleep: float, limit_days: int | None) -> None:
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    days = trading_days(pro, start, end)
    if limit_days:
        days = days[:limit_days]
    log(f"raw: {len(days)} trading days, {days[0]} .. {days[-1]} -> {RAW_DIR}")

    done = skipped = failed = 0
    for index, day in enumerate(days, 1):
        target = RAW_DIR / f"{day}.csv.gz"
        if target.exists():
            skipped += 1
            continue

        daily = fetch(pro, "daily", trade_date=day)
        if daily.empty:
            failed += 1
            log(f"  {day}: no daily rows")
            continue
        adj = fetch(pro, "adj_factor", trade_date=day)
        if not adj.empty:
            daily = daily.merge(adj[["ts_code", "adj_factor"]], on="ts_code", how="left")
        else:
            daily["adj_factor"] = np.nan

        daily.to_csv(target, index=False, compression="gzip")
        done += 1
        if index % 50 == 0 or index == len(days):
            log(f"  {index}/{len(days)}  new={done} cached={skipped} failed={failed}")
        if sleep:
            time.sleep(sleep)

    log(f"raw: done (new={done}, cached={skipped}, failed={failed})")


# --------------------------------------------------------------------------- #
# stage: csv
# --------------------------------------------------------------------------- #


def ts_code_to_qlib(ts_code: str) -> str | None:
    """``600000.SH`` -> ``SH600000``; returns None for anything unexpected."""
    if not isinstance(ts_code, str) or "." not in ts_code:
        return None
    number, suffix = ts_code.split(".", 1)
    if suffix not in {"SH", "SZ", "BJ"}:
        return None
    return f"{suffix}{number}"


def stage_csv(chunk_days: int = 120) -> None:
    """Pivot raw per-day files into one qlib-format CSV per instrument.

    Processes the raw files in chunks so peak memory stays bounded (the full
    history is ~11M rows x 12 columns).
    """
    CSV_DIR.mkdir(parents=True, exist_ok=True)
    # The stage appends chunk-by-chunk within a single run, so a previous run's
    # output must be cleared or the rows would be duplicated.
    stale = list(CSV_DIR.glob("*.csv"))
    if stale:
        log(f"csv: clearing {len(stale)} files from a previous run")
        for path in stale:
            path.unlink()
    files = sorted(RAW_DIR.glob("*.csv.gz"))
    if not files:
        raise SystemExit(f"no raw files under {RAW_DIR}; run --stage raw first")
    log(f"csv: {len(files)} raw day files -> {CSV_DIR}")

    # Accumulate per-instrument frames across chunks, flushing each chunk.
    for offset in range(0, len(files), chunk_days):
        batch = files[offset : offset + chunk_days]
        parts = []
        for path in batch:
            try:
                frame = pd.read_csv(path, compression="gzip",
                                    dtype={"ts_code": str, "trade_date": str})
            except Exception as exc:  # noqa: BLE001
                log(f"  skipping {path.name}: {type(exc).__name__}: {exc}")
                continue
            parts.append(frame)
        if not parts:
            continue
        frame = pd.concat(parts, ignore_index=True)

        frame["symbol"] = frame["ts_code"].map(ts_code_to_qlib)
        frame = frame.dropna(subset=["symbol"])
        frame["date"] = pd.to_datetime(frame["trade_date"], format="%Y%m%d", errors="coerce")
        frame = frame.dropna(subset=["date"])

        factor = (
            pd.to_numeric(frame["adj_factor"], errors="coerce").fillna(1.0)
            if "adj_factor" in frame.columns
            else pd.Series(1.0, index=frame.index)
        )
        volume = pd.to_numeric(frame["vol"], errors="coerce")
        amount = pd.to_numeric(frame["amount"], errors="coerce")

        out = pd.DataFrame(
            {
                "symbol": frame["symbol"].to_numpy(),
                "date": frame["date"].dt.strftime("%Y-%m-%d").to_numpy(),
                "open": (pd.to_numeric(frame["open"], errors="coerce") * factor).to_numpy(),
                "high": (pd.to_numeric(frame["high"], errors="coerce") * factor).to_numpy(),
                "low": (pd.to_numeric(frame["low"], errors="coerce") * factor).to_numpy(),
                "close": (pd.to_numeric(frame["close"], errors="coerce") * factor).to_numpy(),
                "volume": volume.to_numpy(),
                "amount": amount.to_numpy(),
                "change": pd.to_numeric(frame["change"], errors="coerce").to_numpy(),
                "factor": factor.to_numpy(),
                "vwap": (amount * 10.0 / volume.where(volume > 0)).to_numpy(),
                "adjclose": (pd.to_numeric(frame["close"], errors="coerce") * factor).to_numpy(),
            }
        ).dropna(subset=["close"])

        for symbol, group in out.groupby("symbol", sort=False):
            target = CSV_DIR / f"{symbol}.csv"
            group = group.drop(columns=["symbol"]).sort_values("date")
            header = not target.exists()
            group.to_csv(target, mode="a", header=header, index=False)

        log(f"  csv: {min(offset + chunk_days, len(files))}/{len(files)} day files folded in")
        del frame, out, parts

    count = len(list(CSV_DIR.glob("*.csv")))
    log(f"csv: {count} instrument files written")


# --------------------------------------------------------------------------- #
# stage: idx
# --------------------------------------------------------------------------- #


def stage_idx(pro, start: str, end: str) -> None:
    """Benchmark index series, written as a normal instrument CSV."""
    CSV_DIR.mkdir(parents=True, exist_ok=True)
    frame = fetch(pro, "index_daily", ts_code=BENCHMARK_TS_CODE,
                  start_date=start.replace("-", ""), end_date=end.replace("-", ""))
    if frame.empty:
        log("idx: no index rows returned")
        return
    frame["date"] = pd.to_datetime(frame["trade_date"], format="%Y%m%d", errors="coerce")
    frame = frame.dropna(subset=["date"]).sort_values("date")
    volume = pd.to_numeric(frame["vol"], errors="coerce")
    amount = pd.to_numeric(frame["amount"], errors="coerce")
    out = pd.DataFrame(
        {
            "date": frame["date"].dt.strftime("%Y-%m-%d"),
            "open": pd.to_numeric(frame["open"], errors="coerce"),
            "high": pd.to_numeric(frame["high"], errors="coerce"),
            "low": pd.to_numeric(frame["low"], errors="coerce"),
            "close": pd.to_numeric(frame["close"], errors="coerce"),
            "volume": volume,
            "amount": amount,
            "change": pd.to_numeric(frame["change"], errors="coerce"),
            "factor": 1.0,
            "vwap": (amount * 10.0 / volume.where(volume > 0)).fillna(frame["close"]),
            "adjclose": pd.to_numeric(frame["close"], errors="coerce"),
        }
    ).dropna(subset=["close"])
    target = CSV_DIR / f"{BENCHMARK_QLIB}.csv"
    out.to_csv(target, index=False)
    log(f"idx: {len(out)} rows {out['date'].iloc[0]} .. {out['date'].iloc[-1]} -> {target}")


# --------------------------------------------------------------------------- #
# stage: bin
# --------------------------------------------------------------------------- #


def stage_bin(max_workers: int = 8) -> None:
    from qlib.utils import code_to_fname  # noqa: F401  (import check only)

    sys.path.insert(0, str(REPO / "scripts"))
    from dump_bin import DumpDataAll  # noqa: PLC0415

    STORE_DIR.mkdir(parents=True, exist_ok=True)
    log(f"bin: dumping {CSV_DIR} -> {STORE_DIR}")
    DumpDataAll(
        data_path=str(CSV_DIR),
        qlib_dir=str(STORE_DIR),
        freq="day",
        max_workers=max_workers,
        date_field_name="date",
        file_suffix=".csv",
        symbol_field_name="symbol",
        exclude_fields="symbol",
        include_fields=",".join(STOCK_FIELDS),
    ).dump()

    for name in ("calendars", "features", "instruments"):
        path = STORE_DIR / name
        size = sum(f.stat().st_size for f in path.rglob("*") if f.is_file()) if path.exists() else 0
        log(f"  {name}: {size / 1e6:.1f} MB")


# --------------------------------------------------------------------------- #
# stage: inst
# --------------------------------------------------------------------------- #


def stage_inst() -> None:
    """Write the index-membership instrument lists qlib expects."""
    inst_dir = STORE_DIR / "instruments"
    inst_dir.mkdir(parents=True, exist_ok=True)

    all_path = inst_dir / "all.txt"
    if all_path.exists():
        log(f"inst: all.txt already present ({all_path.stat().st_size / 1e6:.1f} MB)")
    else:
        rows = []
        for csv_path in sorted(CSV_DIR.glob("*.csv")):
            dates = pd.read_csv(csv_path, usecols=["date"])["date"]
            if dates.empty:
                continue
            rows.append(f"{csv_path.stem}\t{dates.min()}\t{dates.max()}")
        all_path.write_text("\n".join(rows) + "\n", encoding="utf-8")
        log(f"inst: all.txt written with {len(rows)} instruments")

    # Index membership: the normalized dataset holds per-day constituents.
    candidates = sorted(INDEX_MEMBERSHIP.rglob("*.csv.gz")) if INDEX_MEMBERSHIP.exists() else []
    if not candidates:
        log("inst: no index-membership dataset found; only all.txt written")
        return
    log(f"inst: membership sources: {[p.name for p in candidates][:5]}")
    frames = []
    for path in candidates:
        try:
            frames.append(pd.read_csv(path, compression="gzip", dtype=str))
        except Exception as exc:  # noqa: BLE001
            log(f"  could not read {path.name}: {type(exc).__name__}: {exc}")
    if not frames:
        return
    membership = pd.concat(frames, ignore_index=True)
    log(f"inst: membership columns: {list(membership.columns)[:12]}")

    code_col = next((c for c in ("con_code", "ts_code", "code") if c in membership.columns), None)
    index_col = next((c for c in ("index_code", "index_name", "l1_code") if c in membership.columns), None)
    date_col = next((c for c in ("trade_date", "in_date", "date") if c in membership.columns), None)
    if not (code_col and index_col and date_col):
        log("inst: could not identify membership columns; skipping index lists")
        return

    for index_code in sorted(membership[index_col].dropna().unique()):
        subset = membership[membership[index_col] == index_code]
        rows = []
        for symbol, group in subset.groupby(code_col):
            qlib_symbol = ts_code_to_qlib(symbol)
            if qlib_symbol is None:
                continue
            dates = pd.to_datetime(group[date_col], errors="coerce").dropna()
            if dates.empty:
                continue
            rows.append(f"{qlib_symbol}\t{dates.min():%Y-%m-%d}\t{dates.max():%Y-%m-%d}")
        if not rows:
            continue
        name = str(index_code).lower().replace(".", "")
        target = inst_dir / f"{name}.txt"
        target.write_text("\n".join(sorted(set(rows))) + "\n", encoding="utf-8")
        log(f"  wrote {target.name} with {len(set(rows))} entries")


# --------------------------------------------------------------------------- #


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--stage", default="all",
                        choices=["raw", "csv", "idx", "bin", "inst", "all"])
    parser.add_argument("--start", default="2015-01-01")
    parser.add_argument("--end", default=time.strftime("%Y-%m-%d"))
    parser.add_argument("--sleep", type=float, default=0.0, help="seconds between API calls")
    parser.add_argument("--limit-days", type=int, default=0, help="only the first N trading days (debug)")
    parser.add_argument("--workers", type=int, default=8)
    args = parser.parse_args()

    log(f"repo    : {REPO}")
    log(f"raw dir : {RAW_DIR}")
    log(f"csv dir : {CSV_DIR}")
    log(f"store   : {STORE_DIR}")
    log(f"range   : {args.start} .. {args.end}")

    need_api = args.stage in {"raw", "idx", "all"}
    pro = api() if need_api else None

    if args.stage in {"raw", "all"}:
        stage_raw(pro, args.start, args.end, args.sleep, args.limit_days or None)
    # `csv` clears its output directory, so it must run BEFORE `idx` writes the
    # benchmark CSV into it -- otherwise the index file is deleted again.
    if args.stage in {"csv", "all"}:
        stage_csv()
    if args.stage in {"idx", "all"}:
        stage_idx(pro, args.start, args.end)
    if args.stage in {"bin", "all"}:
        stage_bin(args.workers)
    if args.stage in {"inst", "all"}:
        stage_inst()

    log("done")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
