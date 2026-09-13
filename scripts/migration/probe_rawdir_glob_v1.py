#!/usr/bin/env python
from pathlib import Path

f = Path("/mnt/d/workspaces/qlib/scripts/data_collector/update_daily_market_data_v1.py")
raw_dir = f.resolve().parents[2] / "data/external/tushare/market_daily_v1"
print("raw_dir =", raw_dir)
print("exists =", raw_dir.exists(), " is_dir =", raw_dir.is_dir())
g = list(raw_dir.glob("*.csv.gz"))
print("glob('*.csv.gz') ->", len(g))
g2 = list(raw_dir.iterdir())
print("iterdir ->", len(g2))
print("sample:", [p.name for p in g2[:3]])
days = sorted(p.name.split(".")[0] for p in g)
print("n days =", len(days), " first =", days[0] if days else None,
      " last =", days[-1] if days else None)
