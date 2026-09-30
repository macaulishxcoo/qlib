#!/usr/bin/env python
"""主线 B：`t-252` **交易日**偏移 vs **4 个报告期**偏移 —— `yoy_roa` / `yoy_roe` 的 A/B 对照。

════════════════════════════════════════════════════════════════════════
为什么做这个实验
════════════════════════════════════════════════════════════════════════
`yoy_roa`(0.9837) / `yoy_roe`(0.9851) 的官方值**零并列**
（N = uniq = 5315 / 5318），说明 qdata 没做任何分组/裁剪，
偏差只能来自**内层比值本身**。财报数据是**阶梯函数**（只在披露日跳变），
因此「252 个交易日前的值」与「4 个报告期前的值」在报告边界附近会**落在不同报告期**上，
造成大偏差。

现行实现用的是交易日偏移：
    outp["yoy_roe"] = _div(roe_ttm, roe_ttm.shift(252)) - 1
本实验额外构造报告期偏移版本：
    yoy4 = roe_ttm / roe_ttm.shift(4) - 1     （在**披露序列**上 shift）

做法：猴子补丁 `repro_quality.build_inner_report` 追加两个新 key，
复用 `repro_quality_xs` 的全市场本地构造 + `xs_compare` 判据。
**不改动任何既有文件。**

用法::

    python scripts/qdata/test_yoy_alignment.py --window 2024
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

import repro_quality as R              # noqa: E402
import repro_quality_xs as X           # noqa: E402
import ts_fin as TF                    # noqa: E402
from xs_compare import compare_xs, summarize_xs  # noqa: E402

#: 需要对照的因子：原名(t-252 交易日) → 新增名(4 报告期)
PAIRS = [("yoy_roa", "yoy_roa_r4"), ("yoy_roe", "yoy_roe_r4")]
NEW = [n for _, n in PAIRS]
ALL = [f for pair in PAIRS for f in pair]


def _extra_report_factors(mats: dict, codes: list[str],
                          dates: pd.DatetimeIndex) -> dict[str, pd.DataFrame]:
    """构造「4 披露日偏移」版本的 yoy_roa / yoy_roe（复用 R 的 PANEL_SPECS 与 _series_fn）。"""
    def rs(m, spec: str) -> pd.Series:
        f, per = R.PANEL_SPECS[spec]
        return R._series_fn(f, per)(m)

    def sd(a: pd.Series, b: pd.Series) -> pd.Series:
        return a / b.replace(0, np.nan)

    def yoy4_of(fn):
        def g(m):
            x = fn(m)
            return sd(x, x.shift(4)) - 1
        return g

    # 与 build_inner 保持一致：ROA 分子 = n_income（含少数股东）；ROE 分子 = n_income_attr_p；
    # 分母 = 期末值（时点量 raw），权益取含少数股东权益
    def roa(m):
        return sd(rs(m, "ni_ttm"), rs(m, "ta"))

    def roe(m):
        return sd(rs(m, "npp_ttm"), rs(m, "eq_inc"))

    return {"yoy_roa_r4": TF.to_panel(mats, yoy4_of(roa), dates, codes),
            "yoy_roe_r4": TF.to_panel(mats, yoy4_of(roe), dates, codes),
            # 顺带给出「t-252 交易日偏移」的显式版本，作为 A 组（应与现行实现一致）
            "yoy_roa_s252": TF.to_panel(mats, roa, dates, codes),
            "yoy_roe_s252": TF.to_panel(mats, roe, dates, codes)}


def main() -> int:
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--window", default="2024", choices=["2024", "2026"])
    ap.add_argument("--dates", nargs="*",
                    default=["20240812", "20240813", "20240910", "20241105", "20241216"])
    ap.add_argument("--max-codes", type=int, default=None)
    args = ap.parse_args()

    # ---- 猴补丁：追加报告期偏移版本（不改任何既有文件）--------------------
    orig = R.build_inner_report

    def patched(mats, codes, dates):
        out = orig(mats, codes, dates)
        out.update(_extra_report_factors(mats, codes, dates))
        return out

    R.build_inner_report = patched

    dates = args.dates
    print(f"窗口={args.window} 比对日={dates}")

    local = X.build_local(args.window, dates, ALL + NEW, args.max_codes)
    # build_local 只对 RANK_EMPIRICAL 里的因子做 rank/N；这 4 个 key 不在其中，手工补
    for k in list(local):
        local[k] = R.xs_rank(local[k].replace([np.inf, -np.inf], np.nan))

    official = X.fetch_official(dates, [p[0] for p in PAIRS])
    # 官方只有原名；把官方值复制到对照名上（同一横截面比两次）
    for orig_name, new_name in PAIRS:
        if orig_name in official:
            official[new_name] = official[orig_name]

    print("\n===== 对照：t-252 交易日偏移  vs  4 报告期偏移 =====")
    res = {}
    for orig_name, new_name in PAIRS:
        d = compare_xs("yoy_align", local, official, [orig_name, new_name])
        res[orig_name] = d
        with pd.option_context("display.width", 200):
            print(d.to_string(index=False, float_format=lambda x: f"{x:.6f}"))
        print(summarize_xs(d))

    out = Path("output/qdata_factor_repro/yoy_alignment_compare.csv")
    pd.concat([v.assign(group=k) for k, v in res.items()]).to_csv(out, index=False)
    print(f"\n产出: {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
