#!/usr/bin/env python
"""定位 load_amount_avg 返回零列的原因。"""
import sys
from pathlib import Path

import pandas as pd
import qlib
from qlib.config import REG_CN
from qlib.data import D

sys.path.insert(0, "/mnt/d/workspaces/qlib/scripts")
QLIB_DIR = Path.home() / ".qlib" / "qlib_data" / "cn_data_2026"
qlib.init(provider_uri=str(QLIB_DIR), region=REG_CN)

from backtest_a_share_value_quality_monthly_sensitivity_v4 import (  # noqa
    qlib_symbol, BT_START, BT_END, load_amount_avg,
)

codes = ["600000.SH", "000001.SZ", "002415.SZ"]
qcodes = [qlib_symbol(c) for c in codes]
print("ts_codes  ->", codes)
print("qlib_codes->", qcodes)

calendar = pd.DatetimeIndex(pd.to_datetime(
    pd.read_csv(QLIB_DIR / "calendars" / "day.txt", header=None)[0]))
warm = calendar[calendar.searchsorted(BT_START) - 30]
print(f"warm_start = {warm.date()}   BT_END = {BT_END}")

r1 = D.features(qcodes, ["$amount"], start_time=warm, end_time=BT_END, freq="day")
print(f"\nD.features(qlib_codes, $amount) -> shape={r1.shape}  cols={list(r1.columns)}")
if r1.empty:
    r2 = D.features(qcodes, ["$amount"], start_time=warm, end_time=BT_END, freq="day")
    print("  empty. 试 instruments(market='all') 加过滤:")
    r3 = D.features(D.instruments(market="all"), ["$amount"],
                    start_time="2020-01-02", end_time="2020-01-10", freq="day")
    print(f"  all-market -> shape={r3.shape}")
    r4 = D.features(["SH600000"], ["$amount"], start_time="2020-01-02",
                    end_time="2020-01-10", freq="day")
    print(f"  ['SH600000'] 2020 -> shape={r4.shape}")
    r5 = D.features(["SH600000"], ["$close"], start_time="2020-01-02",
                    end_time="2020-01-10", freq="day")
    print(f"  ['SH600000'] $close 2020 -> shape={r5.shape}")
    r6 = D.features(qcodes, ["$close"], start_time="2020-01-02",
                    end_time="2020-01-10", freq="day")
    print(f"  qcodes $close 2020 -> shape={r6.shape}")

out = load_amount_avg(codes, calendar)
print(f"\nload_amount_avg(['600000.SH','000001.SZ','002415.SZ']) -> {out.shape}")
print("非空计数:", out.notna().sum().to_dict())
