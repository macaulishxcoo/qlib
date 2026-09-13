#!/usr/bin/env bash
# Read-only probe of the WSL environment before we build the research env.
set -u

echo "=== identity ==="
whoami
id

echo
echo "=== os ==="
. /etc/os-release
echo "$PRETTY_NAME"
uname -r
echo "cores: $(nproc)   mem: $(free -h | awk '/^Mem:/{print $2}')"

echo
echo "=== python ==="
for c in python3 python3.11 python3.12 python3.10 pip3; do
  if command -v "$c" >/dev/null 2>&1; then
    printf '%-12s %s\n' "$c" "$(command -v "$c")"
  else
    printf '%-12s %s\n' "$c" "not found"
  fi
done
python3 --version 2>/dev/null || true

echo
echo "=== conda ==="
for d in "$HOME/miniconda3" "$HOME/anaconda3" "$HOME/miniforge3" /opt/conda; do
  [ -d "$d" ] && echo "found: $d"
done
command -v conda >/dev/null 2>&1 && echo "conda on PATH: $(command -v conda)" || echo "conda not on PATH"

echo
echo "=== build tools (needed if qlib must be compiled) ==="
for c in gcc g++ make; do
  if command -v "$c" >/dev/null 2>&1; then printf '%-6s %s\n' "$c" "$(command -v "$c")"; else printf '%-6s %s\n' "$c" "MISSING"; fi
done

echo
echo "=== repo access ==="
if [ -d /mnt/d/workspaces/qlib ]; then
  echo "repo reachable: /mnt/d/workspaces/qlib"
  ls /mnt/d/workspaces/qlib | head -8
  echo "data size: $(du -sh /mnt/d/workspaces/qlib/data 2>/dev/null | cut -f1)"
else
  echo "REPO NOT REACHABLE"
fi

echo
echo "=== home ==="
echo "HOME=$HOME"
df -h "$HOME" | tail -1

echo
echo "=== network ==="
if timeout 20 curl -sI https://pypi.org/simple/ >/dev/null 2>&1; then echo "pypi reachable"; else echo "PYPI UNREACHABLE"; fi
if timeout 20 curl -sI https://repo.anaconda.com/pkgs/main/ >/dev/null 2>&1; then echo "anaconda repo reachable"; else echo "anaconda repo unreachable"; fi

echo
echo "=== sudo without password? ==="
if sudo -n true 2>/dev/null; then echo "passwordless sudo: yes"; else echo "passwordless sudo: no"; fi
