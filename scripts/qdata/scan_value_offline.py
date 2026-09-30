#!/usr/bin/env python
"""Value 族内层口径变体扫描（**离线**，复用 ``cache/value_local.pkl``）。

原理
----
``repro_value_xs.py`` 落盘的 ``value_local.pkl`` 含：

* ``<factor>``          —— 正式因子（rank 型是 ``rank/N``，故可**反解**出内层比值）
* ``<factor>__<variant>`` —— 备选内层比值（原样比值）

反解公式：``ratio = rank / (N * v)``，其中 ``v = 1/total_mv``（价值因子分母统一是市值），
故 ``分子 = rank * total_mv / N``。用它可以**离线**拼出新的分子组合，无需重建面板。

用法::

    python scripts/qdata/scan_value_offline.py --date 20240812
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
DB_RAW = REPO_ROOT / "data" / "external" / "tushare" / "a_share_daily_basic_pit_v1" / "raw"

FACTORS = ["earnings_cut_to_market", "ebitda_to_market", "etp5",
           "ncf_to_market", "ocf_to_market", "pegh5", "sales_to_market"]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", default="20240812")
    ap.add_argument("--out", default="value_variant_offline.csv")
    args = ap.parse_args()
    d = args.date
    t = pd.Timestamp(d)

    with (OUT / "cache" / "value_local.pkl").open("rb") as fh:
        L = pickle.load(fh)

    db = pd.read_csv(DB_RAW / f"{d}.csv.gz", usecols=["ts_code", "close", "total_mv"])
    db = db.set_index("ts_code")
    mv = db["total_mv"] * 1e4            # 万元 → 元
    close = db["close"]

    def official(f: str) -> pd.Series:
        with (XCACHE / f"{f}__{d}.pkl").open("rb") as fh:
            return pickle.load(fh)

    def raw_ratio(tag: str) -> pd.Series:
        """``<factor>__<variant>`` 原样比值。"""
        return L[tag].loc[t].dropna() if tag in L else pd.Series(dtype=float)

    def numer(tag: str) -> pd.Series:
        """从 rank/N 反解分子（分子 = rank × mv / N）。"""
        s = L[tag].loc[t].dropna()
        s = s[np.isfinite(s)]
        if s.empty:
            return s
        N = len(s)
        return (s * N).round() / N * mv.reindex(s.index)

    def score(f: str, s: pd.Series) -> dict | None:
        o = official(f)
        if o.empty or s.empty:
            return None
        N = len(o)
        orank = (o * N).round()
        idx = o.index.intersection(s.index)
        a = pd.to_numeric(o.reindex(idx), errors="coerce")
        b = pd.to_numeric(s.reindex(idx), errors="coerce")
        m = a.notna() & b.notna() & np.isfinite(a) & np.isfinite(b)
        if m.sum() < 100 or b[m].nunique() < 2:
            return None
        sp_shared = float(a[m].corr(b[m], method="spearman"))
        gap = (b[m].rank(method="max") - orank.reindex(idx)[m]).abs()
        return dict(n=int(m.sum()), N=N, sp_shared=sp_shared,
                    rank_gap_med=float(gap.median()),
                    rank_gap_p99=float(gap.quantile(0.99)))

    rows: list[dict] = []
    cand: dict[str, dict[str, pd.Series]] = {}

    # ---- sales / earnings / ebitda：只做横向对照（分子已在缓存或可反解）----
    if "sales_to_market" in L:
        cand["sales_to_market"] = {
            "基线(单季营业总收入)": numer("sales_to_market"),
            "TTM 营业总收入": raw_ratio("sales_to_market__ttm"),
        }
    cand["earnings_cut_to_market"] = {
        "归母净利润TTM（__attr）": raw_ratio("earnings_cut_to_market__attr"),
        "扣非净利润TTM（基线）": numer("earnings_cut_to_market"),
    }
    cand["ebitda_to_market"] = {
        "EBITDA_TTM（基线）": numer("ebitda_to_market"),
        "EBITDA 年报（__y）": raw_ratio("ebitda_to_market__y"),
    }
    cand["fcf_to_market"] = {
        "(OCF−投资流出)TTM（基线）": raw_ratio("fcf_to_market"),
        "Tushare free_cashflow": raw_ratio("fcf_to_market__ts"),
        "(OCF−购建固定资产)": raw_ratio("fcf_to_market__const"),
    }

    # ---- ocf / ncf：用反解出的分子重组 ----
    ocf_num = numer("ocf_to_market")                       # = OCF_TTM
    ncf_num = numer("ncf_to_market")                       # = OCF+ICF+Fin
    icf_num = numer("ocf_to_market") - numer("ocf_to_market")  # 占位
    # 用 (OCF+ICF) 变体反解 icf
    joint = raw_ratio("ncf_to_market__invonly")            # (OCF+ICF)/mv
    if not joint.empty:
        icf_num = joint * mv.reindex(joint.index) - ocf_num.reindex(joint.index)
        cand["ncf_to_market"] = {
            "OCF+ICF+Fin（基线）": numer("ncf_to_market"),
            "OCF+ICF": joint,
            "Fin 部分": (ncf_num - ocf_num.reindex(ncf_num.index)
                         - icf_num.reindex(ncf_num.index)) / mv.reindex(ncf_num.index),
        }
    cand["ocf_to_market"] = {
        "OCF_TTM/mv（基线）": numer("ocf_to_market"),
    }

    for f, variants in cand.items():
        for vname, s in variants.items():
            r = score(f, s)
            if r:
                rows.append(dict(factor=f, variant=vname, **r))

    dfo = pd.DataFrame(rows).sort_values(["factor", "sp_shared"], ascending=[True, False])
    pd.set_option("display.width", 220)
    print(dfo.to_string(index=False, float_format=lambda x: f"{x:.6f}"))
    dfo.to_csv(OUT / args.out, index=False)
    print(f"\n已写 {OUT / args.out}")

    # ---- 官方截面规模一览 ----
    print("\n官方截面（同一日）")
    for f in FACTORS:
        o = official(f)
        if not o.empty:
            print(f"  {f:26s} N={len(o):5d} uniq={o.nunique():5d} min={o.min():.6g} max={o.max():.6g}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
