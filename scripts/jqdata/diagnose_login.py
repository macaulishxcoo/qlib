#!/usr/bin/env python
"""JQData 登录诊断（只读）。

    bash scripts/jqdata/run.sh scripts/jqdata/diagnose_login.py

只做两件事：
1. 报告凭据的**形态**（长度/字符类/是否含空白），用于排除"复制粘贴带入空格"一类问题；
2. 调用 SDK ``auth()`` 并给出**判读**。

不打印密码原文（只打印长度与 sha256 前缀），不修改任何数据。

注意：本脚本**不再**去探测聚宽网页登录接口。实测 ``www.joinquant.com`` 的
``/user/login`` 等端点只返回 SPA 空壳（HTTP 200 + HTML），需要 CSRF token 与前端加密，
无法可靠地区分"账号不存在"与"密码错误"，因此该路径已移除，避免给出误导性结论。
SDK 的报错文本（见下）与平台自身鉴权逻辑一致，是更可靠的依据。
"""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _env import CRED_PATH, ensure_env  # noqa: E402

ensure_env()


def describe(u: str, p: str) -> None:
    print("--- 凭据形态 ---")
    print(f"username       : {u[:3]}****{u[-2:]}  (len={len(u)}, all_digit={u.isdigit()})")
    print(f"password       : len={len(p)}, sha256[:12]={hashlib.sha256(p.encode()).hexdigest()[:12]}")
    classes = "".join(
        sorted(
            {
                "lower" if c.islower() else "upper" if c.isupper() else "digit" if c.isdigit() else "other"
                for c in p
            }
        )
    )
    print(f"password 字符类 : {classes}")
    print(f"含首尾空白      : {p != p.strip()}")
    print(f"含非 ASCII      : {any(ord(c) > 127 for c in p)}")


def main() -> int:
    if not CRED_PATH.is_file():
        print(f"未找到凭据文件：{CRED_PATH}", file=sys.stderr)
        return 2
    d = json.loads(CRED_PATH.read_text(encoding="utf-8"))
    u, p = d["username"], d["password"]
    describe(u, p)

    print("\n--- SDK auth() ---")
    from jqdatasdk import auth

    try:
        print("result:", auth(u, p))
        print("\n[diagnose] 登录成功 ✅")
        return 0
    except Exception as exc:  # noqa: BLE001
        msg = str(exc)
        print(f"Exception: {msg}")

    print("\n--- 判读：`用户不存在或密码错误` 的两种成因 ---")
    print(
        "该报错文本由平台鉴权返回，**同时覆盖两种情况**，SDK 无法进一步区分：\n"
        "  ① 手机号或密码不正确（含：手机号不是聚宽账号 / 密码记错 / 该密码是其他站点的密码）；\n"
        "  ② 账号正确但**未开通 JQData SDK 调用权限**——仅在聚宽注册账号是不够的，\n"
        "     必须在 https://www.joinquant.com/default/index/sdk 提交申请并获批。\n"
        "（依据：报错文本自身的提示，以及公开资料对 JQData 开通流程的说明）"
    )
    print("\n--- 建议的排查顺序 ---")
    print("  1. 用同一手机号+密码登录 https://www.joinquant.com —— 登录不了 → 是密码问题；")
    print("  2. 能登录但取不到数 → 打开上面链接确认 SDK 权限是否已开通/生效；")
    print("  3. 刚改过密码 → 重新运行 set_credentials.py 覆盖旧凭据；")
    print("  4. 短时间内反复试错可能触发风控，建议间隔几分钟再试。")
    return 3


if __name__ == "__main__":
    raise SystemExit(main())
