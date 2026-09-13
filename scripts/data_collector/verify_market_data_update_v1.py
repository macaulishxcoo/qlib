#!/usr/bin/env python3
"""Verify Tushare market-data conventions against the existing Qlib binary store.

Purpose
-------
Before appending incremental daily bars to ``~/.qlib/qlib_data/cn_data_2026`` we must
prove that three conventions hold for the data already in the store:

1. ``close`` is the RAW (unadjusted) close.  Tushare ``daily.close`` is raw, so a
   direct append keeps the historical scale consistent.
2. ``vwap`` is consistent with Tushare ``amount``/``vol``.  Tushare's ``daily``
   endpoint has no vwap field, so the updater must compute it as
   ``vwap = amount * 10 / vol`` (amount in 1e3 CNY, vol in lots of 100 shares).
3. ``factor`` is a cumulative adjustment factor whose ratio to Tushare
   ``adj_factor`` is (approximately) constant.  The updater continues ``factor``
   from Tushare's ``adj_factor`` with the measured ratio.

Verification is done on a sample stock by joining the Qlib binary values for a
recent window against Tushare API responses for the same dates.

Usage
-----
    conda activate qlib
    python scripts/data_collector/verify_market_data_update_v1.py \
        --symbol sh600000 \
        --qlib-dir ~/.qlib/qlib_data/cn_data_2026 \
        --start-date 2026-06-01 --end-date 2026-07-23

The script exits non-zero if any convention fails.
"""

import argparse
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd
import tushare as ts

TOKEN_PATH = Path("/root/.config/tushare/token")


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


def qlib_to_tushare(symbol: str) -> str:
    """Convert Qlib notation (SH600000 / SZ000001 / BJ430017) to Tushare notation."""
    symbol = symbol.upper()
    exchange, code = symbol[:2], symbol[2:]
    exchange = {"SH": "SH", "SZ": "SZ", "BJ": "BJ"}[exchange]
    return f"{code}.{exchange}"


def read_calendars(qlib_dir: Path) -> pd.DatetimeIndex:
    path = qlib_dir / "calendars" / "day.txt"
    return pd.DatetimeIndex(pd.to_datetime(pd.read_csv(path, header=None)[0]))


def read_field_bin(features_dir: Path, field: str, calendar: pd.DatetimeIndex) -> pd.Series:
    """Read a single daily field of one stock from the Qlib binary store.

    The first float32 is the start index into the global calendar; every value
    after that maps 1:1 to a calendar date.
    """
    path = features_dir / f"{field}.day.bin"
    if not path.is_file():
        raise SystemExit(f"Missing field file: {path}")
    arr = np.fromfile(path, dtype="<f4")
    start_index = int(arr[0])
    values = arr[1:]
    dates = calendar[start_index : start_index + len(values)]
    return pd.Series(values, index=dates, name=field)


def verify_symbol(pro, symbol: str, qlib_dir: Path, start: str, end: str) -> None:
    """Join Qlib bin values against Tushare for one symbol and report convention checks."""
    calendar = read_calendars(qlib_dir)
    features_dir = qlib_dir / "features" / symbol.lower()
    ts_code = qlib_to_tushare(symbol)
    print(f"\n=== {symbol} ({ts_code}) window {start} ~ {end} ===")

    daily = pro.query(
        "daily", ts_code=ts_code, start_date=start.replace("-", ""), end_date=end.replace("-", "")
    )
    if daily.empty:
        raise SystemExit(f"No Tushare daily rows for {ts_code} in window")
    daily["trade_date"] = pd.to_datetime(daily["trade_date"])
    daily = daily.set_index("trade_date").sort_index()

    adj = pro.query(
        "adj_factor", ts_code=ts_code, start_date=start.replace("-", ""), end_date=end.replace("-", "")
    )
    if adj.empty:
        raise SystemExit(f"No Tushare adj_factor rows for {ts_code} in window")
    adj["trade_date"] = pd.to_datetime(adj["trade_date"])
    adj = adj.set_index("trade_date").sort_index()

    bin_close = read_field_bin(features_dir, "close", calendar)
    bin_vwap = read_field_bin(features_dir, "vwap", calendar)
    bin_factor = read_field_bin(features_dir, "factor", calendar)

    joined = pd.DataFrame(
        {
            "ts_close": daily["close"],
            "ts_adj_factor": adj["adj_factor"],
        }
    ).join(bin_close).join(bin_vwap).join(bin_factor)
    joined = joined.dropna()

    failed = []

    # 1. close must match the raw close reported by Tushare.
    close_diff = (joined["close"] - joined["ts_close"]).abs().max()
    close_ok = close_diff < 1e-4
    print(f"[close] max |qlib_close - ts_close| = {close_diff:.6f} -> {'OK' if close_ok else 'FAIL'}")
    if not close_ok:
        failed.append("close")

    # 2. vwap must equal amount * 10 / vol.
    vwap_implied = joined["ts_close"].index.to_series().map(
        lambda d: (daily.loc[d, "amount"] * 10.0 / daily.loc[d, "vol"]) if daily.loc[d, "vol"] else np.nan
    )
    vwap_implied = pd.Series(vwap_implied.values, index=joined.index, name="vwap_implied")
    vwap_diff = (joined["vwap"] - vwap_implied).abs().max()
    vwap_ok = vwap_diff < 1e-2
    print(f"[vwap] max |qlib_vwap - amount*10/vol| = {vwap_diff:.4f} -> {'OK' if vwap_ok else 'FAIL'}")
    if not vwap_ok:
        failed.append("vwap")

    # 3. factor must be a constant ratio of Tushare adj_factor.
    ratio = joined["factor"] / joined["ts_adj_factor"]
    ratio_min, ratio_max = ratio.min(), ratio.max()
    factor_ok = ratio_max - ratio_min < 1e-4
    print(
        f"[factor] ratio qlib_factor/ts_adj_factor: min={ratio_min:.8f} max={ratio_max:.8f} "
        f"-> {'OK' if factor_ok else 'FAIL (not constant)'}"
    )
    if not factor_ok:
        failed.append("factor")

    print(f"\n=== RESULT: {'ALL PASS' if not failed else 'FAILED: ' + ', '.join(failed)} ===")
    if failed:
        sys.exit(1)


def check_update(pro, qlib_dir: Path, end_date: str) -> None:
    """Post-update self check: read the appended day through Qlib and compare with
    the Tushare raw prices re-adjusted by the store's K_stock convention.

    Only meaningful right after ``update_daily_market_data_v1.py`` appended a day.
    """
    import qlib
    from qlib.config import REG_CN

    qlib.init(provider_uri=str(qlib_dir), region=REG_CN)
    from qlib.data import D

    cal = read_calendars(qlib_dir)
    if cal[-1].strftime("%Y-%m-%d") != end_date:
        print(f"[warn] store ends {cal[-1].strftime('%Y-%m-%d')}, expected {end_date}")

    samples = ["sh600000", "sz000001", "sh600519", "bj430017"]
    compact = end_date.replace("-", "")
    failed = []

    for sym in samples:
        ts_code = qlib_to_tushare(sym)
        daily = pro.query("daily", ts_code=ts_code, start_date=compact, end_date=compact)
        if daily.empty:
            print(f"[{sym}] no tushare row on {end_date}, skip")
            continue
        adj = pro.query("adj_factor", ts_code=ts_code, start_date=compact, end_date=compact)
        ts_close = float(daily["close"].iloc[0])
        ts_factor = float(adj["adj_factor"].iloc[0])
        ts_vwap_implied = float(daily["amount"].iloc[0]) * 10.0 / float(daily["vol"].iloc[0])

        # K_stock: read from the store directly (tail of close/adjclose bins).
        fd = qlib_dir / "features" / sym.lower()
        close_last = None
        for v in np.fromfile(fd / "close.day.bin", dtype="<f4")[1:][::-1]:
            if not np.isnan(v):
                close_last = v
                break
        adjclose_last = None
        for v in np.fromfile(fd / "adjclose.day.bin", dtype="<f4")[1:][::-1]:
            if not np.isnan(v):
                adjclose_last = v
                break
        k = close_last / adjclose_last

        ql = D.features([sym], ["$close", "$open", "$high", "$low", "$vwap", "$factor", "$adjclose", "$volume"],
                        start_time=end_date, end_time=end_date)
        if ql.empty:
            print(f"[{sym}] qlib has no row on {end_date}")
            failed.append(sym)
            continue
        q_close = float(ql["$close"].iloc[0])
        q_vwap = float(ql["$vwap"].iloc[0])
        q_factor = float(ql["$factor"].iloc[0])

        exp_close = ts_close * ts_factor * k
        exp_vwap = ts_vwap_implied * ts_factor * k
        close_ok = abs(q_close - exp_close) / exp_close < 1e-3
        vwap_ok = abs(q_vwap - exp_vwap) / exp_vwap < 1e-3
        factor_ok = abs(q_factor - ts_factor * k) / (ts_factor * k) < 1e-4
        print(
            f"[{sym}] close q={q_close:.4f} exp={exp_close:.4f} {'OK' if close_ok else 'FAIL'} | "
            f"vwap q={q_vwap:.4f} exp={exp_vwap:.4f} {'OK' if vwap_ok else 'FAIL'} | "
            f"factor q={q_factor:.6f} exp={ts_factor * k:.6f} {'OK' if factor_ok else 'FAIL'} | "
            f"K={k:.6f}"
        )
        if not (close_ok and vwap_ok and factor_ok):
            failed.append(sym)

    # Index check: benchmark SH000852 close must match index_daily close.
    idx = pro.query("index_daily", ts_code="000852.SH", start_date=compact, end_date=compact)
    if not idx.empty:
        q_idx = D.features(["sh000852"], ["$close"], start_time=end_date, end_time=end_date)
        exp_idx = float(idx["close"].iloc[0])
        if not q_idx.empty:
            q_idx_v = float(q_idx["$close"].iloc[0])
            idx_ok = abs(q_idx_v - exp_idx) / exp_idx < 1e-3
            print(f"[sh000852] close q={q_idx_v:.4f} exp={exp_idx:.4f} {'OK' if idx_ok else 'FAIL'}")
            if not idx_ok:
                failed.append("sh000852")

    print(f"\n=== UPDATE CHECK: {'ALL PASS' if not failed else 'FAILED: ' + ', '.join(failed)} ===")
    if failed:
        sys.exit(1)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--symbol", default="sh600000")
    parser.add_argument("--qlib-dir", type=Path, default=Path.home() / ".qlib/qlib_data/cn_data_2026")
    parser.add_argument("--start-date", default="2026-06-01")
    parser.add_argument("--end-date", default="2026-07-23")
    parser.add_argument("--check-update", action="store_true",
                        help="Post-update self check: validate the appended day via Qlib.")
    args = parser.parse_args()

    pro = ts.pro_api(load_token())
    if args.check_update:
        check_update(pro, args.qlib_dir, args.end_date)
    else:
        verify_symbol(pro, args.symbol, args.qlib_dir, args.start_date, args.end_date)
    print(f"[{datetime.now(timezone.utc).isoformat()}] verification finished")


if __name__ == "__main__":
    main()
