#!/usr/bin/env python
"""收益归因: 把每期超额拆到【基础五因子 alpha】/【毒尾否决】/【价格可行性过滤】三部分。

用途: 一旦超额下滑, 立刻知道是哪一部分出了问题。
方法: 分别跑 B(无否决) / E(否决) / F(否决+价格过滤) 三臂, 取日度序列,
      再做滚动 12 个月分解。
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import qlib  # noqa: E402
from qlib.config import REG_CN  # noqa: E402
from qlib.contrib.evaluate import backtest_daily  # noqa: E402
from qlib.contrib.strategy import TopkDropoutStrategy  # noqa: E402

import backtest_a_share_value_growth_five_factor_industry_cap_v3 as v3  # noqa: E402
from backtest_a_share_value_growth_five_factor_industry_cap_v3 import (  # noqa: E402
    QLIB_DIR, BT_START, BT_END, BENCHMARK, COST_SCENARIOS, signal_from_snapshots,
)
from backtest_a_share_five_factor_daily_execution_v1 import (  # noqa: E402
    OUT, TOP_K, CAP, build_toxic_rank, apply_veto,
)
from analyze_a_share_price_feasibility_v1 import price_panel, apply_price_filter  # noqa: E402

CAPITAL = 500_000.0
W = 244


def log(m):
    print(m, flush=True)


def _load_snapshot_cache():
    """优先用【延伸版】快照(由 rebuild_snapshots_to_date_v1.py 生成, 随新数据推进),
    否则退回冻结的研究快照。冻结版止于 2026-06-23 —— 用它时"滚动12个月"不会变化,
    月度检查会变成复读。返回值: (snap_dict, 说明字符串)。"""
    ext = OUT / "snapshots_500k_10day_extended.pkl"
    frozen = OUT / "snapshots_500k_10day.pkl"
    src = ext if ext.exists() else frozen
    snap = pd.read_pickle(src)
    ks = sorted(snap)
    tag = "延伸版(随新数据推进)" if src is ext else "冻结研究快照(不会推进)"
    return snap, f"{src.name}  {len(snap)} 期  {ks[0].date()} .. {ks[-1].date()}  [{tag}]"


def run(sig, tag, end):
    strat = TopkDropoutStrategy(signal=sig, topk=TOP_K, n_drop=TOP_K)
    rep, _ = backtest_daily(
        start_time=BT_START, end_time=end, strategy=strat, account=CAPITAL,
        benchmark=BENCHMARK,
        exchange_kwargs={"limit_threshold": 0.095, "deal_price": "open",
                         "open_cost": COST_SCENARIOS["stress"]["open_cost"],
                         "close_cost": COST_SCENARIOS["stress"]["close_cost"],
                         "min_cost": 5})
    return (rep["return"] - rep["bench"] - rep["cost"]).rename(tag)


def main() -> int:
    qlib.init(provider_uri=str(QLIB_DIR), region=REG_CN)
    v3.ACCOUNT = int(CAPITAL)
    calendar = pd.DatetimeIndex(pd.to_datetime(
        pd.read_csv(QLIB_DIR / "calendars" / "day.txt", header=None)[0]))

    snap, cache_desc = _load_snapshot_cache()
    P = price_panel()
    toxic = build_toxic_rank(calendar)
    cache_end = max(snap)
    end = max(pd.Timestamp(BT_END), cache_end)
    print(f"[cache] {cache_desc}", flush=True)
    print(f"[window] 回测末端 = {end.date()}", flush=True)

    snap_B = snap
    snap_E = apply_veto(snap, toxic, TOP_K, CAP)
    snap_F, _ = apply_price_filter(snap_E, P, TOP_K, CAPITAL, shift=0)

    ser = {}
    for tag, s in (("B_base", snap_B), ("E_veto", snap_E), ("F_final", snap_F)):
        sig = signal_from_snapshots(s, calendar, TOP_K, CAP)
        ser[tag] = run(sig, tag, end)
        log(f"  {tag}: full={((1+ser[tag]).prod()**(244/len(ser[tag]))-1):+.4f}")

    df = pd.DataFrame(ser).dropna()
    df["base_alpha"] = df["B_base"]
    df["veto_contrib"] = df["E_veto"] - df["B_base"]
    df["price_contrib"] = df["F_final"] - df["E_veto"]
    df.to_csv(OUT / "return_attribution_daily.csv")

    print("\n=== 全期累计贡献 (年化) ===")
    n = len(df)
    for c in ("base_alpha", "veto_contrib", "price_contrib", "F_final"):
        print(f"  {c:<16} {(1+df[c]).prod()**(244/n)-1:+.4f}")

    print("\n=== 滚动 12 个月: 各成分贡献 ===")
    idx, rows = [], []
    for i in range(W, len(df) + 1):
        seg = df.iloc[i - W:i]
        idx.append(df.index[i - 1])
        rows.append({c: float((1 + seg[c]).prod() - 1)
                     for c in ("base_alpha", "veto_contrib", "price_contrib", "F_final")})
    roll = pd.DataFrame(rows, index=pd.DatetimeIndex(idx))
    roll.to_csv(OUT / "return_attribution_rolling.csv")

    print(f"{'窗口末':<12}{'基础alpha':>11}{'否决':>10}{'价格过滤':>10}{'合计':>10}")
    for d, r in roll.iloc[::max(1, len(roll) // 12)].iterrows():
        print(f"{str(d.date()):<12}{r['base_alpha']:>+11.4f}{r['veto_contrib']:>+10.4f}"
              f"{r['price_contrib']:>+10.4f}{r['F_final']:>+10.4f}")
    print(f"{'最近':<12}{roll.iloc[-1]['base_alpha']:>+11.4f}"
          f"{roll.iloc[-1]['veto_contrib']:>+10.4f}"
          f"{roll.iloc[-1]['price_contrib']:>+10.4f}{roll.iloc[-1]['F_final']:>+10.4f}")

    (OUT / "return_attribution.json").write_text(json.dumps({
        "full_annualized": {c: float((1 + df[c]).prod() ** (244 / n) - 1)
                            for c in ("base_alpha", "veto_contrib", "price_contrib", "F_final")},
        "rolling_last": roll.iloc[-1].to_dict(),
        "rolling_base_positive_frac": float((roll["base_alpha"] > 0).mean()),
        "rolling_veto_positive_frac": float((roll["veto_contrib"] > 0).mean()),
    }, indent=2, ensure_ascii=False))

    # ---------- 报警: 盯"承重墙"毒尾否决的滚动贡献 ----------
    last = roll.iloc[-1]
    print("\n=== 监测报警 ===")
    print(f"  最近滚动12个月:  基础alpha {last['base_alpha']:+.4f} | "
          f"否决 {last['veto_contrib']:+.4f} | 价格过滤 {last['price_contrib']:+.4f} | "
          f"合计 {last['F_final']:+.4f}")
    print(f"  历史否决贡献为正比例: {float((roll['veto_contrib'] > 0).mean()):.3f}")
    alarm = bool(last["veto_contrib"] < 0)
    if alarm:
        print("  ⚠ 报警: 毒尾否决的滚动 12 个月贡献【为负】—— 承重墙失效，")
        print("          策略已退化为疲弱价值因子。建议复核并考虑降低仓位。")
    else:
        print("  状态正常: 否决仍在贡献正超额。")
        if last["base_alpha"] < 0:
            print("  （注意: 基础价值 alpha 当前为负 —— 超额仍靠否决支撑）")
    return 2 if alarm else 0


if __name__ == "__main__":
    raise SystemExit(main())
