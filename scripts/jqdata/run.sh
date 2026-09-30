#!/usr/bin/env bash
# 统一的 JQData 运行入口：注入 .jqdata_env / TMPDIR，然后执行传入的 python 脚本或 -c 代码。
#
#   bash scripts/jqdata/run.sh scripts/jqdata/check.py
#   bash scripts/jqdata/run.sh -c "from jqdatasdk import *; auth('u','p')"
#
# 之所以需要本包装：本机 site-packages 与 $HOME 只读，jqdatasdk 只能装在仓库内
# 的 .jqdata_env/，必须靠 PYTHONPATH 暴露（见 scripts/jqdata/_env.py 顶部说明）。
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
PY="${JQ_PYTHON:-/home/xiaocong/anaconda3/envs/qlib/bin/python}"

if [[ ! -d "${REPO_ROOT}/.jqdata_env/jqdatasdk" ]]; then
  echo "[run.sh] 未找到 ${REPO_ROOT}/.jqdata_env/jqdatasdk，请先安装：" >&2
  echo "  cd ${REPO_ROOT} && bash scripts/jqdata/install.sh" >&2
  exit 1
fi

mkdir -p "${REPO_ROOT}/.jqdata_tmp"
export PYTHONPATH="${REPO_ROOT}/.jqdata_env${PYTHONPATH:+:${PYTHONPATH}}"
export TMPDIR="${TMPDIR:-${REPO_ROOT}/.jqdata_tmp}"

exec "${PY}" "$@"
