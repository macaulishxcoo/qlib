#!/usr/bin/env bash
# Build the research environment inside WSL. Requires NO sudo.
#
# Notes learned on this machine:
#  - WSL2 resolves AAAA records but IPv6 does not route, so plain curl can hang
#    on DNS/connect. All downloads here force IPv4 (-4) and use retries.
#  - PyPI ships manylinux wheels for pyqlib cp311/cp312, so no compiler is
#    needed; gcc/g++/make are absent and sudo is not passwordless.
#  - System python is 3.14 (no qlib wheel) and has no pip/ensurepip.
# Idempotent: safe to re-run.
set -euo pipefail

VENV="${HOME}/qlib-env"
PY="${VENV}/bin/python"
TOKEN_SRC="/mnt/c/Users/congx/.tushare_token"
TOKEN_DST="${HOME}/.config/tushare/token"
PYPI_MIRROR="https://pypi.org/simple"

fetch() { curl -4 -fsSL --retry 4 --retry-delay 3 --connect-timeout 20 --max-time 300 "$1"; }

echo "=============================================================="
echo " WSL research environment setup"
echo "=============================================================="

# ---------------------------------------------------------------- uv ----
export PATH="${HOME}/.local/bin:${PATH}"
if ! command -v uv >/dev/null 2>&1; then
  echo "[1/5] installing uv (user space, no sudo)"
  ok=0
  for attempt in 1 2 3; do
    if fetch https://astral.sh/uv/install.sh | sh; then ok=1; break; fi
    echo "      attempt ${attempt} failed, retrying..."
    sleep 5
  done
  if [ "${ok}" != "1" ] || ! command -v uv >/dev/null 2>&1; then
    echo "FATAL: could not install uv"
    exit 1
  fi
else
  echo "[1/5] uv already present"
fi
uv --version

# ------------------------------------------------------------ python ----
echo
echo "[2/5] ensuring CPython 3.12 is available"
uv python install 3.12
uv python list 2>/dev/null | grep -E "3\.12" | head -3 || true

# --------------------------------------------------------------- venv ----
echo
echo "[3/5] creating venv at ${VENV}"
if [ ! -x "${PY}" ]; then
  uv venv "${VENV}" --python 3.12
else
  echo "venv already exists"
fi
"${PY}" --version

# ----------------------------------------------------------- packages ----
echo
echo "[4/5] installing packages (a few minutes)"
uv pip install --python "${PY}" --index-url "${PYPI_MIRROR}" \
  "pandas==2.3.3" numpy scipy statsmodels pyarrow lightgbm scikit-learn \
  pyyaml tqdm fire loguru tushare "pyqlib==0.9.7"

echo
echo "installed versions:"
"${PY}" - <<'PYEOF'
import sys
print("python", sys.version.split()[0])
for m in ["pandas", "numpy", "scipy", "statsmodels", "lightgbm", "pyarrow", "sklearn", "tushare"]:
    try:
        mod = __import__(m)
        print(f"  {m:<14}{getattr(mod, '__version__', '?')}")
    except Exception as exc:
        print(f"  {m:<14}FAILED: {type(exc).__name__}: {exc}")
try:
    import qlib
    print(f"  {'qlib':<14}{qlib.__version__}")
    print(f"  qlib path     {qlib.__file__}")
    from qlib.contrib.evaluate import backtest_daily, risk_analysis
    from qlib.contrib.strategy import TopkDropoutStrategy
    from qlib.data import D
    print("  qlib.contrib + qlib.data imports OK")
except Exception as exc:
    print(f"  qlib FAILED: {type(exc).__name__}: {exc}")
PYEOF

# -------------------------------------------------------------- token ----
echo
echo "[5/5] configuring the tushare token"
mkdir -p "$(dirname "${TOKEN_DST}")"
if [ -f "${TOKEN_SRC}" ]; then
  tr -d '\r\n' < "${TOKEN_SRC}" > "${TOKEN_DST}"
  chmod 600 "${TOKEN_DST}"
  echo "token written to ${TOKEN_DST} (length $(wc -c < "${TOKEN_DST}"))"
elif [ -f "${TOKEN_DST}" ]; then
  echo "token already present at ${TOKEN_DST} (length $(wc -c < "${TOKEN_DST}"))"
else
  echo "WARNING: ${TOKEN_SRC} not found; token NOT configured"
fi

echo
echo "=============================================================="
echo " done.  python: ${PY}"
echo " activate:     source ${VENV}/bin/activate"
echo "=============================================================="
