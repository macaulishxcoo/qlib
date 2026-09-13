#!/usr/bin/env python
"""策略衰减监测看板。

用途: 鉴于最终策略在 2025 年起出现衰减（滚动 12 个月降到 +0.6%~+6.3%），
      需要一个自动化的"是否还在工作"的检查，而不是靠人回忆。

输入: 一份日度收益序列 CSV, 含列 [datetime, return, bench, cost]
      （可由 qlib 回测 report 或实盘净值直接提供）
输出: 滚动 12 个月净超额时间序列 + 当前状态判定 + 退出码
      （退出码 0=正常, 2=滚动12个月转负 -> 触发复核）

用法:
  python scripts/monitor_strategy_decay_v1.py --returns <csv>
  python scripts/monitor_strategy_decay_v1.py --backtest   # 直接重跑回测取序列
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

ANN = 244
WINDOW = 244          # 12 个月


def rolling_excess(ret: pd.Series, window: int = WINDOW) -> pd.Series:
    """每个时点的滚动 window 日净超额 (复利)。"""
    out = {}
    idx = ret.index
    for i in range(window, len(idx) + 1):
        seg = ret.iloc[i - window:i]
        out[idx[i - 1]] = float((1 + seg).prod() - 1)
    return pd.Series(out)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--returns", type=Path, default=None,
                    help="CSV 含 datetime, return, bench, cost")
    ap.add_argument("--backtest", action="store_true",
                    help="直接重跑最终策略回测取日度序列（较慢）")
    ap.add_argument("--out-dir", type=Path, default=None)
    args = ap.parse_args()

    out_dir = args.out_dir or (HERE.parent / "output" / "live" / "decay_monitor")
    out_dir.mkdir(parents=True, exist_ok=True)

    if args.backtest:
        import qlib
        from qlib.config import REG_CN
        from qlib.contrib.evaluate import backtest_daily
        from qlib.contrib.strategy import TopkDropoutStrategy
        import backtest_a_share_value_growth_five_factor_industry_cap_v3 as v3
        from backtest_a_share_value_growth_five_factor_industry_cap_v3 import (
            QLIB_DIR, BT_START, BT_END, BENCHMARK, COST_SCENARIOS, signal_from_snapshots)
        from backtest_a_share_five_factor_daily_execution_v1 import (
            OUT as AOUT, TOP_K, CAP, build_toxic_rank, apply_veto)
        from analyze_a_share_price_feasibility_v1 import price_panel, apply_price_filter

        qlib.init(provider_uri=str(QLIB_DIR), region=REG_CN)
        capital = 500_000
        v3.ACCOUNT = capital
        calendar = pd.DatetimeIndex(pd.to_datetime(
            pd.read_csv(QLIB_DIR / "calendars" / "day.txt", header=None)[0]))
        snap = pd.read_pickle(AOUT / "snapshots_500k_10day.pkl")
        toxic = build_toxic_rank(calendar)
        snaps = apply_veto(snap, toxic, TOP_K, CAP)
        snaps, _ = apply_price_filter(snaps, price_panel(), TOP_K, capital, shift=0)
        sig = signal_from_snapshots(snaps, calendar, TOP_K, CAP)
        strat = TopkDropoutStrategy(signal=sig, topk=TOP_K, n_drop=TOP_K)
        report, _ = backtest_daily(
            start_time=BT_START, end_time=BT_END, strategy=strat, account=capital,
            benchmark=BENCHMARK,
            exchange_kwargs={"limit_threshold": 0.095, "deal_price": "open",
                             "open_cost": COST_SCENARIOS["stress"]["open_cost"],
                             "close_cost": COST_SCENARIOS["stress"]["close_cost"],
                             "min_cost": 5})
        df = report.reset_index().rename(columns={"index": "datetime"})
        df.to_csv(out_dir / "backtest_daily.csv", index=False)
    elif args.returns:
        df = pd.read_csv(args.returns)
        df["datetime"] = pd.to_datetime(df["datetime"])
    else:
        raise SystemExit("需要 --returns 或 --backtest")

    df = df.set_index("datetime").sort_index()
    ex = (df["return"] - df["bench"] - df["cost"]).dropna()
    roll = rolling_excess(ex)

    status = {
        "as_of": str(ex.index[-1].date()),
        "n_days": int(len(ex)),
        "full_period_ann_excess": float((1 + ex).prod() ** (ANN / len(ex)) - 1),
        "rolling_12m_current": float(roll.iloc[-1]) if len(roll) else None,
        "rolling_12m_positive_frac": float((roll > 0).mean()) if len(roll) else None,
        "rolling_12m_median": float(roll.median()) if len(roll) else None,
        "rolling_12m_min": float(roll.min()) if len(roll) else None,
    }
    roll.to_frame("rolling_12m_excess").to_csv(out_dir / "rolling_12m.csv")
    (out_dir / "status.json").write_text(json.dumps(status, indent=2, ensure_ascii=False))

    print(f"as of {status['as_of']}  样本 {status['n_days']} 日")
    print(f"  全期年化净超额      {status['full_period_ann_excess']:+.4f}")
    print(f"  滚动12个月(当前)    {status['rolling_12m_current']:+.4f}")
    print(f"  滚动12个月为正比例  {status['rolling_12m_positive_frac']:.3f}")
    print(f"  滚动12个月 中位/最差 {status['rolling_12m_median']:+.4f} / "
          f"{status['rolling_12m_min']:+.4f}")
    trig = status["rolling_12m_current"] is not None and status["rolling_12m_current"] < 0
    print(f"\n状态: {'⚠ 滚动12个月为负 —— 触发复核' if trig else '正常'}")
    return 2 if trig else 0


if __name__ == "__main__":
    raise SystemExit(main())
