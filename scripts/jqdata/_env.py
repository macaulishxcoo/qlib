"""JQData (聚宽) 运行环境引导。

本机限制（2026-09-15 实测）：conda env ``qlib`` 的 ``site-packages`` 与 ``$HOME``
（``/root``）都是**只读**，无法用常规 ``pip install``。因此 jqdatasdk 被安装到
仓库内可写目录 ``.jqdata_env/``，并通过 ``PYTHONPATH`` 注入。

本模块在任何 jqdatasdk 调用前导入即可，作用：
1. 把 ``<repo>/.jqdata_env`` 追加到 ``sys.path``（若尚未存在）；
2. 把 ``<repo>/.jqdata_tmp`` 设为 ``TMPDIR``（避免一切写 /root 的尝试）；
3. 提供凭据来源的统一入口（环境变量优先，其次 ``.jqdata/credentials.json``）。

用法::

    from jqdata_env import ensure_env, auth
    auth()                      # 自动读取凭据并登录
    from jqdatasdk import get_price

注意：本模块**不**打印密码，也不把密码写入任何受版本控制的文件。
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Optional, Tuple

REPO_ROOT = Path(__file__).resolve().parents[2]
ENV_DIR = REPO_ROOT / ".jqdata_env"
TMP_DIR = REPO_ROOT / ".jqdata_tmp"
CRED_PATH = REPO_ROOT / ".jqdata" / "credentials.json"

_ENSURED = False


def ensure_env() -> None:
    """把 jqdatasdk 安装目录与 TMPDIR 接入当前进程（幂等）。"""
    global _ENSURED
    if _ENSURED:
        return
    p = str(ENV_DIR)
    if ENV_DIR.is_dir() and p not in sys.path:
        # 追加而非插入：让 site-packages 的 pandas/numpy 优先，避免版本漂移
        sys.path.append(p)
    TMP_DIR.mkdir(parents=True, exist_ok=True)
    os.environ.setdefault("TMPDIR", str(TMP_DIR))
    _ENSURED = True


def load_credentials() -> Tuple[str, str]:
    """返回 (账号/手机号, 密码)。

    优先级：环境变量 ``JQ_USERNAME``/``JQ_PASSWORD`` > ``.jqdata/credentials.json``。
    找不到时抛 ``RuntimeError``，并由调用方负责给出提示。
    """
    u = os.environ.get("JQ_USERNAME") or os.environ.get("JQDATA_USER")
    pw = os.environ.get("JQ_PASSWORD") or os.environ.get("JQDATA_PASSWORD")
    if u and pw:
        return u.strip(), pw
    if CRED_PATH.is_file():
        try:
            data = json.loads(CRED_PATH.read_text(encoding="utf-8"))
        except Exception as exc:  # noqa: BLE001
            raise RuntimeError(f"凭据文件解析失败：{CRED_PATH}（{exc}）") from exc
        u = (data.get("username") or "").strip()
        pw = data.get("password") or ""
        if u and pw:
            return u, pw
    raise RuntimeError(
        "未找到聚宽凭据。请任选其一：\n"
        f"  A) 设置环境变量：export JQ_USERNAME=手机号 JQ_PASSWORD=密码\n"
        f"  B) 写入 {CRED_PATH}（JSON：{{\"username\": \"手机号\", \"password\": \"密码\"}}，"
        "建议 chmod 600）"
    )


def auth(verbose: bool = True) -> bool:
    """登录聚宽数据服务；成功返回 True，失败抛异常。

    ⚠ 重要（实测 2026-09-15）：``jqdatasdk.auth()`` **本身只写入凭据、不发请求、返回 None**
    （见 ``.jqdata_env/jqdatasdk/__init__.py`` 的 ``def auth``）。真正的鉴权发生在
    **首次 API 调用**时，由 SDK 打印 ``auth success`` 或抛
    ``用户不存在或密码错误``。因此不能用 ``bool(auth(...))`` 判断成败——
    本函数改为「设置凭据 + 触发一次鉴权 + 用 ``is_auth()`` 复核」。
    """
    ensure_env()
    from jqdatasdk import auth as _auth
    from jqdatasdk import is_auth

    user, pw = load_credentials()
    _auth(user, pw)

    # 触发真正的鉴权：get_account_info 是开销最小的调用之一
    from jqdatasdk import get_account_info

    get_account_info()  # 失败会在此抛异常
    ok = bool(is_auth())
    if verbose:
        masked = user[:3] + "****" + user[-2:] if len(user) > 5 else "***"
        print(f"[jqdata] auth OK (account={masked}, is_auth={ok})")
    return ok


if __name__ == "__main__":  # 自检
    ensure_env()
    import jqdatasdk  # noqa: F401

    print("ENV_DIR   :", ENV_DIR, "exists=", ENV_DIR.is_dir())
    print("TMPDIR    :", os.environ.get("TMPDIR"))
    print("jqdatasdk :", jqdatasdk.__file__)
    ok = auth()
    from jqdatasdk import get_account_info

    print("account   :")
    print(get_account_info())
