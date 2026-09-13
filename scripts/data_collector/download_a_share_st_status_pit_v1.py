#!/usr/bin/env python3
"""Download the auditable A-share name/ST-status PIT history from Tushare.

The strategy layer needs, for every historical trading day, a point-in-time
answer to "is this stock under ST/*ST/退市整理 risk warning on that day?".
Tushare's `namechange` endpoint returns per-stock historical name intervals
(name, start_date, end_date, ann_date, change_reason); the ST status is derived
from the name at each interval.

This collector only downloads and normalizes name history.  It does not read
prices, build factors, or backtest.
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


SEED = "a_share_st_status_pit_v1"
PAGE_SIZE = 200


def load_token() -> str:
    token = os.environ.get("TUSHARE_TOKEN", "").strip()
    if not token:
        token_path = Path.home() / ".config/tushare/token"
        if token_path.is_file():
            token = token_path.read_text(encoding="utf-8").strip()
    if not token:
        raise RuntimeError("No Tushare token found (TUSHARE_TOKEN or ~/.config/tushare/token)")
    return token


def atomic_csv(frame: pd.DataFrame, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    frame.to_csv(temporary, index=False, compression="gzip" if path.suffix == ".gz" else None)
    os.replace(temporary, path)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def fetch_all_namechange(pro) -> pd.DataFrame:
    """Pagination over the whole market namechange history."""
    frames = []
    offset = 0
    while True:
        frame = pro.namechange(offset=offset, limit=PAGE_SIZE)
        if frame is None or frame.empty:
            break
        frames.append(frame)
        offset += PAGE_SIZE
        if len(frame) < PAGE_SIZE:
            break
        time.sleep(0.2)
    return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()


def derive_st_status(frame: pd.DataFrame) -> pd.DataFrame:
    """Derive PIT risk-warning intervals from name history.

    ST/*ST/退市整理 are encoded in the interval name:
      - name contains "*ST" or "ST"          -> risk warning (ST / *ST)
      - name contains "退" or "退市"          -> delisting/receivership phase
    Keeps the raw interval boundaries; no inference beyond the name.
    """
    out = frame.copy()
    out["name_lower"] = out["name"].astype(str).str.lower()
    out["is_st"] = out["name_lower"].str.contains("st", regex=False)
    out["is_delist_phase"] = out["name_lower"].str.contains("退", regex=False)
    out["start_date"] = pd.to_datetime(out["start_date"], errors="coerce")
    out["end_date"] = pd.to_datetime(out["end_date"], errors="coerce")
    return out[
        ["ts_code", "name", "start_date", "end_date", "ann_date", "change_reason", "is_st", "is_delist_phase"]
    ]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-root", type=Path, default=Path("data/external/tushare/a_share_st_status_pit_v1"))
    args = parser.parse_args()

    pro = ts.pro_api(load_token())
    print("[1/3] Downloading namechange history ...", flush=True)
    raw = fetch_all_namechange(pro)
    print(f"      raw rows={len(raw)}", flush=True)
    if raw.empty:
        raise RuntimeError("Empty namechange response; token/network issue?")

    print("[2/3] Deriving ST status intervals ...", flush=True)
    normalized = derive_st_status(raw)
    # Fix intervals with missing end_date (still-current names).
    max_date = pd.Timestamp("2100-01-01")
    normalized["end_date"] = normalized["end_date"].fillna(max_date)
    raw_path = args.data_root / "raw/namechange_all.csv.gz"
    norm_path = args.data_root / "normalized/st_status_intervals.csv.gz"
    atomic_csv(raw, raw_path)
    atomic_csv(normalized, norm_path)

    print("[3/3] Manifest ...", flush=True)
    manifest = {
        "dataset": SEED,
        "source": "Tushare Pro namechange",
        "raw_rows": int(len(raw)),
        "normalized_rows": int(len(normalized)),
        "companies": int(normalized["ts_code"].nunique()),
        "st_intervals": int(normalized["is_st"].sum()),
        "delist_phase_intervals": int(normalized["is_delist_phase"].sum()),
        "files": {
            str(raw_path.relative_to(args.data_root)): {"bytes": raw_path.stat().st_size, "sha256": sha256_file(raw_path)},
            str(norm_path.relative_to(args.data_root)): {"bytes": norm_path.stat().st_size, "sha256": sha256_file(norm_path)},
        },
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
    }
    manifests = args.data_root / "manifests"
    manifests.mkdir(parents=True, exist_ok=True)
    (manifests / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    coverage = normalized.groupby(normalized["start_date"].dt.year).size()
    print(f"completed|rows={len(normalized)}|companies={manifest['companies']}|st_intervals={manifest['st_intervals']}")
    print("yearly interval counts:")
    print(coverage.head(40).to_string())


if __name__ == "__main__":
    main()
