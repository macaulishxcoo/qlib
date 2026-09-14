#!/usr/bin/env python
"""风格暴露诊断: 策略在【市场上涨】时到底是赚还是亏?

回答的问题: 用户观察到"市场逆风时表现好, 市场好时收益反而为负"。
本脚本量化: ① 超额收益与市场收益的相关性; ② 上涨/下跌市中的条件超额;
③ 上/下行捕获率; ④ 市场最强的月份里策略是否亏钱。
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd

REPO = Path("/mnt/d/workspaces/qlib")
OUT = REPO / "output" / "live" / "decay_monitor"
ANN = 244


def main() -> int:
    df = pd.read_csv(OUT / "backtest_daily.csv", parse_dates=["datetime"]).set_index("datetime")
    df = df.sort_index()
    df["excess"] = df["return"] - df["bench"] - df["cost"]
    df["net"] = df["return"] - df["cost"]

    bench_ann = (1 + df["bench"]).prod() ** (ANN / len(df)) - 1
    net_ann = (1 + df["net"]).prod() ** (ANN / len(df)) - 1
    print(f"样本 {df.index[0].date()} .. {df.index[-1].date()}  ({len(df)} 日)")
    print(f"  策略年化 {net_ann:+.4f}   中证1000 年化 {bench_ann:+.4f}")

    # ---------- ① 相关性 ----------
    c_ex = float(np.corrcoef(df["excess"], df["bench"])[0, 1])
    c_net = float(np.corrcoef(df["net"], df["bench"])[0, 1])
    print(f"\n① 日度相关性")
    print(f"  corr(策略超额, 市场) = {c_ex:+.3f}")
    print(f"  corr(策略净值, 市场) = {c_net:+.3f}")

    # ---------- ② 条件超额 (日度) ----------
    up, dn = df[df["bench"] > 0], df[df["bench"] < 0]
    print(f"\n② 条件表现 (日度, 年化)")
    for lbl, s in (("市场上涨日", up), ("市场下跌日", dn)):
        if len(s) < 20:
            continue
        print(f"  {lbl:<10} n={len(s):>5}  策略 {s['net'].mean()*ANN:>+8.2%}  "
              f"市场 {s['bench'].mean()*ANN:>+8.2%}  日超额 {s['excess'].mean()*ANN:>+8.2%}")

    # ---------- ③ 月度: 上/下行捕获 ----------
    m = df.resample("ME").apply(lambda x: pd.Series({
        "net": (1 + x["net"]).prod() - 1,
        "bench": (1 + x["bench"]).prod() - 1,
        "excess": (1 + x["excess"]).prod() - 1}) if len(x) else pd.Series(
        {"net": np.nan, "bench": np.nan, "excess": np.nan})).dropna()
    mu, md = m[m["bench"] > 0], m[m["bench"] < 0]
    up_cap = mu["net"].mean() / mu["bench"].mean() if len(mu) else np.nan
    dn_cap = md["net"].mean() / md["bench"].mean() if len(md) else np.nan
    print(f"\n③ 月度上/下行捕获 (n={len(m)})")
    print(f"  上涨月 ({len(mu)} 个): 策略均 {mu['net'].mean():+.2%}  市场均 {mu['bench'].mean():+.2%}  "
          f"月均超额 {mu['excess'].mean():+.2%}")
    print(f"  下跌月 ({len(md)} 个): 策略均 {md['net'].mean():+.2%}  市场均 {md['bench'].mean():+.2%}  "
          f"月均超额 {md['excess'].mean():+.2%}")
    print(f"  上行捕获率 {up_cap:.2f}   下行捕获率 {dn_cap:.2f}")

    # ---------- ④ 市场最强 / 最弱 的月份 ----------
    print(f"\n④ 市场表现最极端的分组 (按市场月收益十分位, 组均超额)")
    m2 = m.copy()
    m2["dec"] = pd.qcut(m2["bench"], 10, labels=False, duplicates="drop")
    g = m2.groupby("dec").agg(market=("bench", "mean"), strategy=("net", "mean"),
                              excess=("excess", "mean"), n=("bench", "size"))
    for i, r in g.iterrows():
        tag = " ← 市场最强" if i == g.index.max() else (" ← 市场最弱" if i == g.index.min() else "")
        print(f"  D{int(i)+1:<2} n={int(r['n']):>3}  市场 {r['market']:>+7.2%}  "
              f"策略 {r['strategy']:>+7.2%}  超额 {r['excess']:>+7.2%}{tag}")

    # ---------- ⑤ 市场大涨年 ----------
    print(f"\n⑤ 市场年度表现最好的 3 年: 策略是否亏钱?")
    y = df.resample("YE").apply(lambda x: pd.Series({
        "net": (1 + x["net"]).prod() - 1,
        "bench": (1 + x["bench"]).prod() - 1,
        "excess": (1 + x["excess"]).prod() - 1}) if len(x) else pd.Series(
        {"net": np.nan, "bench": np.nan, "excess": np.nan})).dropna()
    for d, r in y.nlargest(3, "bench").iterrows():
        print(f"  {d.year}  市场 {r['bench']:>+8.2%}  策略 {r['net']:>+8.2%}  "
              f"超额 {r['excess']:>+8.2%}")

    (OUT / "style_exposure.json").write_text(json.dumps({
        "corr_excess_market": c_ex, "corr_net_market": c_net,
        "up_capture": float(up_cap), "down_capture": float(dn_cap),
        "up_month_excess": float(mu["excess"].mean()),
        "down_month_excess": float(md["excess"].mean()),
        "best_market_year": {str(d.year): float(r["net"]) for d, r in y.nlargest(3, "bench").iterrows()},
    }, indent=2, ensure_ascii=False))
    m.to_csv(OUT / "monthly_returns.csv")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
