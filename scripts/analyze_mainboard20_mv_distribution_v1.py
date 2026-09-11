#!/usr/bin/env python3
"""沪深主板末20%域市值分布统计 v1。

口径：
- 月份：daily_basic 全部月末（2016-01 ~ 2026-08）；
- 域：沪深主板（沪 600/601/603/605 + 深 000/001/002/003）内按 total_mv 截面末 20%；
- 输出：域内市值的分位分布（总市值/流通市值，亿元），逐月 + 分年 + 全样本汇总 + 最新截面。
"""
from __future__ import annotations
import os
from pathlib import Path
import numpy as np
import pandas as pd

ROOT = Path('/home/xiaocong/worksapces/qlib')
DB = ROOT / 'data/external/tushare/a_share_daily_basic_pit_v1/normalized/daily_basic.csv.gz'
OUT = ROOT / 'output/analysis_fundamental/mainboard20_mv_distribution_v1'
OUT.mkdir(parents=True, exist_ok=True)

db = pd.read_csv(DB, compression='gzip',
                 usecols=['ts_code', 'trade_date', 'total_mv', 'circ_mv', 'free_share', 'close'],
                 dtype={'trade_date': str})
db['dt'] = pd.to_datetime(db['trade_date'], format='%Y%m%d')
db['num'] = db['ts_code'].str.split('.').str[0]
db = db[~db['num'].str.startswith(('43', '83', '87', '92', '920'))]
db['board'] = np.where(db['num'].str.startswith('68'), 'star',
              np.where(db['num'].str.startswith('30'), 'chinext',
              np.where(db['num'].str.startswith(('600', '601', '603', '605')), 'sse_main',
              np.where(db['num'].str.startswith(('000', '001', '002', '003')), 'szse_main', 'other'))))
db = db[db['board'].isin(['sse_main', 'szse_main'])]
# 总市值(亿元)、流通市值(亿元)、自由流通市值(亿元)
db['total_mv_yi'] = db['total_mv'] / 1e4
db['circ_mv_yi'] = db['circ_mv'] / 1e4
db['free_mv_yi'] = db['free_share'] * 1e4 * db['close'] / 1e8  # free_share 万股
month_end = db.groupby(db['dt'].dt.to_period('M'))['dt'].max().sort_values()
print(f'[data] 主板月末数={len(month_end)}, {month_end.iloc[0].date()} ~ {month_end.iloc[-1].date()}', flush=True)

QS = [0.0, 0.01, 0.05, 0.10, 0.25, 0.50, 0.75, 0.90, 0.95, 0.99, 1.0]
QL = ['min', 'p1', 'p5', 'p10', 'p25', 'p50', 'p75', 'p90', 'p95', 'p99', 'max']
rows = []
for d in month_end:
    g = db[db['dt'] == d]
    mv = g['total_mv_yi'].dropna()
    if len(mv) < 100:
        continue
    thr = mv.quantile(0.20)
    dom = g[g['total_mv_yi'] <= thr]
    q = dom['total_mv_yi'].quantile(QS).values
    qc = dom['circ_mv_yi'].dropna().quantile(QS).values
    qf = dom['free_mv_yi'].dropna().quantile(QS).values
    rows.append({'date': str(d.date()), 'n_domain': len(dom), 'thr20': thr,
                 **{f'total_{k}': v for k, v in zip(QL, q)},
                 **{f'circ_{k}': v for k, v in zip(QL, qc)},
                 **{f'free_{k}': v for k, v in zip(QL, qf)}})
dist = pd.DataFrame(rows)
dist['year'] = dist['date'].str[:4]
dist.to_csv(OUT / 'monthly_distribution.csv', index=False)

# 分年（各年月末中位数）
yr = dist.groupby('year')[['thr20', 'n_domain', 'total_p10', 'total_p25', 'total_p50',
                           'total_p75', 'total_p90', 'total_max']].median()
yr.to_csv(OUT / 'yearly_distribution.csv')

# 全样本汇总（所有月末域内池化）
allq = {}
for col, lab in [('total_mv_yi', '总市值'), ('circ_mv_yi', '流通市值'), ('free_mv_yi', '自由流通市值')]:
    vals = []
    for d in month_end:
        g = db[db['dt'] == d]
        mv = g['total_mv_yi'].dropna()
        if len(mv) < 100:
            continue
        thr = mv.quantile(0.20)
        vals.append(g[g['total_mv_yi'] <= thr][col].dropna())
    pooled = pd.concat(vals).values
    allq[lab] = dict(zip(QL, np.quantile(pooled, QS)))
pool = pd.DataFrame(allq)
pool.to_csv(OUT / 'pooled_distribution.csv')

print('\n' + '=' * 92)
print('沪深主板末20%域市值分布（亿元；月内截面末20%，月度重建）')
print('=' * 92)
print('\n【全样本池化分位】')
print(pool.round(1).to_string())
print('\n【分年（各年末月中位数，亿元）】')
print(yr.round(1).to_string())
print('\n【最新截面 ' + dist["date"].iloc[-1] + '】')
last = db[db['dt'] == month_end.iloc[-1]]
mv = last['total_mv_yi'].dropna(); thr = mv.quantile(0.20)
dom = last[last['total_mv_yi'] <= thr]
print(f'  末20%阈值: {thr:.1f} 亿元; 数量: {len(dom)}')
t = dom['total_mv_yi']
print(f'  总市值: min={t.min():.1f} p10={t.quantile(.1):.1f} p25={t.quantile(.25):.1f} '
      f'p50={t.median():.1f} p75={t.quantile(.75):.1f} p90={t.quantile(.9):.1f} max={t.max():.1f}')
c = dom['circ_mv_yi'].dropna()
print(f'  流通市值: min={c.min():.1f} p10={c.quantile(.1):.1f} p25={c.quantile(.25):.1f} '
      f'p50={c.median():.1f} p75={c.quantile(.75):.1f} p90={c.quantile(.9):.1f} max={c.max():.1f}')
print(f'\n落盘: {OUT}')
