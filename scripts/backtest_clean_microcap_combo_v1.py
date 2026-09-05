#!/usr/bin/env python3
"""干净微盘 2.0：Alpha101 合成信号 + 域内组合回测（协议 clean_microcap_combo_protocol_v1）。

两层结构：
  第一步  cluster_and_signal.py 逻辑内嵌 —— 聚类 10 候选 -> Z1 合成信号（日频截面）
  第二步  12 臂（N×周期）× 3 成本 网格回测 + 对照臂 + 2024 崩盘段
"""
from __future__ import annotations

import itertools
import json
import os
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path('/home/xiaocong/worksapces/qlib')
QLIB_DIR = Path(os.path.expanduser('~')) / '.qlib/qlib_data/cn_data_2026'
OUT = ROOT / 'output/analysis_fundamental/clean_microcap_combo_v1'
OUT.mkdir(parents=True, exist_ok=True)

START, END = '2021-01-01', '2026-08-31'
BT_START, BT_END = pd.Timestamp('2022-01-04'), pd.Timestamp('2026-08-31')
CRASH = (pd.Timestamp('2024-01-01'), pd.Timestamp('2024-02-29'))
IC_START = pd.Timestamp('2022-01-01')

CANDS = ['alpha101_13', 'alpha101_16', 'alpha101_15', 'alpha101_12', 'alpha101_3',
         'alpha101_6', 'alpha101_4', 'alpha101_19', 'alpha101_52', 'alpha101_14']

cal_full = pd.DatetimeIndex(pd.read_csv(QLIB_DIR / 'calendars' / 'day.txt', header=None)[0])
cal = cal_full[(cal_full >= START) & (cal_full <= END)]

# ---------------- 行情 ----------------
_feat = {}


def read_bin(sym, field):
    k = (sym, field)
    if k in _feat:
        return _feat[k]
    p = QLIB_DIR / 'features' / sym / f'{field}.day.bin'
    if not p.exists():
        _feat[k] = None
        return None
    with open(p, 'rb') as f:
        raw = f.read()
    arr = np.frombuffer(raw, dtype='<f')
    s0 = int(arr[0])
    vals = arr[1:]
    _feat[k] = pd.Series(vals, index=cal_full[s0:s0 + len(vals)])
    return _feat[k]


inst = pd.read_csv(QLIB_DIR / 'instruments' / 'all.txt', sep='\t', header=None,
                   names=['code', 'start', 'end'], parse_dates=['start', 'end'])
inst = inst[~inst['code'].str.lower().str.startswith('bj')]
inst_win = inst[(inst['start'] <= END) & (inst['end'] >= '2022-01-01')]
symbols = sorted(inst_win['code'].str.lower().unique())
print(f'[data] universe={len(symbols)}', flush=True)

print('[data] 加载面板 ...', flush=True)
panels = {}
for f in ['open', 'high', 'low', 'close', 'vwap', 'volume', 'amount' if False else 'volume']:
    pass
FIELDS = ['open', 'high', 'low', 'close', 'vwap', 'volume']
panels = {f: pd.DataFrame({s: read_bin(s, f) for s in symbols if read_bin(s, f) is not None}).reindex(cal)
          for f in FIELDS}
O, H, L, C, VW, V = (panels[f] for f in FIELDS)
RET = C.pct_change()
ADV20 = V.rolling(20).mean()

# amount 用 close*volume 近似（qlib 无 amount 字段时）；微盘成交额门槛用之
AMT = C * V

# ---------------- 10 因子复现（同双臂脚本） ----------------
print('[factor] 复现 10 个候选 ...', flush=True)


def cs_rank(df):
    return df.rank(axis=1, pct=True)


def ts_rank(df, w):
    return df.rolling(w).apply(lambda x: (x[~np.isnan(x)] <= x[-1]).mean() if np.isfinite(x).any() else np.nan, raw=True)


F = {}
F['alpha101_13'] = -1 * cs_rank(cs_rank(C).rolling(5).cov(cs_rank(V)))
F['alpha101_16'] = -1 * cs_rank(cs_rank(H).rolling(5).cov(cs_rank(V)))
F['alpha101_15'] = -1 * (cs_rank(cs_rank(H).rolling(3).corr(cs_rank(V)))).rolling(3).sum()
F['alpha101_12'] = np.sign(V.diff(1)) * (-1 * C.diff(1))
F['alpha101_3'] = -1 * cs_rank(O).rolling(10).corr(cs_rank(V))
F['alpha101_6'] = -1 * O.rolling(10).corr(V)
F['alpha101_4'] = -1 * ts_rank(cs_rank(L), 9)
F['alpha101_19'] = -1 * np.sign((C - C.shift(7)) + C.diff(7)) * (1 + cs_rank(1 + RET.rolling(250).sum()))
tsmin_low5 = L.rolling(5).min()
F['alpha101_52'] = ((-1 * tsmin_low5 + tsmin_low5.shift(5))
                    * cs_rank((RET.rolling(240).sum() - RET.rolling(20).sum()) / 220) * ts_rank(V, 5))
F['alpha101_14'] = -1 * cs_rank(RET.diff(3)) * O.rolling(10).corr(V)
print('[factor] 完成', flush=True)

# ---------------- 域（月度干净微盘池） ----------------
print('[domain] 月度重建干净微盘池 ...', flush=True)
db = pd.read_csv(ROOT / 'data/external/tushare/a_share_daily_basic_pit_v1/normalized/daily_basic.csv.gz',
                 compression='gzip', usecols=['ts_code', 'trade_date', 'total_mv'], dtype={'trade_date': str})
db['dt'] = pd.to_datetime(db['trade_date'], format='%Y%m%d')
db = db[~db['ts_code'].str.split('.').str[0].str.startswith(('43', '83', '87', '92', '920'))]
month_end = db.groupby(db['dt'].dt.to_period('M'))['dt'].max().sort_values()
snap = {}
for d in month_end:
    g = db[db['dt'] == d]
    snap[d] = pd.Series(g['total_mv'].values / 1e4, index=g['ts_code'].values)

st = pd.read_csv(ROOT / 'data/external/tushare/a_share_st_status_pit_v1/normalized/st_status_intervals.csv.gz',
                 compression='gzip', parse_dates=['start_date', 'end_date'])
st_start, st_end = st['start_date'].values, st['end_date'].values
st_bad = (st['is_st'] | st['is_delist_phase']).values
st_code = st['ts_code'].values

from load_financials_extended_v1 import load_financials_extended  # noqa: E402
fin = load_financials_extended()
inc = fin[['ts_code', 'end_date', 'available_date', 'n_income_attr_p']].copy()
inc = inc[inc['end_date'].dt.month == 12]
inc = inc.sort_values(['ts_code', 'end_date', 'available_date']).drop_duplicates(['ts_code', 'end_date'], keep='last').dropna(subset=['n_income_attr_p'])
inc['loss'] = inc['n_income_attr_p'] < 0
bps = fin[['ts_code', 'end_date', 'available_date', 'bps']].copy()
bps = bps.sort_values(['ts_code', 'end_date', 'available_date']).drop_duplicates(['ts_code', 'end_date'], keep='last').dropna(subset=['bps'])


def quasi_at(t):
    t64 = np.datetime64(t)
    sub = inc[inc['available_date'] <= t64].sort_values(['ts_code', 'end_date'])
    last2 = sub.groupby('ts_code').tail(2)
    g = last2.groupby('ts_code')['loss'].agg(['count', 'sum'])
    two = set(g[(g['count'] >= 2) & (g['sum'] >= 2)].index)
    sb = bps[bps['available_date'] <= t64].sort_values(['ts_code', 'end_date']).groupby('ts_code').tail(1)
    neg = set(sb[sb['bps'] < 0]['ts_code'])
    return two | neg


def sym_of(c):
    n, e = c.split('.')
    return f'{e.lower()}{n}'


domain_by_month = {}
for d in month_end:
    if not (pd.Timestamp('2021-12-01') <= d <= BT_END):
        continue
    mv = snap[d]
    universe = set(mv.dropna().index)
    thr = mv.quantile(0.10)
    bottom = set(mv[mv <= thr].index)
    mask = (st_start <= np.datetime64(d)) & (st_end >= np.datetime64(d)) & st_bad
    bad = set(st_code[mask])
    quasi = quasi_at(d) & universe
    domain_by_month[d] = {sym_of(c) for c in (bottom - bad - quasi) & universe}
me_ts = np.array(sorted(domain_by_month))
print(f'[domain] 月份数={len(domain_by_month)}', flush=True)

# ---------------- 聚类 + 合成信号（域内日频截面 rank 均值） ----------------
print('[cluster] 域内因子相关性聚类 ...', flush=True)
trading_days = cal[cal >= IC_START]
corr_sums = pd.DataFrame(np.zeros((len(CANDS), len(CANDS))), index=CANDS, columns=CANDS)
corr_counts = 0
sample_days = trading_days[::3]
for t in sample_days:
    idx = np.searchsorted(me_ts, np.datetime64(t), side='right') - 1
    if idx < 0:
        continue
    dom = domain_by_month[me_ts[idx]]
    if len(dom) < 30:
        continue
    ranks = pd.DataFrame({fn: F[fn].loc[t].reindex(sorted(dom)) for fn in CANDS}).dropna()
    if len(ranks) < 30:
        continue
    cr = ranks.corr(method='spearman')
    corr_sums += cr.abs().fillna(0)
    corr_counts += 1
corr_med = corr_sums / max(corr_counts, 1)

# 连通分量聚类 |corr|>0.60
adj = (corr_med.values > 0.60) & ~np.eye(len(CANDS), dtype=bool)
clusters, seen = [], set()
for i, fn in enumerate(CANDS):
    if fn in seen:
        continue
    stack, comp = [i], []
    while stack:
        j = stack.pop()
        if j in seen:
            continue
        seen.add(j)
        comp.append(CANDS[j])
        for k in range(len(CANDS)):
            if adj[j, k] and CANDS[k] not in comp:
                stack.append(k)
    clusters.append(sorted(comp))
print(f'[cluster] {len(clusters)} 族: {clusters}', flush=True)
(OUT / 'cluster_map.json').write_text(json.dumps({'clusters': clusters, 'corr_matrix_file': 'factor_corr_matrix.csv'},
                                                 ensure_ascii=False, indent=2) + '\n')
corr_med.to_csv(OUT / 'factor_corr_matrix.csv')

# Z1 合成: 族内等权 rank 均值 -> 跨族等权（跳过空族）
print('[signal] 计算 Z1 合成信号（日频） ...', flush=True)
Z1 = None
n_fam = 0
for comp in clusters:
    if not comp:
        continue
    z = None
    for fn in comp:
        r = cs_rank(F[fn])
        z = r if z is None else z + r
    z = z / len(comp)
    n_fam += 1
    Z1 = z if Z1 is None else Z1 + z
Z1 = Z1 / n_fam
print(f'[signal] 完成（{n_fam} 实族）', flush=True)

# ---------------- 回测 ----------------
VOL_OK = (V > 0) & C.notna()
O_next = O.shift(-1)


def domain_for_day(t):
    idx = np.searchsorted(me_ts, np.datetime64(t), side='right') - 1
    return domain_by_month[me_ts[idx]] if idx >= 0 else set()


def bad_syms_at(t):
    mask = (st_start <= np.datetime64(t)) & (st_end >= np.datetime64(t)) & st_bad
    return {s.lower() for s in st_code[mask]}


def run_arm(top_n: int, period: int, cost: float):
    """T 日收盘后调仓: 域内 Z1 top-N; T+1 开盘等权成交; period 日后再调。"""
    cash_like = 1.0
    nav = {}
    holdings = {}  # sym -> weight
    rebal_dates = trading_days[::period]
    rebal_set = set(rebal_dates)
    pending = None  # (new_holdings dict) 待 T+1 开盘成交
    cost_paid = 0.0
    daily = []
    for i, t in enumerate(trading_days):
        dom = domain_for_day(t)
        # 1) 当日收益: 持仓按 T 日 close/close_prev（成交在 T+1 开盘的按开盘价起算）
        if holdings:
            tot = sum(holdings.values())
            rets = []
            wsum = 0.0
            for s, w in holdings.items():
                c = C.at[t, s] if s in C.columns else np.nan
                c0 = C.shift(1).at[t, s] if s in C.columns else np.nan
                if pd.notna(c) and pd.notna(c0) and c0 > 0:
                    rets.append(w * (c / c0 - 1))
                    wsum += w
            port_ret = sum(rets) / wsum if wsum > 0 else 0.0
        else:
            port_ret = 0.0
        cash_like *= (1 + port_ret)
        # 2) T+1 开盘成交 pending（前一天收盘后产生的调仓单）
        if pending is not None:
            o_row = O.loc[t]
            fills, total_w = {}, 0.0
            for s in pending:
                o = o_row.get(s, np.nan)
                if pd.notna(o) and o > 0 and VOL_OK.at[t, s] if s in VOL_OK.columns else False:
                    fills[s] = 1.0 / top_n
                    total_w += 1.0 / top_n
            # 成本
            turnover = sum(1 for s in fills if s not in holdings) / top_n \
                + sum(1 for s in holdings if s not in fills) / max(total_w, 1e-9)
            cost_paid += cost * min(turnover, 2.0) * 0.5  # 单边计半额近似
            holdings = fills
            pending = None
            cash_like *= (1 - cost * 0.5 * min(turnover, 2.0))
        # 3) 收盘后调仓信号
        if t in rebal_set and dom:
            bad = bad_syms_at(t)
            cands = [s for s in C.columns if s in dom and s not in bad]
            if len(cands) >= max(10, top_n // 2):
                z = Z1.loc[t].reindex(cands).dropna()
                amt = AMT.loc[t].reindex(cands)
                z = z[(amt.isna() | (amt > 0))]
                top = z.nlargest(top_n).index.tolist()
                if len(top) >= max(10, top_n // 2):
                    pending = top
        nav[t] = (cash_like - 0) * (1 - 0)  # nav 已含成本扣减
        daily.append({'datetime': t, 'nav': cash_like, 'n_hold': len(holdings), 'pending': pending is not None})
    df = pd.DataFrame(daily).set_index('datetime')
    return df, cost_paid


# 对照臂: 全池等权（月度重建跟随, T+1 开盘调仓, 同成本）
def run_pool_arm(cost: float):
    cash_like = 1.0
    holdings = {}
    daily = []
    prev_month = None
    for i, t in enumerate(trading_days):
        dom = domain_for_day(t)
        # 月度重建: 新月份第一个交易日开盘执行
        me_idx = np.searchsorted(me_ts, np.datetime64(t), side='right') - 1
        cur_me = me_ts[me_idx] if me_idx >= 0 else None
        if prev_month is not None and cur_me != prev_month and dom:
            o_row = O.loc[t]
            fills = {s: 1.0 / len(dom) for s in dom if pd.notna(o_row.get(s, np.nan)) and o_row.get(s, 0) > 0}
            if fills:
                turnover = 1.0
                cash_like *= (1 - cost * 0.5 * 2)  # 全换
                holdings = fills
        prev_month = cur_me
        if holdings:
            rets, wsum = [], 0.0
            for s, w in holdings.items():
                c = C.at[t, s] if s in C.columns else np.nan
                c0 = C.shift(1).at[t, s] if s in C.columns else np.nan
                if pd.notna(c) and pd.notna(c0) and c0 > 0:
                    rets.append(w * (c / c0 - 1))
                    wsum += w
            port_ret = sum(rets) / wsum if wsum > 0 else 0.0
        else:
            port_ret = 0.0
        cash_like *= (1 + port_ret)
        daily.append({'datetime': t, 'nav': cash_like, 'n_hold': len(holdings)})
    return pd.DataFrame(daily).set_index('datetime')


COSTS = {'base': 0.0015, 'stress': 0.0040, 'microcap': 0.0080}
ARMS = [(n, p) for n in (30, 50) for p in (5, 10, 20)]

print('\n[bt] 12 臂 × 3 成本 ...', flush=True)
rows = []
nav_store = {}
for (n, p), (cname, cost) in itertools.product(ARMS, COSTS.items()):
    df, cpaid = run_arm(n, p, cost)
    r = df['nav'].pct_change().dropna()
    years = (df.index[-1] - df.index[0]).days / 365.25
    cagr = df['nav'].iloc[-1] ** (1 / years) - 1
    mdd = (df['nav'] / df['nav'].cummax() - 1).min()
    ir = r.mean() / r.std() * np.sqrt(243) if r.std() > 0 else np.nan
    rows.append({'arm': f'top{n}_p{p}', 'cost': cname, 'cost_bps': cost * 1e4,
                 'CAGR': cagr, 'IR': ir, 'MDD': mdd, 'final_nav': df['nav'].iloc[-1],
                 'cum_cost': cpaid})
    nav_store[f'top{n}_p{p}_{cname}'] = df['nav']
    print(f'  top{n}_p{p} {cname}: CAGR={cagr:+.1%} IR={ir:.2f} MDD={mdd:.1%} 成本累计={cpaid:.3f}', flush=True)

print('\n[bt] 对照臂（全池等权）...', flush=True)
for cname, cost in COSTS.items():
    df = run_pool_arm(cost)
    r = df['nav'].pct_change().dropna()
    years = (df.index[-1] - df.index[0]).days / 365.25
    cagr = df['nav'].iloc[-1] ** (1 / years) - 1
    mdd = (df['nav'] / df['nav'].cummax() - 1).min()
    ir = r.mean() / r.std() * np.sqrt(243) if r.std() > 0 else np.nan
    rows.append({'arm': 'pool_ew', 'cost': cname, 'cost_bps': cost * 1e4,
                 'CAGR': cagr, 'IR': ir, 'MDD': mdd, 'final_nav': df['nav'].iloc[-1], 'cum_cost': np.nan})
    nav_store[f'pool_ew_{cname}'] = df['nav']
    print(f'  pool_ew {cname}: CAGR={cagr:+.1%} IR={ir:.2f} MDD={mdd:.1%}', flush=True)

bt = pd.DataFrame(rows)
bt.to_csv(OUT / 'backtest_summary.csv', index=False)

# 崩盘段
print('\n[crash] 2024-01~02 ...', flush=True)
crash_rows = []
for k, nav in nav_store.items():
    seg = nav.loc[CRASH[0]:CRASH[1]]
    if len(seg) > 2:
        crash_rows.append({'nav': k, 'crash_return': seg.iloc[-1] / seg.iloc[0] - 1,
                           'crash_mdd': (seg / seg.cummax() - 1).min()})
pd.DataFrame(crash_rows).to_csv(OUT / 'crash_2024.csv', index=False)

# 超额判定（microcap 口径 vs pool_ew）
print('\n=== 判定（microcap 成本, vs 全池等权） ===')
pool_mc = bt[(bt['arm'] == 'pool_ew') & (bt['cost'] == 'microcap')]['CAGR'].iloc[0]
dec_rows = []
for _, r in bt[(bt['cost'] == 'microcap') & (bt['arm'] != 'pool_ew')].iterrows():
    ex = r['CAGR'] - pool_mc
    tier = 'signal_alpha_net' if (ex >= 0.03 and r['IR'] >= 0.5) else ('signal_alpha_thin' if ex > 0 else 'signal_alpha_dead')
    dec_rows.append({'arm': r['arm'], 'CAGR': r['CAGR'], 'pool_CAGR': pool_mc, 'excess': ex,
                     'IR': r['IR'], 'MDD': r['MDD'], 'tier': tier})
dec = pd.DataFrame(dec_rows)
dec.to_csv(OUT / 'decision_excess_microcap.csv', index=False)
print(dec.round(4).to_string(index=False))

decision = {'protocol': 'research/protocols/clean_microcap_combo_protocol_v1.md',
            'pool_cagr_microcap': float(pool_mc),
            'arms': dec.to_dict('records'),
            'decision_summary': {t: int((dec['tier'] == t).sum()) for t in dec['tier'].unique()}}
(OUT / 'decision.json').write_text(json.dumps(decision, ensure_ascii=False, indent=2) + '\n')
print(json.dumps({'decision_summary': decision['decision_summary']}, ensure_ascii=False))
