#!/usr/bin/env python3
"""导出 pa 与 np_ttm_qoq 因子月度面板为 CSV（growth15 检验的原始截面值）。

复用 analyze_growth15_dual_arm_v1 的构建逻辑，导出每月末截面：
ts_code, date, factor_value（未 rank 化的原始值），附加同日截面 pct rank。
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path('/home/xiaocong/worksapces/qlib')
sys.path.insert(0, str(ROOT / 'scripts'))
FIN_TOP = ROOT / 'data/external/tushare/a_share_financial_pit_v1/normalized/fina_indicator.csv.gz'
OUT = ROOT / 'output/analysis_static/growth15_dual_arm_v1'
OUT.mkdir(parents=True, exist_ok=True)

# ---- 财务 PIT ----
fin = pd.read_csv(FIN_TOP, compression='gzip', low_memory=False,
                  usecols=['ts_code', 'end_date', 'ann_date', 'available_date', 'roa'])
for c in ('end_date', 'available_date'):
    fin[c] = pd.to_datetime(fin[c].astype(str).str.replace('-', '', regex=False),
                            format='%Y%m%d', errors='coerce')
fin = fin.dropna(subset=['available_date'])
fin = fin.drop_duplicates(['ts_code', 'end_date', 'available_date'], keep='last')

from load_financials_extended_v1 import load_financials_extended  # noqa: E402
fin3 = load_financials_extended()


def ttm_series(frame, val_col):
    df = frame[['ts_code', 'end_date', 'available_date', val_col]].dropna()
    df = df.sort_values(['ts_code', 'end_date', 'available_date']).drop_duplicates(['ts_code', 'end_date'], keep='last')

    def _ttm(g):
        g = g.sort_values('end_date')
        ttm = g[val_col].rolling(4).sum()
        return pd.DataFrame({'ts_code': g['ts_code'].values, 'end_date': g['end_date'].values,
                             'available_date': g['available_date'].values, 'ttm': ttm.values})
    return df.groupby('ts_code', group_keys=False).apply(_ttm)


income_ttm = ttm_series(fin3.dropna(subset=['n_income_attr_p']), 'n_income_attr_p')

# roa 序列（同比用）
roa_seq = fin[['ts_code', 'end_date', 'available_date', 'roa']].dropna()
roa_seq = roa_seq.sort_values(['ts_code', 'end_date', 'available_date']).drop_duplicates(['ts_code', 'end_date'], keep='last')
roa_seq = roa_seq.sort_values(['ts_code', 'end_date'])
roa_seq['roa_prev_y'] = roa_seq.groupby('ts_code')['roa'].shift(4)

# ---- 月末截面 ----
db = pd.read_csv(ROOT / 'data/external/tushare/a_share_daily_basic_pit_v1/normalized/daily_basic.csv.gz',
                 compression='gzip', usecols=['ts_code', 'trade_date'], dtype={'trade_date': str})
db['dt'] = pd.to_datetime(db['trade_date'], format='%Y%m%d')
db = db[~db['ts_code'].str.split('.').str[0].str.startswith(('43', '83', '87', '92', '920'))]
month_end_all = db.groupby(db['dt'].dt.to_period('M'))['dt'].max().sort_values()
me_list = [d for d in month_end_all if d >= pd.Timestamp('2021-12-01')]

rows_pa, rows_np = [], []
for d in me_list:
    # pa: ROA 同比变化（pa 协议口径: 域内月度 IC 用的二阶差分在数据不足时退化为同比变化）
    seq = roa_seq[roa_seq['available_date'] <= d].sort_values('end_date').groupby('ts_code').tail(2)
    seq = seq[~seq.index.duplicated(keep='last')] if seq.index.duplicated().any() else seq
    seq = seq.set_index('ts_code')
    pa = seq['roa'] - seq['roa_prev_y']
    pa = pa.replace([np.inf, -np.inf], np.nan).dropna()
    for code, v in pa.items():
        rows_pa.append({'ts_code': code, 'date': str(d.date()), 'pa': v})
    # np_ttm_qoq: 净利 TTM 环比
    inc_lat = income_ttm[income_ttm['available_date'] <= d].sort_values('end_date').groupby('ts_code').tail(2)
    piv = inc_lat.pivot_table(index='ts_code', columns='end_date', values='ttm')
    if piv.shape[1] >= 2:
        cols = sorted(piv.columns)
        npq = piv[cols[-1]] / piv[cols[-2]].replace(0, np.nan) - 1
        npq = npq.replace([np.inf, -np.inf], np.nan).dropna()
        for code, v in npq.items():
            rows_np.append({'ts_code': code, 'date': str(d.date()), 'np_ttm_qoq': v})
    if len(rows_pa) % 200000 < 5000:
        print(f'  {d.date()} pa_rows={len(rows_pa)} np_rows={len(rows_np)}', flush=True)

pa_df = pd.DataFrame(rows_pa)
np_df = pd.DataFrame(rows_np)
# 附加截面 pct rank
pa_df['pa_rank_pct'] = pa_df.groupby('date')['pa'].rank(pct=True)
np_df['np_ttm_qoq_rank_pct'] = np_df.groupby('date')['np_ttm_qoq'].rank(pct=True)
pa_df.to_csv(OUT / 'factor_panel_pa_monthly.csv.gz', index=False, compression='gzip')
np_df.to_csv(OUT / 'factor_panel_np_ttm_qoq_monthly.csv.gz', index=False, compression='gzip')
print(f'\npa: {len(pa_df)} rows, {pa_df["date"].nunique()} months -> factor_panel_pa_monthly.csv.gz')
print(f'np_ttm_qoq: {len(np_df)} rows, {np_df["date"].nunique()} months -> factor_panel_np_ttm_qoq_monthly.csv.gz')
