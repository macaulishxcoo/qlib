#!/usr/bin/env python
"""直接量测 qlib $amount 的量级, 判断五因子流动性门槛是否 binding。"""
from pathlib import Path

import numpy as np
import pandas as pd
import qlib
from qlib.config import REG_CN
from qlib.data import D

QLIB_DIR = Path.home() / ".qlib" / "qlib_data" / "cn_data_2026"
qlib.init(provider_uri=str(QLIB_DIR), region=REG_CN)

codes = ["SH600000", "SZ000001", "SZ300750", "SH688981", "SZ002415",
         "SH600519", "SZ000002", "SH601398"]
df = D.features(codes, ["$amount", "$volume", "$close"],
                start_time="2016-01-01", end_time="2026-06-30", freq="day")
df.columns = ["amount", "volume", "close"]
print("shape:", df.shape)
s = df.xs("SH600000", level=0)["amount"]
print(f"SH600000 $amount: median={s.median():,.0f}  p10={s.quantile(.1):,.0f}  "
      f"p90={s.quantile(.9):,.0f}")

print("\n各票 $amount 中位数 (原始单位) 与 x1000:")
for c in codes:
    try:
        v = df.xs(c, level=0)["amount"].median()
        print(f"  {c}: {v:>18,.1f}   x1000 = {v*1000:>22,.0f}")
    except KeyError:
        print(f"  {c}: 无数据")

# 全市场截面: 有多少比例的票 x1000 后 >= 门槛
inst = D.instruments(market="all")
allamt = D.features(inst, ["$amount"], start_time="2020-01-02", end_time="2020-01-10", freq="day")
allamt.columns = ["amount"]
v = allamt["amount"].to_numpy(dtype=float) * 1000.0
v = v[np.isfinite(v)]
print(f"\n2020-01-02~10 全市场样本 n={len(v):,}")
for thr, lbl in ((1.3333332e8, "1亿账户门槛 1.33e8"), (6.6666e5, "50万账户门槛 6.67e5")):
    print(f"  {lbl:<26} 通过比例 = {(v >= thr).mean():.4f}")
print(f"  中位数 = {np.median(v):,.0f}")
