#!/usr/bin/env python
"""基准口径标定: 等权全池 vs 常用指数 (2018-2026)。

动机: 隔夜/日内线与涨停事件线都以「可买全池等权」为超额基准, 两条线全部为负。
先确认这个基准有多苛刻, 否则会把"基准太强"误读成"策略无效"。
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
INDEXES = ["SH000300", "SH000905", "SH000852", "SH000016", "SH000001"]
ANN = 244.0


def main() -> int:
    import qlib
    from qlib.config import REG_CN
    from qlib.data import D

    qlib.init(provider_uri=str(STORE), region=REG_CN)

    df = D.features(D.instruments(market="all"), ["$open", "$close", "$volume"],
                    start_time=START, end_time=END, freq="day")
    df.columns = ["open", "close", "volume"]
    df = df[~df.index.duplicated()]
    codes = df.index.get_level_values(0)

    O = df["open"].unstack(0).sort_index()
    C = df["close"].unstack(0).sort_index()
    V = df["volume"].unstack(0).sort_index()

    main = codes.str.startswith("SH6") | codes.str.startswith("SZ00")
    keep = sorted(set(codes[main]))          # 仅用于等权全池; 指数列必须保留

    # 等权全池: 日度 open-to-open 等权, 剔除停牌
    oret = (O.shift(-1) / O) - 1.0
    live = (V > 0) & O.notna()
    ew = oret[keep].where(live[keep]).mean(axis=1, skipna=True).dropna()
    n_names = live[keep].sum(axis=1).reindex(ew.index)

    rows = []
    for code in INDEXES + [None]:
        if code is None:
            r = ew
            label = "等权全池(主板)"
            n = float(n_names.mean())
        else:
            if code not in O.columns:
                continue
            r = ((O[code].shift(-1) / O[code]) - 1.0).dropna()
            label = code
            n = np.nan
        r = r[(r.index >= START) & (r.index <= END)]
        if len(r) < 100:
            continue
        cum = (1 + r).cumprod()
        yrs = len(r) / ANN
        ann = float(cum.iloc[-1] ** (1 / yrs) - 1)
        vol = float(r.std() * np.sqrt(ANN))
        mdd = float((cum / cum.cummax() - 1).min())
        rows.append({"benchmark": label, "n_days": int(len(r)), "ann_return": ann,
                     "ann_vol": vol, "mdd": mdd, "sharpe": ann / vol if vol else np.nan,
                     "avg_names": n})

    out = pd.DataFrame(rows).sort_values("ann_return", ascending=False)
    out.to_csv(OUT / "benchmark_returns.csv", index=False)

    print(f"\n=== 基准标定 {START} ~ {END} (open-to-open, 未扣成本) ===")
    print(f"{'基准':<16}{'年化':>10}{'波动':>9}{'最大回撤':>11}{'Sharpe':>9}{'日均只数':>10}")
    for _, r in out.iterrows():
        print(f"{r['benchmark']:<16}{r['ann_return']:>+10.4f}{r['ann_vol']:>9.4f}"
              f"{r['mdd']:>+11.4f}{r['sharpe']:>9.2f}"
              f"{(r['avg_names'] if np.isfinite(r['avg_names']) else float('nan')):>10.0f}")

    ew_ann = float(out[out["benchmark"] == "等权全池(主板)"]["ann_return"].iloc[0])
    print(f"\n关键: 等权全池 {ew_ann:+.4f}/年")
    for _, r in out.iterrows():
        if r["benchmark"] == "等权全池(主板)":
            continue
        print(f"  以 {r['benchmark']} 为基准 -> 等权全池的'超额' = {ew_ann - r['ann_return']:+.4f}/年")

    (OUT / "summary.json").write_text(json.dumps({
        "window": [START, END], "equal_weight_universe_ann": ew_ann,
        "benchmarks": out.to_dict(orient="records"),
    }, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
