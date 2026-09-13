#!/usr/bin/env python
"""申万一级行业轮动 —— 诊断阶段 v1。

协议: research/protocols/a_share_sw_industry_rotation_protocol_v1.md

只回答"有没有信号", 不建组合。
  端点 A: 按过去 k 日收益排序 30 个行业, 看未来 h 日收益的五分位
  端点 B: 开发 2018-2021 / 样本外 2022-2026 两段 + 逐年符号
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd

REPO = Path("/mnt/d/workspaces/qlib")
SRC = REPO / "data" / "external" / "tushare" / "sw_industry_index_v1" / "normalized" / "sw_industry_daily.csv.gz"
OUT = REPO / "output" / "analysis_static" / "sw_industry_rotation_v1"
OUT.mkdir(parents=True, exist_ok=True)

DEV = ("2018-01-01", "2021-12-31")
OOS = ("2022-01-01", "2026-06-30")
K_GRID = (1, 5, 10, 20)
H_GRID = (1, 5, 10)
MIN_SPREAD = 0.010          # 单期 1.0pp 门槛 (协议 §3)
NQ = 5


def main() -> int:
    d = pd.read_csv(SRC)
    d["trade_date"] = pd.to_datetime(d["trade_date"], format="%Y%m%d")
    d = d.sort_values(["ts_code", "trade_date"])

    # --- 数据风险: 检查每个行业代码的起止日期 (分类切换会导致断裂) ---
    cov = d.groupby(["ts_code", "industry_name"])["trade_date"].agg(["min", "max", "count"])
    cov = cov.reset_index().sort_values("min")
    cov.to_csv(OUT / "industry_coverage.csv", index=False)
    print("=== 行业指数覆盖 (检查分类断裂) ===")
    print(f"{'code':<12}{'name':<10}{'start':<12}{'end':<12}{'n':>6}")
    for _, r in cov.iterrows():
        print(f"{r['ts_code']:<12}{r['industry_name']:<10}"
              f"{r['min'].date()!s:<12}{r['max'].date()!s:<12}{int(r['count']):>6}")
    starts = cov["min"].dt.year.value_counts().sort_index()
    print("起始年份分布:", dict(starts))

    # 宽表: 日期 x 行业
    px = d.pivot_table(index="trade_date", columns="ts_code", values="close").sort_index()
    names = d.drop_duplicates("ts_code").set_index("ts_code")["industry_name"].to_dict()
    print(f"\npanel: {px.shape[0]} 日 x {px.shape[1]} 行业, {px.index.min().date()}..{px.index.max().date()}")

    logret = np.log(px).diff()

    def past_ret(k):
        return px / px.shift(k) - 1.0

    def fwd_ret(h):
        return px.shift(-h) / px - 1.0

    rows, detail = [], {}
    for k in K_GRID:
        pr = past_ret(k)
        for h in H_GRID:
            fr = fwd_ret(h)
            common = pr.notna() & fr.notna()
            # 每日截面五分位
            q = pr.where(common).rank(axis=1, pct=True)
            bucket = np.ceil(q * NQ).clip(1, NQ)
            top = fr.where(bucket == NQ).mean(axis=1, skipna=True)
            bot = fr.where(bucket == 1).mean(axis=1, skipna=True)
            allm = fr.where(common).mean(axis=1, skipna=True)
            spread = (top - bot).dropna()
            for seg, (lo, hi) in (("dev", DEV), ("oos", OOS)):
                s = spread[(spread.index >= lo) & (spread.index <= hi)]
                if len(s) < 30:
                    continue
                t = float(s.mean() / (s.std() / np.sqrt(len(s)))) if s.std() > 0 else np.nan
                rows.append(dict(k=k, h=h, segment=seg, n_days=len(s),
                                 top_minus_bottom=float(s.mean()), t_stat=t,
                                 top_minus_all=float((top - allm)[(top.index >= lo) & (top.index <= hi)].mean()),
                                 bottom_minus_all=float((bot - allm)[(bot.index >= lo) & (bot.index <= hi)].mean())))
            detail[f"k{k}_h{h}"] = spread
    res = pd.DataFrame(rows)
    res.to_csv(OUT / "industry_rotation_diagnostic.csv", index=False)

    print("\n=== 端点 A/B: 五分位 Top-Bottom 价差 (未来 h 日) ===")
    print(f"{'k':>3}{'h':>4}{'分段':<6}{'n':>6}{'Top-Bot':>10}{'t':>8}{'Top-全体':>10}{'Bot-全体':>10}")
    for _, r in res.iterrows():
        print(f"{int(r['k']):>3}{int(r['h']):>4}{r['segment']:<6}{int(r['n_days']):>6}"
              f"{r['top_minus_bottom']:>+10.4f}{r['t_stat']:>8.2f}"
              f"{r['top_minus_all']:>+10.4f}{r['bottom_minus_all']:>+10.4f}")

    # --- 判定: 两段同号 且 两段绝对值均 >= MIN_SPREAD ---
    piv = res.pivot_table(index=["k", "h"], columns="segment", values="top_minus_bottom")
    ok = piv[(np.sign(piv["dev"]) == np.sign(piv["oos"]))
             & (piv["dev"].abs() >= MIN_SPREAD) & (piv["oos"].abs() >= MIN_SPREAD)]
    verdict = "signal_present" if len(ok) else "signal_absent"

    print("\n=== 逐年符号 (稳定性) ===")
    for key in ("k5_h5", "k5_h10", "k1_h5", "k20_h5", "k10_h5"):
        if key not in detail:
            continue
        s = detail[key]
        yr = s.groupby(s.index.year).mean()
        signs = "".join("+" if v > 0 else "-" for v in yr.values)
        print(f"  {key:<8} 逐年均值符号: {signs}  ({', '.join(f'{y}:{v:+.3f}' for y, v in yr.items())})")

    decision = {
        "verdict": verdict,
        "min_spread_gate": MIN_SPREAD,
        "passing_combos": [{"k": int(a), "h": int(b),
                            "dev": float(piv.loc[(a, b), "dev"]),
                            "oos": float(piv.loc[(a, b), "oos"])} for (a, b) in ok.index],
        "n_combos_tested": int(len(piv)),
    }
    (OUT / "decision.json").write_text(json.dumps(decision, indent=2, ensure_ascii=False))
    print(f"\n=== VERDICT: {verdict} ===")
    print(json.dumps(decision, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
