#!/usr/bin/env python
"""口径标定探针：用**非横截面 passthrough 因子**的官方值反推财务口径。

这 5 条官方值是**原始比值**（不是 rank），可直接逐位比对：
  roe_ttm / roe_y / roe_ttm_lag63d / debt_asset_ratio / current_ratio / quick_ratio

用法：``python scripts/qdata/_calib_qg.py``（会读取 qg_official 的缓存，缺则跳过）
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

_SCRIPTS = Path(__file__).resolve().parents[1]
for p in (str(_SCRIPTS), str(_SCRIPTS / "jqdata"), str(_SCRIPTS / "qdata")):
    if p not in sys.path:
        sys.path.insert(0, p)

import ts_fin as TF  # noqa: E402
from qg_official import CODES, fetch_one  # noqa: E402
from qdata_env import QDataClient  # noqa: E402
from ts_env import load_panel  # noqa: E402

START, END, LOOKBACK = "20260601", "20260910", "20200101"


def official(factor: str, code: str, cli):
    return fetch_one(cli, factor, code, START, END)


def err(local: pd.Series, off: pd.Series) -> tuple[int, float, float, float]:
    idx = local.index.intersection(off.index)
    a, b = local.reindex(idx).astype(float), off.reindex(idx).astype(float)
    m = a.notna() & b.notna()
    if m.sum() == 0:
        return 0, np.nan, np.nan, np.nan
    d = (a[m] - b[m]).abs()
    mag = b[m].abs().mean()
    return int(m.sum()), float(d.max()), float((d / mag).median()), float((d / mag).max())


def main() -> int:
    cli = QDataClient()
    codes = CODES
    tabs = TF.load_all(codes, LOOKBACK, "20260917")
    mats = TF.build_matrices(tabs, codes)
    panel = load_panel(codes, LOOKBACK, END)
    dates = panel.dates

    def pnl(fn) -> dict[str, pd.Series]:
        out = {}
        for c in codes:
            m = mats[c]
            s = fn(m)
            s = pd.Series(np.asarray(s, float), index=pd.DatetimeIndex(m.df["ann_date"]))
            s = s[~s.index.duplicated(keep="last")].sort_index()
            out[c] = s.reindex(s.index.union(dates)).ffill().reindex(dates)
        return out

    print("=" * 100)
    print("① roe_ttm = NetProfit_Parent / TotalEquity —— 分母/分子变体")
    can = {
        "npp_ttm/eq_exc(期末)": lambda m: m.ttm("n_income_attr_p", True) / m.raw("total_hldr_eqy_exc_min_int"),
        "npp_ttm/eq_inc(期末)": lambda m: m.ttm("n_income_attr_p", True) / m.raw("total_hldr_eqy_inc_min_int"),
        "npp_ttm/(ta-tl)期末": lambda m: m.ttm("n_income_attr_p", True) / (m.raw("total_assets") - m.raw("total_liab")),
        "ni_ttm/eq_exc(期末)": lambda m: m.ttm("n_income", True) / m.raw("total_hldr_eqy_exc_min_int"),
        "npp_raw/eq_exc": lambda m: m.raw("n_income_attr_p") / m.raw("total_hldr_eqy_exc_min_int"),
        "npp_ttm/eq_exc(平均)": lambda m: m.ttm("n_income_attr_p", True) / ((m.raw("total_hldr_eqy_exc_min_int") + m.raw("total_hldr_eqy_exc_min_int").shift(1)) / 2),
        "npp_ttm/(ta-tl)平均": lambda m: m.ttm("n_income_attr_p", True) / (((m.raw("total_assets") - m.raw("total_liab")) + (m.raw("total_assets") - m.raw("total_liab")).shift(1)) / 2),
    }
    for c in codes:
        off = official("roe_ttm", c, cli)
        if off is None or off.empty:
            continue
        print(f"  -- {c}  官方值前3: {off.head(3).round(6).tolist()}")
        for k, fn in can.items():
            loc = pd.Series(pnl(fn)[c])
            n, mx, mrel, xrel = err(loc, off)
            print(f"     {k:26s} n={n:3d} max_abs={mx:.3e} med_rel={mrel:.3e} max_rel={xrel:.3e}")

    print("=" * 100)
    print("② roe_y（年度口径）")
    can_y = {
        "npp_y/eq_exc(期末)": lambda m: m.y("n_income_attr_p") / m.raw("total_hldr_eqy_exc_min_int"),
        "npp_y/eq_inc(期末)": lambda m: m.y("n_income_attr_p") / m.raw("total_hldr_eqy_inc_min_int"),
        "npp_y/eq_exc(平均)": lambda m: m.y("n_income_attr_p") / ((m.raw("total_hldr_eqy_exc_min_int") + m.raw("total_hldr_eqy_exc_min_int").shift(1)) / 2),
        "npp_ttm/eq_exc(期末)": lambda m: m.ttm("n_income_attr_p", True) / m.raw("total_hldr_eqy_exc_min_int"),
    }
    for c in codes:
        off = official("roe_y", c, cli)
        if off is None or off.empty:
            continue
        print(f"  -- {c}  官方值前3: {off.head(3).round(6).tolist()}")
        for k, fn in can_y.items():
            n, mx, mrel, xrel = err(pd.Series(pnl(fn)[c]), off)
            print(f"     {k:26s} n={n:3d} max_abs={mx:.3e} med_rel={mrel:.3e} max_rel={xrel:.3e}")

    print("=" * 100)
    print("③ roe_ttm_lag63d 与 roe_ttm(t-63交易日) 的关系")
    for c in codes:
        a = official("roe_ttm_lag63d", c, cli)
        b = official("roe_ttm", c, cli)
        if a is None or b is None or a.empty or b.empty:
            continue
        loc = b.shift(63)
        n, mx, mrel, xrel = err(loc, a)
        n2, mx2, mrel2, xrel2 = err(b, a)
        print(f"  -- {c}  官方 lag63d 前3={a.head(3).round(6).tolist()}")
        print(f"     roe_ttm.shift(63)  : n={n} max_abs={mx:.3e} med_rel={mrel:.3e}")
        print(f"     roe_ttm 无滞后      : n={n2} max_abs={mx2:.3e} med_rel={mrel2:.3e}")

    print("=" * 100)
    print("④ debt_asset_ratio / current_ratio / quick_ratio")
    simple = {
        "debt_asset_ratio": {"tl/ta(期末)": lambda m: m.raw("total_liab") / m.raw("total_assets"),
                             "tl/ta(平均)": lambda m: m.raw("total_liab") / ((m.raw("total_assets") + m.raw("total_assets").shift(1)) / 2)},
        "current_ratio": {"tca/tcl(期末)": lambda m: m.raw("total_cur_assets") / m.raw("total_cur_liab")},
        "quick_ratio": {"(tca-inv)/tcl": lambda m: (m.raw("total_cur_assets") - m.raw("inventories")) / m.raw("total_cur_liab")},
    }
    for fac, can2 in simple.items():
        for c in codes:
            off = official(fac, c, cli)
            if off is None or off.empty:
                continue
            print(f"  -- {fac} {c}  官方前3: {off.head(3).round(6).tolist()}")
            for k, fn in can2.items():
                n, mx, mrel, xrel = err(pd.Series(pnl(fn)[c]), off)
                print(f"     {k:26s} n={n:3d} max_abs={mx:.3e} med_rel={mrel:.3e} max_rel={xrel:.3e}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
