#!/usr/bin/env python
"""找出 qlib store 中【个股】数据的真实末端。"""
from pathlib import Path

import pandas as pd
import qlib
from qlib.config import REG_CN
from qlib.data import D

QLIB_DIR = Path.home() / ".qlib" / "qlib_data" / "cn_data_2026"
qlib.init(provider_uri=str(QLIB_DIR), region=REG_CN)

inst = D.instruments(market="all")
df = D.features(inst, ["$close"], start_time="2026-05-01", end_time="2026-09-11", freq="day")
df.columns = ["close"]
d = df.reset_index()
d.columns = ["instrument", "datetime", "close"]
n = d.groupby("datetime")["close"].apply(lambda s: int(s.notna().sum()))
print("每个日历日有价格的 instrument 数 (2026-05-01 起):")
print(n.to_string())

last = d[d["close"].notna()].groupby("instrument")["datetime"].max()
print(f"\ninstrument 总数 = {len(last):,}")
print("各 instrument 的最后有价日 分布 (top 10):")
print(last.value_counts().head(10).to_string())

# 只看股票 (排除指数)
stk = last[~last.index.str.startswith(("SH000", "SZ399"))]
print(f"\n个股数 = {len(stk):,}")
print("个股最后有价日 (top 10):")
print(stk.value_counts().head(10).to_string())
