#!/usr/bin/env bash
# 重算最终策略的阶段拆解 (monitor 会重新生成 backtest_daily.csv, 基于修复后的 50 万快照)
set -uo pipefail
REPO=/mnt/d/workspaces/qlib
PY=/home/macaulish/qlib-env/bin/python
cd "$REPO"
{
  echo "=== start $(date) ==="
  echo "--- monitor (regenerate backtest_daily) ---"
  "$PY" -u scripts/monitor_strategy_decay_v1.py --backtest 2>&1 | tail -15
  echo "--- stage decomposition ---"
  "$PY" -u scripts/diagnose_recent_underperformance_v1.py 2>&1 \
      | grep -v 'WARNING\|RuntimeWarning\|nanmean\|Gym\|migration_guide\|unmaintained' | head -14
  echo "=== exit=$? $(date) ==="
} > output/live/decay_monitor/recheck.log 2>&1
