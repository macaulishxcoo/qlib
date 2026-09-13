#!/usr/bin/env bash
# 数据更新: 先 dry-run 看计划, 再实更新 daily_basic; 然后更新行情到最新交易日。
set -uo pipefail
REPO=/mnt/d/workspaces/qlib
PY=/home/macaulish/qlib-env/bin/python
LOG=$REPO/output/live/data_update.log
mkdir -p "$(dirname "$LOG")"
cd "$REPO"
{
  echo "=== start $(date) ==="
  echo "--- daily_basic dry-run ---"
  "$PY" -u scripts/data_collector/update_daily_basic_v1.py --dry-run 2>&1 | tail -25
  echo "--- daily_basic update ---"
  "$PY" -u scripts/data_collector/update_daily_basic_v1.py 2>&1 | tail -30
  echo "--- market data dry-run ---"
  "$PY" -u scripts/data_collector/update_daily_market_data_v1.py --dry-run 2>&1 | tail -20
  echo "--- market data update ---"
  "$PY" -u scripts/data_collector/update_daily_market_data_v1.py 2>&1 | tail -30
  echo "=== exit=$? $(date) ==="
} > "$LOG" 2>&1
