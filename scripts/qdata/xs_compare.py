#!/usr/bin/env python
"""横截面因子专用比对器。

════════════════════════════════════════════════════════════════════════
为什么要单独一套判据
════════════════════════════════════════════════════════════════════════
qdata 的 242 个因子里有 **126 个（52%）含横截面算子**（`CrossSectionalRank` 72、
`Rank` 49、`IndNeutralize` 7、`Scale` 5，见 `FORMULA_AUDIT.md` §1）。

已实测标定（2026-09-17，`roa_ttm` @20260811）：

    CrossSectionalRank(x) = rank(x) / N
      rank 为**升序**排名，取值 1..N；N = 该横截面参与排名的股票数（实测 N=5430）
      官方值 min=0.000184(=1/5430) max=1.0000，mean=0.5001=(N+1)/(2N)，5430 行 5430 个互异值

**这意味着 `facsim.compare` 的绝对误差判据对横截面因子是错的**：
两个股票名次只差 10 位，因子值就只差 10/5430 = 0.0018，
而 `verdict`（maxerr）会因为个别名次漂移直接判 FAIL，掩盖"99% 名次都对"的事实。

正确的判据是**秩相关**：横截面因子的本质是"排序"，不是"数值"。

判据档位（按逐日 Spearman 的中位/最小）：

    EXACT   spearman_med >= 0.9999 且 spearman_min >= 0.999
    GOOD    spearman_med >= 0.999
    APPROX  spearman_med >= 0.99
    FAIL    其他

════════════════════════════════════════════════════════════════════════
用法
════════════════════════════════════════════════════════════════════════
    from xs_compare import compare_xs, summarize_xs
    df = compare_xs("qdata_quality", local, official, factor_list)
    print(summarize_xs(df))
"""
from __future__ import annotations

import numpy as np
import pandas as pd

EXACT, GOOD, APPROX, FAIL, NO_DATA = "EXACT", "GOOD", "APPROX", "FAIL", "NO_DATA"

#: 单日横截面至少要有这么多只股票才计算秩相关
MIN_CROSS_SECTION = 30


def _verdict(sp_med: float, sp_min: float) -> str:
    if not np.isfinite(sp_med):
        return NO_DATA
    if sp_med >= 0.9999 and sp_min >= 0.999:
        return EXACT
    if sp_med >= 0.999:
        return GOOD
    if sp_med >= 0.99:
        return APPROX
    return FAIL


def compare_xs(family: str, local: dict[str, pd.DataFrame],
               official: dict[str, pd.DataFrame],
               factors: list[str], min_n: int = MIN_CROSS_SECTION) -> pd.DataFrame:
    """逐日横截面 Spearman 比对。

    ``local`` / ``official``：``dict[因子名 -> DataFrame(index=交易日, columns=股票代码)]``，
    与 ``facsim.compare.compare_family`` 的入参一致，便于复用同一套数据加载。
    """
    rows = []
    for f in factors:
        lo, of = local.get(f), official.get(f)
        if lo is None or of is None or lo.empty or of.empty:
            rows.append(dict(factor=f, family=family, verdict_xs=NO_DATA, n_days=0,
                             n_stocks_med=0, spearman_med=np.nan, spearman_min=np.nan,
                             spearman_mean=np.nan))
            continue

        idx = lo.index.intersection(of.index)
        cols = lo.columns.intersection(of.columns)
        sps, ns = [], []
        for t in idx:
            a = pd.to_numeric(of.loc[t, cols], errors="coerce")
            b = pd.to_numeric(lo.loc[t, cols], errors="coerce")
            m = a.notna() & b.notna() & np.isfinite(a) & np.isfinite(b)
            if m.sum() < min_n:
                continue
            # 任一侧为常数时 spearman 无定义，跳过该日
            if a[m].nunique() < 2 or b[m].nunique() < 2:
                continue
            sps.append(a[m].corr(b[m], method="spearman"))
            ns.append(int(m.sum()))

        if not sps:
            rows.append(dict(factor=f, family=family, verdict_xs=NO_DATA, n_days=0,
                             n_stocks_med=0, spearman_med=np.nan, spearman_min=np.nan,
                             spearman_mean=np.nan))
            continue

        s = pd.Series(sps, dtype=float)
        rows.append(dict(
            factor=f, family=family,
            verdict_xs=_verdict(float(s.median()), float(s.min())),
            n_days=len(sps), n_stocks_med=int(np.median(ns)),
            spearman_med=float(s.median()), spearman_min=float(s.min()),
            spearman_mean=float(s.mean()),
        ))
    out = pd.DataFrame(rows)
    order = {EXACT: 0, GOOD: 1, APPROX: 2, FAIL: 3, NO_DATA: 4}
    return out.sort_values(["verdict_xs", "factor"],
                           key=lambda c: c.map(order) if c.name == "verdict_xs" else c
                           ).reset_index(drop=True)


def summarize_xs(df: pd.DataFrame) -> str:
    vc = df["verdict_xs"].value_counts().to_dict()
    parts = [f"{k}={vc.get(k, 0)}" for k in (EXACT, GOOD, APPROX, FAIL, NO_DATA)]
    ok = vc.get(EXACT, 0) + vc.get(GOOD, 0)
    return (f"{ok}/{len(df)} 横截面复现达标（EXACT+GOOD） | " + "  ".join(parts))


def rank_of(values: pd.Series) -> pd.Series:
    """把一列原始比值转成 qdata 口径的横截面因子值 ``rank/N``。

    ``rank(method="max")`` —— 并列取**最大名次**，即 ``count(x_i <= x)``。

    ⚠️ 早期版本用 ``method="average"``，理由写的是「官方 5430 行 5430 个互异值，
    说明横截面上几乎无并列」—— **该理由已证伪**：`roa_ttm` 只是**恰好**无并列，
    而实测有并列的因子多达 70/135，且并列块可以极大
    （`yoy_ocf` 1766 只、`eaa` 1167、`pa` 850，离散输出型因子唯一值只有 2~8 个）。
    算术证据：`yoy_ocf` 并列块的值为 ``3642/4927``，而该块下方 1875 只 + 块内 1767 只
    ``= 3642`` 恰为块内**最大**名次。详见 ``CONVENTIONS.md`` §3.4。
    """
    n = values.notna().sum()
    if n == 0:
        return values * np.nan
    return values.rank(method="max") / n


if __name__ == "__main__":
    print(__doc__)
    print(f"判据档位：EXACT/GOOD/APPROX/FAIL，单日最少 {MIN_CROSS_SECTION} 只股票。")


# ============================================================================
# 离散输出型因子的专用判据：「分档归属一致率」
# ============================================================================
# 背景（2026-09-18 实测）：Alpha101 有 11 个因子是**离散输出**，官方值只有 2~8 个档位
# （`alpha101_21/27/62/65/68` 只有 ±1 两档；`alpha101_58` 6 档、`alpha101_59` 8 档、
#  `alpha101_1` 5 档、`alpha101_7` 120 档）。
#
# ⚠️ 对这类因子**不能**用逐值一致率：档位值是 `rank_max/N`，块大小差几只就会让
#    整块的值在第 4 位小数上全变。实测 `alpha101_1` 官方 5 档值 −0.311169729 与
#    本地 −0.310742152 只差 4e-4，但**全档股票都算不一致** ⇒ 逐值一致率仅 **6.5%**，
#    完全掩盖了它 Spearman 0.9982 的事实。
#
# 正确做法：两侧各自 **dense-rank 成档位序号**，再比档位序号。
# 修正后 `alpha101_1` 的分档一致率 = **0.9988**（应为通过）。


def compare_agreement(family: str, local: dict[str, pd.DataFrame],
                      official: dict[str, pd.DataFrame],
                      factors: list[str], min_n: int = MIN_CROSS_SECTION) -> pd.DataFrame:
    """逐日「分档归属一致率」——离散输出型因子专用。

    对每个交易日：把两侧的值各自 ``rank(method="dense")`` 化为档位序号，
    再统计序号相等的比例。这样只考察**分档归属**，不受块大小微差造成的值漂移影响。
    """
    rows = []
    for f in factors:
        lo, of = local.get(f), official.get(f)
        if lo is None or of is None or lo.empty or of.empty:
            rows.append(dict(factor=f, family=family, verdict_agree=NO_DATA, n_days=0,
                             agree_med=np.nan, agree_min=np.nan, n_levels_med=0))
            continue
        idx = lo.index.intersection(of.index)
        cols = lo.columns.intersection(of.columns)
        ags, nlv = [], []
        for t in idx:
            a = pd.to_numeric(of.loc[t, cols], errors="coerce")
            b = pd.to_numeric(lo.loc[t, cols], errors="coerce")
            m = a.notna() & b.notna() & np.isfinite(a) & np.isfinite(b)
            if m.sum() < min_n:
                continue
            la = b[m].rank(method="dense")
            oa = a[m].rank(method="dense")
            ags.append(float((la == oa).mean()))
            nlv.append(int(oa.nunique()))
        if not ags:
            rows.append(dict(factor=f, family=family, verdict_agree=NO_DATA, n_days=0,
                             agree_med=np.nan, agree_min=np.nan, n_levels_med=0))
            continue
        s = pd.Series(ags, dtype=float)
        med, mn = float(s.median()), float(s.min())
        v = (EXACT if med >= 0.9999 and mn >= 0.999 else
             GOOD if med >= 0.99 else
             APPROX if med >= 0.95 else FAIL)
        rows.append(dict(factor=f, family=family, verdict_agree=v, n_days=len(s),
                         agree_med=med, agree_min=mn, n_levels_med=int(np.median(nlv))))
    out = pd.DataFrame(rows)
    order = {EXACT: 0, GOOD: 1, APPROX: 2, FAIL: 3, NO_DATA: 4}
    return out.sort_values(["verdict_agree", "factor"],
                           key=lambda c: c.map(order) if c.name == "verdict_agree" else c
                           ).reset_index(drop=True)
