#!/usr/bin/env python
"""回撤与危机期分析 —— 最终策略在最坏时段到底会怎样。

输入: output/live/decay_monitor/backtest_daily.csv (monitor --backtest 生成, 50万口径)
输出: 前三大回撤区间、2024-01 小市值流动性危机专项、以及策略与基准的对比
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd

REPO = Path("/mnt/d/workspaces/qlib")
OUT = REPO / "output" / "live" / "decay_monitor"
ANN = 244


def episodes(nav: pd.Series, top: int = 3):
    """识别前 N 大回撤区间 (峰 -> 谷 -> 收复)。"""
    peak = nav.cummax()
    dd = nav / peak - 1.0
    eps = []
    in_dd = False
    start = None
    for d, v in dd.items():
        if not in_dd and v < -1e-9:
            in_dd, start = True, d
        elif in_dd and v >= -1e-9:
            seg = dd.loc[start:d]
            eps.append({"start": start, "trough": seg.idxmin(), "end": d,
                        "depth": float(seg.min())})
            in_dd = False
    if in_dd:
        seg = dd.loc[start:]
        eps.append({"start": start, "trough": seg.idxmin(), "end": None,
                    "depth": float(seg.min())})
    eps.sort(key=lambda e: e["depth"])
    return eps[:top]


def main() -> int:
    p = OUT / "backtest_daily.csv"
    df = pd.read_csv(p, parse_dates=["datetime"]).set_index("datetime").sort_index()
    df["excess"] = df["return"] - df["bench"] - df["cost"]
    df["net"] = df["return"] - df["cost"]

    nav = (1 + df["net"]).cumprod()
    bnav = (1 + df["bench"]).cumprod()
    xnav = (1 + df["excess"]).cumprod()

    print("=== 最终策略: 净值与回撤 ===")
    print(f"  期初 {nav.index[0].date()} .. 期末 {nav.index[-1].date()}  ({len(nav)} 日)")
    print(f"  策略累计 {nav.iloc[-1]-1:+.2%}   中证1000 累计 {bnav.iloc[-1]-1:+.2%}"
          f"   超额累计 {xnav.iloc[-1]-1:+.2%}")
    for lbl, s in (("策略", nav), ("中证1000", bnav), ("超额", xnav)):
        dd = (s / s.cummax() - 1).min()
        print(f"  最大回撤 {lbl:<9}: {dd:+.2%}")

    print("\n=== 策略前三大回撤区间 ===")
    eps = episodes(nav, 3)
    for i, e in enumerate(eps, 1):
        s0, t0, e0 = e["start"], e["trough"], e["end"]
        seg = df.loc[s0:(e0 or df.index[-1])]
        heal = "" if e0 is None else f" 收复 {e0.date()} " \
                                    f"({len(df.loc[t0:e0])} 交易日)"
        print(f"  #{i} {s0.date()} -> 谷 {t0.date()}  深度 {e['depth']:+.2%}{heal}")
        print(f"      区间内: 策略 {((1+seg['net']).prod()-1):+.2%} | "
              f"中证1000 {((1+seg['bench']).prod()-1):+.2%} | "
              f"超额 {((1+seg['excess']).prod()-1):+.2%}")

    print("\n=== 危机期专项 ===")
    windows = {
        "2018 熊市": ("2018-01-01", "2018-12-31"),
        "2020-02 疫情急跌": ("2020-01-20", "2020-03-31"),
        "2021-02 核心资产崩": ("2021-02-10", "2021-03-31"),
        "2022 全年": ("2022-01-01", "2022-12-31"),
        "2024-01 小市值流动性危机": ("2024-01-02", "2024-02-08"),
        "2024 全年": ("2024-01-01", "2024-12-31"),
        "2025H2-2026H1": ("2025-07-01", "2026-06-30"),
    }
    rows = []
    for name, (a, b) in windows.items():
        seg = df.loc[a:b]
        if len(seg) < 5:
            continue
        st = float((1 + seg["net"]).prod() - 1)
        bm = float((1 + seg["bench"]).prod() - 1)
        ex = float((1 + seg["excess"]).prod() - 1)
        rows.append({"window": name, "days": len(seg), "strategy": st,
                     "csi1000": bm, "excess": ex})
        print(f"  {name:<24} {len(seg):>4}日  策略 {st:>+8.2%}  "
              f"中证1000 {bm:>+8.2%}  超额 {ex:>+8.2%}")

    pd.DataFrame(rows).to_csv(OUT / "crisis_windows.csv", index=False)
    (OUT / "drawdown_episodes.json").write_text(json.dumps(
        [{**{k: (str(v.date()) if hasattr(v, "date") else v) for k, v in e.items()}}
         for e in eps], indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
