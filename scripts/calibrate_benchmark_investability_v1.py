#!/usr/bin/env python
"""基准可投资性标定: 日度再平衡等权 vs 月度/季度再平衡等权。

动机: 前两条日频线均以「日度再平衡等权全池」为超额基准。该基准持有 3,372 只
并**每日**再平衡, 会免费收割短期反转 (rebalancing bonus), 现实中不可实现。
若该 bonus 很大, 则既有"超额为负"的结论被系统性低估。

同时给出 中证1000 对照, 明确"10% 超额"在哪个口径下衡量。
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd

STORE = Path.home() / ".qlib" / "qlib_data" / "cn_data_2026"
OUT = Path(__file__).resolve().parents[1] / "output" / "analysis_static" / "benchmark_calibration_v1"
OUT.mkdir(parents=True, exist_ok=True)

START, END = "2018-01-01", "2026-06-30"
ANN = 244.0


def stats(r: pd.Series, label: str) -> dict:
    cum = (1 + r).cumprod()
    yrs = len(r) / ANN
    ann = float(cum.iloc[-1] ** (1 / yrs) - 1)
    vol = float(r.std() * np.sqrt(ANN))
    mdd = float((cum / cum.cummax() - 1).min())
    return {"benchmark": label, "ann_return": ann, "ann_vol": vol, "mdd": mdd,
            "sharpe": ann / vol if vol else np.nan, "n_days": int(len(r))}


def main() -> int:
    import qlib
    from qlib.config import REG_CN
    from qlib.data import D

    qlib.init(provider_uri=str(STORE), region=REG_CN)
    df = D.features(D.instruments(market="all"), ["$open", "$volume"],
                    start_time=START, end_time=END, freq="day")
    df.columns = ["open", "volume"]
    df = df[~df.index.duplicated()]
    codes = df.index.get_level_values(0)
    main = codes.str.startswith("SH6") | codes.str.startswith("SZ00")

    O = df["open"].unstack(0).sort_index()
    V = df["volume"].unstack(0).sort_index()
    keep = sorted(set(codes[main]))

    oret = (O.shift(-1) / O) - 1.0                 # open(t)->open(t+1)
    live = (V > 0) & O.notna()
    R = oret[keep].where(live[keep])
    R = R.loc[(R.index >= START) & (R.index <= END)]

    # 1) 日度再平衡等权
    ew_daily = R.mean(axis=1, skipna=True).dropna()

    # 2) 月度 / 季度再平衡等权 (期内买入持有, 期末等权重置)
    def period_ew(freq: str) -> pd.Series:
        out = []
        for _, blk in R.groupby(pd.Grouper(freq=freq)):
            if blk.empty:
                continue
            # 期初存活标的; 期内缺失收益记为 0 (停牌不交易)
            r0 = blk.fillna(0.0)
            port = (1 + r0).prod(axis=0, skipna=True) - 1.0
            valid = blk.notna().sum(axis=0) > 0
            if valid.sum() == 0:
                continue
            out.append(pd.Series(port[valid].mean(), index=[blk.index[-1]]))
        s = pd.concat(out).sort_index()
        return s

    # 把周期性收益展开成日度序列用于统一统计
    def expand(period_ret: pd.Series) -> pd.Series:
        idx = R.index
        ser = pd.Series(np.nan, index=idx)
        marks = list(period_ret.index)
        start = 0
        for i, m in enumerate(marks):
            loc = idx.get_loc(m)
            ser.iloc[start:loc + 1] = 0.0
            ser.iloc[loc] = period_ret.iloc[i]
            start = loc + 1
        return ser.dropna()

    ew_m = expand(period_ew("ME"))
    ew_q = expand(period_ew("QE"))

    rows = [stats(ew_daily, "等权全池-日度再平衡"),
            stats(ew_m, "等权全池-月度再平衡"),
            stats(ew_q, "等权全池-季度再平衡")]
    if "SH000852" in O.columns:
        r = ((O["SH000852"].shift(-1) / O["SH000852"]) - 1.0).dropna()
        r = r[(r.index >= START) & (r.index <= END)]
        rows.append(stats(r, "SH000852(中证1000)"))

    out = pd.DataFrame(rows).sort_values("ann_return", ascending=False)
    out.to_csv(OUT / "benchmark_investable.csv", index=False)

    print(f"\n=== 基准可投资性标定 {START} ~ {END} (未扣成本) ===")
    print(f"{'基准':<26}{'年化':>10}{'波动':>9}{'最大回撤':>11}{'Sharpe':>9}")
    for _, r in out.iterrows():
        print(f"{r['benchmark']:<26}{r['ann_return']:>+10.4f}{r['ann_vol']:>9.4f}"
              f"{r['mdd']:>+11.4f}{r['sharpe']:>9.2f}")

    d = float(out[out["benchmark"] == "等权全池-日度再平衡"]["ann_return"].iloc[0])
    m = float(out[out["benchmark"] == "等权全池-月度再平衡"]["ann_return"].iloc[0])
    print(f"\n>>> 日度再平衡 bonus (不可实现部分) = {d - m:+.4f}/年")
    print(f">>> 以【月度再平衡等权】为基准时, 前两条线需重新评估 (此前低估约 {d - m:+.4f}/年)")
    if "SH000852" in O.columns:
        i = float(out[out["benchmark"] == "SH000852(中证1000)"]["ann_return"].iloc[0])
        print(f">>> 月度再平衡等权 vs 中证1000 = {m - i:+.4f}/年")

    (OUT / "investable_summary.json").write_text(json.dumps({
        "window": [START, END], "ew_daily": d, "ew_monthly": m,
        "daily_rebalance_bonus": d - m,
    }, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
