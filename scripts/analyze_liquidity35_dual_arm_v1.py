#!/usr/bin/env python3
"""Liquidity 35 因子假设检验 v1（协议 liquidity35_dual_arm_protocol_v1）。

换手率族（MA/STD/BIAS/短长比）+ 成交额/量Alpha，域内月度 RankIC + 分组价差
+ Z1 冗余，协议 §4 判定。
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
OUT = ROOT / 'output/analysis_static/liquidity35_dual_arm_v1'
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

print('[data] 面板 ...', flush=True)
FIELDS = ['close', 'volume', 'factor']
panels = {f: pd.DataFrame({s: read_bin(s, f) for s in symbols if read_bin(s, f) is not None}).reindex(cal)
          for f in FIELDS}
C, V, FAC = panels['close'], panels['volume'], panels['factor']
RET = C.pct_change()
AMT = (C / FAC) * V * 100  # 校准成交额(元)
VOL_SHARES = V * 100  # 股数(股)

# 总股本（月末快照，前向填充到日频做分母）
db = pd.read_csv(ROOT / 'data/external/tushare/a_share_daily_basic_pit_v1/normalized/daily_basic.csv.gz',
                 compression='gzip', usecols=['ts_code', 'trade_date', 'total_share', 'float_share', 'total_mv'],
                 dtype={'trade_date': str})
db['dt'] = pd.to_datetime(db['trade_date'], format='%Y%m%d')
db_hs = db[~db['ts_code'].str.split('.').str[0].str.startswith(('43', '83', '87', '92', '920'))]
month_end_all = db_hs.groupby(db_hs['dt'].dt.to_period('M'))['dt'].max().sort_values()
snap_mv, snap_ts, snap_fs = {}, {}, {}
for d in month_end_all:
    g = db_hs[db_hs['dt'] == d]
    snap_mv[d] = pd.Series(g['total_mv'].values / 1e4, index=g['ts_code'].values)
    snap_ts[d] = pd.Series(g['total_share'].values, index=g['ts_code'].values)  # 万股
    snap_fs[d] = pd.Series(g['float_share'].values, index=g['ts_code'].values)

me_ts_all = np.array(sorted(snap_mv))
me_list = [d for d in sorted(snap_mv) if d >= pd.Timestamp('2021-06-01')]

# 日频换手率（用最近月末总股本）
print('[turn] 日频换手率面板（向量化） ...', flush=True)
# 月末截面 -> 日频前向填充（向量化）
ts_wide = pd.DataFrame({d: snap_ts[d] for d in me_ts_all}).T  # index=月末, cols=ts_code
fs_wide = pd.DataFrame({d: snap_fs[d] for d in me_ts_all}).T
# ts_code -> qlib symbol 列名
def rename_qlib(df):
    df = df.copy()
    df.columns = [f"{c.split('.')[1].lower()}{c.split('.')[0]}" for c in df.columns]
    return df
ts_q = rename_qlib(ts_wide)
fs_q = rename_qlib(fs_wide)
# 对齐到 C.columns 并前向填充到日频
ts_daily = ts_q.reindex(columns=C.columns).reindex(cal, method='ffill') * 1e4  # 股
fs_daily = fs_q.reindex(columns=C.columns).reindex(cal, method='ffill') * 1e4
vol_shares = V * 100  # 手 -> 股
turn = vol_shares / ts_daily.where(ts_daily > 0)
fs_ratio = vol_shares / fs_daily.where(fs_daily > 0)
print(f'  turn 非零占比={turn.notna().mean().mean():.2%}', flush=True)

print('[factor] 35 因子 ...', flush=True)
F = {}
for w in [5, 10, 20, 21, 42, 63, 126, 252]:
    F[f'avg_turnover_{w}d'] = turn.rolling(w).mean()
for w in [21, 42, 63, 126, 252]:
    F[f'std_turnover_{w}d'] = turn.rolling(w).std()
# BIAS: 短(21/42/63/126) 长(std 252/504 -> 252 个交易日≈12月, 504≈24月)
for short in [21, 42, 63, 126]:
    ma_s = turn.rolling(short).mean()
    for long, lname in [(252, '252d'), (504, '504d')]:
        ma_l = turn.rolling(long).mean()
        F[f'bias_turn_{short}d_{lname}'] = ma_s / ma_l - 1
        sd_s = turn.rolling(short).std()
        sd_l = turn.rolling(long).std()
        F[f'bias_std_turn_{short}d_{lname}'] = sd_s / sd_l - 1
# L4
F['amount_ma_20d'] = AMT.rolling(20).mean()
F['sum_abs_rtn_amount_20d'] = RET.abs().rolling(20).sum() / AMT.rolling(20).sum()
vr = fs_ratio  # vol/float 市值口径代理
F['turnover_ma_20d'] = -vr.rolling(20).mean()
ma20, ma120 = vr.rolling(20).mean(), vr.rolling(120).mean()
F['turnover_ma_20d_120d'] = -(ma20 / ma120)
# volume alpha (相对指数 5日量动量, 300日 OLS alpha) — 指数: sh000300
idx_vol = read_bin('sh000300', 'volume')
if idx_vol is not None:
    idx_mom = (idx_vol.rolling(5).sum() - idx_vol.rolling(5).sum().shift(1)) / idx_vol.rolling(5).sum().shift(1)
    stock_mom = (V.rolling(5).sum() - V.rolling(5).sum().shift(1)) / V.rolling(5).sum().shift(1)
    # 滚动 OLS alpha: cov/var 法
    mean_x = idx_mom.reindex_like(stock_mom).rolling(300).mean()
    mean_y = stock_mom.rolling(300).mean()
    cov = (stock_mom * 0).rolling(300).mean()  # placeholder
    # 向量化滚动协方差
    xy = (stock_mom * idx_mom.reindex_like(stock_mom)).rolling(300).mean()
    x2 = (idx_mom.reindex_like(stock_mom) ** 2).rolling(300).mean()
    beta = (xy - mean_x * mean_y) / (x2 - mean_x ** 2).replace(0, np.nan)
    alpha = mean_y - beta * mean_x
    F['volume_alpha_300d_000300'] = alpha
F = {k: v for k, v in F.items() if v is not None and not v.empty}
print(f'[factor] {len(F)} 因子', flush=True)

# ---------------- 域 ----------------
st = pd.read_csv(ROOT / 'data/external/tushare/a_share_st_status_pit_v1/normalized/st_status_intervals.csv.gz',
                 compression='gzip', parse_dates=['start_date', 'end_date'])
st_start, st_end = st['start_date'].values, st['end_date'].values
st_bad = (st['is_st'] | st['is_delist_phase']).values
st_code = st['ts_code'].values

from load_financials_extended_v1 import load_financials_extended  # noqa: E402
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

me_domain = np.array(sorted(domain_by_month))

# 月度收益
rets_all = {}
ml = [d for d in sorted(domain_by_month) if d >= pd.Timestamp('2021-12-01')]
for i in range(len(ml) - 1):
    e0, e1 = ml[i], ml[i + 1]
    rets_all[e1] = (C.loc[e1] / C.loc[e0] - 1)

# ---------------- 双臂 IC + 分组 ----------------
print('[ic] ...', flush=True)
from scipy import stats as sps  # noqa: E402

ic_rows, quint_rows = [], []
for i in range(len(ml) - 1):
    d0, d1 = ml[i], ml[i + 1]
    dom = domain_by_month[ml[i]]
    r_all = rets_all[d1].dropna()
    r_dom = r_all[r_all.index.isin(dom)]
    if len(r_dom) < 50:
        continue
    mask = (st_start <= np.datetime64(d0)) & (st_end >= np.datetime64(d0)) & st_bad
    bad_syms = {s.lower() for s in st_code[mask]}
    for fn, fdf in F.items():
        fser = fdf.loc[d0].dropna()
        if len(fser) < 50:
            continue
        f_dom = fser[fser.index.isin(dom) & ~fser.index.isin(bad_syms)]
        common = f_dom.index.intersection(r_dom.index)
        if len(common) >= 50:
            ic = sps.spearmanr(f_dom[common], r_dom[common])[0]
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
        common_a = fser.index.intersection(r_all.index)
        if len(common_a) >= 200:
            ic_rows.append({'factor': fn, 'arm': 'A_market', 'date': str(d1.date()),
                            'ic': sps.spearmanr(fser[common_a], r_all[common_a])[0]})
    if i % 12 == 0:
        print(f'  {d1.date()}', flush=True)

ic_df = pd.DataFrame(ic_rows)
ic_df.to_csv(OUT / 'ic_monthly_long.csv', index=False)

summary_rows = []
for fn in F:
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

# 分组价差
qdf = pd.DataFrame(quint_rows)
from scipy import stats as sps2  # noqa: E402
shape_rows = []
for fn in F:
    sub = qdf[qdf['factor'] == fn]
    if sub.empty:
        continue
    piv = sub.pivot_table(index='exit', columns='group', values='ret')[['Q1', 'Q2', 'Q3', 'Q4', 'Q5']].dropna()
    if len(piv) < 10:
        continue
    s51 = piv['Q5'] - piv['Q1']
    s41 = piv['Q4'] - piv['Q1']
    t51, _ = sps2.ttest_1samp(s51, 0)
    t41, _ = sps2.ttest_1samp(s41, 0)
    yr = s51.groupby(s51.index.str[:4]).mean()
    shape_rows.append({'factor': fn, 'n_months': len(piv),
                       'Q1': piv['Q1'].mean(), 'Q5': piv['Q5'].mean(),
                       'Q5Q1_monthly': s51.mean(), 'Q5Q1_t': t51,
                       'Q4Q1_monthly': s41.mean(), 'Q4Q1_t': t41,
                       'years_pos_51': int((yr > 0).sum()), 'years_total': len(yr)})
shape_df = pd.DataFrame(shape_rows)
shape_df.to_csv(OUT / 'quintile_shape.csv', index=False)

# 因子互相关（域内月度截面的平均秩相关——抽样以省时）
print('[corr] 因子互相关 ...', flush=True)
fnames = list(F.keys())
corr_sum = pd.DataFrame(0.0, index=fnames, columns=fnames)
corr_n = 0
for d0 in ml[::3]:
    if d0 not in domain_by_month:
        continue
    dom = domain_by_month[d0]
    vals = {}
    for fn in fnames:
        fser = F[fn].loc[d0].dropna()
        f_dom = fser[fser.index.isin(dom)]
        if len(f_dom) >= 50:
            vals[fn] = f_dom.rank(pct=True)
    if len(vals) < 2:
        continue
    vdf = pd.DataFrame(vals).dropna()
    if len(vdf) < 50:
        continue
    corr_sum += vdf.corr(method='spearman').abs()
    corr_n += 1
corr_med = corr_sum / max(corr_n, 1)
corr_med.to_csv(OUT / 'corr_matrix.csv')

# Z1 冗余（量价背离合成, 简化重建: 用 13/16 均值近似 Z1 方向）
print('[z1] ...', flush=True)
O = pd.DataFrame({s: read_bin(s, 'open') for s in symbols if read_bin(s, 'open') is not None}).reindex(cal)
H = pd.DataFrame({s: read_bin(s, 'high') for s in symbols if read_bin(s, 'high') is not None}).reindex(cal)


def cs_rank(df):
    return df.rank(axis=1, pct=True)


z1_proxy = (-cs_rank(cs_rank(C).rolling(5).cov(cs_rank(V))) - cs_rank(cs_rank(H).rolling(5).cov(cs_rank(V)))) / 2
z1_rows = []
for fn in fnames:
    cors = []
    for d0 in ml[::3]:
        fser = F[fn].loc[d0].dropna()
        z = z1_proxy.loc[d0].dropna()
        common = fser.index.intersection(z.index)
        if len(common) >= 100:
            c = sps.spearmanr(fser[common], z[common])[0]
            if pd.notna(c):
                cors.append(c)
    z1_rows.append({'factor': fn, 'z1_spearman_median': float(np.median(cors)) if cors else np.nan})
pd.DataFrame(z1_rows).to_csv(OUT / 'z1_correlation.csv', index=False)

# ---------------- 判定（同族归并: |corr|>0.90 组内只留 |IC| 最高者） ----------------
print('\n=== 判定 ===', flush=True)
cand_pool = []
for fn in fnames:
    sub = ic_df[(ic_df['factor'] == fn) & (ic_df['arm'] == 'B_domain')]
    sh = shape_df[shape_df['factor'] == fn]
    if sub.empty or sh.empty:
        continue
    ic = sub['ic'].dropna()
    yr = sub.assign(year=sub['date'].str[:4]).groupby('year')['ic'].median()
    years_same = max((yr > 0).sum(), (yr <= 0).sum())
    t_best = max(abs(sh['Q5Q1_t'].iloc[0]), abs(sh['Q4Q1_t'].iloc[0]))
    if abs(ic.median()) >= 0.02 and t_best >= 2 and years_same >= 4:
        cand_pool.append((fn, abs(ic.median())))

# 归并
final_cands = []
used = set()
for fn, icabs in sorted(cand_pool, key=lambda x: -x[1]):
    if fn in used:
        continue
    final_cands.append(fn)
    for other in cand_pool:
        on = other[0]
        if on != fn and on not in used and corr_med.loc[fn, on] > 0.90:
            used.add(on)

dec_rows = []
for fn in fnames:
    sub = ic_df[(ic_df['factor'] == fn) & (ic_df['arm'] == 'B_domain')]
    sh = shape_df[shape_df['factor'] == fn]
    z1c = [r for r in z1_rows if r['factor'] == fn][0]['z1_spearman_median']
    if sub.empty or sh.empty:
        tier = 'insufficient_data'
    else:
        ic = sub['ic'].dropna()
        yr = sub.assign(year=sub['date'].str[:4]).groupby('year')['ic'].median()
        years_same = max((yr > 0).sum(), (yr <= 0).sum())
        t_best = max(abs(sh['Q5Q1_t'].iloc[0]), abs(sh['Q4Q1_t'].iloc[0]))
        if fn in final_cands:
            tier = 'liquidity_domain_candidate' + ('_reversal_dir' if ic.median() < 0 else '')
        elif abs(ic.median()) >= 0.02 and t_best >= 2 and years_same >= 4:
            tier = 'candidate_merged_duplicate'
        else:
            tier = 'not_qualified'
    dec_rows.append({'factor': fn, 'domain_ic_median': sub['ic'].median() if not sub.empty else np.nan,
                     'z1_corr': z1c, 'tier': tier})
dec = pd.DataFrame(dec_rows)
dec.to_csv(OUT / 'decision_table.csv', index=False)
print(dec.sort_values('domain_ic_median', key=abs, ascending=False).head(15).round(4).to_string(index=False))
print(f'\n最终候选（归并后）: {final_cands}')

summary = {'protocol': 'research/protocols/liquidity35_dual_arm_protocol_v1.md',
           'n_factors': len(F),
           'final_candidates': final_cands,
           'tiers': {t: int((dec['tier'] == t).sum()) for t in dec['tier'].unique()}}
(OUT / 'decision.json').write_text(json.dumps(summary, ensure_ascii=False, indent=2) + '\n')
print(json.dumps(summary, ensure_ascii=False))
