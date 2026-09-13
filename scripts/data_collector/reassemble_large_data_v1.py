#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Reassemble chunked large normalized data files from their git-tracked parts.

Three normalized files exceed GitHub's 100 MB per-file limit and are stored in
the repository as ``<name>.csv.gz.partNN`` chunks (95 MB each) plus a sha256
manifest (``data/external/tushare/large_file_chunks_manifest.json``):

    a_share_daily_basic_pit_v1/normalized/daily_basic.csv.gz   (636 MB)
    moneyflow_pit_v1/normalized/moneyflow.csv.gz               (315 MB)
    margin_pit_v1/normalized/margin_detail.csv.gz              (190 MB)

The originals are gitignored; scripts read them by path, so on a fresh clone
run this once to reconstruct them before running any analysis.

Usage
-----
    python scripts/data_collector/reassemble_large_data_v1.py
    python scripts/data_collector/reassemble_large_data_v1.py --force   # redo even if target exists
    python scripts/data_collector/reassemble_large_data_v1.py --check   # verify only, no writes

The script verifies every chunk's sha256 against the manifest before writing,
then checks the total size of the assembled file.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
MANIFEST = REPO_ROOT / "data/external/tushare/large_file_chunks_manifest.json"


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--force", action="store_true", help="reassemble even if the target already exists")
    ap.add_argument("--check", action="store_true", help="verify chunks and existing targets only; write nothing")
    args = ap.parse_args()

    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    ok, skipped, failed = 0, 0, 0

    for entry in manifest["files"]:
        target = REPO_ROOT / entry["original"]
        chunks = [target.parent / c["file"] for c in entry["chunks"]]

        # 1. verify every chunk hash
        for chunk, meta in zip(chunks, entry["chunks"]):
            if not chunk.is_file():
                print(f"FAIL  missing chunk: {chunk}", file=sys.stderr)
                failed += 1
                continue
            if sha256_file(chunk) != meta["sha256"]:
                print(f"FAIL  sha256 mismatch: {chunk}", file=sys.stderr)
                failed += 1
        if failed:
            continue

        # 2. skip if target already assembled (unless --force)
        if not args.force and target.is_file() and target.stat().st_size == entry["total_size"]:
            print(f"OK    {entry['original']} ({entry['total_size'] / 1e6:.0f} MB) already present")
            skipped += 1
            continue

        if args.check:
            print(f"OK    chunks verified for {entry['original']}")
            ok += 1
            continue

        # 3. reassemble
        target.parent.mkdir(parents=True, exist_ok=True)
        tmp = target.with_name(target.name + ".tmp")
        with open(tmp, "wb") as out:
            for chunk in chunks:
                with open(chunk, "rb") as src:
                    shutil.copyfileobj(src, out, 1 << 20)
        if tmp.stat().st_size != entry["total_size"]:
            print(f"FAIL  size mismatch for {entry['original']}: got {tmp.stat().st_size}, want {entry['total_size']}", file=sys.stderr)
            tmp.unlink(missing_ok=True)
            failed += 1
            continue
        tmp.replace(target)
        print(f"OK    reassembled {entry['original']} ({entry['total_size'] / 1e6:.0f} MB)")
        ok += 1

    print(f"\n{ok} assembled, {skipped} skipped, {failed} failed")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
