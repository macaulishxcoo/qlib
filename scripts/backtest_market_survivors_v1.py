#!/usr/bin/env python3
"""全市场存活候选组合回测 v1（协议 market_survivors_validation_protocol_v1 Stage B）。

8 臂 × 三档成本（0.15/0.30/0.50% 单边），月度调仓 T+1 开盘进出，
涨停/停牌剔除，对照 pool_ew（域等权）与 csi1000（费前）。
主判定臂: z_comp_v1_top30 @ 0.30%。
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
OUT = ROOT / 'output/analysis_fundamental/market_survivors_bt_v1'
OUT.mkdir(parents=True, exist_ok=True)

START, END = '2020-06-01', '2026-08-31'
BT_START = pd.Timestamp('2022-01-01')
IPO_MIN_DAYS = 120
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
inst_win = inst[(inst['start'] <= END) & (inst['end'] >= BT_START)]
symbols = sorted(inst_win['code'].str.lower().unique())

print('[data] 加载面板 ...', flush=True)
FIELDS = ['open', 'close', 'volume', 'factor']
panels = {f: pd.DataFrame({s: read_bin(s, f) for s in symbols if read_bin(s, f) is not None}).reindex(cal)
          for f in FIELDS}
O, C, V, FAC = (panels[f] for f in FIELDS)
RET = C.pct_change()
AMT = (C / FAC) * V * 100
PREV_C = C.shift(1)
N_LISTED = C.notna().cumsum()

# ---------------- 换手率 / 市值（同 Stage A） ----------------
print('[turn] ...', flush=True)
db = pd.read_csv(ROOT / 'data/external/tushare/a_share_daily_basic_pit_v1/normalized/daily_basic.csv.gz',
                 compression='gzip', usecols=['ts_code', 'trade_date', 'total_share', 'total_mv'],
                 dtype={'trade_date': str})
db['dt'] = pd.to_datetime(db['trade_date'], format='%Y%m%d')
db = db[~db['ts_code'].str.split('.').str[0].str.startswith(('43', '83', '87', '92', '920'))]
month_end_all = db.groupby(db['dt'].dt.to_period('M'))['dt'].max().sort_values()
snap_ts = {}
snap_mv = {}
for d in month_end_all:
    g = db[db['dt'] == d]
    snap_ts[d] = pd.Series(g['total_share'].values, index=g['ts_code'].values)
    snap_mv[d] = pd.Series(g['total_mv'].values / 1e4, index=g['ts_code'].values)


def rename_qlib_cols(df):
    df = df.copy()
    df.columns = [f"{c.split('.')[1].lower()}{c.split('.')[0]}" for c in df.columns]
    return df


ts_daily = rename_qlib_cols(pd.DataFrame(snap_ts).T).reindex(columns=C.columns).reindex(cal, method='ffill') * 1e4
turn = (V * 100) / ts_daily.where(ts_daily > 0)
mv_daily = (rename_qlib_cols(pd.DataFrame(snap_mv).T)
            .reindex(columns=C.columns).reindex(cal, method='ffill'))  # 亿元

# ---------------- 因子 ----------------
print('[factor] ...', flush=True)


def cs_rank(df):
    return df.rank(axis=1, pct=True)


def ts_rank(df, w):
    return df.rolling(w).apply(lambda x: (x[~np.isnan(x)] <= x[-1]).mean() if np.isfinite(x).any() else np.nan, raw=True)


F = {}
F['sum_abs_rtn_amount_20d'] = RET.abs().rolling(20).sum() / AMT.rolling(20).sum()
F['amount_ma_20d'] = AMT.rolling(20).mean()
sd21, sd252 = turn.rolling(21).std(), turn.rolling(252).std()
F['bias_std_turn_21d_252d'] = sd21 / sd252 - 1
sd42 = turn.rolling(42).std()
F['bias_std_turn_42d_252d'] = sd42 / sd252 - 1
# alpha101 单调存活 7 因子
H_panel = pd.DataFrame({s: read_bin(s, 'high') for s in symbols if read_bin(s, 'high') is not None}).reindex(cal)
O_panel = pd.DataFrame({s: read_bin(s, 'open') for s in symbols if read_bin(s, 'open') is not None}).reindex(cal)
L_panel = pd.DataFrame({s: read_bin(s, 'low') for s in symbols if read_bin(s, 'low') is not None}).reindex(cal)
F['alpha101_13'] = -1 * cs_rank(cs_rank(C).rolling(5).cov(cs_rank(V)))
F['alpha101_16'] = -1 * cs_rank(cs_rank(H_panel).rolling(5).cov(cs_rank(V)))
F['alpha101_15'] = -1 * (cs_rank(cs_rank(H_panel).rolling(3).corr(cs_rank(V)))).rolling(3).sum()
F['alpha101_3'] = -1 * cs_rank(O_panel).rolling(10).corr(cs_rank(V))
F['alpha101_6'] = -1 * O_panel.rolling(10).corr(V)
F['alpha101_4'] = -1 * ts_rank(cs_rank(L_panel), 9)
F['alpha101_14'] = -1 * cs_rank(RET.diff(3)) * O_panel.rolling(10).corr(V)

# yoy_total_asset（PIT 扩深版, 同 Stage A 口径）—— z_comp_v0 第 4 源
print('[fin] yoy panel ...', flush=True)
import glob  # noqa: E402
_fi_frames = []
for _p in sorted(glob.glob(str(ROOT / 'data/external/tushare/a_share_financial_pit_v1/full/normalized/batch_*/fina_indicator.csv.gz'))):
    _fi_frames.append(pd.read_csv(_p, usecols=['ts_code', 'end_date', 'available_date', 'assets_yoy']))
_fi = pd.concat(_fi_frames, ignore_index=True).dropna(subset=['assets_yoy'])
_fi['end_date'] = pd.to_datetime(_fi['end_date'].astype(str), format='%Y%m%d', errors='coerce')
_fi['available_date'] = pd.to_datetime(_fi['available_date'].astype(str), format='%Y-%m-%d', errors='coerce')
_fi = _fi.dropna(subset=['available_date'])
_fi['yoy_ta'] = _fi['assets_yoy'] / 100.0

_bs = pd.concat([pd.read_csv(_p) for _p in sorted(glob.glob(str(ROOT / 'data/external/tushare/a_share_financial_pit_v1/recent_3tables/balancesheet_*.csv.gz')))], ignore_index=True)
_bs['end_date'] = pd.to_datetime(_bs['end_date'].astype(str), format='%Y%m%d', errors='coerce')
_bs['available_date'] = pd.to_datetime(_bs['ann_date'].astype(str), format='%Y%m%d', errors='coerce')
_bs = _bs.dropna(subset=['available_date', 'total_assets']).sort_values(['ts_code', 'end_date', 'available_date']).drop_duplicates(['ts_code', 'end_date'], keep='last')
_bs['yoy_ta'] = _bs['total_assets'] / _bs.groupby('ts_code')['total_assets'].shift(4) - 1
_ta = pd.concat([_fi[['ts_code', 'end_date', 'available_date', 'yoy_ta']],
                 _bs[['ts_code', 'end_date', 'available_date', 'yoy_ta']]], ignore_index=True)
_ta = _ta.sort_values(['ts_code', 'end_date', 'available_date']).drop_duplicates(['ts_code', 'end_date'], keep='last')
_yp = {}
for _d in [d for d in month_end_all if pd.Timestamp('2021-06-01') <= d <= pd.Timestamp(END)]:
    _yp[_d] = _ta[_ta['available_date'] <= _d].sort_values('end_date').groupby('ts_code').tail(1).set_index('ts_code')['yoy_ta']
_ydf = pd.DataFrame(_yp)
_ydf.index = [f"{c.split('.')[1].lower()}{c.split('.')[0]}" for c in _ydf.index]
F['yoy_total_asset'] = _ydf.T.reindex(columns=C.columns).reindex(cal, method='ffill')

# ---------------- 域与调仓日 ----------------
st = pd.read_csv(ROOT / 'data/external/tushare/a_share_st_status_pit_v1/normalized/st_status_intervals.csv.gz',
                 compression='gzip', parse_dates=['start_date', 'end_date'])
st_start, st_end = st['start_date'].values, st['end_date'].values
st_bad = (st['is_st'] | st['is_delist_phase']).values
st_code = st['ts_code'].values


def bad_at(t):
    mask = (st_start <= np.datetime64(t)) & (st_end >= np.datetime64(t)) & st_bad
    return {s.lower() for s in st_code[mask]}


trading_days = cal[cal >= BT_START]
td_s = pd.Series(trading_days, index=trading_days)
month_first = td_s.groupby(trading_days.to_period('M')).min().sort_values().tolist()
print(f'[bt] 调仓月数={len(month_first)}', flush=True)


def universe_at(t):
    bad = bad_at(t)
    n_listed = N_LISTED.loc[t]
    return [s for s in C.columns if s not in bad and pd.notna(n_listed.get(s, np.nan))
            and n_listed.get(s, 0) >= IPO_MIN_DAYS]


def rank_mean(signals, cols, t_day):
    """多源 rank 均值: 每源截面 pct rank（带方向符号），取可用源均值（≥3 源非缺失）。"""
    parts = []
    for name, sgn in signals:
        r = F[name].loc[t_day, cols].rank(pct=True)
        parts.append(sgn * r)
    stacked = pd.concat(parts, axis=1)
    cnt = stacked.notna().sum(axis=1)
    z = stacked.mean(axis=1)
    return z.where(cnt >= 3)


# 复合源定义（协议 §4 修订版）
Z_V0 = [('sum_abs_rtn_amount_20d', 1), ('amount_ma_20d', -1),
        ('bias_std_turn_42d_252d', -1), ('yoy_total_asset', 1)]
Z_V1 = [('alpha101_13', 1), ('alpha101_16', 1), ('alpha101_15', 1), ('alpha101_3', 1),
        ('alpha101_6', 1), ('alpha101_4', 1), ('alpha101_14', 1),
        ('bias_std_turn_21d_252d', -1)]


def weights_for(arm, t, t_day):
    cands = universe_at(t)
    if len(cands) < 300:
        return {}
    if arm == 'pool_ew':
        return {s: 1 / len(cands) for s in cands}
    if arm == 'bias_cool_top30':
        z = F['bias_std_turn_21d_252d'].loc[t_day, cands].dropna()
        sel = z.nsmallest(30).index.tolist()
    elif arm == 'a101_comp_top30':
        z = rank_mean(Z_V1[:7], cands, t_day)
        sel = z.nlargest(30).index.tolist()
    elif arm == 'z_comp_v0_top30':
        z = rank_mean(Z_V0, cands, t_day)
        sel = z.nlargest(30).index.tolist()
    elif arm in ('z_comp_v1_top30', 'z_comp_v1_top100', 'z_neutral_top30'):
        z = rank_mean(Z_V1, cands, t_day)
        if arm == 'z_neutral_top30':
            mv = mv_daily.loc[t_day, z.index]
            dec = pd.qcut(mv.rank(method='first'), 10, labels=False)
            z = z.groupby(dec).rank(pct=True)  # 十分位内重排名
            sel = z.nlargest(30).index.tolist()
        else:
            n = 100 if arm.endswith('top100') else 30
            sel = z.nlargest(n).index.tolist()
    else:
        raise ValueError(arm)
    if len(sel) < 20:
        return {}
    return {s: 1 / len(sel) for s in sel}


# ---------------- 回测引擎（同 q4_v2 + 可执行性过滤） ----------------
def run_arm(arm, cost):
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
        new_h = weights_for(arm, d, d)
        o_buy = O.loc[buy_day]
        v_buy = V.loc[buy_day]
        prev_c_buy = C.loc[buy_day - pd.Timedelta(days=1)] if False else PREV_C.loc[buy_day]
        # 可执行性: 买入日非涨停（对前收 <9.5%）且非停牌
        keep = {}
        for s, w in new_h.items():
            b = o_buy.get(s, np.nan)
            pc = prev_c_buy.get(s, np.nan)
            vb = v_buy.get(s, np.nan)
            if pd.isna(b) or b <= 0:
                continue
            if pd.notna(vb) and vb <= 0:
                continue
            if pd.notna(pc) and pc > 0 and b / pc - 1 >= 0.095:
                continue
            keep[s] = w
        if keep:
            wsum = sum(keep.values())
            new_h = {s: w / wsum for s, w in keep.items()}
        # 换手成本
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
        port = sum(rets) / wsum if wsum > 0 else 0.0
        cash *= (1 + port)
        navs.append((exit_d, cash, len(holdings)))
    df = pd.DataFrame(navs, columns=['datetime', 'nav', 'n']).set_index('datetime')
    return df, float(np.mean(turns)) if turns else np.nan


ARMS = ['bias_cool_top30', 'a101_comp_top30', 'z_comp_v0_top30', 'z_comp_v1_top30',
        'z_comp_v1_top100', 'z_neutral_top30', 'pool_ew']
COSTS = {'c15': 0.0015, 'c30': 0.0030, 'c50': 0.0050}

print('\n[bt] 7 臂 × 3 成本 ...', flush=True)
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

# csi1000 对照（费前，月度）
idx_close = read_bin('sh000852', 'close').reindex(month_first).dropna()
idx_ret = idx_close.pct_change().dropna()
idx_rows = []
for cname, _ in COSTS.items():
    seg = idx_ret[idx_ret.index >= BT_START]
    years = (seg.index[-1] - seg.index[0]).days / 365.25
    idx_rows.append({'arm': 'csi1000', 'cost': cname, 'CAGR': (1 + seg).prod() ** (1 / years) - 1,
                     'IR': np.nan, 'MDD': np.nan, 'final_nav': np.nan, 'avg_monthly_turnover': 0.0})
bt = pd.concat([bt, pd.DataFrame(idx_rows)], ignore_index=True)
bt.to_csv(OUT / 'backtest_summary.csv', index=False)

# 分年超额（c30 档，vs pool_ew）
print('\n[yearly] ...', flush=True)
yr_rows = []
for arm in ARMS:
    if arm == 'pool_ew':
        continue
    try:
        nav_a = nav_store[f'{arm}_c30']
        nav_p = nav_store[f'pool_ew_c30']
    except KeyError:
        continue
    ra, rp = nav_a.pct_change().dropna(), nav_p.pct_change().dropna()
    common = ra.index.intersection(rp.index)
    ex = (1 + ra[common]).groupby(common.year).prod() - (1 + rp[common]).groupby(common.year).prod()
    for y, v in ex.items():
        yr_rows.append({'arm': arm, 'year': int(y), 'excess_c30': v})
ydf = pd.DataFrame(yr_rows)
ydf.to_csv(OUT / 'yearly_excess.csv', index=False)
print(ydf.pivot_table(index='arm', columns='year', values='excess_c30').round(4).to_string())

# 崩盘段
cr = []
for k, nav in nav_store.items():
    pre = nav.loc[:'2023-12-31']
    peak = nav.loc[:'2024-02-29']
    if len(pre) and len(peak):
        cr.append({'nav': k, 'crash_return': peak.iloc[-1] / pre.iloc[-1] - 1})
pd.DataFrame(cr).to_csv(OUT / 'crash_2024.csv', index=False)

# ---------------- 判定 ----------------
print('\n=== 判定（c30 主判定档 vs pool_ew） ===')
pool = bt[(bt['arm'] == 'pool_ew') & (bt['cost'] == 'c30')]['CAGR'].iloc[0]
dec = []
for _, r in bt[(bt['cost'] == 'c30')].iterrows():
    if r['arm'] in ('pool_ew', 'csi1000'):
        continue
    ex = r['CAGR'] - pool
    if r['arm'] == 'z_comp_v1_top30':
        tier = ('survive' if (ex >= 0.03 and r['IR'] >= 0.5)
                else ('marginal' if ex > 0 else 'dead'))
    else:
        tier = 'attribution_' + ('positive' if ex > 0 else 'negative')
    dec.append({'arm': r['arm'], 'CAGR': r['CAGR'], 'pool_CAGR': pool, 'excess': ex,
                'IR': r['IR'], 'MDD': r['MDD'], 'tier': tier})
dd = pd.DataFrame(dec)
dd.to_csv(OUT / 'decision_excess.csv', index=False)
print(dd.round(4).to_string(index=False))

# 分年一致性（主判定臂）
try:
    main_y = ydf[ydf['arm'] == 'z_comp_v1_top30']
    years_pos = int((main_y['excess_c30'] > 0).sum())
    years_total = len(main_y)
except Exception:
    years_pos, years_total = -1, -1

# 规模β裁决: 主判定臂 vs 中性臂
z_ex = dd[dd['arm'] == 'z_comp_v1_top30']['excess'].iloc[0] if len(dd[dd['arm'] == 'z_comp_v1_top30']) else np.nan
zn_ex = dd[dd['arm'] == 'z_neutral_top30']['excess'].iloc[0] if len(dd[dd['arm'] == 'z_neutral_top30']) else np.nan
# 协议 §5 顺序: 主臂过全部门槛(含崩盘) 且 中性臂过线 → survive;
# 主臂过线但中性臂不过线 → scale_beta_disguised(关闭); 主臂不过线 → not_survived
main_row = bt[(bt['arm'] == 'z_comp_v1_top30') & (bt['cost'] == 'c30')].iloc[0]
cr_row = [r for r in cr if r['nav'] == 'z_comp_v1_top30_c30']
pool_cr = [r for r in cr if r['nav'] == 'pool_ew_c30']
crash_ok = (cr_row and pool_cr and cr_row[0]['crash_return'] >= pool_cr[0]['crash_return'] - 0.05)
main_pass = (z_ex >= 0.03) and (main_row['IR'] >= 0.5) and crash_ok
zn_row = bt[(bt['arm'] == 'z_neutral_top30') & (bt['cost'] == 'c30')].iloc[0]
neutral_pass = (zn_ex >= 0.03) and (zn_row['IR'] >= 0.5)
verdict = ('survive' if (main_pass and neutral_pass)
           else ('scale_beta_disguised' if main_pass else 'not_survived'))

decision = {'protocol': 'research/protocols/market_survivors_validation_protocol_v1.md',
            'verdict': verdict,
            'z_comp_v1_excess_c30': float(z_ex), 'z_neutral_excess_c30': float(zn_ex),
            'main_arm_years_positive': f'{years_pos}/{years_total}',
            'pool_cagr_c30': float(pool),
            'arms': dd.to_dict('records')}
(OUT / 'decision.json').write_text(json.dumps(decision, ensure_ascii=False, indent=2) + '\n')
print(f"\nverdict: {verdict}, z_v1 超额={z_ex:+.1%}, 中性臂={zn_ex:+.1%}, 分年正={years_pos}/{years_total}, crash_ok={crash_ok}")
