#!/usr/bin/env python
"""价格可行性过滤 (整手约束的事前化) —— 独立变体测试。

问题: 50万/top30 -> 单笔预算 16,667 元 -> 股价 >166.67 元的股票连 1 手都买不到。
      现有实现是"选中后才在股数计算时归零", 导致这些名额被浪费,
      实测首次清单利用率仅 0.807 (2/30 名额被 173.3/177.6 元的票占掉)。

本变体: 在【选股前】剔除 100*close > capital/topk 的候选, 让后面名次递补。
        与毒尾否决同样的机制 (score 置 -999)。

关键: 超额是按 NAV 计的, 故仓位利用率直接缩放超额 ——
      0.807 -> ~0.93 预期带来约 1.15x 的超额 (同时也等比放大波动)。

对照:
  E = 10日 + 否决                 (现状)
  F = 10日 + 否决 + 价格可行性      (本变体)
  G = F 但价格用滞后 1 日 (稳健性)
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
    QLIB_DIR, BT_START, BT_END, signal_from_snapshots, run_backtest,
)
from backtest_a_share_five_factor_daily_execution_v1 import (  # noqa: E402
    OUT, TOP_K, CAP, build_toxic_rank, apply_veto, _to_ts_code,
)

CAPITAL = 500_000.0


def log(m):
    print(m, flush=True)


def price_panel() -> pd.DataFrame:
    """每个交易日的收盘价 (列 = ts_code), 用于整手可行性判断。"""
    from qlib.data import D
    df = D.features(D.instruments(market="all"), ["$close"],
                    start_time=str(BT_START.date()), end_time=str(BT_END.date()), freq="day")
    P = df["$close"].unstack(0).sort_index().astype("float32")
    P.columns = [_to_ts_code(c) for c in P.columns]
    return P


def apply_price_filter(snapshots: dict, px: pd.DataFrame, top_k: int,
                       capital: float, shift: int = 0) -> dict:
    """把 100*close > capital/top_k 的候选 score 置 -999。"""
    P = px.shift(shift) if shift else px
    cap_per = capital / top_k
    out, hit, tot = {}, 0, 0
    for date, frame in snapshots.items():
        f = frame.copy()
        if date in P.index:
            c = P.loc[date].reindex(f["ts_code"]).to_numpy(dtype=float)
        else:
            c = np.full(len(f), np.nan)
        too_expensive = np.isfinite(c) & (100.0 * c > cap_per)
        cand = f["neutral_composite"].notna().to_numpy()
        hit += int((cand & too_expensive).sum())
        tot += int(cand.sum())
        f.loc[too_expensive, "neutral_composite"] = -999.0
        out[date] = f
    return out, (hit, tot)


def main() -> int:
    qlib.init(provider_uri=str(QLIB_DIR), region=REG_CN)
    v3.ACCOUNT = int(CAPITAL)
    calendar = pd.DatetimeIndex(pd.to_datetime(
        pd.read_csv(QLIB_DIR / "calendars" / "day.txt", header=None)[0]))

    snap_10 = pd.read_pickle(OUT / "snapshots_500k_10day.pkl")
    log(f"snapshots: {len(snap_10)}")

    toxic = build_toxic_rank(calendar)
    px = price_panel()
    log(f"price panel: {px.shape}  单笔预算上限价 = {CAPITAL/TOP_K/100:.2f} 元")

    snap_veto = apply_veto(snap_10, toxic, TOP_K, CAP)
    snap_f, (h0, t0) = apply_price_filter(snap_veto, px, TOP_K, CAPITAL, shift=0)
    snap_g, (h1, t1) = apply_price_filter(snap_veto, px, TOP_K, CAPITAL, shift=1)
    log(f"价格过滤屏蔽候选: 当日口径 {h0:,}/{t0:,} ({h0/max(t0,1):.3f}) ; "
        f"滞后1日 {h1:,}/{t1:,} ({h1/max(t1,1):.3f})")

    arms = [("E_veto", snap_veto), ("F_veto_price", snap_f), ("G_veto_price_lag1", snap_g)]
    rows = []
    for name, snaps in arms:
        sig = signal_from_snapshots(snaps, calendar, TOP_K, CAP)
        bt = run_backtest(sig, TOP_K)
        bt["arm"] = name
        rows.append(bt)
        st = bt[bt["cost_scenario"] == "stress"].set_index("stage")
        log(f"  --- {name}: full={st.loc['full','net_excess_annualized_return']:+.4f} "
            f"IR={st.loc['full','net_excess_ir']:+.3f} "
            f"MDD={st.loc['full','net_excess_max_drawdown']:+.4f} | "
            f"holdout={st.loc['holdout','net_excess_annualized_return']:+.4f} "
            f"new_cov={st.loc['new_coverage','net_excess_annualized_return']:+.4f}")

    bt = pd.concat(rows, ignore_index=True)
    bt.to_csv(OUT / "price_feasibility_summary.csv", index=False)

    log("\n=== 三臂对照 (stress, 净超额) ===")
    p = bt[bt["cost_scenario"] == "stress"].pivot_table(
        index="stage", columns="arm", values="net_excess_annualized_return")
    log(p.round(4).to_string())
    log("\n=== IR ===")
    log(bt[bt["cost_scenario"] == "stress"].pivot_table(
        index="stage", columns="arm", values="net_excess_ir").round(3).to_string())

    e = p.loc["full", "E_veto"]
    f = p.loc["full", "F_veto_price"]
    (OUT / "price_feasibility_decision.json").write_text(json.dumps({
        "capital": CAPITAL, "top_k": TOP_K,
        "max_affordable_price": CAPITAL / TOP_K / 100.0,
        "masked_frac_same_day": h0 / max(t0, 1),
        "masked_frac_lag1": h1 / max(t1, 1),
        "full_E_veto": float(e), "full_F_price": float(f),
        "full_gain": float(f - e),
        "verdict": "improves" if f > e else "no_improvement",
    }, indent=2, ensure_ascii=False))
    log(f"\n>>> 价格可行性过滤全期增量 = {f - e:+.4f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
