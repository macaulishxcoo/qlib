#!/usr/bin/env python
"""阶段 A：**横截面基础设施实测验证**（Rank / Scale / VWAP / 逐元素口径）。

目的：在与官方相同的股票全集下，证明本地横截面算子语义正确。
只用**少量交易日**（默认 20260803~20260811，已在缓存里），秒级完成。

三个股票池变体
--------------
``official``  面板列 = 官方当日返回的 ts_code 集合（隔离「算子语义」与「股票池」）
``tushare``   面板列 = 全 Tushare 口径（量化股票池差异的影响）
``common``    两者交集

输出
----
1. 逐因子误差表（max/median 绝对误差、Spearman、覆盖率）
2. 关键因子的**逐股数值对照**（本地 vs 官方）
3. ``Rank`` 口径的定向证据（官方值是否恰为 ``rank/N``）
"""
from __future__ import annotations

import json
import sys
import warnings
from pathlib import Path

import numpy as np
import pandas as pd

warnings.filterwarnings("ignore")

_SCRIPTS = Path(__file__).resolve().parents[1]
for _p in (str(_SCRIPTS), str(_SCRIPTS / "qdata")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import alpha101_eval as E                       # noqa: E402
import xs_ops as X                              # noqa: E402
from qdata_env import QDataClient               # noqa: E402
from repro_alpha101 import (OFF_DAY_CACHE, build_vars, load_formula,  # noqa: E402
                            official_day)
from ts_market import load_market               # noqa: E402

OUT_DIR = Path(__file__).resolve().parents[2] / "output" / "qdata_factor_repro"

#: 探针因子：覆盖 纯逐元素 / 纯 Rank / VWAP / 比值 四类
PROBES = ["alpha101_101", "alpha101_54", "alpha101_33", "alpha101_42",
          "alpha101_41", "alpha101_53", "alpha101_12"]


def compute(panel, name: str, mask: pd.DataFrame | None = None) -> pd.DataFrame:
    env = E.build_env(build_vars(panel, mask))
    env.ind_mat = None
    return E.eval_formula(load_formula(name), env).replace([np.inf, -np.inf], np.nan)


def official_series(name: str, date: str, cli: QDataClient | None = None) -> pd.Series:
    cli = cli or QDataClient(qps=8, retries=5)
    s = official_day(cli, name, date)
    return pd.Series(s, dtype=float) if s else pd.Series(dtype=float)


def stats(local: pd.Series, off: pd.Series) -> dict:
    j = pd.DataFrame({"l": local, "o": off}).dropna()
    if j.empty:
        return dict(n=0, max_abs=np.nan, med_abs=np.nan, sp=np.nan,
                    mean_abs=np.nan, n_off=int(off.notna().sum()))
    d = (j["l"] - j["o"]).abs()
    sp = (j["o"].corr(j["l"], method="spearman")
          if j["l"].nunique() > 1 and j["o"].nunique() > 1 else np.nan)
    return dict(n=len(j), max_abs=float(d.max()), med_abs=float(d.median()),
                mean_abs=float(d.mean()), sp=float(sp),
                n_off=int(off.notna().sum()))


def main() -> int:
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", default="20260811")
    ap.add_argument("--start", default="20260803", help="面板起点（供 Delay/Delta 用）")
    ap.add_argument("--factors", nargs="*", default=PROBES)
    ap.add_argument("--show", type=int, default=6, help="逐股对照展示条数")
    ap.add_argument("--cfg", nargs="*", default=None, help="口径覆盖 形如 PRICE_MODE=fq")
    args = ap.parse_args()
    if args.cfg:
        kw = {}
        for kv in args.cfg:
            k, v = kv.split("=")
            kw[k] = int(v) if v.lstrip("-").isdigit() else v
        X.set_cfg(**kw)
        print(f"  [cfg] {kw}  (PRICE_MODE={X.CFG['PRICE_MODE']}, "
              f"RANK_METHOD={X.CFG['RANK_METHOD']}, FLAT={X.CFG['FLAT_SUSPENDED']})")

    cli = QDataClient(qps=8, retries=5)
    panel = load_market(args.start, args.date, fields="core")
    dt = pd.Timestamp(args.date)

    rows = []
    detail: dict[str, pd.DataFrame] = {}
    for f in args.factors:
        off = official_series(f, args.date, cli)
        if off.empty:
            print(f"  !! {f}: 官方无数据")
            continue
        ocodes = sorted(off.dropna().index)
        colmask = panel.C.columns.isin(ocodes)
        variants = {"official": "evalonly", "official_all": "all", "tushare": "none"}
        for vname, mode in variants.items():
            if mode == "none":
                m = None
            else:
                m = pd.DataFrame(True, index=panel.dates, columns=panel.C.columns)
                if mode == "all":
                    m.loc[:, ~colmask] = False      # 全历史都限制到官方股票池
                else:
                    m.loc[dt, ~colmask] = False     # 仅比对日限制
            loc = compute(panel, f, m).loc[dt]
            st = stats(loc, off)
            st.update(factor=f, universe=vname)
            rows.append(st)
            if vname == "official":
                detail[f] = pd.DataFrame({"local": loc, "official": off}).dropna()

    df = pd.DataFrame(rows)[["factor", "universe", "n", "n_off", "max_abs",
                             "med_abs", "mean_abs", "sp"]]
    print("\n===== 阶段 A：同口径股票池下的实测吻合度 =====")
    with pd.option_context("display.width", 200):
        print(df.to_string(index=False, float_format=lambda x: f"{x:.6g}"))
    df.to_csv(OUT_DIR / "phaseA_xs_validation.csv", index=False)

    print(f"\n===== 逐股数值对照（date={args.date}, universe=official）=====")
    for f, j in detail.items():
        print(f"\n--- {f} ---  （共同有效 {len(j)} 只，官方 {int(detail[f]['official'].notna().sum())} 只）")
        show = pd.concat([j.head(args.show // 2), j.tail(args.show // 2)])
        show = show.assign(abs_err=(show["local"] - show["official"]).abs())
        print(show.to_string(float_format=lambda x: f"{x:.10f}"))

    # ---- Rank 口径定向证据：官方名次 vs 本地名次（method=max） ----
    print("\n===== Rank 口径定向证据 =====")
    for f in ("alpha101_33", "alpha101_42"):
        if f not in detail:
            continue
        o = detail[f]["official"].dropna()
        n_off = int(round(1.0 / o.min()))          # 官方 Rank 的分母 = 1/min
        print(f"  {f}: 官方 N = 1/min(官方) = {n_off}；本地共同有效 {len(o)} 只")
        # 用 Rank 输入量本身构造名次做对照
        loc_val = detail[f]["local"]
        print(f"        本地 vs 官方 值域:  max|Δ|={(loc_val - o).abs().max():.3e}  "
              f"中位|Δ|={(loc_val - o).abs().median():.3e}  "
              f"Spearman={o.corr(loc_val, method='spearman'):.10f}")

    # alpha101_33 是纯 Rank，可把「官方名次 − 本地名次」算出来：应只差一个常数
    if "alpha101_33" in detail:
        j = detail["alpha101_33"]
        o = j["official"].dropna()
        N = int(round(1.0 / o.min()))
        loc = j["local"].dropna()
        # 本地名次（相对同一批股票，N=官方 N 的归一化）
        exact = (o * N).round() - (loc * len(loc)).round()
        print(f"  alpha101_33 官方名次 − 本地点名次（N_off={N}, N_loc={len(loc)}）分布："
              f"{exact.value_counts().head(8).to_dict()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
