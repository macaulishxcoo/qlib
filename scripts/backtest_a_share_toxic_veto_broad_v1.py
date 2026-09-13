#!/usr/bin/env python
"""毒尾否决 + 宽基等权 日频组合 v1。

协议: research/protocols/a_share_toxic_veto_broad_protocol_v1.md

冻结要点:
  * 池      SH6xx + SZ 000/001/002/003
  * 毒尾分  toxic = mean[pct_rank(id_mom_20), pct_rank(id_vol_20), pct_rank(on_vol_20)]
  * 否决    toxic > 0.90 (剔除最高 10%)
  * 资金    50 万, N=150, 100 股整手 -> 100*close <= 500000/150
  * 调仓    每 10 交易日 (主) / 5 交易日 (次), 缓冲带: 未入否决区则保留
  * 执行    t 收盘信号 -> t+1 开盘成交; 涨停不买, 跌停不卖(强制保留)
  * 成本    base 0.05/0.15 ; stress 0.10/0.30
  * 判定    开发 2018-2021 / 样本外 2022-2026-06, 只看样本外
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd

STORE = Path.home() / ".qlib" / "qlib_data" / "cn_data_2026"
OUT = Path(__file__).resolve().parents[1] / "output" / "analysis_static" / "a_share_toxic_veto_broad_v1"
OUT.mkdir(parents=True, exist_ok=True)

LOAD_START = "2016-06-01"
START, SPLIT, END = "2018-01-01", "2022-01-01", "2026-06-30"
CAPITAL = 500_000.0
N_HOLD = 150
VETO_Q = 0.90
LIQ_WIN = 20
STEPS = (10, 5)
COSTS = {"base": (0.0005, 0.0015), "stress": (0.0010, 0.0030)}
ANN = 244.0
LIMIT_GAP = 0.095
MIN_PRICE = 2.0


def log(m):
    print(m, flush=True)


def load_panel():
    import qlib
    from qlib.config import REG_CN
    from qlib.data import D
    qlib.init(provider_uri=str(STORE), region=REG_CN)
    df = D.features(D.instruments(market="all"),
                    ["$open", "$close", "$volume", "$amount"],
                    start_time=LOAD_START, end_time=END, freq="day")
    df.columns = ["open", "close", "volume", "amount"]
    df = df[~df.index.duplicated()]
    codes = df.index.get_level_values(0)
    # 主板池 + 保留中证1000 作为基准列 (指数不得进入选股池)
    df = df[codes.str.startswith("SH6") | codes.str.startswith("SZ00")
            | (codes == "SH000852")]
    cols = {}
    for c in ["open", "close", "volume", "amount"]:
        m = df[c].unstack(0).sort_index()
        cols[c] = m.where(m > 0) if c != "amount" else m
    idx = df["close"].unstack(0).sort_index().index
    log(f"main-board rows={len(df):,} insts={df.index.get_level_values(0).nunique():,}")
    return (cols["open"].astype("float32"), cols["close"].astype("float32"),
            cols["volume"].astype("float32"), cols["amount"].astype("float32"))


def main() -> int:
    log("-> loading")
    O, C, V, A = load_panel()

    on1 = O / C.shift(1) - 1.0
    id1 = C / O - 1.0
    id_mom = id1.rolling(20, min_periods=10).sum()
    id_vol = id1.rolling(20, min_periods=10).std()
    on_vol = on1.rolling(20, min_periods=10).std()
    liq = A.rolling(LIQ_WIN, min_periods=10).mean()

    toxic = (id_mom.rank(axis=1, pct=True)
             + id_vol.rank(axis=1, pct=True)
             + on_vol.rank(axis=1, pct=True)) / 3.0
    veto = toxic > VETO_Q

    gap = O / C.shift(1) - 1.0
    live = O.notna() & (V > 0) & (O >= MIN_PRICE)
    buy_ok = live & (gap < LIMIT_GAP)
    sell_ok = live & (gap > -LIMIT_GAP)

    price_ok = (100.0 * C) <= (CAPITAL / N_HOLD)
    STOCK_COLS = [c for c in C.columns if c != "SH000852"]     # 指数不得入池
    eligible = ((~veto) & price_ok & C.notna())[STOCK_COLS]

    open_ret = (O.shift(-1) / O) - 1.0
    univ = open_ret[eligible.columns].where(buy_ok.shift(-1)[eligible.columns]).mean(axis=1, skipna=True)
    ew_all = open_ret[eligible.columns].mean(axis=1, skipna=True)

    idx_ret = None
    if "SH000852" in O.columns:
        idx_ret = ((O["SH000852"].shift(-1) / O["SH000852"]) - 1.0)

    dates = O.index
    sel = dates[(dates >= START) & (dates <= END)]

    def run(step, buy_rate, sell_rate, use_veto):
        elig = eligible if use_veto else (price_ok & C.notna())
        e = elig.reindex(sel).fillna(False)
        b_ok = buy_ok.reindex(sel).fillna(False)
        s_ok = sell_ok.reindex(sel).fillna(False)
        lq = liq.reindex(sel)
        ret = open_ret.reindex(sel)
        n = len(sel)
        held: list = []
        gross = np.full(n, np.nan)
        cost = np.zeros(n)
        turn = np.zeros(n)
        sides = np.zeros(n)
        w_prev = None
        for i in range(0, n - 1, step):
            j = i + 1
            if j >= n:
                break
            cand = e.iloc[i] & b_ok.iloc[j]
            names_all = list(cand.index[cand])
            lqi = lq.iloc[i].reindex(names_all).sort_values(ascending=False)
            top_n = list(lqi.index[:N_HOLD])
            # 缓冲带必须**有界**: 只有仍在前 2N 名内的旧持仓才保留,
            # 否则组合会无限累积 (首版即因此膨胀到 635~875 只、换手仅 1.3)
            band = set(lqi.index[:2 * N_HOLD])
            keep = [c for c in held if (c in band) and bool(e.iloc[i].get(c, False))]
            tgt = list(dict.fromkeys(keep + top_n))
            unsell = set(s_ok.iloc[j].index[~s_ok.iloc[j]])
            tgt += [c for c in held if c in unsell]
            tgt = list(dict.fromkeys(tgt))
            if not tgt:
                continue
            w_new = pd.Series(1.0 / len(tgt), index=tgt)
            if w_prev is None:
                buys, sells, t = 1.0, 0.0, 1.0
            else:
                allc = w_new.index.union(w_prev.index)
                d = w_new.reindex(allc).fillna(0.0) - w_prev.reindex(allc).fillna(0.0)
                buys, sells = float(d[d > 0].sum()), float(-d[d < 0].sum())
                t = (buys + sells) / 2.0
            cost[j] = buys * buy_rate + sells * sell_rate
            turn[j] = t
            sides[j] = len(tgt)
            end = min(j + step, n)
            for dd in range(j, end):
                r = ret.iloc[dd].reindex(tgt)
                if r.notna().sum() > 0:
                    gross[dd] = float(r.mean(skipna=True))
            held = tgt
            w_prev = w_new
        g = pd.Series(gross, index=sel)
        net = (g - pd.Series(cost, index=sel)).where(g.notna())
        return net.dropna(), pd.Series(turn, index=sel), pd.Series(sides, index=sel)

    def perf(r, label):
        cum = (1 + r).cumprod()
        yrs = len(r) / ANN
        ann = float(cum.iloc[-1] ** (1 / yrs) - 1)
        vol = float(r.std() * np.sqrt(ANN))
        mdd = float((cum / cum.cummax() - 1).min())
        return dict(label=label, n_days=len(r), ann=ann, vol=vol, mdd=mdd,
                    sharpe=ann / vol if vol else np.nan)

    rows, ser = [], {}
    for step in STEPS:
        for cname, (br, sr) in COSTS.items():
            for use_veto, tag in ((True, "策略"), (False, "底仓-无否决")):
                r, tn, sd = run(step, br, sr, use_veto)
                rows.append({**perf(r, f"{tag}|step{step}|{cname}"), "kind": tag,
                             "step": step, "cost": cname,
                             "ann_turnover": float(tn.sum()) / (len(sel) / ANN),
                             "avg_names": float(sd[sd > 0].mean())})
                ser[f"{tag}|{step}|{cname}"] = r
    pf = pd.DataFrame(rows)
    pf.to_csv(OUT / "performance.csv", index=False)

    idx = idx_ret.reindex(sel)
    bm_ew = ew_all.reindex(sel)
    for nm, s in (("中证1000", idx), ("等权全池", bm_ew)):
        cum = (1 + s.dropna()).cumprod()
        yrs = len(s.dropna()) / ANN
        log(f"基准 {nm}: 年化 {cum.iloc[-1] ** (1 / yrs) - 1:+.4f}")

    log("\n=== 绩效 (step=10, base/stress) ===")
    log(f"{'组合':<18}{'成本':<8}{'年化':>9}{'波动':>8}{'回撤':>9}{'换手':>7}{'只数':>6}")
    for _, r in pf[pf["step"] == 10].iterrows():
        log(f"{r['label']:<18}{'':<8}{r['ann']:>+9.4f}{r['vol']:>8.4f}{r['mdd']:>+9.4f}"
            f"{r['ann_turnover']:>7.1f}{r['avg_names']:>6.0f}")

    # ---------------- 分段 + 归因 ----------------
    attrib = []
    for step in STEPS:
        for cname in COSTS:
            strat = ser[f"策略|{step}|{cname}"]
            base = ser[f"底仓-无否决|{step}|{cname}"]
            for seg, lo, hi in (("开发2018-2021", START, SPLIT), ("样本外2022-2026", SPLIT, END)):
                ss = strat[(strat.index >= lo) & (strat.index < hi)]
                bb = base[(base.index >= lo) & (base.index < hi)]
                ii = idx[(idx.index >= lo) & (idx.index < hi)].dropna()
                ee = bm_ew[(bm_ew.index >= lo) & (bm_ew.index < hi)].dropna()
                f = lambda x: float((1 + x).prod() ** (ANN / len(x)) - 1) if len(x) > 20 else np.nan
                a_s, a_b, a_i, a_e = f(ss), f(bb), f(ii), f(ee)
                attrib.append({
                    "step": step, "cost": cname, "segment": seg,
                    "strategy_ann": a_s, "base_ann": a_b, "csi1000_ann": a_i, "ew_ann": a_e,
                    "total_excess_vs_csi1000": a_s - a_i,
                    "small_cap_premium": a_b - a_i,
                    "veto_contribution": a_s - a_b,
                    "liquidity_selection": a_b - a_e,
                })
    at = pd.DataFrame(attrib)
    at.to_csv(OUT / "attribution.csv", index=False)

    log("\n=== 归因 (step=10) ===")
    log(f"{'分段':<18}{'成本':<8}{'策略':>9}{'底仓':>9}{'中证1000':>10}"
        f"{'总超额':>9}{'小市值':>9}{'否决':>9}{'选样':>9}")
    for _, r in at[at["step"] == 10].iterrows():
        log(f"{r['segment']:<18}{r['cost']:<8}{r['strategy_ann']:>+9.4f}{r['base_ann']:>+9.4f}"
            f"{r['csi1000_ann']:>+10.4f}{r['total_excess_vs_csi1000']:>+9.4f}"
            f"{r['small_cap_premium']:>+9.4f}{r['veto_contribution']:>+9.4f}"
            f"{r['liquidity_selection']:>+9.4f}")

    # ---------------- 判定 ----------------
    oos = at[(at["step"] == 10) & (at["cost"] == "stress") & (at["segment"] == "样本外2022-2026")].iloc[0]
    oos_b = at[(at["step"] == 10) & (at["cost"] == "base") & (at["segment"] == "样本外2022-2026")].iloc[0]
    dev = at[(at["step"] == 10) & (at["cost"] == "stress") & (at["segment"] == "开发2018-2021")].iloc[0]
    c1 = oos["total_excess_vs_csi1000"] >= 0.10
    c2 = oos["total_excess_vs_csi1000"] > 0
    c3 = (oos["veto_contribution"] > 0) and (dev["veto_contribution"] > 0)
    c4 = oos_b["total_excess_vs_csi1000"] > 0
    verdict = ("supported" if (c1 and c2 and c3 and c4)
               else "partially_supported" if (c2 and c3 and c4) else "not_supported")
    decision = {
        "verdict": verdict,
        "checks": {"C1_样本外净超额>=10pp": bool(c1), "C2_样本外净超额>0": bool(c2),
                   "C3_否决两段同号为正": bool(c3), "C4_base成本下>0": bool(c4)},
        "oos_stress_excess_vs_csi1000": float(oos["total_excess_vs_csi1000"]),
        "oos_stress_excess_vs_ew": float(oos["strategy_ann"] - oos["ew_ann"]),
        "oos_stress_veto_contribution": float(oos["veto_contribution"]),
        "oos_stress_small_cap_premium": float(oos["small_cap_premium"]),
        "oos_stress_strategy_ann": float(oos["strategy_ann"]),
        "dev_stress_veto_contribution": float(dev["veto_contribution"]),
    }
    (OUT / "decision.json").write_text(json.dumps(decision, indent=2, ensure_ascii=False))
    (OUT / "methodology.json").write_text(json.dumps({
        "protocol": "research/protocols/a_share_toxic_veto_broad_protocol_v1.md",
        "capital": CAPITAL, "n_hold": N_HOLD, "veto_q": VETO_Q, "liq_win": LIQ_WIN,
        "steps": list(STEPS), "costs": COSTS,
        "split": {"dev": [START, SPLIT], "oos": [SPLIT, END]},
    }, indent=2, ensure_ascii=False))

    log(f"\n=== VERDICT: {verdict.upper()} ===")
    log(json.dumps(decision, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
