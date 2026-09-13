#!/usr/bin/env bash
set -uo pipefail
REPO=/mnt/d/workspaces/qlib
PY=/home/macaulish/qlib-env/bin/python
LOG=$REPO/output/live/five_factor_veto_top30/holdings.log
mkdir -p "$(dirname "$LOG")"
cd "$REPO"
echo "=== start $(date) ===" > "$LOG"
"$PY" -u scripts/generate_five_factor_veto_holdings_v1.py >> "$LOG" 2>&1
echo "=== exit=$? $(date) ===" >> "$LOG"
