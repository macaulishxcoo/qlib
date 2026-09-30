#!/usr/bin/env python
"""Value 族「官方 vs 本地」名次对照（离线，复用 ``cache/value_local.pkl``）。

输出每个因子的：
* 名次差的分布（中位 / p90 / p99 / max）
* 差异最大的 15 只股票及其官方/本地点位
* 官方名次 vs 本地点位的**分段一致性**（把名次分 20 段，看每段的一致率）

用于判断残差是「全池的系统性位移」还是「少数股票错位」。

用法::

    python scripts/qdata/diag_value_gap.py --date 20240812
"""
from __future__ import annotations

import argparse
import pickle
from pathlib import Path

import numpy as np
import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[2]
OUT = REPO_ROOT / "output" / "qdata_factor_repro"
XCACHE = OUT / "cache" / "value_official_day"

FACTORS = ["sales_to_market", "earnings_cut_to_market", "ebitda_to_market",
           "etp5", "ocf_to_market", "ncf_to_market", "pegh5"]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", default="20240812")
    ap.add_argument("--top", type=int, default=15)
    args = ap.parse_args()
    t = pd.Timestamp(args.date)

    with (OUT / "cache" / "value_local.pkl").open("rb") as fh:
        L = pickle.load(fh)

    for f in FACTORS:
        with (XCACHE / f"{f}__{args.date}.pkl").open("rb") as fh:
            o = pickle.load(fh)
        lv = L[f].loc[t].dropna()
        lv = lv[np.isfinite(lv)]
        N_o, N_l = len(o), len(lv)
        orank = (o * N_o).round()
        lrank = (lv * N_l).round()
        idx = o.index.intersection(lv.index)
        a, b = orank.reindex(idx), lrank.reindex(idx)
        m = a.notna() & b.notna()
        gap = (b[m] - a[m])
        print(f"\n=== {f}  官方N={N_o} 本地N={N_l} 交集={int(m.sum())} ===")
        print(f"  名次差: 中位|Δ|={gap.abs().median():.0f}  p90={gap.abs().quantile(0.90):.0f} "
              f"p99={gap.abs().quantile(0.99):.0f} max={gap.abs().max():.0f}  "
              f"符号: 正={int((gap>0).sum())} 负={int((gap<0).sum())}")
        # 分段一致率（按官方名次分 10 段，看本地名次是否落在同一段）
        bins = pd.qcut(a[m].rank(method="first"), 10, labels=False)
        same = (pd.Series(bins, index=a[m].index) ==
                pd.qcut(b[m].rank(method="first"), 10, labels=False))
        print("  官方名次分 10 段 → 本地点位落在同段比例: " +
              " ".join(f"{k}:{v:.2f}" for k, v in same.groupby(bins).mean().items()))
        worst = gap.abs().sort_values(ascending=False).head(args.top)
        print(f"  差异最大的 {args.top} 只:")
        for c in worst.index:
            print(f"    {c}  官方名次={int(a[c]):5d}  本地点位={int(b[c]):5d}  差={int(b[c]-a[c]):+6d}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
