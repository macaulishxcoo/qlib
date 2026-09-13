#!/usr/bin/env bash
set -uo pipefail
REPO=/mnt/d/workspaces/qlib
PY=/home/macaulish/qlib-env/bin/python
LOG=$REPO/output/analysis_fundamental/a_share_five_factor_daily_execution_v1/return_attr.log
cd "$REPO"
{
  echo "=== start $(date) ==="
  "$PY" -u scripts/analyze_strategy_return_attribution_v1.py 2>&1 \
      | grep -v 'WARNING\|RuntimeWarning\|nanmean\|backtest loop'
  echo "=== exit=$? $(date) ==="
} > "$LOG" 2>&1
