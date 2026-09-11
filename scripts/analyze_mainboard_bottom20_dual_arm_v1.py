#!/usr/bin/env python3
"""沪深主板末20%域分层检验 v1（协议 mainboard_bottom20_dual_arm_protocol_v1）。

7 信号 × 4 臂（B_domain / B_new / A_market / A_main），月度 RankIC + 5 分组
+ Z1 冗余 + 互相关，协议 §5 判定。

信号复用既有实现：Z1/alpha101_19（q4 脚本）、pa（growth15 面板）、
BIAS 换手冷却 + Amihud/amount（liquidity35 脚本）。
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
OUT = ROOT / 'output/analysis_static/mainboard_bottom20_dual_arm_v1'
OUT.mkdir(parents=True, exist_ok=True)

START, END = '2020-01-01', '2026-08-31'  # 504 日 BIAS 需长预热
BT_START = pd.Timestamp('2022-01-01')
DOMAIN_PCT = 0.20  # 主板内末 20%

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
FIELDS = ['open', 'high', 'low', 'close', 'volume', 'factor']
panels = {f: pd.DataFrame({s: read_bin(s, f) for s in symbols if read_bin(s, f) is not None}).reindex(cal)
          for f in FIELDS}
O, H, L, C, V, FAC = (panels[f] for f in FIELDS)
RET = C.pct_change()
AMT = (C / FAC) * V * 100  # 校准成交额(元)，q4 轮已验证
print(f'[data] symbols={len(symbols)} days={len(cal)}', flush=True)

# ---------------- 信号 ----------------
print('[factor] 7 信号 ...', flush=True)


def cs_rank(df):
    return df.rank(axis=1, pct=True)


def ts_rank(df, w):
    return df.rolling(w).apply(lambda x: (x[~np.isnan(x)] <= x[-1]).mean() if np.isfinite(x).any() else np.nan, raw=True)


# Z1 合成（与 q4 脚本同构造）
CANDS = ['alpha101_13', 'alpha101_16', 'alpha101_15', 'alpha101_12', 'alpha101_3',
         'alpha101_6', 'alpha101_4', 'alpha101_19', 'alpha101_52', 'alpha101_14']
CLUSTERS = [['alpha101_13', 'alpha101_15', 'alpha101_16'], ['alpha101_12'],
            ['alpha101_14', 'alpha101_3', 'alpha101_6'], ['alpha101_4'],
            ['alpha101_19'], ['alpha101_52']]
AF = {}
AF['alpha101_13'] = -1 * cs_rank(cs_rank(C).rolling(5).cov(cs_rank(V)))
AF['alpha101_16'] = -1 * cs_rank(cs_rank(H).rolling(5).cov(cs_rank(V)))
AF['alpha101_15'] = -1 * (cs_rank(cs_rank(H).rolling(3).corr(cs_rank(V)))).rolling(3).sum()
AF['alpha101_12'] = np.sign(V.diff(1)) * (-1 * C.diff(1))
AF['alpha101_3'] = -1 * cs_rank(O).rolling(10).corr(cs_rank(V))
AF['alpha101_6'] = -1 * O.rolling(10).corr(V)
AF['alpha101_4'] = -1 * ts_rank(cs_rank(L), 9)
AF['alpha101_19'] = -1 * np.sign((C - C.shift(7)) + C.diff(7)) * (1 + cs_rank(1 + RET.rolling(250).sum()))
tsmin_low5 = L.rolling(5).min()
AF['alpha101_52'] = ((-1 * tsmin_low5 + tsmin_low5.shift(5))
                     * cs_rank((RET.rolling(240).sum() - RET.rolling(20).sum()) / 220) * ts_rank(V, 5))
AF['alpha101_14'] = -1 * cs_rank(RET.diff(3)) * O.rolling(10).corr(V)
Z1 = None
for comp in CLUSTERS:
    z = None
    for fn in comp:
        r = cs_rank(AF[fn])
        z = r if z is None else z + r
    z = z / len(comp)
    Z1 = z if Z1 is None else Z1 + z
Z1 = Z1 / len(CLUSTERS)

# 换手率（liquidity35 口径）
db = pd.read_csv(ROOT / 'data/external/tushare/a_share_daily_basic_pit_v1/normalized/daily_basic.csv.gz',
                 compression='gzip', usecols=['ts_code', 'trade_date', 'total_share', 'float_share', 'total_mv'],
                 dtype={'trade_date': str})
db['dt'] = pd.to_datetime(db['trade_date'], format='%Y%m%d')
db['num'] = db['ts_code'].str.split('.').str[0]
db = db[~db['num'].str.startswith(('43', '83', '87', '92', '920'))]
db['board'] = np.where(db['num'].str.startswith('68'), 'star',
              np.where(db['num'].str.startswith('30'), 'chinext',
              np.where(db['num'].str.startswith(('600', '601', '603', '605')), 'sse_main',
              np.where(db['num'].str.startswith(('000', '001', '002', '003')), 'szse_main', 'other'))))
month_end_all = db.groupby(db['dt'].dt.to_period('M'))['dt'].max().sort_values()
snap_mv, snap_ts, snap_fs = {}, {}, {}
for d in month_end_all:
    g = db[db['dt'] == d]
    snap_mv[d] = pd.Series(g['total_mv'].values / 1e4, index=g['ts_code'].values)
    snap_ts[d] = pd.Series(g['total_share'].values, index=g['ts_code'].values)  # 万股
    snap_fs[d] = pd.Series(g['float_share'].values, index=g['ts_code'].values)


def rename_qlib(df):
    df = df.copy()
    df.columns = [f"{c.split('.')[1].lower()}{c.split('.')[0]}" for c in df.columns]
    return df


me_ts_all = np.array(sorted(snap_mv))
ts_wide = pd.DataFrame({d: snap_ts[d] for d in me_ts_all}).T
fs_wide = pd.DataFrame({d: snap_fs[d] for d in me_ts_all}).T
ts_daily = rename_qlib(ts_wide).reindex(columns=C.columns).reindex(cal, method='ffill') * 1e4  # 股
fs_daily = rename_qlib(fs_wide).reindex(columns=C.columns).reindex(cal, method='ffill') * 1e4
vol_shares = V * 100
turn = vol_shares / ts_daily.where(ts_daily > 0)

F = {}
F['Z1_synth'] = Z1
F['alpha101_19'] = AF['alpha101_19']
F['bias_std_turn_21d_252d'] = turn.rolling(21).std() / turn.rolling(252).std() - 1
F['bias_std_turn_42d_504d'] = turn.rolling(42).std() / turn.rolling(504).std() - 1
F['sum_abs_rtn_amount_20d'] = RET.abs().rolling(20).sum() / AMT.rolling(20).sum()
F['amount_ma_20d'] = AMT.rolling(20).mean()

# pa 从 growth15 面板（月度截面）
pa_panel = pd.read_csv(ROOT / 'output/analysis_static/growth15_dual_arm_v1/factor_panel_pa_monthly.csv.gz',
                       compression='gzip')
pa_panel['dt'] = pd.to_datetime(pa_panel['date'])
pa_panel['sym'] = pa_panel['ts_code'].str.split('.').str[1].str.lower() + pa_panel['ts_code'].str.split('.').str[0]
# 面板每 symbol-月含 2 行（export 的 tail(2) 口径，同一 ts_code 两个报告期），
# 取最后一行为最新报告期——与 growth15 的"取最新一期"意图一致
pa_panel = pa_panel.drop_duplicates(['dt', 'sym'], keep='last')
pa_by_date = {d: pd.Series(g['pa'].values, index=g['sym'].values)
              for d, g in pa_panel.groupby('dt')}
SIGNALS = list(F.keys()) + ['pa']
print(f'[factor] {len(SIGNALS)} 信号（{len(F)} 日频 + pa 面板 {len(pa_by_date)} 个月）', flush=True)


def series_at(fn, d0):
    """取信号在 d0 月末的截面（pa 走月度面板，其余走日频矩阵）。"""
    if fn == 'pa':
        return pa_by_date.get(d0, pd.Series(dtype=float))
    fdf = F[fn]
    return fdf.loc[d0].dropna() if d0 in fdf.index else pd.Series(dtype=float)

# ---------------- 域 ----------------
print('[domain] ...', flush=True)
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
bpsdf = fin[['ts_code', 'end_date', 'available_date', 'bps']].copy()
bpsdf = bpsdf.sort_values(['ts_code', 'end_date', 'available_date']).drop_duplicates(['ts_code', 'end_date'], keep='last').dropna(subset=['bps'])


def quasi_at(t):
    t64 = np.datetime64(t)
    sub = inc[inc['available_date'] <= t64].sort_values(['ts_code', 'end_date'])
    last2 = sub.groupby('ts_code').tail(2)
    g = last2.groupby('ts_code')['loss'].agg(['count', 'sum'])
    two = set(g[(g['count'] >= 2) & (g['sum'] >= 2)].index)
    sb = bpsdf[bpsdf['available_date'] <= t64].sort_values(['ts_code', 'end_date']).groupby('ts_code').tail(1)
    return two | set(sb[sb['bps'] < 0]['ts_code'])


def sym_of(c):
    n, e = c.split('.')
    return f'{e.lower()}{n}'


board_by_code = db.drop_duplicates('ts_code', keep='last').set_index('ts_code')['board'].to_dict()

dom_domain, dom_new, dom_market, dom_main, dom_old10 = {}, {}, {}, {}, {}
for d in month_end_all:
    if not (pd.Timestamp('2021-12-01') <= d <= pd.Timestamp(END)):
        continue
    mask = (st_start <= np.datetime64(d)) & (st_end >= np.datetime64(d)) & st_bad
    bad = set(st_code[mask])
    quasi = quasi_at(d)
    mv_all = snap_mv[d]
    universe = set(mv_all.dropna().index)

    # 主板末20%清洁域
    main_codes = {c for c in universe if board_by_code.get(c) in ('sse_main', 'szse_main')}
    mv_main = mv_all[[c for c in mv_all.index if c in main_codes]].dropna()
    thr20 = mv_main.quantile(DOMAIN_PCT)
    b20 = set(mv_main[mv_main <= thr20].index)
    clean20 = (b20 - bad - quasi) & universe

    # 旧微盘域（三板块末10%清洁）——用于 B_new 与 A_main
    thr10 = mv_all.dropna().quantile(0.10)
    b10 = set(mv_all[mv_all <= thr10].index)
    clean10 = (b10 - bad - quasi) & universe

    dom_domain[d] = {sym_of(c) for c in clean20}
    dom_new[d] = {sym_of(c) for c in (clean20 - clean10)}
    dom_main[d] = {sym_of(c) for c in (main_codes - bad - quasi) & universe}
    dom_market[d] = {sym_of(c) for c in (universe - bad - quasi)}
    dom_old10[d] = {sym_of(c) for c in clean10}  # 复现校验：旧微盘域

ml = [d for d in sorted(dom_domain) if d >= pd.Timestamp('2021-12-01')]
rets_all = {}
for i in range(len(ml) - 1):
    rets_all[ml[i + 1]] = (C.loc[ml[i + 1]] / C.loc[ml[i]] - 1)
print(f'[domain] {len(ml)-1} 个月, B_domain 中位 {int(np.median([len(v) for v in dom_domain.values()]))} 只, '
      f'B_new 中位 {int(np.median([len(v) for v in dom_new.values()]))} 只', flush=True)

# ---------------- IC + 分组 ----------------
print('[ic] ...', flush=True)
from scipy import stats as sps  # noqa: E402

ARMS = {'B_domain': dom_domain, 'B_new': dom_new, 'A_market': dom_market, 'A_main': dom_main,
        'B_old10': dom_old10}  # B_old10 = 旧微盘域，复现校验用
ic_rows, quint_rows = [], []
for i in range(len(ml) - 1):
    d0, d1 = ml[i], ml[i + 1]
    r_all = rets_all[d1].dropna()
    for fn in SIGNALS:
        fser = series_at(fn, d0)
        if len(fser) < 50:
            continue
        for arm, dmap in ARMS.items():
            dom = dmap.get(d0, set())
            f_dom = fser[fser.index.isin(dom)]
            r_dom = r_all[r_all.index.isin(dom)]
            common = f_dom.index.intersection(r_dom.index)
            min_n = 50 if arm in ('B_domain', 'B_new', 'B_old10') else 200
            if len(common) < min_n:
                continue
            ic = sps.spearmanr(f_dom[common], r_dom[common])[0]
            if pd.isna(ic):
                continue
            ic_rows.append({'factor': fn, 'arm': arm, 'date': str(d1.date()), 'ic': ic})
            if arm in ('B_domain', 'B_new', 'B_old10'):
                try:
                    q = pd.qcut(f_dom[common].rank(method='first'), 5, labels=False)
                except ValueError:
                    q = None
                if q is not None:
                    for grp in range(5):
                        sel = common[q == grp]
                        quint_rows.append({'factor': fn, 'arm': arm, 'exit': str(d1.date()),
                                           'group': f'Q{grp+1}', 'ret': float(r_dom[sel].mean())})
    if i % 12 == 0:
        print(f'  {d1.date()}', flush=True)

ic_df = pd.DataFrame(ic_rows)
ic_df.to_csv(OUT / 'ic_monthly_long.csv', index=False)

summary_rows = []
for fn in SIGNALS:
    for arm in ARMS:
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
from scipy import stats as sps2  # noqa: E402
shape_rows = []
for fn in SIGNALS:
    for arm in ('B_domain', 'B_new', 'B_old10'):
        sub = qdf[(qdf['factor'] == fn) & (qdf['arm'] == arm)]
        if sub.empty:
            continue
        piv = sub.pivot_table(index='exit', columns='group', values='ret')[['Q1', 'Q2', 'Q3', 'Q4', 'Q5']].dropna()
        if len(piv) < 10:
            continue
        s51 = piv['Q5'] - piv['Q1']
        s41 = piv['Q4'] - piv['Q1']
        t51, _ = sps2.ttest_1samp(s51, 0)
        t41, _ = sps2.ttest_1samp(s41, 0)
        yr51 = s51.groupby(s51.index.str[:4]).mean()
        yr41 = s41.groupby(s41.index.str[:4]).mean()
        # 形状分类（协议 §4）：先判峰位，再判单调——倒U的 Spearman 天然偏低，
        # 不能先套单调阈值，否则峰在 Q4 的形状会被误判 no_shape
        means = piv[['Q1', 'Q2', 'Q3', 'Q4', 'Q5']].mean()
        sp = sps.spearmanr([1, 2, 3, 4, 5], means.values)[0]
        peak = means.idxmax()
        if abs(sp) >= 0.80:
            shape = 'monotonic_up' if sp > 0 else 'monotonic_down'
        elif peak == 'Q4' and (means['Q4'] - means['Q1']) > 0 and means['Q5'] < means['Q4']:
            shape = 'inverted_u'
        elif peak == 'Q5' and (means['Q5'] - means['Q3']) > 2 * abs(means['Q3'] - means['Q1']):
            shape = 'head_concentrated'
        elif peak == 'Q1' and means['Q5'] == means.min():
            shape = 'head_toxic'
        else:
            shape = 'no_shape' if abs(sp) < 0.40 else 'other'
        shape_rows.append({'factor': fn, 'arm': arm, 'n_months': len(piv),
                           'Q1': means['Q1'], 'Q2': means['Q2'], 'Q3': means['Q3'],
                           'Q4': means['Q4'], 'Q5': means['Q5'],
                           'Q5Q1_monthly': s51.mean(), 'Q5Q1_t': t51,
                           'Q4Q1_monthly': s41.mean(), 'Q4Q1_t': t41,
                           'spearman_shape': sp, 'shape': shape,
                           'years_pos_51': int((yr51 > 0).sum()), 'years_pos_41': int((yr41 > 0).sum()),
                           'years_total': len(yr51)})
shape_df = pd.DataFrame(shape_rows)
shape_df.to_csv(OUT / 'quintile_shape.csv', index=False)

# Z1 相关 + 互相关（B_domain 内）
print('[corr] ...', flush=True)
z1_rows = []
for fn in SIGNALS:
    if fn == 'Z1_synth':
        continue
    cors = []
    for d0 in ml[::3]:
        fser = series_at(fn, d0)
        z = F['Z1_synth'].loc[d0].dropna()
        dom = dom_domain.get(d0, set())
        common = fser.index.intersection(z.index)
        common = common[common.isin(dom)]
        if len(common) >= 50:
            c = sps.spearmanr(fser[common], z[common])[0]
            if pd.notna(c):
                cors.append(c)
    z1_rows.append({'factor': fn, 'z1_spearman_median': float(np.median(cors)) if cors else np.nan})
pd.DataFrame(z1_rows).to_csv(OUT / 'z1_correlation.csv', index=False)

fnames = SIGNALS
corr_sum = pd.DataFrame(0.0, index=fnames, columns=fnames)
corr_cnt = pd.DataFrame(0, index=fnames, columns=fnames)
for d0 in ml[::3]:
    dom = dom_domain.get(d0, set())
    vals = {}
    for fn in fnames:
        fser = series_at(fn, d0)
        f_dom = fser[fser.index.isin(dom)]
        if len(f_dom) >= 50:
            vals[fn] = f_dom.rank(pct=True)
    if len(vals) < 2:
        continue
    vdf = pd.DataFrame(vals).dropna()
    if len(vdf) < 50:
        continue
    c = vdf.corr(method='spearman').abs()
    # 逐格累积、只计有限值——某月某因子全 NaN（如 504d 预热不足）不应污染全表
    corr_sum = corr_sum.add(c, fill_value=0.0)
    corr_cnt = corr_cnt.add(c.notna().astype(int), fill_value=0)
(corr_sum / corr_cnt.replace(0, np.nan)).to_csv(OUT / 'corr_matrix.csv')

# ---------------- 判定 ----------------
print('\n=== 判定 ===', flush=True)
info = {}
for fn in SIGNALS:
    sh = shape_df[(shape_df['factor'] == fn) & (shape_df['arm'] == 'B_domain')]
    sub = ic_df[(ic_df['factor'] == fn) & (ic_df['arm'] == 'B_domain')]
    z1c = next((r['z1_spearman_median'] for r in z1_rows if r['factor'] == fn), np.nan)
    if sub.empty or sh.empty:
        info[fn] = {'domain_ic_median': np.nan, 'z1_corr': z1c, 'tier': 'insufficient_data',
                    'n_months': int(sub['ic'].count()) if not sub.empty else 0}
        continue
    ic = sub['ic'].dropna()
    yr = sub.assign(year=sub['date'].str[:4]).groupby('year')['ic'].median()
    years_same = int(max((yr > 0).sum(), (yr <= 0).sum()))
    ic_med = ic.median()
    t51 = abs(sh['Q5Q1_t'].iloc[0])
    t41 = abs(sh['Q4Q1_t'].iloc[0])
    t_best = max(t51, t41)
    info[fn] = {'domain_ic_median': ic_med, 'z1_corr': z1c, 't_best': t_best,
                'years_same': years_same, 'n_months': len(ic),
                'shape': sh['shape'].iloc[0],
                'Q5Q1_monthly': sh['Q5Q1_monthly'].iloc[0], 'Q5Q1_t': sh['Q5Q1_t'].iloc[0],
                'Q4Q1_monthly': sh['Q4Q1_monthly'].iloc[0], 'Q4Q1_t': sh['Q4Q1_t'].iloc[0],
                'years_pos_51': int(sh['years_pos_51'].iloc[0]),
                'years_pos_41': int(sh['years_pos_41'].iloc[0]),
                'years_total': int(sh['years_total'].iloc[0])}
    if abs(ic_med) >= 0.02 and t_best >= 2 and years_same >= 4:
        info[fn]['tier'] = 'z1_duplicate' if abs(z1c) >= 0.60 else (
            'mainboard20_candidate' + ('_reversal_dir' if ic_med < 0 else ''))
    else:
        info[fn]['tier'] = 'not_qualified'

dec = pd.DataFrame([{'factor': fn, **v} for fn, v in info.items()])
print(dec.sort_values('domain_ic_median', key=abs, ascending=False).round(4).to_string(index=False))

# 协议 §4 冗余归并：|corr|>0.90 视为同一信号，只留 |IC| 最高者
corr_abs = (corr_sum / corr_cnt.replace(0, np.nan)).abs()
cand_names = [f for f, v in info.items() if str(v.get('tier', '')).find('candidate') >= 0
              and v.get('tier') != 'z1_duplicate']
merged, kept = [], []
for fn in sorted(cand_names, key=lambda f: -abs(info[f].get('domain_ic_median', 0))):
    if fn in kept:
        continue
    kept.append(fn)
    for other in cand_names:
        if other != fn and other not in kept and pd.notna(corr_abs.loc[fn, other]) and corr_abs.loc[fn, other] > 0.90:
            info[other]['tier'] = 'merged_into_' + fn
            merged.append({'factor': other, 'merged_into': fn,
                           'corr': float(corr_abs.loc[fn, other])})
print(f'\n冗余归并（|corr|>0.90）: {merged if merged else "无"}')
dec = pd.DataFrame([{'factor': fn, **v} for fn, v in info.items()])
dec.to_csv(OUT / 'decision_table.csv', index=False)

# Z1 主判定（协议 §5：倒U + Q4−Q1 t≥2 + 分年≥4/5）
z1 = info.get('Z1_synth', {})
z1_q41_t = abs(z1.get('Q4Q1_t', 0))
z1_q51_t = abs(z1.get('Q5Q1_t', 0))
z1_yrs = max(z1.get('years_pos_41', 0), z1.get('years_total', 0) - z1.get('years_pos_41', 0))
if z1.get('shape') == 'inverted_u' and z1_q41_t >= 2 and z1_yrs >= 4:
    z1_verdict = 'z1_shape_transfers'
elif z1.get('shape') == 'monotonic_up' and z1_q51_t >= 2:
    z1_verdict = 'z1_monotonic_in_new_domain'
else:
    z1_verdict = 'z1_microcap_specific'
print(f'\nZ1 主判定: {z1_verdict} (shape={z1.get("shape")}, Q4Q1_t={z1.get("Q4Q1_t"):.2f}, '
      f'Q4Q1 分年同号={z1_yrs}/{z1.get("years_total")})')

# 复现校验：旧微盘域 Z1 形状（q4 轮记录 Q4−Q1 +0.94%/月, t=2.80, 4/5 年）
old = shape_df[(shape_df['factor'] == 'Z1_synth') & (shape_df['arm'] == 'B_old10')]
if not old.empty:
    o = old.iloc[0]
    print(f'[复现校验] 旧微盘域 Z1: shape={o["shape"]}, Q4−Q1={o["Q4Q1_monthly"]:+.2%}/月 '
          f'(t={o["Q4Q1_t"]:.2f}), Q5−Q1={o["Q5Q1_monthly"]:+.2%} (t={o["Q5Q1_t"]:.2f}) '
          f'— q4 轮记录 +0.94%/t=2.80')

summary = {'protocol': 'research/protocols/mainboard_bottom20_dual_arm_protocol_v1.md',
           'domain_pct': DOMAIN_PCT,
           'z1_verdict': z1_verdict,
           'n_signals': len(SIGNALS),
           'tiers': {t: int((dec['tier'] == t).sum()) for t in dec['tier'].unique()},
           'candidates_after_merge': kept,
           'merged': merged}
(OUT / 'decision.json').write_text(json.dumps(summary, ensure_ascii=False, indent=2) + '\n')
print(json.dumps(summary, ensure_ascii=False))
