#!/usr/bin/env python3
"""评估引擎：IC / 十分位 / 换手 / 扣成本 top-N 组合 / 等权基准。

口径唯一来源：协议 v1 及其 Addendum 1（A1 基准可行性、A2 哨兵作用域）。
只做计算，不做判定（判定在 grade.py）。
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from . import common as C
from .context import Ctx

CAPITAL = 500_000.0
MIN_COMM = 5.0
LOT = 100
N_TOP = 50
Q_DECILE = 10


# ---- 标签 --------------------------------------------------------------------
def forward_label(ctx: Ctx, h: int) -> pd.DataFrame:
    """open-to-open：open[t+1+h]/open[t+1] - 1（后复权）。"""
    O = ctx.O
    return O.shift(-(1 + h)) / O.shift(-1) - 1


# ---- IC ----------------------------------------------------------------------
def rank_ic(factor: pd.DataFrame, label: pd.DataFrame, mask: pd.DataFrame,
            min_n: int = 100) -> tuple[pd.Series, pd.Series]:
    f = factor.where(mask)
    l = label.where(mask)
    both = f.notna() & l.notna()
    n = both.sum(axis=1)
    fm = f.rank(axis=1).where(both)
    lm = l.rank(axis=1).where(both)
    fz = fm.sub(fm.mean(axis=1), axis=0)
    lz = lm.sub(lm.mean(axis=1), axis=0)
    cov = (fz * lz).sum(axis=1)
    den = np.sqrt((fz ** 2).sum(axis=1) * (lz ** 2).sum(axis=1))
    ic = cov / den.replace(0, np.nan)
    ic[n < min_n] = np.nan
    return ic, n


def ic_stats(ic: pd.Series, h: int, min_obs: int = 20) -> dict:
    s = ic.dropna()
    if len(s) < min_obs:
        return dict(ic_n=len(s), ic_mean=np.nan, ic_std=np.nan, icir_ann=np.nan,
                    t_naive=np.nan, t_nonoverlap=np.nan, pos_ratio=np.nan)
    mean, std = float(s.mean()), float(s.std())
    icir = mean / std * np.sqrt(245 / h) if std > 0 else np.nan
    t_naive = mean / std * np.sqrt(len(s)) if std > 0 else np.nan
    s2 = s.iloc[::h]
    t_no = (s2.mean() / s2.std() * np.sqrt(len(s2))
            if len(s2) > 5 and s2.std() > 0 else np.nan)
    return dict(ic_n=len(s), ic_mean=mean, ic_std=std, icir_ann=icir,
                t_naive=t_naive, t_nonoverlap=float(t_no), pos_ratio=float((s > 0).mean()))


# ---- 十分位 ------------------------------------------------------------------
def decile_returns(factor: pd.DataFrame, label: pd.DataFrame, mask: pd.DataFrame,
                   q: int = Q_DECILE) -> pd.DataFrame:
    f = factor.where(mask)
    l = label.where(mask)
    ranks = f.rank(axis=1, pct=True)
    dec = np.ceil(ranks * q).clip(1, q)
    out = {}
    for d in range(1, q + 1):
        sel = (dec == d) & l.notna()
        out[d] = l.where(sel).mean(axis=1)
    return pd.DataFrame(out)


def decile_shape(dec: pd.DataFrame) -> dict:
    m = dec.mean()
    spread = float(m.get(Q_DECILE, np.nan) - m.get(1, np.nan))
    rho = np.nan
    try:
        from scipy.stats import spearmanr
        rho, _ = spearmanr(m.index.values, m.values)
    except Exception:
        pass
    return dict(d1=float(m.get(1, np.nan)), d10=float(m.get(Q_DECILE, np.nan)),
                d10_minus_d1=spread, mono_rho=float(rho) if rho == rho else np.nan)


# ---- 换手 --------------------------------------------------------------------
def topn_turnover(factor: pd.DataFrame, mask: pd.DataFrame, n: int,
                  sig_positions: list[int], h: int) -> float:
    sets = []
    for ti in sig_positions:
        row = factor.iloc[ti].where(mask.iloc[ti]).dropna()
        if len(row) < n:
            continue
        sets.append(set(row.nlargest(n).index))
    if len(sets) < 2:
        return np.nan
    tos = [len(sets[k] - sets[k - 1]) / n for k in range(1, len(sets))]
    return float(np.mean(tos) * (245 / h))


# ---- 等权基准（Addendum 1 §A1 主基准：指数口径、不计成本/整手） ---------------
def ew_benchmark_index(ctx: Ctx, sig_positions: list[int], mask: pd.DataFrame) -> pd.Series:
    O = ctx.O.values
    T = len(ctx.cal)
    exec_idx = [ti + 1 for ti in sig_positions if ti + 1 < T]
    if len(exec_idx) < 2:
        return pd.Series(dtype=float)
    m = mask.values
    lvl = [1.0]
    for k in range(len(exec_idx) - 1):
        e, e2 = exec_idx[k], exec_idx[k + 1]
        sel = m[e] & np.isfinite(O[e]) & np.isfinite(O[e2])
        if sel.sum() < 50:
            lvl.append(lvl[-1])
            continue
        r = O[e2, sel] / O[e, sel] - 1
        lvl.append(lvl[-1] * (1 + np.nanmean(r)))
    return pd.Series(lvl, index=[ctx.cal[i] for i in exec_idx[:len(lvl)]])


# ---- 扣成本 top-N 组合模拟 ----------------------------------------------------
def simulate_topn(ctx: Ctx, signal: pd.DataFrame, mask: pd.DataFrame, h: int, n: int,
                  direction: int, buy_rate: float, sell_rate: float,
                  capital: float = CAPITAL) -> dict:
    """T 日收盘出信号 → T+1 开盘成交；持有 h 日；100 股整手；min_comm；涨跌停/停牌约束。"""
    O, C, OU, CU = (ctx.O.values, ctx.C.values, ctx.O_UNADJ.values, ctx.C_UNADJ.values)
    sig = (signal * direction)
    T = len(ctx.cal)

    seg_idx = np.where(mask.any(axis=1).values)[0]
    i0, i1 = int(seg_idx[0]), int(seg_idx[-1])
    sig_positions = list(range(i0, i1, h))

    exec_idx = set(ti + 1 for ti in sig_positions if ti + 1 < T)
    nav = np.full(T, np.nan)
    cash = capital
    pos: dict[int, dict] = {}
    trades = 0
    util = []
    n_pos = []
    buy_notional = 0.0
    sell_notional = 0.0

    start = sig_positions[0] + 1 if sig_positions else None
    sym_pos = {s: k for k, s in enumerate(ctx.symbols)}
    for dd in range(start, T):
        if dd in exec_idx:
            # --- 先定目标（决定哪些持仓需要卖出）---
            ti = dd - 1
            row = sig.iloc[ti].where(mask.iloc[ti]).dropna()
            targets = list(row.nlargest(n).index) if len(row) >= n else list(row.index)
            tgt_j = {sym_pos[s] for s in targets if s in sym_pos}
            # --- 卖出：只卖「不再入选」的持仓 ---
            # 仍入选的持仓必须留仓，否则每次重平衡都会把整个组合卖出再买回，白付一轮买卖成本：
            # 实测 h=1 时该实现缺陷叠加 5 元最低佣金会把 50 万磨到 6,825 元（−98.6%），
            # 使口径 A 完全失真（正确做法是只交易变动部分，与口径 B 的换手定义一致）。
            for j in list(pos):
                if j in tgt_j:
                    continue
                ou, oa, pc = OU[dd, j], O[dd, j], CU[dd - 1, j]
                if not (np.isfinite(ou) and ou > 0 and np.isfinite(oa) and oa > 0):
                    continue
                if np.isfinite(pc) and ou <= round(pc * 0.9, 2) + 1e-9:
                    continue
                proceeds = pos[j]['cost'] * (oa / pos[j]['entry_adj'])
                comm = max(MIN_COMM, proceeds * sell_rate)
                cash += proceeds - comm
                sell_notional += proceeds
                trades += 1
                del pos[j]
            # --- 买入：只用现金买「尚未持有」的目标名 ---
            equity = cash + sum(p['cost'] * (C[dd - 1, j] / p['entry_adj'])
                                for j, p in pos.items() if np.isfinite(C[dd - 1, j]))
            budget = equity / n
            for sym in targets:
                j = sym_pos[sym]
                if j in pos:
                    # 已持有（仍入选，或停牌/跌停未能卖出）→ 不覆盖、不重复买，
                    # 否则 pos[j]=... 会丢弃旧仓市值（资金静默泄漏）。
                    continue
                ou, oa, pc = OU[dd, j], O[dd, j], CU[dd - 1, j]
                if not (np.isfinite(ou) and ou > 0 and np.isfinite(oa) and oa > 0):
                    continue
                if np.isfinite(pc) and ou >= round(pc * 1.1, 2) - 1e-9:
                    continue
                lots = int(budget // (LOT * ou))
                while lots > 0:
                    cost = lots * LOT * ou
                    comm = max(MIN_COMM, cost * buy_rate)
                    if cost + comm <= cash:
                        break
                    lots -= 1
                if lots <= 0:
                    continue
                cash -= cost + comm
                buy_notional += cost
                trades += 1
                pos[j] = dict(lots=lots, entry_adj=oa, cost=cost)
            inv = sum(p['cost'] * (C[dd, j] / p['entry_adj'])
                      for j, p in pos.items() if np.isfinite(C[dd, j]))
            util.append(inv / equity if equity > 0 else np.nan)
            n_pos.append(len(pos))
        val = cash + sum(p['cost'] * (C[dd, j] / p['entry_adj'])
                         for j, p in pos.items() if np.isfinite(C[dd, j]))
        nav[dd] = val

    navs = pd.Series(nav, index=ctx.cal)
    n_reb = max(len(exec_idx), 1)
    return dict(nav=navs,
                turnover_ann=(buy_notional + sell_notional) / 2 / capital / n_reb * (245 / h),
                utilization=float(np.nanmean(util)) if util else np.nan,
                n_positions=float(np.nanmean(n_pos)) if n_pos else np.nan,
                trades=trades, buy_notional=buy_notional, sell_notional=sell_notional)


def simulate_topn_ew(ctx: Ctx, signal: pd.DataFrame, mask: pd.DataFrame, h: int, n: int,
                     direction: int, buy_rate: float, sell_rate: float,
                     capital: float = CAPITAL) -> dict:
    """口径 B（满仓可比）：等权持有 top-N，无整手/现金拖累，成本按换手比例扣。

    用于与「主板等权全池指数」公平比较（口径 A 的现金拖累会系统性压低超额）。
    每期：gross = 入选股 open→open 等权收益；净 = gross − 单边换手×(买率+卖率)；
    最低佣金以 max(rate, 5元/单笔名义) 折算。
    """
    O, OU, CU = ctx.O.values, ctx.O_UNADJ.values, ctx.C_UNADJ.values
    sig = signal * direction
    T = len(ctx.cal)
    rows_any = np.where(mask.any(axis=1).values)[0]
    i0, i1 = int(rows_any[0]), int(rows_any[-1])
    sig_positions = list(range(i0, i1, h))
    exec_idx = [t + 1 for t in sig_positions if t + 1 < T]
    if len(exec_idx) < 2:
        return dict(nav=pd.Series(dtype=float), turnover_ann=np.nan, rets=pd.Series(dtype=float))

    notional = capital / n
    eff_buy = max(buy_rate, MIN_COMM / notional)
    eff_sell = max(sell_rate, MIN_COMM / notional)

    nav = [1.0]
    dates = [ctx.cal[exec_idx[0]]]
    prev = None
    tos = []
    for k in range(len(exec_idx) - 1):
        e, e2 = exec_idx[k], exec_idx[k + 1]
        ti = e - 1
        row = sig.iloc[ti].where(mask.iloc[ti]).dropna()
        if len(row) < n:
            cur = set(row.index)
        else:
            cur = set(row.nlargest(n).index)
        # 只保留两端都有价的可成交标的
        sel = [s for s in cur]
        cols = {s: i for i, s in enumerate(ctx.symbols)}
        jj = np.array([cols[s] for s in sel], dtype=int)
        ok = np.isfinite(O[e, jj]) & np.isfinite(O[e2, jj])
        jj = jj[ok]
        if len(jj) < 10:
            nav.append(nav[-1]); dates.append(ctx.cal[e2]); continue
        gross = float(np.nanmean(O[e2, jj] / O[e, jj] - 1))
        to = (len(cur - prev) / n) if prev is not None else 1.0
        tos.append(to)
        net = gross - to * (eff_buy + eff_sell)
        nav.append(nav[-1] * (1 + net))
        dates.append(ctx.cal[e2])
        prev = cur
    return dict(nav=pd.Series(nav, index=dates),
                turnover_ann=float(np.mean(tos) * (245 / h)) if tos else np.nan,
                rets=pd.Series(np.diff(nav) / np.array(nav[:-1]), index=dates[1:]))


# ---- 分段与分桶 --------------------------------------------------------------
def segment_positions(ctx: Ctx, seg: str, h: int, mask: pd.DataFrame) -> list[int]:
    cal = ctx.cal
    idx = C.in_segment(cal, seg)
    m = mask.reindex(idx).any(axis=1).values
    pos = [int(np.where(cal == d)[0][0]) for d in idx[m]]
    return pos[::h]


def bucket_masks(ctx: Ctx, total_mv: pd.DataFrame, pool: pd.DataFrame) -> dict[str, pd.DataFrame]:
    """分桶：all / size 五分位 Q1..Q5 / SME（002+003 原中小板）/ nonSME。

    协议 §2 要求 002/003 单独分层报告。
    """
    b = C.size_bucket(total_mv, pool, C.SIZE_N)
    out = {'all': pool}
    for k in range(1, C.SIZE_N + 1):
        out[f'Q{k}'] = pool & (b == k)
    sme = pd.Series(ctx.sme, index=pool.columns)
    out['SME'] = pool & sme
    out['nonSME'] = pool & (~sme)
    return out


def annualized_return(nav: pd.Series, idx: pd.DatetimeIndex) -> float:
    s = nav.reindex(idx).dropna()
    if len(s) < 2 or s.iloc[0] <= 0:
        return np.nan
    yrs = (s.index[-1] - s.index[0]).days / 365.25
    return float((s.iloc[-1] / s.iloc[0]) ** (1 / yrs) - 1) if yrs > 0 else np.nan
