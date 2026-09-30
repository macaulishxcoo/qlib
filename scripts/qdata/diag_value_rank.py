#!/usr/bin/env python
"""诊断：为什么 ``earnings_cut_to_market`` 的**内层比值** Spearman ≈ 1，但正式因子只有 0.95。

用 ``repro_value_xs.py`` 落盘的 ``cache/value_local.pkl`` 做离线复检（无需重建面板）。

用法::

    python scripts/qdata/diag_value_rank.py --date 20240812
"""
from __future__ import annotations

import argparse
import pickle
import sys
from pathlib import Path

import numpy as np
import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[2]
OUT = REPO_ROOT / "output" / "qdata_factor_repro"
XCACHE = OUT / "cache" / "value_official_day"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", default="20240812")
    args = ap.parse_args()
    d = args.date

    with (OUT / "cache" / "value_local.pkl").open("rb") as fh:
        local = pickle.load(fh)

    def off(f):
        with (XCACHE / f"{f}__{d}.pkl").open("rb") as fh:
            return pickle.load(fh)

    t = pd.Timestamp(d)
    pd.set_option("display.width", 200)
    for f in ["earnings_cut_to_market", "sales_to_market", "ocf_to_market",
              "etp5", "pegh5", "ebitda_to_market", "ncf_to_market"]:
        o = off(f)
        lv = local[f].loc[t]
        N = len(o)
        orank = (o * N).round().astype("Int64")

        for tag in (f, f + "__attr", f + "__y", f + "__ttm"):
            if tag not in local:
                continue
            raw = local[tag].loc[t]
            idx = o.index.intersection(raw.index)
            a = pd.to_numeric(o.reindex(idx), errors="coerce")
            b = pd.to_numeric(raw.reindex(idx), errors="coerce")
            m = a.notna() & b.notna() & np.isfinite(a) & np.isfinite(b)
            if m.sum() < 30:
                continue
            # 用官方池内的名次（消除 N 差异）—— 直接比较比值次序
            sp_poolrank = a[m].corr(b[m].rank(), method="spearman")
            lrank = b.rank(method="max")
            diff = (lrank[m] - orank.reindex(idx)[m]).abs()
            print(f"{tag:38s} n={int(m.sum()):5d} 官方N={N:5d} 本地非空={int(raw.notna().sum()):5d} "
                  f"sp={sp_poolrank:.6f} 名次差中位={diff.median():.0f} p99={diff.quantile(0.99):.0f}")
        print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
