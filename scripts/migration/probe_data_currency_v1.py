#!/usr/bin/env python
"""检查数据时效: 今天是哪天, daily_basic 与 qlib store 各到哪天。"""
from datetime import datetime
from pathlib import Path

import pandas as pd

REPO = Path("/mnt/d/workspaces/qlib")
print("today (WSL):", datetime.now().strftime("%Y-%m-%d %H:%M %A"))

db = REPO / "data/external/tushare/a_share_daily_basic_pit_v1/normalized/daily_basic.csv.gz"
d = pd.read_csv(db, usecols=["trade_date"])
print("daily_basic last :", int(d["trade_date"].max()))

cal = pd.read_csv(Path.home() / ".qlib/qlib_data/cn_data_2026/calendars/day.txt",
                  header=None)[0]
print("store calendar last:", cal.iloc[-1], f"({len(cal)} 天)")

raw = REPO / "data/external/tushare/market_daily_v1/raw"
days = sorted(p.name.split(".")[0] for p in raw.glob("*.csv.gz") if p.name[:8].isdigit())
print("raw 行情 last     :", days[-1] if days else None, f"({len(days)} 个文件)")
