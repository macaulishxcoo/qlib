#!/usr/bin/env python
"""交互式写入聚宽凭据到 ``.jqdata/credentials.json``（chmod 600，不进版本控制）。

用法::

    bash scripts/jqdata/run.sh scripts/jqdata/set_credentials.py

说明：
- 账号 = 申请试用时填写的**手机号**；密码 = 聚宽官网登录密码（见 JQData 文档）。
- 密码输入时不回显。
- 若你更愿意用环境变量（``JQ_USERNAME`` / ``JQ_PASSWORD``），可以不运行本脚本。
"""

from __future__ import annotations

import getpass
import json
import os
import stat
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _env import CRED_PATH  # noqa: E402


def main() -> int:
    print(f"凭据将写入：{CRED_PATH}")
    user = input("聚宽账号（申请试用的手机号）: ").strip()
    if not user:
        print("账号为空，已取消。", file=sys.stderr)
        return 1
    pw = getpass.getpass("聚宽密码（不回显）: ")
    if not pw:
        print("密码为空，已取消。", file=sys.stderr)
        return 1
    pw2 = getpass.getpass("再次输入密码确认: ")
    if pw != pw2:
        print("两次输入不一致，已取消。", file=sys.stderr)
        return 1

    CRED_PATH.parent.mkdir(parents=True, exist_ok=True)
    CRED_PATH.write_text(
        json.dumps({"username": user, "password": pw}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    os.chmod(CRED_PATH, stat.S_IRUSR | stat.S_IWUSR)  # 600
    print(f"已写入并设为 600：{CRED_PATH}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
