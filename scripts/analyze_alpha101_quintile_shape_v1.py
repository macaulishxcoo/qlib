#!/usr/bin/env python3
"""Alpha101 域内分层单调性检验 v1（协议 alpha101_quintile_shape_protocol_v1）。

10 候选 + Z1 合成，域内 5 分组，月度调仓持有，费前。
输出形状判定（单调/头部集中/头部有毒/无形状）+ Q5 可交易性 + 多空价差 t 检验。
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path('/home/xiaocong/worksapces/qlib')
QLIB_DIR = Path(os.path.expanduser('~')) / '.qlib/qlib_data/cn_data_2026'
OUT = ROOT / 'output/analysis_static/alpha101_quintile_shape_v1'
OUT.mkdir(parents=True, exist_ok=True)

START, END = '2021-01-01', '2026-08-31'
BT_START = pd.Timestamp('2022-01-01')

CANDS = ['alpha101_13', 'alpha101_16', 'alpha101_15', 'alpha101_12', 'alpha101_3',
         'alpha101_6', 'alpha101_4', 'alpha101_19', 'alpha101_52', 'alpha101_14']

cal_full = pd.DatetimeIndex(pd.read_csv(QLIB_DIR / 'calendars' / 'day.txt', header=None)[0])
cal = cal_full[(cal_full >= START) & (cal_full <= END)]

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

print('[data] 加载面板 ...', flush=True)
FIELDS = ['open', 'high', 'low', 'close', 'vwap', 'volume']
panels = {f: pd.DataFrame({s: read_bin(s, f) for s in symbols if read_bin(s, f) is not None}).reindex(cal)
          for f in FIELDS}
O, H, L, C, VW, V = (panels[f] for f in FIELDS)
RET = C.pct_change()
ADV20 = V.rolling(20).mean()
PREV_C = C.shift(1)

# ---------------- 因子（同前） ----------------
print('[factor] 复现 10 候选 ...', flush=True)


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

# Z1 合成（复用 clean_microcap 聚类结果: 6 实族）
CLUSTERS = [['alpha101_13', 'alpha101_15', 'alpha101_16'], ['alpha101_12'],
            ['alpha101_14', 'alpha101_3', 'alpha101_6'], ['alpha101_4'],
            ['alpha101_19'], ['alpha101_52']]
Z1 = None
for comp in CLUSTERS:
    z = None
    for fn in comp:
        r = cs_rank(F[fn])
        z = r if z is None else z + r
    z = z / len(comp)
    Z1 = z if Z1 is None else Z1 + z
Z1 = Z1 / len(CLUSTERS)
SIGNALS = dict(F)
SIGNALS['Z1_synth'] = Z1
print(f'[factor] 信号数={len(SIGNALS)}', flush=True)

# ---------------- 域（月度重建，同前） ----------------
print('[domain] 干净微盘池 ...', flush=True)
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
    if not (pd.Timestamp('2021-12-01') <= d <= pd.Timestamp(END)):
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

# ---------------- 月度调仓日（每月第一个交易日） ----------------
trading_days = cal[cal >= BT_START]
td_series = pd.Series(trading_days, index=trading_days)
month_first = td_series.groupby(trading_days.to_period('M')).min().sort_values()
month_first = [d for d in month_first if np.searchsorted(me_ts, np.datetime64(d), side='right') - 1 >= 0]
print(f'[bt] 调仓月数={len(month_first)}', flush=True)

# ---------------- 分组回测（月度，费前） ----------------
print('[bt] 分组回测 ...', flush=True)
C_prev = PREV_C


def group_month_returns(sig_name: str, entry_day) -> dict[str, float] | None:
    """entry_day T 收盘分组 -> T+1 开盘买入, 持有至下月同日 T+1 开盘卖出（费前）。
    返回 {Q1..Q5, Q5Q1, ALL(全域等权)} 的持有期收益。"""
    idx = np.searchsorted(me_ts, np.datetime64(entry_day), side='right') - 1
    dom = domain_by_month[me_ts[idx]]
    bad_mask = (st_start <= np.datetime64(entry_day)) & (st_end >= np.datetime64(entry_day)) & st_bad
    bad_syms = {s.lower() for s in st_code[bad_mask]}
    cands = [s for s in C.columns if s in dom and s not in bad_syms]
    if len(cands) < 50:
        return None
    frow = SIGNALS[sig_name].loc[entry_day].reindex(cands).dropna()
    if len(frow) < 50:
        return None
    # 分组: 5 等份
    try:
        qcut = pd.qcut(frow.rank(method='first'), 5, labels=False)
    except ValueError:
        return None
    groups = {q: qcut[qcut == q].index.tolist() for q in range(5)}

    # 下一调仓日
    pos = month_first.index(entry_day)
    if pos + 1 >= len(month_first):
        return None
    exit_day = month_first[pos + 1]
    o_in = O.loc[exit_day]  # 用 exit_day 的开盘价? 不: 买入在 entry 的 T+1 开盘
    # T+1 开盘（entry 的下一交易日）
    cal_pos = cal.get_loc(entry_day)
    if cal_pos + 1 >= len(cal):
        return None
    buy_day = cal[cal_pos + 1]
    o_buy = O.loc[buy_day]

    # 卖出日 = exit_day 的下一交易日开盘
    exit_pos = cal.get_loc(exit_day)
    if exit_pos + 1 >= len(cal):
        return None
    sell_day = cal[exit_pos + 1]
    o_sell = O.loc[sell_day]

    out = {}
    valid_syms = 0
    for q in range(5):
        rets = []
        for s in groups[q]:
            b = o_buy.get(s, np.nan)
            sl = o_sell.get(s, np.nan)
            if pd.notna(b) and pd.notna(sl) and b > 0:
                rets.append(sl / b - 1)
        out[f'Q{q+1}'] = float(np.mean(rets)) if rets else np.nan
    all_rets = []
    for s in frow.index:
        b = o_buy.get(s, np.nan)
        sl = o_sell.get(s, np.nan)
        if pd.notna(b) and pd.notna(sl) and b > 0:
            all_rets.append(sl / b - 1)
    out['ALL'] = float(np.mean(all_rets)) if all_rets else np.nan
    out['n'] = len(frow)
    out['exit'] = str(exit_day.date())
    # Q5 可交易性: 分组时点(entry_day 收盘)的涨停/停牌占比
    q5 = groups[4]
    limit_up = 0
    halted = 0
    for s in q5:
        c_now = C.at[entry_day, s] if s in C.columns else np.nan
        c_prev = C_prev.at[entry_day, s] if s in C.columns else np.nan
        v_now = V.at[entry_day, s] if s in V.columns else np.nan
        if pd.notna(c_now) and pd.notna(c_prev) and c_prev > 0 and c_now / c_prev - 1 >= 0.095:
            limit_up += 1
        if pd.isna(v_now) or v_now <= 0:
            halted += 1
    out['q5_limit_up_ratio'] = limit_up / len(q5) if q5 else np.nan
    out['q5_halt_ratio'] = halted / len(q5) if q5 else np.nan
    return out


rows = []
for sig in list(SIGNALS.keys()):
    print(f'  {sig} ...', flush=True)
    for i, d in enumerate(month_first[:-1]):
        r = group_month_returns(sig, d)
        if r is None:
            continue
        for k in ['Q1', 'Q2', 'Q3', 'Q4', 'Q5', 'ALL']:
            rows.append({'signal': sig, 'entry': str(d.date()), 'exit': r['exit'],
                         'group': k, 'ret': r[k], 'n': r['n'],
                         'q5_limit_up': r['q5_limit_up_ratio'], 'q5_halt': r['q5_halt_ratio']})

df = pd.DataFrame(rows)
df.to_csv(OUT / 'quintile_monthly_returns.csv', index=False)

# ---------------- 形状判定 ----------------
print('\n[shape] 形状判定 ...', flush=True)
from scipy import stats as sps  # noqa: E402

shape_rows = []
for sig in SIGNALS:
    sub = df[df['signal'] == sig]
    piv = sub.pivot_table(index='exit', columns='group', values='ret')
    piv = piv[['Q1', 'Q2', 'Q3', 'Q4', 'Q5']].dropna()
    if len(piv) < 10:
        continue
    means = piv.mean()
    rho, _ = sps.spearmanr([1, 2, 3, 4, 5], means.values)
    spread = piv['Q5'] - piv['Q1']
    t_stat, p_val = sps.ttest_1samp(spread.dropna(), 0)
    yearly_spread = spread.groupby(spread.index.str[:4]).mean()
    years_pos = int((yearly_spread > 0).sum())
    # Q5 可交易性（跨月均值）
    q5lu = sub.dropna(subset=['q5_limit_up'])['q5_limit_up'].mean()
    q5h = sub.dropna(subset=['q5_halt'])['q5_halt'].mean()

    if rho >= 0.80 and means['Q5'] > means['Q1']:
        shape = 'monotonic'
    elif means['Q5'] == means.max() and (means['Q5'] - means['Q3']) > 2 * max(means['Q3'] - means['Q1'], 1e-9):
        shape = 'head_concentrated'
    elif means['Q5'] < means['Q3']:
        shape = 'head_toxic'
    elif abs(rho) < 0.40:
        shape = 'no_shape'
    else:
        shape = 'head_concentrated' if means['Q5'] == means.max() else 'no_shape'

    spread_sig = (abs(t_stat) >= 2) and (years_pos >= 4 or years_pos <= 1)
    shape_rows.append({'signal': sig, 'shape': shape,
                       'Q1': means['Q1'], 'Q2': means['Q2'], 'Q3': means['Q3'],
                       'Q4': means['Q4'], 'Q5': means['Q5'], 'ALL': sub['ret'][sub['group'] == 'ALL'].mean(),
                       'Q5_minus_Q1_monthly': spread.mean(),
                       'spread_t': t_stat, 'spread_p': p_val,
                       'years_positive': f'{years_pos}/{len(yearly_spread)}',
                       'spread_significant': spread_sig,
                       'q5_limit_up_ratio': q5lu, 'q5_halt_ratio': q5h,
                       'n_months': len(piv)})

sh = pd.DataFrame(shape_rows)
sh.to_csv(OUT / 'shape_summary.csv', index=False)


def route(row):
    if row['shape'] == 'monotonic' and row['spread_significant']:
        return '全池增强构造（top-N 结论不适用）'
    if row['shape'] == 'head_concentrated' and (row['q5_limit_up_ratio'] + row['q5_halt_ratio']) <= 0.10:
        return '复核成本后重测 top-N'
    if row['shape'] == 'head_toxic' or (row['q5_limit_up_ratio'] + row['q5_halt_ratio']) > 0.10:
        return '截头中段构造或放弃'
    return '放弃信号'


sh['construction_route'] = sh.apply(route, axis=1)

print('\n=== 形状总表（月均收益，费前） ===')
print(sh.round(4).to_string(index=False))

z1 = sh[sh['signal'] == 'Z1_synth'].iloc[0]
decision = {'protocol': 'research/protocols/alpha101_quintile_shape_protocol_v1.md',
            'z1_shape': z1['shape'],
            'z1_spread_t': float(z1['spread_t']),
            'z1_q5_tradability': float(z1['q5_limit_up_ratio'] + z1['q5_halt_ratio']),
            'z1_route': z1['construction_route'],
            'per_signal_shapes': sh[['signal', 'shape', 'construction_route']].to_dict('records')}
(OUT / 'decision.json').write_text(json.dumps(decision, ensure_ascii=False, indent=2) + '\n')
print(f"\nZ1 主信号: shape={z1['shape']}, Q5-Q1月均={z1['Q5_minus_Q1_monthly']:.4f}, "
      f"t={z1['spread_t']:.2f}, Q5涨停+停牌={z1['q5_limit_up_ratio']+z1['q5_halt_ratio']:.1%}")
print(f"路线: {z1['construction_route']}")
