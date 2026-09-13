#!/usr/bin/env bash
# 否决定义稳健性检验 (复用已缓存的 snapshots)
set -uo pipefail
REPO=/mnt/d/workspaces/qlib
PY=/home/macaulish/qlib-env/bin/python
LOG=$REPO/output/analysis_fundamental/a_share_five_factor_daily_execution_v1/robustness.log
cd "$REPO"
echo "=== start $(date) ===" > "$LOG"
"$PY" -u scripts/analyze_a_share_veto_definition_robustness_v1.py >> "$LOG" 2>&1
echo "=== exit=$? $(date) ===" >> "$LOG"
