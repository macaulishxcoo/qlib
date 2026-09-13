#!/usr/bin/env python
"""核查 qlib store 的【日历末端】与【实际数据末端】是否一致。

现象: asof=2026-09-11 时 价格查询全 NaN、毒尾面板该日也全 NaN。
怀疑: 日历已排到 2026-09-11, 但行情数据(bin)实际只到更早的日期。
"""
from pathlib import Path

import pandas as pd
import qlib
from qlib.config import REG_CN
from qlib.data import D

QLIB_DIR = Path.home() / ".qlib" / "qlib_data" / "cn_data_2026"
qlib.init(provider_uri=str(QLIB_DIR), region=REG_CN)

cal = pd.DatetimeIndex(pd.to_datetime(
    pd.read_csv(QLIB_DIR / "calendars" / "day.txt", header=None)[0]))
print(f"calendar: {cal.min().date()} .. {cal.max().date()}  ({len(cal)} 天)")
print(f"最后 8 个交易日: {[str(d.date()) for d in cal[-8:]]}")

codes = ["SH600000", "SZ000001", "SH601398", "SZ002415"]
df = D.features(codes, ["$close", "$volume"],
                start_time=str(cal[-12].date()), end_time=str(cal[-1].date()), freq="day")
df.columns = ["close", "volume"]
piv = df["close"].unstack(0)
print("\n最后 12 个交易日收盘价:")
print(piv.to_string())
print("\n各列非空数:", piv.notna().sum().to_dict())

# 全市场层面: 每个日历日有多少只有价格
inst = D.instruments(market="all")
allpx = D.features(inst, ["$close"], start_time=str(cal[-12].date()),
                   end_time=str(cal[-1].date()), freq="day")
allpx.columns = ["close"]
cnt = allpx["close"].groupby(level=1).apply(lambda s: int(s.notna().sum()))
print("\n每个日历日有价格的股票数:")
print(cnt.to_string())
