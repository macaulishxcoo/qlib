#!/usr/bin/env python
"""探针: 申万行业指数日线 + 股票->行业 PIT 映射 的结构与覆盖率。"""
from pathlib import Path

import pandas as pd

EXT = Path("/mnt/d/workspaces/qlib/data/external/tushare")

p1 = EXT / "sw_industry_index_v1" / "normalized" / "sw_industry_daily.csv.gz"
p2 = EXT / "a_share_style_pit_v1" / "normalized" / "industry_l1_effective_intervals.csv.gz"

print("=== sw_industry_daily ===")
d = pd.read_csv(p1)
print("shape:", d.shape)
print("cols:", list(d.columns))
print(d.head(3).to_string())
for c in d.columns:
    if d[c].dtype == object and d[c].nunique() < 60:
        print(f"  {c}: {d[c].nunique()} uniques -> {sorted(d[c].unique())[:40]}")
    elif "date" in c.lower() or "trade" in c.lower():
        print(f"  {c}: {d[c].min()} .. {d[c].max()}")

print("\n=== industry_l1_effective_intervals ===")
e = pd.read_csv(p2)
print("shape:", e.shape)
print("cols:", list(e.columns))
print(e.head(5).to_string())
for c in e.columns:
    if e[c].dtype == object and e[c].nunique() < 80:
        print(f"  {c}: {e[c].nunique()} uniques -> {sorted(e[c].unique())[:40]}")

raw = EXT / "a_share_style_pit_v1" / "raw" / "industry_member_all"
print("\n=== raw industry_member_all ===")
print("exists:", raw.exists())
if raw.exists():
    fs = sorted(raw.rglob("*"))
    print("n files:", len(fs))
    for f in fs[:3]:
        print("  ", f.name)
    if fs and fs[0].is_file():
        x = pd.read_csv(fs[0], nrows=5)
        print(x.to_string())
