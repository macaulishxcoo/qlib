#!/usr/bin/env python3
"""财务困境分层假设检验 v1（协议: research/protocols/a_share_distress_split_protocol_v1.md）。

在 5 个历史时点用 PIT 财务重建"连续两年年报亏损"名单，按主业崩坏(G1)/周期底(G2)
拆分，观察各时点至 2026-08-13 的等权收益，对照全市场。事件层检验，不计成本。
"""
from __future__ import annotations

import json
import os
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path('/home/xiaocong/worksapces/qlib')
sys.path.insert(0, str(ROOT / 'scripts'))
FEAT = Path(os.path.expanduser('~')) / '.qlib/qlib_data/cn_data_2026/features'
OUT = ROOT / 'output/analysis_fundamental/a_share_distress_split_v1'
TODAY = pd.Timestamp('2026-08-13')

cal = pd.DatetimeIndex(pd.read_csv(FEAT.parent / 'calendars' / 'day.txt', header=None)[0])
cal_pos = {d: i for i, d in enumerate(cal)}


def recent_day(target: pd.Timestamp) -> pd.Timestamp:
    prior = cal[cal <= target]
    return prior[-1]


# ---------------- 数据 ----------------
from load_financials_extended_v1 import load_financials_extended  # noqa: E402

fin = load_financials_extended()
# 补充 op_income / or_yoy（fina_indicator 顶层文件）
fin_top = pd.read_csv(ROOT / 'data/external/tushare/a_share_financial_pit_v1/normalized/fina_indicator.csv.gz',
                      compression='gzip', low_memory=False,
                      usecols=['ts_code', 'end_date', 'available_date', 'op_income', 'or_yoy'])
for c in ('end_date', 'available_date'):
    fin_top[c] = pd.to_datetime(fin_top[c].astype(str).str.replace('-', '', regex=False),
                                format='%Y%m%d', errors='coerce')
fin_top = fin_top.drop_duplicates(['ts_code', 'end_date', 'available_date'], keep='last')
print(f'[data] fin rows={len(fin)}, fin_top rows={len(fin_top)}', flush=True)

st = pd.read_csv(ROOT / 'data/external/tushare/a_share_st_status_pit_v1/normalized/st_status_intervals.csv.gz',
                 compression='gzip', parse_dates=['start_date', 'end_date'])

db = pd.read_csv(ROOT / 'data/external/tushare/a_share_daily_basic_pit_v1/normalized/daily_basic.csv.gz',
                 compression='gzip', usecols=['ts_code', 'trade_date'], dtype={'trade_date': str})
db = db[db['trade_date'] == db['trade_date'].max()]
hs_codes = [c for c in db['ts_code'] if not c.split('.')[0].startswith(('43', '83', '87', '92', '920'))]
hs_set = set(hs_codes)
print(f'[data] 沪深三板块股票数={len(hs_codes)}', flush=True)


def build_groups(asof: pd.Timestamp):
    """PIT 重建: 返回 (g1_collapse, g2_cycle, bps_neg_nonst, st_excluded_count)。"""
    avail = fin[fin['available_date'] <= asof]
    # 收入/同比列
    inc_top = fin_top[fin_top['available_date'] <= asof]

    # 连续两个年报亏损（用 n_income_attr_p）
    income = avail[['ts_code', 'end_date', 'available_date', 'n_income_attr_p']].copy()
    income = income[income['end_date'].dt.month == 12]
    income = income.sort_values(['ts_code', 'end_date', 'available_date']) \
        .drop_duplicates(['ts_code', 'end_date'], keep='last')

    two_loss, loss_detail = [], {}
    for code, grp in income.groupby('ts_code'):
        yrs = grp.sort_values('end_date', ascending=False).head(2)
        if len(yrs) >= 2 and (yrs['n_income_attr_p'] < 0).sum() == 2:
            code = str(code)
            if code in hs_set:
                two_loss.append(code)
                loss_detail[code] = yrs['end_date'].iloc[0]  # 最近年报期

    # ST 排除
    active_st = st[(st['start_date'] <= asof) & (st['end_date'] >= asof) & (st['is_st'] == True)]
    st_codes = set(active_st['ts_code'])
    two_loss = [c for c in two_loss if c not in st_codes]

    # 拆分维度: 最近年报期的 or_yoy（退化: op_income 同期对比）与 n_cashflow_act
    inc_annual = inc_top[inc_top['end_date'].dt.month == 12] if hasattr(inc_top['end_date'], 'dt') else None
    g1, g2, undetermined = [], [], []
    for code in two_loss:
        ld = loss_detail[code]
        # or_yoy（最新版本）
        rows = inc_top[(inc_top['ts_code'] == code) & (inc_top['end_date'] == ld)]
        or_yoy = rows['or_yoy'].dropna()
        ocf = fin[(fin['ts_code'] == code) & (fin['end_date'] == ld) & (fin['available_date'] <= asof)]
        ocf_val = ocf['n_cashflow_act'].dropna()
        ocf_negative = bool(len(ocf_val) and ocf_val.iloc[-1] < 0)
        if len(or_yoy):
            rev_decline = bool(or_yoy.iloc[-1] < 0)
        else:
            # 退化: 与上一期年报 op_income 对比
            rows_all = inc_top[(inc_top['ts_code'] == code) & (inc_top['end_date'].dt.month == 12) &
                               (inc_top['end_date'] <= ld)].sort_values('end_date')
            ops = rows_all[['end_date', 'op_income']].dropna().drop_duplicates('end_date', keep='last')
            if len(ops) >= 2 and pd.notna(ops['op_income'].iloc[-2]) and ops['op_income'].iloc[-2] != 0:
                rev_decline = bool(ops['op_income'].iloc[-1] < ops['op_income'].iloc[-2])
            else:
                undetermined.append(code)
                continue
        (g1 if (rev_decline and ocf_negative) else g2).append(code)

    # bps<0 硬排除层（单列记录，不参与分组检验）
    latest = avail.sort_values(['ts_code', 'end_date', 'available_date']).drop_duplicates('ts_code', keep='last')
    bps_neg = set(latest[(latest['bps'] < 0) & (latest['ts_code'].isin(hs_set))]['ts_code']) - st_codes

    return set(g1), set(g2), set(undetermined), bps_neg, len(st_codes)


# ---------------- 行情 ----------------
_cache = {}


def read_close(symbol: str):
    if symbol in _cache:
        return _cache[symbol]
    p = FEAT / symbol / 'close.day.bin'
    if not p.exists():
        _cache[symbol] = None
        return None
    with open(p, 'rb') as f:
        raw = f.read()
    arr = np.frombuffer(raw, dtype='<f')
    start = int(arr[0])
    vals = arr[1:]
    s = pd.Series(vals, index=cal[start:start + len(vals)])
    _cache[symbol] = s
    return s


def ts_to_symbol(ts_code: str) -> str:
    num, ex = ts_code.split('.')
    return f'{ex.lower()}{num}'


def group_ret(codes, t0, t1):
    rets, missing = [], 0
    for c in codes:
        s = read_close(ts_to_symbol(c))
        if s is None or t0 not in s.index:
            missing += 1
            continue
        c0 = s[t0]
        seg = s.loc[:t1].dropna()
        if len(seg) == 0 or c0 <= 0:
            missing += 1
            continue
        c1 = seg.iloc[-1]
        if c1 <= 0:
            missing += 1
            continue
        r = c1 / c0 - 1
        if np.isfinite(r):
            rets.append(r)
    arr = np.array(rets, dtype=float)
    return arr, missing


TARGETS = {
    '2y_2024-08': pd.Timestamp('2024-08-13'),
    '1.5y_2025-02': pd.Timestamp('2025-02-13'),
    '1y_2025-08': pd.Timestamp('2025-08-13'),
    '6m_2026-02': pd.Timestamp('2026-02-13'),
    '3m_2026-05': pd.Timestamp('2026-05-13'),
}

print('预载行情 ...', flush=True)
with ThreadPoolExecutor(max_workers=16) as ex:
    list(ex.map(read_close, [ts_to_symbol(c) for c in hs_codes]))
print('完成', flush=True)

rows, detail = [], []
for label, t_target in TARGETS.items():
    t = recent_day(t_target)
    g1, g2, undet, bps_neg, n_st = build_groups(t)
    full_arr, full_miss = group_ret(hs_codes, t, TODAY)
    g1_arr, g1_miss = group_ret(list(g1), t, TODAY)
    g2_arr, g2_miss = group_ret(list(g2), t, TODAY)
    for name, arr, miss, n in [('G1_collapse', g1_arr, g1_miss, len(g1)),
                               ('G2_cycle', g2_arr, g2_miss, len(g2)),
                               ('full_market', full_arr, full_miss, len(hs_codes))]:
        rows.append({
            'window': label, 'asof': str(t.date()), 'group': name,
            'n_listed': n, 'n_with_return': len(arr), 'missing': miss,
            'ew_return': float(arr.mean()) if len(arr) else np.nan,
            'median_return': float(np.median(arr)) if len(arr) else np.nan,
            'loss_ratio': float((arr < 0).mean()) if len(arr) else np.nan,
        })
    excess = (g1_arr.mean() - g1_arr.mean()) if False else None
    detail.append({
        'window': label, 'asof': str(t.date()),
        'n_g1': len(g1), 'n_g2': len(g2), 'n_undetermined': len(undet), 'n_bps_neg': len(bps_neg),
        'n_st_excluded': n_st,
        'g1_ew': float(g1_arr.mean()) if len(g1_arr) else np.nan,
        'g2_ew': float(g2_arr.mean()) if len(g2_arr) else np.nan,
        'full_ew': float(full_arr.mean()) if len(full_arr) else np.nan,
        'g1_minus_g2': float(g1_arr.mean() - g2_arr.mean()) if len(g1_arr) and len(g2_arr) else np.nan,
        'g1_vs_full': float(g1_arr.mean() - full_arr.mean()) if len(g1_arr) else np.nan,
        'g2_vs_full': float(g2_arr.mean() - full_arr.mean()) if len(g2_arr) else np.nan,
    })
    d = detail[-1]
    print(f"{label}: G1={d['n_g1']}({d['g1_ew']:+.1%}) G2={d['n_g2']}({d['g2_ew']:+.1%}) "
          f"全市场={d['full_ew']:+.1%} G1-G2={d['g1_minus_g2']:+.1%} 未定={d['n_undetermined']}", flush=True)

OUT.mkdir(parents=True, exist_ok=True)
perf = pd.DataFrame(rows)
det = pd.DataFrame(detail)
perf.to_csv(OUT / 'group_performance.csv', index=False)
det.to_csv(OUT / 'window_summary.csv', index=False)

# ---------------- 判定 ----------------
valid = det.dropna(subset=['g1_minus_g2'])
n_g1_worse = int((valid['g1_minus_g2'] < 0).sum())
n_windows = len(valid)
if n_g1_worse >= 4:
    decision = 'distress_split_supported'
elif n_g1_worse <= 2:
    decision = 'distress_split_not_supported'
else:
    decision = 'distress_split_mixed'

meta = {
    'protocol': 'research/protocols/a_share_distress_split_protocol_v1.md',
    'asof_today': str(TODAY.date()),
    'n_windows': n_windows,
    'n_g1_worse_than_g2': n_g1_worse,
    'decision': decision,
    'note': 'bps<0 硬排除层不在本检验范围（协议 §2）',
}
(OUT / 'decision.json').write_text(json.dumps(meta, ensure_ascii=False, indent=2) + '\n')
print('\n', json.dumps(meta, ensure_ascii=False, indent=2))
