#!/usr/bin/env python3
"""沪深主板末20%域市场表现统计 v1（复刻 /tmp/b10_clean_vs_market.py 口径，换域）。

口径与旧窗口完全一致（除域定义）：
- 每月末 T: 域内按 total_mv 截面排名取档；组合等权持有至 T'，复利成 NAV；
- 域：沪深主板（沪 600/601/603/605 + 深 000/001/002/003）内末 20%；
- 剔除：ST/*ST/退市整理（PIT 区间）+ 准ST（bps<0 或 连续两年年报亏损，PIT 年报）；
- 收益：月末收盘 -> 下月末收盘，等权、费前；期间退市用最后可得价；
- 窗口：2016-01 ~ 2026-08（daily_basic 全历史）。

组合（7 个）：
  mb20_clean  主板末20% - ST - 准ST（主）
  mb20_all    主板末20%（不剔，对照污染）
  mb_main     主板全池等权（剔北交所）
  mb_main_exbad 主板全池剔 ST
  mkt         全市场三板块等权（对照）
  mkt_exbad   全市场剔 ST（对照）
  b10_clean   旧微盘域（三板块末10% - ST - 准ST，横向参照）

产物：output/analysis_fundamental/mainboard20_market_performance_v1/
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path('/home/xiaocong/worksapces/qlib')
sys.path.insert(0, str(ROOT / 'scripts'))
QLIB_DIR = Path(os.path.expanduser('~')) / '.qlib/qlib_data/cn_data_2026'
OUT = ROOT / 'output/analysis_fundamental/mainboard20_market_performance_v1'
OUT.mkdir(parents=True, exist_ok=True)

DB = ROOT / 'data/external/tushare/a_share_daily_basic_pit_v1/normalized/daily_basic.csv.gz'
ST = ROOT / 'data/external/tushare/a_share_st_status_pit_v1/normalized/st_status_intervals.csv.gz'

# ---------------- 日历 ----------------
cal_full = pd.DatetimeIndex(pd.read_csv(QLIB_DIR / 'calendars' / 'day.txt', header=None)[0])

# ---------------- daily_basic + 板块 ----------------
print('[data] daily_basic ...', flush=True)
db = pd.read_csv(DB, compression='gzip', usecols=['ts_code', 'trade_date', 'total_mv'], dtype={'trade_date': str})
db['dt'] = pd.to_datetime(db['trade_date'], format='%Y%m%d')
db['num'] = db['ts_code'].str.split('.').str[0]
db = db[~db['num'].str.startswith(('43', '83', '87', '92', '920'))]
db['board'] = np.where(db['num'].str.startswith('68'), 'star',
              np.where(db['num'].str.startswith('30'), 'chinext',
              np.where(db['num'].str.startswith(('600', '601', '603', '605')), 'sse_main',
              np.where(db['num'].str.startswith(('000', '001', '002', '003')), 'szse_main', 'other'))))
db = db[db['board'] != 'other']
month_end = db.groupby(db['dt'].dt.to_period('M'))['dt'].max().sort_values()
print(f'[data] {db["dt"].min().date()} ~ {db["dt"].max().date()}, 月末数={len(month_end)}', flush=True)

snap_mv, snap_board = {}, {}
for d in month_end:
    g = db[db['dt'] == d]
    snap_mv[d] = pd.Series(g['total_mv'].values / 1e4, index=g['ts_code'].values)
    snap_board[d] = g.set_index('ts_code')['board']

# ---------------- ST PIT ----------------
st = pd.read_csv(ST, compression='gzip', parse_dates=['start_date', 'end_date'])
st_start, st_end = st['start_date'].values, st['end_date'].values
st_bad = (st['is_st'] | st['is_delist_phase']).values
st_code = st['ts_code'].values


def bad_at(t):
    mask = (st_start <= np.datetime64(t)) & (st_end >= np.datetime64(t)) & st_bad
    return set(st_code[mask])


# ---------------- 准ST PIT ----------------
from load_financials_extended_v1 import load_financials_extended  # noqa: E402
print('[data] 财务 PIT ...', flush=True)
fin = load_financials_extended()
inc = fin[['ts_code', 'end_date', 'available_date', 'n_income_attr_p']].copy()
inc = inc[inc['end_date'].dt.month == 12]
inc = inc.sort_values(['ts_code', 'end_date', 'available_date']).drop_duplicates(['ts_code', 'end_date'], keep='last')
inc = inc.dropna(subset=['n_income_attr_p'])
inc['loss'] = inc['n_income_attr_p'] < 0
bpsdf = fin[['ts_code', 'end_date', 'available_date', 'bps']].copy()
bpsdf = bpsdf.sort_values(['ts_code', 'end_date', 'available_date']).drop_duplicates(['ts_code', 'end_date'], keep='last')
bpsdf = bpsdf.dropna(subset=['bps'])


def quasi_at(t):
    t64 = np.datetime64(t)
    sub = inc[inc['available_date'] <= t64].sort_values(['ts_code', 'end_date'])
    last2 = sub.groupby('ts_code').tail(2)
    g = last2.groupby('ts_code')['loss'].agg(['count', 'sum'])
    two = set(g[(g['count'] >= 2) & (g['sum'] >= 2)].index)
    sb = bpsdf[bpsdf['available_date'] <= t64].sort_values(['ts_code', 'end_date']).groupby('ts_code').tail(1)
    return two | set(sb[sb['bps'] < 0]['ts_code'])


# ---------------- 行情宽表 ----------------
print('[data] 行情面板 ...', flush=True)


def read_bin(sym, field):
    p = QLIB_DIR / 'features' / sym / f'{field}.day.bin'
    if not p.exists():
        return None
    with open(p, 'rb') as f:
        raw = f.read()
    arr = np.frombuffer(raw, dtype='<f')
    s0 = int(arr[0])
    vals = arr[1:]
    return pd.Series(vals, index=cal_full[s0:s0 + len(vals)])


def ts2sym(c):
    n, e = c.split('.')
    return f'{e.lower()}{n}'


all_ts = sorted(db['ts_code'].unique())
cal = cal_full[(cal_full >= '2016-01-01') & (cal_full <= '2026-08-31')]
cols, data = [], {}
for c in all_ts:
    s = read_bin(ts2sym(c), 'close')
    if s is not None:
        data[c] = s.reindex(cal)
C = pd.DataFrame(data)  # index=cal, cols=ts_code
print(f'[data] 行情 {C.shape[0]} 天 × {C.shape[1]} 只', flush=True)

# ---------------- 月度组合收益 ----------------
print('[bt] 月度组合 ...', flush=True)
dates = list(month_end)
rows = []
for i in range(len(dates) - 1):
    t, t1 = dates[i], dates[i + 1]
    mv = snap_mv[t].dropna()
    board = snap_board[t]
    universe = set(mv.index)
    main_codes = {c for c in universe if board.get(c) in ('sse_main', 'szse_main')}
    bad = bad_at(t)
    quasi = quasi_at(t) & universe

    # 主板内末20%
    mv_main = mv[[c for c in mv.index if c in main_codes]]
    thr20 = mv_main.quantile(0.20)
    mb_bottom = set(mv_main[mv_main <= thr20].index)
    # 旧微盘域（三板块末10%）
    thr10 = mv.quantile(0.10)
    b10 = set(mv[mv <= thr10].index)

    mb20_clean = (mb_bottom - bad - quasi) & universe
    mb20_all = mb_bottom & universe
    mb_main = main_codes
    mb_main_exbad = main_codes - bad
    mkt_all = universe
    mkt_exbad = universe - bad
    b10_clean = (b10 - bad - quasi) & universe

    c0 = C.loc[t]
    c1 = C.loc[:t1].ffill().iloc[-1]  # 最后可得价（退市用最后价）

    def month_ret(codes):
        codes = [c for c in codes if c in c0.index and c in c1.index]
        if not codes:
            return np.nan, 0
        b = c0.reindex(codes)
        s = c1.reindex(codes)
        r = s / b.where(b > 0) - 1
        r = r.replace([np.inf, -np.inf], np.nan).dropna()
        return (r.mean() if len(r) else np.nan), len(r)

    r_clean, n1 = month_ret(mb20_clean)
    r_all, n2 = month_ret(mb20_all)
    r_main, n3 = month_ret(mb_main)
    r_mainex, n4 = month_ret(mb_main_exbad)
    r_mkt, n5 = month_ret(mkt_all)
    r_mktx, n6 = month_ret(mkt_exbad)
    r_b10, n7 = month_ret(b10_clean)

    rows.append({'t': t, 't1': t1, 'thr20_yi': thr20, 'thr10_yi': thr10,
                 'n_mb20_clean': n1, 'n_mb20_all': n2, 'n_mb_main': n3,
                 'n_mkt': n5, 'n_b10_clean': n7,
                 'st_rate_mb20': len(mb_bottom & bad) / max(len(mb_bottom), 1),
                 'quasi_rate_mb20': len(mb_bottom & quasi) / max(len(mb_bottom), 1),
                 'mv_med_mb20_yi': mv_main[mv_main <= thr20].median(),
                 'overlap_b10': len(mb20_clean & b10_clean),
                 'ret_mb20_clean': r_clean, 'ret_mb20_all': r_all,
                 'ret_mb_main': r_main, 'ret_mb_main_exbad': r_mainex,
                 'ret_mkt': r_mkt, 'ret_mkt_exbad': r_mktx,
                 'ret_b10_clean': r_b10})
    if i % 24 == 0:
        print(f'  {t.date()}: 阈值{thr20:.0f}亿 clean={n1} bottom={n2} main={n3} | '
              f'clean={r_clean:+.1%} mkt={r_mkt:+.1%}', flush=True)

perf = pd.DataFrame(rows)
perf['year'] = perf['t'].dt.year
print(f'[bt] {len(perf)} 个月度区间', flush=True)

# ---------------- 统计 ----------------
RETS = ['ret_mb20_clean', 'ret_mb20_all', 'ret_mb_main', 'ret_mb_main_exbad',
        'ret_mkt', 'ret_mkt_exbad', 'ret_b10_clean']
NAMES = {'ret_mb20_clean': '主板末20%剔ST/准ST', 'ret_mb20_all': '主板末20%(不剔)',
         'ret_mb_main': '主板全池等权', 'ret_mb_main_exbad': '主板全池剔ST',
         'ret_mkt': '全市场等权', 'ret_mkt_exbad': '全市场剔ST',
         'ret_b10_clean': '旧微盘域(三板块末10%)'}

stats = []
navs = {}
for c in RETS:
    r = perf[c].dropna()
    nav = (1 + r).cumprod()
    navs[c] = nav
    years = len(r) / 12
    cagr = nav.iloc[-1] ** (1 / years) - 1
    vol = r.std() * np.sqrt(12)
    dd = nav / nav.cummax() - 1
    mdd = dd.min()
    trough = dd.idxmin()
    stats.append({'portfolio': c, 'name': NAMES[c], 'n_months': len(r),
                  'nav_x': nav.iloc[-1], 'CAGR': cagr, 'vol': vol, 'MDD': mdd,
                  'MDD_trough': str(perf.loc[trough, 't1'].date()) if trough in perf.index else '',
                  'best_month': r.max(), 'worst_month': r.min(),
                  'win_rate': (r > 0).mean()})
st = pd.DataFrame(stats)
st.to_csv(OUT / 'performance_summary.csv', index=False)

# 分年度
yr = perf.groupby('year')[RETS].apply(lambda g: (1 + g).prod() - 1)
yr.to_csv(OUT / 'yearly_returns.csv')

# 超额统计
exc_rows = []
for base in ['ret_mkt', 'ret_mkt_exbad', 'ret_mb_main', 'ret_b10_clean']:
    e = perf['ret_mb20_clean'] - perf[base]
    e = e.dropna()
    exc_rows.append({'vs': NAMES[base], 'mean_monthly': e.mean(),
                     'win_rate': (e > 0).mean(),
                     't_annual': e.mean() / e.std() * np.sqrt(12) if e.std() > 0 else np.nan,
                     'corr': perf['ret_mb20_clean'].corr(perf[base])})
exc = pd.DataFrame(exc_rows)
exc.to_csv(OUT / 'excess_stats.csv', index=False)

# 相关性
corr = perf[RETS].corr()
corr.to_csv(OUT / 'correlation_matrix.csv')

# 最差 5 个月
worst = perf.nsmallest(5, 'ret_mb20_clean')[['t1', 'ret_mb20_clean', 'ret_mkt', 'ret_b10_clean']]
worst.to_csv(OUT / 'worst_months.csv', index=False)

perf.to_csv(OUT / 'monthly_returns.csv', index=False)

# ---------------- 主板内市值十分位梯度 ----------------
print('\n[decile] 主板内市值十分位梯度 ...', flush=True)
dec_rows = []
dec_nav = {k: [] for k in range(1, 11)}
for i in range(len(dates) - 1):
    t, t1 = dates[i], dates[i + 1]
    mv = snap_mv[t].dropna()
    board = snap_board[t]
    main_codes = [c for c in mv.index if board.get(c) in ('sse_main', 'szse_main')]
    mv_main = mv[main_codes]
    if len(mv_main) < 100:
        continue
    rk = mv_main.rank(method='first')
    q = pd.qcut(rk, 10, labels=False) + 1  # 1=最小 ... 10=最大
    c0 = C.loc[t]
    c1 = C.loc[:t1].ffill().iloc[-1]
    for d in range(1, 11):
        codes = mv_main.index[(q == d).values]
        codes = [c for c in codes if c in c0.index and c in c1.index]
        b = c0.reindex(codes)
        s = c1.reindex(codes)
        r = (s / b.where(b > 0) - 1).replace([np.inf, -np.inf], np.nan).dropna()
        dec_nav[d].append(r.mean() if len(r) else np.nan)
dec_nav = pd.DataFrame(dec_nav, index=[dates[i + 1] for i in range(len(dates) - 1) if len(snap_mv[dates[i]].dropna()) >= 100])
for d in range(1, 11):
    r = dec_nav[d].dropna()
    if len(r) == 0:
        continue
    nav = (1 + r).cumprod()
    years = len(r) / 12
    dd = nav / nav.cummax() - 1
    dec_rows.append({'decile': f'D{d}', 'n_months': len(r),
                     'nav_x': nav.iloc[-1], 'CAGR': nav.iloc[-1] ** (1 / years) - 1,
                     'vol': r.std() * np.sqrt(12), 'MDD': dd.min()})
dec = pd.DataFrame(dec_rows)
dec.to_csv(OUT / 'decile_gradient.csv', index=False)

# ---------------- 报告 ----------------
print('\n' + '=' * 96)
print(f'沪深主板末20%域市场表现（{dates[0].date()} -> {dates[-1].date()}，月度调仓、等权、费前）')
print('=' * 96)
show = st[['name', 'n_months', 'nav_x', 'CAGR', 'vol', 'MDD', 'MDD_trough', 'win_rate']].copy()
show['CAGR'] = (show['CAGR'] * 100).round(1)
show['vol'] = (show['vol'] * 100).round(1)
show['MDD'] = (show['MDD'] * 100).round(1)
show['win_rate'] = (show['win_rate'] * 100).round(0)
show['nav_x'] = show['nav_x'].round(2)
print(show.to_string(index=False))

print('\n分年度收益（%）:')
print((yr * 100).round(1).to_string())

print('\n超额统计（主板末20%剔ST/准ST - 基准）:')
ex_show = exc.copy()
ex_show['mean_monthly'] = (ex_show['mean_monthly'] * 100).round(2)
ex_show['win_rate'] = (ex_show['win_rate'] * 100).round(0)
ex_show = ex_show.round(3)
print(ex_show.to_string(index=False))

print('\n最差 5 个月:')
w = worst.copy()
for c in ['ret_mb20_clean', 'ret_mkt', 'ret_b10_clean']:
    w[c] = (w[c] * 100).round(1)
print(w.to_string(index=False))

print('\n主板内市值十分位梯度（D1=最小, D10=最大）:')
d_show = dec.copy()
d_show['CAGR'] = (d_show['CAGR'] * 100).round(1)
d_show['vol'] = (d_show['vol'] * 100).round(1)
d_show['MDD'] = (d_show['MDD'] * 100).round(1)
d_show['nav_x'] = d_show['nav_x'].round(2)
print(d_show.to_string(index=False))

print('\n域特征（中位）:')
for c in ['thr20_yi', 'n_mb20_clean', 'n_mb20_all', 'n_mb_main', 'n_mkt',
          'st_rate_mb20', 'quasi_rate_mb20', 'mv_med_mb20_yi', 'overlap_b10']:
    print(f'  {c:18s} min={perf[c].min():.1f} med={perf[c].median():.1f} max={perf[c].max():.1f}')
print(f'\n落盘: {OUT}')
