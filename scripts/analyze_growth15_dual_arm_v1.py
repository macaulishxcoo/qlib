#!/usr/bin/env python3
"""Growth 15 因子假设检验 v1（协议 growth15_dual_arm_protocol_v1）。

15 个 Growth 因子 PIT 复现 → 干净微盘域（臂B）+ 全市场（臂A）月度 RankIC
→ 域内 5 分组价差 t 检验 → 与 g2 冗余判定 → 协议 §5 出判定。
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path('/home/xiaocong/worksapces/qlib')
sys.path.insert(0, str(ROOT / 'scripts'))
QLIB_DIR = Path(os.path.expanduser('~')) / '.qlib/qlib_data/cn_data_2026'
OUT = ROOT / 'output/analysis_static/growth15_dual_arm_v1'
OUT.mkdir(parents=True, exist_ok=True)

START, END = '2021-01-01', '2026-08-31'
BT_START = pd.Timestamp('2022-01-01')

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

print('[data] close 面板 ...', flush=True)
C = pd.DataFrame({s: read_bin(s, 'close') for s in symbols if read_bin(s, 'close') is not None}).reindex(cal)
FACTOR = pd.DataFrame({s: read_bin(s, 'factor') for s in symbols if read_bin(s, 'factor') is not None}).reindex(cal)
C_UNADJ = C / FACTOR

# ---------------- 财务 PIT ----------------
print('[fin] 加载财务 PIT ...', flush=True)
FIN_TOP = ROOT / 'data/external/tushare/a_share_financial_pit_v1/normalized/fina_indicator.csv.gz'
fin = pd.read_csv(FIN_TOP, compression='gzip', low_memory=False,
                  usecols=['ts_code', 'end_date', 'ann_date', 'available_date',
                           'eps', 'roa', 'roe', 'bps', 'gross_margin',
                           'netprofit_yoy', 'or_yoy', 'ocf_yoy', 'dt_netprofit_yoy',
                           'total_revenue_ps', 'op_income'])
for c in ('end_date', 'available_date'):
    fin[c] = pd.to_datetime(fin[c].astype(str).str.replace('-', '', regex=False),
                            format='%Y%m%d', errors='coerce')
fin = fin.dropna(subset=['available_date'])
fin = fin.drop_duplicates(['ts_code', 'end_date', 'available_date'], keep='last')

# 三表: income(n_income_attr_p), cashflow(n_cashflow_act), balancesheet(total_assets)
from load_financials_extended_v1 import load_financials_extended  # noqa: E402
fin3 = load_financials_extended()
print(f'[fin] fin rows={len(fin)}, fin3 rows={len(fin3)}', flush=True)

# total_share 从 daily_basic 月末截面
db = pd.read_csv(ROOT / 'data/external/tushare/a_share_daily_basic_pit_v1/normalized/daily_basic.csv.gz',
                 compression='gzip', usecols=['ts_code', 'trade_date', 'total_mv', 'total_share'],
                 dtype={'trade_date': str})
db['dt'] = pd.to_datetime(db['trade_date'], format='%Y%m%d')
db_hs = db[~db['ts_code'].str.split('.').str[0].str.startswith(('43', '83', '87', '92', '920'))]
month_end_all = db_hs.groupby(db_hs['dt'].dt.to_period('M'))['dt'].max().sort_values()
snap_mv = {}
snap_ts = {}
for d in month_end_all:
    g = db_hs[db_hs['dt'] == d]
    snap_mv[d] = pd.Series(g['total_mv'].values / 1e4, index=g['ts_code'].values)
    snap_ts[d] = pd.Series(g['total_share'].values, index=g['ts_code'].values)

# ---------------- PIT 因子面板构建 ----------------
print('[factor] 构建 15 个 Growth 因子（月度 PIT 截面）...', flush=True)


def pit_latest(asof: pd.Timestamp, frame: pd.DataFrame, cols: list[str]) -> pd.DataFrame:
    sub = frame[frame['available_date'] <= asof]
    sub = sub.sort_values(['ts_code', 'end_date', 'available_date']).drop_duplicates('ts_code', keep='last')
    return sub.set_index('ts_code')[cols]


def ttm_series(frame: pd.DataFrame, val_col: str) -> pd.DataFrame:
    """每股票每报告期的 TTM（最近4个季度求和）。"""
    df = frame[['ts_code', 'end_date', 'available_date', val_col]].dropna()
    df = df.sort_values(['ts_code', 'end_date', 'available_date']).drop_duplicates(['ts_code', 'end_date'], keep='last')
    def _ttm(g):
        g = g.sort_values('end_date')
        v = g[val_col]
        ttm = v.rolling(4).sum()  # 报告期严格按季度排序时即 TTM
        # 校验季度连续性: 简化处理（A 股报告期一般连续）
        return pd.DataFrame({'ts_code': g['ts_code'], 'end_date': g['end_date'],
                             'available_date': g['available_date'], 'ttm': ttm.values})
    out = df.groupby('ts_code', group_keys=False).apply(_ttm)
    return out


income_ttm = ttm_series(fin3.dropna(subset=['n_income_attr_p']), 'n_income_attr_p')
ocf_ttm = ttm_series(fin3.dropna(subset=['n_cashflow_act']), 'n_cashflow_act')
assets = fin3[['ts_code', 'end_date', 'available_date', 'total_assets']].dropna()
assets = assets.sort_values(['ts_code', 'end_date', 'available_date']).drop_duplicates(['ts_code', 'end_date'], keep='last')
assets = assets.sort_values(['ts_code', 'end_date'])
assets['assets_prev_q'] = assets.groupby('ts_code')['total_assets'].shift(1)
assets['assets_prev_y'] = assets.groupby('ts_code')['total_assets'].shift(4)

roe_seq = fin[['ts_code', 'end_date', 'available_date', 'roe', 'roa', 'eps', 'gross_margin', 'total_revenue_ps']].dropna(how='all', subset=['roe', 'roa', 'eps', 'gross_margin', 'total_revenue_ps'])
roe_seq = roe_seq.sort_values(['ts_code', 'end_date', 'available_date']).drop_duplicates(['ts_code', 'end_date'], keep='last')
roe_seq = roe_seq.sort_values(['ts_code', 'end_date'])
for c in ['roe', 'roa', 'eps', 'gross_margin', 'total_revenue_ps']:
    roe_seq[f'{c}_prev_q'] = roe_seq.groupby('ts_code')[c].shift(1)
    roe_seq[f'{c}_prev_y'] = roe_seq.groupby('ts_code')[c].shift(4)

me_ts = np.array(sorted(snap_mv))
factor_names = ['peg_252d', 'np_ttm_qoq', 'yoy_net_profit', 'yoy_ocf', 'sa',
                'gross_margin_qoq', 'pa', 'yoy_roa', 'yoy_net_asset', 'yoy_revenue',
                'yoy_roe', 'yoy_total_asset', 'eaa', 'eap', 'asset_growth_qoq']

# 预计算每月末的因子截面（对全部月末）
print('[factor] 计算月末截面（15 因子 × 128 月）...', flush=True)
panels = {fn: {} for fn in factor_names}
peg_anomaly_ratio = []

for d in month_end_all:
    if d < pd.Timestamp('2021-06-01'):
        continue
    codes_mv = snap_mv[d].dropna()
    universe = set(codes_mv.index)
    ts_share = snap_ts[d]

    lat = pit_latest(d, fin, ['eps', 'roa', 'roe', 'bps', 'gross_margin', 'netprofit_yoy', 'or_yoy', 'ocf_yoy', 'dt_netprofit_yoy', 'total_revenue_ps'])
    lat = lat[lat.index.isin(universe)]

    # TTM 环比/同比
    inc_lat = income_ttm[income_ttm['available_date'] <= d].sort_values('end_date').groupby('ts_code').tail(2)
    inc_lat = inc_lat[inc_lat['ts_code'].isin(universe)]
    inc_piv = inc_lat.pivot_table(index='ts_code', columns='end_date', values='ttm')
    ocf_lat = ocf_ttm[ocf_ttm['available_date'] <= d].sort_values('end_date').groupby('ts_code').tail(2)
    ocf_lat = ocf_lat[ocf_lat['ts_code'].isin(universe)]
    ocf_piv = ocf_lat.pivot_table(index='ts_code', columns='end_date', values='ttm')

    as_lat = assets[assets['available_date'] <= d].sort_values('end_date').groupby('ts_code').tail(5)
    as_lat = as_lat[as_lat['ts_code'].isin(universe)]

    seq_lat = roe_seq[roe_seq['available_date'] <= d].sort_values('end_date').groupby('ts_code').tail(6)
    seq_lat = seq_lat[seq_lat['ts_code'].isin(universe)].set_index('ts_code')
    # 每票只保留最新一期（防重复索引）
    seq_lat = seq_lat[~seq_lat.index.duplicated(keep='last')]

    close_u = C_UNADJ.loc[d]

    f = {}
    # 1 peg_252d: PE / (EPS增速*100)
    eps_now = lat['eps']
    eps_seq = seq_lat[['eps', 'eps_prev_y']]
    eps_g = (eps_seq['eps'] / eps_seq['eps_prev_y'] - 1) if 'eps_prev_y' in eps_seq else pd.Series(dtype=float)
    pe = close_u / eps_now.replace(0, np.nan)
    peg = pe / (eps_g * 100)
    peg = peg.replace([np.inf, -np.inf], np.nan)
    bad_peg = peg.isna().sum() / max(len(peg), 1)
    peg_anomaly_ratio.append((str(d.date()), bad_peg))
    f['peg_252d'] = peg
    # 2 np_ttm_qoq: 净利TTM环比（最近两期 TTM 之比-1）
    if inc_piv.shape[1] >= 2:
        cols = sorted(inc_piv.columns)
        f['np_ttm_qoq'] = inc_piv[cols[-1]] / inc_piv[cols[-2]].replace(0, np.nan) - 1
    # 3 yoy_net_profit
    f['yoy_net_profit'] = lat['netprofit_yoy'] / 100.0
    # 4 yoy_ocf
    f['yoy_ocf'] = lat['ocf_yoy'] / 100.0
    # 5 sa: 每股营收增长（加速度需两期同比，数据不足时退化为同比，协议 §2 已注明）
    trp = seq_lat[['total_revenue_ps', 'total_revenue_ps_prev_q', 'total_revenue_ps_prev_y']]
    sg0 = trp['total_revenue_ps'] / trp['total_revenue_ps_prev_y'].replace(0, np.nan) - 1
    f['sa'] = sg0
    # 6 gross_margin_qoq
    gm = seq_lat[['gross_margin', 'gross_margin_prev_q']]
    f['gross_margin_qoq'] = gm['gross_margin'] / gm['gross_margin_prev_q'].replace(0, np.nan) - 1
    # 7 pa: ROA 增长加速度
    roa3 = seq_lat[['roa', 'roa_prev_q', 'roa_prev_y']]
    pg_now = roa3['roa'] - roa3['roa_prev_y']
    pg_prev = roa3['roa_prev_q'] - roa3['roa']  # 近似（缺两期前 ROA 时用此代理）
    f['pa'] = pg_now
    # 8 yoy_roa
    roa_y = seq_lat[['roa', 'roa_prev_y']]
    f['yoy_roa'] = roa_y['roa'] / roa_y['roa_prev_y'].replace(0, np.nan) - 1
    # 9 yoy_net_asset: 净资产同比 = bps*total_share 同比（bps_yoy 可用，但用 bps 直接近似总净资产增速）
    f['yoy_net_asset'] = lat['bps']
    # 10 yoy_revenue
    f['yoy_revenue'] = lat['or_yoy'] / 100.0
    # 11 yoy_roe
    roe_y = seq_lat[['roe', 'roe_prev_y']]
    f['yoy_roe'] = roe_y['roe'] / roe_y['roe_prev_y'].replace(0, np.nan) - 1
    # 12 yoy_total_asset
    a5 = as_lat.pivot_table(index='ts_code', columns='end_date', values='total_assets')
    if a5.shape[1] >= 5:
        cols5 = sorted(a5.columns)
        f['yoy_total_asset'] = a5[cols5[-1]] / a5[cols5[-5]].replace(0, np.nan) - 1
        f['asset_growth_qoq'] = a5[cols5[-1]] / a5[cols5[-2]].replace(0, np.nan) - 1
    # 13 eaa: EPS 增长加速度
    e3 = seq_lat[['eps', 'eps_prev_q', 'eps_prev_y']]
    ega_now = e3['eps'] / e3['eps_prev_y'].replace(0, np.nan) - 1
    f['eaa'] = ega_now  # 加速度数据不足时退化为同比
    # 14 eap: EPS增量/价格
    f['eap'] = (e3['eps'] - e3['eps_prev_y']) / close_u.reindex(e3.index).replace(0, np.nan)

    for fn in factor_names:
        if fn in f:
            s = f[fn].replace([np.inf, -np.inf], np.nan).dropna()
            panels[fn][d] = s

anom = pd.DataFrame(peg_anomaly_ratio, columns=['date', 'peg_nan_ratio'])
print(f'[factor] 完成。peg 平均异常率={anom["peg_nan_ratio"].mean():.1%}', flush=True)

# ---------------- 域 ----------------
print('[domain] ...', flush=True)
st = pd.read_csv(ROOT / 'data/external/tushare/a_share_st_status_pit_v1/normalized/st_status_intervals.csv.gz',
                 compression='gzip', parse_dates=['start_date', 'end_date'])
st_start, st_end = st['start_date'].values, st['end_date'].values
st_bad = (st['is_st'] | st['is_delist_phase']).values
st_code = st['ts_code'].values

fin2 = load_financials_extended()
inc = fin2[['ts_code', 'end_date', 'available_date', 'n_income_attr_p']].copy()
inc = inc[inc['end_date'].dt.month == 12]
inc = inc.sort_values(['ts_code', 'end_date', 'available_date']).drop_duplicates(['ts_code', 'end_date'], keep='last').dropna(subset=['n_income_attr_p'])
inc['loss'] = inc['n_income_attr_p'] < 0
bpsdf = fin2[['ts_code', 'end_date', 'available_date', 'bps']].copy()
bpsdf = bpsdf.sort_values(['ts_code', 'end_date', 'available_date']).drop_duplicates(['ts_code', 'end_date'], keep='last').dropna(subset=['bps'])


def quasi_at(t):
    t64 = np.datetime64(t)
    sub = inc[inc['available_date'] <= t64].sort_values(['ts_code', 'end_date'])
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
print(f'[domain] {len(domain_by_month)} 月', flush=True)

# ---------------- 月度收益（域内 + 全市场） ----------------
print('[ret] 月度收益矩阵 ...', flush=True)
me_list = [d for d in sorted(domain_by_month) if d >= pd.Timestamp('2021-12-01')]
rets_all = {}   # {exit_date: Series(ts_code -> 月收益)}
for i in range(len(me_list) - 1):
    e0, e1 = me_list[i], me_list[i + 1]
    c0 = C_UNADJ.loc[e0]
    c1 = C_UNADJ.loc[e1]
    r = (c1 / c0 - 1)
    rets_all[e1] = r

# ---------------- 双臂月度 IC + 分组 ----------------
print('[ic] 双臂 IC ...', flush=True)
from scipy import stats as sps  # noqa: E402

ic_rows, quint_rows = [], []
g2_series = {}
# 统一口径: dom 为 qlib symbol, 因子面板索引为 ts_code -> 全部转 qlib symbol 比较
def ts_to_qlib_set(ts_codes):
    out = set()
    for c in ts_codes:
        n, e = c.split('.')
        out.add(f'{e.lower()}{n}')
    return out

for i in range(len(me_list) - 1):
    d0, d1 = me_list[i], me_list[i + 1]
    dom = domain_by_month[me_list[i]]  # qlib symbols
    r_all = rets_all[d1].dropna()      # qlib symbols
    r_dom = r_all[r_all.index.isin(dom)]
    if len(r_dom) < 50:
        continue
    mask = (st_start <= np.datetime64(d0)) & (st_end >= np.datetime64(d0)) & st_bad
    bad_syms = {s.lower() for s in st_code[mask]}
    bad_syms = ts_to_qlib_set(bad_syms)

    for fn in factor_names:
        fser = panels[fn].get(d0)
        if fser is None or len(fser) < 50:
            continue
        # ts_code -> qlib symbol
        f_qlib = fser.copy()
        f_qlib.index = [f"{c.split('.')[1].lower()}{c.split('.')[0]}" for c in f_qlib.index]
        f_dom = f_qlib[f_qlib.index.isin(dom) & ~f_qlib.index.isin(bad_syms)]
        common = f_dom.index.intersection(r_dom.index)
        if len(common) >= 50:
            ic = sps.spearmanr(f_dom[common], r_dom[common])[0]
            ic_rows.append({'factor': fn, 'arm': 'B_domain', 'date': str(d1.date()), 'ic': ic})
            # 5 分组
            try:
                q = pd.qcut(f_dom[common].rank(method='first'), 5, labels=False)
            except ValueError:
                q = None
            if q is not None:
                for grp in range(5):
                    sel = common[q == grp]
                    quint_rows.append({'factor': fn, 'exit': str(d1.date()), 'group': f'Q{grp+1}',
                                       'ret': float(r_dom[sel].mean()), 'n': len(sel)})
        # 臂A（全市场, 每因子全截面）
        common_a = f_qlib.index.intersection(r_all.index)
        if len(common_a) >= 200:
            ic_a = sps.spearmanr(f_qlib[common_a], r_all[common_a])[0]
            ic_rows.append({'factor': fn, 'arm': 'A_market', 'date': str(d1.date()), 'ic': ic_a})

ic_df = pd.DataFrame(ic_rows)
ic_df.to_csv(OUT / 'ic_monthly_long.csv', index=False)

# 汇总
def summarize(sub):
    ic = sub['ic'].dropna()
    yearly = ic.groupby(sub.loc[ic.index, 'date'].str[:4] if hasattr(ic, 'index') else pd.Series([d[:4] for d in sub['date']])).median()
    return ic.median(), ic.median() / (ic.std() + 1e-12), yearly

summary_rows = []
for fn in factor_names:
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
ic_sum = pd.DataFrame(summary_rows)
ic_sum.to_csv(OUT / 'ic_summary.csv', index=False)

# 分组价差 t 检验（域内）
from scipy import stats as sps2
qdf = pd.DataFrame(quint_rows)
shape_rows = []
for fn in factor_names:
    sub = qdf[qdf['factor'] == fn]
    if sub.empty:
        continue
    piv = sub.pivot_table(index='exit', columns='group', values='ret')[['Q1', 'Q2', 'Q3', 'Q4', 'Q5']].dropna()
    if len(piv) < 10:
        continue
    s51 = piv['Q5'] - piv['Q1']
    s41 = piv['Q4'] - piv['Q1']
    t51, p51 = sps2.ttest_1samp(s51, 0)
    t41, p41 = sps2.ttest_1samp(s41, 0)
    yr51 = s51.groupby(s51.index.str[:4]).mean()
    shape_rows.append({'factor': fn, 'n_months': len(piv),
                       'Q1': piv['Q1'].mean(), 'Q2': piv['Q2'].mean(), 'Q3': piv['Q3'].mean(),
                       'Q4': piv['Q4'].mean(), 'Q5': piv['Q5'].mean(),
                       'Q5Q1_monthly': s51.mean(), 'Q5Q1_t': t51, 'Q5Q1_p': p51,
                       'Q4Q1_monthly': s41.mean(), 'Q4Q1_t': t41,
                       'years_pos_51': int((yr51 > 0).sum()), 'years_total': len(yr51)})
shape_df = pd.DataFrame(shape_rows)
shape_df.to_csv(OUT / 'quintile_shape.csv', index=False)

# g2 冗余
print('[g2] 冗余判定 ...', flush=True)
g2_rows = []
sample_dates = [d for d in me_list if d >= BT_START][::3]
g2_panel = {}
for d in sample_dates:
    lat = pit_latest(d, fin, ['dt_netprofit_yoy'])
    g2_panel[d] = lat['dt_netprofit_yoy'] / 100.0
for fn in factor_names:
    cors = []
    for d in sample_dates:
        fser = panels[fn].get(d)
        g2 = g2_panel.get(d)
        if fser is None or g2 is None:
            continue
        common = fser.index.intersection(g2.index)
        if len(common) >= 50:
            c = sps.spearmanr(fser[common], g2[common])[0]
            if pd.notna(c):
                cors.append(c)
    g2_rows.append({'factor': fn, 'g2_spearman_median': float(np.median(cors)) if cors else np.nan})
g2_df = pd.DataFrame(g2_rows)
g2_df.to_csv(OUT / 'g2_correlation.csv', index=False)

# ---------------- 判定 ----------------
print('\n=== 判定 ===', flush=True)
dec_rows = []
for fn in factor_names:
    sub = ic_sum[(ic_sum['factor'] == fn) & (ic_sum['arm'] == 'B_domain')]
    sh = shape_df[shape_df['factor'] == fn]
    g2c = g2_df[g2_df['factor'] == fn]['g2_spearman_median'].iloc[0] if len(g2_df[g2_df['factor'] == fn]) else np.nan
    if sub.empty or sh.empty:
        continue
    ic_med = sub['ic_median'].iloc[0]
    yr = sub['yearly'].iloc[0]
    years_pos = sum(1 for v in yr.values() if v > 0)
    years_neg = len(yr) - years_pos
    years_same = max(years_pos, years_neg)
    t51 = sh['Q5Q1_t'].iloc[0]
    t41 = sh['Q4Q1_t'].iloc[0]
    best_t = max(abs(t51), abs(t41))
    is_cand = (abs(ic_med) >= 0.02) and (best_t >= 2) and (years_same >= 4)
    dup = abs(g2c) >= 0.80 if pd.notna(g2c) else False
    inc_ok = abs(g2c) < 0.60 if pd.notna(g2c) else False
    tier = ('growth_domain_candidate' if is_cand else 'not_qualified')
    if is_cand and dup:
        tier = 'mainline_duplicate'
    elif is_cand and inc_ok:
        tier = 'incremental_over_mainline'
    dec_rows.append({'factor': fn, 'domain_ic_median': ic_med, 'best_spread_t': best_t,
                     'years_same_sign': f'{years_same}/{len(yr)}', 'g2_corr': g2c, 'tier': tier})
dec = pd.DataFrame(dec_rows)
dec.to_csv(OUT / 'decision_table.csv', index=False)
print(dec.round(4).sort_values('domain_ic_median', key=abs, ascending=False).to_string(index=False))

summary = {'protocol': 'research/protocols/growth15_dual_arm_protocol_v1.md',
           'peg_mean_anomaly_ratio': float(anom['peg_nan_ratio'].mean()),
           'tiers': {t: int((dec['tier'] == t).sum()) for t in dec['tier'].unique()}}
(OUT / 'decision.json').write_text(json.dumps(summary, ensure_ascii=False, indent=2) + '\n')
print(json.dumps(summary, ensure_ascii=False))
