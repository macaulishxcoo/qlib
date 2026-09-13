#!/usr/bin/env python
"""实盘执行清单生成器 —— 五因子 top30 + 行业cap3 + 毒尾否决 (50万口径)。

跑的是与回测**完全相同**的管线, 只是网格换成"最新可用交易日":
  1. 取 daily_basic 中最新可用交易日作为 asof_date
  2. build_snapshot -> composite5 (EP/BM/股息/应计/成长 的 pct-rank 均值, 需 >=4 个非空)
  3. 剔除 ST; 对 l1_code + log_size 做 OLS 中性化
  4. 毒尾否决 (toxic > 0.90) -> score 置 -999
  5. 取 top30, 每个申万一级行业最多 3 只
  6. 按 50 万等权 + 100 股整手 -> 目标股数

产物:
  holdings_<date>.csv    持仓清单 (含目标市值/股数/行业/分数)
  orders_<date>.csv      相对上一期清单的买卖差异 (若提供 --prev)
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import qlib  # noqa: E402
from qlib.config import REG_CN  # noqa: E402

import backtest_a_share_value_growth_five_factor_industry_cap_v3 as v3  # noqa: E402
from backtest_a_share_value_growth_five_factor_industry_cap_v3 import (  # noqa: E402
    QLIB_DIR, STYLE_DIR, ST_INTERVALS, select_with_industry_cap,
)
from load_financials_extended_v1 import load_financials_extended  # noqa: E402
from backtest_a_share_value_quality_monthly_sensitivity_v4 import load_amount_avg  # noqa: E402
from run_daily_signal_pipeline_v1 import load_g2_series  # noqa: E402
from backtest_a_share_five_factor_daily_execution_v1 import (  # noqa: E402
    build_toxic_rank, apply_veto,
)

CAPITAL = 500_000.0
TOP_K = 30
CAP = 3
VETO_Q = 0.90
LOT = 100
OUT = Path(__file__).resolve().parents[1] / "output" / "live" / "five_factor_veto_top30"


def log(m):
    print(m, flush=True)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--capital", type=float, default=CAPITAL)
    ap.add_argument("--prev", type=Path, default=None, help="上一期 holdings CSV, 用于生成 orders")
    args = ap.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)

    qlib.init(provider_uri=str(QLIB_DIR), region=REG_CN)
    v3.ACCOUNT = int(args.capital)
    calendar = pd.DatetimeIndex(pd.to_datetime(
        pd.read_csv(QLIB_DIR / "calendars" / "day.txt", header=None)[0]))

    from backtest_a_share_value_quality_monthly_dailygrid_v6 import DAILY_BASIC
    db_dates = pd.read_csv(DAILY_BASIC, compression="gzip", usecols=["trade_date"])
    db_dates = pd.to_datetime(db_dates["trade_date"].astype(str), format="%Y%m%d")
    asof = db_dates.max()
    # 对齐到 qlib 日历中 <= asof 的最后一个交易日
    asof = calendar[calendar <= asof].max()
    log(f"asof_date = {asof.date()}   (daily_basic 最新 {db_dates.max().date()}, "
        f"qlib 日历最新 {calendar.max().date()})")

    log("[1/4] loading shared data ...")
    fin = load_financials_extended()
    fin_g2 = load_g2_series()
    industry = pd.read_csv(STYLE_DIR / "industry_l1_effective_intervals.csv.gz",
                           compression="gzip", dtype=str)
    industry["in_date"] = pd.to_datetime(industry["in_date"], errors="coerce")
    industry["out_date"] = pd.to_datetime(industry["out_date"], errors="coerce")
    st = pd.read_csv(ST_INTERVALS, compression="gzip",
                     parse_dates=["start_date", "end_date"])

    log("[2/4] building snapshot ...")
    # 直接取 asof 当日的 daily_basic 行作为 size 层。
    # 不要走 build_daily_grid(end=asof): 它只返回【月末】日期, 会把 size 停在月末,
    # 而 asof 可能已是最新月 -> 市值/中性化层比 asof 落后数周。
    db = pd.read_csv(DAILY_BASIC, compression="gzip",
                     usecols=["trade_date", "ts_code", "total_mv", "total_share", "dv_ttm"])
    db["datetime"] = pd.to_datetime(db["trade_date"].astype(str), format="%Y%m%d")
    size_latest = db[db["datetime"] == asof].copy()
    if size_latest.empty:
        raise SystemExit(f"daily_basic 在 {asof.date()} 无数据")
    size_latest["asof_date"] = asof
    size_latest = size_latest[["ts_code", "asof_date", "total_mv", "total_share", "dv_ttm"]]
    size_latest["size_control"] = size_latest["total_mv"].rank(pct=True)
    log(f"      size 层来自 {asof.date()}, {len(size_latest):,} 只")
    grid = pd.DataFrame({"rebalance_date": [asof], "asof_date": [asof]})
    universe = sorted(size_latest["ts_code"].unique())
    amount_avg = load_amount_avg(universe, calendar)
    snaps = v3.build_snapshots(fin, fin_g2, grid, industry, size_latest, st, amount_avg)
    if not snaps:
        raise SystemExit("snapshot build failed (无有效快照)")
    log(f"      候选数 = {int(list(snaps.values())[0]['neutral_composite'].notna().sum()):,}")

    log("[3/4] applying toxic veto ...")
    toxic = build_toxic_rank(calendar, end=str(asof.date()))
    if asof not in toxic.index:
        avail = toxic.index[toxic.index <= asof]
        if len(avail) == 0:
            raise SystemExit("toxic panel 无可用日期")
        log(f"      注意: {asof.date()} 不在毒尾面板, 回退到 {avail.max().date()}")
    snaps_v = apply_veto(snaps, toxic, TOP_K, CAP)

    log("[4/4] selecting top-%d (行业 cap %d) ..." % (TOP_K, CAP))
    frame = list(snaps_v.values())[0]
    sel = select_with_industry_cap(frame, TOP_K, CAP)
    if sel.empty:
        raise SystemExit("selection empty")

    # 最新收盘价 (用于整手)。注意 D.features 返回的索引是 **qlib 代码** (SH600050),
    # 而 sel["ts_code"] 是 tushare 代码 (600050.SH), 两者不可直接混用。
    from qlib.data import D
    from run_daily_signal_pipeline_v1 import qlib_symbol
    qmap = {c: qlib_symbol(c) for c in sel["ts_code"]}
    px = D.features(list(qmap.values()), ["$close"], start_time=str(asof.date()),
                    end_time=str(asof.date()), freq="day")
    price = px["$close"].droplevel(1) if isinstance(px.index, pd.MultiIndex) else px["$close"]

    per = args.capital / len(sel)
    rows = []
    for _, r in sel.iterrows():
        code = r["ts_code"]
        p = float(price.get(qmap[code], np.nan))
        lots = int(per // (LOT * p)) if (np.isfinite(p) and p > 0) else 0
        rows.append({
            "ts_code": code,
            "industry": r.get("l1_name", r.get("l1_code")),
            "score": float(r["neutral_composite"]),
            "close": p,
            "lots": lots,
            "shares": lots * LOT,
            "target_value": lots * LOT * p,
        })
    h = pd.DataFrame(rows).sort_values("target_value", ascending=False)
    h["weight"] = h["target_value"] / h["target_value"].sum()
    total = float(h["target_value"].sum())

    # --- 显式校验: asof 当日必须有非空价格 ---
    # 此前因 store 日历领先于行情 21 天, 产出过一份"30 只全 0 股"的清单且不报错。
    n_priced = int(np.isfinite(h["close"]).sum())
    if n_priced == 0:
        raise SystemExit(
            f"asof={asof.date()} 查不到任何价格 —— 数据可能落后于日历。"
            "请先运行 scripts/data_collector/update_daily_market_data_v1.py")
    if n_priced < len(h) * 0.5:
        log(f"      [warn] 仅 {n_priced}/{len(h)} 只有价格, 请核查数据完整性")

    path = OUT / f"holdings_{asof.date()}.csv"
    h.to_csv(path, index=False)

    log(f"\n=== 目标持仓 ({asof.date()}, 资金 {args.capital:,.0f}) ===")
    log(f"标的数 {len(h)}   实际投入 {total:,.0f}   仓位利用率 {total/args.capital:.3f}")
    log(h[["ts_code", "industry", "close", "lots", "target_value", "weight"]]
        .to_string(index=False, float_format=lambda x: f"{x:,.3f}"))
    ind = h["industry"].value_counts()
    log(f"\n行业分布 (top5): {dict(ind.head(5))}")

    if args.prev and args.prev.exists():
        prev = pd.read_csv(args.prev)
        new_codes = set(h["ts_code"]) - set(prev["ts_code"])
        gone = set(prev["ts_code"]) - set(h["ts_code"])
        kept = set(h["ts_code"]) & set(prev["ts_code"])
        log(f"\n=== 相对上一期 ({args.prev.name}) ===")
        log(f"  保留 {len(kept)}  买入 {len(new_codes)}  卖出 {len(gone)}")
        if new_codes:
            log(f"  买入: {sorted(new_codes)}")
        if gone:
            log(f"  卖出: {sorted(gone)}")
        pd.DataFrame({"action": ["BUY"] * len(new_codes) + ["SELL"] * len(gone),
                      "ts_code": sorted(new_codes) + sorted(gone)}).to_csv(
            OUT / f"orders_{asof.date()}.csv", index=False)

    (OUT / f"meta_{asof.date()}.json").write_text(json.dumps({
        "asof_date": asof.date().isoformat(), "capital": args.capital,
        "top_k": TOP_K, "industry_cap": CAP, "veto_q": VETO_Q,
        "n_holdings": int(len(h)), "invested": total,
        "utilization": total / args.capital,
        "n_priced": n_priced,
        "next_rebalance_hint": "每 10 个交易日调仓; 下次 = 本日 +10 交易日",
    }, indent=2, ensure_ascii=False))

    # --- 写入 live_ledger, 供 paper_trading_tracker_v1.py 消费 ---
    # 格式: output/live_ledger/signal_YYYY-MM-DD_<tag>.csv, 需含 ts_code 与 action
    LEDGER = Path(__file__).resolve().parents[1] / "output" / "live_ledger"
    LEDGER.mkdir(parents=True, exist_ok=True)
    sig = h[["ts_code", "industry", "close", "shares", "target_value", "weight", "score"]].copy()
    sig.insert(1, "action", "BUY")
    sig_path = LEDGER / f"signal_{asof.date()}_ffveto.csv"
    sig.to_csv(sig_path, index=False)
    log(f"已写出 live_ledger: {sig_path}")
    log(f"已写出: {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
