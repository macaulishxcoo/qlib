#!/usr/bin/env python3
"""微盘引擎风险工程 v1（协议 microcap_engineering_protocol_v1）。

实验一：3 状态变量 × 半仓减仓规则（V1 回撤 / V2 成交额比 / V3 风格差）+ 并集臂。
实验二：enhance 截断 top150/100/50（可执行性）vs 全池 vs top30 对照。
共用数据层与 fusion_v1 脚本（Z_final 五簇融合 + 干净微盘域 + 月度 T+1 开盘）。
成本 0.8% microcap 单边。判定门槛见协议 §3/§4。
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
OUT1 = ROOT / 'output/analysis_fundamental/microcap_risk_engineering_v1'
OUT2 = ROOT / 'output/analysis_fundamental/microcap_topn_exec_v1'
for d in (OUT1, OUT2):
    d.mkdir(parents=True, exist_ok=True)

START, END = '2018-06-01', '2026-08-31'
BT_START = pd.Timestamp('2022-01-04')
CRASH = (pd.Timestamp('2024-01-01'), pd.Timestamp('2024-02-29'))
COST = 0.0080  # microcap 单边

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
FIELDS = ['open', 'high', 'low', 'close', 'vwap', 'volume']
panels = {f: pd.DataFrame({s: read_bin(s, f) for s in symbols if read_bin(s, f) is not None}).reindex(cal)
          for f in FIELDS}
O, H, L, C, VW, V = (panels[f] for f in FIELDS)
RET = C.pct_change()
FAC = pd.DataFrame({s: read_bin(s, 'factor') for s in symbols if read_bin(s, 'factor') is not None}).reindex(cal)
AMT20 = ((C / FAC) * V * 100).rolling(20).mean()


def cs_rank(df):
    return df.rank(axis=1, pct=True)


def ts_rank(df, w):
    return df.rolling(w).apply(lambda x: (x[~np.isnan(x)] <= x[-1]).mean() if np.isfinite(x).any() else np.nan, raw=True)


# ---------------- 五簇融合信号（fusion closure 复现） ----------------
print('[signal] 五簇 ...', flush=True)
F13 = -cs_rank(cs_rank(C).rolling(5).cov(cs_rank(V)))
F16 = -cs_rank(cs_rank(H).rolling(5).cov(cs_rank(V)))
F15 = -cs_rank(cs_rank(H).rolling(3).corr(cs_rank(V)))
z1 = (F13 + F15 + F16) / 3 + np.sign(V.diff(1)) * (-1 * C.diff(1))
F3 = -cs_rank(O).rolling(10).corr(cs_rank(V))
F6 = -1 * O.rolling(10).corr(V)
F14 = -cs_rank(RET.diff(3)) * O.rolling(10).corr(V)
z1 += (F14 + F3 + F6) / 3
z1 += -ts_rank(cs_rank(L), 9)
F19 = -1 * np.sign((C - C.shift(7)) + C.diff(7)) * (1 + cs_rank(1 + RET.rolling(250).sum()))
z1 += F19
tsmin_low5 = L.rolling(5).min()
F52 = ((-1 * tsmin_low5 + tsmin_low5.shift(5))
       * cs_rank((RET.rolling(240).sum() - RET.rolling(20).sum()) / 220) * ts_rank(V, 5))
z1 += F52
Z1 = z1 / 6
del F13, F16, F15, F3, F6, F14, F19, F52, z1

fi = pd.read_csv(ROOT / 'data/external/tushare/a_share_financial_pit_v1/normalized/fina_indicator.csv.gz',
                 compression='gzip', low_memory=False,
                 usecols=['ts_code', 'end_date', 'ann_date', 'available_date', 'gross_margin', 'roa'])
for c in ('end_date', 'available_date'):
    fi[c] = pd.to_datetime(fi[c].astype(str).str.replace('-', '', regex=False), format='%Y%m%d', errors='coerce')
fi = fi.dropna(subset=['available_date']).drop_duplicates(['ts_code', 'end_date', 'available_date'], keep='last')
fi = fi.sort_values(['ts_code', 'end_date'])
fi['gpm_prev4'] = fi.groupby('ts_code')['gross_margin'].shift(4)
fi['delta_gpm'] = fi['gross_margin'] - fi['gpm_prev4']
fi['roa_prev4'] = fi.groupby('ts_code')['roa'].shift(4)
fi['pa'] = fi['roa'] - fi['roa_prev4']

db = pd.read_csv(ROOT / 'data/external/tushare/a_share_daily_basic_pit_v1/normalized/daily_basic.csv.gz',
                 compression='gzip', usecols=['ts_code', 'trade_date', 'total_mv', 'total_share'],
                 dtype={'trade_date': str})
db['dt'] = pd.to_datetime(db['trade_date'], format='%Y%m%d')
db = db[~db['ts_code'].str.split('.').str[0].str.startswith(('43', '83', '87', '92', '920'))]
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


ts_daily = rename_qlib(pd.DataFrame(snap_ts).T).reindex(columns=C.columns).reindex(cal, method='ffill') * 1e4
turn = (V * 100) / ts_daily.where(ts_daily > 0)
sd21 = turn.rolling(21).std()
sd252 = turn.rolling(252).std()
S_bias = sd21 / sd252 - 1
sd42_504 = turn.rolling(42).std()
sd504 = turn.rolling(504).std()
S_bias42 = sd42_504 / sd504 - 1
dif = C.ewm(span=12, adjust=False).mean() - C.ewm(span=26, adjust=False).mean()
S_macd = 2 * (dif - dif.ewm(span=9, adjust=False).mean())
S_std21 = RET.rolling(21).std()

FI_SIGNALS = {'delta_gpm': fi.set_index('ts_code')[['delta_gpm', 'available_date', 'end_date']],
              'pa': fi.set_index('ts_code')[['pa', 'available_date', 'end_date']]}
DAILY_SIGNALS = {'Z1': Z1, 'bias_21_252': S_bias, 'bias_42_504': S_bias42, 'MACD_neg': -S_macd, 'std_21d_neg': -S_std21}


def qlib_idx(ts_codes):
    return [f"{c.split('.')[1].lower()}{c.split('.')[0]}" for c in ts_codes]


# ---------------- 域（同 fusion） ----------------
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
me_domain = np.array(sorted(domain_by_month))


def domain_for(t):
    idx = np.searchsorted(me_domain, np.datetime64(t), side='right') - 1
    return domain_by_month[me_domain[idx]] if idx >= 0 else set()


def bad_at(t):
    mask = (st_start <= np.datetime64(t)) & (st_end >= np.datetime64(t)) & st_bad
    return {s.lower() for s in st_code[mask]}


# 主板末20%域（V3 状态变量用, 同 mainboard 线口径: 主板=60/00 开头, 末20%）
domain_mb20_by_month = {}
for d in month_end_all:
    if not (pd.Timestamp('2021-12-01') <= d <= pd.Timestamp(END)):
        continue
    mv = snap_mv[d]
    universe = set(mv.dropna().index)
    main_codes = [c for c in universe if c.split('.')[0].startswith(('60', '00'))]
    mvs = mv[mv.index.isin(main_codes)]
    thr = mvs.quantile(0.20)
    bottom = set(mvs[mvs <= thr].index)
    mask = (st_start <= np.datetime64(d)) & (st_end >= np.datetime64(d)) & st_bad
    bad = set(st_code[mask])
    domain_mb20_by_month[d] = {sym_of(c) for c in (bottom - bad) & universe}
mb_me = np.array(sorted(domain_mb20_by_month))


def mb20_for(t):
    idx = np.searchsorted(mb_me, np.datetime64(t), side='right') - 1
    return domain_mb20_by_month[mb_me[idx]] if idx >= 0 else set()


# ---------------- 状态变量（协议 §2） ----------------
print('[state] 状态变量 ...', flush=True)
dom_sets = {d: domain_by_month[d] for d in me_domain}
# V1: 微盘域等权日收益 → 20 日回撤
daily_eq_ret = {}
daily_mb20_ret = {}
daily_amt = {}
for d in cal:
    if d < pd.Timestamp('2021-12-01'):
        continue
    dom = domain_for(d)
    if not dom:
        continue
    cols = [s for s in C.columns if s in dom]
    r = C.loc[d, cols] / C.shift(1).loc[d, cols] - 1
    daily_eq_ret[d] = r.mean()
    # V2: 域内总成交额
    amt = ((C / FAC).loc[d, cols] * V.loc[d, cols] * 100).sum()
    daily_amt[d] = amt
    m20 = mb20_for(d)
    if m20:
        cols20 = [s for s in C.columns if s in m20]
        r20 = C.loc[d, cols20] / C.shift(1).loc[d, cols20] - 1
        daily_mb20_ret[d] = r20.mean()

eq_ret = pd.Series(daily_eq_ret).sort_index()
mb20_ret = pd.Series(daily_mb20_ret).sort_index()
amt_ser = pd.Series(daily_amt).sort_index()
nav_eq = (1 + eq_ret).cumprod()
V1 = nav_eq / nav_eq.rolling(20).max() - 1  # 20 日回撤（负值）
V2 = amt_ser.rolling(20).mean() / amt_ser.rolling(250).mean()
# V3: 主板末20% 与微盘 20 日累计收益差（pp）
mb20_20d = (1 + mb20_ret).rolling(20).apply(np.prod, raw=True) - 1
eq_20d = (1 + eq_ret).rolling(20).apply(np.prod, raw=True) - 1
V3 = (mb20_20d - eq_20d) * 100

state = pd.DataFrame({'V1': V1, 'V2': V2, 'V3': V3})
state.to_csv(OUT1 / 'state_variables_daily.csv')
# 危机段及时性报告
crash_days = state.loc[CRASH[0]:CRASH[1]]
print('2024-01/02 危机段状态变量（周采样）:')
print(crash_days.iloc[::5].round(3).to_string())

# ---------------- Z_final（五簇: Z1 / delta_gpm+pa / bias / MACD / std21） ----------------
print('[signal] Z_final ...', flush=True)
CLUSTERS = [['Z1'], ['delta_gpm', 'pa'], ['bias_42_504', 'bias_21_252'], ['MACD_neg'], ['std_21d_neg']]
Z_final = None
for comp in CLUSTERS:
    parts = [cs_rank(DAILY_SIGNALS[s]) for s in comp if s in DAILY_SIGNALS]
    for s in comp:
        if s in FI_SIGNALS:
            df = FI_SIGNALS[s]
            snaps = {}
            for d in me_domain:
                if d < pd.Timestamp('2021-12-01') or d > pd.Timestamp(END):
                    continue
                sub = df[df['available_date'] <= d].sort_values(['end_date', 'available_date']).groupby('ts_code').tail(1)
                sr = sub[s].replace([np.inf, -np.inf], np.nan).dropna()
                snaps[d] = pd.Series(sr.values, index=qlib_idx(sr.index)).rank(pct=True)
            parts.append(pd.DataFrame(snaps).T.reindex(cal).ffill())
    z = sum(parts) / len(parts)
    Z_final = z if Z_final is None else Z_final + z
Z_final = Z_final / len(CLUSTERS)

# ---------------- 回测（月度 T+1 开盘, enhance 权重, 半仓状态可叠加） ----------------
trading_days = cal[cal >= BT_START]
td_s = pd.Series(trading_days, index=trading_days)
mf = [d for d in td_s.groupby(trading_days.to_period('M')).min().sort_values()
      if np.searchsorted(me_domain, np.datetime64(d), side='right') - 1 >= 0]
print(f'[bt] 调仓月数={len(mf)}', flush=True)

F_V1 = (V1 < -0.08).fillna(False)   # 日频布尔触发序列
F_V2 = (V2 < 0.7).fillna(False)
F_V3 = (V3 > 3.0).fillna(False)
FIRE = {'v1_dd_half': F_V1, 'v2_amt_half': F_V2, 'v3_style_half': F_V3}
F_COMBO = F_V1 | F_V2 | F_V3
# 解除条件: 连续 5 日未触发
F_CLEAR = {}
for _k, _f in list(FIRE.items()) + [('combo_or', F_COMBO)]:
    _g = _f.rolling(5).sum()
    F_CLEAR[_k] = (_g == 0) & _f.notna()


def run(arm, cost=COST, top_n=None):
    """月度调仓（T 收盘生成目标, T+1 开盘成交）+ 日频状态乘数（T 收盘判断, T+1 开盘执行）。
    会计: 逐票市值随价格漂移（真实买入持有）, NAV = 现金 + Σ v_i。"""
    nav, cash = 1.0, 1.0
    v = {}  # sym -> 市值(NAV 单位)
    navs, turns = [], []
    weight_state = 1.0
    pending_swap = None   # (fill_day, {sym: w}, to)
    pending_state = None  # (exec_day, multiplier)
    trigger_log = []
    is_state_arm = arm in FIRE or arm == 'combo_or'
    if is_state_arm:
        fire_ser = F_COMBO if arm == 'combo_or' else FIRE[arm]
        clear_ser = F_CLEAR[arm]
    else:
        fire_ser = clear_ser = None

    for idx, t in enumerate(trading_days):
        if t < mf[0] or idx >= len(trading_days) - 2:
            continue
        i = CIDX[t]
        # ---- 1) 当日计价: 持仓自 (t-1) 开盘持有至 t 开盘（停牌冻结, 比例成本日不计） ----
        port_dv = 0.0
        for s, vi in v.items():
            j = SIDX.get(s)
            r = 0.0
            if j is not None:
                c0, c1 = RN[i, j], ON[i, j]
                if np.isfinite(c0) and np.isfinite(c1) and c0 > 0:
                    r = c1 / c0 - 1
            vi_new = vi * (1 + r)
            port_dv += vi_new - vi
            v[s] = vi_new
        nav += port_dv
        # ---- 2) T 开盘执行（计价之后: 今天开盘前的收益归旧持仓） ----
        # a. 状态切换
        if is_state_arm and pending_state is not None and pending_state[0] == t:
            new_st = pending_state[1]
            inv = sum(v.values())
            if inv > 0:
                if new_st < weight_state:
                    frac_sell = (weight_state - new_st) / max(weight_state, 1e-9)
                    nav -= inv * frac_sell * cost
                    for s in v:
                        v[s] *= (1 - frac_sell)
                elif new_st > weight_state and cash > 0:
                    frac_buy = min((new_st - weight_state) / max(weight_state, 1e-9), cash / inv)
                    nav -= inv * frac_buy * cost
                    for s in v:
                        v[s] *= (1 + frac_buy)
            weight_state = new_st
            pending_state = None
        # b. 调仓成交（全部卖出 → 按目标权重买入, 单次换手成本）
        if pending_swap is not None and pending_swap[0] == t:
            _, w, to = pending_swap
            nav *= (1 - cost * to)
            v = {}
            for s, wi in w.items():
                j = SIDX.get(s)
                if j is not None and np.isfinite(ON[i, j]) and ON[i, j] > 0:
                    v[s] = wi * weight_state * nav
            cash = nav - sum(v.values())
            turns.append(to)
            pending_swap = None
        cash = nav - sum(v.values())
        navs.append((t, nav, len(v)))
        # ---- 3) T 收盘: 状态判断（T+1 开盘生效）+ 调仓目标生成（T+1 开盘成交） ----
        if is_state_arm:
            if bool(fire_ser.at[t]):
                if weight_state == 1.0 and pending_state is None:
                    pending_state = (trading_days[idx + 1], 0.5)
                    trigger_log.append(str(t.date()))
            elif weight_state == 0.5 and pending_state is None and bool(clear_ser.at[t]):
                pending_state = (trading_days[idx + 1], 1.0)
        if t in mf_set:
            dom = domain_for(t)
            bad = bad_at(t)
            cands = [s for s in C.columns if s in dom and s not in bad]
            if len(cands) >= 50:
                z = Z_final.loc[t].reindex(cands).dropna()
                if len(z):
                    if arm == 'pool_ew':
                        w = pd.Series(1.0, index=z.index)
                        w = w / w.sum()
                    elif top_n:
                        top = z.nlargest(top_n).index
                        wz = 1.0 + 0.5 * (z.loc[top].rank(pct=True) - 0.5)
                        w = wz / wz.sum()
                    else:
                        w = 1.0 + 0.5 * (z.rank(pct=True) - 0.5)
                        w = w / w.sum()
                    old, new = set(v), set(w.index)
                    to = (len(old - new) + len(new - old)) / 2 / max(len(new), 1) if new else 1.0
                    pending_swap = (trading_days[idx + 1], w.to_dict(), to)
    df = pd.DataFrame(navs, columns=['datetime', 'nav', 'n']).set_index('datetime')
    return df, (float(np.mean(turns)) if turns else np.nan), trigger_log


mf_set = set(mf)
D_RET = O.shift(1)         # 开盘→开盘口径（与 fusion 月频引擎一致）
CN = O.to_numpy()
RN = D_RET.to_numpy()
ON = O.to_numpy()
CIDX = {d: i for i, d in enumerate(cal)}
SIDX = {s: j for j, s in enumerate(C.columns)
        if True}
print('\n[exp1] 状态减仓臂 ...', flush=True)
ARMS1 = ['base_enhance', 'v1_dd_half', 'v2_amt_half', 'v3_style_half', 'combo_or']
rows, navs1, trig_summary = [], {}, {}
for arm in ARMS1:
    df, to, tlog = run(arm)
    r_d = df['nav'].pct_change().dropna()
    r_m = df['nav'].resample('ME').last().pct_change().dropna()
    years = (df.index[-1] - df.index[0]).days / 365.25
    cagr = df['nav'].iloc[-1] ** (1 / years) - 1
    mdd = (df['nav'] / df['nav'].cummax() - 1).min()
    ir = r_m.mean() / r_m.std() * np.sqrt(12) if r_m.std() > 0 else np.nan
    seg = df['nav'].loc[CRASH[0]:CRASH[1]]
    crash_ret = seg.iloc[-1] / df['nav'].loc[:CRASH[0]].iloc[-1] - 1 if len(seg) else np.nan
    rows.append({'arm': arm, 'CAGR': cagr, 'IR': ir, 'MDD': mdd, 'final_nav': df['nav'].iloc[-1],
                 'avg_turnover': to, 'n_trigger_days': len(tlog), 'crash_2024': crash_ret})
    navs1[arm] = df['nav']
    trig_summary[arm] = tlog
    df['nav'].to_csv(OUT1 / f'nav_{arm}.csv')
    print(f'  {arm}: CAGR={cagr:+.1%} IR={ir:.2f} MDD={mdd:.1%} 触发月={len(tlog)} 崩盘段={crash_ret:+.1%}', flush=True)

bt1 = pd.DataFrame(rows)
bt1.to_csv(OUT1 / 'backtest_summary.csv', index=False)
json.dump(trig_summary, open(OUT1 / 'trigger_log.json', 'w'), ensure_ascii=False, indent=1)

# 判定（协议 §3）
base = bt1[bt1['arm'] == 'base_enhance'].iloc[0]
dec1 = []
for _, r in bt1.iterrows():
    if r['arm'] == 'base_enhance':
        continue
    mdd_gain = r['MDD'] - base['MDD']  # 正值=MDD 变浅
    if r['MDD'] >= -0.20 and r['CAGR'] >= 0.18:
        tier = 'risk_engineering_passed'
    elif mdd_gain >= 0.05 and r['CAGR'] < 0.18:
        tier = 'risk_mdd_fixed_cost_high'
    elif mdd_gain < 0.02:
        tier = 'state_variable_dead'
    else:
        tier = 'mdd_improved_partial'
    dec1.append({'arm': r['arm'], 'tier': tier, 'MDD_gain': mdd_gain,
                 'CAGR_cost': r['CAGR'] - base['CAGR']})
dd1 = pd.DataFrame(dec1)
dd1.to_csv(OUT1 / 'decision_exp1.csv', index=False)
print(dd1.round(4).to_string(index=False))

print('\n[exp2] 截断臂 ...', flush=True)
ARMS2 = [('enhance_full', None), ('enhance_top150', 150), ('enhance_top100', 100),
         ('enhance_top50', 50), ('top30_ew', 30), ('pool_ew', None)]
rows2, navs2 = [], {}
for arm, tn in ARMS2:
    df, to, _ = run(arm, top_n=tn)
    r_m2 = df['nav'].resample('ME').last().pct_change().dropna()
    years = (df.index[-1] - df.index[0]).days / 365.25
    cagr = df['nav'].iloc[-1] ** (1 / years) - 1
    mdd = (df['nav'] / df['nav'].cummax() - 1).min()
    ir = r_m2.mean() / r_m2.std() * np.sqrt(12) if r_m2.std() > 0 else np.nan
    rows2.append({'arm': arm, 'CAGR': cagr, 'IR': ir, 'MDD': mdd, 'avg_turnover': to})
    navs2[arm] = df['nav']
    df['nav'].to_csv(OUT2 / f'nav_{arm}.csv')
    print(f'  {arm}: CAGR={cagr:+.1%} IR={ir:.2f} MDD={mdd:.1%} 换手={to:.1%}', flush=True)

bt2 = pd.DataFrame(rows2)
bt2.to_csv(OUT2 / 'backtest_summary.csv', index=False)

pool_c = bt2[bt2['arm'] == 'pool_ew']['CAGR'].iloc[0]
full_c = bt2[bt2['arm'] == 'enhance_full']['CAGR'].iloc[0]
full_ex = full_c - pool_c
full_mdd = bt2[bt2['arm'] == 'enhance_full']['MDD'].iloc[0]
dec2 = []
for _, r in bt2.iterrows():
    if r['arm'] in ('pool_ew', 'enhance_full'):
        continue
    ex = r['CAGR'] - pool_c
    tier = 'executable' if (ex >= 0.7 * full_ex and r['MDD'] >= full_mdd - 0.02) else 'insufficient'
    dec2.append({'arm': r['arm'], 'excess': ex, 'retention': ex / full_ex if full_ex > 0 else np.nan,
                 'tier': tier})
dd2 = pd.DataFrame(dec2)
dd2.to_csv(OUT2 / 'decision_exp2.csv', index=False)
print(dd2.round(4).to_string(index=False))

json.dump({'protocol': 'research/protocols/microcap_engineering_protocol_v1.md',
           'exp1_base': base.to_dict(), 'exp1_decisions': dd1.to_dict('records'),
           'exp2_full_excess': float(full_ex), 'exp2_decisions': dd2.to_dict('records')},
          open(OUT1 / 'decision.json', 'w'), ensure_ascii=False, indent=2)
print('\n完成:', OUT1, OUT2)
