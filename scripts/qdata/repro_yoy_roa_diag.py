#!/usr/bin/env python
"""``yoy_roa`` / ``yoy_roe`` 残差诊断（对官方值做变体标定）。

背景
----
这两条因子是全库「零并列」的 FAIL：

```
yoy_roa  官方 N=4825  uniq=4825   ← 名次全互异 ⇒ 官方没做任何分组
yoy_roe  ...
```

已排除的假设（见 ``CONVENTIONS.md`` §5.7 / §5.9）：

| 假设 | 结果 |
|---|---|
| 报告期偏移（4 个披露日）替代 ``t-252`` 交易日 | **更差**（0.9626 / 0.9689 < 0.9837 / 0.9851） |
| PIT 基准换 ``f_ann_date`` | 略优但仅 +0.0014 / +0.0033，不足以解释 ~1.6% |

本脚本把候选变体一次性做全，逐个与官方单日全市场值比：

A. ``t-252`` 交易日（现行基线）
B. 4 个披露日偏移
C. ``f_ann_date`` 对齐
D. TTM 分子换 ``n_income_attr_p`` / ``n_income``（ROA/ROE 交叉）
E. 分母换期末 / (期初+期末)/2
F. 用 ``fina_indicator.roa``/``roe`` 的 **单期**值（已是累计，直接再 TTM）

用法::

    python scripts/qdata/repro_yoy_roa_diag.py --dates 20240812 20240910 20241105
"""
from __future__ import annotations

import argparse
import pickle
import sys
from pathlib import Path

import numpy as np
import pandas as pd

_SCRIPTS = Path(__file__).resolve().parents[1]
for p in (str(_SCRIPTS), str(_SCRIPTS / "qdata"), str(_SCRIPTS / "jqdata")):
    if p not in sys.path:
        sys.path.insert(0, p)

REPO_ROOT = Path(__file__).resolve().parents[2]
OUT = REPO_ROOT / "output" / "qdata_factor_repro"
XCACHE = OUT / "cache" / "qg_official_day"

FACTORS = ["yoy_roa", "yoy_roe"]


def official(factor: str, date: str) -> pd.Series:
    p = XCACHE / f"{factor}__{date}.pkl"
    if not p.is_file():
        return pd.Series(dtype=float)
    with p.open("rb") as f:
        return pickle.load(f)


def load_fin(max_codes: int | None = None) -> dict:
    """只加载诊断所需字段的镜像（比全量快很多）。"""
    import ts_fin as TF
    tables = {
        "income": ["n_income", "n_income_attr_p", "total_assets",
                   "total_hldr_eqy_inc_min_int", "total_hldr_eqy_exc_min_int",
                   "ann_date", "f_ann_date"],
        "balancesheet": ["total_assets", "total_hldr_eqy_inc_min_int",
                         "total_hldr_eqy_exc_min_int"],
    }
    tabs = TF.load_mirror_full(codes=None, tables=tables)
    codes = sorted(tabs["income"]["ts_code"].unique())
    if max_codes:
        codes = codes[:max_codes]
    return {t: df[df["ts_code"].isin(codes)] for t, df in tabs.items()}, codes


def rank_pct(s: pd.Series) -> pd.Series:
    """``rank/N``（并列取最大名次，与 qdata 一致）。"""
    v = s.dropna()
    v = v[np.isfinite(v)]
    if v.empty:
        return pd.Series(dtype=float)
    return v.rank(method="max") / len(v)


def spearman(a: pd.Series, b: pd.Series) -> tuple[float, int]:
    idx = a.index.intersection(b.index)
    x = pd.to_numeric(a.reindex(idx), errors="coerce")
    y = pd.to_numeric(b.reindex(idx), errors="coerce")
    m = x.notna() & y.notna() & np.isfinite(x) & np.isfinite(y)
    if m.sum() < 30 or x[m].nunique() < 2 or y[m].nunique() < 2:
        return np.nan, int(m.sum())
    return float(x[m].corr(y[m], method="spearman")), int(m.sum())


def build_variants(tabs: dict, codes: list[str], dates: pd.DatetimeIndex,
                   use_f_ann: bool = False) -> dict[str, pd.DataFrame]:
    """返回 ``{变体名: DataFrame(index=日期, columns=代码)}``（值为**内层比值**）。"""
    inc = tabs["income"].copy()
    bs = tabs["balancesheet"].copy()
    key = "f_ann_date" if use_f_ann and "f_ann_date" in inc.columns else "ann_date"

    # 每只股票：报告期序列（按公告日排序、去重取最早可得版本）
    panels: dict[str, dict[str, pd.Series]] = {}
    for name, df in (("inc", inc), ("bs", bs)):
        g = (df.dropna(subset=["end_date", key])
               .sort_values([key, "end_date"], kind="stable")
               .drop_duplicates(subset=["ts_code", "end_date"], keep="first"))
        panels[name] = g

    def ttm(df: pd.DataFrame, col: str) -> dict[str, pd.DataFrame]:
        """累计 → TTM：本期累计 + 上年年报 − 上年同期累计。

        返回 ``{代码: DataFrame(index=end_date, columns=[ann, val])}``。
        """
        d = df[["ts_code", key, "end_date", col]].dropna(subset=[col]).copy()
        d["year"] = d["end_date"].dt.year
        d["q"] = d["end_date"].dt.quarter
        out: dict[str, pd.DataFrame] = {}
        for c, g in d.groupby("ts_code", sort=False):
            g = g.sort_values("end_date")
            v = dict(zip(zip(g["year"], g["q"]), g[col].to_numpy(dtype=float)))
            if col in ("total_assets", "total_hldr_eqy_inc_min_int",
                       "total_hldr_eqy_exc_min_int"):
                vals = g[col].to_numpy(dtype=float)          # 时点量：直接用期末值
            else:
                vals = []
                for y, q in zip(g["year"], g["q"]):
                    cum = v.get((y, q), np.nan)
                    if q == 4:
                        vals.append(cum)
                    else:
                        fy = v.get((y - 1, 4), np.nan)
                        pq = v.get((y - 1, q), np.nan)
                        z = cum + fy - pq
                        vals.append(z if np.isfinite(z) else np.nan)
            out[c] = pd.DataFrame({"ann": g[key].to_numpy(),
                                   "val": np.asarray(vals, dtype=float)},
                                  index=pd.DatetimeIndex(g["end_date"]))
        return out

    # 构造 {代码: DataFrame(index=end_date, [ann, val])}
    ni = ttm(panels["inc"], "n_income")
    npp = ttm(panels["inc"], "n_income_attr_p")
    ta = ttm(panels["bs"], "total_assets")
    eq_inc = ttm(panels["bs"], "total_hldr_eqy_inc_min_int")
    eq_exc = ttm(panels["bs"], "total_hldr_eqy_exc_min_int")

    def to_daily(m: dict[str, pd.DataFrame]) -> pd.DataFrame:
        cols = {}
        for c in codes:
            g = m.get(c)
            if g is None or g.empty:
                continue
            t = pd.Series(g["val"].to_numpy(dtype=float),
                          index=pd.DatetimeIndex(g["ann"]))
            t = t[~t.index.isna()].sort_index()
            if t.index.has_duplicates:
                t = t.groupby(level=0).last()
            cols[c] = t.reindex(t.index.union(dates)).ffill().reindex(dates)
        return pd.DataFrame(cols)

    NI = to_daily(ni)
    NPP = to_daily(npp)
    TA = to_daily(ta)
    EQ = to_daily(eq_inc)
    EQX = to_daily(eq_exc)

    def div(a, b):
        b = b.replace(0, np.nan)
        return a / b

    out: dict[str, pd.DataFrame] = {}
    variants = {
        "roa_ni_over_ta_end": div(NI, TA),
        "roa_ni_over_ta_avg": div(NI, (TA + TA.shift(1)) / 2),
        "roa_npp_over_ta_end": div(NPP, TA),
        "roe_npp_over_eqi_end": div(NPP, EQ),
        "roe_ni_over_eqi_end": div(NI, EQ),
        "roe_npp_over_eqx_end": div(NPP, EQX),
        "roe_npp_over_eqi_avg": div(NPP, (EQ + EQ.shift(1)) / 2),
    }

    for base_name, base in variants.items():
        # A: t-252 交易日（现行）
        prev = base.shift(252)
        out[f"{base_name}__t252"] = div(base, prev) - 1
        out[f"{base_name}__t252_diff"] = base - prev
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dates", nargs="*",
                    default=["20240812", "20240910", "20241105", "20241216"])
    ap.add_argument("--max-codes", type=int, default=None)
    args = ap.parse_args()

    dates = pd.DatetimeIndex([pd.Timestamp(d) for d in args.dates])
    # ⚠️ ``t-252`` 需要 252 个交易日的**面板历史**：比对日必须放进一条包含热身日的日期轴，
    #    否则 shift(252) 全为 NaN（本脚本首版即踩此坑）。
    DB_RAW = REPO_ROOT / "data" / "external" / "tushare" / "a_share_daily_basic_pit_v1" / "raw"
    all_days = sorted(p.name[: -len(".csv.gz")] for p in DB_RAW.glob("*.csv.gz"))
    pos = {d: i for i, d in enumerate(all_days)}
    known = [d for d in args.dates if d in pos]
    if known:
        lo, hi = min(pos[d] for d in known), max(pos[d] for d in known)
        axis = pd.DatetimeIndex([pd.Timestamp(x) for x in all_days[max(0, lo - 300): hi + 1]])
    else:
        axis = dates
    print(f"股票池加载中；日期轴 {len(axis)} 天（含热身），比对日 {args.dates}", flush=True)
    tabs, codes = load_fin(args.max_codes)
    print(f"股票池 {len(codes)} 只", flush=True)
    variants = build_variants(tabs, codes, axis)
    print(f"候选变体 {len(variants)} 条\n", flush=True)

    off = {f: {d: official(f, d) for d in args.dates} for f in FACTORS}
    rows = []
    for vname, mat in variants.items():
        # 与官方值比：官方是 rank/N，故比较本地的 rank/N
        rec = {"variant": vname}
        for f in FACTORS:
            sps, meds = [], []
            for d in args.dates:
                o = off[f].get(d)
                if o is None or o.empty:
                    continue
                loc = mat.loc[pd.Timestamp(d)] if pd.Timestamp(d) in mat.index else None
                if loc is None:
                    continue
                lr = rank_pct(loc)
                sp, n = spearman(o, lr)
                if np.isfinite(sp):
                    sps.append(sp)
                # 中位相对误差：只对两边都有值的股票，用 rank 尺度换算回比值不可行，
                # 故这里用「名次相对差」的中位数作为辅助指标
                idx = o.index.intersection(lr.index)
                if len(idx) >= 30:
                    N = len(o)
                    meds.append(float((lr.reindex(idx) - o.reindex(idx)).abs().median() * N))
            rec[f + "_sp"] = float(np.median(sps)) if sps else np.nan
            rec[f + "_rank_gap"] = float(np.median(meds)) if meds else np.nan
        rows.append(rec)

    df = pd.DataFrame(rows).sort_values("yoy_roa_sp", ascending=False)
    pd.set_option("display.width", 200)
    print(df.to_string(index=False, float_format=lambda x: f"{x:.6f}"))
    df.to_csv(OUT / "yoy_roa_diag.csv", index=False)
    print("\n已写 output/qdata_factor_repro/yoy_roa_diag.csv")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
