#!/usr/bin/env bash
set -uo pipefail
REPO=/mnt/d/workspaces/qlib
PY=/home/macaulish/qlib-env/bin/python
LOG=$REPO/output/analysis_fundamental/a_share_five_factor_daily_execution_v1/run_500k.log
cd "$REPO"
echo "=== start $(date) ===" > "$LOG"
"$PY" -u scripts/backtest_a_share_five_factor_500k_v1.py >> "$LOG" 2>&1
echo "=== exit=$? $(date) ===" >> "$LOG"
