#!/usr/bin/env bash
# 把数据与模拟盘更新到最新交易日。
#   1) daily_basic 增量
#   2) 行情增量 + dump 到 qlib store (脚本已修: 以"实际行情末日"为基准, 不再误判无新交易日)
#   3) 重算持仓清单(若已到调仓日) / 否则沿用现有信号
#   4) 模拟盘按最新收盘价 mark-to-market
#   5) 衰减 + 承重墙监测
set -uo pipefail
REPO=/mnt/d/workspaces/qlib
PY=/home/macaulish/qlib-env/bin/python
LOG=$REPO/output/live/daily_update_$(date +%Y%m%d).log
mkdir -p "$(dirname "$LOG")"
cd "$REPO"
{
  echo "=== update start $(date) ==="

  echo; echo "########## [1/5] daily_basic 增量 ##########"
  "$PY" -u scripts/data_collector/update_daily_basic_v1.py 2>&1 | tail -12

  echo; echo "########## [2/5] 行情增量 + dump ##########"
  "$PY" -u scripts/data_collector/update_daily_market_data_v1.py 2>&1 \
      | grep -vE '^\s*$' | tail -25

  echo; echo "########## [3/5] 数据时效核对 ##########"
  "$PY" -u scripts/migration/probe_data_currency_v1.py 2>&1 | tail -6

  echo; echo "########## [4/5] 生成最新持仓清单 ##########"
  "$PY" -u scripts/generate_five_factor_veto_holdings_v1.py 2>&1 \
      | grep -vE 'WARNING|Gym|migration_guide|unmaintained' | tail -20

  echo; echo "########## [5/5] 模拟盘 mark-to-market + 监测 ##########"
  "$PY" -u scripts/paper_trading_tracker_v1.py --update 2>&1 | tail -8
  "$PY" -u scripts/paper_trading_tracker_v1.py --status 2>&1 | tail -22

  echo "=== update exit=$? $(date) ==="
} > "$LOG" 2>&1
