#!/usr/bin/env python3
"""Download global index daily bars from Tushare `index_global` (protocol v1).

Dataset: data/external/tushare/us_index_v1/
  raw/ts_code/year.csv.gz   per (index, year) raw slices
  normalized/us_index.csv.gz  full concat, cols:
      ts_code, trade_date(datetime), open, close, high, low, pre_close,
      pct_chg, swing, vol, amount
  manifest.json   per-index coverage + validation results

Frozen in research/protocols/us_market_overnight_conduction_protocol_v1.md §4.1:
  codes = SPX IXIC DJI RUT XIN9 HSI HKTECH ; start 2010-01-01
  validation: no dup (ts_code,trade_date); pct_chg vs close consistent (<0.1pp);
  per-index-year rows in [220, 262]; |pct_chg|>12% listed as flagged (not fatal).

Usage (conda activate qlib):
    python scripts/data_collector/download_us_index_v1.py
    python scripts/data_collector/download_us_index_v1.py --start 2010-01-01
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

ROOT = Path(__file__).resolve().parent.parent.parent
DATA_DIR = ROOT / "data/external/tushare/us_index_v1"
RAW_DIR = DATA_DIR / "raw"
NORM_DIR = DATA_DIR / "normalized"

TOKEN_PATH = Path("/root/.config/tushare/token")
CODES = ["SPX", "IXIC", "DJI", "RUT", "XIN9", "HSI", "HKTECH"]
START = "2010-01-01"
FIELDS = ["ts_code", "trade_date", "open", "close", "high", "low",
          "pre_close", "change", "pct_chg", "swing", "vol", "amount"]
RETRY = 5
SLEEP = 6.5  # index_global rate limit: 10 calls/min for this account
CHUNK = 4000  # max rows per call (unused by fetch; kept as documented const)
CHUNK_YEARS = 5  # date-chunk width: 5y ~ <=1300 rows/call


def get_token() -> str:
    token = os.environ.get("TUSHARE_TOKEN")
    if token:
        return token.strip()
    if TOKEN_PATH.is_file():
        return TOKEN_PATH.read_text(encoding="utf-8").strip()
    raise RuntimeError("TUSHARE_TOKEN env var or token file required")


def fetch(pro, code: str, start: str, end: str) -> pd.DataFrame:
    """Fetch full range in date chunks (<=~1300 rows each, no limit/offset).

    Do NOT use limit/offset pagination: tushare's row ordering is unstable
    (observed: offset drift truncates the newest segment), but date-range
    calls are deterministic.
    """
    frames = []
    cur = pd.Timestamp(start)
    last = pd.Timestamp(end)
    while cur <= last:
        seg_end = min(cur + pd.DateOffset(years=CHUNK_YEARS) - pd.Timedelta(days=1), last)
        got = None
        for attempt in range(1, RETRY + 1):
            try:
                got = pro.index_global(ts_code=code,
                                       start_date=cur.strftime("%Y%m%d"),
                                       end_date=seg_end.strftime("%Y%m%d"))
                break
            except Exception as e:  # noqa: BLE001 - tushare raises generic errors
                print(f"  [retry {attempt}/{RETRY}] {code} {cur.date()}~{seg_end.date()}: {e}", flush=True)
                time.sleep(SLEEP * attempt)
        if got is None:
            raise RuntimeError(f"fetch failed: {code} {cur}~{seg_end}")
        if got is not None and not got.empty:
            frames.append(got)
        cur = seg_end + pd.Timedelta(days=1)
        time.sleep(SLEEP)
    return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--start", default=START, help="earliest date (YYYY-MM-DD)")
    parser.add_argument("--end", default=None, help="latest date (default today)")
    args = parser.parse_args()

    end = args.end or datetime.now(timezone.utc).strftime("%Y-%m-%d")
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    NORM_DIR.mkdir(parents=True, exist_ok=True)

    import tushare as ts
    pro = ts.pro_api(get_token())

    years = list(range(int(args.start[:4]), int(end[:4]) + 1))
    manifest = {"dataset": "us_index_v1", "purpose": "美股/全球指数日线（隔夜传导研究）",
                "source": "tushare index_global", "start_date": args.start,
                "end_date": end, "created_at_utc": datetime.now(timezone.utc).isoformat(),
                "codes": {}}

    for code in CODES:
        print(f"[{code}] fetching {args.start}~{end} (rate-limit paced) ...", flush=True)
        df = fetch(pro, code, args.start, end)
        if df is None or df.empty:
            print(f"  -> EMPTY", flush=True)
            manifest["codes"][code] = {"rows": 0, "ok": False}
            continue
        # normalize
        df = df[df["trade_date"].notna()].copy()
        df["trade_date"] = pd.to_datetime(df["trade_date"].astype(str), format="%Y%m%d", errors="coerce")
        df = df.dropna(subset=["trade_date"]).sort_values("trade_date").reset_index(drop=True)
        # normalize (index_global returns: ts_code,trade_date,open,close,high,low,
        # pre_close,change,pct_chg,swing,vol -- no 'amount'; convert defensively)
        for col in ("open", "close", "high", "low", "pre_close", "change", "pct_chg", "swing", "vol", "amount"):
            if col in df.columns:
                df[col] = pd.to_numeric(df[col], errors="coerce")
        # validation
        dup = int(df.duplicated(subset=["trade_date"]).sum())
        chk = df.dropna(subset=["pct_chg", "close", "pre_close"])
        bad_chg = int((np.abs(chk["pct_chg"] / 100 - (chk["close"] / chk["pre_close"] - 1)) > 0.001).sum())
        by_year = df.groupby(df["trade_date"].dt.year).size()
        # partial years at data boundaries (first year, current year) are expected
        full_years = [y for y in by_year.index
                      if y != by_year.index.min() and y != df["trade_date"].dt.year.max()]
        thin_years = {int(y): int(n) for y, n in by_year.items() if y in full_years and not (220 <= n <= 264)}
        big_moves = df[df["pct_chg"].abs() > 12][["trade_date", "pct_chg"]].copy()
        big_moves["trade_date"] = big_moves["trade_date"].dt.strftime("%Y-%m-%d")
        big_moves = big_moves.to_dict("records")
        manifest["codes"][code] = {
            "rows": int(len(df)),
            "first_date": str(df["trade_date"].min().date()) if len(df) else None,
            "last_date": str(df["trade_date"].max().date()) if len(df) else None,
            "dup_dates": dup, "pct_chg_mismatch": bad_chg, "thin_years": thin_years,
            "flagged_big_moves": big_moves,
            "ok": dup == 0 and bad_chg == 0 and not thin_years,
        }
        df.to_csv(f"{RAW_DIR / code}_full.csv.gz", index=False, compression="gzip")
        print(f"  -> {len(df)} rows {df['trade_date'].min().date()}~{df['trade_date'].max().date()} "
              f"dup={dup} mismatch={bad_chg} thin={thin_years}", flush=True)
        time.sleep(SLEEP)

    # global normalized file
    all_frames = []
    for code in CODES:
        p = f"{RAW_DIR / code}_full.csv.gz"
        if Path(p).exists():
            all_frames.append(pd.read_csv(p))
    full = pd.concat(all_frames, ignore_index=True)
    full.to_csv(NORM_DIR / "us_index.csv.gz", index=False, compression="gzip")
    manifest["normalized_rows"] = int(len(full))
    manifest["normalized_file"] = "normalized/us_index.csv.gz"
    (DATA_DIR / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[done] normalized rows={len(full)} -> {NORM_DIR / 'us_index.csv.gz'}", flush=True)


if __name__ == "__main__":
    main()
