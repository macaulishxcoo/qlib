#!/usr/bin/env python
"""探针: baostock 分钟级数据可得性 / 速度 / 体量。"""
import sys
import time
from pathlib import Path

ok = True
try:
    import baostock as bs
    print("baostock import OK")
except Exception as e:
    print("baostock import FAILED:", e)
    ok = False

if ok:
    lg = bs.login()
    print("login:", lg.error_code, lg.error_msg)
    # 单只股票全历史 5 分钟
    t0 = time.time()
    rs = bs.query_history_k_data_plus(
        "sh.600000",
        "date,time,code,open,high,low,close,volume,amount",
        start_date="2024-01-01", end_date="2024-03-31", frequency="5")
    rows = []
    while rs.error_code == "0" and rs.next():
        rows.append(rs.get_row_data())
    dt = time.time() - t0
    print(f"sh.600000 2024Q1 5min: rows={len(rows)} elapsed={dt:.2f}s")
    if rows:
        print("first:", rows[0])
        print("last :", rows[-1])
        # 一个交易日有多少根
        from collections import Counter
        c = Counter(r[0] for r in rows)
        print("bars per day (sample):", list(c.items())[:3])
    bs.logout()

print("--- existing collector ---")
p = Path(__file__).resolve().parents[1] / "scripts" / "data_collector" / "baostock_5min"
for f in sorted(p.rglob("*")):
    print("  ", f.relative_to(p.parent.parent.parent) if f.is_file() else f.name)
