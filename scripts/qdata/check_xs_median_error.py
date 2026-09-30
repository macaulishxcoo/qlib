#!/usr/bin/env python
"""补测：横截面因子的「数值差多少」（中位相对误差）。

════════════════════════════════════════════════════════════════════════
为什么要补这一步
════════════════════════════════════════════════════════════════════════
现有体系对横截面因子只用 **Spearman（排序一致度）** 判定，报告里的
``med_rel_err`` 是空的 —— 即**从未测过它们的数值差多少**。

而用户提出的判据是：「数值差不太多就算公式正确，不必完全一致」。
对 ``rank/N`` 型因子，这两件事可能严重不一致：

* 排序上 1.4% 的样本对调（Spearman 0.9864）**看起来很差**；
* 但值只差 1~2 个名次 ⇒ **中位相对误差可能只有 0.1%~0.2%**，按用户标准就是"对"。

本脚本对**横截面判据下判 FAIL 的因子**补算中位相对误差，给出两套判据的对照。

用法::

    python scripts/qdata/check_xs_median_error.py --window 2024
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

_SCRIPTS = Path(__file__).resolve().parents[1]
for p in (str(_SCRIPTS), str(_SCRIPTS / "qdata"), str(_SCRIPTS / "jqdata")):
    if p not in sys.path:
        sys.path.insert(0, p)

import repro_quality_xs as X  # noqa: E402

OUT = Path("output/qdata_factor_repro")


def main() -> int:
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--window", default="2024", choices=["2024", "2026"])
    ap.add_argument("--dates", nargs="*",
                    default=["20240812", "20240813", "20240910", "20241105", "20241216"])
    ap.add_argument("--max-codes", type=int, default=None)
    args = ap.parse_args()

    # 目标：当前横截面判据下判 FAIL 的因子
    s = pd.read_csv(OUT / "SUMMARY.csv")
    tgt = sorted(s[(s["判据"].astype(str).str.contains("横截面", na=False))
                   & (s["verdict_med"] == "FAIL")].factor)
    print(f"待补测 {len(tgt)} 个因子（横截面判据下 FAIL）")

    local = X.build_local(args.window, args.dates, tgt, args.max_codes)
    official = X.fetch_official(args.dates, tgt)

    rows = []
    for f in tgt:
        lo, of = local.get(f), official.get(f)
        if lo is None or of is None or lo.empty or of.empty:
            continue
        idx = lo.index.intersection(of.index)
        cols = lo.columns.intersection(of.columns)
        meds, sps, ns = [], [], []
        for t in idx:
            a = pd.to_numeric(of.loc[t, cols], errors="coerce")
            b = pd.to_numeric(lo.loc[t, cols], errors="coerce")
            m = a.notna() & b.notna() & np.isfinite(a) & np.isfinite(b)
            if m.sum() < 30:
                continue
            a2, b2 = a[m], b[m]
            # 中位相对误差：以官方值的量级为分母，避免 rank/N 的小量级放大
            denom = a2.abs().mean()
            if denom == 0:
                continue
            meds.append(float((a2 - b2).abs().median() / denom))
            sps.append(float(a2.corr(b2, method="spearman")))
            ns.append(int(m.sum()))
        if meds:
            rows.append(dict(factor=f, n_days=len(meds), n_stocks_med=int(np.median(ns)),
                             spearman_med=float(np.median(sps)),
                             med_rel_err=float(np.median(meds))))

    d = pd.DataFrame(rows).sort_values("med_rel_err")
    d["Spearman判"] = np.where(d.spearman_med >= 0.9999, "EXACT",
                        np.where(d.spearman_med >= 0.999, "GOOD",
                          np.where(d.spearman_med >= 0.99, "APPROX", "FAIL")))
    d["中位误差判"] = np.where(d.med_rel_err <= 1e-9, "EXACT",
                        np.where(d.med_rel_err <= 1e-4, "GOOD",
                          np.where(d.med_rel_err <= 1e-2, "APPROX", "FAIL")))
    with pd.option_context("display.width", 220):
        print(d[["factor", "spearman_med", "Spearman判", "med_rel_err", "中位误差判",
                 "n_days", "n_stocks_med"]].to_string(
            index=False, float_format=lambda x: f"{x:.6g}"))
    d.to_csv(OUT / "xs_median_error.csv", index=False)
    n1 = int(d["Spearman判"].isin(["EXACT", "GOOD", "APPROX"]).sum())
    n2 = int(d["中位误差判"].isin(["EXACT", "GOOD", "APPROX"]).sum())
    print(f"\n按 Spearman (>=0.99) 视为公式正确：{n1}/{len(d)}")
    print(f"按中位相对误差 (<=1%) 视为公式正确：{n2}/{len(d)}")
    print(f"产出: {OUT / 'xs_median_error.csv'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
