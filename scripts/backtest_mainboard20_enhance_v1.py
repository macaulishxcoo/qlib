#!/usr/bin/env python3
"""沪深主板末20% enhance 构造组合回测 v1（协议 mainboard20_enhance_protocol_v1）。

臂: enhance_fuse(三源加权) / enhance_z1(仅Z1) / q4_fuse(60-80分位带) / pool_ew(对照)
月度调仓, T+1 开盘成交, 三档成本, 2022-01~2026-08。
"""
from __future__ import annotations

import itertools
import json
import os
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path('/home/xiaocong/worksapces/qlib')
sys.path.insert(0, str(ROOT / 'scripts'))
QLIB_DIR = Path(os.path.expanduser('~')) / '.qlib/qlib_data/cn_data_2026'
OUT = ROOT / 'output/analysis_fundamental/mainboard20_enhance_v1'
OUT.mkdir(parents=True, exist_ok=True)

START, END = '2020-01-01', '2026-08-31'
BT_START = pd.Timestamp('2022-01-01')
DOMAIN_PCT = 0.20
CRASH = (pd.Timestamp('2024-01-01'), pd.Timestamp('2024-02-29'))

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
AMT = (C / FAC) * V * 100

print('[factor] 三源信号 ...', flush=True)


def cs_rank(df):
    return df.rank(axis=1, pct=True)


def ts_rank(df, w):
    return df.rolling(w).apply(lambda x: (x[~np.isnan(x)] <= x[-1]).mean() if np.isfinite(x).any() else np.nan, raw=True)


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

# 换手率
db = pd.read_csv(ROOT / 'data/external/tushare/a_share_daily_basic_pit_v1/normalized/daily_basic.csv.gz',
                 compression='gzip', usecols=['ts_code', 'trade_date', 'total_share', 'total_mv'],
                 dtype={'trade_date': str})
db['dt'] = pd.to_datetime(db['trade_date'], format='%Y%m%d')
db['num'] = db['ts_code'].str.split('.').str[0]
db = db[~db['num'].str.startswith(('43', '83', '87', '92', '920'))]
db['board'] = np.where(db['num'].str.startswith('68'), 'star',
              np.where(db['num'].str.startswith('30'), 'chinext',
              np.where(db['num'].str.startswith(('600', '601', '603', '605')), 'sse_main',
              np.where(db['num'].str.startswith(('000', '001', '002', '003')), 'szse_main', 'other'))))
month_end_all = db.groupby(db['dt'].dt.to_period('M'))['dt'].max().sort_values()
snap_mv, snap_ts = {}, {}
for d in month_end_all:
    g = db[db['dt'] == d]
    snap_mv[d] = pd.Series(g['total_mv'].values / 1e4, index=g['ts_code'].values)
    snap_ts[d] = pd.Series(g['total_share'].values, index=g['ts_code'].values)


def rename_qlib(df):
    df = df.copy()
    df.columns = [f"{c.split('.')[1].lower()}{c.split('.')[0]}" for c in df.columns]
    return df


me_ts_all = np.array(sorted(snap_mv))
ts_daily = rename_qlib(pd.DataFrame({d: snap_ts[d] for d in me_ts_all}).T) \
    .reindex(columns=C.columns).reindex(cal, method='ffill') * 1e4
turn = (V * 100) / ts_daily.where(ts_daily > 0)
BIAS = turn.rolling(21).std() / turn.rolling(252).std() - 1

# pa 面板
pa_panel = pd.read_csv(ROOT / 'output/analysis_static/growth15_dual_arm_v1/factor_panel_pa_monthly.csv.gz',
                       compression='gzip')
pa_panel['dt'] = pd.to_datetime(pa_panel['date'])
pa_panel['sym'] = pa_panel['ts_code'].str.split('.').str[1].str.lower() + pa_panel['ts_code'].str.split('.').str[0]
pa_panel = pa_panel.drop_duplicates(['dt', 'sym'], keep='last')
pa_by_date = {d: pd.Series(g['pa'].values, index=g['sym'].values) for d, g in pa_panel.groupby('dt')}

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
domain_by_month = {}
for d in month_end_all:
    if not (pd.Timestamp('2021-12-01') <= d <= pd.Timestamp(END)):
        continue
    mask = (st_start <= np.datetime64(d)) & (st_end >= np.datetime64(d)) & st_bad
    bad = set(st_code[mask])
    quasi = quasi_at(d)
    mv_all = snap_mv[d]
    universe = set(mv_all.dropna().index)
    main_codes = {c for c in universe if board_by_code.get(c) in ('sse_main', 'szse_main')}
    mv_main = mv_all[[c for c in mv_all.index if c in main_codes]].dropna()
    thr20 = mv_main.quantile(DOMAIN_PCT)
    b20 = set(mv_main[mv_main <= thr20].index)
    clean20 = (b20 - bad - quasi) & universe
    domain_by_month[d] = {sym_of(c) for c in clean20}
me_ts = np.array(sorted(domain_by_month))
print(f'[domain] 域中位 {int(np.median([len(v) for v in domain_by_month.values()]))} 只', flush=True)


def domain_for(t):
    idx = np.searchsorted(me_ts, np.datetime64(t), side='right') - 1
    return domain_by_month[me_ts[idx]] if idx >= 0 else set()


def bad_at(t):
    mask = (st_start <= np.datetime64(t)) & (st_end >= np.datetime64(t)) & st_bad
    return {s.lower() for s in st_code[mask]}


# 月度调仓日
trading_days = cal[cal >= BT_START]
month_first = [d for d in pd.Series(trading_days, index=trading_days)
               .groupby(trading_days.to_period('M')).min().sort_values()
               if np.searchsorted(me_ts, np.datetime64(d), side='right') - 1 >= 0]
print(f'[bt] 调仓月数={len(month_first)}', flush=True)


def fuse_score(t, cands):
    # pa 面板为月末截面；调仓日为当月首个交易日，取上一个已完成月末（与域同键）
    idx = np.searchsorted(me_ts, np.datetime64(t), side='right') - 1
    me_key = me_ts[idx] if idx >= 0 else None
    z = Z1.loc[t].reindex(cands)
    p = pa_by_date.get(me_key, pd.Series(dtype=float)).reindex(cands)
    b = BIAS.loc[t].reindex(cands)
    rz, rp, rb = z.rank(pct=True), p.rank(pct=True), (-b).rank(pct=True)
    return (rz + rp + rb) / 3


def weights_for(arm, t):
    dom = domain_for(t)
    bad = bad_at(t)
    cands = [s for s in C.columns if s in dom and s not in bad]
    if len(cands) < 50:
        return {}
    if arm == 'pool_ew':
        w = pd.Series(1.0, index=cands)
    elif arm == 'enhance_z1':
        rk = Z1.loc[t].reindex(cands).rank(pct=True)
        w = 1.0 + 0.5 * (rk - 0.5)
    elif arm == 'enhance_fuse':
        rk = fuse_score(t, cands).rank(pct=True)
        w = 1.0 + 0.5 * (rk - 0.5)
    elif arm == 'q4_fuse':
        f = fuse_score(t, cands)
        rk = f.rank(pct=True)
        sel = rk[(rk >= 0.60) & (rk <= 0.80)].index.tolist()
        if len(sel) < 20:
            return {}
        return {s: 1.0 / len(sel) for s in sel}
    else:
        return {}
    w = w.replace([np.inf, -np.inf], np.nan).dropna()
    if w.sum() <= 0:
        return {}
    return (w / w.sum()).to_dict()


def run_arm(arm, cost):
    cash, holdings, navs, turns = 1.0, {}, [], []
    for i, d in enumerate(month_first[:-1]):
        cal_pos = cal.get_loc(d)
        buy_day = cal[cal_pos + 1]
        exit_d = month_first[i + 1]
        exit_pos = cal.get_loc(exit_d)
        sell_day = cal[min(exit_pos + 1, len(cal) - 1)]
        new_h = weights_for(arm, d)
        o_buy = O.loc[buy_day]
        new_h = {s: w for s, w in new_h.items() if pd.notna(o_buy.get(s, np.nan)) and o_buy.get(s, 0) > 0}
        if holdings:
            old, new = set(holdings), set(new_h)
            turnover = (len(old - new) + len(new - old)) / 2 / max(len(new), 1)
        else:
            turnover = 1.0
        cash *= (1 - cost * turnover)
        turns.append(turnover)
        holdings = new_h
        o_sell = O.loc[sell_day]
        rets, wsum = [], 0.0
        for s, w in holdings.items():
            b, sl = o_buy.get(s, np.nan), o_sell.get(s, np.nan)
            if pd.notna(b) and pd.notna(sl) and b > 0:
                rets.append(w * (sl / b - 1))
                wsum += w
        cash *= (1 + (sum(rets) / wsum if wsum > 0 else 0.0))
        navs.append((exit_d, cash, len(holdings)))
    df = pd.DataFrame(navs, columns=['datetime', 'nav', 'n']).set_index('datetime')
    return df, float(np.mean(turns)) if turns else np.nan


COSTS = {'base': 0.0015, 'stress': 0.0040, 'microcap': 0.0080}
ARMS = ['enhance_fuse', 'enhance_z1', 'q4_fuse', 'pool_ew']

print('\n[bt] 4 臂 × 3 成本 ...', flush=True)
rows, nav_store = [], {}
for arm, (cname, cost) in itertools.product(ARMS, COSTS.items()):
    df, avg_turn = run_arm(arm, cost)
    if df.empty:
        continue
    r = df['nav'].pct_change().dropna()
    years = (df.index[-1] - df.index[0]).days / 365.25
    cagr = df['nav'].iloc[-1] ** (1 / years) - 1
    mdd = (df['nav'] / df['nav'].cummax() - 1).min()
    ir = r.mean() / r.std() * np.sqrt(12) if r.std() > 0 else np.nan
    rows.append({'arm': arm, 'cost': cname, 'CAGR': cagr, 'IR': ir, 'MDD': mdd,
                 'final_nav': df['nav'].iloc[-1], 'avg_monthly_turnover': avg_turn})
    nav_store[f'{arm}_{cname}'] = df['nav']
    print(f'  {arm} {cname}: CAGR={cagr:+.1%} IR={ir:.2f} MDD={mdd:.1%} 月均换手={avg_turn:.1%}', flush=True)

bt = pd.DataFrame(rows)
bt.to_csv(OUT / 'backtest_summary.csv', index=False)

cr = []
for k, nav in nav_store.items():
    seg = nav.loc[CRASH[0]:CRASH[1]]
    if len(seg) > 2:
        cr.append({'nav': k, 'crash_return': seg.iloc[-1] / seg.iloc[0] - 1})
pd.DataFrame(cr).to_csv(OUT / 'crash_2024.csv', index=False)

print('\n=== 判定（microcap 成本 vs pool_ew） ===')
pool = bt[(bt['arm'] == 'pool_ew') & (bt['cost'] == 'microcap')]['CAGR'].iloc[0]
dec = []
for _, r in bt[(bt['cost'] == 'microcap')].iterrows():
    if r['arm'] == 'pool_ew':
        continue
    ex = r['CAGR'] - pool
    tier = ('mainboard20_construction_works' if (ex >= 0.03 and r['IR'] >= 0.5)
            else ('mainboard20_marginal' if ex > 0 else 'mainboard20_construction_dead'))
    dec.append({'arm': r['arm'], 'CAGR': r['CAGR'], 'pool_CAGR': pool, 'excess': ex,
                'IR': r['IR'], 'MDD': r['MDD'], 'turnover': r['avg_monthly_turnover'], 'tier': tier})
dd = pd.DataFrame(dec)
dd.to_csv(OUT / 'decision_excess.csv', index=False)
print(dd.round(4).to_string(index=False))

decision = {'protocol': 'research/protocols/mainboard20_enhance_protocol_v1.md',
            'pool_cagr_microcap': float(pool),
            'arms': dd.to_dict('records'),
            'summary': {t: int((dd['tier'] == t).sum()) for t in dd['tier'].unique()}}
(OUT / 'decision.json').write_text(json.dumps(decision, ensure_ascii=False, indent=2) + '\n')
print(json.dumps({'summary': decision['summary']}, ensure_ascii=False))
