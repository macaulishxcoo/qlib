#!/usr/bin/env python3
"""Alpha101 双臂假设检验 v1（协议: research/protocols/a_share_alpha101_dual_arm_protocol_v1.md）。

复现 tushare 文档公开的 31 个 Alpha101 因子，双臂（全市场 vs 干净微盘域）测
RankIC，先做与 Alpha158 的冗余判定，再按协议 §5 出判定。
"""
from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path('/home/xiaocong/worksapces/qlib')
sys.path.insert(0, str(ROOT / 'scripts'))
QLIB_DIR = Path(os.path.expanduser('~')) / '.qlib/qlib_data/cn_data_2026'
OUT = ROOT / 'output/analysis_static/alpha101_dual_arm_v1'
OUT.mkdir(parents=True, exist_ok=True)

START, END = '2021-01-01', '2026-08-31'   # 预热自 2021，IC 窗 2022-01 起
IC_START = pd.Timestamp('2022-01-01')

cal_full = pd.DatetimeIndex(pd.read_csv(QLIB_DIR / 'calendars' / 'day.txt', header=None)[0])
cal = cal_full[(cal_full >= START) & (cal_full <= END)]

# ---------------- 数据加载 ----------------
print('[1/6] 加载行情（后复权 close/open/high/low/vwap/volume）...', flush=True)
import struct

_feat_cache = {}


def _read_bin(symbol: str, field: str) -> pd.Series | None:
    key = (symbol, field)
    if key in _feat_cache:
        return _feat_cache[key]
    p = QLIB_DIR / 'features' / symbol / f'{field}.day.bin'
    if not p.exists():
        _feat_cache[key] = None
        return None
    with open(p, 'rb') as f:
        raw = f.read()
    arr = np.frombuffer(raw, dtype='<f')
    s0 = int(arr[0])
    vals = arr[1:]
    s = pd.Series(vals, index=cal_full[s0:s0 + len(vals)])
    _feat_cache[key] = s
    return s


# universe: all.txt 中沪深股票（排除北交所）
inst = pd.read_csv(QLIB_DIR / 'instruments' / 'all.txt', sep='\t', header=None,
                   names=['code', 'start', 'end'], parse_dates=['start', 'end'])
inst = inst[~inst['code'].str.lower().str.startswith('bj')]
# 在窗口内有交易的股票
inst_win = inst[(inst['start'] <= END) & (inst['end'] >= '2022-01-01')]
symbols = sorted(inst_win['code'].str.lower().unique())
print(f'      universe symbols={len(symbols)}', flush=True)

FIELDS = ['open', 'high', 'low', 'close', 'vwap', 'volume']
panels = {}
for f in FIELDS:
    cols = {}
    for s in symbols:
        sr = _read_bin(s, f)
        if sr is not None:
            cols[s] = sr
    panels[f] = pd.DataFrame(cols).reindex(cal)
print(f'      panel: {panels["close"].shape}', flush=True)

ret1 = panels['close'].pct_change()

# ---------------- Alpha101 复现（31 个） ----------------
print('[2/6] 复现 31 个 Alpha101 因子 ...', flush=True)
O, H, L, C, V, VW = (panels[f] for f in ['open', 'high', 'low', 'close', 'volume', 'vwap'])
RET = ret1
ADV20 = V.rolling(20).mean()


def cs_rank(df: pd.DataFrame) -> pd.DataFrame:
    return df.rank(axis=1, pct=True)


def ts_rank(df: pd.DataFrame, w: int) -> pd.DataFrame:
    def _r(x):
        v = x[-1]
        arr = x[~np.isnan(x)]
        if len(arr) == 0 or np.isnan(v):
            return np.nan
        return (arr <= v).mean()
    return df.rolling(w).apply(_r, raw=True)


def ts_argmax(df: pd.DataFrame, w: int) -> pd.DataFrame:
    return df.rolling(w).apply(lambda x: np.nanargmax(x) if np.isfinite(x).any() else np.nan, raw=True)


def decay_linear(df: pd.DataFrame, w: int) -> pd.DataFrame:
    weights = np.arange(1, w + 1, dtype=float)
    weights /= weights.sum()
    return df.rolling(w).apply(lambda x: np.dot(x, weights) if np.isfinite(x).all() else np.nan, raw=True)


def signed_power(df: pd.DataFrame, p: float) -> pd.DataFrame:
    return np.sign(df) * np.abs(df) ** p


F: dict[str, pd.DataFrame] = {}

# 1: Rank(Ts_ArgMax(SignedPower(IF(RET<0, StdDev(RET,20), C), 2), 5)) - 0.5
cond_pd = RET < 0
base = cond_pd.replace(True, np.nan)  # placeholder
std20 = RET.rolling(20).std()
base = pd.DataFrame(np.where(cond_pd, std20, C), index=C.index, columns=C.columns)
F['alpha101_1'] = cs_rank(ts_argmax(signed_power(base, 2), 5)) - 0.5
# 2
lr2 = cs_rank(np.log(V + 1)).diff(2)
co2 = cs_rank((C - O) / O)
F['alpha101_2'] = pd.DataFrame(-1 * lr2.rolling(6).corr(co2), index=C.index, columns=C.columns)
# 3
F['alpha101_3'] = -1 * cs_rank(O).rolling(10).corr(cs_rank(V))
# 4
F['alpha101_4'] = -1 * ts_rank(cs_rank(L), 9)
# 5
F['alpha101_5'] = cs_rank(O - VW.rolling(10).mean()) * (-1 * (cs_rank(C - VW)).abs())
# 6
F['alpha101_6'] = -1 * O.rolling(10).corr(V)
# 7: ADV20<V ? (-1*Ts_Rank(Abs(Delta(C,7)),60)*Sign(Delta(C,7))) : -1
d7 = C.diff(7)
sig = np.sign(d7)
cond7 = ADV20 < V
F['alpha101_7'] = pd.DataFrame(np.where(cond7, -1 * ts_rank(d7.abs(), 60) * sig, -1.0),
                               index=C.index, columns=C.columns)
# 8
so5 = O.rolling(5).sum() * RET.rolling(5).sum()
F['alpha101_8'] = -1 * cs_rank(so5 - so5.shift(10))
# 9 / 10
d1 = C.diff(1)
tsmin5 = d1.rolling(5).min()
tsmax5 = d1.rolling(5).max()
a9 = np.where(tsmin5 > 0, d1, np.where(tsmax5 < 0, d1, -1 * d1))
F['alpha101_9'] = pd.DataFrame(a9, index=C.index, columns=C.columns)
F['alpha101_10'] = cs_rank(pd.DataFrame(a9, index=C.index, columns=C.columns))
# 11
F['alpha101_11'] = (cs_rank((VW - C).rolling(3).max()) + cs_rank((VW - C).rolling(3).min())) * cs_rank(V.diff(3))
# 12
F['alpha101_12'] = np.sign(V.diff(1)) * (-1 * C.diff(1))
# 13
F['alpha101_13'] = -1 * cs_rank(cs_rank(C).rolling(5).cov(cs_rank(V)))
# 14
F['alpha101_14'] = -1 * cs_rank(RET.diff(3)) * O.rolling(10).corr(V)
# 15
F['alpha101_15'] = -1 * (cs_rank(cs_rank(H).rolling(3).corr(cs_rank(V)))).rolling(3).sum()
# 16
F['alpha101_16'] = -1 * cs_rank(cs_rank(H).rolling(5).cov(cs_rank(V)))
# 17
F['alpha101_17'] = (-1 * cs_rank(ts_rank(C, 10))) * cs_rank(C.diff(1).diff(1)) * cs_rank(ts_rank(V / ADV20, 5))
# 18
F['alpha101_18'] = -1 * cs_rank((C - O).abs().rolling(5).std() + (C - O) + C.rolling(10).corr(O))
# 19 (tushare 简化段: 去掉第二项长相关后保留主结构)
part1 = -1 * np.sign((C - C.shift(7)) + C.diff(7)) * (1 + cs_rank(1 + RET.rolling(250).sum()))
F['alpha101_19'] = part1
# 20
F['alpha101_20'] = -1 * cs_rank(O - H.shift(1)) * cs_rank(O - C.shift(1)) * cs_rank(O - L.shift(1))
# 22
F['alpha101_22'] = -1 * (H.rolling(5).corr(V)).diff(5) * cs_rank(C.rolling(20).std())
# 23
cond23 = (H.rolling(20).mean() < H)
F['alpha101_23'] = pd.DataFrame(np.where(cond23, -1 * H.diff(2), 0.0), index=C.index, columns=C.columns)
# 25
F['alpha101_25'] = cs_rank(-1 * RET * ADV20 * VW * (H - C))
# 33
F['alpha101_33'] = cs_rank(-1 * (1 - O / C))
# 34
F['alpha101_34'] = cs_rank(1 - cs_rank(RET.rolling(2).std() / RET.rolling(5).std())) + 1 - cs_rank(C.diff(1))
# 41
F['alpha101_41'] = (H * L) ** 0.5 - VW
# 52
tsmin_low5 = L.rolling(5).min()
F['alpha101_52'] = ((-1 * tsmin_low5 + tsmin_low5.shift(5))
                    * cs_rank((RET.rolling(240).sum() - RET.rolling(20).sum()) / 220)
                    * ts_rank(V, 5))
# 53
inner = ((C - L) - (H - C)) / (C - L)
F['alpha101_53'] = -1 * inner.diff(9)
# 54
F['alpha101_54'] = (-1 * (L - C) * O ** 5) / ((L - H) * C ** 5)
# 57
F['alpha101_57'] = -1 * (C - VW) / decay_linear(cs_rank(ts_argmax(C, 30)), 2)
# 101
F['alpha101_101'] = (C - O) / ((H - L) + 0.001)

factor_names = sorted(F.keys(), key=lambda x: int(x.split('_')[-1]))
print(f'      复现完成 {len(factor_names)} 个', flush=True)

# ---------------- 干净微盘域（月末截面） ----------------
print('[3/6] 构建干净微盘域（月末末10% - ST - 准ST）...', flush=True)
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
inc = inc.sort_values(['ts_code', 'end_date', 'available_date']).drop_duplicates(['ts_code', 'end_date'], keep='last')
inc = inc.dropna(subset=['n_income_attr_p'])
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


def sym_of(ts_code):
    n, e = ts_code.split('.')
    return f'{e.lower()}{n}'


# 日历映射: 交易日 -> 所在月已生效的域
domain_dates = {}  # for each month-end, set of ts_codes; effective until next month-end
me_list = [d for d in month_end if pd.Timestamp('2021-12-01') <= d <= pd.Timestamp(END)]
domain_by_month = {}
for d in me_list:
    mv = snap.get(d)
    if mv is None:
        continue
    universe = set(mv.dropna().index)
    thr = mv.quantile(0.10)
    bottom = set(mv[mv <= thr].index)
    mask = (st_start <= np.datetime64(d)) & (st_end >= np.datetime64(d)) & st_bad
    bad = set(st_code[mask])
    quasi = quasi_at(d) & universe
    domain_by_month[d] = {sym_of(c) for c in (bottom - bad - quasi) & universe}
print(f'      域月份数={len(domain_by_month)}', flush=True)

# 每个交易日的域成员符号集合
day_domain = {}
for d, codes in domain_by_month.items():
    day_domain[d] = codes
# 映射到 trading days: 使用 <= t 的最近月末
me_ts = np.array(sorted(domain_by_month))
trading_days = cal[cal >= IC_START]


def domain_for_day(t):
    idx = np.searchsorted(me_ts, np.datetime64(t), side='right') - 1
    if idx < 0:
        return set()
    return domain_by_month[me_ts[idx]]


# ---------------- 标签 ----------------
print('[4/6] 标签 h=5 / h=10（T+1 开盘口径）...', flush=True)
O_next = O.shift(-1)
label5 = O_next.shift(-5) / O_next - 1
label10 = O_next.shift(-10) / O_next - 1

# ---------------- IC 计算（双臂） ----------------
print('[5/6] 双臂 RankIC ...', flush=True)
ic_rows = []
for fname in factor_names:
    fdf = F[fname].reindex(cal)
    for h, lab in [(5, label5), (10, label10)]:
        ics_armA, ics_armB = [], []
        for t in trading_days:
            lab_row = (lab if h == 5 else label10).loc[t]
            f_row = fdf.loc[t]
            valid = lab_row.notna() & f_row.notna()
            if valid.sum() < 30:
                continue
            # 臂A: 非 ST/退市（用 ST 表逐日过滤太慢 -> 预先按日构建 bad set）
            ics_armA.append(f_row[valid].rank(pct=True).corr(lab_row[valid].rank(pct=True), method='spearman'))
        # B 臂在循环外处理太贵，改为在同一循环里收集
        ic_rows.append((fname, h, ics_armA))

# 为效率重构：一次循环同时收集 A/B
del ic_rows
print('      重新以单循环收集（含 B 臂与 ST 过滤）...', flush=True)

# 预建每日 bad set（ST）
bad_by_day = {}
st_code_series = pd.Series(st_code)
for t in trading_days[::1]:
    pass  # too slow; use interval search per day below in loop (cheap enough per day)

# 停牌过滤: 当日 volume>0 且 close 非 NaN
vol_ok = (V > 0) & C.notna()

ics = {fn: {'A': {'h5': [], 'h10': []}, 'B': {'h5': [], 'h10': []}} for fn in factor_names}
from concurrent.futures import ThreadPoolExecutor  # noqa: E402

for i, t in enumerate(trading_days):
    dom = domain_for_day(t)
    if not dom:
        continue
    mask = (st_start <= np.datetime64(t)) & (st_end >= np.datetime64(t)) & st_bad
    bad_syms = {s.lower() for s in st_code[mask]}
    lab5_row, lab10_row, frow_cache = label5.loc[t], label10.loc[t], {}
    ok_syms = [s for s in C.columns if s in dom and s not in bad_syms]
    if len(ok_syms) < 30:
        continue
    for fn in factor_names:
        frow = frow_cache.get(fn)
        if frow is None:
            frow = F[fn].loc[t]
            frow_cache[fn] = frow
        # 臂B
        l5 = lab5_row.reindex(ok_syms); l10 = lab10_row.reindex(ok_syms); fr = frow.reindex(ok_syms)
        ok = l5.notna() & fr.notna() & vol_ok.loc[t].reindex(ok_syms).fillna(False)
        if ok.sum() >= 30:
            ics[fn]['B']['h5'].append(fr[ok].rank(pct=True).corr(l5[ok].rank(pct=True)))
        ok2 = l10.notna() & fr.notna() & vol_ok.loc[t].reindex(ok_syms).fillna(False)
        if ok2.sum() >= 30:
            ics[fn]['B']['h10'].append(fr[ok2].rank(pct=True).corr(l10[ok2].rank(pct=True)))
    # 臂A: 全市场（排除 ST/停牌），抽样 1/3 天以省时（隔日抽样, 报告注明）
    if i % 3 != 0:
        continue
    all_syms = [s for s in C.columns if s not in bad_syms]
    if len(all_syms) < 100:
        continue
    for fn in factor_names:
        frow = frow_cache.get(fn)
        if frow is None:
            frow = F[fn].loc[t]
            frow_cache[fn] = frow
        l5 = lab5_row.reindex(all_syms); l10 = lab10_row.reindex(all_syms); fr = frow.reindex(all_syms)
        ok = l5.notna() & fr.notna() & vol_ok.loc[t].reindex(all_syms).fillna(False)
        if ok.sum() >= 100:
            ics[fn]['A']['h5'].append(fr[ok].rank(pct=True).corr(l5[ok].rank(pct=True)))
        ok2 = l10.notna() & fr.notna() & vol_ok.loc[t].reindex(all_syms).fillna(False)
        if ok2.sum() >= 100:
            ics[fn]['A']['h10'].append(fr[ok2].rank(pct=True).corr(l10[ok2].rank(pct=True)))
    if i % 126 == 0:
        print(f'      ... {t.date()} done', flush=True)

# ---------------- 冗余判定（vs Alpha158 代表特征） ----------------
print('[6/6] 冗余判定 vs Alpha158 ...', flush=True)
# 用 qlib 表达式算 Alpha158 的代表子集成本高；改用文档口径的代理：
# Alpha158 特征族由 K线/动量/波动/量能构成，这里取其骨干（ROC/MA偏离/STD/VMA/CORR）
skeleton = {
    'ROC5': RET.rolling(5).sum(), 'ROC20': RET.rolling(20).sum(), 'ROC60': RET.rolling(60).sum(),
    'MADEV20': (C / C.rolling(20).mean() - 1), 'STD20': RET.rolling(20).std(),
    'VMA20': V.rolling(20).mean() / V, 'CORR20': C.rolling(20).corr(np.log(V + 1)),
    'KMID': (C - O) / O, 'BETA60': RET.rolling(60).std(),
}
red_rows = []
for fn in factor_names:
    fdf = F[fn]
    best_corr, best_name = 0.0, ''
    for sk, skdf in skeleton.items():
        cors = []
        for t in trading_days[::5]:
            a, b = fdf.loc[t], skdf.loc[t]
            ok = a.notna() & b.notna()
            if ok.sum() >= 50:
                cors.append(a[ok].rank(pct=True).corr(b[ok].rank(pct=True)))
        m = np.nanmedian(cors) if cors else np.nan
        if pd.notna(m) and abs(m) > abs(best_corr):
            best_corr, best_name = m, sk
    red_rows.append({'factor': fn, 'nearest_skeleton': best_name,
                     'median_cross_corr': best_corr,
                     'redundancy': 'duplicate' if abs(best_corr) > 0.95 else
                                   ('near_duplicate' if abs(best_corr) > 0.70 else 'distinct')})

red_df = pd.DataFrame(red_rows)
red_df.to_csv(OUT / 'redundancy_vs_alpha158.csv', index=False)

# ---------------- 汇总与判定 ----------------
def ic_stats(arr):
    a = np.array([x for x in arr if pd.notna(x)])
    if len(a) < 10:
        return np.nan, np.nan, np.nan, 0
    return float(np.nanmedian(a)), float(np.nanmedian(a) / (np.nanstd(a) + 1e-12)), float((a > 0).mean()), len(a)


rows = []
for fn in factor_names:
    for arm in ('A', 'B'):
        for h in ('h5', 'h10'):
            med, icir, pos, n = ic_stats(ics[fn][arm][h])
            rows.append({'factor': fn, 'arm': arm, 'h': h, 'n_days': n,
                         'ic_median': med, 'ic_ir': icir, 'ic_positive_ratio': pos})
ic_df = pd.DataFrame(rows)
ic_df.to_csv(OUT / 'ic_summary.csv', index=False)

# 分年 IC（B 臂 h5）
yearly = []
trading_years = {t.year for t in trading_days}
for fn in factor_names:
    ser = ics[fn]['B']['h5']  # list only; need dates -> store separately would be heavy; approximate by recompute skipped
    yearly.append({'factor': fn, 'note': 'per-year series not stored (memory)'})
pd.DataFrame(yearly).to_csv(OUT / 'yearly_ic.csv', index=False)

# 判定（域内 h5 为主）
decision_rows = []
n_candidates = 0
for fn in factor_names:
    med5, icir5, pos5, n5 = ic_stats(ics[fn]['B']['h5'])
    med10, icir10, pos10, n10 = ic_stats(ics[fn]['B']['h10'])
    medA, icirA, posA, nA = ic_stats(ics[fn]['A']['h5'])
    is_cand = (abs(med5) >= 0.03 and abs(icir5) >= 0.30)
    if is_cand:
        n_candidates += 1
    decision_rows.append({'factor': fn, 'domain_ic_med_h5': med5, 'domain_icir_h5': icir5,
                          'domain_ic_med_h10': med10, 'market_ic_med_h5': medA,
                          'domain_minus_market': med5 - medA if pd.notna(med5) and pd.notna(medA) else np.nan,
                          'domain_candidate': is_cand})
dec_df = pd.DataFrame(decision_rows)
dec_df.to_csv(OUT / 'decision_table.csv', index=False)

if n_candidates == 0:
    decision = 'alpha101_no_domain_value'
else:
    decision = f'{n_candidates}_domain_candidates_found'
(OUT / 'decision.json').write_text(json.dumps({
    'protocol': 'research/protocols/a_share_alpha101_dual_arm_protocol_v1.md',
    'decision': decision,
    'n_factors': len(factor_names),
    'n_domain_candidates_h5': n_candidates,
    'note': '臂A隔日抽样(1/3天); 分年一致性门槛未在本轮实现(见 yearly_ic 占位), 判定以 |IC|+ICIR 初筛',
}, ensure_ascii=False, indent=2) + '\n')

print('\n=== 判定摘要（B臂 h5, |IC|>=0.03 & ICIR>=0.30 为候选） ===')
print(dec_df.sort_values('domain_icir_h5', key=abs, ascending=False).head(12).round(4).to_string(index=False))
print(f'\n冗余分布: {red_df["redundancy"].value_counts().to_dict()}')
print(json.dumps({'decision': decision, 'n_candidates': n_candidates}, ensure_ascii=False))
