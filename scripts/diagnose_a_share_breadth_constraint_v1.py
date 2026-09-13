#!/usr/bin/env python
"""广度约束诊断: 50 万资金持有 N 只等权, 到底损失了什么?

动机: 毒尾否决线显示"选样"一项就贡献 −14pp/年, 远超否决本身的价值。
根因怀疑: 按 20 日均额降序取前 N = 挑最活跃的大市值股, 是主动的大市值押注,
而非中性的可实施性代理。

同时必须回答: 50 万 + 100 股整手, 能持有多少只、什么价位的股票?
(等权 N 只 -> 每只 500000/N 元 -> 需 100*价格 <= 500000/N)

本脚本分解以下组合 (每 10 交易日等权重置, 未含否决):
  A 全池等权                 (上界, 不可实施)
  B 仅价格可行 (P<=5000/N)
  C 系统抽样: 按流动性排序每隔 k 个取一个, 保持规模分布
  D 头部流动性: 前 N 大成交额 (此前 v1 的做法)
并给出 加否决 后的对照。
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd

import sys
sys.path.insert(0, str(Path(__file__).resolve().parent))
from backtest_a_share_toxic_veto_broad_v1 import load_panel  # noqa: E402

OUT = Path(__file__).resolve().parents[1] / "output" / "analysis_static" / "breadth_constraint_v1"
OUT.mkdir(parents=True, exist_ok=True)

START, SPLIT, END = "2018-01-01", "2022-01-01", "2026-06-30"
CAPITAL, N_HOLD, STEP, ANN = 500_000.0, 150, 10, 244.0
COST = 0.0005 + 0.0015          # 单边合计 (等权固定权重, 简化)
VETO_Q = 0.90
LIMIT_GAP = 0.095


def main() -> int:
    O, C, V, A = load_panel()
    cols = [c for c in C.columns if c != "SH000852"]
    O, C, V, A = O[cols], C[cols], V[cols], A[cols]

    on1 = O / C.shift(1) - 1.0
    id1 = C / O - 1.0
    toxic = (id1.rolling(20, min_periods=10).sum().rank(axis=1, pct=True)
             + id1.rolling(20, min_periods=10).std().rank(axis=1, pct=True)
             + on1.rolling(20, min_periods=10).std().rank(axis=1, pct=True)) / 3.0
    veto = toxic > VETO_Q
    liq = A.rolling(20, min_periods=10).mean()

    gap = O / C.shift(1) - 1.0
    live = O.notna() & (V > 0) & (O >= 2.0)
    buy_ok = live & (gap < LIMIT_GAP)
    open_ret = (O.shift(-1) / O) - 1.0
    ret = open_ret

    feas = (100.0 * C) <= (CAPITAL / N_HOLD)
    buyable = buy_ok.shift(-1)

    dates = O.index
    sel = dates[(dates >= START) & (dates <= END)]

    def systematic(mask_row, liq_row, n_target, offset=0):
        idx = mask_row.index[mask_row]
        if len(idx) <= n_target:
            return list(idx)
        order = liq_row.reindex(idx).sort_values(ascending=False)
        k = len(order) / n_target
        picks = [order.index[min(int(i * k) + offset, len(order) - 1)] for i in range(n_target)]
        return list(dict.fromkeys(picks))

    def run(mode, use_veto, offset=0, n_hold=N_HOLD):
        feasn = (100.0 * C) <= (CAPITAL / n_hold)
        e = ((~veto) if use_veto else pd.DataFrame(True, index=C.index, columns=C.columns))
        e = e.reindex(sel).fillna(False)
        f = feasn.reindex(sel).fillna(False)
        b = buyable.reindex(sel).fillna(False)
        lq = liq.reindex(sel)
        r = ret.reindex(sel)
        n = len(sel)
        port = np.full(n, np.nan)
        turn = np.zeros(n)
        cnt = np.zeros(n)
        prev = None
        for i in range(0, n - 1, STEP):
            j = i + 1
            if j >= n:
                break
            base = e.iloc[i] & b.iloc[j]
            if mode in ("B", "C", "D", "Cv", "Dv"):
                base = base & f.iloc[i]
            if mode in ("C", "Cv"):
                names = systematic(base, lq.iloc[i], n_hold, offset)
            elif mode in ("D", "Dv"):
                cand = list(base.index[base])
                names = list(lq.iloc[i].reindex(cand).sort_values(ascending=False).index[:n_hold])
            else:
                names = list(base.index[base])
            if not names:
                continue
            w = pd.Series(1.0 / len(names), index=names)
            if prev is not None:
                allc = w.index.union(prev.index)
                d = w.reindex(allc).fillna(0.0) - prev.reindex(allc).fillna(0.0)
                turn[j] = float(d[d > 0].sum())
            else:
                turn[j] = 1.0
            cnt[j] = len(names)
            for dd in range(j, min(j + STEP, n)):
                x = r.iloc[dd].reindex(names)
                if x.notna().sum() > 0:
                    port[dd] = float(x.mean(skipna=True))
            prev = w
        p = pd.Series(port, index=sel)
        net = (p - pd.Series(turn, index=sel) * COST).where(p.notna()).dropna()
        return net, pd.Series(cnt, index=sel)

    def perf(x):
        cum = (1 + x).cumprod()
        yrs = len(x) / ANN
        ann = float(cum.iloc[-1] ** (1 / yrs) - 1)
        vol = float(x.std() * np.sqrt(ANN))
        return ann, vol, float((cum / cum.cummax() - 1).min())

    MODES = [("A_全池等权_上界", "A", False), ("B_仅价格可行", "B", False),
             ("C_系统抽样150", "C", False), ("D_头部流动性150", "D", False),
             ("Cv_系统抽样150+否决", "Cv", True), ("Dv_头部流动性150+否决", "Dv", True)]

    series, rows = {}, []
    for label, mode, uv in MODES:
        x, c = run(mode, uv)
        series[label] = x
        for seg, lo, hi in (("开发2018-2021", START, SPLIT), ("样本外2022-2026", SPLIT, END)):
            s = x[(x.index >= lo) & (x.index < hi)]
            ann, vol, mdd = perf(s)
            rows.append(dict(portfolio=label, segment=seg, ann=ann, vol=vol, mdd=mdd,
                             avg_names=float(c[(c.index >= lo) & (c.index < hi)][c > 0].mean())))
    df = pd.DataFrame(rows)
    df.to_csv(OUT / "breadth_decomposition.csv", index=False)

    for seg in ("开发2018-2021", "样本外2022-2026"):
        print(f"\n=== {seg} (每10交易日等权重置, 扣成本, 未含择时) ===")
        print(f"{'组合':<24}{'年化':>10}{'波动':>9}{'回撤':>10}{'只数':>8}")
        for _, r in df[df["segment"] == seg].iterrows():
            print(f"{r['portfolio']:<24}{r['ann']:>+10.4f}{r['vol']:>9.4f}"
                  f"{r['mdd']:>+10.4f}{r['avg_names']:>8.0f}")

    # ---- 多抽样平均: 150 只组合的抽样噪声约 ±4pp/年, 单次结果不可信 ----
    NOFF = 10
    print(f"\n=== 系统抽样 {NOFF} 个偏移的平均 (消除抽样噪声) ===")
    avg_rows = []
    for label, mode, uv in (("C_系统抽样150", "C", False), ("Cv_系统抽样150+否决", "Cv", True)):
        runs = []
        for off in range(NOFF):
            x, _ = run(mode, uv, off)
            runs.append(x)
        mat = pd.DataFrame({i: r for i, r in enumerate(runs)})
        avg = mat.mean(axis=1)
        for seg, lo, hi in (("开发2018-2021", START, SPLIT), ("样本外2022-2026", SPLIT, END)):
            s = avg[(avg.index >= lo) & (avg.index < hi)]
            ann, vol, mdd = perf(s)
            subs = [perf(r[(r.index >= lo) & (r.index < hi)])[0] for r in runs]
            avg_rows.append(dict(portfolio=label, segment=seg, ann_mean=ann, vol=vol, mdd=mdd,
                                 member_min=float(np.min(subs)), member_max=float(np.max(subs)),
                                 member_std=float(np.std(subs))))
            print(f"{label:<22}{seg:<16} 均值={ann:+.4f}  单次区间=[{min(subs):+.4f},{max(subs):+.4f}] "
                  f"std={np.std(subs):.4f}")
    pd.DataFrame(avg_rows).to_csv(OUT / "sampling_average.csv", index=False)

    # ---- 可行 (N, P_max) 前沿: 资金约束是硬约束, 属可实施性参数而非信号参数 ----
    print("\n=== 资金可行前沿 (10 偏移均值, 每10交易日等权重置, 扣成本) ===")
    front = []
    for n_hold in (100, 150, 200, 300):
        p_max = CAPITAL / n_hold / 100.0
        row = {"n_hold": n_hold, "p_max": p_max}
        for tag, mode, uv in (("C", "C", False), ("Cv", "Cv", True)):
            runs = [run(mode, uv, off, n_hold)[0] for off in range(NOFF)]
            avg = pd.DataFrame({i: r for i, r in enumerate(runs)}).mean(axis=1)
            for seg, lo, hi in (("dev", START, SPLIT), ("oos", SPLIT, END)):
                s = avg[(avg.index >= lo) & (avg.index < hi)]
                row[f"{tag}_{seg}"] = perf(s)[0]
        front.append(row)
        print(f"  N={n_hold:>3}  P<={p_max:>5.1f}元  "
              f"开发: C={row['C_dev']:+.4f} Cv={row['Cv_dev']:+.4f} | "
              f"样本外: C={row['C_oos']:+.4f} Cv={row['Cv_oos']:+.4f}  "
              f"否决={row['Cv_oos'] - row['C_oos']:+.4f}")
    pd.DataFrame(front).to_csv(OUT / "capital_frontier.csv", index=False)

    # ---- 价格可行性统计 ----
    px = C.reindex(sel)
    print("\n=== 价格可行性 (50万 / N=150 -> P <= 33.3) ===")
    for p in (10, 16.7, 33.3, 50, 100):
        frac = float((px <= p).to_numpy().mean())
        print(f"  收盘价 <= {p:>5.1f} 元的样本占比: {frac:.3f}")
    print(f"  中位收盘价: {float(np.nanmedian(px.to_numpy())):.2f} 元")

    (OUT / "summary.json").write_text(json.dumps({
        "capital": CAPITAL, "n_hold": N_HOLD, "step": STEP, "cost_per_turn": COST,
        "results": df.to_dict(orient="records"),
    }, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
