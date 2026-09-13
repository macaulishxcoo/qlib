#!/usr/bin/env python
"""低名义价格作为显式因子 —— 正交性 + 增量检验。

协议: research/protocols/a_share_lowprice_factor_protocol_v1.md

Q1 正交性: lowprice 与 五因子/composite5 的截面 Spearman 相关
Q2 增量  : composite6 (= 五因子 + lowprice 等权 rank 均值) 相对 composite5 是否改善
三臂: A=composite5+价格过滤(=当前策略)  B=composite6+价格过滤  C=composite6 无价格过滤
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
    QLIB_DIR, BT_START, BT_END, signal_from_snapshots, run_backtest, ols_residual,
)
from backtest_a_share_five_factor_daily_execution_v1 import (  # noqa: E402
    OUT, TOP_K, CAP, build_toxic_rank, apply_veto, _to_ts_code,
)
from analyze_a_share_price_feasibility_v1 import price_panel, apply_price_filter  # noqa: E402

CAPITAL = 500_000.0
FACTORS5 = ["ep", "bm", "div_yield", "accruals", "g2"]
CORR_GATE = 0.50


def log(m):
    print(m, flush=True)


def main() -> int:
    qlib.init(provider_uri=str(QLIB_DIR), region=REG_CN)
    v3.ACCOUNT = int(CAPITAL)
    calendar = pd.DatetimeIndex(pd.to_datetime(
        pd.read_csv(QLIB_DIR / "calendars" / "day.txt", header=None)[0]))

    snap10 = pd.read_pickle(OUT / "snapshots_500k_10day.pkl")
    P = price_panel()
    log(f"snapshots {len(snap10)} ; price panel {P.shape}")

    # ---------- 附加 lowprice ----------
    snaps5, corr_rows = {}, []
    for date, frame in snap10.items():
        f = frame.copy()
        if date in P.index:
            c = P.loc[date].reindex(f["ts_code"]).to_numpy(dtype=float)
        else:
            c = np.full(len(f), np.nan)
        f["lowprice"] = -c
        # 供 composite6 用的 lowprice rank（在候选集内）
        snaps5[date] = f
        # ---------- Q1 正交性 ----------
        sub = f.dropna(subset=["lowprice"] + FACTORS5)
        if len(sub) < 100:
            continue
        row = {"date": date}
        r_lp = sub["lowprice"].rank()
        for k in FACTORS5:
            row[k] = float(np.corrcoef(r_lp, sub[k].rank())[0, 1])
        popt = (sub[FACTORS5].rank(pct=True).mean(axis=1))
        row["composite5_rank"] = float(np.corrcoef(r_lp, popt.rank())[0, 1])
        corr_rows.append(row)

    corr = pd.DataFrame(corr_rows)
    log("\n=== Q1 正交性: lowprice 与各因子的截面 Spearman 相关 (255 期均值) ===")
    for c in FACTORS5 + ["composite5_rank"]:
        if c in corr.columns:
            log(f"  corr(lowprice, {c:<14}) = {corr[c].mean():+.4f}   "
                f"(期间 std {corr[c].std():.3f})")
    cmax = float(abs(corr["composite5_rank"].mean()))
    log(f"  -> 与 composite5 的 |corr| = {cmax:.4f}  "
        f"({'> 0.5 高度重叠' if cmax > CORR_GATE else '<= 0.5 非高度重叠'})")

    # ---------- 构造 composite6 ----------
    snaps6 = {}
    for date, f in snaps5.items():
        g = f.copy()
        cols = FACTORS5 + ["lowprice"]
        ranks = pd.concat([g[c].rank(method="first", pct=True) for c in cols], axis=1)
        n_ok = ranks.notna().sum(axis=1)
        comp = ranks.mean(axis=1)
        comp[n_ok < 5] = np.nan          # 6 个里至少 5 个非空
        g["composite6"] = comp
        valid = g.dropna(subset=["composite6", "log_size", "l1_code"])
        if len(valid) < 50:
            g["neutral_composite"] = np.nan
        else:
            g["neutral_composite"] = ols_residual(
                valid["composite6"], valid["l1_code"], valid["log_size"]).reindex(g.index)
        snaps6[date] = g

    # ---------- 三臂 ----------
    toxic = build_toxic_rank(calendar)
    arms = {}
    arms["A_comp5_pricefilter"] = apply_price_filter(
        apply_veto(snaps5, toxic, TOP_K, CAP), P, TOP_K, CAPITAL, shift=0)[0]
    arms["B_comp6_pricefilter"] = apply_price_filter(
        apply_veto(snaps6, toxic, TOP_K, CAP), P, TOP_K, CAPITAL, shift=0)[0]
    arms["C_comp6_nofilter"] = apply_veto(snaps6, toxic, TOP_K, CAP)

    rows = []
    for name, snaps in arms.items():
        sig = signal_from_snapshots(snaps, calendar, TOP_K, CAP)
        bt = run_backtest(sig, TOP_K)
        bt["arm"] = name
        rows.append(bt)
        st = bt[bt["cost_scenario"] == "stress"].set_index("stage")
        log(f"  --- {name}: full={st.loc['full','net_excess_annualized_return']:+.4f} "
            f"IR={st.loc['full','net_excess_ir']:+.3f} "
            f"holdout={st.loc['holdout','net_excess_annualized_return']:+.4f} "
            f"new_cov={st.loc['new_coverage','net_excess_annualized_return']:+.4f}")

    bt = pd.concat(rows, ignore_index=True)
    bt.to_csv(OUT / "lowprice_incremental_summary.csv", index=False)
    log("\n=== 三臂对照 (stress, 净超额) ===")
    log(bt[bt["cost_scenario"] == "stress"].pivot_table(
        index="stage", columns="arm",
        values="net_excess_annualized_return").round(4).to_string())
    log("\n=== IR ===")
    log(bt[bt["cost_scenario"] == "stress"].pivot_table(
        index="stage", columns="arm", values="net_excess_ir").round(3).to_string())

    s = bt[bt["cost_scenario"] == "stress"].pivot_table(
        index="stage", columns="arm", values="net_excess_annualized_return")
    gain_full = float(s.loc["full", "B_comp6_pricefilter"] - s.loc["full", "A_comp5_pricefilter"])
    gain_hold = float(s.loc["holdout", "B_comp6_pricefilter"] - s.loc["holdout", "A_comp5_pricefilter"])
    gain_new = float(s.loc["new_coverage", "B_comp6_pricefilter"]
                     - s.loc["new_coverage", "A_comp5_pricefilter"])
    verdict = ("redundant" if cmax > CORR_GATE
               else "adopt" if (gain_full > 0 and gain_hold > -0.01) else "reject")
    log(f"\n>>> B-A 增量: full {gain_full:+.4f} / holdout {gain_hold:+.4f} / "
        f"new_cov {gain_new:+.4f}")
    log(f"=== VERDICT: {verdict} ===")
    (OUT / "lowprice_incremental_decision.json").write_text(json.dumps({
        "verdict": verdict,
        "corr_with_composite5": cmax,
        "corr_detail": {c: float(corr[c].mean()) for c in FACTORS5 + ["composite5_rank"]},
        "gain_full": gain_full, "gain_holdout": gain_hold, "gain_new_coverage": gain_new,
    }, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
