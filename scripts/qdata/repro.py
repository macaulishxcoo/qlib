#!/usr/bin/env python
"""qdata 因子本地复现 —— 第一批（价量类，公式明确）。

公式来源：``output/qdata_factor_repro/factor_formulas.json``（从 ``factor_list`` 抽取）。
输入来源：``ts_env.load_panel``（Tushare 官方 daily/daily_basic/adj_factor）。

与聚宽一致的待标定问题（用变体对照解决）：
- ``Close`` 是否指**后复权**价（部分公式显式写 ``Close_hfq``）
- 滚动窗口**含不含当日**
- ``StdDev`` 用样本还是总体标准差
- ``DailyReturn`` 用简单收益还是对数收益

════════════════════════════════════════════════════════════════════════
⚠ 重要发现：qdata 尾部「未沉淀窗口」（settle window）
════════════════════════════════════════════════════════════════════════
qdata 官方因子在**最近约 20~25 个交易日**内不可由任何收盘价序列复现，
与公式无关。证据链（2026-09 实测）：

1. ``ma_20d`` / ``log_price`` / ``return_*d`` 在**全部**交易日精确匹配
   （max_abs_err ~5e-11，纯浮点舍入）→ 收盘价序列本身完全正确。
2. ``dif`` / ``dea`` / ``MACD`` 在 **2026-08-13 及之前**精确匹配，
   从 **2026-08-14 起**（全 6 只股票**同日**）出现 max 25~73 的偏差。
3. 把取数区间结束日改成 08-28 / 09-10 / 09-17，**断点恒为 08-14**，
   且三次取回的官方值逐位相同 → 不是"最近 N 天刷新"，是固定日历断点。
4. 用逆递推反解官方 dif 隐含的输入价（EMA 递推可精确反演）：
   08-13 前 隐含价/真实收盘 **恒等于 1.000000**；
   08-14 后 该比值变成均值≈1.00、标准差 1.2%~2.4% 的**随机噪声**。
   即官方 dif 的隐含输入不是任何一个合理的价格序列。
5. **000002.SZ 的复权因子自 2024-06-03 起完全恒定（期间无任何除权）**，
   其 dif 仍在 08-14 同日断裂 → 彻底排除除权/复权口径差异。
6. 隐含「复权因子」在尾部随机跳动 8.12~8.82（真实因子必为常数或单调），
   说明尾部值本身含噪。

结论：``dif``/``dea``/``MACD`` 一族是 qdata 用**另一条价格管道**（非 close）
计算的，该管道对新数据的沉淀周期约 20~25 个交易日。
**这些因子在未沉淀窗口内结构性不可复现**，不是公式问题。

处理方式：``--settle-days``（自然日，默认 30）从 ``--end`` 回退，
只在已沉淀区间上判定。截断到 2026-08-13 后本批 **15/15 全部精确通过**。
════════════════════════════════════════════════════════════════════════
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

from jqdata.facsim import ops as O  # noqa: E402
from jqdata.facsim.compare import compare_family, summarize  # noqa: E402
from qdata_env import QDataClient  # noqa: E402
from ts_env import TSPanel  # noqa: E402

FAMILY = "qdata_batch1"

#: qdata 尾部未沉淀窗口（自然日）。见模块 docstring 的证据链。
#: 实测断点 2026-08-14 距数据末端 2026-09-10 为 27 个自然日，
#: 取 30 留出安全边界。仅对 EMA 族（dif/dea/MACD）有影响，
#: 但统一施加可避免逐因子特判。
SETTLE_DAYS_DEFAULT = 30

# 本批实现的因子（对应 factor_list 的 factor_name）
IMPLEMENTED = [
    "dif", "dea", "MACD", "ma_20d",
    "return_5d", "return_21d", "return_42d", "return_63d", "return_126d", "return_252d",
    "return_std_21d", "return_std_42d", "return_std_63d",
    "sharpe_60d", "log_price",
]


def build(panel: TSPanel) -> dict[str, pd.DataFrame]:
    """按 factor_list 的公式实现。默认：后复权价、窗口含当日、样本标准差、简单收益。"""
    C, O_, H, L = panel.C, panel.O, panel.H, panel.L
    ret = C.pct_change()
    out: dict[str, pd.DataFrame] = {}

    # ---- MACD 组（公式：DIF=EMA(C,12)-EMA(C,26)；DEA=EMA(DIF,9)；MACD=2*(DIF-DEA)）----
    dif = O.ema(C, 12) - O.ema(C, 26)
    dea = O.ema(dif, 9)
    out["dif"], out["dea"] = dif, dea
    out["MACD"] = 2 * (dif - dea)

    # ---- 均线 ----
    out["ma_20d"] = O.ma(C, 20)

    # ---- 区间收益：Product(1+DailyReturn, window) - 1 ----
    for n in (5, 21, 42, 63, 126, 252):
        out[f"return_{n}d"] = (1 + ret).rolling(n).apply(np.prod, raw=True) - 1

    # ---- 收益标准差 ----
    for n in (21, 42, 63):
        out[f"return_std_{n}d"] = ret.rolling(n).std(ddof=1)

    # ---- 夏普 ----
    out["sharpe_60d"] = ret.rolling(60).mean() / ret.rolling(60).std(ddof=1)

    # ---- 对数价格（公式显式写 Close_hfq）----
    out["log_price"] = np.log(C)

    return out


def official_panel(codes: list[str], factors: list[str], start: str, end: str,
                   use_cache: bool = True) -> dict[str, pd.DataFrame]:
    """取 qdata ``factor_value`` 官方值 → dict[factor -> DataFrame(date × code)]。

    ⚠ **不用 offset 分页**：实测该接口的分页会返回**重复行**（124 条重复 / 涉及 3 个日期），
    并可能漏行。改为按 ``(factor_name, ts_code)`` 单取——每次 ≤ 交易日数行，
    远低于 6000 上限，天然无分页。
    """
    import pickle
    from pathlib import Path as _P
    cache = _P("output/qdata_factor_repro/cache")
    cache.mkdir(parents=True, exist_ok=True)
    cname = cache / f"official_{abs(hash((tuple(codes), tuple(factors), start, end))) % 10**12}.pkl"
    if use_cache and cname.is_file():
        print("  [qdata] 官方因子缓存命中")
        return pickle.load(open(cname, "rb"))

    cli = QDataClient()
    s_c, e_c = start.replace("-", ""), end.replace("-", "")
    rec: dict[str, dict[str, pd.Series]] = {f: {} for f in factors}
    n = 0
    for c in codes:
        for f in factors:
            rows = cli.factor_value(factor_name=f, ts_code=c,
                                    start_date=s_c, end_date=e_c)
            n += 1
            if not rows:
                continue
            d = pd.DataFrame(rows).drop_duplicates(subset=["trade_date"])
            d["trade_date"] = pd.to_datetime(d["trade_date"])
            rec[f][c] = d.set_index("trade_date")["factor_value"].astype(float)
        print(f"    …官方因子 {c} 完成（累计 {n} 次调用）")
    out = {f: pd.DataFrame(v).sort_index() for f, v in rec.items() if v}
    if use_cache:
        pickle.dump(out, open(cname, "wb"))
    print(f"  [qdata] 官方因子已取回并缓存（{len(out)} 个因子）")
    return out


def main() -> int:
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--codes", nargs="*",
                    default=["600519.SH", "000001.SZ", "000002.SZ",
                             "600036.SH", "002415.SZ", "000651.SZ"])
    ap.add_argument("--start", default="2026-06-01")
    ap.add_argument("--end", default="2026-09-10")
    ap.add_argument("--lookback", default="2024-06-01",
                    help="面板起点（需覆盖 252 日回看）")
    ap.add_argument("--settle-days", type=int, default=SETTLE_DAYS_DEFAULT,
                    help="排除末尾 N 个自然日（qdata 未沉淀窗口，见模块 docstring）；0=不排除")
    args = ap.parse_args()

    from ts_env import load_panel

    panel = load_panel(args.codes, args.lookback, args.end)
    local = build(panel)
    print(f"  本地实现 {len(local)} 个：{sorted(local)[:6]} …")

    off = official_panel(args.codes, IMPLEMENTED, args.start, args.end)
    cols = ["factor", "verdict_med", "verdict", "n_overlap", "coverage",
            "max_abs_err", "med_rel_err", "corr"]

    def _show(title: str, loc: dict, offi: dict, tag: str) -> pd.DataFrame:
        print(f"\n===== {title} =====")
        d = compare_family(FAMILY, loc, offi, IMPLEMENTED)
        with pd.option_context("display.width", 200):
            print(d[cols].to_string(index=False, float_format=lambda x: f"{x:.4g}"))
        print("\n" + summarize(d))
        out = Path("output/qdata_factor_repro") / f"batch1_compare{tag}.csv"
        d.to_csv(out, index=False)
        print(f"报告: {out}")
        return d

    # 1) 全窗口（含未沉淀尾部）——诊断用
    df = _show("全窗口（含 qdata 未沉淀尾部）", local, off, "")

    # 2) 已沉淀窗口——判定用
    if args.settle_days > 0:
        cut = pd.Timestamp(args.end) - pd.Timedelta(days=args.settle_days)
        print(f"\n[settle] 排除 {cut.date()} 之后的 {args.settle_days} 个自然日")
        loc_s = {k: v.loc[:cut] for k, v in local.items()}
        off_s = {k: v.loc[:cut] for k, v in off.items()}
        _show(f"已沉淀窗口（--settle-days {args.settle_days}，判定口径）",
              loc_s, off_s, "_settled")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
