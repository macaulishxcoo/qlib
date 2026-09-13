#!/usr/bin/env python3
"""Download SW (Shenwan) Level-1 industry index daily data from Tushare.

30 industry indices covering the full A-share market.  Used for industry
rotation signal validation and backtesting.

Usage
-----
    conda activate qlib
    python scripts/data_collector/download_sw_industry_index_v1.py
"""

from __future__ import annotations

import os
import time
from pathlib import Path

import pandas as pd
import tushare as ts

TOKEN_PATH = Path.home() / ".config/tushare/token"
DATA_ROOT = Path("data/external/tushare/sw_industry_index_v1")
RAW_DIR = DATA_ROOT / "raw"
NORMALIZED_DIR = DATA_ROOT / "normalized"
NORMALIZED_FILE = NORMALIZED_DIR / "sw_industry_daily.csv.gz"

# 30 Shenwan Level-1 industry indices
SW_INDICES = {
    "801010.SI": "农林牧渔", "801030.SI": "采掘", "801040.SI": "化工",
    "801050.SI": "钢铁", "801080.SI": "有色金属", "801110.SI": "家用电器",
    "801120.SI": "食品饮料", "801130.SI": "纺织服装", "801140.SI": "轻工制造",
    "801150.SI": "医药生物", "801160.SI": "公用事业", "801170.SI": "交通运输",
    "801180.SI": "房地产", "801200.SI": "商贸零售", "801210.SI": "休闲服务",
    "801230.SI": "综合", "801710.SI": "建筑材料", "801720.SI": "建筑装饰",
    "801730.SI": "电气设备", "801740.SI": "国防军工", "801750.SI": "计算机",
    "801760.SI": "传媒", "801770.SI": "通信", "801780.SI": "银行",
    "801790.SI": "非银金融", "801880.SI": "汽车", "801890.SI": "机械设备",
    "801950.SI": "煤炭", "801960.SI": "石油石化", "801970.SI": "环保",
}

START_DATE = "20150101"


def load_token() -> str:
    if TOKEN_PATH.is_file():
        return TOKEN_PATH.read_text(encoding="utf-8").strip()
    raise SystemExit("Tushare token missing")


def main():
    pro = ts.pro_api(load_token())
    RAW_DIR.mkdir(parents=True, exist_ok=True)

    all_frames = []
    for code, name in sorted(SW_INDICES.items()):
        target = RAW_DIR / f"{code}.csv.gz"
        if target.is_file():
            df = pd.read_csv(target, compression="gzip")
        else:
            try:
                df = pro.index_daily(ts_code=code, start_date=START_DATE)
                if df is None or df.empty:
                    print(f"  {code} {name}: empty")
                    continue
                df["industry_name"] = name
                df.to_csv(target, index=False, compression="gzip")
                time.sleep(0.3)
            except Exception as exc:
                print(f"  {code} {name}: FAILED {exc}")
                continue

        print(f"  {code} {name}: {len(df)} rows, {df['trade_date'].min()} ~ {df['trade_date'].max()}")
        all_frames.append(df)

    if not all_frames:
        print("[error] no data downloaded")
        return

    combined = pd.concat(all_frames, ignore_index=True)
    NORMALIZED_DIR.mkdir(parents=True, exist_ok=True)
    tmp = NORMALIZED_FILE.with_name(f".{NORMALIZED_FILE.name}.{os.getpid()}.tmp")
    combined.to_csv(tmp, index=False, compression="gzip")
    os.replace(tmp, NORMALIZED_FILE)
    print(f"\n[done] {len(combined):,} rows -> {NORMALIZED_FILE}")
    print(f"  indices: {combined['ts_code'].nunique()}, dates: {combined['trade_date'].min()} ~ {combined['trade_date'].max()}")


if __name__ == "__main__":
    main()
