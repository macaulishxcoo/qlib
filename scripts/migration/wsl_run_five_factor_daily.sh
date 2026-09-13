#!/usr/bin/env bash
# 运行五因子日频执行实验, 输出落到日志文件以便实时监控 (不要用 tail 管道, 会缓冲到 EOF)
set -uo pipefail
REPO=/mnt/d/workspaces/qlib
PY=/home/macaulish/qlib-env/bin/python
LOG=$REPO/output/analysis_fundamental/a_share_five_factor_daily_execution_v1/run.log
mkdir -p "$(dirname "$LOG")"
cd "$REPO"
echo "=== start $(date) ===" > "$LOG"
"$PY" -u scripts/backtest_a_share_five_factor_daily_execution_v1.py >> "$LOG" 2>&1
echo "=== exit=$? $(date) ===" >> "$LOG"
