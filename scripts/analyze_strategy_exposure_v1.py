#!/usr/bin/env python
"""持仓暴露与归因 —— 这个策略到底在押什么。

对最终策略的每一期实际选股 (top30, 行业cap3, 经毒尾否决+价格可行性过滤),
统计其行业分布与因子暴露, 并与候选池对比得出"倾斜"。
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
    OUT, TOP_K, CAP, build_toxic_rank, apply_veto,
)
from analyze_a_share_price_feasibility_v1 import price_panel, apply_price_filter  # noqa: E402

CAPITAL = 500_000.0
FACTORS5 = ["ep", "bm", "div_yield", "accruals", "g2"]


def log(m):
    print(m, flush=True)


def main() -> int:
    qlib.init(provider_uri=str(QLIB_DIR), region=REG_CN)
    v3.ACCOUNT = int(CAPITAL)
    calendar = pd.DatetimeIndex(pd.to_datetime(
        pd.read_csv(QLIB_DIR / "calendars" / "day.txt", header=None)[0]))

    snap = pd.read_pickle(OUT / "snapshots_500k_10day.pkl")
    P = price_panel()
    toxic = build_toxic_rank(calendar)
    snaps = apply_veto(snap, toxic, TOP_K, CAP)
    snaps, _ = apply_price_filter(snaps, P, TOP_K, CAPITAL, shift=0)
    log(f"snapshots {len(snaps)}")

    rows, ind_rows, sel_detail = [], [], []
    for date, f in snaps.items():
        sel = select_with_industry_cap(f, TOP_K, CAP)
        if sel.empty:
            continue
        cand = f[f["neutral_composite"].notna()]
        # 截面分位 (0~1, 越大代表该维度越高)
        def pct(frame, col, sub):
            r = frame[col].rank(pct=True)
            return float(r.reindex(sub.index).mean())
        row = {"date": date, "n": len(sel),
               "sel_size_pct": pct(cand, "log_size", sel),
               "uni_size_pct": pct(cand, "log_size", cand),
               "sel_ep": pct(cand, "ep", sel), "uni_ep": pct(cand, "ep", cand),
               "sel_bm": pct(cand, "bm", sel), "uni_bm": pct(cand, "bm", cand),
               "sel_div": pct(cand, "div_yield", sel), "uni_div": pct(cand, "div_yield", cand),
               "sel_acc": pct(cand, "accruals", sel), "uni_acc": pct(cand, "accruals", cand),
               "sel_g2": pct(cand, "g2", sel), "uni_g2": pct(cand, "g2", cand),
               }
        # 价格分位
        if date in P.index:
            c = P.loc[date]
            cr = c.rank(pct=True)
            row["sel_price_pct"] = float(cr.reindex(sel["ts_code"].values).mean())
            row["uni_price_pct"] = float(cr.reindex(cand["ts_code"].values).mean())
        rows.append(row)
        for code, ind in zip(sel["ts_code"], sel["l1_code"]):
            ind_rows.append({"date": date, "ts_code": code, "l1_code": ind})
        sel_detail.append(sel[["ts_code", "l1_code"]].assign(date=date))

    expo = pd.DataFrame(rows).set_index("date")
    log("\n=== 因子暴露 (截面分位均值, 0.5 = 与候选池中位持平) ===")
    log(f"{'维度':<14}{'策略持仓':>10}{'候选池':>10}{'倾斜':>10}   解读")
    for dim in ["size", "price", "ep", "bm", "div", "acc", "g2"]:
        skey = f"sel_{dim}_pct" if dim in ("size", "price") else f"sel_{dim}"
        ukey = f"uni_{dim}_pct" if dim in ("size", "price") else f"uni_{dim}"
        s, u = expo[skey].mean(), expo[ukey].mean()
        tag = ("偏小/偏低" if dim in ("size", "price") else "偏高")
        tilt = s - u
        log(f"{dim:<14}{s:>10.3f}{u:>10.3f}{tilt:>+10.3f}   "
            f"{tag if abs(tilt) > 0.05 else '中性'}")

    inds = pd.DataFrame(ind_rows)
    share = inds.groupby("l1_code").size() / len(inds)
    n_cand_ind = {}
    log("\n=== 行业分布 (策略持仓占比 vs 候选池占比, 前 12) ===")
    allind = []
    for date, f in snaps.items():
        for c in f.loc[f["neutral_composite"].notna(), "l1_code"]:
            allind.append(c)
    uni_share = pd.Series(allind).value_counts(normalize=True)
    comp = pd.DataFrame({"strategy": share, "universe": uni_share}).fillna(0)
    comp["tilt"] = comp["strategy"] - comp["universe"]
    comp = comp.sort_values("strategy", ascending=False)
    log(f"{'行业代码':<14}{'策略占比':>10}{'候选池':>10}{'倾斜':>10}")
    for i, r in comp.head(12).iterrows():
        log(f"{i:<14}{r['strategy']:>10.3f}{r['universe']:>10.3f}{r['tilt']:>+10.3f}")
    log(f"\n  持仓覆盖 {len(comp)} 个行业; 最大单一行业平均占比 "
        f"{share.groupby(inds['date']).max().mean():.3f} (cap={CAP}/{TOP_K})")

    comp.to_csv(OUT / "exposure_industry.csv")
    expo.to_csv(OUT / "exposure_factors.csv")
    (OUT / "exposure_summary.json").write_text(json.dumps({
        "factor_tilts": {d: float(
            expo[f"sel_{d}_pct" if d in ("size", "price") else f"sel_{d}"].mean()
            - expo[f"uni_{d}_pct" if d in ("size", "price") else f"uni_{d}"].mean())
            for d in ["size", "price", "ep", "bm", "div", "acc", "g2"]},
        "industries": int(len(comp)),
        "top5_industry_share": float(comp["strategy"].head(5).sum()),
        "universe_top5_share": float(comp["universe"].head(5).sum()),
    }, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
