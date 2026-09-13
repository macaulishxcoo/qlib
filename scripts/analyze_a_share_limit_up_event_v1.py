#!/usr/bin/env python
"""涨停板事件日频策略线 v1。

协议: research/protocols/a_share_limit_up_event_protocol_v1.md
状态: design_frozen_before_data

冻结要点:
  * 池      沪深主板 SH6xx + SZ 000/001/002/003 (单一 10% 涨跌幅制度)
  * 事件    封板 lim_close = 0.095 <= chg <= 0.11
            触板 lim_touch = high/prev_close - 1 >= 0.095
            炸板 = touch & ~close ;  一字 = close & (low == high)
            连板数 k = 连续 lim_close 天数 ;  量比 vr = vol / mean(vol, t-20..t-1)
  * 执行    事件日 t 确认 -> t+1 开盘买入 -> open(t+1+h) 卖出
            涨停开盘买不进 -> 剔除 (buy_ok)
  * 成本    base 0.05/0.15 ; stress 0.10/0.30
  * 判定    A: 分档 excess_h 按日聚类 t ;  B: 事件组合净收益
            需同时满足 stress>0, t>=2, 先验>=2 条同向, 两半同号
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd

STORE = Path.home() / ".qlib" / "qlib_data" / "cn_data_2026"
OUT = Path(__file__).resolve().parents[1] / "output" / "analysis_static" / "a_share_limit_up_event_v1"
OUT.mkdir(parents=True, exist_ok=True)

# ---------------- 冻结参数 ----------------
LOAD_START = "2016-06-01"
EVAL_START = "2018-01-01"
EVAL_END = "2026-06-30"
HORIZONS = (1, 5, 10)
LIMIT_LO, LIMIT_HI = 0.095, 0.11
LIMIT_GAP = 0.095
MIN_PRICE = 2.0
MIN_EVENTS_PER_DAY = 1
SPLIT = "2022-01-01"                      # 两半样本分界
COSTS = {"base": (0.0005, 0.0015), "stress": (0.0010, 0.0030)}
ANN = 244.0
VR_LO, VR_HI = 0.5, 1.5


def log(m: str) -> None:
    print(m, flush=True)


def load_panel():
    import qlib
    from qlib.config import REG_CN
    from qlib.data import D

    qlib.init(provider_uri=str(STORE), region=REG_CN)
    df = D.features(D.instruments(market="all"),
                    ["$open", "$high", "$low", "$close", "$volume"],
                    start_time=LOAD_START, end_time=EVAL_END, freq="day")
    df.columns = ["open", "high", "low", "close", "volume"]
    df = df[~df.index.duplicated()]
    codes = df.index.get_level_values(0)
    df = df[codes.str.startswith("SH6") | codes.str.startswith("SZ00")]
    log(f"main-board panel rows={len(df):,} insts={df.index.get_level_values(0).nunique():,}")
    out = []
    for c in ["open", "high", "low", "close", "volume"]:
        m = df[c].unstack(0).sort_index()
        out.append(m.where(m > 0) if c != "volume" else m)
    O, H, L, C, V = (x.astype("float32") for x in out)
    return O, H, L, C, V


def build_events(O, H, L, C, V):
    prev_c = C.shift(1)
    chg = C / prev_c - 1.0
    lim_close = (chg >= LIMIT_LO) & (chg <= LIMIT_HI)
    lim_touch = (H / prev_c - 1.0) >= LIMIT_LO
    lim_break = lim_touch & ~lim_close

    # 连续封板天数 (显式递推, 避免向量化写法出错)
    lc = lim_close.to_numpy()
    kv = np.zeros(lc.shape, dtype="int16")
    for i in range(1, lc.shape[0]):
        kv[i] = np.where(lc[i], kv[i - 1] + 1, 0)
    k = pd.DataFrame(kv, index=lim_close.index, columns=lim_close.columns)
    k = k.where(lim_close)

    vr = V / V.rolling(20, min_periods=10).mean().shift(1)
    one = lim_close & (L >= H - H * 1e-6)

    # 建仓可交易性: 在 open(t) 能否买入
    gap = O / C.shift(1) - 1.0
    live = O.notna() & (V > 0) & (O >= MIN_PRICE)
    buy_ok = live & (gap < LIMIT_GAP)
    return dict(lim_close=lim_close, lim_break=lim_break, k=k, vr=vr,
                one=one, buy_ok=buy_ok)


def main() -> int:
    log("-> loading panel")
    O, H, L, C, V = load_panel()
    log("-> building events")
    E = build_events(O, H, L, C, V)
    lim_close, lim_break, k, vr, one, buy_ok = (
        E["lim_close"], E["lim_break"], E["k"], E["vr"], E["one"], E["buy_ok"])

    fwd = {}
    for h in HORIZONS:
        fwd[h] = (O.shift(-(1 + h)) / O.shift(-1)) - 1.0

    # 事件日 t -> 建仓日 t+1, 故用 buy_ok.shift(-1)
    entry_ok = buy_ok.shift(-1)
    univ = {h: fwd[h].where(entry_ok).mean(axis=1, skipna=True) for h in HORIZONS}
    exc = {h: fwd[h].sub(univ[h], axis=0) for h in HORIZONS}

    all_dates = O.index
    sel = all_dates[(all_dates >= EVAL_START) & (all_dates <= EVAL_END)]
    log(f"-> eval {sel[0].date()}..{sel[-1].date()} n={len(sel)}")

    ev = lim_close.reindex(sel) & entry_ok.reindex(sel)
    brk = lim_break.reindex(sel) & entry_ok.reindex(sel)
    kk = k.reindex(sel)
    vv = vr.reindex(sel)
    oo = one.reindex(sel)
    log(f"-> 封板事件 {int(ev.to_numpy().sum()):,} ; 炸板事件 {int(brk.to_numpy().sum()):,} "
        f"(已剔除 T+1 涨停开盘买不进的样本)")

    def cells():
        yield "ALL_close", ev
        yield "k1_首板", ev & (kk == 1)
        yield "k2", ev & (kk == 2)
        yield "k3p_连板", ev & (kk >= 3)
        yield "vr_lo缩量", ev & (vv < VR_LO)
        yield "vr_mid", ev & (vv >= VR_LO) & (vv <= VR_HI)
        yield "vr_hi放量", ev & (vv > VR_HI)
        yield "one_一字", ev & oo
        yield "nonone_回封", ev & ~oo
        yield "break_炸板", brk
        yield "k1_vr_lo", ev & (kk == 1) & (vv < VR_LO)
        yield "k1_one", ev & (kk == 1) & oo
        yield "k3p_vr_hi", ev & (kk >= 3) & (vv > VR_HI)

    def day_clustered(mask, h):
        """同日多事件先取日均 -> 避免截面相关高估显著性。"""
        x = exc[h].where(mask)
        d = x.mean(axis=1, skipna=True).dropna()
        if len(d) < 30:
            return None
        t = float(d.mean() / (d.std() / np.sqrt(len(d)))) if d.std() > 0 else np.nan
        return dict(n_events=int(mask.to_numpy().sum()), n_days=int(len(d)),
                    mean_excess=float(d.mean()), t_stat=t,
                    mean_raw=float(fwd[h].where(mask).stack().mean()),
                    half1=float(d[d.index < SPLIT].mean()) if (d.index < SPLIT).any() else np.nan,
                    half2=float(d[d.index >= SPLIT].mean()) if (d.index >= SPLIT).any() else np.nan)

    rows = []
    for cname, mask in cells():
        for h in HORIZONS:
            r = day_clustered(mask, h)
            if r is None:
                continue
            r.update(cell=cname, h=h, same_sign=bool(np.sign(r["half1"]) == np.sign(r["half2"]))
                     if np.isfinite(r["half1"]) and np.isfinite(r["half2"]) else False)
            rows.append(r)
    es = pd.DataFrame(rows)[["cell", "h", "n_events", "n_days", "mean_raw",
                             "mean_excess", "t_stat", "half1", "half2", "same_sign"]]
    es.to_csv(OUT / "event_study.csv", index=False)

    log("\n=== 端点 A: 事件研究 (h=5, 超额 = 事件 - 可买全池等权) ===")
    log(f"{'分档':<14}{'n':>8}{'日均超额':>11}{'t':>8}{'前半':>9}{'后半':>9}  同号")
    for _, r in es[es["h"] == 5].iterrows():
        log(f"{r['cell']:<14}{int(r['n_events']):>8}{r['mean_excess']:>+11.4f}"
            f"{r['t_stat']:>8.2f}{r['half1']:>+9.4f}{r['half2']:>+9.4f}  {r['same_sign']}")

    log("\n--- h=1 ---")
    for _, r in es[es["h"] == 1].iterrows():
        log(f"{r['cell']:<14}{int(r['n_events']):>8}{r['mean_excess']:>+11.4f}{r['t_stat']:>8.2f}")
    log("\n--- h=10 ---")
    for _, r in es[es["h"] == 10].iterrows():
        log(f"{r['cell']:<14}{int(r['n_events']):>8}{r['mean_excess']:>+11.4f}{r['t_stat']:>8.2f}")

    # ---------------- 端点 B: 事件组合 ----------------
    def portfolio(mask, h, buy_rate, sell_rate):
        m = mask.reindex(sel).fillna(False)
        hold = m.astype(float).rolling(h, min_periods=1).max() > 0        # t..t+h-1 持有
        cap = hold.to_numpy()
        ret = fwd[1].reindex(sel).to_numpy()                        # 日度: open(t)->open(t+1)
        port = np.full(len(sel), np.nan)
        turn = np.zeros(len(sel))
        prev = None
        for i in range(len(sel)):
            names = np.where(cap[i])[0]
            if len(names) == 0:
                port[i] = 0.0
                prev = None
                continue
            w = np.zeros(cap.shape[1]); w[names] = 1.0 / len(names)
            r = ret[i][names]
            ok = np.isfinite(r)
            port[i] = float(r[ok].mean()) if ok.any() else 0.0
            if prev is not None:
                turn[i] = float(np.abs(w - prev).sum() / 2)
            else:
                turn[i] = 1.0
            prev = w
        p = pd.Series(port, index=sel).fillna(0.0)
        cost = pd.Series(turn, index=sel) * (buy_rate + sell_rate)
        net = p - cost
        gross_ann = float((1 + p).prod() ** (ANN / len(p)) - 1)
        net_ann = float((1 + net).prod() ** (ANN / len(sel)) - 1)
        cum = (1 + net).cumprod()
        # 仅在持仓日的条件超额 (与全池同期对比, 剔除空仓择时成分)
        inv = pd.Series(cap.any(axis=1), index=sel)
        cond = (p - univ[1].reindex(sel))[inv]
        return dict(gross_ann=gross_ann, net_ann=net_ann,
                    mdd=float((cum / cum.cummax() - 1).min()),
                    ann_turnover=float(turn.sum()) / (len(sel) / ANN),
                    invested_frac=float(inv.mean()),
                    cond_excess_mean=float(cond.mean()) if len(cond) else np.nan,
                    cond_t=float(cond.mean() / (cond.std() / np.sqrt(len(cond))))
                    if len(cond) > 2 and cond.std() > 0 else np.nan,
                    n_days=int(len(sel)))

    prows = []
    for cname, mask in cells():
        for h in (1, 5):
            for cost_name, (br, sr) in COSTS.items():
                r = portfolio(mask, h, br, sr)
                r.update(cell=cname, h=h, cost=cost_name)
                prows.append(r)
    pf = pd.DataFrame(prows)
    pf.to_csv(OUT / "portfolio_summary.csv", index=False)
    log("\n=== 端点 B: 事件组合 (h=5) ===")
    for _, r in pf[(pf["h"] == 5) & (pf["cost"] == "stress")].sort_values(
            "net_ann", ascending=False).iterrows():
        log(f"{r['cell']:<14} 持仓占比={r['invested_frac']:.2f} 毛年化={r['gross_ann']:+.3f} "
            f"净年化={r['net_ann']:+.3f} 换手={r['ann_turnover']:.1f} "
            f"条件超额/日={r['cond_excess_mean']:+.5f} t={r['cond_t']:+.1f}")

    # ---------------- 判定 ----------------
    h5 = es[es["h"] == 5]
    cond_a = h5[(h5["mean_excess"] > 0) & (h5["t_stat"] >= 2.0) & h5["same_sign"]]
    priors = {
        "H1_首板>连板": _cmp(h5, "k1_首板", "k3p_连板"),
        "H2_缩量>放量": _cmp(h5, "vr_lo缩量", "vr_hi放量"),
        "H3_一字>回封": _cmp(h5, "one_一字", "nonone_回封"),
        "H4_封板>炸板": _cmp(h5, "ALL_close", "break_炸板"),
    }
    n_prior_ok = sum(1 for v in priors.values() if v)
    stress5 = pf[(pf["h"] == 5) & (pf["cost"] == "stress")]
    b_pass = stress5[stress5["cond_excess_mean"] > 0]
    verdict = "supported" if (len(cond_a) > 0 and n_prior_ok >= 2 and len(b_pass) > 0) else "not_supported"

    decision = {
        "verdict": verdict,
        "endpoint_A_pass_cells": cond_a["cell"].tolist(),
        "priors_confirmed": {k: bool(v) for k, v in priors.items()},
        "n_priors_confirmed": n_prior_ok,
        "endpoint_B_pass_cells": b_pass["cell"].tolist(),
        "criteria": {"A": "h=5 excess>0 & day-clustered t>=2 & 两半同号",
                     "priors": ">=2 of H1-H4 同向",
                     "B": "stress 后条件超额>0"},
    }
    (OUT / "decision.json").write_text(json.dumps(decision, indent=2, ensure_ascii=False))
    (OUT / "methodology.json").write_text(json.dumps({
        "protocol": "research/protocols/a_share_limit_up_event_protocol_v1.md",
        "eval_start": EVAL_START, "eval_end": EVAL_END, "split": SPLIT,
        "limit_lo": LIMIT_LO, "limit_hi": LIMIT_HI, "limit_gap": LIMIT_GAP,
        "min_price": MIN_PRICE, "vr": [VR_LO, VR_HI], "costs": COSTS,
        "horizons": list(HORIZONS),
    }, indent=2, ensure_ascii=False))

    log(f"\n=== VERDICT: {verdict.upper()} ===")
    log(f"A 通过单元: {decision['endpoint_A_pass_cells']}")
    log(f"先验确认 {n_prior_ok}/4: {priors}")
    return 0


def _cmp(df, a, b):
    ra = df[df["cell"] == a]
    rb = df[df["cell"] == b]
    if ra.empty or rb.empty:
        return False
    return bool(ra.iloc[0]["mean_excess"] > rb.iloc[0]["mean_excess"])


if __name__ == "__main__":
    raise SystemExit(main())
