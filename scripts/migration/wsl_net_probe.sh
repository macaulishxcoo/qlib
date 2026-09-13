#!/usr/bin/env bash
# Find which external hosts this WSL instance can actually reach.
set -u

echo "=== resolv.conf ==="
cat /etc/resolv.conf 2>/dev/null || echo "(none)"

echo
echo "=== default route / nameserver reachability ==="
ip route 2>/dev/null | head -3

probe() {
  local url="$1"
  local code
  code=$(timeout 15 curl -s -o /dev/null -w '%{http_code}' "$url" 2>/dev/null)
  if [ "$code" = "000" ] || [ -z "$code" ]; then
    printf '  %-55s UNREACHABLE\n' "$url"
  else
    printf '  %-55s HTTP %s\n' "$url" "$code"
  fi
}

echo
echo "=== HTTP reachability ==="
probe https://pypi.org/simple/
probe https://files.pythonhosted.org/
probe https://github.com/
probe https://objects.githubusercontent.com/
probe https://astral.sh/
probe https://repo.anaconda.com/pkgs/main/
probe https://mirrors.tuna.tsinghua.edu.cn/anaconda/miniconda/
probe https://mirrors.tuna.tsinghua.edu.cn/pypi/web/simple/
probe https://mirrors.aliyun.com/pypi/simple/
probe https://registry.npmmirror.com/

echo
echo "=== DNS lookups ==="
for h in pypi.org github.com astral.sh mirrors.tuna.tsinghua.edu.cn; do
  if getent hosts "$h" >/dev/null 2>&1; then
    printf '  %-40s %s\n' "$h" "$(getent hosts "$h" | head -1 | awk '{print $1}')"
  else
    printf '  %-40s FAILED\n' "$h"
  fi
done

echo
echo "=== can system python make a venv / get pip? ==="
python3 -c "import venv, ensurepip; print('venv+ensurepip modules present')" 2>&1 | head -3
python3 -m pip --version 2>&1 | head -2
