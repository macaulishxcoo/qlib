#!/usr/bin/env python
"""测量 baostock 单只股票【全历史】5 分钟请求的耗时与体量, 用于估算全量下载成本。"""
import time

import baostock as bs

bs.login()
for code, start, end in (("sh.600000", "2018-01-01", "2026-06-30"),
                         ("sz.000001", "2018-01-01", "2026-06-30")):
    t0 = time.time()
    rs = bs.query_history_k_data_plus(
        code, "date,time,open,high,low,close,volume,amount",
        start_date=start, end_date=end, frequency="5")
    n = 0
    while rs.error_code == "0" and rs.next():
        n += 1
    dt = time.time() - t0
    print(f"{code} {start}..{end}: rows={n} elapsed={dt:.1f}s  ({dt/max(n,1)*1e6:.0f} us/row)")
bs.logout()
