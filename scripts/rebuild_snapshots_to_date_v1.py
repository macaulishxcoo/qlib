#!/usr/bin/env python
"""把 50 万口径的 10 交易日快照网格【延伸】到最新交易日, 供月度监测使用。

⚠ 绝不覆盖 snapshots_500k_10day.pkl
    那是冻结的研究产物, 所有已发布数字(交付总览/决策记录)都基于它。
    覆盖它会让历史结果静默改变, 且不可追溯。故本脚本写到独立的新文件
    snapshots_500k_10day_extended.pkl。

用途: 监测脚本的"承重墙检查"(毒尾否决的滚动 12 个月贡献)此前读冻结快照,
      止于 2026-06-23, 每月跑都是同一组数字 —— 等于复读。
      本脚本让该检查能随新数据推进。

方法: build_ten_day_grid 以模块级 BT_END 为截止日, 故把 BT_END 临时改为
      最新可用交易日(store 日历与 daily_basic 取较小者), 其余逻辑完全不动,
      以保证延伸部分与研究部分同口径。
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import qlib  # noqa: E402
from qlib.config import REG_CN  # noqa: E402

import backtest_a_share_value_growth_five_factor_industry_cap_v3 as v3  # noqa: E402
from backtest_a_share_value_growth_five_factor_industry_cap_v3 import (  # noqa: E402
    QLIB_DIR, STYLE_DIR, ST_INTERVALS, BT_START,
)
from backtest_a_share_value_quality_monthly_sensitivity_v4 import load_amount_avg  # noqa: E402
from load_financials_extended_v1 import load_financials_extended  # noqa: E402
from run_daily_signal_pipeline_v1 import load_g2_series  # noqa: E402
import backtest_a_share_five_factor_daily_execution_v1 as ex  # noqa: E402
from backtest_a_share_five_factor_daily_execution_v1 import OUT  # noqa: E402
from backtest_a_share_value_quality_monthly_dailygrid_v6 import DAILY_BASIC  # noqa: E402

CAPITAL = 500_000.0
CACHE_OUT = OUT / "snapshots_500k_10day_extended.pkl"


def log(m):
    print(m, flush=True)


def main() -> int:
    qlib.init(provider_uri=str(QLIB_DIR), region=REG_CN)
    calendar = pd.DatetimeIndex(pd.to_datetime(
        pd.read_csv(QLIB_DIR / "calendars" / "day.txt", header=None)[0]))

    # 最新可用交易日 = min(store 日历末端, daily_basic 末端)
    db = pd.read_csv(DAILY_BASIC, compression="gzip", usecols=["trade_date"])
    db_last = pd.to_datetime(db["trade_date"].astype(str), format="%Y%m%d").max()
    latest = calendar[calendar <= db_last].max()
    log(f"store 日历末端 {calendar[-1].date()} | daily_basic 末端 {db_last.date()}")
    log(f"-> 延伸截止日 {latest.date()}")
    if latest <= v3.BT_END:
        log(f"[skip] 未超出原 BT_END ({v3.BT_END.date()}), 无需延伸。")
        return 0

    # 临时把 BT_END 推到 latest —— v3 与 ex 两个模块都要改,
    # build_ten_day_grid 读的是 ex 模块的全局变量。
    orig_v3, orig_ex = v3.BT_END, ex.BT_END
    v3.BT_END = latest
    ex.BT_END = latest
    try:
        log("[1/4] 加载财务/行业/ST 数据 ...")
        fin = load_financials_extended()
        fin_g2 = load_g2_series()
        industry = pd.read_csv(STYLE_DIR / "industry_l1_effective_intervals.csv.gz",
                               compression="gzip", dtype=str)
        industry["in_date"] = pd.to_datetime(industry["in_date"], errors="coerce")
        industry["out_date"] = pd.to_datetime(industry["out_date"], errors="coerce")
        st = pd.read_csv(ST_INTERVALS, compression="gzip",
                         parse_dates=["start_date", "end_date"])

        log("[2/4] 构建延伸网格 ...")
        grid_d, size_d = ex.build_ten_day_grid(calendar)
        log(f"      网格 {len(grid_d)} 期, {grid_d['rebalance_date'].min().date()} .. "
            f"{grid_d['rebalance_date'].max().date()}")

        # 原缓存有多少期, 用于说明新增
        n_old = None
        old_cache = OUT / "snapshots_500k_10day.pkl"
        if old_cache.exists():
            n_old = len(pd.read_pickle(old_cache))
            log(f"      冻结缓存 {n_old} 期 (止于 2026-06-23)")

        log("[3/4] 构建快照 (流动性门槛按 50 万重设) ...")
        universe = sorted(set(size_d["ts_code"]))
        amount_avg = load_amount_avg(universe, calendar, start=BT_START, end=latest)
        log(f"      amount_avg {amount_avg.shape}")
        v3.ACCOUNT = int(CAPITAL)
        v3.PARTICIPATION = 0.05
        t0 = time.time()
        snaps = v3.build_snapshots(fin, fin_g2, grid_d, industry, size_d, st, amount_avg)
        log(f"      快照 {len(snaps)} 期 ({time.time()-t0:.0f}s)")
    finally:
        v3.BT_END, ex.BT_END = orig_v3, orig_ex

    # 关键量断言: 不能因为静默失效而写出空/退化缓存
    n_cand = [int(f["neutral_composite"].notna().sum()) for f in snaps.values()]
    med = float(np.median(n_cand)) if n_cand else 0.0
    log(f"      每期候选数 中位 {med:,.0f}  最小 {min(n_cand) if n_cand else 0:,}  "
        f"最大 {max(n_cand) if n_cand else 0:,}")
    if not snaps or med < 500:
        raise SystemExit(f"断言失败: 候选数中位仅 {med:,.0f} (应 >500) —— 疑似静默失效, 不写出缓存")
    if n_old is not None and len(snaps) < n_old:
        raise SystemExit(f"断言失败: 延伸后期数 {len(snaps)} 少于冻结缓存 {n_old}")

    log(f"[4/4] 写出 {CACHE_OUT.name} ...")
    pd.to_pickle(snaps, CACHE_OUT)
    new_dates = sorted(snaps)[n_old:] if n_old else []
    log(f"      完成: {len(snaps)} 期, {min(snaps).date()} .. {max(snaps).date()}")
    if new_dates:
        log(f"      新增 {len(new_dates)} 期: "
            f"{', '.join(str(d.date()) for d in new_dates)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
