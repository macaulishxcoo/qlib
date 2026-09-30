#!/usr/bin/env bash
# 安装 / 重装 JQData SDK 到仓库内可写目录 .jqdata_env/。
#
# 背景：本机 conda env qlib 的 site-packages 与 $HOME 都是只读文件系统，
# 常规 `pip install jqdatasdk` 会失败在 `/root/.local`（Errno 30 Read-only file system）。
# 因此固定采用 `--target .jqdata_env --no-deps`：
#   - --target       : 装到仓库内可写目录
#   - --no-deps      : 避免 pip 把 pandas/numpy 升级到 3.x/2.5（会遮蔽 qlib 依赖的 pandas 2.3.3）
#   依赖只补 jqdatasdk 真正需要、且环境里没有的：thriftpy2/ply/ijson/pymysql/msgpack
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
PY="${JQ_PYTHON:-/home/xiaocong/anaconda3/envs/qlib/bin/python}"
MIRROR="${JQ_PIP_INDEX:-https://pypi.tuna.tsinghua.edu.cn/simple}"

cd "${REPO_ROOT}"
mkdir -p .jqdata_env .jqdata_tmp .jqdata_cache
export TMPDIR="${REPO_ROOT}/.jqdata_tmp"
export PIP_CACHE_DIR="${REPO_ROOT}/.jqdata_cache"

echo "[install] 目标目录: ${REPO_ROOT}/.jqdata_env"
"${PY}" -m pip install --no-user --target .jqdata_env --no-deps \
  -i "${MIRROR}" \
  jqdatasdk==1.9.8 thriftpy2 ply ijson pymysql msgpack

echo "[install] 完成。自检："
bash "${REPO_ROOT}/scripts/jqdata/run.sh" -c \
  "import jqdatasdk,pandas,numpy;print('jqdatasdk',jqdatasdk.__version__ if hasattr(jqdatasdk,'__version__') else 'n/a');print('pandas',pandas.__version__);print('numpy',numpy.__version__)"
