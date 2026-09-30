#!/usr/bin/env python
"""交付 ②：反推 `yoy_ocf` 大并列块的**判定条件**（离线，用 2009-2024 全列镜像）。

════════════════════════════════════════════════════════════════════════
问题
════════════════════════════════════════════════════════════════════════
qdata 的 `yoy_ocf` 有一批股票共享**同一个名次**（20260811: 1767 只；20240812: 1670 只；
20241105: 1099 只）。并列块的值恰为块内**最大**名次（已确认 `method="max"`）：
    20240812: 块下方 1847 + 块内 1670 = 3517 = 值×N ✅
    20241105: 块下方 2226 + 块内 1099 = 3325 = 值×N ✅
说明 qdata 对这批股票**没有各给一个名次**，而是并成一组 —— 即 `filter=True` 的真实语义。

**已排除**：缺数据（99.9% 有本地 cashflow）、负 OCF（两组负值比例相近）、
交易所/板块（茅台 600519.SH 在块内、招商银行 600036.SH 不在；正常组 347 只 SH 全是 600xxx）。

**位置证据**：哨兵在**中段**（块下方占 38%~47%），排除"填最小值/最大值"，
**指向哨兵 = 同比 0**。

════════════════════════════════════════════════════════════════════════
本脚本做什么
════════════════════════════════════════════════════════════════════════
用 ``full/normalized/cashflow``（2009-2024 全列，期数充足）计算本地
``yoy_ocf = OCF_TTM_t / OCF_TTM_{t-252} - 1``，然后：

1. 统计"本地能算出 yoy" 与 "落入官方并列块" 的**交叉表** —— 直接检验"哨兵=不可算"假设；
2. 对**并列块内**的股票，检查若干候选条件（缺前期、前期为 0、前期为负、报告期不足 4 期）；
3. 对**非并列**股票做同样统计，用**判别力**（两组命中率之差）挑出真正的规则。

用法::

    python scripts/qdata/analyze_yoy_ocf_block.py --dates 20240812 20241105
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

import ts_fin as TF                    # noqa: E402
from qdata_env import QDataClient      # noqa: E402

CACHE = Path("output/qdata_factor_repro/cache")
OUT = Path("output/qdata_factor_repro")
#: 参与 TTM 计算的交易日跨度（同比 ≈ 一年）
LAG_TRADING_DAYS = 252


def official_series(factor: str, date: str) -> pd.Series:
    p = CACHE / "official_day" / f"{factor}__{date}.pkl"
    if p.is_file():
        d = pd.read_pickle(p)
        return pd.Series(d) if isinstance(d, dict) else d
    cli = QDataClient()
    for _ in range(5):
        rows = cli.factor_value(factor_name=factor, trade_date=date)
        if rows:
            s = pd.Series({r["ts_code"]: float(r["factor_value"]) for r in rows})
            CACHE.joinpath("official_day").mkdir(parents=True, exist_ok=True)
            pd.to_pickle(dict(s), p)
            return s
    return pd.Series(dtype=float)


def _to_ymd(v) -> int:
    """把 ``end_date`` 统一成 ``YYYYMMDD`` 整数。

    ⚠️ ``ts_fin.load_mirror_full`` 会把 ``end_date`` 转成 ``Timestamp``，
    此时 ``.astype(int)`` 得到的是**纳秒**（~1.7e18）而不是 ``YYYYMMDD``，
    直接与 ``20240812`` 比较会全部为 False、TTM 全 NaN。
    """
    if isinstance(v, (pd.Timestamp,)) or hasattr(v, "strftime"):
        return int(pd.Timestamp(v).strftime("%Y%m%d"))
    return int(v)


def per_stock_ocf() -> dict[str, dict]:
    """``{ts_code: {end_date(int YYYYMMDD): 累计 OCF}}``（来自 2009-2024 全列镜像）。"""
    tabs = TF.load_mirror_full(codes=None, tables={"cashflow": ["n_cashflow_act"]})
    cf = tabs.get("cashflow")
    if cf is None or cf.empty:
        return {}
    out: dict[str, dict] = {}
    for c, g in cf.groupby("ts_code", sort=False):
        g = g.dropna(subset=["end_date"])
        if g.empty:
            continue
        out[c] = dict(zip((_to_ymd(e) for e in g["end_date"]),
                          g["n_cashflow_act"].astype(float)))
    return out


def ttm(d: dict[int, float], asof: int) -> float:
    """``asof`` 时点可见的最近报告期的 OCF TTM = 本期累计 + 上年年报 − 上年同期累计。"""
    if not d:
        return np.nan
    ends = [e for e in d if e <= asof]
    if not ends:
        return np.nan
    q = max(ends)
    iy = q // 10000
    fy = [e for e in ends if e // 10000 == iy - 1 and e % 10000 == 1231]
    qp = [e for e in ends if e // 10000 == iy - 1 and e % 10000 == q % 10000]
    if not fy or not qp:
        return np.nan
    return d[q] + d[fy[0]] - d[qp[0]]


def shift_asof(asof: int, months_back: int = 12) -> int:
    """把 ``asof`` 往回推约一年（用 ``-12 个月`` 近似 252 交易日）。"""
    y, m, dd = asof // 10000, (asof // 100) % 100, asof % 100
    y -= months_back // 12
    return y * 10000 + m * 100 + dd


def main() -> int:
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--factor", default="yoy_ocf")
    ap.add_argument("--dates", nargs="*", default=["20240812", "20241105"])
    ap.add_argument("--out", default="yoy_ocf_block_analysis.csv")
    args = ap.parse_args()

    print("加载 2009-2024 全列现金流镜像 …", flush=True)
    ocf = per_stock_ocf()
    print(f"  {len(ocf)} 只股票有现金流数据", flush=True)

    rows = []
    for dt in args.dates:
        off = official_series(args.factor, dt)
        if off.empty:
            print(f"{dt}: 官方值取不到，跳过")
            continue
        off = pd.to_numeric(off, errors="coerce").dropna()
        N = len(off)
        cnt = off.value_counts()
        tie = float(cnt.index[0])
        tied = set(off.index[off == tie])
        print(f"\n=== {dt} === N={N} 并列块={len(tied)}（值 {tie:.10f} = {tie*N:.0f}/{N}）")

        d_now = int(dt)
        d_prev = shift_asof(d_now, 12)
        recs = []
        for c in off.index:
            d = ocf.get(c)
            cur = ttm(d, d_now) if d else np.nan
            prv = ttm(d, d_prev) if d else np.nan
            n_ends = len([e for e in (d or {}) if e <= d_now])
            recs.append(dict(
                ts_code=c, tied=(c in tied),
                has_ocf=d is not None,
                n_ends=n_ends,
                cur=cur, prv=prv,
                prv_missing=not np.isfinite(prv),
                prv_zero=bool(np.isfinite(prv) and abs(prv) < 1e-9),
                prv_neg=bool(np.isfinite(prv) and prv < 0),
                cur_neg=bool(np.isfinite(cur) and cur < 0),
                computable=bool(np.isfinite(cur) and np.isfinite(prv) and prv != 0),
            ))
        R = pd.DataFrame(recs)
        R["date"] = dt
        rows.append(R)

        # 判别力：并列块命中率 vs 非并列命中率
        cands = ["has_ocf", "prv_missing", "prv_zero", "prv_neg", "cur_neg", "computable"]
        n_ends_rule = R["n_ends"] < 4
        tb, nb = R[R.tied], R[~R.tied]
        print(f"  {'条件':16s}{'并列块命中':>11s}{'非并列命中':>11s}{'判别力':>9s}")
        for cond in cands:
            a, b = tb[cond].mean(), nb[cond].mean()
            print(f"  {cond:16s}{a:>11.1%}{b:>11.1%}{a-b:>9.1%}")
        a, b = n_ends_rule[R.tied].mean(), n_ends_rule[~R.tied].mean()
        print(f"  {'n_ends<4':16s}{a:>11.1%}{b:>11.1%}{a-b:>9.1%}")
        print(f"  并列块内可算 yoy 的比例：{tb['computable'].mean():.1%}"
              f"  非并列：{nb['computable'].mean():.1%}")

    if rows:
        allR = pd.concat(rows, ignore_index=True)
        allR.to_csv(OUT / args.out, index=False)
        print(f"\n产出: {OUT / args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
