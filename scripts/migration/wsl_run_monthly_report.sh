#!/usr/bin/env bash
# 月度报告: 前瞻证据(会随新数据推进) + 承重墙检查(冻结研究窗口)。
#
# 为什么分两段:
#   [B] 的监测脚本读的是 snapshots_500k_10day.pkl —— 冻结的研究快照, 止于 2026-06-23,
#   因此它的"当前滚动12个月"不随新数据变化, 每月跑都是同一组数字。
#   真正会推进的前瞻证据在 output/paper_trading/nav_log.csv, 故 [A] 先报它。
set -uo pipefail
REPO=/mnt/d/workspaces/qlib
PY=/home/macaulish/qlib-env/bin/python
LOG=$REPO/output/live/monthly_report_$(date +%Y%m).log
mkdir -p "$(dirname "$LOG")"
cd "$REPO"
{
  echo "=== 月度报告 $(date) ==="

  echo
  echo "########## [A] 前瞻证据: 模拟盘轨迹 (随新数据推进) ##########"
  "$PY" -u scripts/paper_trading_tracker_v1.py --update 2>&1 | tail -3
  "$PY" -u scripts/paper_trading_tracker_v1.py --status 2>&1 | tail -30

  echo
  echo "########## [B] 承重墙 / 衰减检查 (冻结研究窗口, 止于 2026-06-23) ##########"
  bash scripts/migration/wsl_run_monitor_all.sh
  RC=$?
  echo
  if [ "$RC" -eq 2 ]; then
      echo ">>> 报警: 毒尾否决的滚动 12 个月贡献为【负】—— 承重墙失效。"
      echo ">>> 处置: 先查实现缺陷(见 [B] 第 3 段断言), 再查数据是否更新, 最后才判定策略失效。"
  else
      echo ">>> 状态正常: 否决仍在贡献正超额 (exit=$RC)。"
  fi
  echo "=== 月度报告结束 $(date) ==="
} > "$LOG" 2>&1
exit $RC
