#!/usr/bin/env python
"""qdata Value 族补测 —— ``book_to_market``（需要资产负债表科目）。

════════════════════════════════════════════════════════════════════════
口径标定过程（2026-09-17 实测，6 只股票 × 438 个 stock-day）
════════════════════════════════════════════════════════════════════════
qdata 文档公式::

    book_to_market = (SE_without_MI_pri + DeferredTaxAssets_pri) / (ClosePrice × TotalShares)

其中 ``_pri`` 后缀**具有误导性** —— 实测用的是**最新已披露报告期的期末值**，不是"上期/期初"。

各候选口径的实测结果：

| 分子口径 | 中位相对误差 | corr |
|---|---|---|
| **期末归母权益 + 递延所得税资产** | **1.28e-11** ✅ | 0.99961 |
| 期末归母权益（不加 DTA） | 5.3e-02 | 0.99392 |
| 上期(期初)归母权益 + DTA | 1.1e-02 | 0.99947 |
| 上年报归母权益 + DTA | 1.1e-02 | 0.99967 |
| 上期归母权益（不加 DTA） | 6.9e-02 | 0.99745 |

**关键点：递延所得税资产（`defer_tax_assets`）必须加进去。** 这正是 `1/pb` 口径失败的原因
（Tushare 的 `pb` 用归母权益、不含 DTA，中位相对误差 0.0995）。

剩下的 19/438 个残差样本**全部落在 2026-08-28 之后**，即 §G2 的 qdata 未沉淀窗口，
与公式无关。

用法::

    python scripts/qdata/repro_value.py            # 用缓存（若有）
    python scripts/qdata/repro_value.py --refresh  # 强制重新取官方值
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

_SCRIPTS = Path(__file__).resolve().parents[1]
for p in (str(_SCRIPTS), str(_SCRIPTS / "jqdata"), str(_SCRIPTS / "qdata")):
    if p not in sys.path:
        sys.path.insert(0, p)

from jqdata.facsim.compare import compare_family, summarize  # noqa: E402
from qdata_env import QDataClient  # noqa: E402
from ts_env import load_token  # noqa: E402

FAMILY = "qdata_value"
FACTORS = ["book_to_market"]
SETTLE_DAYS = 30

#: 本地 daily_basic 全历史离线镜像（含 total_mv，单位万元）
DAILY_BASIC = Path("data/external/tushare/a_share_daily_basic_pit_v1/normalized/daily_basic.csv.gz")
CACHE = Path("output/qdata_factor_repro/cache")


def load_balancesheet(codes: list[str], start: str = "20230101", end: str = "20260910") -> dict[str, pd.DataFrame]:
    """取资产负债表（按公告日 PIT 对齐所需字段）。"""
    import tushare as ts
    pro = ts.pro_api(load_token())
    out: dict[str, pd.DataFrame] = {}
    for c in codes:
        d = pro.balancesheet(ts_code=c, start_date=start, end_date=end)
        time.sleep(0.5)
        # report_type=1 为合并报表
        d = d[d["report_type"].astype(str) == "1"].drop_duplicates(["end_date"])
        d = d.assign(ann_date=d["ann_date"].astype(int)).sort_values("end_date")
        out[c] = d
    return out


def load_total_mv(codes: list[str]) -> pd.DataFrame:
    """离线镜像取总市值（万元 → 元），避免占用 Tushare 配额。"""
    db = pd.read_csv(DAILY_BASIC, usecols=["ts_code", "trade_date", "total_mv"])
    db = db[db["ts_code"].isin(codes)].copy()
    db["trade_date"] = pd.to_datetime(db["trade_date"].astype(str))
    return db.pivot_table(index="trade_date", columns="ts_code", values="total_mv") * 1e4


def build_book_to_market(bs: dict[str, pd.DataFrame], mv: pd.DataFrame,
                         index: pd.DatetimeIndex) -> dict[str, pd.DataFrame]:
    """``(期末归母权益 + 期末递延所得税资产) / (收盘价 × 总股本)``。

    分母 ``ClosePrice × TotalShares`` 即总市值，故直接用 ``total_mv``。
    """
    out: dict[str, pd.DataFrame] = {}
    for c, d in bs.items():
        idx = index.intersection(mv.index)
        vals = []
        for t in idx:
            cand = d[d["ann_date"] <= int(t.strftime("%Y%m%d"))]
            if cand.empty:
                vals.append(np.nan)
                continue
            r = cand.iloc[-1]
            eq = float(r["total_hldr_eqy_exc_min_int"])
            dta = r.get("defer_tax_assets", np.nan)
            vals.append((eq + (float(dta) if pd.notna(dta) else 0.0)) / mv.loc[t, c])
        out[c] = pd.Series(vals, index=idx)
    return {"book_to_market": pd.DataFrame(out)}


def official_panel(codes: list[str], start: str, end: str, refresh: bool) -> dict[str, pd.DataFrame]:
    CACHE.mkdir(parents=True, exist_ok=True)
    pkl = CACHE / f"official_book_to_market_{start}_{end}.pkl"
    if pkl.is_file() and not refresh:
        return pd.read_pickle(pkl)
    cli = QDataClient()
    rec: dict[str, pd.Series] = {}
    for c in codes:
        for _ in range(4):
            try:
                rows = cli.factor_value(factor_name="book_to_market", ts_code=c,
                                        start_date=start.replace("-", ""),
                                        end_date=end.replace("-", ""))
                break
            except Exception as e:  # noqa: BLE001
                print(f"   重试 {c}: {str(e)[:60]}")
                time.sleep(6)
        else:
            continue
        if rows:
            rec[c] = pd.Series({pd.Timestamp(str(r["trade_date"])): float(r["factor_value"])
                                for r in rows}).sort_index()
    out = {"book_to_market": pd.DataFrame(rec).sort_index()}
    pd.to_pickle(out, pkl)
    return out


def main() -> int:
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--codes", nargs="*", default=["600519.SH", "000001.SZ", "000002.SZ",
                                                   "600036.SH", "002415.SZ", "000651.SZ"])
    ap.add_argument("--start", default="2026-06-01")
    ap.add_argument("--end", default="2026-09-10")
    ap.add_argument("--settle-days", type=int, default=SETTLE_DAYS)
    ap.add_argument("--refresh", action="store_true", help="强制重新取官方值")
    args = ap.parse_args()

    off = official_panel(args.codes, args.start, args.end, args.refresh)
    idx = off["book_to_market"].index
    local = build_book_to_market(load_balancesheet(args.codes), load_total_mv(args.codes), idx)

    def show(title: str, loc: dict, offi: dict, tag: str) -> None:
        print(f"\n===== {title} =====")
        d = compare_family(FAMILY, loc, offi, FACTORS)
        cols = ["factor", "verdict_med", "verdict", "n_overlap", "coverage",
                "max_abs_err", "med_rel_err", "corr"]
        with pd.option_context("display.width", 200):
            print(d[cols].to_string(index=False, float_format=lambda x: f"{x:.4g}"))
        print(summarize(d))
        out = Path("output/qdata_factor_repro") / f"value_compare{tag}.csv"
        d.to_csv(out, index=False)
        print(f"报告: {out}")

    show("全窗口（含 qdata 未沉淀尾部）", local, off, "")
    if args.settle_days > 0:
        cut = pd.Timestamp(args.end) - pd.Timedelta(days=args.settle_days)
        print(f"\n[settle] 排除 {cut.date()} 之后的 {args.settle_days} 个自然日")
        show(f"已沉淀窗口（--settle-days {args.settle_days}，判定口径）",
             {k: v.loc[:cut] for k, v in local.items()},
             {k: v.loc[:cut] for k, v in off.items()}, "_settled")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
