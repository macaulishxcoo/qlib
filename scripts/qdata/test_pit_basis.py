#!/usr/bin/env python
"""线索 1：PIT 对齐基准 ``ann_date``（公告日） vs ``f_ann_date``（实际公告日）的 A/B 对照。

════════════════════════════════════════════════════════════════════════
线索来源
════════════════════════════════════════════════════════════════════════
`yoy_roa`(0.98367) / `yoy_roe`(0.98512) 的官方值**零并列**（N = uniq），
成因必为内层比值错位。上一轮已证伪「4 报告期偏移」（0.9626 / 0.9689，更差），
确认 `t-252` 交易日口径是对的 —— 所以偏差只能来自**历史时点的 PIT 取值**。

离线镜像实测：``ann_date != f_ann_date`` 的报告占 **1.79%**（57504 条中 1031 条），
与观察到的 **~1.6% 名次不一致率**高度吻合。样例显示 ``f_ann_date`` 常**晚一年**
（追溯重述版本），会改变历史时点的 PIT 取值。

现行实现（``ts_fin.FinMatrix``）用 ``ann_date`` 作 PIT 键，``f_ann_date`` 被丢弃。
本脚本做 A/B：

* **A 组**：``ann_date``（现行）
* **B 组**：``f_ann_date``（有值时替代，否则回退 ``ann_date``）

**不改动任何既有文件**：仅在运行时猴补丁 ``ts_fin._MIRROR_TABLES``（追加 ``f_ann_date`` 列）
与 ``ts_fin.FinMatrix.__init__``（替 PIT 键）。
注意 ``load_mirror_full`` 的缓存键**包含列清单**，追加列后会自动重新加载，不会误命中旧缓存。

用法::

    python scripts/qdata/test_pit_basis.py --window 2024
"""
from __future__ import annotations

import sys
import time
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
from ts_env import TSPanel             # noqa: E402
from xs_compare import compare_xs, summarize_xs  # noqa: E402

FACTORS = ["yoy_roa", "yoy_roe"]


def _ensure_f_ann_column() -> None:
    """运行时给 ``_MIRROR_TABLES`` 的每张表追加 ``f_ann_date``（会改变缓存键 ⇒ 重新加载）。"""
    for t, cols in TF._MIRROR_TABLES.items():
        if "f_ann_date" not in cols:
            cols.append("f_ann_date")


def _swap_to_f_ann(tables: dict[str, pd.DataFrame]) -> dict[str, pd.DataFrame]:
    """把 ``ann_date`` 替换成 ``f_ann_date``（有值者），模拟 B 组。"""
    out = {}
    for name, t in tables.items():
        if t is None or t.empty or "f_ann_date" not in t.columns:
            out[name] = t
            continue
        t = t.copy()
        fa = pd.to_datetime(t["f_ann_date"], errors="coerce")
        an = pd.to_datetime(t["ann_date"], errors="coerce")
        t["ann_date"] = fa.where(fa.notna(), an)
        out[name] = t
    return out


_ORIG_INIT = TF.FinMatrix.__init__
_SWAP = {"on": False}


def _patched_init(self, tables):
    _ORIG_INIT(self, _swap_to_f_ann(tables) if _SWAP["on"] else tables)


def build_variant(uni, all_codes, name, idx, dates, swap: bool):
    """只算 ``roa_ttm`` / ``roe_ttm`` 及其 ``shift(252)`` 比值。

    ⚠️ 早期版本调用 ``R.build_panels``（会建 ~40 个面板 × codes × 424 日），
    1500 只时内存爆掉、进程被杀。这里只建需要的 2 个面板（``to_panel`` 直接算），
    内存与耗时都降一个量级。
    """
    _SWAP["on"] = swap
    mats = {c: TF.FinMatrix(uni[c]) for c in all_codes}
    ni_ttm = R._series_fn("n_income", "ttm")
    npp_ttm = R._series_fn("n_income_attr_p", "ttm")
    ta = R._series_fn("total_assets", "raw")
    eq_inc = R._series_fn("total_hldr_eqy_inc_min_int", "raw")

    def roa_fn(m):
        return ni_ttm(m) / ta(m).replace(0, np.nan)

    def roe_fn(m):
        return npp_ttm(m) / eq_inc(m).replace(0, np.nan)

    out = {}
    for name_f, fn in (("yoy_roa", roa_fn), ("yoy_roe", roe_fn)):
        pnl = TF.to_panel(mats, fn, idx, all_codes).replace([np.inf, -np.inf], np.nan)
        pnl = pnl.reindex(idx)
        yoy = pnl / pnl.shift(252) - 1
        out[name_f] = R.xs_rank(yoy)
    del mats
    return out


def main() -> int:
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--window", default="2024", choices=["2024", "2026"])
    ap.add_argument("--dates", nargs="*",
                    default=["20240812", "20240813", "20240910", "20241105", "20241216"])
    ap.add_argument("--max-codes", type=int, default=None)
    args = ap.parse_args()

    TF.FinMatrix.__init__ = _patched_init
    _ensure_f_ann_column()

    uni = X.load_universe(args.window)
    all_codes = sorted(uni)
    if args.max_codes:
        all_codes = all_codes[: args.max_codes]
    print(f"本地股票池 {len(all_codes)} 只（窗口 {args.window}）", flush=True)

    # 统计 f_ann_date 的替换比例
    n_tot = n_diff = 0
    for c in all_codes[:1200]:
        for name, t in uni[c].items():
            if t is None or t.empty or "f_ann_date" not in t.columns:
                continue
            fa = pd.to_datetime(t["f_ann_date"], errors="coerce")
            an = pd.to_datetime(t["ann_date"], errors="coerce")
            n_tot += len(t)
            n_diff += int((fa.notna() & an.notna() & (fa != an)).sum())
    print(f"抽样 1200 只：f_ann_date 与 ann_date 不同的报告占 {n_diff / max(n_tot,1):.2%}")

    all_days = X.warmup_days(args.dates)
    idx, fields = X.market_days(all_days)
    panel = TSPanel(codes=all_codes, fields=fields)

    t0 = time.time()
    localA = build_variant(uni, all_codes, "A", idx, args.dates, swap=False)
    print(f"  A 组（ann_date）完成 {time.time()-t0:.1f}s", flush=True)
    t0 = time.time()
    localB = build_variant(uni, all_codes, "B", idx, args.dates, swap=True)
    print(f"  B 组（f_ann_date）完成 {time.time()-t0:.1f}s", flush=True)

    official = X.fetch_official(args.dates, FACTORS)

    print("\n===== A/B 对照：ann_date vs f_ann_date =====")
    res = []
    for f in FACTORS:
        loc = {f"{f}[ann]": localA[f], f"{f}[f_ann]": localB[f]}
        off = {f"{f}[ann]": official[f], f"{f}[f_ann]": official[f]}
        d = compare_xs("pit_basis", loc, off, list(loc))
        res.append(d.assign(base=f))
        with pd.option_context("display.width", 200):
            print(d.to_string(index=False, float_format=lambda x: f"{x:.6f}"))
        print(summarize_xs(d))

    out = Path("output/qdata_factor_repro/pit_basis_compare.csv")
    pd.concat(res, ignore_index=True).to_csv(out, index=False)
    print(f"\n产出: {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
