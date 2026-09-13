#!/usr/bin/env bash
# 安装 baostock 并探测 5 分钟数据可得性。
# 用脚本文件而非内联命令: PowerShell 会展开 $HOME/$PATH 导致 PATH 被破坏。
set -euo pipefail

REPO=/mnt/d/workspaces/qlib
UV=/home/macaulish/.local/bin/uv
PY=/home/macaulish/qlib-env/bin/python

cd "$REPO"
echo "=== install baostock ==="
"$UV" pip install --python "$PY" baostock 2>&1 | tail -5

echo "=== probe ==="
"$PY" scripts/migration/probe_baostock_5min_v1.py 2>&1 | tail -30
