#!/usr/bin/env python3
"""Value 11 因子假设检验 v1（协议 value11_dual_arm_protocol_v1，九族收官）。"""
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
OUT = ROOT / 'output/analysis_static/value11_dual_arm_v1'
OUT.mkdir(parents=True, exist_ok=True)

START, END = '2016-01-01', '2026-08-31'

cal_full = pd.DatetimeIndex(pd.read_csv(QLIB_DIR / 'calendars' / 'day.txt', header=None)[0])
cal = cal_full[(cal_full >= START) & (cal_full <= END)]


def sps_ic(a, b):
    return sps.spearmanr(a, b)[0]


def mad_clip(s, k=3.0):
    med = s.median()
    mad = (s - med).abs().median() * 1.4826
    if mad == 0 or np.isnan(mad):
        return s
    return s.clip(med - k * mad, med + k * mad)


def safe_div(a, b):
    return a / b.replace(0, np.nan)


# ---------------- 财务 ----------------
print('[fin] ...', flush=True)
FIN_TOP = ROOT / 'data/external/tushare/a_share_financial_pit_v1/normalized/fina_indicator.csv.gz'
fi = pd.read_csv(FIN_TOP, compression='gzip', low_memory=False,
                 usecols=['ts_code', 'end_date', 'ann_date', 'available_date',
                          'profit_dedt', 'ebitda', 'eps'])
for c in ('end_date', 'available_date'):
    fi[c] = pd.to_datetime(fi[c].astype(str).str.replace('-', '', regex=False), format='%Y%m%d', errors='coerce')
fi = fi.dropna(subset=['available_date']).drop_duplicates(['ts_code', 'end_date', 'available_date'], keep='last')
fi = fi.sort_values(['ts_code', 'end_date'])

from load_financials_extended_v1 import _read_full, _read_recent_3tables, _fill_available, load_financials_extended  # noqa: E402

inc_cols = ['ts_code', 'end_date', 'ann_date', 'available_date', 'total_revenue', 'n_income_attr_p']
income = pd.concat([_read_full('income', inc_cols), _read_recent_3tables('income', inc_cols)], ignore_index=True)
income = _fill_available(income).dropna(subset=['available_date'])
income = income.drop_duplicates(['ts_code', 'end_date', 'available_date'], keep='last').sort_values(['ts_code', 'end_date'])

bs_frames = []
BS_DIR = ROOT / 'data/external/tushare/a_share_financial_pit_v1/balancesheet_v1/normalized'
for batch in sorted(BS_DIR.glob('batch_*')):
    p = batch / 'balancesheet.csv.gz'
    if p.exists():
        bs_frames.append(pd.read_csv(p, compression='gzip',
                                     usecols=['ts_code', 'end_date', 'ann_date', 'available_date',
                                              'total_hldr_eqy_exc_min_int', 'defer_tax_assets']))
bs = pd.concat(bs_frames, ignore_index=True)
bs = _fill_available(bs).dropna(subset=['available_date'])
bs = bs.drop_duplicates(['ts_code', 'end_date', 'available_date'], keep='last').sort_values(['ts_code', 'end_date'])

fin2 = load_financials_extended()

print(f'[fin] income={len(income)} bs={len(bs)}', flush=True)

# ---------------- 域 ----------------
db = pd.read_csv(ROOT / 'data/external/tushare/a_share_daily_basic_pit_v1/normalized/daily_basic.csv.gz',
                 compression='gzip', usecols=['ts_code', 'trade_date', 'total_mv', 'total_share', 'dv_ttm'], dtype={'trade_date': str})
db['dv_ttm'] = pd.to_numeric(db['dv_ttm'], errors='coerce')
db['dt'] = pd.to_datetime(db['trade_date'], format='%Y%m%d')
db = db[~db['ts_code'].str.split('.').str[0].str.startswith(('43', '83', '87', '92', '920'))]
month_end_all = db.groupby(db['dt'].dt.to_period('M'))['dt'].max().sort_values()
snap_mv, snap_ts = {}, {}
for d in month_end_all:
    g = db[db['dt'] == d]
    snap_mv[d] = pd.Series(g['total_mv'].values / 1e4, index=g['ts_code'].values)
    snap_ts[d] = pd.Series(g['total_share'].values, index=g['ts_code'].values)

st = pd.read_csv(ROOT / 'data/external/tushare/a_share_st_status_pit_v1/normalized/st_status_intervals.csv.gz',
                 compression='gzip', parse_dates=['start_date', 'end_date'])
st_start, st_end = st['start_date'].values, st['end_date'].values
st_bad = (st['is_st'] | st['is_delist_phase']).values
st_code = st['ts_code'].values

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

# ---------------- close ----------------
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
print('[data] close ...', flush=True)
C = pd.DataFrame({s: read_bin(s, 'close') for s in symbols if read_bin(s, 'close') is not None}).reindex(cal)
rets_all = {}
ml_bt = [d for d in ml if d >= pd.Timestamp('2021-12-01')]
for i in range(len(ml_bt) - 1):
    e0, e1 = ml_bt[i], ml_bt[i + 1]
    rets_all[e1] = (C.loc[e1] / C.loc[e0] - 1)


def pit_ttm(df, val_col, d):
    sub = df[df['available_date'] <= d].groupby('ts_code').tail(4).reset_index(drop=True)
    sub = sub.sort_values(['ts_code', 'end_date'])
    ttm = sub.groupby('ts_code')[val_col].sum()
    return ttm


def pit_latest(df, cols, d):
    sub = df[df['available_date'] <= d].sort_values(['ts_code', 'end_date', 'available_date']).groupby('ts_code').tail(1).set_index('ts_code')
    return sub[cols]


# ---------------- 双臂 IC + 分组 ----------------
print('[ic] ...', flush=True)
ic_rows, quint_rows = [], []
peg_bad_ratio = []
for i in range(len(ml_bt) - 1):
    d0, d1 = ml_bt[i], ml_bt[i + 1]
    dom = domain_by_month[ml_bt[i]]
    r_all = rets_all[d1].dropna()
    r_dom = r_all[r_all.index.isin(dom)]
    if len(r_dom) < 50:
        continue
    mask = (st_start <= np.datetime64(d0)) & (st_end >= np.datetime64(d0)) & st_bad
    bad_syms = {s.lower() for s in st_code[mask]}
    ts = snap_ts[d0]
    px = pd.Series({c: C.loc[d0].get(f"{c.split('.')[1].lower()}{c.split('.')[0]}", np.nan) for c in ts.index})
    mcap = ts * 1e4 * px  # 元

    ni_ttm = pit_ttm(income, 'n_income_attr_p', d0)
    rev_q = pit_latest(income, ['total_revenue'], d0)['total_revenue']
    pded_ttm = pit_ttm(fi[['ts_code', 'end_date', 'available_date', 'profit_dedt']].dropna(), 'profit_dedt', d0)
    ebitda = pit_latest(fi, ['ebitda'], d0)['ebitda']
    ocf_ttm = pit_ttm(fin2[['ts_code', 'end_date', 'available_date', 'n_cashflow_act']].dropna(), 'n_cashflow_act', d0)
    bs_lat = pit_latest(bs, ['total_hldr_eqy_exc_min_int', 'defer_tax_assets'], d0)
    eqy = bs_lat['total_hldr_eqy_exc_min_int']
    dta = bs_lat['defer_tax_assets']

    F = {}
    F['earnings_to_price'] = safe_div(ni_ttm, mcap)
    F['book_to_market'] = safe_div(eqy + dta.fillna(0), mcap)
    F['earnings_cut_to_market'] = safe_div(pded_ttm, mcap)
    F['ocf_to_market'] = safe_div(ocf_ttm, mcap)
    F['fcf_to_market_proxy'] = F['ocf_to_market']  # 投资流出缺失, 代理口径（协议 §2）
    F['ncf_to_market_proxy'] = F['ocf_to_market']  # 同上
    F['ebitda_to_market'] = safe_div(ebitda, mcap)
    F['sales_to_market'] = mad_clip(safe_div(rev_q, mcap))
    # etp5: 5年滚动净利均值/市值
    inc5_annual = income[(income['available_date'] <= d0) & (income['end_date'].dt.month == 12)].sort_values(['ts_code', 'end_date'])
    np5_mean = inc5_annual.groupby('ts_code')['n_income_attr_p'].rolling(5).mean()
    np5_mean.index = np5_mean.index.get_level_values(0)
    np5_latest = inc5_annual.groupby('ts_code').tail(1).set_index('ts_code')['n_income_attr_p']
    np5 = pd.Series(np5_mean.values, index=np5_latest.index[:len(np5_mean)] if len(np5_mean) == len(np5_latest) else np5_mean.index)
    # 简化: 每票取最新一条 5 年均值
    np5 = np5_mean.groupby(level=0).tail(1)
    np5.index = np5_mean.groupby(level=0).tail(1).index.get_level_values(0)
    F['etp5'] = safe_div(np5.reindex(mcap.index), mcap)
    # dividend_yield_3y_avg: daily_basic dv_ttm 12 个月均值代理（月度快照均值近似 3 年均值的降级口径, 协议已标注）
    dv_lat = db[db['dt'] <= d0].groupby('ts_code').tail(12)
    dv3 = dv_lat.groupby('ts_code')['dv_ttm' if 'dv_ttm' in dv_lat.columns else 'total_mv'].mean()
    if 'dv_ttm' not in dv_lat.columns:
        F['dividend_yield_3y_avg_proxy'] = None
    else:
        F['dividend_yield_3y_avg_proxy'] = dv3
    # pegh5: 5年EPS复合
    eps_seq = fi[fi['available_date'] <= d0].sort_values(['ts_code', 'end_date'])
    eps_y = eps_seq[eps_seq['end_date'].dt.month == 12][['ts_code', 'end_date', 'available_date', 'eps']].dropna()
    eps_y = eps_y.groupby('ts_code').tail(6).reset_index(drop=True).sort_values(['ts_code', 'end_date'])
    eps_y['eps_5y_ago'] = eps_y.groupby('ts_code')['eps'].shift(5)
    eps_y = eps_y.groupby('ts_code').tail(1).set_index('ts_code')
    eps_g = np.sign(eps_y['eps']) * (np.abs(eps_y['eps'] / eps_y['eps_5y_ago'].replace(0, np.nan)) ** 0.2 - 1)
    peg = safe_div(px.reindex(eps_g.index), eps_g * eps_y['eps'])
    peg = peg.replace([np.inf, -np.inf], np.nan)
    bad_ratio = peg.isna().mean()
    peg_bad_ratio.append((str(d0.date()), bad_ratio))
    F['pegh5'] = -peg

    for fn, fser in F.items():
        fser = mad_clip(fser.replace([np.inf, -np.inf], np.nan).dropna())
        if len(fser) < 50:
            continue
        f_q = fser.copy()
        f_q.index = [f"{c.split('.')[1].lower()}{c.split('.')[0]}" for c in f_q.index]
        f_dom = f_q[f_q.index.isin(dom) & ~f_q.index.isin(bad_syms)]
        common = f_dom.index.intersection(r_dom.index)
        if len(common) >= 50:
            ic = sps_ic(f_dom[common], r_dom[common])
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
            ic_a = sps_ic(f_q[common_a], r_all[common_a])
            if pd.notna(ic_a):
                ic_rows.append({'factor': fn, 'arm': 'A_market', 'date': str(d1.date()), 'ic': ic_a})
    if i % 12 == 0:
        print(f'  {d1.date()}', flush=True)

ic_df = pd.DataFrame(ic_rows)
ic_df.to_csv(OUT / 'ic_monthly_long.csv', index=False)
anom = pd.DataFrame(peg_bad_ratio, columns=['date', 'peg_nan_ratio'])
print(f'peg 平均异常率: {anom["peg_nan_ratio"].mean():.1%}')
anom.to_csv(OUT / 'peg_anomaly.csv', index=False)

# 汇总
summary_rows = []
all_factors = sorted(ic_df['factor'].unique())
for fn in all_factors:
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
for fn in all_factors:
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

# 因子互相关（域内）
fnames = all_factors
corr_sum = pd.DataFrame(0.0, index=fnames, columns=fnames)
corr_n = 0
for d0 in ml_bt[::3]:
    if d0 not in domain_by_month:
        continue
    dom = domain_by_month[d0]
    vals = {}
    ts = snap_ts[d0]
    px = pd.Series({c: C.loc[d0].get(f"{c.split('.')[1].lower()}{c.split('.')[0]}", np.nan) for c in ts.index})
    mcap = ts * 1e4 * px
    ni_ttm = pit_ttm(income, 'n_income_attr_p', d0)
    rev_q = pit_latest(income, ['total_revenue'], d0)['total_revenue']
    pded_ttm = pit_ttm(fi[['ts_code', 'end_date', 'available_date', 'profit_dedt']].dropna(), 'profit_dedt', d0)
    ebitda = pit_latest(fi, ['ebitda'], d0)['ebitda']
    ocf_ttm = pit_ttm(fin2[['ts_code', 'end_date', 'available_date', 'n_cashflow_act']].dropna(), 'n_cashflow_act', d0)
    bs_lat = pit_latest(bs, ['total_hldr_eqy_exc_min_int', 'defer_tax_assets'], d0)
    vals['earnings_to_price'] = safe_div(ni_ttm, mcap)
    vals['book_to_market'] = safe_div(bs_lat['total_hldr_eqy_exc_min_int'] + bs_lat['defer_tax_assets'].fillna(0), mcap)
    vals['earnings_cut_to_market'] = safe_div(pded_ttm, mcap)
    vals['ocf_to_market'] = safe_div(ocf_ttm, mcap)
    vals['ebitda_to_market'] = safe_div(ebitda, mcap)
    vals['sales_to_market'] = safe_div(rev_q, mcap)
    vals = {k: mad_clip(v.replace([np.inf, -np.inf], np.nan).dropna()) for k, v in vals.items()}
    vals = {k: v[v.index.isin(dom)] for k, v in vals.items() if len(v) >= 50}
    vals = {k: v.rank(pct=True) for k, v in vals.items()}
    if len(vals) < 2:
        continue
    vdf = pd.DataFrame(vals).dropna()
    if len(vdf) < 50:
        continue
    corr_sum += vdf.corr(method='spearman').abs()
    corr_n += 1
corr_med = corr_sum / max(corr_n, 1)
corr_med.to_csv(OUT / 'corr_matrix.csv')

# ---------------- 判定 ----------------
print('\n=== 判定 ===', flush=True)
sh_all = pd.read_csv(OUT / 'quintile_shape.csv')
dec_rows = []
for fn in all_factors:
    sub = ic_df[(ic_df['factor'] == fn) & (ic_df['arm'] == 'B_domain')]
    sh = sh_all[sh_all['factor'] == fn]
    if sub.empty or sh.empty:
        continue
    ic = sub['ic'].dropna()
    yr = sub.assign(year=sub['date'].str[:4]).groupby('year')['ic'].median()
    years_same = max((yr > 0).sum(), (yr <= 0).sum())
    t_best = max(abs(sh['Q5Q1_t'].iloc[0]), abs(sh['Q4Q1_t'].iloc[0]))
    ic_med = ic.median()
    n_m = int(sh['n_months'].iloc[0])
    if abs(ic_med) >= 0.02 and t_best >= 2 and years_same >= 4:
        if fn in ('earnings_to_price', 'book_to_market'):
            tier = 'mainline_anchor'
        elif corr_med is not None and fn in corr_med.index:
            main_rel = max(abs(corr_med.loc[fn, 'earnings_to_price']), abs(corr_med.loc[fn, 'book_to_market']))
            tier = 'mainline_duplicate' if main_rel >= 0.60 else 'value_increment_candidate'
        else:
            tier = 'value_increment_candidate'
    else:
        tier = 'not_qualified'
    if n_m < 40:
        tier += '_low_sample'
    dec_rows.append({'factor': fn, 'domain_ic_median': ic_med, 't_best': t_best,
                     'years_same_sign': f'{years_same}/{len(yr)}', 'tier': tier})
dec = pd.DataFrame(dec_rows).sort_values('domain_ic_median', key=abs, ascending=False)
dec.to_csv(OUT / 'decision_table.csv', index=False)
print(dec.round(4).to_string(index=False))
A = ic_df[ic_df['arm'] == 'A_market'].groupby('factor')['ic'].median()
for _, r in dec.iterrows():
    a = A.get(r['factor'], np.nan)
    print(f"  全市场IC[{r['factor']}] = {a:+.4f}" if pd.notna(a) else f"  全市场IC[{r['factor']}] = N/A")

final_cands = dec[dec['tier'] == 'value_increment_candidate']['factor'].tolist()
summary = {'protocol': 'research/protocols/value11_dual_arm_protocol_v1.md',
           'n_factors': len(all_factors),
           'final_candidates': final_cands,
           'peg_mean_anomaly_ratio': float(anom['peg_nan_ratio'].mean()),
           'tiers': {t.split('_low_sample')[0]: int((dec['tier'].str.split('_low_sample').str[0] == t.split('_low_sample')[0]).sum()) for t in dec['tier'].unique()},
           'notes': 'fcf/ncf_to_market 用 ocf 代理（投资流出明细缺失）; dividend_yield 用 dv_ttm 均值代理; etp5/pegh5 样本降级'}
(OUT / 'decision.json').write_text(json.dumps(summary, ensure_ascii=False, indent=2) + '\n')
print(json.dumps(summary, ensure_ascii=False))
