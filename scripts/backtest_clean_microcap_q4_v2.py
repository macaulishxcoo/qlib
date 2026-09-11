#!/usr/bin/env python3
"""干净微盘 3.0：Q4 型构造组合回测 v2（协议 clean_microcap_q4_protocol_v2）。

臂: q4_band(60-80分位) / q4_liq(+流动性下限) / q4_over(40-85分位) /
    enhance(全池加权) / pool_ew(对照) / a19_top(单因子top30)
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
QLIB_DIR = Path(os.path.expanduser('~')) / '.qlib/qlib_data/cn_data_2026'
OUT = ROOT / 'output/analysis_fundamental/clean_microcap_q4_v2'
OUT.mkdir(parents=True, exist_ok=True)

START, END = '2021-01-01', '2026-08-31'
BT_START = pd.Timestamp('2022-01-01')
CRASH = (pd.Timestamp('2024-01-01'), pd.Timestamp('2024-02-29'))

CANDS = ['alpha101_13', 'alpha101_16', 'alpha101_15', 'alpha101_12', 'alpha101_3',
         'alpha101_6', 'alpha101_4', 'alpha101_19', 'alpha101_52', 'alpha101_14']
CLUSTERS = [['alpha101_13', 'alpha101_15', 'alpha101_16'], ['alpha101_12'],
            ['alpha101_14', 'alpha101_3', 'alpha101_6'], ['alpha101_4'],
            ['alpha101_19'], ['alpha101_52']]

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

print('[data] 加载面板 ...', flush=True)
FIELDS = ['open', 'high', 'low', 'close', 'vwap', 'volume']
panels = {f: pd.DataFrame({s: read_bin(s, f) for s in symbols if read_bin(s, f) is not None}).reindex(cal)
          for f in FIELDS}
O, H, L, C, VW, V = (panels[f] for f in FIELDS)
RET = C.pct_change()
# 20日均成交额(元): qlib volume 单位为手(100股)且 close 为后复权,
# 正确口径 = (close/factor) * volume * 100（已用 market_daily_v1 实际 amount 校验, 误差<3%）
FACTOR = pd.DataFrame({s: read_bin(s, 'factor') for s in symbols if read_bin(s, 'factor') is not None}).reindex(cal)
AMT20 = ((C / FACTOR) * V * 100).rolling(20).mean()

print('[factor] 信号 ...', flush=True)


def cs_rank(df):
    return df.rank(axis=1, pct=True)


def ts_rank(df, w):
    return df.rolling(w).apply(lambda x: (x[~np.isnan(x)] <= x[-1]).mean() if np.isfinite(x).any() else np.nan, raw=True)


F = {}
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
Z1 = None
for comp in CLUSTERS:
    z = None
    for fn in comp:
        r = cs_rank(F[fn])
        z = r if z is None else z + r
    z = z / len(comp)
    Z1 = z if Z1 is None else Z1 + z
Z1 = Z1 / len(CLUSTERS)

# ---------------- 域 ----------------
print('[domain] ...', flush=True)
db = pd.read_csv(ROOT / 'data/external/tushare/a_share_daily_basic_pit_v1/normalized/daily_basic.csv.gz',
                 compression='gzip', usecols=['ts_code', 'trade_date', 'total_mv'], dtype={'trade_date': str})
db['dt'] = pd.to_datetime(db['trade_date'], format='%Y%m%d')
db = db[~db['ts_code'].str.split('.').str[0].str.startswith(('43', '83', '87', '92', '920'))]
month_end = db.groupby(db['dt'].dt.to_period('M'))['dt'].max().sort_values()
snap = {}
for d in month_end:
    g = db[db['dt'] == d]
    snap[d] = pd.Series(g['total_mv'].values / 1e4, index=g['ts_code'].values)

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
bps = fin[['ts_code', 'end_date', 'available_date', 'bps']].copy()
bps = bps.sort_values(['ts_code', 'end_date', 'available_date']).drop_duplicates(['ts_code', 'end_date'], keep='last').dropna(subset=['bps'])


def quasi_at(t):
    t64 = np.datetime64(t)
    sub = inc[inc['available_date'] <= t64].sort_values(['ts_code', 'end_date'])
    last2 = sub.groupby('ts_code').tail(2)
    g = last2.groupby('ts_code')['loss'].agg(['count', 'sum'])
    two = set(g[(g['count'] >= 2) & (g['sum'] >= 2)].index)
    sb = bps[bps['available_date'] <= t64].sort_values(['ts_code', 'end_date']).groupby('ts_code').tail(1)
    neg = set(sb[sb['bps'] < 0]['ts_code'])
    return two | neg


def sym_of(c):
    n, e = c.split('.')
    return f'{e.lower()}{n}'


domain_by_month = {}
for d in month_end:
    if not (pd.Timestamp('2021-12-01') <= d <= pd.Timestamp(END)):
        continue
    mv = snap[d]
    universe = set(mv.dropna().index)
    thr = mv.quantile(0.10)
    bottom = set(mv[mv <= thr].index)
    mask = (st_start <= np.datetime64(d)) & (st_end >= np.datetime64(d)) & st_bad
    bad = set(st_code[mask])
    quasi = quasi_at(d) & universe
    domain_by_month[d] = {sym_of(c) for c in (bottom - bad - quasi) & universe}
me_ts = np.array(sorted(domain_by_month))

# 月度调仓日：每月第一个交易日
trading_days = cal[cal >= BT_START]
td_s = pd.Series(trading_days, index=trading_days)
month_first = [d for d in td_s.groupby(trading_days.to_period('M')).min().sort_values()
               if np.searchsorted(me_ts, np.datetime64(d), side='right') - 1 >= 0]
print(f'[bt] 调仓月数={len(month_first)}', flush=True)


def domain_for(t):
    idx = np.searchsorted(me_ts, np.datetime64(t), side='right') - 1
    return domain_by_month[me_ts[idx]] if idx >= 0 else set()


def bad_at(t):
    mask = (st_start <= np.datetime64(t)) & (st_end >= np.datetime64(t)) & st_bad
    return {s.lower() for s in st_code[mask]}


# ---------------- 持仓生成 ----------------
def holdings_for(arm: str, t) -> dict[str, float]:
    dom = domain_for(t)
    bad = bad_at(t)
    cands = [s for s in C.columns if s in dom and s not in bad]
    if len(cands) < 50:
        return {}
    if arm == 'pool_ew':
        sel = cands
        w = 1.0 / len(sel)
        return {s: w for s in sel}
    if arm == 'a19_top':
        z = F['alpha101_19'].loc[t].reindex(cands).dropna()
        top = z.nlargest(30).index.tolist()
        return {s: 1 / len(top) for s in top} if len(top) >= 20 else {}
    # Z1 分位臂
    z = Z1.loc[t].reindex(cands).dropna()
    rk = z.rank(pct=True)
    if arm == 'q4_liq':
        lo, hi = 0.60, 0.80
    else:
        lo, hi = {'q4_band': (0.60, 0.80), 'q4_over': (0.40, 0.85)}[arm]
    sel = rk[(rk >= lo) & (rk <= hi)].index.tolist()
    if arm == 'q4_liq':
        amt = AMT20.loc[t].reindex(sel)
        sel = [s for s in sel if pd.notna(amt.get(s, np.nan)) and amt.get(s, 0) >= 30_000_000]
    if len(sel) < 20:
        return {}
    return {s: 1 / len(sel) for s in sel}


def weights_for(arm: str, t) -> dict[str, float]:
    if arm != 'enhance':
        return holdings_for(arm, t)
    dom = domain_for(t)
    bad = bad_at(t)
    cands = [s for s in C.columns if s in dom and s not in bad]
    if len(cands) < 50:
        return {}
    z = Z1.loc[t].reindex(cands)
    rk = z.rank(pct=True)
    w = 1.0 + 0.5 * (rk - 0.5)
    w = w / w.sum()
    return w.dropna().to_dict()


# ---------------- 回测 ----------------
def run_arm(arm: str, cost: float):
    cash = 1.0
    holdings = {}
    navs = []
    turns = []
    for i, d in enumerate(month_first[:-1]):
        cal_pos = cal.get_loc(d)
        buy_day = cal[cal_pos + 1]
        exit_d = month_first[i + 1]
        exit_pos = cal.get_loc(exit_d)
        sell_day = cal[min(exit_pos + 1, len(cal) - 1)]
        # 新持仓（T+1 开盘成交）
        new_h = weights_for(arm, d)
        o_buy = O.loc[buy_day]
        new_h = {s: w for s, w in new_h.items() if pd.notna(o_buy.get(s, np.nan)) and o_buy.get(s, 0) > 0}
        # 换手成本（双边）
        if holdings:
            old = set(holdings)
            new = set(new_h)
            turnover = (len(old - new) + len(new - old)) / 2 / max(len(new), 1)
        else:
            turnover = 1.0
        cash *= (1 - cost * turnover)
        turns.append(turnover)
        holdings = new_h
        # 持有期收益：buy_day 开盘 -> sell_day 开盘，逐票
        o_sell = O.loc[sell_day]
        rets, wsum = [], 0.0
        for s, w in holdings.items():
            b = o_buy.get(s, np.nan)
            sl = o_sell.get(s, np.nan)
            if pd.notna(b) and pd.notna(sl) and b > 0:
                rets.append(w * (sl / b - 1))
                wsum += w
        port = sum(rets) / wsum if wsum > 0 else 0.0
        cash *= (1 + port)
        navs.append((exit_d, cash, len(holdings)))
    df = pd.DataFrame(navs, columns=['datetime', 'nav', 'n']).set_index('datetime')
    return df, float(np.mean(turns)) if turns else np.nan


COSTS = {'base': 0.0015, 'stress': 0.0040, 'microcap': 0.0080}
ARMS = ['q4_band', 'q4_liq', 'q4_over', 'enhance', 'pool_ew', 'a19_top']

print('\n[bt] 5 臂 × 3 成本 ...', flush=True)
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

# 崩盘段
cr = []
for k, nav in nav_store.items():
    seg = nav.loc[CRASH[0]:CRASH[1]]
    if len(seg) > 2:
        cr.append({'nav': k, 'crash_return': seg.iloc[-1] / seg.iloc[0] - 1})
pd.DataFrame(cr).to_csv(OUT / 'crash_2024.csv', index=False)

# 判定（microcap vs pool_ew）
print('\n=== 判定（microcap 成本 vs pool_ew） ===')
pool = bt[(bt['arm'] == 'pool_ew') & (bt['cost'] == 'microcap')]['CAGR'].iloc[0]
dec = []
for _, r in bt[(bt['cost'] == 'microcap')].iterrows():
    if r['arm'] == 'pool_ew':
        continue
    ex = r['CAGR'] - pool
    tier = ('q4_construction_works' if (ex >= 0.03 and r['IR'] >= 0.5)
            else ('q4_marginal' if ex > 0 else 'q4_construction_dead'))
    dec.append({'arm': r['arm'], 'CAGR': r['CAGR'], 'pool_CAGR': pool, 'excess': ex,
                'IR': r['IR'], 'MDD': r['MDD'], 'tier': tier})
dd = pd.DataFrame(dec)
dd.to_csv(OUT / 'decision_excess.csv', index=False)
print(dd.round(4).to_string(index=False))

# stress 同向性检查（q4_marginal 才需要）
print('\n=== stress 口径超额 ===')
pool_s = bt[(bt['arm'] == 'pool_ew') & (bt['cost'] == 'stress')]['CAGR'].iloc[0]
for _, r in bt[(bt['cost'] == 'stress') & (bt['arm'].str.startswith('q4'))].iterrows():
    print(f"  {r['arm']}: {r['CAGR']-pool_s:+.1%}")

decision = {'protocol': 'research/protocols/clean_microcap_q4_protocol_v2.md',
            'pool_cagr_microcap': float(pool),
            'arms': dd.to_dict('records'),
            'summary': {t: int((dd['tier'] == t).sum()) for t in dd['tier'].unique()}}
(OUT / 'decision.json').write_text(json.dumps(decision, ensure_ascii=False, indent=2) + '\n')
print(json.dumps({'summary': decision['summary']}, ensure_ascii=False))
