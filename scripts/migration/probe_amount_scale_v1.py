#!/usr/bin/env python
"""探针: 五因子线的流动性门槛到底是否 binding?

结果已知: 把 ACCOUNT 由 1 亿改成 50 万 (门槛 1.33 亿 -> 66.7 万, 降 200 倍),
候选数完全不变 (2,925)。说明该门槛根本不 binding。本脚本查明原因 (单位问题?)。
"""
from pathlib import Path
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, "/mnt/d/workspaces/qlib/scripts")
from backtest_a_share_value_quality_monthly_sensitivity_v4 import load_amount_avg  # noqa

import qlib  # noqa
from qlib.config import REG_CN  # noqa

QLIB_DIR = Path.home() / ".qlib" / "qlib_data" / "cn_data_2026"
qlib.init(provider_uri=str(QLIB_DIR), region=REG_CN)
calendar = pd.DatetimeIndex(pd.to_datetime(
    pd.read_csv(QLIB_DIR / "calendars" / "day.txt", header=None)[0]))
cal = calendar[(calendar >= "2016-01-01") & (calendar <= "2026-06-30")]
codes = ["600000.SH", "000001.SZ", "300750.SZ", "688981.SH", "002415.SZ"]

aa = load_amount_avg(codes, calendar)
print("load_amount_avg shape:", aa.shape)
d = cal[::120][:6]
for dt in d:
    if dt in aa.index:
        row = aa.loc[dt]
        print(f"  {dt.date()}  原始值: " +
              ", ".join(f"{c}={row.get(c, np.nan):,.1f}" for c in codes))
        print(f"              x1000 后: " +
              ", ".join(f"{c}={row.get(c, np.nan)*1000:,.0f}" for c in codes))

print("\n门槛 = (ACCOUNT//15)/0.05")
for acc in (100_000_000, 500_000):
    print(f"  ACCOUNT={acc:>12,} -> 门槛 {(acc//15)/0.05:>18,.0f}")
