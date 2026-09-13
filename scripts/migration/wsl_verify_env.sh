#!/usr/bin/env bash
# Verify that the repo's scripts will import the INSTALLED pyqlib, not the
# uncompiled local qlib/ source tree (which has no _libs/*.so on this machine).
set -u
PY="${HOME}/qlib-env/bin/python"
REPO=/mnt/d/workspaces/qlib

echo "=== A) run a script from /tmp, cwd = repo root (how the repo scripts run) ==="
cat > /tmp/_check_qlib.py <<'PYEOF'
import sys, qlib
print("  sys.path[0] :", sys.path[0] or "<cwd>")
print("  qlib file   :", qlib.__file__)
print("  qlib version:", qlib.__version__)
from qlib.contrib.evaluate import backtest_daily, risk_analysis
from qlib.contrib.strategy import TopkDropoutStrategy
from qlib.data import D
print("  contrib/data imports OK")
PYEOF
cd "${REPO}" && "${PY}" /tmp/_check_qlib.py

echo
echo "=== B) heredoc / stdin (cwd on sys.path) -- this is what FAILED before ==="
cd "${REPO}" && "${PY}" -c "import qlib; print('  qlib file:', qlib.__file__)"

echo
echo "=== C) from a different cwd entirely ==="
cd /tmp && "${PY}" /tmp/_check_qlib.py

echo
echo "=== D) does the repo have compiled _libs? ==="
ls "${REPO}/qlib/data/_libs/" 2>/dev/null | head -10 || echo "  (no _libs dir)"
echo "  .so files in repo qlib/: $(find "${REPO}/qlib" -name '*.so' 2>/dev/null | wc -l)"

echo
echo "=== E) lightgbm / libgomp ==="
"${PY}" -c "import lightgbm; print('  lightgbm OK', lightgbm.__version__)" 2>&1 | head -3
echo "  libgomp present? $(ldconfig -p 2>/dev/null | grep -c libgomp)"

echo
echo "=== F) tushare connectivity with the saved token ==="
"${PY}" - <<'PYEOF'
from pathlib import Path
import tushare as ts
tok = Path.home().joinpath(".config/tushare/token").read_text().strip()
print("  token length:", len(tok))
try:
    pro = ts.pro_api(tok)
    cal = pro.trade_cal(exchange="SSE", start_date="20260801", end_date="20260813", is_open="1")
    print("  trade_cal rows:", len(cal))
    print(cal.head(3).to_string(index=False))
    d = pro.daily(trade_date="20260813")
    print("  daily(20260813) rows:", len(d), "| cols:", list(d.columns))
except Exception as exc:
    print("  TUSHARE CALL FAILED:", type(exc).__name__, exc)
PYEOF
