#!/usr/bin/env python
"""对照实验：`IndNeutralize` 的行业口径 —— Tushare `stock_basic.industry` vs **申万一级**。

════════════════════════════════════════════════════════════════════════
背景
════════════════════════════════════════════════════════════════════════
Alpha101 有 7 个因子依赖 `IndNeutralize`（48/58/59/63/67/69/70），此前用
`stock_basic.industry`（Tushare 自有的粗分类）做去均值，Spearman 卡在 0.72~0.92，
报告中归因为「行业口径未标定」。

`tushare_factor/datapro_starter_kit/api_catalog.md` 里列出了此前未使用的**申万行业**接口，
实测**有权限**：

* `index_classify`   申万行业分类（L1 28 个）
* `index_member`     申万行业成分（带 `in_date`/`out_date`/`is_new`，PIT 就绪）
* `index_member_all` 申万**三级**行业全量映射（注意默认只返回 3000 行，需翻页）

中信（`ci_index_member`）/ 同花顺（`ths_index`）/ `sw_daily` **无权限**。

本脚本用申万一级替换行业映射，重跑那 7 个因子做 A/B 对照。

用法::

    python scripts/qdata/test_ind_neutralize_sw.py
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

import pandas as pd

_SCRIPTS = Path(__file__).resolve().parents[1]
for p in (str(_SCRIPTS), str(_SCRIPTS / "qdata"), str(_SCRIPTS / "jqdata")):
    if p not in sys.path:
        sys.path.insert(0, p)

CACHE = Path("output/qdata_factor_repro/cache")
CACHE.mkdir(parents=True, exist_ok=True)
SW_CACHE = CACHE / "sw_l1_map.pkl"

#: 依赖 `IndNeutralize` 的 7 个因子
FACTORS = ["alpha101_48", "alpha101_58", "alpha101_59",
           "alpha101_63", "alpha101_67", "alpha101_69", "alpha101_70"]


def sw_l1_map(use_cache: bool = True, level: str = "l1_name") -> pd.Series:
    """``ts_code -> 申万行业名``（``level`` 取 ``l1_name``/``l2_name``/``l3_name``）。

    ``index_member_all`` 有 3000 行默认上限，须翻页。缓存按 level 区分。
    """
    cache = SW_CACHE.with_name(SW_CACHE.stem + f"_{level}.pkl")
    if use_cache and cache.is_file():
        return pd.read_pickle(cache)
    from ts_env import load_token
    import tushare as ts
    pro = ts.pro_api(load_token())
    frames, off = [], 0
    while True:
        d = pro.index_member_all(limit=6000, offset=off)
        time.sleep(0.4)
        if d is None or d.empty:
            break
        frames.append(d)
        off += len(d)
        if len(d) < 6000:
            break
    if not frames:
        return pd.Series(dtype=object)
    df = pd.concat(frames, ignore_index=True).drop_duplicates("ts_code")
    s = df.set_index("ts_code")[level].astype(object)
    pd.to_pickle(s, cache)
    return s


def main() -> int:
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--levels", nargs="*", default=["l1_name", "l2_name", "l3_name"])
    ap.add_argument("--factors", nargs="*", default=FACTORS)
    args = ap.parse_args()

    import ts_market
    import xs_ops
    import repro_alpha101

    results = {}
    for level in args.levels:
        sw = sw_l1_map(level=level)
        print(f"\n{'='*70}\n申万 {level}：{len(sw)} 只股票，{sw.nunique()} 个行业\n{'='*70}")
        ts_market.industry_map = (lambda lv: (lambda use_cache=True: sw_l1_map(use_cache, lv)))(level)
        # ⚠️ `repro_alpha101` 的本地结果缓存键 = hash(factors, dates, ..., X.CFG)。
        #    它**不含行业来源**，故换行业后仍会命中上一级的缓存（实测 l1 与 l2 结果逐位相同）。
        #    把 level 注入 CFG 可让每一级各自缓存。
        xs_ops.CFG["INDUSTRY_LEVEL"] = level
        out_name = f"output/qdata_factor_repro/alpha101_ind_sw_{level}.csv"
        sys.argv = ["repro_alpha101.py", "--factors", *args.factors, "--out", out_name]
        repro_alpha101.main()
        p = Path(out_name)
        if p.is_file():
            d = pd.read_csv(p)
            results[level] = d.set_index("factor")["spearman_med"]

    if results:
        cmp = pd.DataFrame(results)
        with pd.option_context("display.width", 200):
            print(f"\n{'='*70}\n申万各级 vs 官方 Spearman 中位对照\n{'='*70}")
            print(cmp.to_string(float_format=lambda x: f"{x:.6f}"))
        base = {
            "alpha101_48": 0.920494, "alpha101_58": 0.717071, "alpha101_59": 0.736823,
            "alpha101_63": 0.877625, "alpha101_67": 0.757726, "alpha101_69": 0.872862,
            "alpha101_70": 0.881264,
        }
        cmp["原(Tushare行业)"] = cmp.index.map(base)
        print("\n含原口径对照：")
        print(cmp.to_string(float_format=lambda x: f"{x:.6f}"))
        cmp.to_csv("output/qdata_factor_repro/ind_neutralize_levels.csv")
        print("\n产出: output/qdata_factor_repro/ind_neutralize_levels.csv")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
