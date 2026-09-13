#!/usr/bin/env bash
# 一站式监测: 衰减(双基准) + 收益归因/承重墙报警 + 关键量断言。
# 建议每月或每 10 个交易日跑一次。
set -uo pipefail
REPO=/mnt/d/workspaces/qlib
PY=/home/macaulish/qlib-env/bin/python
BASE=$REPO/output/analysis_fundamental/a_share_five_factor_daily_execution_v1
OUTD=$REPO/output/live/monitor
mkdir -p "$OUTD"
cd "$REPO"
LOG=$OUTD/monitor_all.log
RC=0
{
  echo "=== monitor_all start $(date) ==="

  echo
  echo "########## [1/3] 衰减监测 (双基准) ##########"
  "$PY" -u scripts/monitor_strategy_decay_v1.py --backtest 2>&1 | tail -12
  echo "  (note: vs等权全池 口径见下节)"

  echo
  echo "########## [2/3] 收益归因 + 承重墙报警 ##########"
  "$PY" -u scripts/analyze_strategy_return_attribution_v1.py 2>&1 \
      | grep -v 'WARNING\|RuntimeWarning\|nanmean\|backtest loop' | tail -12
  RC=${PIPESTATUS[0]}

  echo
  echo "########## [3/3] 关键量断言 (静默失效哨兵) ##########"
  "$PY" - <<'PYEOF'
import json, pathlib
base = pathlib.Path("/mnt/d/workspaces/qlib/output/analysis_fundamental/a_share_five_factor_daily_execution_v1")
att = base / "return_attribution.json"
if att.is_file():
    d = json.loads(att.read_text())
    r = d["rolling_last"]
    checks = [
        ("否决滚动贡献 > 0",  r["veto_contrib"] > 0),
        ("合计滚动超额 != 0", abs(r["F_final"]) > 1e-9),
        ("基础alpha 非零",    abs(r["base_alpha"]) > 1e-9),
    ]
    for name, ok in checks:
        print(f"  [{'PASS' if ok else 'FAIL'}] {name}")
    print("  (若某项 FAIL, 首先怀疑数据/实现缺陷, 而不是策略变化)")
else:
    print("  [SKIP] 未找到 return_attribution.json")
PYEOF

  echo
  echo "=== monitor_all exit=$RC $(date) ==="
} > "$LOG" 2>&1
exit $RC
