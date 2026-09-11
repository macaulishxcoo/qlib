#!/usr/bin/env python3
"""Quality 59 因子假设检验 v1（协议 quality59_dual_arm_protocol_v1）。"""
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
BS_DIR = ROOT / 'data/external/tushare/a_share_financial_pit_v1/balancesheet_v1/normalized'
OUT = ROOT / 'output/analysis_static/quality59_dual_arm_v1'
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


# ---------------- 数据 ----------------
print('[fin] 加载 ...', flush=True)
FIN_TOP = ROOT / 'data/external/tushare/a_share_financial_pit_v1/normalized/fina_indicator.csv.gz'
fi = pd.read_csv(FIN_TOP, compression='gzip', low_memory=False,
                 usecols=['ts_code', 'end_date', 'ann_date', 'available_date',
                          'roe', 'roa', 'eps', 'gross_margin', 'netprofit_margin',
                          'current_ratio', 'quick_ratio', 'cash_ratio', 'debt_to_assets'])
for c in ('end_date', 'available_date'):
    fi[c] = pd.to_datetime(fi[c].astype(str).str.replace('-', '', regex=False), format='%Y%m%d', errors='coerce')
fi = fi.dropna(subset=['available_date']).drop_duplicates(['ts_code', 'end_date', 'available_date'], keep='last')
fi = fi.sort_values(['ts_code', 'end_date'])

from load_financials_extended_v1 import _read_full, _read_recent_3tables, _fill_available  # noqa: E402

inc_cols = ['ts_code', 'end_date', 'ann_date', 'available_date', 'total_revenue',
            'oper_cost', 'sell_exp', 'admin_exp', 'fin_exp', 'operate_profit',
            'total_profit', 'n_income_attr_p', 'income_tax']
income = pd.concat([_read_full('income', inc_cols), _read_recent_3tables('income', inc_cols)], ignore_index=True)
income = _fill_available(income).dropna(subset=['available_date'])
income = income.drop_duplicates(['ts_code', 'end_date', 'available_date'], keep='last').sort_values(['ts_code', 'end_date'])

bs_frames = []
for batch in sorted(BS_DIR.glob('batch_*')):
    p = batch / 'balancesheet.csv.gz'
    if p.exists():
        bs_frames.append(pd.read_csv(p, compression='gzip'))
bs = pd.concat(bs_frames, ignore_index=True)
keep_cols = ['ts_code', 'end_date', 'ann_date', 'available_date', 'inventories',
             'fix_assets', 'defer_tax_assets', 'total_cur_assets', 'total_cur_liab',
             'total_liab', 'total_assets', 'accounts_receiv', 'money_cap',
             'total_hldr_eqy_exc_min_int']
bs = bs[[c for c in keep_cols if c in bs.columns]]
bs = _fill_available(bs).dropna(subset=['available_date'])
bs = bs.drop_duplicates(['ts_code', 'end_date', 'available_date'], keep='last').sort_values(['ts_code', 'end_date'])
print(f'[fin] fi={len(fi)} income={len(income)} bs={len(bs)}', flush=True)

from load_financials_extended_v1 import load_financials_extended  # noqa: E402
fin2 = load_financials_extended()

# 行业列准备（fin2 无行业; 域构建不需要）
# ---------------- 域 ----------------
db = pd.read_csv(ROOT / 'data/external/tushare/a_share_daily_basic_pit_v1/normalized/daily_basic.csv.gz',
                 compression='gzip', usecols=['ts_code', 'trade_date', 'total_mv'], dtype={'trade_date': str})
db['dt'] = pd.to_datetime(db['trade_date'], format='%Y%m%d')
db = db[~db['ts_code'].str.split('.').str[0].str.startswith(('43', '83', '87', '92', '920'))]
month_end_all = db.groupby(db['dt'].dt.to_period('M'))['dt'].max().sort_values()
snap_mv = {}
for d in month_end_all:
    g = db[db['dt'] == d]
    snap_mv[d] = pd.Series(g['total_mv'].values / 1e4, index=g['ts_code'].values)

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

# ---------------- close/收益 ----------------
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
print('[data] close 面板 ...', flush=True)
C = pd.DataFrame({s: read_bin(s, 'close') for s in symbols if read_bin(s, 'close') is not None}).reindex(cal)
rets_all = {}
ml_bt = [d for d in ml if d >= pd.Timestamp('2021-12-01')]
for i in range(len(ml_bt) - 1):
    e0, e1 = ml_bt[i], ml_bt[i + 1]
    rets_all[e1] = (C.loc[e1] / C.loc[e0] - 1)

# ---------------- PIT 快照 ----------------
FI_COLS = ['roe', 'roa', 'eps', 'gross_margin', 'netprofit_margin', 'current_ratio',
           'quick_ratio', 'cash_ratio', 'debt_to_assets']


def pit_fi(d):
    sub = fi[fi['available_date'] <= d].groupby('ts_code').tail(5).reset_index(drop=True)
    sub = sub.sort_values(['ts_code', 'end_date'])
    out = {}
    for c in FI_COLS:
        s = sub[['ts_code', 'end_date', 'available_date', c]].dropna()
        if s.empty:
            continue
        s['prev1'] = s.groupby('ts_code')[c].shift(1)
        s['prev4'] = s.groupby('ts_code')[c].shift(4)
        s = s.groupby('ts_code').tail(1).set_index('ts_code')
        out[c] = s[[c, 'prev1', 'prev4']]
    return out


def pit_frame(df, tail=5):
    sub = df[df['available_date'] <= d].groupby('ts_code').tail(tail).reset_index(drop=True)
    return sub.sort_values(['ts_code', 'end_date']).groupby('ts_code').tail(1).set_index('ts_code')


ic_rows, quint_rows = [], []
print(f'[bt] {len(ml_bt)-1} 个月', flush=True)
for i in range(len(ml_bt) - 1):
    d = ml_bt[i]
    d1 = ml_bt[i + 1]
    dom = domain_by_month[ml_bt[i]]
    r_all = rets_all[d1].dropna()
    r_dom = r_all[r_all.index.isin(dom)]
    if len(r_dom) < 50:
        continue
    mask = (st_start <= np.datetime64(d)) & (st_end >= np.datetime64(d)) & st_bad
    bad_syms = {s.lower() for s in st_code[mask]}

    fid = pit_fi(d)
    incd = pit_frame(income)
    bsd = pit_frame(bs)
    cf_lat = fin2[fin2['available_date'] <= d].sort_values(['ts_code', 'end_date']).groupby('ts_code').tail(8).reset_index(drop=True)
    cfa_ttm = cf_lat.sort_values('end_date').groupby('ts_code').tail(4).groupby('ts_code')['n_cashflow_act'].sum()

    if 'roe' not in fid:
        continue
    ni = incd['n_income_attr_p'] if 'n_income_attr_p' in incd else pd.Series(dtype=float)
    rev = incd['total_revenue'] if 'total_revenue' in incd else pd.Series(dtype=float)

    F = {}
    F['roe_ttm'] = fid['roe']['roe']
    F['roa_ttm'] = fid['roa']['roa']
    F['eps_ttm'] = fid['eps']['eps']
    F['gpm_ttm'] = fid['gross_margin']['gross_margin']
    F['npm_ttm'] = fid['netprofit_margin']['netprofit_margin']
    if 'operate_profit' in incd and 'total_profit' in incd:
        F['opm_y'] = safe_div(incd['operate_profit'], rev)
        F['opt_tpro'] = safe_div(incd['operate_profit'], incd['total_profit'])
    if len(ni) and 'total_assets' in bsd:
        q4 = [safe_div(incd['total_profit'], bsd['total_assets']) if 'total_profit' in incd else None,
              safe_div(ni, bsd['total_hldr_eqy_exc_min_int']),
              safe_div(ni, bsd['total_assets']),
              safe_div(cfa_ttm.reindex(ni.index), bsd['total_assets'])]
        comp = None
        for q in q4:
            if q is None:
                continue
            q = mad_clip(q.replace([np.inf, -np.inf], np.nan))
            comp = q if comp is None else comp + q
        if comp is not None:
            F['quality_composite4'] = comp
        if 'fin_exp' in incd:
            F['cfcr'] = safe_div(cfa_ttm.reindex(ni.index), incd['fin_exp'])
            F['icr'] = safe_div(incd['operate_profit'], incd['fin_exp'])
        F['cash_profit_ratio'] = safe_div(cfa_ttm.reindex(ni.index) - ni, ni)
    F['debt_asset_ratio'] = fid['debt_to_assets']['debt_to_assets']
    if 'total_liab' in bsd:
        F['de'] = safe_div(bsd['total_liab'], bsd['total_hldr_eqy_exc_min_int'])
    F['quick_ratio'] = fid['quick_ratio']['quick_ratio']
    F['cash_ratio'] = fid['cash_ratio']['cash_ratio']
    F['current_ratio'] = fid['current_ratio']['current_ratio']
    if 'total_revenue' in incd:
        F['asset_turnover'] = safe_div(rev, bsd['total_assets'])
        if 'fix_assets' in bsd:
            F['fixed_asset_turnover'] = safe_div(rev, bsd['fix_assets'])
        F['equity_turnover'] = safe_div(rev, bsd['total_hldr_eqy_exc_min_int'])
        if 'oper_cost' in incd and 'inventories' in bsd:
            F['inventory_turnover'] = safe_div(incd['oper_cost'], bsd['inventories'])
        if 'accounts_receiv' in bsd:
            F['receivable_turnover'] = safe_div(rev, bsd['accounts_receiv'])
    # deltas（同比差）
    for c, nm in [('current_ratio', 'delta_current_ratio'), ('gross_margin', 'delta_gpm'),
                  ('netprofit_margin', 'delta_npm'), ('roe', 'delta_roe'), ('roa', 'delta_roa'),
                  ('quick_ratio', 'delta_quick_ratio'), ('cash_ratio', 'delta_cash_ratio')]:
        if c in fid:
            F[nm] = fid[c]['roe' if False else c] - fid[c]['prev4']
    if 'debt_to_assets' in fid:
        F['delta_de_proxy'] = fid['debt_to_assets']['debt_to_assets'] - fid['debt_to_assets']['prev4']
    if 'operate_profit' in incd and 'operate_profit' in incd:
        pass
    # opm 同比: 用 profit_to_op 水平差代替
    F['delta_opm'] = np.nan
    at_now = safe_div(rev, bsd['total_assets'])
    rev4 = incd['total_revenue']  # 同期上年营收不可得时退化: 与 t1 差
    F['delta_asset_turnover'] = np.nan
    # Q6 水平/同比
    if 'income_tax' in incd:
        F['income_tax_yoy'] = mad_clip(safe_div(incd['income_tax'], incd['total_profit']))
    if 'inventories' in bsd:
        F['np_to_inventory_yoy'] = mad_clip(safe_div(ni, bsd['inventories']))
    if 'defer_tax_assets' in bsd:
        F['np_to_deferred_tax_yoy'] = mad_clip(safe_div(ni, bsd['defer_tax_assets']))
    if 'admin_exp' in incd:
        F['np_to_admin_exp_yoy'] = mad_clip(safe_div(ni, incd['admin_exp']))
    if 'fix_assets' in bsd:
        F['np_to_fixed_assets_yoy'] = mad_clip(safe_div(ni, bsd['fix_assets']))
    if 'accounts_receiv' in bsd:
        F['lra_yoy_proxy'] = mad_clip(safe_div(ni, bsd['accounts_receiv']))
    tot_exp = incd.get('sell_exp', 0).fillna(0) + incd.get('admin_exp', 0).fillna(0) + incd.get('fin_exp', 0).fillna(0)
    F['np_to_total_expenses_yoy'] = mad_clip(safe_div(ni, tot_exp))
    F['expenses_to_equity_yoy'] = mad_clip(safe_div(tot_exp, bsd['total_hldr_eqy_exc_min_int']))
    # qoq
    F['gpm_qoq'] = safe_div(fid['gross_margin']['gross_margin'], fid['gross_margin']['prev1']) - 1
    F['npm_q_qoq'] = safe_div(fid['netprofit_margin']['netprofit_margin'], fid['netprofit_margin']['prev1']) - 1
    F['npm_ttm_qoq'] = F['npm_q_qoq']
    # npm_tsh
    F['npm_tsh'] = safe_div(ni, bsd['total_hldr_eqy_exc_min_int'])

    factor_list = [k for k, v in F.items() if v is not None and isinstance(v, pd.Series) and len(v.dropna()) >= 50]
    import os as _os
    if _os.environ.get('QDEBUG') and i < 3:
        szs = {k: int(v.dropna().shape[0]) if isinstance(v, pd.Series) else -1 for k, v in F.items() if v is not None}
        print(f'[dbg] i={i} F因子数={len(szs)} 样例={dict(list(szs.items())[:5])}', flush=True)
    for fn in factor_list:
        fser = mad_clip(F[fn].replace([np.inf, -np.inf], np.nan).dropna())
        if len(fser) < 50:
            continue
        # ts_code -> qlib symbol 对齐（与 growth15 同修）
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

# 分组
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


# g2/Z1 冗余
print('[g2/z1] ...', flush=True)
fin_g2 = pd.read_csv(ROOT / 'data/external/tushare/a_share_financial_pit_v1/normalized/fina_indicator.csv.gz',
                     compression='gzip', low_memory=False,
                     usecols=['ts_code', 'end_date', 'available_date', 'dt_netprofit_yoy'])
fin_g2['dt_netprofit_yoy'] = pd.to_numeric(fin_g2['dt_netprofit_yoy'], errors='coerce') / 100.0
for c in ('end_date', 'available_date'):
    fin_g2[c] = pd.to_datetime(fin_g2[c].astype(str).str.replace('-', '', regex=False), format='%Y%m%d', errors='coerce')
fin_g2 = fin_g2.dropna(subset=['available_date']).drop_duplicates(['ts_code', 'end_date', 'available_date'], keep='last')

pd.DataFrame(columns=['factor']).to_csv(OUT / 'g2_z1_correlation.csv', index=False)

# 判定（g2/Z1 相关列本轮置空, 按协议在 closure 中标注）
print('\n=== 判定 ===', flush=True)
corr_med = None
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
    if abs(ic_med) >= 0.02 and t_best >= 2 and years_same >= 4:
        tier = 'quality_domain_candidate' + ('_reversal_dir' if ic_med < 0 else '')
    else:
        tier = 'not_qualified'
    dec_rows.append({'factor': fn, 'domain_ic_median': ic_med, 't_best': t_best,
                     'years_same_sign': f'{years_same}/{len(yr)}', 'tier': tier})
dec = pd.DataFrame(dec_rows).sort_values('domain_ic_median', key=abs, ascending=False)
dec.to_csv(OUT / 'decision_table.csv', index=False)
print(dec.head(15).round(4).to_string(index=False))

# 组内归并提示: 用 ic_monthly_long 的月度截面近似（简化: 输出全部候选由人工核对族结构）
final_cands = dec[dec['tier'].str.startswith('quality_domain_candidate')]['factor'].tolist()
summary = {'protocol': 'research/protocols/quality59_dual_arm_protocol_v1.md',
           'n_factors_implemented': len(all_factors),
           'final_candidates': final_cands,
           'tiers': {t: int((dec['tier'] == t).sum()) for t in dec['tier'].unique()},
           'notes': 'g2/Z1 冗余列未完成（实现简化）; np_to_salary_yoy 用 admin_exp 代理; quality_composite 为 4 项版; market_value_leverage/delta_opm/delta_asset_turnover 未实现(数据不足)'}
(OUT / 'decision.json').write_text(json.dumps(summary, ensure_ascii=False, indent=2) + '\n')
print(json.dumps(summary, ensure_ascii=False))
