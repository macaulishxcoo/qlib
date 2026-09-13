#!/usr/bin/env bash
set -uo pipefail
REPO=/mnt/d/workspaces/qlib
PY=/home/macaulish/qlib-env/bin/python
LOG=$REPO/output/analysis_fundamental/a_share_five_factor_daily_execution_v1/profile.log
cd "$REPO"
echo "=== start $(date) ===" > "$LOG"
"$PY" -u scripts/analyze_a_share_final_strategy_profile_v1.py >> "$LOG" 2>&1
echo "=== exit=$? $(date) ===" >> "$LOG"
