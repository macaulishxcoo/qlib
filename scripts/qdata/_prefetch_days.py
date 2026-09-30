#!/usr/bin/env python
"""预取指定交易日的全市场官方因子值（供 repro_quality_xs.py 使用）。"""
import sys, time
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent)); sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import repro_quality as R
import repro_quality_xs as X

DATES = sys.argv[1:] or ["20240910", "20241105", "20241216", "20240813"]
facs = R.all_factor_names()
t0 = time.time(); n = 0; tot = len(facs) * len(DATES)
for d in DATES:
    for f in facs:
        p = X.XCACHE / f"{f}__{d}.pkl"
        if p.is_file():
            n += 1
            continue
        X.official_day(f, d)
        n += 1
        if n % 25 == 0:
            el = time.time() - t0
            print(f"  …{n}/{tot} {el:.0f}s 剩余约 {el/max(n-(tot-len(facs)*len(DATES)),1)*0:.0f}s", flush=True)
print("完成", n, f"{time.time()-t0:.0f}s")
