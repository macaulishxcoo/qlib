#!/usr/bin/env python
"""毒尾否决 + 宽基等权 v2 —— 真实成本与整手约束下的重估。

协议: research/protocols/a_share_toxic_veto_broad_protocol_v2.md

v1 -> v2 唯一改动是成本实现 (不改任何信号参数):
  * 佣金 = max(5 元, 成交额 x 费率)
  * 100 股整手向下取整
  * 显式现金 (整手残差 + 卖出所得)
  * 真实 NAV = 持仓股数 x 开盘价 + 现金

主判据基准改为「同等可实施性的宽基 B0」= 同样 50 万/N=150/整手/最低佣金/系统抽样,
但不施加否决。alpha := 策略 - B0 ; beta := B0 - 中证1000。
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
from backtest_a_share_toxic_veto_broad_v1 import load_panel  # noqa: E402

OUT = Path(__file__).resolve().parents[1] / "output" / "analysis_static" / "a_share_toxic_veto_broad_v2"
OUT.mkdir(parents=True, exist_ok=True)

START, SPLIT, END = "2018-01-01", "2022-01-01", "2026-06-30"
CAPITAL = 500_000.0
N_HOLD = 150
N_GRID = (40, 60, 80, 120, 150)   # 持仓只数: 越少 -> 单笔越大 -> 整手现金拖累越小
VETO_Q = 0.90
STEP = 10
BUFFER = 2 * N_HOLD
MIN_COMMISSION = 5.0
LOT = 100
COSTS = {"base": (0.0005, 0.0015), "stress": (0.0010, 0.0030)}
ANN = 244.0
LIMIT_GAP = 0.095
MIN_PRICE = 2.0
N_OFFSETS = 10


def log(m):
    print(m, flush=True)


def main() -> int:
    O, C, V, A = load_panel()
    cols = [c for c in C.columns if c != "SH000852"]
    O, C, V, A = O[cols], C[cols], V[cols], A[cols]

    on1 = O / C.shift(1) - 1.0
    id1 = C / O - 1.0
    toxic = (id1.rolling(20, min_periods=10).sum().rank(axis=1, pct=True)
             + id1.rolling(20, min_periods=10).std().rank(axis=1, pct=True)
             + on1.rolling(20, min_periods=10).std().rank(axis=1, pct=True)) / 3.0
    veto = (toxic > VETO_Q).fillna(True)
    liq = A.rolling(20, min_periods=10).mean()

    gap = O / C.shift(1) - 1.0
    live = O.notna() & (V > 0) & (O >= MIN_PRICE)
    buy_ok = (live & (gap < LIMIT_GAP)).fillna(False)
    sell_ok = (live & (gap > -LIMIT_GAP)).fillna(False)

    price_ok = ((LOT * C) <= (CAPITAL / N_HOLD)).fillna(False)
    dates = O.index
    sel = dates[(dates >= START) & (dates <= END)]

    Op = O.reindex(sel).to_numpy(dtype="float64")
    Bok = buy_ok.reindex(sel).to_numpy()
    Sok = sell_ok.reindex(sel).to_numpy()
    POK = price_ok.reindex(sel).to_numpy()
    VETO = veto.reindex(sel).to_numpy()
    LQ = liq.reindex(sel).to_numpy(dtype="float64")
    n, m = Op.shape

    def systematic(mask_row, liq_row, n_target, offset):
        idx = np.where(mask_row)[0]
        if len(idx) <= n_target:
            return list(idx)
        order = idx[np.argsort(-np.nan_to_num(liq_row[idx], nan=-1e18))]
        k = len(order) / n_target
        picks = [order[min(int(i * k) + offset, len(order) - 1)] for i in range(n_target)]
        return list(dict.fromkeys(picks))

    def sticky_sample(elig, liq_row, prev_rep, n_target, offset=0):
        """桶粘性系统抽样。

        按流动性名次均分为 n_target 个"桶", 每桶出一只 -> 覆盖全流动性区间 (无大市值倾斜)。
        关键: 每个桶**优先保留上一期的代表**, 只有当它不再合格时才在同桶内换人。
        这样既保持无偏广度, 又把换手压到只由"进出合格集"驱动,
        而不是每期重抽 (v2 首版每期重抽 -> 年化换手 28 次 -> stress 下约 11%/年成本)。
        """
        idx = np.where(elig)[0]
        if len(idx) == 0:
            return [], {}
        order = idx[np.argsort(-np.nan_to_num(liq_row[idx], nan=-1e18))]
        k = max(1.0, len(order) / n_target)
        buckets: dict = {}
        for pos, c in enumerate(order):
            b = min(int(pos // k), n_target - 1)
            buckets.setdefault(b, []).append(c)
        new_rep: dict = {}
        for b in range(n_target):
            cands = buckets.get(b, [])
            if not cands:
                continue
            old = prev_rep.get(b)
            if old is not None and old in cands:
                new_rep[b] = old
            else:
                # offset 只影响"换人时挑谁", 用于多抽样稳健性检验
                new_rep[b] = cands[(len(cands) // 2 + offset) % len(cands)]
        return list(new_rep.values()), new_rep

    def run(use_veto, buy_rate, sell_rate, offset, n_hold):
        p_ok = ((LOT * C) <= (CAPITAL / n_hold)).fillna(False).reindex(sel).to_numpy()
        shares = np.zeros(m)
        cash = CAPITAL
        nav_open = np.full(n, np.nan)
        turn_amt = np.zeros(n)
        npos = np.zeros(n)
        inv_frac = np.zeros(n)
        prev_idx: list = []
        prev_rep: dict = {}
        for i in range(0, n - 1, STEP):
            j = i + 1
            # 以 open(j) 成交
            px = Op[j]
            nav_before = float(np.nansum(shares * px) + cash)
            elig = p_ok[i] & Bok[j] & (~VETO[i] if use_veto else True)
            if not elig.any():
                continue
            tgt, prev_rep = sticky_sample(elig, LQ[i], prev_rep, n_hold, offset)
            if not tgt:
                continue
            tgt = [c for c in tgt if np.isfinite(px[c]) and px[c] > 0]
            if not tgt:
                continue
            tgt_set = set(tgt)
            # 卖出不在目标中的持仓
            cost = 0.0
            for c in prev_idx:
                if c not in tgt_set and np.isfinite(px[c]) and shares[c] > 0 and Sok[j][c]:
                    notional = shares[c] * px[c]
                    fee = max(MIN_COMMISSION, notional * sell_rate)
                    cash += notional - fee
                    cost += fee
                    turn_amt[j] += notional / max(nav_before, 1.0)
                    shares[c] = 0
            prev_idx = [c for c in prev_idx if shares[c] > 0]
            # 目标等权市值, 按整手买入/调整
            per = nav_before / len(tgt) if len(tgt) else 0.0
            for c in tgt:
                want_lots = int(per // (LOT * px[c]))
                cur_lots = int(round(shares[c] / LOT))
                d = want_lots - cur_lots
                if d > 0:
                    notional = d * LOT * px[c]
                    fee = max(MIN_COMMISSION, notional * buy_rate)
                    if notional + fee <= cash:
                        cash -= notional + fee
                        cost += fee
                        turn_amt[j] += notional / max(nav_before, 1.0)
                        shares[c] += d * LOT
            prev_idx = tgt
            npos[j] = len(tgt)
            nav_open[j] = float(np.nansum(shares * px) + cash)
            for dd in range(j + 1, min(j + STEP, n)):
                nav_open[dd] = float(np.nansum(shares * Op[dd]) + cash)
                if nav_open[dd] > 0:
                    inv_frac[dd] = 1.0 - cash / nav_open[dd]
        s = pd.Series(nav_open, index=sel)
        s.iloc[0] = CAPITAL
        s = s.ffill()
        return (s.pct_change().dropna(), pd.Series(turn_amt, index=sel),
                pd.Series(npos, index=sel), pd.Series(inv_frac, index=sel))

    def perf(r):
        if len(r) < 50:
            return np.nan, np.nan, np.nan
        cum = (1 + r).cumprod()
        yrs = len(r) / ANN
        ann = float(cum.iloc[-1] ** (1 / yrs) - 1)
        vol = float(r.std() * np.sqrt(ANN))
        return ann, vol, float((cum / cum.cummax() - 1).min())

    idx_full = None
    Oall = O  # already main-board + index column removed; re-read index from store
    import qlib
    from qlib.config import REG_CN
    from qlib.data import D
    raw = D.features(["SH000852"], ["$open"], start_time=START, end_time=END, freq="day")
    idx_full = ((raw["$open"].shift(-1) / raw["$open"]) - 1.0).droplevel(0)
    idx_full.index = pd.DatetimeIndex(idx_full.index)

    rows, series = [], {}
    for n_hold in N_GRID:
      for cname, (br, sr) in COSTS.items():
        for tag, uv in (("策略", True), ("B0_宽基无否决", False)):
            runs, turns, poss, invs = [], [], [], []
            for off in range(N_OFFSETS):
                r, t, p, iv = run(uv, br, sr, off, n_hold)
                runs.append(r)
                turns.append(t.sum())
                poss.append(p[p > 0].mean())
                invs.append(iv[iv > 0].mean())
            avg = pd.DataFrame({i: r for i, r in enumerate(runs)}).mean(axis=1)
            series[f"{tag}|{cname}|N{n_hold}"] = avg
            for seg, lo, hi in (("开发2018-2021", START, SPLIT), ("样本外2022-2026", SPLIT, END)):
                s = avg[(avg.index >= lo) & (avg.index < hi)]
                a, v, dd = perf(s)
                rows.append(dict(portfolio=tag, cost=cname, n_hold=n_hold, segment=seg,
                                 ann=a, vol=v, mdd=dd,
                                 ann_turnover=float(np.mean(turns)) / (len(sel) / ANN),
                                 avg_positions=float(np.mean(poss)),
                                 invested_frac=float(np.mean(invs))))
    pf = pd.DataFrame(rows)
    pf.to_csv(OUT / "performance.csv", index=False)

    log("\n=== v2 真实成本 (10 偏移均值, 5元最低佣金 + 整手) ===")
    log(f"{'N':>4} {'组合':<14}{'成本':<7}{'分段':<15}{'年化':>9}{'波动':>8}{'回撤':>9}"
        f"{'换手':>7}{'仓位':>7}")
    for _, r in pf.iterrows():
        log(f"{int(r['n_hold']):>4} {r['portfolio']:<14}{r['cost']:<7}{r['segment']:<15}"
            f"{r['ann']:>+9.4f}{r['vol']:>8.4f}{r['mdd']:>+9.4f}"
            f"{r['ann_turnover']:>7.1f}{r['invested_frac']:>7.2f}")

    # 归因: alpha = 策略 - B0 ; beta = B0 - 中证1000
    att = []
    for n_hold in N_GRID:
      for cname in COSTS:
        for seg, lo, hi in (("开发2018-2021", START, SPLIT), ("样本外2022-2026", SPLIT, END)):
            def ann_of(s):
                s = s[(s.index >= lo) & (s.index < hi)]
                return float((1 + s).prod() ** (ANN / len(s)) - 1) if len(s) > 20 else np.nan
            a_s = ann_of(series[f"策略|{cname}|N{n_hold}"])
            a_b = ann_of(series[f"B0_宽基无否决|{cname}|N{n_hold}"])
            a_i = ann_of(idx_full)
            att.append(dict(n_hold=n_hold, cost=cname, segment=seg, strategy=a_s, B0_broad=a_b,
                            csi1000=a_i, alpha_vs_B0=a_s - a_b,
                            beta_B0_minus_csi1000=a_b - a_i, total_vs_csi1000=a_s - a_i))
    at = pd.DataFrame(att)
    at.to_csv(OUT / "attribution.csv", index=False)
    log("\n=== 归因 v2 ===")
    log(f"{'N':>4} {'成本':<7}{'分段':<15}{'策略':>9}{'B0宽基':>9}{'中证1000':>10}"
        f"{'alpha':>8}{'beta':>8}{'总超额':>9}")
    for _, r in at.iterrows():
        log(f"{int(r['n_hold']):>4} {r['cost']:<7}{r['segment']:<15}{r['strategy']:>+9.4f}"
            f"{r['B0_broad']:>+9.4f}{r['csi1000']:>+10.4f}{r['alpha_vs_B0']:>+8.4f}"
            f"{r['beta_B0_minus_csi1000']:>+8.4f}{r['total_vs_csi1000']:>+9.4f}")

    o = at[(at["cost"] == "stress") & (at["segment"] == "样本外2022-2026")
           & (at["n_hold"] == N_HOLD)].iloc[0]
    c1 = o["alpha_vs_B0"] > 0
    c2 = o["total_vs_csi1000"] >= 0.10
    c3 = o["total_vs_csi1000"] > 0
    verdict = "supported" if (c1 and c2 and c3) else ("partially_supported" if (c1 and c3) else "not_supported")
    decision = {"verdict": verdict,
                "checks": {"alpha_vs_B0>0": bool(c1), "总超额>=10pp": bool(c2), "总超额>0": bool(c3)},
                "oos_stress": {k: float(o[k]) for k in
                               ["strategy", "B0_broad", "csi1000", "alpha_vs_B0",
                                "beta_B0_minus_csi1000", "total_vs_csi1000"]},
                "note": "v2 成本含 5 元最低佣金与整手取整; 只降不升"}
    (OUT / "decision.json").write_text(json.dumps(decision, indent=2, ensure_ascii=False))
    (OUT / "methodology.json").write_text(json.dumps({
        "protocol": "research/protocols/a_share_toxic_veto_broad_protocol_v2.md",
        "capital": CAPITAL, "n_hold": N_HOLD, "veto_q": VETO_Q, "step": STEP,
        "min_commission": MIN_COMMISSION, "lot": LOT, "costs": COSTS,
        "n_offsets": N_OFFSETS, "split": {"dev": [START, SPLIT], "oos": [SPLIT, END]},
    }, indent=2, ensure_ascii=False))

    log(f"\n=== VERDICT: {verdict.upper()} ===")
    log(json.dumps(decision, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
