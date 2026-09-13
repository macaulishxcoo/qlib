#!/usr/bin/env python
"""探索性诊断: 隔夜/日内分解因子的十分位单调性表 (EXPLORATORY, 非协议端点)。

目的: 协议 v1 判定 not_supported —— IC 极强 (|t| 达 20+) 但 long-only 十分位
      组合在 base 与 stress 成本下全线亏损。本脚本只回答一个诊断问题:
      超额收益到底分布在截面的哪一段? 是"多头端不涨"还是"空头端才有效"?

纪律声明:
  * 本脚本不改变协议 v1 的判定 (not_supported 已冻结)。
  * 不据此调整任何阈值或窗口。产出仅用于解释失败机制, 并为可能的 v2 协议提供依据。
  * 使用 h=5 前瞻 (open-to-open), 重叠样本, 故仅作单调性方向的定性诊断,
    其 t 值不可当作独立检验 (已在报告中标注)。
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

from analyze_a_share_overnight_intraday_daily_v1 import (  # noqa: E402
    ANN, EVAL_END, EVAL_START, OUT, build_factors, load_panel, log, tradeability,
)

FOCUS = ["id_vol_20", "on_vol_20", "id_mom_20", "on_id_spread_20", "id_mom_5", "on_id_spread_5"]
NDEC = 10
DEPTH = 5          # 前瞻深度, 与协议 h=5 一致
MIN_NAMES = 200


def main() -> int:
    log("-> loading panel")
    O, C, V = load_panel()
    F = build_factors(O, C)

    fwd = (O.shift(-(1 + DEPTH)) / O.shift(-1)) - 1.0
    # 建仓在 open(t+1) -> 必须用 open(t+1) 的可买性过滤 (涨停开盘买不进)
    buy_ok, _ = tradeability(O, C, V)
    entry = buy_ok.shift(-1)                       # entry(t) = 能否在 open(t+1) 建仓
    fwd = fwd.where(entry & fwd.notna())
    log(f"-> entry filter: 保留 {fwd.notna().to_numpy().mean():.3f} 的样本")

    dates = O.index
    sel = dates[(dates >= EVAL_START) & (dates <= EVAL_END)]
    fwd = fwd.reindex(sel)

    uni = fwd.mean(axis=1, skipna=True)
    log(f"-> eval {sel[0].date()}..{sel[-1].date()}  n={len(sel)}  "
        f"universe {DEPTH}d mean={uni.mean():+.5f} -> ann={uni.mean()*ANN/DEPTH:+.4f}")

    rows = []
    for name in FOCUS:
        fac = F[name].reindex(sel)
        valid = fac.notna() & fwd.notna()
        n_ok = valid.sum(axis=1)
        rk = fac.where(valid).rank(axis=1, pct=True)
        dec = np.ceil(rk * NDEC).clip(1, NDEC).where(n_ok >= MIN_NAMES)
        means = {}
        for d in range(1, NDEC + 1):
            m = (dec == d) & valid
            means[d] = fwd.where(m).mean(axis=1, skipna=True)
        tab = pd.DataFrame(means)
        avg = tab.mean() * ANN / DEPTH                      # 年化
        spread = (tab[NDEC] - tab[1]).mean() * ANN / DEPTH
        rows.append({"factor": name, "D1": avg[1], "D5": avg[5], "D10": avg[NDEC],
                     "D10-D1": spread, "universe": uni.mean() * ANN / DEPTH,
                     "D1_univ": avg[1] - uni.mean() * ANN / DEPTH,
                     "D10_univ": avg[NDEC] - uni.mean() * ANN / DEPTH,
                     "_tab": avg})
        log(f"\n-- {name}  (年化, h={DEPTH}, 未扣成本)")
        log("   " + " ".join(f"D{d}={avg[d]:+.3f}" for d in range(1, NDEC + 1)))
        log(f"   D10-D1={spread:+.4f}  D1-uni={rows[-1]['D1_univ']:+.4f}  "
            f"D10-uni={rows[-1]['D10_univ']:+.4f}")

    summ = pd.DataFrame([{k: v for k, v in r.items() if k != "_tab"} for r in rows])
    OUT.mkdir(parents=True, exist_ok=True)
    summ.to_csv(OUT / "decile_diagnostic.csv", index=False)
    pd.DataFrame({r["factor"]: r["_tab"] for r in rows}).to_csv(OUT / "decile_detail.csv")
    log("\n=== 诊断结论 ===")
    for r in rows:
        t = r["_tab"]
        mono = np.corrcoef(np.arange(1, NDEC + 1), t.values)[0, 1]
        tail = "空头端主导" if abs(r["D1_univ"]) > abs(r["D10_univ"]) else "多头端主导"
        log(f"   {r['factor']:<18} 单调性 corr={mono:+.2f}  {tail} "
            f"(D1-uni={r['D1_univ']:+.3f}, D10-uni={r['D10_univ']:+.3f})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
