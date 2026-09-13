#!/usr/bin/env python
"""可实施性成本侧研究 v3。

协议: research/protocols/a_share_cost_frontier_protocol_v3.md

只调实现参数 (N, STEP, 佣金口径), 不动任何信号参数 (否决定义/阈值沿用 v1/v2)。
引擎与 v2 相同 (整手 + 显式现金 + 真实 NAV), 增加 STEP 与成本阶梯两个维度。
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
from backtest_a_share_toxic_veto_broad_v1 import load_panel  # noqa: E402

OUT = Path(__file__).resolve().parents[1] / "output" / "analysis_static" / "cost_frontier_v3"
OUT.mkdir(parents=True, exist_ok=True)

START, SPLIT, END = "2018-01-01", "2022-01-01", "2026-06-30"
CAPITAL = 500_000.0
VETO_Q = 0.90
LOT = 100
ANN = 244.0
LIMIT_GAP = 0.095
MIN_PRICE = 2.0
N_OFFSETS = 5

N_GRID = (30, 40, 60, 100, 150)
STEP_GRID = (10, 20)
# (buy_rate, sell_rate, min_commission)
COST_SCENARIOS = {
    "stress": (0.0010, 0.0030, 5.0),
    "base": (0.0005, 0.0015, 5.0),
    "base_nofloor": (0.0005, 0.0015, 0.0),
    "retail_best": (0.00015, 0.00065, 0.0),
}


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

    dates = O.index
    sel = dates[(dates >= START) & (dates <= END)]
    Op = O.reindex(sel).to_numpy(dtype="float64")
    Bok = buy_ok.reindex(sel).to_numpy()
    Sok = sell_ok.reindex(sel).to_numpy()
    VETO = veto.reindex(sel).to_numpy()
    LQ = liq.reindex(sel).to_numpy(dtype="float64")
    n, m = Op.shape

    import qlib
    from qlib.config import REG_CN
    from qlib.data import D
    raw = D.features(["SH000852"], ["$open"], start_time=START, end_time=END, freq="day")
    idx_ret = ((raw["$open"].shift(-1) / raw["$open"]) - 1.0).droplevel(0)
    idx_ret.index = pd.DatetimeIndex(idx_ret.index)

    def sticky_sample(elig, liq_row, prev_rep, n_target, offset):
        idx = np.where(elig)[0]
        if len(idx) == 0:
            return [], {}
        order = idx[np.argsort(-np.nan_to_num(liq_row[idx], nan=-1e18))]
        k = max(1.0, len(order) / n_target)
        buckets: dict = {}
        for pos, c in enumerate(order):
            buckets.setdefault(min(int(pos // k), n_target - 1), []).append(c)
        new_rep: dict = {}
        for b in range(n_target):
            cands = buckets.get(b, [])
            if not cands:
                continue
            old = prev_rep.get(b)
            new_rep[b] = old if (old is not None and old in cands) else \
                cands[(len(cands) // 2 + offset) % len(cands)]
        return list(new_rep.values()), new_rep

    def run(use_veto, step, n_hold, buy_rate, sell_rate, min_comm, offset):
        p_ok = ((LOT * C) <= (CAPITAL / n_hold)).fillna(False).reindex(sel).to_numpy()
        shares = np.zeros(m)
        cash = CAPITAL
        nav = np.full(n, np.nan)
        turn = np.zeros(n)
        inv = np.zeros(n)
        prev_rep: dict = {}
        for i in range(0, n - 1, step):
            j = i + 1
            px = Op[j]
            nav_before = float(np.nansum(shares * px) + cash)
            elig = p_ok[i] & Bok[j] & (~VETO[i] if use_veto else True)
            if not elig.any():
                continue
            tgt, prev_rep = sticky_sample(elig, LQ[i], prev_rep, n_hold, offset)
            tgt = [c for c in tgt if np.isfinite(px[c]) and px[c] > 0]
            if not tgt:
                continue
            tset = set(tgt)
            held_idx = np.where(shares > 0)[0]
            for c in held_idx:
                if c not in tset and np.isfinite(px[c]) and Sok[j][c]:
                    notional = shares[c] * px[c]
                    fee = max(min_comm, notional * sell_rate)
                    cash += notional - fee
                    turn[j] += notional / max(nav_before, 1.0)
                    shares[c] = 0.0
            per = nav_before / len(tgt)
            for c in tgt:
                want = int(per // (LOT * px[c]))
                cur = int(round(shares[c] / LOT))
                d = want - cur
                if d > 0:
                    notional = d * LOT * px[c]
                    fee = max(min_comm, notional * buy_rate)
                    if notional + fee <= cash:
                        cash -= notional + fee
                        turn[j] += notional / max(nav_before, 1.0)
                        shares[c] += d * LOT
            nav[j] = float(np.nansum(shares * px) + cash)
            for dd in range(j + 1, min(j + step, n)):
                nav[dd] = float(np.nansum(shares * Op[dd]) + cash)
                if nav[dd] > 0:
                    inv[dd] = 1.0 - cash / nav[dd]
        s = pd.Series(nav, index=sel)
        s.iloc[0] = CAPITAL
        return s.ffill().pct_change().dropna(), pd.Series(turn, index=sel), pd.Series(inv, index=sel)

    def ann_of(s):
        s = s.dropna()
        if len(s) < 20:
            return np.nan
        return float((1 + s).prod() ** (ANN / len(s)) - 1)

    rows = []
    for n_hold in N_GRID:
        p_max = CAPITAL / n_hold / LOT
        for step in STEP_GRID:
            for cname, (br, sr, mc) in COST_SCENARIOS.items():
                res = {}
                for tag, uv in (("strategy", True), ("B0", False)):
                    runs, turns, invs = [], [], []
                    for off in range(N_OFFSETS):
                        r, t, iv = run(uv, step, n_hold, br, sr, mc, off)
                        runs.append(r)
                        turns.append(t.sum())
                        invs.append(iv[iv > 0].mean())
                    avg = pd.DataFrame({i: r for i, r in enumerate(runs)}).mean(axis=1)
                    for seg, lo, hi in (("dev", START, SPLIT), ("oos", SPLIT, END)):
                        ss = avg[(avg.index >= lo) & (avg.index < hi)]
                        res[f"{tag}_{seg}"] = ann_of(ss)
                    res[f"{tag}_turnover"] = float(np.mean(turns)) / (len(sel) / ANN)
                    res[f"{tag}_inv"] = float(np.mean(invs))
                for seg, lo, hi in (("dev", START, SPLIT), ("oos", SPLIT, END)):
                    res[f"csi1000_{seg}"] = ann_of(idx_ret[(idx_ret.index >= lo) & (idx_ret.index < hi)])
                rows.append(dict(n_hold=n_hold, p_max=p_max, step=step, cost=cname, **res))
    df = pd.DataFrame(rows)
    df.to_csv(OUT / "cost_frontier.csv", index=False)

    log("\n=== 成本前沿 (样本外 2022-2026, 10/5 偏移均值) ===")
    log(f"{'N':>4}{'Pmax':>6}{'STEP':>5}{'成本':<14}{'策略':>9}{'B0':>9}{'中证1000':>9}"
        f"{'超额':>9}{'换手':>7}{'仓位':>7}")
    for _, r in df.iterrows():
        log(f"{int(r['n_hold']):>4}{r['p_max']:>6.1f}{int(r['step']):>5}{r['cost']:<14}"
            f"{r['strategy_oos']:>+9.4f}{r['B0_oos']:>+9.4f}{r['csi1000_oos']:>+9.4f}"
            f"{r['strategy_oos'] - r['csi1000_oos']:>+9.4f}"
            f"{r['strategy_turnover']:>7.1f}{r['strategy_inv']:>7.2f}")

    best = df.loc[df["strategy_oos"].idxmax()]
    base = df[df["cost"] == "base"]
    bb = base.loc[base["strategy_oos"].idxmax()]
    log("\n=== 结论 ===")
    log(f"全网格最优(样本外): N={int(best['n_hold'])} STEP={int(best['step'])} "
        f"成本={best['cost']} -> 策略 {best['strategy_oos']:+.4f}, "
        f"超额 {best['strategy_oos'] - best['csi1000_oos']:+.4f}")
    log(f"仅 base 成本最优: N={int(bb['n_hold'])} STEP={int(bb['step'])} -> "
        f"策略 {bb['strategy_oos']:+.4f}, 超额 {bb['strategy_oos'] - bb['csi1000_oos']:+.4f}")

    # 成本阶梯对比 (固定最优 N/STEP)
    log("\n=== 成本阶梯对比 (最优 base 配置, 样本外) ===")
    for cname in COST_SCENARIOS:
        r = df[(df["n_hold"] == bb["n_hold"]) & (df["step"] == bb["step"])
               & (df["cost"] == cname)].iloc[0]
        log(f"  {cname:<14} 策略={r['strategy_oos']:+.4f} 超额={r['strategy_oos'] - r['csi1000_oos']:+.4f}")

    ex_best = float(best["strategy_oos"] - best["csi1000_oos"])
    ex_base = float(bb["strategy_oos"] - bb["csi1000_oos"])
    verdict = ("cost_frontier_found" if ex_best >= 0.10
               else "cost_improved_only" if ex_base > 0 else "no_feasible_config")
    decision = {
        "verdict": verdict,
        "best_any_cost": {"n_hold": int(best["n_hold"]), "step": int(best["step"]),
                          "cost": best["cost"], "strategy_oos": float(best["strategy_oos"]),
                          "excess_vs_csi1000": ex_best},
        "best_base_cost": {"n_hold": int(bb["n_hold"]), "step": int(bb["step"]),
                           "strategy_oos": float(bb["strategy_oos"]),
                           "excess_vs_csi1000": ex_base},
        "csi1000_oos": float(df["csi1000_oos"].iloc[0]),
        "csi1000_dev": float(df["csi1000_dev"].iloc[0]),
    }
    (OUT / "decision.json").write_text(json.dumps(decision, indent=2, ensure_ascii=False))
    (OUT / "methodology.json").write_text(json.dumps({
        "protocol": "research/protocols/a_share_cost_frontier_protocol_v3.md",
        "capital": CAPITAL, "veto_q": VETO_Q, "lot": LOT,
        "n_grid": list(N_GRID), "step_grid": list(STEP_GRID),
        "cost_scenarios": {k: list(v) for k, v in COST_SCENARIOS.items()},
        "n_offsets": N_OFFSETS, "split": {"dev": [START, SPLIT], "oos": [SPLIT, END]},
    }, indent=2, ensure_ascii=False))
    log(f"\n=== VERDICT: {verdict} ===")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
