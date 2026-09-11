#!/usr/bin/env python3
"""干净微盘收官双实验 v1（协议 clean_microcap_final_dual_protocol_v1）。

实验一：7 源相关归并 → Z_final 融合 → 月度 enhance 回测（vs Z1 单源）。
实验二：Z1 短周期 enhance（10/15 日持有期）扫描。
两实验共用数据加载与域构建。
"""
from __future__ import annotations

import itertools
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
OUT1 = ROOT / 'output/analysis_fundamental/clean_microcap_fusion_v1'
OUT2 = ROOT / 'output/analysis_fundamental/clean_microcap_shortcycle_v1'
for d in (OUT1, OUT2):
    d.mkdir(parents=True, exist_ok=True)

START, END = '2020-01-01', '2026-08-31'
BT_START = pd.Timestamp('2022-01-04')
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
FIELDS = ['open', 'high', 'low', 'close', 'vwap', 'volume']
panels = {f: pd.DataFrame({s: read_bin(s, f) for s in symbols if read_bin(s, f) is not None}).reindex(cal)
          for f in FIELDS}
O, H, L, C, VW, V = (panels[f] for f in FIELDS)
RET = C.pct_change()
FAC = pd.DataFrame({s: read_bin(s, 'factor') for s in symbols if read_bin(s, 'factor') is not None}).reindex(cal)
C_UNADJ = C / FAC
AMT20 = ((C / FAC) * V * 100).rolling(20).mean()


def cs_rank(df):
    return df.rank(axis=1, pct=True)


def ts_rank(df, w):
    return df.rolling(w).apply(lambda x: (x[~np.isnan(x)] <= x[-1]).mean() if np.isfinite(x).any() else np.nan, raw=True)


# ---------------- 七源信号 ----------------
print('[signal] 七源 ...', flush=True)
# S1 Z1（6 族合成, 同 q4 轮聚类）
z_parts = []
F13 = -cs_rank(cs_rank(C).rolling(5).cov(cs_rank(V)))
F16 = -cs_rank(cs_rank(H).rolling(5).cov(cs_rank(V)))
F15 = -cs_rank(cs_rank(H).rolling(3).corr(cs_rank(V)))
z_parts.append((F13 + F15 + F16) / 3)
z_parts.append(np.sign(V.diff(1)) * (-1 * C.diff(1)))
F3 = -cs_rank(O).rolling(10).corr(cs_rank(V))
F6 = -1 * O.rolling(10).corr(V)
F14 = -cs_rank(RET.diff(3)) * O.rolling(10).corr(V)
z_parts.append((F14 + F3 + F6) / 3)
z_parts.append(-ts_rank(cs_rank(L), 9))
F19 = -1 * np.sign((C - C.shift(7)) + C.diff(7)) * (1 + cs_rank(1 + RET.rolling(250).sum()))
z_parts.append(F19)
tsmin_low5 = L.rolling(5).min()
F52 = ((-1 * tsmin_low5 + tsmin_low5.shift(5))
       * cs_rank((RET.rolling(240).sum() - RET.rolling(20).sum()) / 220) * ts_rank(V, 5))
z_parts.append(F52)
Z1 = sum(z_parts) / len(z_parts)
del F13, F16, F15, F3, F6, F14, F19, F52

# S2 delta_gpm: 毛利率同比差（fina_indicator PIT）
fi = pd.read_csv(ROOT / 'data/external/tushare/a_share_financial_pit_v1/normalized/fina_indicator.csv.gz',
                 compression='gzip', low_memory=False,
                 usecols=['ts_code', 'end_date', 'ann_date', 'available_date', 'gross_margin'])
for c in ('end_date', 'available_date'):
    fi[c] = pd.to_datetime(fi[c].astype(str).str.replace('-', '', regex=False), format='%Y%m%d', errors='coerce')
fi = fi.dropna(subset=['available_date']).drop_duplicates(['ts_code', 'end_date', 'available_date'], keep='last')
fi = fi.sort_values(['ts_code', 'end_date'])
fi['gpm_prev4'] = fi.groupby('ts_code')['gross_margin'].shift(4)
fi['delta_gpm'] = fi['gross_margin'] - fi['gpm_prev4']
fi['available_ord'] = fi['available_date']

# S3 pa: ROA 同比变化（同 growth 轮实现）
fi['roa_prev4'] = fi.groupby('ts_code')['roa' if 'roa' in fi.columns else 'gross_margin'].shift(4) if 'roa' in fi.columns else np.nan
# roa 列需重新载入（上面 usecols 没含）——独立再取
fi_roa = pd.read_csv(ROOT / 'data/external/tushare/a_share_financial_pit_v1/normalized/fina_indicator.csv.gz',
                     compression='gzip', low_memory=False,
                     usecols=['ts_code', 'end_date', 'available_date', 'roa'])
for c in ('end_date', 'available_date'):
    fi_roa[c] = pd.to_datetime(fi_roa[c].astype(str).str.replace('-', '', regex=False), format='%Y%m%d', errors='coerce')
fi_roa = fi_roa.dropna(subset=['available_date']).drop_duplicates(['ts_code', 'end_date', 'available_date'], keep='last')
fi_roa = fi_roa.sort_values(['ts_code', 'end_date'])
fi_roa['roa_prev4'] = fi_roa.groupby('ts_code')['roa'].shift(4)
fi_roa['pa'] = fi_roa['roa'] - fi_roa['roa_prev4']

# S4/S5 bias_std_turn（Liquidity 轮）
ts_daily_src = ROOT / 'data/external/tushare/a_share_daily_basic_pit_v1/normalized/daily_basic.csv.gz'
db = pd.read_csv(ts_daily_src, compression='gzip',
                 usecols=['ts_code', 'trade_date', 'total_mv', 'total_share', 'float_share'],
                 dtype={'trade_date': str})
db['dt'] = pd.to_datetime(db['trade_date'], format='%Y%m%d')
db = db[~db['ts_code'].str.split('.').str[0].str.startswith(('43', '83', '87', '92', '920'))]
month_end_all = db.groupby(db['dt'].dt.to_period('M'))['dt'].max().sort_values()
snap_mv, snap_ts, snap_fs = {}, {}, {}
for d in month_end_all:
    g = db[db['dt'] == d]
    snap_mv[d] = pd.Series(g['total_mv'].values / 1e4, index=g['ts_code'].values)
    snap_ts[d] = pd.Series(g['total_share'].values, index=g['ts_code'].values)
    snap_fs[d] = pd.Series(g['float_share'].values, index=g['ts_code'].values)
me_ts_all = np.array(sorted(snap_mv))

ts_wide = pd.DataFrame({d: snap_ts[d] for d in me_ts_all}).T
fs_wide = pd.DataFrame({d: snap_fs[d] for d in me_ts_all}).T


def rename_qlib(df):
    df = df.copy()
    df.columns = [f"{c.split('.')[1].lower()}{c.split('.')[0]}" for c in df.columns]
    return df


ts_daily = rename_qlib(ts_wide).reindex(columns=C.columns).reindex(cal, method='ffill') * 1e4
fs_daily = rename_qlib(fs_wide).reindex(columns=C.columns).reindex(cal, method='ffill') * 1e4
vol_shares = V * 100
turn = vol_shares / ts_daily.where(ts_daily > 0)
vr = vol_shares / fs_daily.where(fs_daily > 0)
sd21 = turn.rolling(21).std()
sd252 = turn.rolling(252).std()
S_bias_21_252 = sd21 / sd252 - 1
sd42_504 = turn.rolling(42).std()
sd504 = turn.rolling(504).std()
S_bias_42_504 = sd42_504 / sd504 - 1
# MACD（负向）
dif = C.ewm(span=12, adjust=False).mean() - C.ewm(span=26, adjust=False).mean()
S_macd = 2 * (dif - dif.ewm(span=9, adjust=False).mean())
S_std21 = RET.rolling(21).std()

SIGNALS = {'Z1': Z1, 'delta_gpm_fi': fi.reset_index().set_index('ts_code')[['delta_gpm', 'available_date', 'end_date']],
           'pa_fi': fi_roa.reset_index().set_index('ts_code')[['pa', 'available_date', 'end_date']],
           'bias_21_252': S_bias_21_252, 'bias_42_504': S_bias_42_504,
           'MACD_neg': -S_macd, 'std_21d_neg': -S_std21}
# fi 型信号（ts_code 索引 + available_date PIT）需要逐日 PIT 快照
FI_SIGNALS = {'delta_gpm_fi': 'delta_gpm', 'pa_fi': 'pa'}
DAILY_SIGNALS = {k: v for k, v in SIGNALS.items() if k not in FI_SIGNALS}

# ---------------- 域 ----------------
st = pd.read_csv(ROOT / 'data/external/tushare/a_share_st_status_pit_v1/normalized/st_status_intervals.csv.gz',
                 compression='gzip', parse_dates=['start_date', 'end_date'])
st_start, st_end = st['start_date'].values, st['end_date'].values
st_bad = (st['is_st'] | st['is_delist_phase']).values
st_code = st['ts_code'].values

fin2 = load = None
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
ml = [d for d in sorted(domain_by_month) if d >= pd.Timestamp('2021-12-01')]
rets_all = {}
for i in range(len(ml) - 1):
    e0, e1 = ml[i], ml[i + 1]
    rets_all[e1] = (C.loc[e1] / C.loc[e0] - 1)


def domain_for(t):
    idx = np.searchsorted(me_domain, np.datetime64(t), side='right') - 1
    return domain_by_month[me_domain[idx]] if idx >= 0 else set()


def bad_at(t):
    mask = (st_start <= np.datetime64(t)) & (st_end >= np.datetime64(t)) & st_bad
    return {s.lower() for s in st_code[mask]}


def qlib_idx(ts_codes):
    return [f"{c.split('.')[1].lower()}{c.split('.')[0]}" for c in ts_codes]


# 月度因子截面缓存（fi 型, PIT）
fi_snap_cache = {}


def fi_signal_at(name, col, t):
    key = (name, t)
    if key in fi_snap_cache:
        return fi_snap_cache[key]
    df = SIGNALS[name]
    sub = df[df['available_date'] <= t].sort_values(['end_date', 'available_date']).groupby('ts_code').tail(1)
    s = sub[col].replace([np.inf, -np.inf], np.nan).dropna()
    s_q = pd.Series(s.values, index=qlib_idx(s.index))
    fi_snap_cache[key] = s_q
    return s_q


# ---------------- 实验一: 相关归并 ----------------
print('[exp1] 相关归并 ...', flush=True)
sample_days = [d for d in ml if d >= BT_START][::3]
corr_acc = pd.DataFrame(0.0, index=list(SIGNALS.keys()), columns=list(SIGNALS.keys()))
corr_n = 0
for d in sample_days:
    dom = domain_for(d)
    if len(dom) < 50:
        continue
    bad = bad_at(d)
    vals = {}
    for k, v in DAILY_SIGNALS.items():
        s = v.loc[d].dropna()
        vals[k] = s[s.index.isin(dom) & ~s.index.isin(bad)].rank(pct=True)
    for k in FI_SIGNALS:
        s = fi_signal_at(k, FI_SIGNALS[k], d)
        vals[k] = s[s.index.isin(dom) & ~s.index.isin(bad)].rank(pct=True)
    vals = {k: v for k, v in vals.items() if len(v) >= 50}
    if len(vals) < 4:
        continue
    vdf = pd.DataFrame(vals).dropna()
    if len(vdf) < 50:
        continue
    corr_acc += vdf.corr(method='spearman').abs()
    corr_n += 1
corr_mat = corr_acc / max(corr_n, 1)
corr_mat.to_csv(OUT1 / 'source_corr_matrix.csv')
print(corr_mat.round(2).to_string(), flush=True)

# 归并: |corr|>0.60 连通分量, 每簇取一（按源优先级 Z1>delta_gpm>pa>bias42>bias21>MACD>std21）
PRIORITY = ['Z1', 'delta_gpm_fi', 'pa_fi', 'bias_42_504', 'bias_21_252', 'MACD_neg', 'std_21d_neg']
clusters = []
seen = set()
for s in PRIORITY:
    if s in seen:
        continue
    comp = [s]
    seen.add(s)
    for other in PRIORITY:
        if other != s and other not in seen and pd.notna(corr_mat.loc[s, other]) and corr_mat.loc[s, other] > 0.60:
            comp.append(other)
            seen.add(other)
    clusters.append(comp)
print(f'[exp1] 归并后簇: {clusters}', flush=True)
json.dump({'clusters': clusters}, open(OUT1 / 'clusters.json', 'w'), ensure_ascii=False)

# 融合信号 Z_final（日频, 簇内等权 rank 均值→跨簇等权; fi 型以月度前向近似日频）
print('[exp1] Z_final ...', flush=True)
Z_final = None
for comp in clusters:
    parts = []
    for s in comp:
        if s in DAILY_SIGNALS:
            parts.append(cs_rank(DAILY_SIGNALS[s]))
        else:
            col = FI_SIGNALS[s]
            df = SIGNALS[s]
            # 月度前向: 每月末 PIT 截面 ffill 到日频
            me_codes = [x for x in me_ts_all if x <= pd.Timestamp(END)]
            snaps = {}
            for d in me_codes:
                sub = df[df['available_date'] <= d].sort_values(['end_date', 'available_date']).groupby('ts_code').tail(1)
                sr = sub[col].replace([np.inf, -np.inf], np.nan).dropna()
                snaps[d] = pd.Series(sr.values, index=qlib_idx(sr.index)).rank(pct=True)
            sdf = pd.DataFrame(snaps).T.reindex(cal).ffill()
            parts.append(sdf)
    z = sum(parts) / len(parts)
    Z_final = z if Z_final is None else Z_final + z
Z_final = Z_final / len(clusters)

# ---------------- 回测引擎（月度 & 多周期共用） ----------------
trading_days = cal[cal >= BT_START]


def month_firsts():
    td_s = pd.Series(trading_days, index=trading_days)
    return [d for d in td_s.groupby(trading_days.to_period('M')).min().sort_values()
            if np.searchsorted(me_domain, np.datetime64(d), side='right') - 1 >= 0]


def run_period(signal_df, period_days: int, cost: float, weighting: str = 'enhance',
               top_n: int | None = None, limit_days: list | None = None):
    """period_days: 调仓间隔（交易日）; weighting: 'enhance'(全池加权) or 'topN'。"""
    o_next = O.shift(-1)
    vol_ok = (V > 0) & C.notna()
    navs, turns = [], []
    holdings, cash = {}, 1.0
    days = limit_days or list(trading_days)
    next_reb = days[0]
    pend = None
    for idx, t in enumerate(days):
        if idx >= len(days) - period_days - 2:
            navs.append((t, cash, len(holdings)))
            continue
        # T+1 开盘成交 pending
        if pend is not None:
            bp = days[min(idx + 1, len(days) - 1)]
            o_row = O.loc[bp]
            fills = {s: w for s, w in pend.items() if pd.notna(o_row.get(s, np.nan)) and o_row.get(s, 0) > 0}
            old, new = set(holdings), set(fills)
            to = (len(old - new) + len(new - old)) / 2 / max(len(new), 1) if new else 1.0
            cash *= (1 - cost * to)
            turns.append(to)
            holdings = fills
            pend = None
        # 持有到下一调仓日（period 内逐日收盘计价简化为 buy→sell 区间收益）
        dom = domain_for(t)
        if dom and t >= next_reb:
            bad = bad_at(t)
            cands = [s for s in C.columns if s in dom and s not in bad]
            if weighting == 'enhance':
                z = signal_df.loc[t].reindex(cands).dropna()
                w = 1.0 + 0.5 * (z.rank(pct=True) - 0.5)
                w = w / w.sum()
                pend = w.dropna().to_dict()
            else:
                z = signal_df.loc[t].reindex(cands).dropna()
                top = z.nlargest(top_n).index.tolist()
                pend = {s: 1 / len(top) for s in top} if len(top) >= 10 else {}
            next_reb = days[min(idx + period_days, len(days) - 1)] if idx + period_days < len(days) else next_reb
        # 区间收益: 买入日开盘到 min(下一调仓日, 期末) 开盘（简化沿用 q4 轮 buy_day→sell_day）
        # 此处用 daily compounding 近似（持有期收益=当日持仓日收益累计）
        if holdings:
            rets, wsum = [], 0.0
            for s, w in holdings.items():
                c0 = C.shift(1).at[t, s] if s in C.columns else np.nan
                c1 = C.at[t, s] if s in C.columns else np.nan
                if pd.notna(c0) and pd.notna(c1) and c0 > 0:
                    rets.append(w * (c1 / c0 - 1))
                    wsum += w
            pr = sum(rets) / wsum if wsum > 0 else 0.0
        else:
            pr = 0.0
        cash *= (1 + pr)
        navs.append((t, cash, len(holdings)))
    df = pd.DataFrame(navs, columns=['datetime', 'nav', 'n']).set_index('datetime')
    return df, float(np.mean(turns)) if turns else np.nan


# ---------------- 实验一执行 ----------------
COSTS = {'base': 0.0015, 'stress': 0.0040, 'microcap': 0.0080}
mf = month_firsts()
print(f'[exp1] 调仓月数={len(mf)}', flush=True)


def run_monthly_enhance(sig, cost):
    """月度调仓: 月末信号->次月开盘买入->持有一个月。"""
    cash, holdings, navs, turns = 1.0, {}, [], []
    for i in range(len(mf) - 1):
        d = mf[i]
        d1 = mf[i + 1]
        cp = cal.get_loc(d)
        buy = cal[cp + 1]
        ep = cal.get_loc(d1)
        sell = cal[min(ep + 1, len(cal) - 1)]
        dom = domain_for(d)
        bad = bad_at(d)
        cands = [s for s in C.columns if s in dom and s not in bad]
        if len(cands) < 50:
            navs.append((d1, cash, len(holdings)))
            continue
        z = sig.loc[d].reindex(cands).dropna()
        w = 1.0 + 0.5 * (z.rank(pct=True) - 0.5)
        w = w / w.sum()
        o_buy = O.loc[buy]
        new_h = {s: wv for s, wv in w.dropna().items()
                 if pd.notna(o_buy.get(s, np.nan)) and o_buy.get(s, 0) > 0}
        old, new = set(holdings), set(new_h)
        to = (len(old - new) + len(new - old)) / 2 / max(len(new), 1) if new else 1.0
        cash *= (1 - cost * to)
        turns.append(to)
        holdings = new_h
        o_sell = O.loc[sell]
        rets, wsum = [], 0.0
        for s, wv in holdings.items():
            b = o_buy.get(s, np.nan)
            sl = o_sell.get(s, np.nan)
            if pd.notna(b) and pd.notna(sl) and b > 0:
                rets.append(wv * (sl / b - 1))
                wsum += wv
        pr = sum(rets) / wsum if wsum > 0 else 0.0
        cash *= (1 + pr)
        navs.append((d1, cash, len(holdings)))
    return pd.DataFrame(navs, columns=['datetime', 'nav', 'n']).set_index('datetime'), (float(np.mean(turns)) if turns else np.nan)


print('\n[exp1] 回测 ...', flush=True)
rows, nav_store = [], {}
arms_sig = {'fusion': Z_final, 'z1': Z1}
# 单源臂
for comp in clusters:
    if len(comp) == 1:
        s = comp[0]
        if s in DAILY_SIGNALS:
            arms_sig[f'single_{s}'] = DAILY_SIGNALS[s]
        else:
            # fi 型: 月度截面
            parts = []
            for d in me_ts_all:
                if d < pd.Timestamp('2021-12-01') or d > pd.Timestamp(END):
                    continue
                sub = SIGNALS[s][SIGNALS[s]['available_date'] <= d].sort_values(['end_date', 'available_date']).groupby('ts_code').tail(1)
                sr = sub[FI_SIGNALS[s]].replace([np.inf, -np.inf], np.nan).dropna()
                parts.append(pd.Series(sr.values, index=qlib_idx(sr.index)).rank(pct=True).rename(d))
            arms_sig[f'single_{s}'] = pd.DataFrame(parts).T.reindex(cal).ffill()

for (aname, sig), (cname, cost) in itertools.product(arms_sig.items(), COSTS.items()):
    df, to = run_monthly_enhance(sig, cost)
    r = df['nav'].pct_change().dropna()
    years = (df.index[-1] - df.index[0]).days / 365.25
    cagr = df['nav'].iloc[-1] ** (1 / years) - 1
    mdd = (df['nav'] / df['nav'].cummax() - 1).min()
    ir = r.mean() / r.std() * np.sqrt(12) if r.std() > 0 else np.nan
    rows.append({'arm': aname, 'cost': cname, 'CAGR': cagr, 'IR': ir, 'MDD': mdd,
                 'final_nav': df['nav'].iloc[-1], 'avg_turnover': to})
    nav_store[f'{aname}_{cname}'] = df['nav']
    print(f'  {aname} {cname}: CAGR={cagr:+.1%} IR={ir:.2f} MDD={mdd:.1%} 换手={to:.1%}', flush=True)
# pool_ew
for cname, cost in COSTS.items():
    df, to = run_monthly_enhance(pd.DataFrame(0.5, index=cal, columns=C.columns), cost)
    r = df['nav'].pct_change().dropna()
    years = (df.index[-1] - df.index[0]).days / 365.25
    cagr = df['nav'].iloc[-1] ** (1 / years) - 1
    mdd = (df['nav'] / df['nav'].cummax() - 1).min()
    ir = r.mean() / r.std() * np.sqrt(12) if r.std() > 0 else np.nan
    rows.append({'arm': 'pool_ew', 'cost': cname, 'CAGR': cagr, 'IR': ir, 'MDD': mdd,
                 'final_nav': df['nav'].iloc[-1], 'avg_turnover': to})
    nav_store[f'pool_ew_{cname}'] = df['nav']
    print(f'  pool_ew {cname}: CAGR={cagr:+.1%} IR={ir:.2f} MDD={mdd:.1%}', flush=True)

bt1 = pd.DataFrame(rows)
bt1.to_csv(OUT1 / 'backtest_summary.csv', index=False)

print('\n[exp1] 判定（microcap vs pool_ew）...', flush=True)
pool_mc = bt1[(bt1['arm'] == 'pool_ew') & (bt1['cost'] == 'microcap')]['CAGR'].iloc[0]
z1_mc = bt1[(bt1['arm'] == 'z1') & (bt1['cost'] == 'microcap')]['CAGR'].iloc[0]
fu_mc = bt1[(bt1['arm'] == 'fusion') & (bt1['cost'] == 'microcap')].iloc[0]
fu_ir = fu_mc['IR']
ex_pool = fu_mc['CAGR'] - pool_mc
ex_z1 = fu_mc['CAGR'] - z1_mc
if ex_pool >= 0.03 and fu_ir >= 0.5:
    d1 = 'fusion_adopted'
elif ex_pool > 0.02 and ex_z1 >= 0.01:
    d1 = 'fusion_adopted'
elif ex_pool > 0.02 and ex_z1 <= 0.005:
    d1 = 'keep_z1_only'
elif ex_pool > 0.02:
    d1 = 'fusion_marginal'
else:
    d1 = 'fusion_no_increment'
json.dump({'decision_exp1': d1, 'fusion_cagr': float(fu_mc['CAGR']), 'z1_cagr': float(z1_mc),
           'pool_cagr': float(pool_mc), 'excess_vs_pool': float(ex_pool), 'excess_vs_z1': float(ex_z1),
           'clusters': clusters},
          open(OUT1 / 'decision.json', 'w'), ensure_ascii=False, indent=2)
print(f'exp1 判定: {d1} | fusion={fu_mc["CAGR"]:+.1%} z1={z1_mc:+.1%} pool={pool_mc:+.1%}')
