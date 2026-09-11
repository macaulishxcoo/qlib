#!/usr/bin/env python3
"""沪深主板末20%域（剔除ST/准ST）市场表现 + 市值分布 v1。

口径（复刻旧窗口域构建 + 本轮统计口径）：
- 主板 = 沪 600/601/603/605 + 深 000/001/002/003，排除创业板/科创板/北交所；
- 每月末按 total_mv 在主板内排名取末 20%；
- 清洁域 = 末20% − ST/*ST/退市整理(PIT 区间) − 准ST(bps<0 或 连续两年年报亏损, PIT)；
- 表现：月末收盘->下月末收盘，等权、费前，退市用最后可得价；2016-01~2026-08；
- 分布：总市值/流通市值/自由流通市值（亿元）的分位。

产物：output/analysis_fundamental/mainboard20_clean_profile_v1/
"""
from __future__ import annotations
import os, sys
from pathlib import Path
import numpy as np
import pandas as pd

ROOT = Path('/home/xiaocong/worksapces/qlib')
sys.path.insert(0, str(ROOT / 'scripts'))
QLIB = Path(os.path.expanduser('~')) / '.qlib/qlib_data/cn_data_2026'
OUT = ROOT / 'output/analysis_fundamental/mainboard20_clean_profile_v1'
OUT.mkdir(parents=True, exist_ok=True)
DB = ROOT / 'data/external/tushare/a_share_daily_basic_pit_v1/normalized/daily_basic.csv.gz'
ST = ROOT / 'data/external/tushare/a_share_st_status_pit_v1/normalized/st_status_intervals.csv.gz'

cal_full = pd.DatetimeIndex(pd.read_csv(QLIB / 'calendars' / 'day.txt', header=None)[0])

db = pd.read_csv(DB, compression='gzip',
                 usecols=['ts_code', 'trade_date', 'total_mv', 'circ_mv', 'free_share', 'close'],
                 dtype={'trade_date': str})
db['dt'] = pd.to_datetime(db['trade_date'], format='%Y%m%d')
db['num'] = db['ts_code'].str.split('.').str[0]
db = db[~db['num'].str.startswith(('43', '83', '87', '92', '920'))]
db['board'] = np.where(db['num'].str.startswith('68'), 'star',
              np.where(db['num'].str.startswith('30'), 'chinext',
              np.where(db['num'].str.startswith(('600', '601', '603', '605')), 'sse_main',
              np.where(db['num'].str.startswith(('000', '001', '002', '003')), 'szse_main', 'other'))))
db = db[db['board'].isin(['sse_main', 'szse_main'])].copy()
db['total_yi'] = db['total_mv'] / 1e4
db['circ_yi'] = db['circ_mv'] / 1e4
db['free_yi'] = db['free_share'] * 1e4 * db['close'] / 1e8
month_end = db.groupby(db['dt'].dt.to_period('M'))['dt'].max().sort_values()
print(f'[data] 主板月末 {len(month_end)} 个, {month_end.iloc[0].date()} ~ {month_end.iloc[-1].date()}', flush=True)

st = pd.read_csv(ST, compression='gzip', parse_dates=['start_date', 'end_date'])
st_start, st_end = st['start_date'].values, st['end_date'].values
st_bad = (st['is_st'] | st['is_delist_phase']).values
st_code = st['ts_code'].values
def bad_at(t):
    m = (st_start <= np.datetime64(t)) & (st_end >= np.datetime64(t)) & st_bad
    return set(st_code[m])

from load_financials_extended_v1 import load_financials_extended  # noqa
fin = load_financials_extended()
inc = fin[['ts_code', 'end_date', 'available_date', 'n_income_attr_p']].copy()
inc = inc[inc['end_date'].dt.month == 12].dropna(subset=['n_income_attr_p'])
inc = inc.sort_values(['ts_code', 'end_date', 'available_date']).drop_duplicates(['ts_code', 'end_date'], keep='last')
inc['loss'] = inc['n_income_attr_p'] < 0
bps = fin[['ts_code', 'end_date', 'available_date', 'bps']].copy().dropna(subset=['bps'])
bps = bps.sort_values(['ts_code', 'end_date', 'available_date']).drop_duplicates(['ts_code', 'end_date'], keep='last')
def quasi_at(t):
    t64 = np.datetime64(t)
    s = inc[inc['available_date'] <= t64].sort_values(['ts_code', 'end_date'])
    g = s.groupby('ts_code').tail(2).groupby('ts_code')['loss'].agg(['count', 'sum'])
    two = set(g[(g['count'] >= 2) & (g['sum'] >= 2)].index)
    b = bps[bps['available_date'] <= t64].sort_values(['ts_code', 'end_date']).groupby('ts_code').tail(1)
    return two | set(b[b['bps'] < 0]['ts_code'])

# 行情面板（仅用于表现）
def read_bin(sym, field):
    p = QLIB / 'features' / sym / f'{field}.day.bin'
    if not p.exists():
        return None
    arr = np.frombuffer(open(p, 'rb').read(), dtype='<f')
    s0 = int(arr[0]); return pd.Series(arr[1:], index=cal_full[s0:s0 + len(arr) - 1])
def ts2sym(c):
    n, e = c.split('.'); return f'{e.lower()}{n}'
cal = cal_full[(cal_full >= '2016-01-01') & (cal_full <= '2026-08-31')]
all_ts = sorted(db['ts_code'].unique())
data = {}
for c in all_ts:
    s = read_bin(ts2sym(c), 'close')
    if s is not None:
        data[c] = s.reindex(cal)
C = pd.DataFrame(data)
print(f'[data] 行情 {C.shape[0]} 天 × {C.shape[1]} 只', flush=True)

QS = [0.0, .01, .05, .10, .25, .50, .75, .90, .95, .99, 1.0]
QL = ['min', 'p1', 'p5', 'p10', 'p25', 'p50', 'p75', 'p90', 'p95', 'p99', 'max']

dates = list(month_end)
dist_rows, perf_rows = [], []
pooled = {'total': [], 'circ': [], 'free': []}
snap_cache = {}


def domain_at(t):
    """返回 (thr, raw_df, clean_df)，月末主板末20%的原始与清洁名单。"""
    if t in snap_cache:
        return snap_cache[t]
    snap = db[db['dt'] == t]
    mv = snap['total_yi'].dropna()
    thr = mv.quantile(0.20)
    raw = snap[snap['total_yi'] <= thr].copy()
    bad, quasi = bad_at(t), quasi_at(t)
    clean = raw[~raw['ts_code'].isin(bad | quasi)].copy()
    snap_cache[t] = (thr, raw, clean, bad, quasi)
    return snap_cache[t]


# --- 分布：遍历全部月末（含最后一个） ---
for t in dates:
    thr, raw, clean, bad, quasi = domain_at(t)
    if len(raw) < 100:
        continue
    q = clean['total_yi'].quantile(QS).values
    qc = clean['circ_yi'].dropna().quantile(QS).values
    qf = clean['free_yi'].dropna().quantile(QS).values
    dist_rows.append({'date': str(t.date()), 'thr20': thr, 'n_raw': len(raw), 'n_clean': len(clean),
                      'n_st': int(raw['ts_code'].isin(bad).sum()),
                      'n_quasi': int(raw['ts_code'].isin(quasi).sum()),
                      'n_overlap': int(raw['ts_code'].isin(bad & quasi).sum()),
                      **{f'total_{k}': v for k, v in zip(QL, q)},
                      **{f'circ_{k}': v for k, v in zip(QL, qc)},
                      **{f'free_{k}': v for k, v in zip(QL, qf)}})
    pooled['total'].append(clean['total_yi'].dropna().values)
    pooled['circ'].append(clean['circ_yi'].dropna().values)
    pooled['free'].append(clean['free_yi'].dropna().values)

# --- 表现：月末配对（最后一个月末无下一期，不能配对） ---
for i in range(len(dates) - 1):
    t, t1 = dates[i], dates[i + 1]
    thr, raw, clean, bad, quasi = domain_at(t)
    if len(raw) < 100:
        continue
    c0, c1 = C.loc[t], C.loc[:t1].ffill().iloc[-1]

    def mr(codes):
        codes = [c for c in codes if c in c0.index and c in c1.index]
        b, s = c0.reindex(codes), c1.reindex(codes)
        r = (s / b.where(b > 0) - 1).replace([np.inf, -np.inf], np.nan).dropna()
        return (r.mean() if len(r) else np.nan), len(r)
    rc, nc = mr(clean['ts_code'].tolist())
    rr, nr = mr(raw['ts_code'].tolist())
    perf_rows.append({'t': t, 't1': t1, 'ret_clean': rc, 'ret_raw': rr, 'n_clean': nc, 'n_raw': nr})

dist = pd.DataFrame(dist_rows)
dist['year'] = dist['date'].str[:4]
dist.to_csv(OUT / 'monthly_mv_distribution.csv', index=False)
perf = pd.DataFrame(perf_rows); perf['year'] = perf['t'].dt.year
perf.to_csv(OUT / 'monthly_returns.csv', index=False)

# 池化分布
pool_row = {lab: dict(zip(QL, np.quantile(np.concatenate(v), QS)))
            for lab, v in [('总市值', pooled['total']), ('流通市值', pooled['circ']), ('自由流通市值', pooled['free'])]}
pd.DataFrame(pool_row).to_csv(OUT / 'pooled_mv_distribution.csv')

# 分年分布
yr = dist.groupby('year')[['thr20', 'n_clean', 'total_p10', 'total_p25', 'total_p50',
                           'total_p75', 'total_p90', 'total_max']].median()
yr.to_csv(OUT / 'yearly_mv_distribution.csv')

# 市值区间计数（最新截面 + 全样本池化）
def band_counts(vals):
    edges = [0, 10, 20, 30, 40, 50, np.inf]
    labs = ['<10亿', '10-20亿', '20-30亿', '30-40亿', '40-50亿', '>50亿']
    v = np.concatenate(vals) if isinstance(vals, list) else vals
    return {l: int(((v >= edges[k]) & (v < edges[k + 1])).sum()) for k, l in enumerate(labs)}
pd.Series(band_counts(pooled['total'])).to_csv(OUT / 'pooled_mv_bands.csv')
thr_l, rawl, cleanl, bad_l, quasi_l = domain_at(dates[-1])
pd.Series(band_counts(cleanl['total_yi'].dropna().values)).to_csv(OUT / 'latest_mv_bands.csv')

# 表现统计
def stats(r):
    r = r.dropna(); nav = (1 + r).cumprod(); yrs = len(r) / 12
    dd = nav / nav.cummax() - 1
    return {'n_months': len(r), 'nav_x': nav.iloc[-1], 'CAGR': nav.iloc[-1] ** (1 / yrs) - 1,
            'vol': r.std() * np.sqrt(12), 'MDD': dd.min(), 'win_rate': (r > 0).mean()}
perf_sum = pd.DataFrame({'clean': stats(perf['ret_clean']), 'raw': stats(perf['ret_raw'])}).T
perf_sum.to_csv(OUT / 'performance_summary.csv')
yret = perf.groupby('year')[['ret_clean', 'ret_raw']].apply(lambda g: (1 + g).prod() - 1)
yret.to_csv(OUT / 'yearly_returns.csv')

# 打印
print('\n' + '=' * 94)
print('沪深主板末20%（剔除ST/准ST）——市场表现 + 市值分布')
print('=' * 94)
print('\n【市场表现（等权、月度调仓、费前）】')
ps = perf_sum.copy()
ps['nav_x'] = ps['nav_x'].round(2); ps['CAGR'] = (ps['CAGR'] * 100).round(1)
ps['vol'] = (ps['vol'] * 100).round(1); ps['MDD'] = (ps['MDD'] * 100).round(1)
ps['win_rate'] = (ps['win_rate'] * 100).round(0)
print(ps.to_string())
print('\n【分年度收益（%）】')
print((yret * 100).round(1).to_string())
print('\n【清洁域市值分布：全样本池化分位（亿元）】')
print(pd.DataFrame(pool_row).round(1).to_string())
print('\n【分年市值分布（中位，亿元）】')
print(yr.round(1).to_string())
print('\n【最新截面 ' + dist["date"].iloc[-1] + '】')
print(f'  末20%阈值={thr_l:.1f}亿, 原始={len(rawl)}, 清洁={len(cleanl)}, '
      f'ST={int(rawl["ts_code"].isin(bad_l).sum())}, 准ST={int(rawl["ts_code"].isin(quasi_l).sum())}, '
      f'重叠={int(rawl["ts_code"].isin(bad_l & quasi_l).sum())}')
for c, lab in [('total_yi', '总市值'), ('circ_yi', '流通市值'), ('free_yi', '自由流通市值')]:
    s = cleanl[c].dropna().quantile([0, .1, .25, .5, .75, .9, 1])
    print(f'  {lab:8s}: min={s[0]:5.1f} p10={s[.1]:5.1f} p25={s[.25]:5.1f} p50={s[.5]:5.1f} '
          f'p75={s[.75]:5.1f} p90={s[.9]:5.1f} max={s[1]:5.1f}')
print('\n【全样本市值区间占比】')
bc = band_counts(pooled['total']); tot = sum(bc.values())
for k, v in bc.items():
    print(f'  {k:>8s}: {v:6d}  ({100*v/tot:5.1f}%)')
print(f'\n落盘: {OUT}')
