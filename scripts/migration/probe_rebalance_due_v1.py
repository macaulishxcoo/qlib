#!/usr/bin/env python
"""核对: 以 2026-09-11 的信号为起点, 第 10 个交易日是哪天? 调仓是否已到期?"""
from pathlib import Path

import pandas as pd

cal = pd.DatetimeIndex(pd.read_csv(
    Path.home() / ".qlib/qlib_data/cn_data_2026/calendars/day.txt", header=None)[0])

sig = pd.Timestamp("2026-09-11")
pos = cal.get_loc(sig)
print(f"信号日 {sig.date()}  在日历中的位置 {pos} / {len(cal)}")
print(f"日历末端 {cal[-1].date()}")

print("\n信号日之后的交易日 (编号从 1 开始):")
for k in range(1, 12):
    if pos + k < len(cal):
        mark = "  <-- 第10个交易日 = 调仓日" if k == 10 else ""
        print(f"  +{k:>2}  {cal[pos+k].date()}{mark}")

elapsed = len(cal) - 1 - pos
print(f"\n自信号日以来已过 {elapsed} 个交易日")
if elapsed >= 10:
    print(f">>> 调仓【已到期】(应于 {cal[pos+10].date()} 调仓, 之后又过了 {elapsed-10} 天)")
else:
    print(f">>> 调仓【未到期】(还需 {10-elapsed} 个交易日)")
