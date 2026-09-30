#!/usr/bin/env python
"""Value 族：同时给出**两套判据**（用户口径 + 横截面 Spearman）。

官方因子值 = ``rank(inner)/N``（已实测，步长严格 ``1/N``）。若分母是市值，
则可**反解**官方内层比值：

    官方内层比值 = (官方 rank/N) × N × TotalMV / N ... 不成立（rank 只是名次）

⇒ 官方值的**绝对水平不可复原**，但「本地点位 vs 官方名次」的换算可比：

    官方名次 = round(官方值 × N)
    本地点位 = round(本地 rank/N × 本地 N)

于是可算**名次相对偏差** ``|本地点位 − 官方名次| / N`` 作为「用户口径」的代理，
并额外用**比值本身的分位**做对照：

* ``rank_rel_err``  = 名次差 / N 的中位数（0.01 相当于 1% 名次偏差）
* ``spearman``      = 横截面秩相关（现行判据）

对 `sales_to_market` / `earnings_cut_to_market` 这类官方 rank 与本地比值**单调一致**
的因子，两者同时达标；对 `ocf_to_market` 这类有少数极端错位的，两者的差别能定量说明
「是整体口径错还是少数股票错」。

用法::

    python scripts/qdata/value_dual_criterion.py --date 20240812
"""
from __future__ import annotations

import argparse
import pickle
import sys
from pathlib import Path

import numpy as np
import pandas as pd

_SCRIPTS = Path(__file__).resolve().parents[1]
for p in (str(_SCRIPTS), str(_SCRIPTS / "qdata")):
    if p not in sys.path:
        sys.path.insert(0, p)

REPO_ROOT = Path(__file__).resolve().parents[2]
OUT = REPO_ROOT / "output" / "qdata_factor_repro"
XCACHE = OUT / "cache" / "value_official_day"

#: 最终采用的口径（含 2026-09-21 标定结果）
FINAL = {
    "sales_to_market": "sales_to_market",
    "earnings_cut_to_market": "earnings_cut_to_market__attr",
    "ebitda_to_market": "ebitda_to_market",
    "etp5": "etp5",
    "ocf_to_market": "ocf_to_market",
    "ncf_to_market": "ncf_to_market",
    "pegh5": "pegh5",
    "fcf_to_market": "fcf_to_market",
}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dates", nargs="*",
                    default=["20240812", "20240910", "20241105", "20241216"])
    args = ap.parse_args()

    with (OUT / "cache" / "value_local.pkl").open("rb") as fh:
        L = pickle.load(fh)

    rows = []
    for f, tag in FINAL.items():
        if tag not in L:
            continue
        for d in args.dates:
            t = pd.Timestamp(d)
            p = XCACHE / f"{f}__{d}.pkl"
            if not p.is_file():
                continue
            with p.open("rb") as fh:
                o = pickle.load(fh)
            s = L[tag].loc[t].dropna()
            s = s[np.isfinite(s)]
            if f in ("fcf_to_market",):       # 原始比值型：直接比数值
                idx = o.index.intersection(s.index)
                a = pd.to_numeric(o.reindex(idx), errors="coerce")
                b = pd.to_numeric(s.reindex(idx), errors="coerce")
                m = a.notna() & b.notna() & np.isfinite(a) & np.isfinite(b) & (a != 0)
                rel = ((b[m] - a[m]) / a[m]).abs()
                rows.append(dict(factor=f, date=d, n=int(m.sum()),
                                 spearman=np.nan,
                                 rank_rel_err=np.nan,
                                 med_rel_err=float(rel.median()),
                                 p90_rel_err=float(rel.quantile(0.90))))
                continue
            N_o, N_l = len(o), len(s)
            orank = (o * N_o).round()
            lrank = (s.rank(method="max") / N_l * N_l).round()
            idx = o.index.intersection(s.index)
            a, b = orank.reindex(idx), lrank.reindex(idx)
            m = a.notna() & b.notna()
            if m.sum() < 200:
                continue
            sp = float(pd.to_numeric(o.reindex(idx)[m], errors="coerce")
                       .corr(s.reindex(idx)[m].rank(), method="spearman"))
            rel = (b[m] - a[m]).abs() / N_o
            rows.append(dict(factor=f, date=d, n=int(m.sum()),
                             spearman=sp,
                             rank_rel_err=float(rel.median()),
                             med_rel_err=np.nan, p90_rel_err=float(rel.quantile(0.90))))

    d = pd.DataFrame(rows)
    agg = (d.groupby("factor")
             .agg(n_days=("date", "nunique"),
                  spearman_med=("spearman", "median"),
                  spearman_min=("spearman", "min"),
                  rank_rel_err_med=("rank_rel_err", "median"),
                  rank_rel_err_p90=("p90_rel_err", "median"),
                  med_rel_err=("med_rel_err", "median"))
             .reset_index())
    pd.set_option("display.width", 200)
    print(agg.to_string(index=False, float_format=lambda x: f"{x:.6f}"))
    agg.to_csv(OUT / "value_dual_criterion.csv", index=False)

    print("\n【用户口径】名次相对偏差 ≤1% ⇒ 认为公式正确；【现行口径】Spearman ≥0.99 ⇒ APPROX")
    for _, r in agg.iterrows():
        if np.isfinite(r["rank_rel_err_med"]):
            user_ok = r["rank_rel_err_med"] <= 0.01
            crit_ok = r["spearman_med"] >= 0.99
            print(f"  {r['factor']:26s} 名次偏差中位={r['rank_rel_err_med']:.4%} "
                  f"→ 用户口径{'通过' if user_ok else '未通过'} | "
                  f"Spearman={r['spearman_med']:.6f} → {'通过' if crit_ok else '未通过'}")
        else:
            print(f"  {r['factor']:26s} 中位相对误差={r['med_rel_err']:.4%}（原始比值型）")
    print(f"\n已写 {OUT / 'value_dual_criterion.csv'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
