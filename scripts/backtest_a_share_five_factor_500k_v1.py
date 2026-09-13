#!/usr/bin/env python
"""50 万口径重估: 流动性门槛按真实资金重设 + 组合按真实资金回测。

问题: 既有五因子线的流动性门槛为
        min_amount = (ACCOUNT // 15) / PARTICIPATION = (1亿/15)/0.05 = 1.33亿/日
      这是为【1 亿账户 + top15】标定的, 只有约几百只大盘股能过。
      用户资金 50 万 + top30 -> 单笔 16,667 元, 真实所需门槛
        = 16,667 / 0.05 = 33.3万/日
      即门槛高估了约 400 倍, 无谓剔除了大量用户实际可买的中小票。

同时把 qlib 回测的 account 也改为 500,000 —— qlib 会按 100 股整手取整
并以 min_cost=5 计费, 因此这一改就顺带得到真实的整手/最低佣金约束。

对照:
  A_m100 (既有)      : 1亿门槛 + 1亿账户
  B_m100_veto        : 1亿门槛 + 否决
  D_m500 (新基线)     : 50万门槛 + 50万账户, 无否决
  E_m500_veto        : 50万门槛 + 否决
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

import backtest_a_share_value_growth_five_factor_industry_cap_v3 as v3  # noqa: E402
from backtest_a_share_value_growth_five_factor_industry_cap_v3 import (  # noqa: E402
    QLIB_DIR, STYLE_DIR, ST_INTERVALS, BT_START, BT_END,
    signal_from_snapshots, run_backtest,
)
from load_financials_extended_v1 import load_financials_extended  # noqa: E402
from backtest_a_share_value_quality_monthly_sensitivity_v4 import load_amount_avg  # noqa: E402
from run_daily_signal_pipeline_v1 import load_g2_series  # noqa: E402
from backtest_a_share_five_factor_daily_execution_v1 import (  # noqa: E402
    OUT, TOP_K, CAP, STEP, build_ten_day_grid, build_toxic_rank, apply_veto,
)

CAPITAL = 500_000.0
CACHE_500K = OUT / "snapshots_500k_10day.pkl"


def log(m):
    print(m, flush=True)


def main() -> int:
    qlib.init(provider_uri=str(QLIB_DIR), region=REG_CN)
    calendar = pd.DatetimeIndex(pd.to_datetime(
        pd.read_csv(QLIB_DIR / "calendars" / "day.txt", header=None)[0]))

    log(f"[1/3] 重建 10 日快照, 流动性门槛按 {CAPITAL:,.0f} 元重设 ...")
    log(f"      原 ACCOUNT={v3.ACCOUNT:,} -> 门槛 {(v3.ACCOUNT//15)/v3.PARTICIPATION:,.0f} 元/日")
    log(f"      新 ACCOUNT={CAPITAL:,.0f} -> 门槛 {(CAPITAL//15)/v3.PARTICIPATION:,.0f} 元/日")
    if CACHE_500K.exists():
        snap_500 = pd.read_pickle(CACHE_500K)
        log(f"      [cache hit] {len(snap_500)}")
    else:
        fin = load_financials_extended()
        fin_g2 = load_g2_series()
        industry = pd.read_csv(STYLE_DIR / "industry_l1_effective_intervals.csv.gz",
                               compression="gzip", dtype=str)
        industry["in_date"] = pd.to_datetime(industry["in_date"], errors="coerce")
        industry["out_date"] = pd.to_datetime(industry["out_date"], errors="coerce")
        st = pd.read_csv(ST_INTERVALS, compression="gzip",
                         parse_dates=["start_date", "end_date"])
        grid_d, size_d = build_ten_day_grid(calendar)
        universe = sorted(set(size_d["ts_code"]))
        amount_avg = load_amount_avg(universe, calendar)
        v3.ACCOUNT = int(CAPITAL)          # build_snapshots 读本模块的 ACCOUNT
        v3.PARTICIPATION = 0.05
        import time as _t
        t0 = _t.time()
        snap_500 = v3.build_snapshots(fin, fin_g2, grid_d, industry, size_d, st, amount_avg)
        log(f"      快照 {len(snap_500)} ({_t.time()-t0:.0f}s)")
        pd.to_pickle(snap_500, CACHE_500K)

    # 候选数对比
    n_new = np.mean([int(f["neutral_composite"].notna().sum()) for f in snap_500.values()])
    log(f"      50万门槛下每期平均候选数 = {n_new:,.0f}")
    try:
        _, snap_100 = pd.read_pickle(OUT / "snapshots_cache.pkl")
        n_old = np.mean([int(f["neutral_composite"].notna().sum()) for f in snap_100.values()])
        log(f"      1亿门槛下每期平均候选数 = {n_old:,.0f}  (扩大 {n_new/max(n_old,1):.1f}x)")
    except Exception as e:
        log(f"      (无法读取 1 亿快照做对比: {e})")

    log("[2/3] toxic veto overlay (50万口径) ...")
    toxic = build_toxic_rank(calendar)
    snap_500_veto = apply_veto(snap_500, toxic, TOP_K, CAP)

    log("[3/3] backtesting ...")
    # 注意: run_backtest 使用 v3 模块的 ACCOUNT, 此处已为 500,000
    arms = [("D_m500_noveto", snap_500), ("E_m500_veto", snap_500_veto)]
    rows = []
    for name, snaps in arms:
        sig = signal_from_snapshots(snaps, calendar, TOP_K, CAP)
        log(f"  --- {name}: signal rows={len(sig):,} ---")
        bt = run_backtest(sig, TOP_K)
        bt["arm"] = name
        rows.append(bt)
        for _, r in bt.iterrows():
            if r["cost_scenario"] == "stress":
                log(f"      {r['stage']:<14} net={r['net_excess_annualized_return']:+.4f} "
                    f"IR={r['net_excess_ir']:+.3f} MDD={r['net_excess_max_drawdown']:+.4f}")
    bt = pd.concat(rows, ignore_index=True)
    bt.to_csv(OUT / "capital_500k_summary.csv", index=False)

    # 并入既有 100 万口径结果做总表
    prev = OUT / "backtest_summary.csv"
    if prev.exists():
        old = pd.read_csv(prev)
        old = old[old["arm"].isin(["A_monthly_noveto", "B_10day_noveto", "C_10day_veto"])]
        both = pd.concat([old, bt], ignore_index=True)
        both.to_csv(OUT / "capital_comparison.csv", index=False)
        log("\n=== 口径对比 (stress, 净超额) ===")
        p = both[both["cost_scenario"] == "stress"].pivot_table(
            index="stage", columns="arm", values="net_excess_annualized_return")
        log(p.round(4).to_string())
        log("\n=== IR ===")
        p2 = both[both["cost_scenario"] == "stress"].pivot_table(
            index="stage", columns="arm", values="net_excess_ir")
        log(p2.round(3).to_string())

    st = bt[bt["cost_scenario"] == "stress"].set_index("stage")
    d = float(st.loc["full", "net_excess_annualized_return"]) if "D_m500_noveto" in st.index else np.nan
    (OUT / "capital_500k_decision.json").write_text(json.dumps({
        "capital": CAPITAL, "min_amount_per_day": (CAPITAL // 15) / 0.05,
        "old_account": 100_000_000, "old_min_amount_per_day": (100_000_000 // 15) / 0.05,
        "avg_candidates_500k": float(n_new),
        "full": {a: float(bt[(bt["arm"] == a) & (bt["stage"] == "full")
                             & (bt["cost_scenario"] == "stress")]["net_excess_annualized_return"].iloc[0])
                 for a in ["D_m500_noveto", "E_m500_veto"]},
        "note": "qlib account=500000 -> 100股整手 + min_cost=5 自动生效",
    }, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
