"""对 10 个域内候选做协议 §5 附加判定：
1) 域内对 log(size) 正交后 RankIC 是否仍 |IC|>=0.02（orthogonal_confirmed）
2) 分年 IC 一致性（2022-2026 五年同号 >=4 年）
"""
import os
import sys
import numpy as np
import pandas as pd

ROOT = '/home/xiaocong/worksapces/qlib'
sys.path.insert(0, os.path.join(ROOT, 'scripts'))
QLIB_DIR = os.path.join(os.path.expanduser('~'), '.qlib/qlib_data/cn_data_2026')
START, END = '2021-01-01', '2026-08-31'
IC_START = pd.Timestamp('2022-01-01')

cal_full = pd.DatetimeIndex(pd.read_csv(os.path.join(QLIB_DIR, 'calendars', 'day.txt'), header=None)[0])
cal = cal_full[(cal_full >= START) & (cal_full <= END)]

# ---- 因子复现（复用主脚本的函数；直接 import 太重，这里挑 10 个候选单独算）----
_feat = {}
def read_bin(sym, field):
    k = (sym, field)
    if k in _feat: return _feat[k]
    p = os.path.join(QLIB_DIR, 'features', sym, f'{field}.day.bin')
    if not os.path.exists(p):
        _feat[k] = None; return None
    with open(p,'rb') as f: raw = f.read()
    arr = np.frombuffer(raw, dtype='<f')
    s0 = int(arr[0]); vals = arr[1:]
    _feat[k] = pd.Series(vals, index=cal_full[s0:s0+len(vals)])
    return _feat[k]

inst = pd.read_csv(os.path.join(QLIB_DIR, 'instruments', 'all.txt'), sep='\t', header=None,
                   names=['code','start','end'], parse_dates=['start','end'])
inst = inst[~inst['code'].str.lower().str.startswith('bj')]
inst_win = inst[(inst['start'] <= END) & (inst['end'] >= '2022-01-01')]
symbols = sorted(inst_win['code'].str.lower().unique())

print('加载行情...', flush=True)
panels = {}
for f in ['open','high','low','close','vwap','volume']:
    cols = {s: read_bin(s, f) for s in symbols}
    panels[f] = pd.DataFrame({k:v for k,v in cols.items() if v is not None}).reindex(cal)
O,H,L,C,V,VW = (panels[f] for f in ['open','high','low','close','volume','vwap'])
RET = C.pct_change()
ADV20 = V.rolling(20).mean()

def cs_rank(df): return df.rank(axis=1, pct=True)
def ts_rank(df, w):
    return df.rolling(w).apply(lambda x: (x[~np.isnan(x)] <= x[-1]).mean() if np.isfinite(x).any() else np.nan, raw=True)

# 10 个候选
F = {}
F['alpha101_13'] = -1 * cs_rank(cs_rank(C).rolling(5).cov(cs_rank(V)))
F['alpha101_16'] = -1 * cs_rank(cs_rank(H).rolling(5).cov(cs_rank(V)))
F['alpha101_15'] = -1 * (cs_rank(cs_rank(H).rolling(3).corr(cs_rank(V)))).rolling(3).sum()
F['alpha101_12'] = np.sign(V.diff(1)) * (-1 * C.diff(1))
F['alpha101_3']  = -1 * cs_rank(O).rolling(10).corr(cs_rank(V))
F['alpha101_6']  = -1 * O.rolling(10).corr(V)
F['alpha101_23'] = pd.DataFrame(np.where(H.rolling(20).mean() < H, -1*H.diff(2), 0.0), index=C.index, columns=C.columns)
d7 = C.diff(7); sig = np.sign(d7)
F['alpha101_7']  = pd.DataFrame(np.where(ADV20 < V, -1*ts_rank(d7.abs(),60)*sig, -1.0), index=C.index, columns=C.columns)
part1 = -1*np.sign((C-C.shift(7))+C.diff(7))*(1+cs_rank(1+RET.rolling(250).sum()))
F['alpha101_19'] = part1
tsmin_low5 = L.rolling(5).min()
F['alpha101_52'] = ((-1*tsmin_low5+tsmin_low5.shift(5))
                    * cs_rank((RET.rolling(240).sum()-RET.rolling(20).sum())/220) * ts_rank(V,5))
F['alpha101_14'] = -1*cs_rank(RET.diff(3))*O.rolling(10).corr(V)
F['alpha101_4']  = -1*ts_rank(cs_rank(L), 9)

CANDS = list(F.keys())
print(f'候选 {len(CANDS)} 个', flush=True)

# ---- 域重建（与主脚本一致）----
db = pd.read_csv(os.path.join(ROOT, 'data/external/tushare/a_share_daily_basic_pit_v1/normalized/daily_basic.csv.gz'),
                 compression='gzip', usecols=['ts_code','trade_date','total_mv'], dtype={'trade_date':str})
db['dt'] = pd.to_datetime(db['trade_date'], format='%Y%m%d')
db = db[~db['ts_code'].str.split('.').str[0].str.startswith(('43','83','87','92','920'))]
month_end = db.groupby(db['dt'].dt.to_period('M'))['dt'].max().sort_values()
snap = {}
for d in month_end:
    g = db[db['dt'] == d]
    snap[d] = pd.Series(g['total_mv'].values/1e4, index=g['ts_code'].values)

st = pd.read_csv(os.path.join(ROOT, 'data/external/tushare/a_share_st_status_pit_v1/normalized/st_status_intervals.csv.gz'),
                 compression='gzip', parse_dates=['start_date','end_date'])
st_start, st_end = st['start_date'].values, st['end_date'].values
st_bad = (st['is_st']|st['is_delist_phase']).values
st_code = st['ts_code'].values

from load_financials_extended_v1 import load_financials_extended
fin = load_financials_extended()
inc = fin[['ts_code','end_date','available_date','n_income_attr_p']].copy()
inc = inc[inc['end_date'].dt.month==12]
inc = inc.sort_values(['ts_code','end_date','available_date']).drop_duplicates(['ts_code','end_date'], keep='last').dropna(subset=['n_income_attr_p'])
inc['loss'] = inc['n_income_attr_p'] < 0
bps = fin[['ts_code','end_date','available_date','bps']].copy()
bps = bps.sort_values(['ts_code','end_date','available_date']).drop_duplicates(['ts_code','end_date'], keep='last').dropna(subset=['bps'])

def quasi_at(t):
    t64 = np.datetime64(t)
    sub = inc[inc['available_date'] <= t64].sort_values(['ts_code','end_date'])
    last2 = sub.groupby('ts_code').tail(2)
    g = last2.groupby('ts_code')['loss'].agg(['count','sum'])
    two = set(g[(g['count']>=2)&(g['sum']>=2)].index)
    sb = bps[bps['available_date'] <= t64].sort_values(['ts_code','end_date']).groupby('ts_code').tail(1)
    neg = set(sb[sb['bps']<0]['ts_code'])
    return two | neg

def sym_of(c):
    n,e = c.split('.'); return f'{e.lower()}{n}'

domain_by_month = {}
for d in month_end:
    if not (pd.Timestamp('2021-12-01') <= d <= pd.Timestamp(END)):
        continue
    mv = snap[d]
    universe = set(mv.dropna().index)
    thr = mv.quantile(0.10)
    bottom = set(mv[mv<=thr].index)
    mask = (st_start <= np.datetime64(d)) & (st_end >= np.datetime64(d)) & st_bad
    bad = set(st_code[mask])
    quasi = quasi_at(d) & universe
    domain_by_month[d] = {sym_of(c) for c in (bottom-bad-quasi) & universe}
me_ts = np.array(sorted(domain_by_month))
trading_days = cal[cal >= IC_START]

# 域内 log_size（用于正交化）
def domain_size_row(t, dom):
    # 当日总市值近似: 用 daily_basic 最近 <= t 的月末截面
    idx = np.searchsorted(me_ts, np.datetime64(t), side='right')-1
    mv = snap[me_ts[idx]]
    syms = [sym_of(c) for c in mv.index if sym_of(c) in dom]
    return pd.Series(np.log(mv.reindex([c for c in mv.index if sym_of(c) in dom]).values),
                     index=syms)

vol_ok = (V > 0) & C.notna()
O_next = O.shift(-1)
label5 = O_next.shift(-5)/O_next - 1

print('双臂正交 IC ...', flush=True)
res = {fn: {'raw': [], 'orth': [], 'years': {}} for fn in CANDS}
for i, t in enumerate(trading_days):
    idx = np.searchsorted(me_ts, np.datetime64(t), side='right')-1
    if idx < 0: continue
    dom = domain_by_month[me_ts[idx]]
    if not dom: continue
    mask = (st_start <= np.datetime64(t)) & (st_end >= np.datetime64(t)) & st_bad
    bad_syms = {s.lower() for s in st_code[mask]}
    ok_syms = [s for s in C.columns if s in dom and s not in bad_syms]
    if len(ok_syms) < 30: continue
    lab = label5.loc[t].reindex(ok_syms)
    vol = vol_ok.loc[t].reindex(ok_syms).fillna(False)
    sz = None
    for fn in CANDS:
        fr = F[fn].loc[t].reindex(ok_syms)
        ok = lab.notna() & fr.notna() & vol
        if ok.sum() < 30: continue
        rk = fr[ok].rank(pct=True)
        lr = lab[ok].rank(pct=True)
        ic = rk.corr(lr)
        res[fn]['raw'].append((t, ic))
        # 正交化: 因子对 log size 截面回归残差的 IC
        if sz is None:
            sz = domain_size_row(t, dom).reindex(ok_syms)
        ok_sz = ok & sz.notna().reindex(ok_syms).fillna(False)
        if ok_sz.sum() >= 30:
            sz_al = sz.reindex(ok_syms)
            keep = ok_sz.values
            syms_keep = np.array(ok_syms)[keep]
            x = sz_al[ok_sz].values
            y = fr[ok_sz].values
            X = np.column_stack([np.ones(len(x)), x])
            beta, *_ = np.linalg.lstsq(X, y, rcond=None)
            resid = y - X @ beta
            lr2 = lab[ok_sz].rank(pct=True)
            rk2 = pd.Series(resid, index=syms_keep).rank(pct=True)
            res[fn]['orth'].append((t, rk2.corr(lr2)))

# 汇总
rows = []
for fn in CANDS:
    raw = pd.Series({t: v for t, v in res[fn]['raw']})
    orth = pd.Series({t: v for t, v in res[fn]['orth']})
    raw_med, orth_med = raw.median(), orth.median()
    yearly_raw = raw.groupby(raw.index.year).median()
    years_pos = int((yearly_raw > 0).sum()); years_total = len(yearly_raw)
    # 方向一致性: 用原始符号（因子方向已按公式, 不再翻面）
    rows.append({'factor': fn,
                 'raw_ic_med': raw_med, 'orth_ic_med': orth_med,
                 'icir': raw_med/(raw.std()+1e-12),
                 'years_same_sign': f'{years_pos}/{years_total}',
                 'years_consistent': years_pos >= 4 or years_pos <= 1,
                 'orth_confirmed': abs(orth_med) >= 0.02,
                 'yearly': {int(y): round(v,4) for y, v in yearly_raw.items()}})
out = pd.DataFrame(rows).sort_values('orth_ic_med', key=abs, ascending=False)
out.to_csv(os.path.join(ROOT, 'output/analysis_static/alpha101_dual_arm_v1/orthogonality_check.csv'), index=False)
print(out[['factor','raw_ic_med','orth_ic_med','icir','years_same_sign','years_consistent','orth_confirmed']].round(4).to_string(index=False))
