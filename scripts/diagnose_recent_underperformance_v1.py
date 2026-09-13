#!/usr/bin/env python
"""近一年亏损归因: 是绝对亏损, 还是跑输上涨的市场?

输入: output/live/decay_monitor/backtest_daily.csv (由 monitor_strategy_decay_v1.py --backtest 生成)
      含 return(策略毛收益), bench(中证1000), cost

同时给出等权全池(主板)作为第二参照 —— 用于区分
  "价值因子跑输" vs "小市值跑输" vs "整体市场下跌"
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

REPO = Path("/mnt/d/workspaces/qlib")
ANN = 244
STAGES = {
    "全期 full": ("2016-01-01", "2026-06-30"),
    "★2020起 剔除开发段": ("2020-01-01", "2026-06-30"),
    "2016-2019 development": ("2016-01-01", "2019-12-31"),
    "2020-2022 confirmation": ("2020-01-01", "2022-12-31"),
    "2023-2025H1 holdout": ("2023-01-01", "2025-06-30"),
    "2025H2-2026H1 new_coverage": ("2025-07-01", "2026-06-30"),
    "最近12个月": None,
}


def main() -> int:
    p = REPO / "output" / "live" / "decay_monitor" / "backtest_daily.csv"
    df = pd.read_csv(p, parse_dates=["datetime"]).set_index("datetime").sort_index()
    df["excess"] = df["return"] - df["bench"] - df["cost"]
    df["net"] = df["return"] - df["cost"]

    # 等权全池 (主板) 作为第二参照
    sys.path.insert(0, str(REPO / "scripts"))
    ew = None
    try:
        from backtest_a_share_toxic_veto_broad_v1 import load_panel
        import qlib
        from qlib.config import REG_CN
        qlib.init(provider_uri=str(Path.home() / ".qlib" / "qlib_data" / "cn_data_2026"),
                  region=REG_CN)
        O, C, V, A = load_panel()
        cols = [c for c in C.columns if c != "SH000852"]
        oret = (O[cols].shift(-1) / O[cols]) - 1.0
        live = (V[cols] > 0) & O[cols].notna()
        ew = oret.where(live).mean(axis=1, skipna=True).dropna()
    except Exception as e:
        print(f"(等权全池参照不可用: {e})")

    def ann(s):
        s = s.dropna()
        if len(s) < 20:
            return np.nan
        return float((1 + s).prod() ** (ANN / len(s)) - 1)

    print("=== 分阶段: 策略 vs 中证1000 vs 等权全池 (年化) ===")
    print(f"{'阶段':<28}{'策略净':>10}{'中证1000':>11}{'净超额':>10}{'等权全池':>11}{'策略-等权':>11}")
    rows = []
    for name, rng in STAGES.items():
        if rng is None:
            sub = df.iloc[-ANN:]
        else:
            sub = df.loc[rng[0]:rng[1]]
        if len(sub) < 20:
            continue
        a = ann(sub["net"])
        b = ann(sub["bench"])
        e = ann(sub["excess"])
        w = np.nan
        if ew is not None:
            s2 = ew[(ew.index >= sub.index[0]) & (ew.index <= sub.index[-1])]
            w = ann(s2)
        rows.append(dict(stage=name, strategy_net=a, csi1000=b, excess=e, ew_universe=w,
                         strat_minus_ew=(a - w) if np.isfinite(w) else np.nan,
                         n_days=int(len(sub))))
        print(f"{name:<28}{a:>+10.4f}{b:>+11.4f}{e:>+10.4f}"
              f"{(w if np.isfinite(w) else float('nan')):>+11.4f}"
              f"{(a - w if np.isfinite(w) else float('nan')):>+11.4f}")

    print("\n=== 最近 12 个月逐月 (策略净 / 中证1000 / 净超额) ===")
    sub = df.iloc[-ANN:]
    m = sub.resample("ME").apply(lambda x: (1 + x).prod() - 1 if len(x) else np.nan)
    for d, r in m.iterrows():
        print(f"  {d.date()}  策略净={r['net']:+.4f}  中证1000={r['bench']:+.4f}  "
              f"超额={r['excess']:+.4f}")

    print("\n=== 滚动 12 个月净超额: vs 中证1000 与 vs 等权全池 ===")
    if ew is not None:
        ew_a = ew.reindex(df.index).ffill()
        # 必须先对齐成同一 index 再滚动, 否则两个序列长度不同会取错窗口
        comb = pd.DataFrame({"ex1000": df["excess"], "ew": ew_a}).dropna()
        W = 244
        r_idx, r_1000, r_ew = [], [], []
        for i in range(W, len(comb) + 1):
            r_idx.append(comb.index[i - 1])
            r_1000.append(float((1 + comb["ex1000"].iloc[i - W:i]).prod() - 1))
            r_ew.append(float((1 + comb["ew"].iloc[i - W:i]).prod() - 1))
        roll = pd.DataFrame({"vs_csi1000": r_1000, "vs_ew_universe": r_ew},
                            index=pd.DatetimeIndex(r_idx))
        roll.to_csv(REPO / "output" / "live" / "decay_monitor" / "rolling_both_benchmarks.csv")
        print(f"  (对齐后 n={len(comb)} 日, 末日 {comb.index[-1].date()})")
        for c in roll.columns:
            s = roll[c]
            print(f"  {c:<18} 为正比例={float((s>0).mean()):.3f}  中位={s.median():+.4f}  "
                  f"当前={s.iloc[-1]:+.4f}  最差={s.min():+.4f}")
        n = min(len(roll), 8)
        print("\n  最近 8 个滚动12个月窗口:")
        for d, row in roll.tail(n).iterrows():
            print(f"    {d.date()}  vs中证1000={row['vs_csi1000']:+.4f}   "
                  f"vs等权全池={row['vs_ew_universe']:+.4f}")

    pd.DataFrame(rows).to_csv(
        REPO / "output" / "live" / "decay_monitor" / "stage_decomposition.csv", index=False)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
