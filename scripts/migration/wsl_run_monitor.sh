#!/usr/bin/env bash
set -uo pipefail
REPO=/mnt/d/workspaces/qlib
PY=/home/macaulish/qlib-env/bin/python
LOG=$REPO/output/live/decay_monitor/monitor.log
mkdir -p "$(dirname "$LOG")"
cd "$REPO"
echo "=== start $(date) ===" > "$LOG"
"$PY" -u scripts/monitor_strategy_decay_v1.py --backtest >> "$LOG" 2>&1
echo "=== exit=$? $(date) ===" >> "$LOG"
