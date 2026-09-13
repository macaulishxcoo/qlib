#!/usr/bin/env bash
set -uo pipefail
REPO=/mnt/d/workspaces/qlib
PY=/home/macaulish/qlib-env/bin/python
LOG=$REPO/output/live/market_update.log
mkdir -p "$(dirname "$LOG")"
cd "$REPO"
{
  echo "=== start $(date) ==="
  "$PY" -u scripts/data_collector/update_daily_market_data_v1.py 2>&1 | tail -60
  echo "=== exit=$? $(date) ==="
} > "$LOG" 2>&1
