#!/usr/bin/env python
"""JQData 接入自检：登录 + 账号权限 + 一次最小取数。

用法（本机 site-packages 只读，必须走 run.sh 注入 PYTHONPATH）::

    cd /home/xiaocong/worksapces/qlib
    bash scripts/jqdata/run.sh scripts/jqdata/check.py
    bash scripts/jqdata/run.sh scripts/jqdata/check.py --date 2026-03-02   # 指定取样日

退出码：0 = 全部通过；2 = 未找到凭据；3 = 登录失败；4 = 取数失败。

登录失败时先跑 ``scripts/jqdata/diagnose_login.py``：``用户不存在或密码错误`` 这个报错
**同时覆盖「凭据错误」与「JQData SDK 权限未开通」两种情况**，SDK 无法区分。

关于取样日期：试用账号的历史区间是**动态的**（``date_range_start``/``date_range_end``，
形如「前 15 个月 ~ 前 3 个月」），因此**不能硬编码日期**——默认取账号允许区间的中点，
并由 ``get_account_info()`` 先读出区间。
"""

from __future__ import annotations

import argparse
import sys
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _env import auth, ensure_env  # noqa: E402

ensure_env()


def _mid_date(info: dict) -> str:
    """取账号可用区间的中点日期（避免贴边导致的空结果）。"""
    fmt = "%Y-%m-%d %H:%M:%S"
    try:
        s = datetime.strptime(info["date_range_start"], fmt)
        e = datetime.strptime(info["date_range_end"], fmt)
        return (s + (e - s) / 2).strftime("%Y-%m-%d")
    except Exception:  # noqa: BLE001
        return "2026-03-02"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--date", default=None, help="取样交易日；默认=账号可用区间中点")
    ap.add_argument("--code", default="000001.XSHE", help="取样标的")
    args = ap.parse_args()

    try:
        auth()
    except RuntimeError as exc:
        print(f"[check] 凭据缺失：{exc}", file=sys.stderr)
        return 2
    except Exception as exc:  # noqa: BLE001
        print(f"[check] 登录失败：{type(exc).__name__}: {exc}", file=sys.stderr)
        return 3

    from jqdatasdk import get_account_info, get_all_securities, get_price

    info = get_account_info()
    print("\n=== 账号信息 ===")
    for k, v in info.items():
        print(f"  {k:20s}: {v}")

    day = args.date or _mid_date(info)
    start = (datetime.strptime(day, "%Y-%m-%d") - timedelta(days=7)).strftime("%Y-%m-%d")
    print(f"\n抽样日期: {start} ~ {day}（账号允许区间: "
          f"{info.get('date_range_start')} ~ {info.get('date_range_end')}）")

    try:
        print("\n=== 证券列表（前 5 行）===")
        sec = get_all_securities(date=day)
        print(f"总数: {len(sec)}")
        print(sec.head())

        print(f"\n=== 取数测试：{args.code} {start} ~ {day} ===")
        df = get_price(
            args.code,
            start_date=start,
            end_date=day,
            frequency="daily",
            fields=["open", "close", "volume", "money"],
        )
        print(df.head())
        if df is None or df.empty:
            print("[check] 取数为空（可能权限/日期问题）", file=sys.stderr)
            return 4
    except Exception as exc:  # noqa: BLE001
        print(f"[check] 取数失败：{type(exc).__name__}: {exc}", file=sys.stderr)
        return 4

    print("\n[check] 全部通过 ✅")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
