#!/usr/bin/env python3
"""Momentum 20 因子假设检验 v1（协议 momentum20_dual_arm_protocol_v1）。

区间收益/趋势指标/CAPM alpha/形态位置 四组，域内月度 RankIC + 分组价差
+ Z1 冗余 + 组内归并，协议 §4 判定。
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
OUT = ROOT / 'output/analysis_static/momentum20_dual_arm_v1'
OUT.mkdir(parents=True, exist_ok=True)

START, END = '2016-01-01', '2026-08-31'  # 长窗口因子需要长预热
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
FIELDS = ['open', 'high', 'low', 'close', 'volume']
panels = {f: pd.DataFrame({s: read_bin(s, f) for s in symbols if read_bin(s, f) is not None}).reindex(cal)
          for f in FIELDS}
O, H, L, C, V = (panels[f] for f in FIELDS)
RET = C.pct_change()

# 指数收益
idx300 = read_bin('sh000300', 'close')
idx300 = idx300.reindex(cal).pct_change() if idx300 is not None else None
idx1 = read_bin('sz399300', 'close')  # 上证综指 bin 不存在, 用沪深300替代并注明
if idx1 is None:
    idx1 = read_bin('sh000300', 'close')
idx1_ret = idx1.reindex(cal).pct_change() if idx1 is not None else None

print('[factor] 20 因子 ...', flush=True)


def ema(df, w):
    return df.ewm(span=w, adjust=False).mean()


F = {}
# M1
for w in [5, 21, 42, 63, 126, 252]:
    F[f'return_{w}d'] = np.expm1(np.log1p(RET).rolling(w).sum())
# M2
F['ma_20d'] = C.rolling(20).mean()
dif = ema(C, 12) - ema(C, 26)
F['dif'] = dif
F['dea'] = ema(dif, 9)
F['MACD'] = 2 * (dif - ema(dif, 9))
# M3 CAPM alpha（滚动 OLS 截距, 用 cov/var 法）
if idx300 is not None:
    for w in [125, 250, 500, 1000]:
        mx_s = idx300.rolling(w).mean()
        my = RET.rolling(w).mean()
        xy = RET.mul(idx300, axis=0).rolling(w).mean()
        x2 = (idx300 ** 2).rolling(w).mean()
        mx_df = pd.DataFrame(np.repeat(mx_s.values[:, None], my.shape[1], axis=1),
                             index=my.index, columns=my.columns)
        var_x = x2 - mx_s ** 2
        beta = (xy - mx_df * my).div(var_x.where(var_x.abs() > 1e-12), axis=0)
        F[f'alpha_{w}d_000300'] = my - beta * mx_df
if idx1_ret is not None:
    for w in [528, 792, 1320]:
        mx_s = idx1_ret.rolling(w).mean()
        my = RET.rolling(w).mean()
        xy = RET.mul(idx1_ret, axis=0).rolling(w).mean()
        x2 = (idx1_ret ** 2).rolling(w).mean()
        mx_df = pd.DataFrame(np.repeat(mx_s.values[:, None], my.shape[1], axis=1),
                             index=my.index, columns=my.columns)
        var_x = x2 - mx_s ** 2
        beta = (xy - mx_df * my).div(var_x.where(var_x.abs() > 1e-12), axis=0)
        F[f'alpha_{w}d_000001'] = my - beta * mx_df  # 指数用沪深300替代上证(原始上证bin缺失), 注明
# M4
ratio = (C - O) / (H - L).replace(0, np.nan)
F['price_position_ir_60d'] = ratio.rolling(60).mean() / ratio.rolling(60).std()
# rsrs: 18日 Low~High 回归斜率 + 200日 zscore
mx = H.rolling(18).mean()
my = L.rolling(18).mean()
xy = (H * L).rolling(18).mean()
x2 = (H ** 2).rolling(18).mean()
slope = (xy - mx * my) / (x2 - mx ** 2).replace(0, np.nan)
F['rsrs'] = (slope - slope.rolling(200).mean()) / slope.rolling(200).std()
# days_down_up: 连续涨跌天数（向量化: 用 sign 变化分段计数近似——按日累计计数）
up = (RET > 0).astype(int)
dn = (RET < 0).astype(int)


def consec_cols(flag: pd.DataFrame) -> pd.DataFrame:
    """逐列连续 flag 计数。"""
    out = {}
    for col in flag.columns:
        s = flag[col].fillna(0)
        grp = (s != s.shift(1)).cumsum()
        out[col] = s.groupby(grp).cumsum() * s
    return pd.DataFrame(out, index=flag.index)


cons_up = consec_cols(up)
cons_dn = consec_cols(dn)
F['days_down_up'] = (cons_up - cons_dn - 1).abs()

F = {k: v for k, v in F.items() if v is not None and not v.empty and not v.isna().all().all()}
print(f'[factor] {len(F)} 因子: {sorted(F.keys())}', flush=True)

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

ml = [d for d in sorted(domain_by_month) if d >= pd.Timestamp('2021-12-01')]
rets_all = {}
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
            if pd.isna(ic):
                continue
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
            ic_a = sps.spearmanr(fser[common_a], r_all[common_a])[0]
            if pd.notna(ic_a):
                ic_rows.append({'factor': fn, 'arm': 'A_market', 'date': str(d1.date()), 'ic': ic_a})
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

qdf = pd.DataFrame(quint_rows)
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
    t51, _ = sps.ttest_1samp(s51, 0)
    t41, _ = sps.ttest_1samp(s41, 0)
    yr = s51.groupby(s51.index.str[:4]).mean()
    shape_rows.append({'factor': fn, 'n_months': len(piv),
                       'Q1': piv['Q1'].mean(), 'Q5': piv['Q5'].mean(),
                       'Q5Q1_monthly': s51.mean(), 'Q5Q1_t': t51,
                       'Q4Q1_monthly': s41.mean(), 'Q4Q1_t': t41,
                       'years_pos_51': int((yr > 0).sum()), 'years_total': len(yr)})
pd.DataFrame(shape_rows).to_csv(OUT / 'quintile_shape.csv', index=False)

# Z1 相关 + 互相关
print('[corr] ...', flush=True)


def cs_rank(df):
    return df.rank(axis=1, pct=True)


z1_proxy = (-cs_rank(cs_rank(C).rolling(5).cov(cs_rank(V))) - cs_rank(cs_rank(H).rolling(5).cov(cs_rank(V)))) / 2
z1_rows = []
for fn in F:
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

# ---------------- 判定 ----------------
print('\n=== 判定 ===', flush=True)
cand_pool = []
info = {}
for fn in F:
    sub = ic_df[(ic_df['factor'] == fn) & (ic_df['arm'] == 'B_domain')]
    sh = shape_df[shape_df['factor'] == fn] if 'shape_df' in dir() else pd.DataFrame()
    sh = pd.read_csv(OUT / 'quintile_shape.csv')
    sh = sh[sh['factor'] == fn]
    z1c = [r for r in z1_rows if r['factor'] == fn][0]['z1_spearman_median']
    if sub.empty or sh.empty:
        info[fn] = {'domain_ic_median': np.nan, 'z1_corr': z1c, 'tier': 'insufficient_data',
                    'n_months': sub['ic'].count() if not sub.empty else 0}
        continue
    ic = sub['ic'].dropna()
    yr = sub.assign(year=sub['date'].str[:4]).groupby('year')['ic'].median()
    years_same = max((yr > 0).sum(), (yr <= 0).sum())
    t_best = max(abs(sh['Q5Q1_t'].iloc[0]), abs(sh['Q4Q1_t'].iloc[0]))
    ic_med = ic.median()
    info[fn] = {'domain_ic_median': ic_med, 'z1_corr': z1c, 't_best': t_best,
                'years_same': years_same, 'n_months': len(ic)}
    if abs(ic_med) >= 0.02 and t_best >= 2 and years_same >= 4:
        if abs(z1c) >= 0.60:
            info[fn]['tier'] = 'z1_duplicate'
        else:
            info[fn]['tier'] = ('momentum_domain_candidate' + ('_reversal_dir' if ic_med < 0 else ''))
            cand_pool.append((fn, abs(ic_med)))
    else:
        info[fn]['tier'] = 'not_qualified'

# 组内归并 |corr|>0.90
final_cands = []
used = set()
for fn, icabs in sorted(cand_pool, key=lambda x: -x[1]):
    if fn in used:
        continue
    final_cands.append(fn)
    for other, _ in cand_pool:
        if other != fn and other not in used and pd.notna(corr_med.loc[fn, other]) and corr_med.loc[fn, other] > 0.90:
            used.add(other)

dec = pd.DataFrame([{'factor': fn, **v} for fn, v in info.items()])
dec.to_csv(OUT / 'decision_table.csv', index=False)
print(dec.sort_values('domain_ic_median', key=abs, ascending=False).head(12).round(4).to_string(index=False))
print(f'\n最终候选（归并后）: {final_cands}')

summary = {'protocol': 'research/protocols/momentum20_dual_arm_protocol_v1.md',
           'n_factors': len(F),
           'final_candidates': final_cands,
           'tiers': {t: int((dec['tier'] == t).sum()) for t in dec['tier'].unique()}}
(OUT / 'decision.json').write_text(json.dumps(summary, ensure_ascii=False, indent=2) + '\n')
print(json.dumps(summary, ensure_ascii=False))
