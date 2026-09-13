#!/usr/bin/env python
"""核查: 五因子线的流动性过滤是否实际生效 (候选数在两个门槛下完全相同 => 疑为 no-op)。"""
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, "/mnt/d/workspaces/qlib/scripts")
import qlib
from qlib.config import REG_CN

QLIB_DIR = Path.home() / ".qlib" / "qlib_data" / "cn_data_2026"
qlib.init(provider_uri=str(QLIB_DIR), region=REG_CN)

from backtest_a_share_value_quality_monthly_dailygrid_v6 import DAILY_BASIC, build_daily_grid
from backtest_a_share_value_quality_monthly_sensitivity_v4 import load_amount_avg

calendar = pd.DatetimeIndex(pd.to_datetime(
    pd.read_csv(QLIB_DIR / "calendars" / "day.txt", header=None)[0]))
grid, size_daily = build_daily_grid()
grid = grid[(grid["rebalance_date"] >= "2016-01-01") & (grid["rebalance_date"] <= "2026-06-30")]
universe = sorted(size_daily["ts_code"].unique())
print(f"universe ts_codes = {len(universe):,}  (例: {universe[:3]})")

aa = load_amount_avg(universe, calendar)
print(f"amount_avg shape = {aa.shape}  (index=日期, columns=?)")
print(f"columns 例: {list(aa.columns[:5])}")

d = grid["asof_date"].iloc[len(grid) // 2]
print(f"\n抽查 asof_date = {d.date()}")
row = aa.loc[d]
print(f"  该行非空数 = {int(row.notna().sum()):,} / {len(row):,}")
v = row.to_numpy(dtype=float) * 1000.0
v = v[np.isfinite(v)]
print(f"  有限值 n = {len(v):,}")
for thr, lbl in ((133_333_320, "1亿门槛"), (666_660, "50万门槛")):
    print(f"  {lbl:<10} 通过 = {(v >= thr).mean():.4f}")
print(f"  该行被 reindex 到快照 ts_code 后, 缺失比例需在 build_snapshots 内才可见")
