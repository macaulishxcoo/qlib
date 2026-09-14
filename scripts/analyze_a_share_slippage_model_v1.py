#!/usr/bin/env python
"""滑点 / 冲击成本模型 —— 给出 50 万真实执行下的净超额区间。

协议: research/protocols/a_share_slippage_model_protocol_v1.md

做法:
  1. 重建最终策略(五因子+否决+价格过滤, top30 cap3)的逐期目标持仓
  2. 逐期算换手(买入/卖出名单与金额, 等权 30 只)
  3. 对每笔成交套用: 单边滑点 = 0.5*tick/price + c*sigma20*sqrt(金额/ADV20)
  4. 把滑点从毛收益里扣掉, 重算净超额
全部使用 asof 日及之前的数据(ADV20 / sigma20), 不使用成交日之后信息。
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
    QLIB_DIR, BT_START, BT_END, select_with_industry_cap,
)
from backtest_a_share_five_factor_daily_execution_v1 import (  # noqa: E402
    OUT, TOP_K, CAP, build_toxic_rank, apply_veto, _to_ts_code,
)
from analyze_a_share_price_feasibility_v1 import price_panel, apply_price_filter  # noqa: E402

CAPITAL = 500_000.0
ANN, TICK = 244, 0.01
REPO = Path("/mnt/d/workspaces/qlib")
SCENARIOS = {"optimistic_c0.3": 0.3, "moderate_c0.5": 0.5,
             "conservative_c1.0": 1.0, "drought_c1.0_fullspread": 1.0}
COMMISSION = {"base": (0.0005, 0.0015), "stress": (0.0010, 0.0030)}
FINAL_COLS = ["final_base", "final_stress"]


def log(m):
    print(m, flush=True)


def load_adv_sigma(dates: pd.DatetimeIndex):
    """ADV20 与 sigma20 面板 (仅在 asof 日取值, 严格 PIT)。"""
    from qlib.data import D
    df = D.features(D.instruments(market="all"), ["$close", "$amount"],
                    start_time="2015-01-01", end_time=str(BT_END.date()), freq="day")
    df.columns = ["close", "amount"]
    df = df[~df.index.duplicated()]
    C = df["close"].unstack(0).sort_index().astype("float64")
    A = df["amount"].unstack(0).sort_index().astype("float64") * 1000.0   # 千元 -> 元
    C.columns = [_to_ts_code(c) for c in C.columns]
    A.columns = [_to_ts_code(c) for c in A.columns]
    ret = (C / C.shift(1) - 1.0).where(C > 0)
    adv = A.rolling(20, min_periods=10).mean()
    sig = ret.rolling(20, min_periods=10).std()
    return adv.reindex(dates), sig.reindex(dates)


def _build_trades(s, dates, P, adv, sig) -> pd.DataFrame:
    rows, prev_w = [], None
    for d in dates:
        sel = select_with_industry_cap(s[d], TOP_K, CAP)
        if sel.empty:
            continue
        names = list(sel["ts_code"])
        w = pd.Series(1.0 / len(names), index=names)
        if prev_w is None:
            traded = w.copy()
        else:
            allc = w.index.union(prev_w.index)
            a = w.reindex(allc).fillna(0.0)
            b = prev_w.reindex(allc).fillna(0.0)
            traded = (a - b).abs()
        traded = traded[traded > 1e-12]
        prev_w = w
        if traded.empty or d not in P.index:
            continue
        px = P.loc[d].reindex(traded.index)
        av = adv.loc[d].reindex(traded.index) if d in adv.index else pd.Series(np.nan, index=traded.index)
        sg = sig.loc[d].reindex(traded.index) if d in sig.index else pd.Series(np.nan, index=traded.index)
        notional = traded * CAPITAL
        for bidx in traded.index:
            p, a20, s20, q = (px.get(bidx, np.nan), av.get(bidx, np.nan),
                              sg.get(bidx, np.nan), notional.get(bidx, 0.0))
            if not (np.isfinite(p) and p > 0 and np.isfinite(a20) and a20 > 0 and np.isfinite(s20)):
                continue
            rows.append({"date": d, "ts_code": bidx, "weight_traded": float(traded[bidx]),
                         "price": float(p), "adv20": float(a20), "sigma20": float(s20),
                         "notional": float(q),
                         "half_spread": 0.5 * TICK / float(p),
                         "participation": float(q / a20)})
    return pd.DataFrame(rows)


def main() -> int:
    qlib.init(provider_uri=str(QLIB_DIR), region=REG_CN)
    v3.ACCOUNT = int(CAPITAL)
    calendar = pd.DatetimeIndex(pd.to_datetime(
        pd.read_csv(QLIB_DIR / "calendars" / "day.txt", header=None)[0]))

    snap = pd.read_pickle(OUT / "snapshots_500k_10day.pkl")
    P = price_panel()
    toxic = build_toxic_rank(calendar)
    s = apply_veto(snap, toxic, TOP_K, CAP)
    s, _ = apply_price_filter(s, P, TOP_K, CAPITAL, shift=0)

    dates = pd.DatetimeIndex(sorted(s.keys()))
    log(f"[1/3] 目标持仓 {len(dates)} 期; 载入 ADV20 / sigma20 ...")
    adv, sig = load_adv_sigma(dates)

    log("[2/3] 逐期计算换手与滑点 ...")
    cache = OUT / "slippage_trades.csv.gz"
    if cache.exists():
        tr = pd.read_csv(cache, parse_dates=["date"])
        log(f"      [cache hit] 成交笔数 {len(tr):,}")
    else:
        tr = _build_trades(s, dates, P, adv, sig)
        tr.to_csv(cache, index=False, compression="gzip")
    if tr.empty:
        raise SystemExit("无成交记录")
    log(f"      成交笔数 {len(tr):,}")
    log(f"      参与率 participation: 中位 {tr['participation'].median():.5f}  "
        f"p90 {tr['participation'].quantile(.9):.5f}  最大 {tr['participation'].max():.5f}")
    log(f"      价差(半)均值: {tr['half_spread'].mean()*1e4:.2f} bp")

    # 逐期滑点成本 = Σ 权重成交 × (half_spread + c*sigma*sqrt(part))
    log("[3/3] 汇总各情景 ...")
    by_date = tr.groupby("date")
    res = []
    for sc, c in SCENARIOS.items():
        full_spread = 2.0 if "fullspread" in sc else 1.0
        daily_cost = []
        for d, g in by_date:
            imp = c * g["sigma20"] * np.sqrt(g["participation"])
            slip = full_spread * g["half_spread"] + imp
            daily_cost.append((d, float((g["weight_traded"] * slip).sum())))
        cost = pd.Series(dict(daily_cost)).sort_index()
        for cm, (br, sr) in COMMISSION.items():
            # 佣金: 买卖各半, 用平均费率近似(与 qlib 的 open/close 分档一致)
            comm = 0.5 * (br + sr)
            total = cost + comm * tr.groupby("date")["weight_traded"].sum().reindex(cost.index).fillna(0)
            res.append({"scenario": sc, "commission": cm,
                        "extra_cost_pp_per_year": float(cost.sum() / (len(dates) / (ANN / 10)) * 100),
                        "mean_slip_bp": float((tr["weight_traded"] * (full_spread * tr["half_spread"]
                                              + c * tr["sigma20"] * np.sqrt(tr["participation"]))).sum()
                                              / tr["weight_traded"].sum() * 1e4),
                        "_series": total})
    df = pd.DataFrame(res)
    piv = df.pivot_table(index="scenario", columns="commission", values="extra_cost_pp_per_year")
    log("\n=== 额外成本 (滑点部分, pp/年; 以总换手次数计) ===")
    log(piv.round(3).to_string())

    # 与"仅佣金"基线对比。注意: backtest_daily.csv 的 cost 列已经是 stress 佣金,
    # 因此必须从【毛收益】出发按各佣金档 + 滑点重算, 不能拿它再减一次佣金(会重复扣)。
    base = pd.read_csv(REPO / "output" / "live" / "decay_monitor" / "backtest_daily.csv",
                       parse_dates=["datetime"]).set_index("datetime")
    base = base.sort_index()
    gross = base["return"] - base["bench"]
    turn = tr.groupby("date")["weight_traded"].sum()
    log("\n=== 净超额 (全期年化, 从毛收益出发: 佣金 + 滑点) ===")
    log(f"{'情景':<26}{'佣金档':<8}{'全期':>9}{'2020起':>9}{'最近1年':>10}{'滑点bp':>9}{'总成本pp/年':>12}")
    out_rows = []
    for _, r in df.iterrows():
        cost = r["_series"]                       # 已含滑点 + 该档佣金(按权重换手)
        add = pd.Series(0.0, index=gross.index)
        for d, v in cost.items():
            nxt = gross.index[gross.index > d]
            end = nxt[10] if len(nxt) >= 10 else (nxt[-1] if len(nxt) else d)
            seg = gross.index[(gross.index >= d) & (gross.index < end)]
            if len(seg):
                add.loc[seg] += v / len(seg)
        ex = (gross - add).dropna()
        def ann(x):
            x = x.dropna()
            return float((1 + x).prod() ** (ANN / len(x)) - 1) if len(x) > 20 else np.nan
        row = {"scenario": r["scenario"], "commission": r["commission"],
               "full": ann(ex), "y2020": ann(ex.loc["2020-01-01":]),
               "last_year": ann(ex.iloc[-244:]),
               "slip_bp": r["mean_slip_bp"],
               "total_cost_pp": float(cost.sum() / (len(dates) / (ANN / 10)) * 100)}
        out_rows.append(row)
        log(f"{r['scenario']:<26}{r['commission']:<8}{row['full']:>+9.4f}"
            f"{row['y2020']:>+9.4f}{row['last_year']:>+10.4f}{r['mean_slip_bp']:>9.2f}"
            f"{row['total_cost_pp']:>12.3f}")

    od = pd.DataFrame(out_rows)
    od.to_csv(OUT / "slippage_summary.csv", index=False)
    best = od.loc[od["full"].idxmax()]
    worst = od.loc[od["full"].idxmin()]
    log(f"\n>>> 净超额区间(全期): {worst['full']:+.4f} ({worst['scenario']}/{worst['commission']}) "
        f"~ {best['full']:+.4f} ({best['scenario']}/{best['commission']})")
    (OUT / "slippage_decision.json").write_text(json.dumps({
        "participation_median": float(tr["participation"].median()),
        "participation_p90": float(tr["participation"].quantile(.9)),
        "participation_max": float(tr["participation"].max()),
        "extra_cost_pp_per_year": piv.to_dict(),
        "range_full": {"worst": float(worst["full"]), "best": float(best["full"])},
        "detail": out_rows,
    }, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
