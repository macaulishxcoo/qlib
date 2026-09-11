#!/usr/bin/env python3
"""Size 3 因子假设检验 v1（协议 size3_dual_arm_protocol_v1）。"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import numpy as np
import pandas as pd
from scipy import stats as sps

ROOT = Path('/home/xiaocong/worksapces/qlib')
sys.path.insert(0, str(ROOT / 'scripts'))
QLIB_DIR = Path(os.path.expanduser('~')) / '.qlib/qlib_data/cn_data_2026'
OUT = ROOT / 'output/analysis_static/size3_dual_arm_v1'
OUT.mkdir(parents=True, exist_ok=True)

START, END = '2016-01-01', '2026-08-31'

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

print('[data] 面板 ...', flush=True)
C = pd.DataFrame({s: read_bin(s, 'close') for s in symbols if read_bin(s, 'close') is not None}).reindex(cal)
FAC = pd.DataFrame({s: read_bin(s, 'factor') for s in symbols if read_bin(s, 'factor') is not None}).reindex(cal)
C_UNADJ = C / FAC

db = pd.read_csv(ROOT / 'data/external/tushare/a_share_daily_basic_pit_v1/normalized/daily_basic.csv.gz',
                 compression='gzip', usecols=['ts_code', 'trade_date', 'total_mv', 'total_share', 'float_share'],
                 dtype={'trade_date': str})
db['dt'] = pd.to_datetime(db['trade_date'], format='%Y%m%d')
db = db[~db['ts_code'].str.split('.').str[0].str.startswith(('43', '83', '87', '92', '920'))]
month_end_all = db.groupby(db['dt'].dt.to_period('M'))['dt'].max().sort_values()
snap_mv, snap_ts, snap_fs = {}, {}, {}
for d in month_end_all:
    g = db[db['dt'] == d]
    snap_mv[d] = pd.Series(g['total_mv'].values / 1e4, index=g['ts_code'].values)
    snap_ts[d] = pd.Series(g['total_share'].values, index=g['ts_code'].values)
    snap_fs[d] = pd.Series(g['float_share'].values, index=g['ts_code'].values)

st = pd.read_csv(ROOT / 'data/external/tushare/a_share_st_status_pit_v1/normalized/st_status_intervals.csv.gz',
                 compression='gzip', parse_dates=['start_date', 'end_date'])
st_start, st_end = st['start_date'].values, st['end_date'].values
st_bad = (st['is_st'] | st['is_delist_phase']).values
st_code = st['ts_code'].values

from load_financials_extended_v1 import load_financials_extended  # noqa: E402
fin2 = load_financials_extended()
inc0 = fin2[['ts_code', 'end_date', 'available_date', 'n_income_attr_p']].copy()
inc0 = inc0[inc0['end_date'].dt.month == 12]
inc0 = inc0.sort_values(['ts_code', 'end_date', 'available_date']).drop_duplicates(['ts_code', 'end_date'], keep='last').dropna(subset=['n_income_attr_p'])
inc0['loss'] = inc0['n_income_attr_p'] < 0
bpsdf = fin2[['ts_code', 'end_date', 'available_date', 'bps']].copy()
bpsdf = bpsdf.sort_values(['ts_code', 'end_date', 'available_date']).drop_duplicates(['ts_code', 'end_date'], keep='last').dropna(subset=['bps'])


def quasi_at(t):
    t64 = np.datetime64(t)
    sub = inc0[inc0['available_date'] <= t64].sort_values(['ts_code', 'end_date'])
    last2 = sub.groupby('ts_code').tail(2)
    g = last2.groupby('ts_code')['loss'].agg(['count', 'sum'])
    two = set(g[(g['count'] >= 2) & (g['sum'] >= 2)].index)
    sb = bpsdf[bpsdf['available_date'] <= t64].sort_values(['ts_code', 'end_date']).groupby('ts_code').tail(1)
    neg = set(sb[sb['bps'] < 0]['ts_code'])
    return two | neg


def sym_of(c):
    n, e = c.split('.')
    return f'{e.lower()}{n}'


domain_by_month = {}
for d in month_end_all:
    if not (pd.Timestamp('2021-12-01') <= d <= pd.Timestamp(END)):
        continue
    mv = snap_mv[d]
    universe = set(mv.dropna().index)
    thr = mv.quantile(0.10)
    bottom = set(mv[mv <= thr].index)
    mask = (st_start <= np.datetime64(d)) & (st_end >= np.datetime64(d)) & st_bad
    bad = set(st_code[mask])
    quasi = quasi_at(d) & universe
    domain_by_month[d] = {sym_of(c) for c in (bottom - bad - quasi) & universe}
ml = [d for d in sorted(domain_by_month) if d >= pd.Timestamp('2021-12-01')]

rets_all = {}
ml_bt = [d for d in ml if d >= pd.Timestamp('2021-12-01')]
for i in range(len(ml_bt) - 1):
    e0, e1 = ml_bt[i], ml_bt[i + 1]
    rets_all[e1] = (C.loc[e1] / C.loc[e0] - 1)

# ---------------- 双臂 IC + 分组 ----------------
print('[ic] ...', flush=True)
ic_rows, quint_rows = [], []
for i in range(len(ml_bt) - 1):
    d0, d1 = ml_bt[i], ml_bt[i + 1]
    dom = domain_by_month[ml_bt[i]]
    r_all = rets_all[d1].dropna()
    r_dom = r_all[r_all.index.isin(dom)]
    if len(r_dom) < 50:
        continue
    mask = (st_start <= np.datetime64(d0)) & (st_end >= np.datetime64(d0)) & st_bad
    bad_syms = {s.lower() for s in st_code[mask]}
    ts = snap_ts[d0] if d0 in snap_ts else snap_ts[[x for x in snap_ts if x <= d0][-1]]
    fs = snap_fs[d0] if d0 in snap_fs else snap_fs[[x for x in snap_fs if x <= d0][-1]]

    # 因子（全市场截面, ts_code 索引 -> qlib symbol）
    cap_total = (ts * 1e4) * C_UNADJ.loc[d0].reindex([f"{c[2:]}.{c[:2].upper()}" for c in []] if False else ts.index).map(
        dict(zip([f"{c.split('.')[1].lower()}{c.split('.')[0]}" for c in ts.index],
                 [C_UNADJ.loc[d0].get(f"{c.split('.')[1].lower()}{c.split('.')[0]}", np.nan) for c in ts.index])))
    # 简化：直接用 ts 索引上拼接未复权价
    px = pd.Series({c: C_UNADJ.loc[d0].get(f"{c.split('.')[1].lower()}{c.split('.')[0]}", np.nan) for c in ts.index})
    size = -np.log(ts * 1e4 * px / 1e6).replace([np.inf, -np.inf], np.nan).dropna()
    float_px = pd.Series({c: C_UNADJ.loc[d0].get(f"{c.split('.')[1].lower()}{c.split('.')[0]}", np.nan) for c in fs.index})
    fsize = -np.log(fs * 1e4 * float_px / 1e6).replace([np.inf, -np.inf], np.nan).dropna()
    # nl_size: size^3 ~ size 截面 OLS 残差
    s3 = size ** 3
    X = np.column_stack([np.ones(len(size)), size.values])
    beta, *_ = np.linalg.lstsq(X, s3.values, rcond=None)
    nl = pd.Series(s3.values - X @ beta, index=size.index)

    factors = {'size': size, 'float_size': fsize, 'nl_size': nl}
    for fn, fser in factors.items():
        fser = fser.dropna()
        if len(fser) < 50:
            continue
        # ts_code -> qlib symbol
        f_q = fser.copy()
        f_q.index = [f"{c.split('.')[1].lower()}{c.split('.')[0]}" for c in f_q.index]
        f_dom = f_q[f_q.index.isin(dom) & ~f_q.index.isin(bad_syms)]
        common = f_dom.index.intersection(r_dom.index)
        if len(common) >= 50:
            ic = sps.spearmanr(f_dom[common], r_dom[common])[0]
            if pd.notna(ic):
                ic_rows.append({'factor': fn, 'arm': 'B_domain', 'date': str(d1.date()), 'ic': ic})
                try:
                    q = pd.qcut(f_dom[common].rank(method='first'), 5, labels=False)
                except ValueError:
                    q = None
                if q is not None:
                    for grp in range(5):
                        sel = common[q == grp]
                        quint_rows.append({'factor': fn, 'exit': str(d1.date()), 'group': f'Q{grp+1}',
                                           'ret': float(r_dom[sel].mean())})
        common_a = f_q.index.intersection(r_all.index)
        if len(common_a) >= 200:
            ic_a = sps.spearmanr(f_q[common_a], r_all[common_a])[0]
            if pd.notna(ic_a):
                ic_rows.append({'factor': fn, 'arm': 'A_market', 'date': str(d1.date()), 'ic': ic_a})
    if i % 12 == 0:
        print(f'  {d1.date()}', flush=True)

ic_df = pd.DataFrame(ic_rows)
ic_df.to_csv(OUT / 'ic_monthly_long.csv', index=False)

summary_rows = []
for fn in ['size', 'float_size', 'nl_size']:
    for arm in ['B_domain', 'A_market']:
        sub = ic_df[(ic_df['factor'] == fn) & (ic_df['arm'] == arm)]
        if sub.empty:
            continue
        ic = sub['ic'].dropna()
        yr = sub.assign(year=sub['date'].str[:4]).groupby('year')['ic'].median()
        summary_rows.append({'factor': fn, 'arm': arm, 'n_months': len(ic),
                             'ic_median': ic.median(),
                             'ic_ir': ic.median() / (ic.std() + 1e-12) * np.sqrt(12) if ic.std() > 0 else np.nan,
                             'ic_positive_ratio': (ic > 0).mean(),
                             'yearly': {int(y): round(v, 4) for y, v in yr.items()}})
pd.DataFrame(summary_rows).to_csv(OUT / 'ic_summary.csv', index=False)

qdf = pd.DataFrame(quint_rows)
shape_rows = []
for fn in ['size', 'float_size', 'nl_size']:
    sub = qdf[qdf['factor'] == fn]
    if sub.empty:
        continue
    piv = sub.pivot_table(index='exit', columns='group', values='ret')[['Q1', 'Q2', 'Q3', 'Q4', 'Q5']].dropna()
    if len(piv) < 10:
        continue
    s51 = piv['Q5'] - piv['Q1']
    s41 = piv['Q4'] - piv['Q1']
    t51, _ = sps.ttest_1samp(s51, 0)
    t41, _ = sps.ttest_1samp(s41, 0)
    yr = s51.groupby(s51.index.str[:4]).mean()
    shape_rows.append({'factor': fn, 'n_months': len(piv),
                       'Q1': piv['Q1'].mean(), 'Q5': piv['Q5'].mean(),
                       'Q5Q1_monthly': s51.mean(), 'Q5Q1_t': t51,
                       'Q4Q1_monthly': s41.mean(), 'Q4Q1_t': t41,
                       'years_pos_51': int((yr > 0).sum()), 'years_total': len(yr)})
pd.DataFrame(shape_rows).to_csv(OUT / 'quintile_shape.csv', index=False)

# ---------------- 判定 ----------------
print('\n=== 判定 ===', flush=True)
dec_rows = []
for fn in ['size', 'float_size', 'nl_size']:
    sub = ic_df[(ic_df['factor'] == fn) & (ic_df['arm'] == 'B_domain')]
    sh = pd.read_csv(OUT / 'quintile_shape.csv')
    sh = sh[sh['factor'] == fn]
    if sub.empty or sh.empty:
        continue
    ic = sub['ic'].dropna()
    yr = sub.assign(year=sub['date'].str[:4]).groupby('year')['ic'].median()
    years_same = max((yr > 0).sum(), (yr <= 0).sum())
    t_best = max(abs(sh['Q5Q1_t'].iloc[0]), abs(sh['Q4Q1_t'].iloc[0]))
    ic_med = ic.median()
    if abs(ic_med) >= 0.02 and t_best >= 2 and years_same >= 4:
        tier = ('size_beta_residue' if fn in ('size', 'float_size')
                else 'size_nl_candidate')
    else:
        tier = 'not_qualified'
    dec_rows.append({'factor': fn, 'domain_ic_median': ic_med, 't_best': t_best,
                     'years_same_sign': f'{years_same}/{len(yr)}', 'tier': tier})
dec = pd.DataFrame(dec_rows).sort_values('domain_ic_median', key=abs, ascending=False)
dec.to_csv(OUT / 'decision_table.csv', index=False)
print(dec.round(4).to_string(index=False))
A = ic_df[ic_df['arm'] == 'A_market'].groupby('factor')['ic'].median()
for _, r in dec.iterrows():
    a = A.get(r['factor'], np.nan)
    print(f"  全市场IC[{r['factor']}] = {a:+.4f}" if pd.notna(a) else f"  全市场IC[{r['factor']}] = N/A")

final_cands = dec[dec['tier'] == 'size_nl_candidate']['factor'].tolist()
summary = {'protocol': 'research/protocols/size3_dual_arm_protocol_v1.md',
           'n_factors': 3,
           'final_candidates': final_cands,
           'tiers': {t: int((dec['tier'] == t).sum()) for t in dec['tier'].unique()}}
(OUT / 'decision.json').write_text(json.dumps(summary, ensure_ascii=False, indent=2) + '\n')
print(json.dumps(summary, ensure_ascii=False))
