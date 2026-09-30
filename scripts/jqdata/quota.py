#!/usr/bin/env python
"""JQData 额度守卫 —— 防止再次把当日 100 万条额度烧光。

用法::

    bash scripts/jqdata/run.sh scripts/jqdata/quota.py            # 查看当前额度
    bash scripts/jqdata/run.sh scripts/jqdata/quota.py --cost 5013 250   # 估算一次任务的消耗

在代码里::

    from quota import quota
    with quota("拉取全市场 250 日 OHLC", limit=200_000) as q:
        for batch in batches:
            df = get_price(...)
            q.charge(len(df))          # 记账；超预算立即抛 QuotaExceeded

关键事实（2026-09-15 实测）：
- 计费 = **每返回 1 行算 1 条**，与字段数无关（取 4 字段的 245 行 = 245 条）。
- ``get_query_count()`` / ``get_account_info()`` **不耗额度**（实测差值为 0），可放心查询。
- 额度**按日重置**：``total`` = 当日额度，``spare`` = 当日剩余。
- ``query``/``get_fundamentals`` 单次最多返回 **5,000 行**，需分页。

踩过的坑：探测因子权限时跑了约 300 次调用、没有记账，把 100 万条烧掉 88 万条
（`get_all_securities` 每次都返回 5,000+ 行）。**任何批量取数前先跑本脚本估算。**
"""

from __future__ import annotations

import argparse
import contextlib
import sys
from pathlib import Path
from typing import Iterator

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _env import auth, ensure_env  # noqa: E402

ensure_env()


class QuotaExceeded(RuntimeError):
    """预算超限，提前中止以免浪费额度。"""


class _Quota:
    def __init__(self, label: str, limit: int | None = None, verbose: bool = True) -> None:
        from jqdatasdk import get_query_count

        self.label = label
        self.limit = limit
        self.verbose = verbose
        self.start = get_query_count()
        self.used = 0

    def charge(self, rows: int) -> None:
        self.used += max(int(rows), 0)
        if self.limit is not None and self.used > self.limit:
            raise QuotaExceeded(
                f"[{self.label}] 已用 {self.used:,} 超过预算 {self.limit:,}，已中止"
            )
        if self.verbose:
            print(f"  [{self.label}] +{rows:,} -> 累计 {self.used:,}", flush=True)

    def report(self) -> None:
        from jqdatasdk import get_query_count

        end = get_query_count()
        real = self.start["spare"] - end["spare"]
        print(
            f"\n[{self.label}] 完成\n"
            f"  本次记账   : {self.used:,} 条\n"
            f"  服务端实测 : {real:,} 条\n"
            f"  剩余额度   : {end['spare']:,} / {end['total']:,}"
        )


@contextlib.contextmanager
def quota(label: str, limit: int | None = None, verbose: bool = True) -> Iterator[_Quota]:
    q = _Quota(label, limit=limit, verbose=verbose)
    try:
        yield q
    finally:
        q.report()


def estimate(per_call_rows: int, calls: int) -> int:
    return per_call_rows * calls


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--cost", nargs=2, type=int, metavar=("ROWS_PER_CALL", "CALLS"),
                    help="估算：每次调用行数 × 调用次数")
    args = ap.parse_args()

    auth()
    from jqdatasdk import get_query_count

    q = get_query_count()
    pct = q["spare"] / q["total"] * 100 if q["total"] else 0
    print(f"当日额度: {q['spare']:,} / {q['total']:,}  剩余 {pct:.1f}%")

    if args.cost:
        rows, calls = args.cost
        need = estimate(rows, calls)
        print(f"\n估算任务: {rows:,} 行/次 × {calls:,} 次 = {need:,} 条")
        if need > q["spare"]:
            print(f"❌ 超出剩余额度 {need - q['spare']:,} 条 —— 需分日执行或缩小范围")
        else:
            print(f"✅ 可执行，执行后剩余 {q['spare'] - need:,} 条")

    # 常见任务参考
    print("\n常见任务成本（行数=股票数 × 交易日数）：")
    for label, n in [
        ("全市场 5,000 只 × 250 日", 5000 * 250),
        ("全市场 5,000 只 × 60 日", 5000 * 60),
        ("单只 × 250 日", 250),
        ("沪深300 × 250 日", 300 * 250),
    ]:
        ok = "✅" if n <= q["spare"] else "❌"
        print(f"  {ok} {label:26s} {n:>10,} 条")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
