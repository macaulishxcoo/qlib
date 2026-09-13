#!/usr/bin/env bash
set -uo pipefail
REPO=/mnt/d/workspaces/qlib
PY=/home/macaulish/qlib-env/bin/python
LOG=$REPO/output/analysis_fundamental/a_share_five_factor_daily_execution_v1/veto_transfer.log
cd "$REPO"
{
  echo "=== start $(date) ==="
  "$PY" -u scripts/analyze_a_share_veto_transfer_v1.py 2>&1 | grep -v 'RuntimeWarning\|nanmean'
  echo "=== exit=$? $(date) ==="
} > "$LOG" 2>&1
