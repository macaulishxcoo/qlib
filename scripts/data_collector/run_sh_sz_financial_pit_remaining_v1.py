#!/usr/bin/env python3
"""Run the remaining frozen-universe financial PIT batches sequentially.

This runner does not transform financial data.  It only invokes the audited
single-batch collector in order, skips already-ready batches, and stops at the
first failure so a network or provider error cannot be silently bypassed.
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path


def batch_is_ready(audit_report: Path) -> bool:
    return audit_report.is_file() and "status: batch_data_ready" in audit_report.read_text(encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[2])
    parser.add_argument("--start-batch", type=int, default=1)
    parser.add_argument("--end-batch", type=int, required=True)
    parser.add_argument("--batch-size", type=int, default=100)
    parser.add_argument("--sleep-seconds", type=float, default=0.3)
    args = parser.parse_args()
    if args.start_batch < 1 or args.end_batch < args.start_batch:
        raise SystemExit("batch range is invalid")

    root = args.root.resolve()
    collector = root / "scripts/data_collector/download_sh_sz_financial_pit_batch_v1.py"
    audit_root = root / "output/data_audits/a_share_financial_pit_v1/full"
    runner_log = audit_root / "full_download_runner_v1.log"
    runner_log.parent.mkdir(parents=True, exist_ok=True)

    with runner_log.open("a", encoding="utf-8") as stream:
        stream.write(f"{datetime.now(timezone.utc).isoformat()} start {args.start_batch}-{args.end_batch}\n")
        stream.flush()
        for number in range(args.start_batch, args.end_batch + 1):
            batch_id = f"batch_{number:04d}"
            report = audit_root / batch_id / "batch_audit_report.txt"
            if batch_is_ready(report):
                message = f"{datetime.now(timezone.utc).isoformat()} {batch_id} skip_ready\n"
                print(message, end="", flush=True)
                stream.write(message)
                stream.flush()
                continue
            message = f"{datetime.now(timezone.utc).isoformat()} {batch_id} start\n"
            print(message, end="", flush=True)
            stream.write(message)
            stream.flush()
            result = subprocess.run(
                [
                    sys.executable,
                    "-u",
                    str(collector),
                    "--root",
                    str(root),
                    "--batch-number",
                    str(number),
                    "--batch-size",
                    str(args.batch_size),
                    "--sleep-seconds",
                    str(args.sleep_seconds),
                ],
                cwd=root,
                stdout=stream,
                stderr=subprocess.STDOUT,
                text=True,
            )
            if result.returncode != 0 or not batch_is_ready(report):
                message = f"{datetime.now(timezone.utc).isoformat()} {batch_id} blocked exit={result.returncode}\n"
                print(message, end="", flush=True)
                stream.write(message)
                stream.flush()
                raise SystemExit(f"{batch_id} failed; see {runner_log}")
            message = f"{datetime.now(timezone.utc).isoformat()} {batch_id} ready\n"
            print(message, end="", flush=True)
            stream.write(message)
            stream.flush()
        message = f"{datetime.now(timezone.utc).isoformat()} complete {args.start_batch}-{args.end_batch}\n"
        print(message, end="", flush=True)
        stream.write(message)


if __name__ == "__main__":
    main()
