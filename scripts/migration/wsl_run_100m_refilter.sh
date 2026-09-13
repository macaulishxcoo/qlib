#!/usr/bin/env bash
# 用修复后的 load_amount_avg 在【1 亿口径】重跑五因子线, 验证"流动性过滤从未生效"的影响。
set -uo pipefail
REPO=/mnt/d/workspaces/qlib
PY=/home/macaulish/qlib-env/bin/python
BASE=$REPO/output/analysis_fundamental/a_share_five_factor_daily_execution_v1
cd "$REPO"
echo "=== start $(date) ===" > "$BASE/run_100m_refilter.log"
# 备份旧结果, 便于对照
cp "$BASE/backtest_summary.csv" "$BASE/backtest_summary_PREfilterfix.csv" 2>/dev/null || true
rm -f "$BASE/snapshots_cache.pkl"
"$PY" -u scripts/backtest_a_share_five_factor_daily_execution_v1.py \
      >> "$BASE/run_100m_refilter.log" 2>&1
echo "=== exit=$? $(date) ===" >> "$BASE/run_100m_refilter.log"
