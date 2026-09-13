#!/usr/bin/env bash
set -uo pipefail
REPO=/mnt/d/workspaces/qlib
PY=/home/macaulish/qlib-env/bin/python
LOG=$REPO/output/paper_trading/tracker.log
mkdir -p "$(dirname "$LOG")"
cd "$REPO"
{
  echo "=== start $(date) ==="
  echo "--- init (start 2026-09-11, capital 500000) ---"
  "$PY" -u scripts/paper_trading_tracker_v1.py --init --start-date 2026-09-11 \
        --capital 500000 2>&1 | tail -30
  echo "--- update ---"
  "$PY" -u scripts/paper_trading_tracker_v1.py --update 2>&1 | tail -30
  echo "--- status ---"
  "$PY" -u scripts/paper_trading_tracker_v1.py --status 2>&1 | tail -40
  echo "=== exit=$? $(date) ==="
} > "$LOG" 2>&1
