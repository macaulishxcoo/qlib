#!/usr/bin/env python
"""最终策略的滚动表现 / 换手成本 / 调仓频率稳健性。

(A) 滚动 12 个月净超额 —— 4 个固定 stage 会掩盖"收益集中在少数时段"
(B) 实际换手与成本拖累 (qlib report 自带 turnover / cost)
(C) 调仓频率稳健性: 把否决同时加到【月末】臂上, 看是否也改善
    (若只对 10 日网格有效, 说明是频率特异; 若两处都有效, 说明是通用机制)

配置 = 用户真实口径: account=500,000, top30, 行业 cap3, 10 交易日调仓, 毒尾否决。
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
    QLIB_DIR, BT_START, BT_END, BENCHMARK, COST_SCENARIOS,
    signal_from_snapshots,
)
from backtest_a_share_five_factor_daily_execution_v1 import (  # noqa: E402
    OUT, TOP_K, CAP, build_toxic_rank, apply_veto,
)

CAPITAL = 500_000
ANN = 244.0


def log(m):
    print(m, flush=True)


def run_with_report(signal, top_k, costs):
    strat = TopkDropoutStrategy(signal=signal, topk=top_k, n_drop=top_k)
    report, _ = backtest_daily(
        start_time=BT_START, end_time=BT_END, strategy=strat,
        account=CAPITAL, benchmark=BENCHMARK,
        exchange_kwargs={"limit_threshold": 0.095, "deal_price": "open",
                         "open_cost": costs["open_cost"], "close_cost": costs["close_cost"],
                         "min_cost": 5},
    )
    return report


def main() -> int:
    qlib.init(provider_uri=str(QLIB_DIR), region=REG_CN)
    v3.ACCOUNT = CAPITAL

    calendar = pd.DatetimeIndex(pd.to_datetime(
        pd.read_csv(QLIB_DIR / "calendars" / "day.txt", header=None)[0]))

    cache10, cache500 = OUT / "snapshots_cache.pkl", OUT / "snapshots_500k_10day.pkl"
    if not cache500.exists():
        raise SystemExit("run backtest_a_share_five_factor_500k_v1.py first")
    snap_m, _ = pd.read_pickle(cache10)
    snap_d = pd.read_pickle(cache500)
    log(f"snapshots: 月末 {len(snap_m)} ; 10日 {len(snap_d)}")

    toxic = build_toxic_rank(calendar)
    snap_d_veto = apply_veto(snap_d, toxic, TOP_K, CAP)
    snap_m_veto = apply_veto(snap_m, toxic, TOP_K, CAP)

    arms = {
        "10day_noveto": snap_d,
        "10day_veto": snap_d_veto,
        "monthly_noveto": snap_m,
        "monthly_veto": snap_m_veto,
    }
    reports = {}
    for name, snaps in arms.items():
        sig = signal_from_snapshots(snaps, calendar, TOP_K, CAP)
        reports[name] = run_with_report(sig, TOP_K, COST_SCENARIOS["stress"])
        log(f"  --- {name}: report {reports[name].shape} cols={list(reports[name].columns)[:12]}")

    # ---------- (A) 滚动 12 个月净超额 ----------
    def excess(r):
        return r["return"] - r["bench"] - r["cost"]

    log("\n=== (A) 滚动 12 个月净超额 (10日+否决) ===")
    ex = excess(reports["10day_veto"]).dropna()
    cum = (1 + ex).cumprod()
    rows = []
    for end in pd.date_range(ex.index[0] + pd.Timedelta(days=365), ex.index[-1], freq="QE"):
        seg = ex[ex.index <= end]
        if len(seg) < 200:
            continue
        yr = float((1 + seg.iloc[-244:]).prod() - 1)
        rows.append({"end": end.date().isoformat(), "rolling_12m_excess": yr})
    roll = pd.DataFrame(rows)
    roll.to_csv(OUT / "rolling_12m_excess.csv", index=False)
    if len(roll):
        pos = (roll["rolling_12m_excess"] > 0).mean()
        log(f"  滚动12个月为正的比例 = {pos:.3f}  ({int((roll['rolling_12m_excess']>0).sum())}/{len(roll)})")
        log(f"  滚动12个月: 中位 {roll['rolling_12m_excess'].median():+.4f}  "
            f"最差 {roll['rolling_12m_excess'].min():+.4f}  最好 {roll['rolling_12m_excess'].max():+.4f}")
        log(f"  逐年: " + ", ".join(
            f"{r['end'][:4]}:{r['rolling_12m_excess']:+.3f}" for _, r in roll.iterrows()))

    # ---------- (B) 换手与成本 ----------
    log("\n=== (B) 换手与成本 (stress) ===")
    cost_rows = []
    for name, r in reports.items():
        yrs = len(r) / ANN
        c = r["cost"]
        ann_cost = float((1 + c).prod() ** (1 / yrs) - 1)
        row = {"arm": name, "ann_cost_drag": ann_cost,
               "gross_ann": float((1 + (r["return"] - r["bench"])).prod() ** (1 / yrs) - 1),
               "net_ann": float((1 + excess(r)).prod() ** (1 / yrs) - 1)}
        if "turnover" in r.columns:
            row["ann_turnover"] = float(r["turnover"].sum() / yrs)
        cost_rows.append(row)
    cd = pd.DataFrame(cost_rows)
    cd.to_csv(OUT / "turnover_cost.csv", index=False)
    log(cd.round(4).to_string(index=False))

    # ---------- (C) 调仓频率稳健性 ----------
    log("\n=== (C) 否决在月末臂上是否也有效 (频率稳健性) ===")
    for nm in ("monthly", "10day"):
        a = reports[f"{nm}_noveto"]
        b = reports[f"{nm}_veto"]
        for stage, (s0, s1) in list(v3.STAGES.items()) + [("full", (BT_START, BT_END))]:
            x = excess(a).loc[s0:s1]
            y = excess(b).loc[s0:s1]
            fa = float((1 + x).prod() ** (ANN / len(x)) - 1)
            fb = float((1 + y).prod() ** (ANN / len(y)) - 1)
            log(f"  {nm:<8} {stage:<14} 无否决={fa:+.4f} 有否决={fb:+.4f} 增量={fb-fa:+.4f}")

    (OUT / "final_strategy_profile.json").write_text(json.dumps({
        "capital": CAPITAL, "top_k": TOP_K, "cap": CAP, "rebalance_days": 10,
        "veto": "toxic>0.90 excluded (score=-999)",
        "rolling_12m_positive_frac": float((roll["rolling_12m_excess"] > 0).mean()) if len(roll) else None,
        "turnover_cost": cd.to_dict(orient="records"),
    }, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
