#!/usr/bin/env python3
"""Run frozen balance-sheet PIT batches sequentially and stop on first failure."""

from __future__ import annotations

import argparse
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path


def ready(path: Path) -> bool:
    return path.is_file() and "status: batch_data_ready" in path.read_text(encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[2])
    parser.add_argument("--start-batch", type=int, default=1)
    parser.add_argument("--end-batch", type=int, default=54)
    parser.add_argument("--sleep-seconds", type=float, default=0.3)
    args = parser.parse_args()
    if not 1 <= args.start_batch <= args.end_batch <= 54:
        raise SystemExit("invalid batch range")
    root = args.root.resolve()
    collector = root / "scripts/data_collector/download_sh_sz_balancesheet_pit_batch_v1.py"
    audit_root = root / "output/data_audits/a_share_financial_pit_v1/balancesheet_v1"
    log_path = audit_root / "download_runner_v1.log"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with log_path.open("a", encoding="utf-8") as log:
        for number in range(args.start_batch, args.end_batch + 1):
            batch_id = f"batch_{number:04d}"
            report = audit_root / batch_id / "batch_audit_report.txt"
            if ready(report):
                print(f"{batch_id} skip_ready", flush=True)
                continue
            log.write(f"{datetime.now(timezone.utc).isoformat()} {batch_id} start\n")
            log.flush()
            result = subprocess.run([sys.executable, "-u", str(collector), "--root", str(root), "--batch-number", str(number), "--sleep-seconds", str(args.sleep_seconds)], cwd=root, stdout=log, stderr=subprocess.STDOUT, text=True)
            if result.returncode != 0 or not ready(report):
                log.write(f"{datetime.now(timezone.utc).isoformat()} {batch_id} blocked exit={result.returncode}\n")
                raise SystemExit(f"{batch_id} blocked; inspect {log_path}")
            print(f"{batch_id} ready", flush=True)
        print("all requested batches ready", flush=True)


if __name__ == "__main__":
    main()
