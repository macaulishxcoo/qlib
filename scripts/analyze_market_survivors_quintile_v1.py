#!/usr/bin/env python3
"""全市场存活候选 quintile 形状检验 v1（协议 market_survivors_validation_protocol_v1 Stage A）。

22 信号 × 全市场（沪深三板块 − ST/退市 − 次新 <120 交易日），5 分组月度调仓费前。
输出形状判定 + Q5−Q1 价差 t + 分年一致性 + 各组规模阶梯（规模β诊断）+ IC 对账。
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
OUT = ROOT / 'output/analysis_static/market_survivors_quintile_v1'
OUT.mkdir(parents=True, exist_ok=True)

START, END = '2020-06-01', '2026-08-31'
BT_START = pd.Timestamp('2022-01-01')
IPO_MIN_DAYS = 120

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
inst_win = inst[(inst['start'] <= END) & (inst['end'] >= BT_START)]
symbols = sorted(inst_win['code'].str.lower().unique())

print('[data] 加载面板 ...', flush=True)
FIELDS = ['open', 'high', 'low', 'close', 'vwap', 'volume', 'factor']
panels = {f: pd.DataFrame({s: read_bin(s, f) for s in symbols if read_bin(s, f) is not None}).reindex(cal)
          for f in FIELDS}
O, H, L, C, VW, V, FAC = (panels[f] for f in FIELDS)
RET = C.pct_change()
AMT = (C / FAC) * V * 100  # 校准成交额(元)
PREV_C = C.shift(1)
N_LISTED = C.notna().cumsum()  # 上市以来交易日数（面板内）

# ---------------- 换手率（同 liquidity35 口径） ----------------
print('[turn] 换手率面板 ...', flush=True)
db = pd.read_csv(ROOT / 'data/external/tushare/a_share_daily_basic_pit_v1/normalized/daily_basic.csv.gz',
                 compression='gzip', usecols=['ts_code', 'trade_date', 'total_share'],
                 dtype={'trade_date': str})
db['dt'] = pd.to_datetime(db['trade_date'], format='%Y%m%d')
db = db[~db['ts_code'].str.split('.').str[0].str.startswith(('43', '83', '87', '92', '920'))]
month_end_all = db.groupby(db['dt'].dt.to_period('M'))['dt'].max().sort_values()
snap_ts = {}
for d in month_end_all:
    g = db[db['dt'] == d]
    snap_ts[d] = pd.Series(g['total_share'].values, index=g['ts_code'].values)

ts_wide = pd.DataFrame(snap_ts).T  # index=月末, cols=ts_code


def rename_qlib(df):
    df = df.copy()
    df.columns = [f"{c.split('.')[1].lower()}{c.split('.')[0]}" for c in df.columns]
    return df


ts_daily = rename_qlib(ts_wide).reindex(columns=C.columns).reindex(cal, method='ffill') * 1e4
turn = (V * 100) / ts_daily.where(ts_daily > 0)

# ---------------- yoy_total_asset / asset_growth_qoq（PIT 扩深版） ----------------
print('[fin] assets_yoy + recent balancesheet ...', flush=True)
import glob  # noqa: E402
frames = []
for p in sorted(glob.glob(str(ROOT / 'data/external/tushare/a_share_financial_pit_v1/full/normalized/batch_*/fina_indicator.csv.gz'))):
    frames.append(pd.read_csv(p, usecols=['ts_code', 'end_date', 'available_date', 'assets_yoy']))
fi = pd.concat(frames, ignore_index=True)
fi = fi.dropna(subset=['assets_yoy'])
fi['end_date'] = pd.to_datetime(fi['end_date'].astype(str), format='%Y%m%d', errors='coerce')
fi['available_date'] = pd.to_datetime(fi['available_date'].astype(str), format='%Y-%m-%d', errors='coerce')
fi = fi.dropna(subset=['available_date'])
fi['yoy_ta'] = fi['assets_yoy'] / 100.0
fi['qoq_ta'] = np.nan  # fina_indicator 无环比，balancesheet 重算

bs_frames = []
for p in sorted(glob.glob(str(ROOT / 'data/external/tushare/a_share_financial_pit_v1/recent_3tables/balancesheet_*.csv.gz'))):
    d = pd.read_csv(p)
    if len(d):
        bs_frames.append(d)
bs = pd.concat(bs_frames, ignore_index=True)
bs['end_date'] = pd.to_datetime(bs['end_date'].astype(str), format='%Y%m%d', errors='coerce')
bs['available_date'] = pd.to_datetime(bs['ann_date'].astype(str), format='%Y%m%d', errors='coerce')
bs = bs.dropna(subset=['available_date', 'total_assets']).sort_values(['ts_code', 'end_date', 'available_date'])
bs = bs.drop_duplicates(['ts_code', 'end_date'], keep='last')
bs['assets_prev_q'] = bs.groupby('ts_code')['total_assets'].shift(1)
bs['assets_prev_y'] = bs.groupby('ts_code')['total_assets'].shift(4)
bs['yoy_ta'] = bs['total_assets'] / bs['assets_prev_y'] - 1
bs['qoq_ta'] = bs['total_assets'] / bs['assets_prev_q'] - 1
bs = bs[['ts_code', 'end_date', 'available_date', 'yoy_ta', 'qoq_ta']]

ta = pd.concat([fi[['ts_code', 'end_date', 'available_date', 'yoy_ta', 'qoq_ta']], bs], ignore_index=True)
ta = ta.sort_values(['ts_code', 'end_date', 'available_date']).drop_duplicates(['ts_code', 'end_date'], keep='last')
print(f'[fin] ta rows={len(ta)}, yoy non-null={ta["yoy_ta"].notna().sum()}', flush=True)

# ---------------- 因子 ----------------
print('[factor] 22 信号 ...', flush=True)


def cs_rank(df):
    return df.rank(axis=1, pct=True)


def ts_rank(df, w):
    return df.rolling(w).apply(lambda x: (x[~np.isnan(x)] <= x[-1]).mean() if np.isfinite(x).any() else np.nan, raw=True)


F = {}
# T1: 流动性梯队
F['sum_abs_rtn_amount_20d'] = RET.abs().rolling(20).sum() / AMT.rolling(20).sum()
F['amount_ma_20d'] = AMT.rolling(20).mean()
for short in [21, 42, 63]:
    ma_s = turn.rolling(short).mean()
    sd_s = turn.rolling(short).std()
    ma_l = turn.rolling(252).mean()
    sd_l = turn.rolling(252).std()
    F[f'bias_turn_{short}d_252d'] = ma_s / ma_l - 1
    F[f'bias_std_turn_{short}d_252d'] = sd_s / sd_l - 1
# 补充: 换手激增
F['turn_surge_21d_252d'] = turn.rolling(21).mean() / turn.rolling(252).mean() - 1

# T2: 成长（月度截面 → 日频面板）
month_ends = [d for d in month_end_all if pd.Timestamp('2021-06-01') <= d <= pd.Timestamp(END)]
ta_indexed = ta.set_index(['ts_code', 'available_date'])
yoy_panels, qoq_panels = {}, {}
for d in month_ends:
    sub = ta[ta['available_date'] <= d].sort_values('end_date').groupby('ts_code').tail(1).set_index('ts_code')
    yoy_panels[d] = sub['yoy_ta']
    qoq_panels[d] = sub['qoq_ta']
yoy_df = pd.DataFrame(yoy_panels)
qoq_df = pd.DataFrame(qoq_panels)


def rename_sym_idx(df):
    df = df.copy()
    df.index = [f"{c.split('.')[1].lower()}{c.split('.')[0]}" for c in df.index]
    return df


# index=ts_code → qlib symbol，转置后列=股票、行=月末，再 ffill 到日频
yoy_daily = rename_sym_idx(yoy_df).T.reindex(columns=C.columns).reindex(cal, method='ffill')
qoq_daily = rename_sym_idx(qoq_df).T.reindex(columns=C.columns).reindex(cal, method='ffill')
F['yoy_total_asset'] = yoy_daily
F['asset_growth_qoq'] = qoq_daily

# T3: Alpha101 10 候选（公式与 quintile_shape 逐行一致）
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

# 基准诊断: 规模
mv_snap = pd.read_csv(ROOT / 'data/external/tushare/a_share_daily_basic_pit_v1/normalized/daily_basic.csv.gz',
                      compression='gzip', usecols=['ts_code', 'trade_date', 'total_mv'], dtype={'trade_date': str})
mv_snap['dt'] = pd.to_datetime(mv_snap['trade_date'], format='%Y%m%d')
mv_snap = mv_snap[~mv_snap['ts_code'].str.split('.').str[0].str.startswith(('43', '83', '87', '92', '920'))]
mv_me = mv_snap[mv_snap['dt'].isin(month_end_all)]
mv_wide = mv_me.pivot_table(index='dt', columns='ts_code', values='total_mv')
mv_daily = rename_qlib(mv_wide).reindex(columns=C.columns).reindex(cal, method='ffill') / 1e4  # 亿元
F['total_mv'] = mv_daily

F = {k: v for k, v in F.items() if v is not None}
SIGNALS = dict(F)
print(f'[factor] 信号数={len(SIGNALS)}', flush=True)

# ---------------- ST 状态 ----------------
st = pd.read_csv(ROOT / 'data/external/tushare/a_share_st_status_pit_v1/normalized/st_status_intervals.csv.gz',
                 compression='gzip', parse_dates=['start_date', 'end_date'])
st_start, st_end = st['start_date'].values, st['end_date'].values
st_bad = (st['is_st'] | st['is_delist_phase']).values
st_code = st['ts_code'].values


def bad_at(t):
    mask = (st_start <= np.datetime64(t)) & (st_end >= np.datetime64(t)) & st_bad
    return {s.lower() for s in st_code[mask]}


def sym_of(c):
    n, e = c.split('.')
    return f'{e.lower()}{n}'


BAD_SETS = {c: {sym_of(c)} for c in set(st_code[st_bad])}

# ---------------- 月度调仓日 ----------------
trading_days = cal[cal >= BT_START]
td_s = pd.Series(trading_days, index=trading_days)
month_first = td_s.groupby(trading_days.to_period('M')).min().sort_values().tolist()
print(f'[bt] 调仓月数={len(month_first)}', flush=True)

# ---------------- quintile 分组（T+1 开盘进出，费前） ----------------
print('[bt] 分组回测 ...', flush=True)


def month_returns(sig_name, entry_day):
    """全市场域 5 分组 + ALL，费前月度收益 + 各组规模中位。"""
    bad = bad_at(entry_day)
    n_listed = N_LISTED.loc[entry_day]
    cands = [s for s in C.columns if s not in bad and pd.notna(n_listed.get(s, np.nan))
             and n_listed.get(s, 0) >= IPO_MIN_DAYS]
    if len(cands) < 300:
        return None
    frow = SIGNALS[sig_name].loc[entry_day].reindex(cands).dropna()
    if len(frow) < 300:
        return None
    qcut = pd.qcut(frow.rank(method='first'), 5, labels=False)
    groups = {q: qcut[qcut == q].index.tolist() for q in range(5)}

    pos = month_first.index(entry_day)
    if pos + 1 >= len(month_first):
        return None
    exit_day = month_first[pos + 1]
    cal_pos = cal.get_loc(entry_day)
    if cal_pos + 1 >= len(cal):
        return None
    buy_day = cal[cal_pos + 1]
    exit_pos = cal.get_loc(exit_day)
    if exit_pos + 1 >= len(cal):
        return None
    sell_day = cal[exit_pos + 1]
    o_buy, o_sell = O.loc[buy_day], O.loc[sell_day]

    out = {}
    for q in range(5):
        rets, mvs = [], []
        for s in groups[q]:
            b, sl = o_buy.get(s, np.nan), o_sell.get(s, np.nan)
            if pd.notna(b) and pd.notna(sl) and b > 0:
                rets.append(sl / b - 1)
                m = mv_daily.at[entry_day, s] if s in mv_daily.columns else np.nan
                mvs.append(m if pd.notna(m) else np.nan)
        out[f'Q{q+1}'] = float(np.mean(rets)) if rets else np.nan
        out[f'mv_med_Q{q+1}'] = float(np.nanmedian(mvs)) if mvs else np.nan
    all_rets = []
    for s in frow.index:
        b, sl = o_buy.get(s, np.nan), o_sell.get(s, np.nan)
        if pd.notna(b) and pd.notna(sl) and b > 0:
            all_rets.append(sl / b - 1)
    out['ALL'] = float(np.mean(all_rets)) if all_rets else np.nan
    out['n'] = len(frow)
    out['exit'] = str(exit_day.date())
    # Q5 可交易性（方向随信号符号: 高分组）
    q5 = groups[4]
    limit_up = halted = 0
    for s in q5:
        c_now = C.at[entry_day, s] if s in C.columns else np.nan
        c_prev = PREV_C.at[entry_day, s] if s in C.columns else np.nan
        v_now = V.at[entry_day, s] if s in V.columns else np.nan
        if pd.notna(c_now) and pd.notna(c_prev) and c_prev > 0 and c_now / c_prev - 1 >= 0.095:
            limit_up += 1
        if pd.isna(v_now) or v_now <= 0:
            halted += 1
    out['q5_limit_up_ratio'] = limit_up / len(q5) if q5 else np.nan
    out['q5_halt_ratio'] = halted / len(q5) if q5 else np.nan
    return out


rows = []
for sig in SIGNALS:
    print(f'  {sig} ...', flush=True)
    for d in month_first[:-1]:
        r = month_returns(sig, d)
        if r is None:
            continue
        for k in ['Q1', 'Q2', 'Q3', 'Q4', 'Q5', 'ALL']:
            rows.append({'signal': sig, 'entry': str(d.date()), 'exit': r['exit'],
                         'group': k, 'ret': r[k], 'n': r['n'],
                         'q5_limit_up': r['q5_limit_up_ratio'], 'q5_halt': r['q5_halt_ratio']})
        for q in range(1, 6):
            rows.append({'signal': sig, 'entry': str(d.date()), 'exit': r['exit'],
                         'group': f'mv_med_Q{q}', 'ret': r[f'mv_med_Q{q}'], 'n': r['n'],
                         'q5_limit_up': np.nan, 'q5_halt': np.nan})

df = pd.DataFrame(rows)
df.to_csv(OUT / 'quintile_monthly_returns.csv', index=False)

# ---------------- 形状判定 ----------------
print('\n[shape] ...', flush=True)
from scipy import stats as sps  # noqa: E402

shape_rows = []
for sig in SIGNALS:
    sub = df[(df['signal'] == sig) & (df['group'].isin(['Q1', 'Q2', 'Q3', 'Q4', 'Q5', 'ALL']))]
    piv = sub.pivot_table(index='exit', columns='group', values='ret')
    if not {'Q1', 'Q2', 'Q3', 'Q4', 'Q5'}.issubset(piv.columns):
        continue
    piv = piv[['Q1', 'Q2', 'Q3', 'Q4', 'Q5']].dropna()
    if len(piv) < 10:
        continue
    means = piv.mean()
    rho, _ = sps.spearmanr([1, 2, 3, 4, 5], means.values)
    spread = piv['Q5'] - piv['Q1']
    t_stat, p_val = sps.ttest_1samp(spread.dropna(), 0)
    yearly = spread.groupby(spread.index.str[:4]).mean()
    years_pos = int((yearly > 0).sum())
    # 规模阶梯: Q5 vs Q1 的市值中位比（规模β诊断）
    mvsub = df[(df['signal'] == sig) & (df['group'].str.startswith('mv_med_Q'))]
    mvpiv = mvsub.pivot_table(index='exit', columns='group', values='ret')
    mv_ratio = (mvpiv['mv_med_Q5'] / mvpiv['mv_med_Q1']).median() if not mvpiv.empty else np.nan
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

    shape_rows.append({'signal': sig, 'shape': shape,
                       'Q1': means['Q1'], 'Q2': means['Q2'], 'Q3': means['Q3'],
                       'Q4': means['Q4'], 'Q5': means['Q5'], 'ALL': sub['ret'][sub['group'] == 'ALL'].mean(),
                       'Q5_minus_Q1_monthly': spread.mean(),
                       'spread_t': t_stat, 'spread_p': p_val,
                       'years_positive': f'{years_pos}/{len(yearly)}',
                       'mv_med_Q5_over_Q1': mv_ratio,
                       'q5_limit_up_ratio': q5lu, 'q5_halt_ratio': q5h,
                       'n_months': len(piv)})

sh = pd.DataFrame(shape_rows)
sh.to_csv(OUT / 'shape_summary.csv', index=False)
print(sh.round(4).to_string(index=False))

# ---------------- IC 对账（月末 RankIC，域=同剔除口径） ----------------
print('\n[recon] IC 对账 ...', flush=True)
recon_rows = []
rets_all = {}
ml = month_first[1:]
for i in range(len(month_first) - 1):
    e0, e1 = month_first[i], month_first[i + 1]
    rets_all[e1] = C.loc[e1] / C.loc[e0] - 1

for sig in SIGNALS:
    fdf = SIGNALS[sig]
    ics = []
    for i in range(len(month_first) - 1):
        d0, d1 = month_first[i], month_first[i + 1]
        bad = bad_at(d0)
        n_listed = N_LISTED.loc[d0]
        cands = [s for s in C.columns if s not in bad and pd.notna(n_listed.get(s, np.nan))
                 and n_listed.get(s, 0) >= IPO_MIN_DAYS]
        r = rets_all[d1]
        fser = fdf.loc[d0].reindex(cands).dropna()
        common = fser.index.intersection(r.dropna().index)
        if len(common) < 300:
            continue
        ics.append(sps.spearmanr(fser[common], r[common])[0])
    if ics:
        recon_rows.append({'signal': sig, 'ic_median': float(np.median(ics)),
                           'ic_ir': float(np.median(ics) / (np.std(ics) + 1e-12) * np.sqrt(12)),
                           'n_months': len(ics)})
rec = pd.DataFrame(recon_rows)
rec.to_csv(OUT / 'reconciliation_ic.csv', index=False)
print(rec.round(4).to_string(index=False))

decision = {'protocol': 'research/protocols/market_survivors_validation_protocol_v1.md',
            'stage_a': sh[['signal', 'shape', 'Q5_minus_Q1_monthly', 'spread_t', 'years_positive',
                           'mv_med_Q5_over_Q1', 'q5_limit_up_ratio', 'q5_halt_ratio']].to_dict('records'),
            'reconciliation': rec.to_dict('records')}
(OUT / 'decision.json').write_text(json.dumps(decision, ensure_ascii=False, indent=2) + '\n')
print('\nStage A 完成:', OUT)
