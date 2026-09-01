#!/usr/bin/env python3
"""板块/市值/风险状态分层分析工具 v1。

把本项目反复使用的横截面分层统计固化为一个 CLI 工具，供后续策略研究做
"分层报告"（研究母池章程 §3 的分层报告要求）。能力：

  1. 板块分层：任意时点的沪深主板/创业板/科创板（北交所默认排除）市值分布；
  2. 市值分档：按分位数（末 10%）或绝对阈值（如 ≤20 亿）切档，输出数量、
     板块分布、市值区间；
  3. 风险状态：ST（PIT 区间）、退市整理、准ST（bps<0 / 连续两年年报亏损）
     的占比与交集；
  4. 流动性：换手率/量比分布对照。

数据源（全部既有资产，只读）：
  - data/external/tushare/a_share_daily_basic_pit_v1/normalized/daily_basic.csv.gz
  - data/external/tushare/a_share_st_status_pit_v1/normalized/st_status_intervals.csv.gz
  - data/external/tushare/a_share_financial_pit_v1/normalized/fina_indicator.csv.gz
  - data/external/tushare/a_share_financial_pit_v1/{full,recent_3tables}/（income）

用法：
  python scripts/analyze_board_segmentation_v1.py                     # 最新交易日
  python scripts/analyze_board_segmentation_v1.py --trade-date 20260813
  python scripts/analyze_board_segmentation_v1.py --tail-pct 0.10     # 末10%档
  python scripts/analyze_board_segmentation_v1.py --thresholds 50 30 20
  python scripts/analyze_board_segmentation_v1.py --out report.csv    # 落盘
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / 'scripts'))
from load_financials_extended_v1 import load_financials_extended  # noqa: E402

DB_PATH = ROOT / 'data/external/tushare/a_share_daily_basic_pit_v1/normalized/daily_basic.csv.gz'
ST_PATH = ROOT / 'data/external/tushare/a_share_st_status_pit_v1/normalized/st_status_intervals.csv.gz'
FIN_TOP = ROOT / 'data/external/tushare/a_share_financial_pit_v1/normalized/fina_indicator.csv.gz'
CLS_PATH = ROOT / 'data/derived/a_share_stock_classification_v2/monthly_stock_classification.csv.gz'

BSE_PREFIX = ('43', '83', '87', '92', '920')
SH_MAIN = ('600', '601', '603', '605')
SZ_MAIN = ('000', '001', '002', '003')


def board_of(ts_code: str) -> str:
    num = str(ts_code).split('.')[0]
    if num.startswith('68'):
        return '科创板'
    if num.startswith('30'):
        return '创业板'
    if num.startswith(SH_MAIN):
        return '沪主板'
    if num.startswith(SZ_MAIN):
        return '深主板'
    if num.startswith(BSE_PREFIX):
        return '北交所'
    return '其他'


def load_cross_section(trade_date: str | None) -> pd.DataFrame:
    usecols = ['ts_code', 'trade_date', 'total_mv', 'circ_mv',
               'turnover_rate', 'turnover_rate_f', 'volume_ratio']
    db = pd.read_csv(DB_PATH, compression='gzip', usecols=usecols, dtype={'trade_date': str})
    date = trade_date or db['trade_date'].max()
    if date not in set(db['trade_date']):
        raise SystemExit(f'trade_date {date} 不在 daily_basic 覆盖内 '
                         f'({db["trade_date"].min()} ~ {db["trade_date"].max()})')
    df = db[db['trade_date'] == date].copy()
    df['board'] = df['ts_code'].map(board_of)
    df = df[df['board'] != '北交所'].copy()  # 章程：北交所不在沪深母池
    df['total_mv_yi'] = df['total_mv'] / 1e4
    df['circ_mv_yi'] = df['circ_mv'] / 1e4
    return df, date


def load_st_sets(asof: pd.Timestamp) -> tuple[set, set]:
    st = pd.read_csv(ST_PATH, compression='gzip', parse_dates=['start_date', 'end_date'])
    active = st[(st['start_date'] <= asof) & (st['end_date'] >= asof)]
    st_codes = set(active.loc[active['is_st'] == True, 'ts_code'])  # noqa: E712
    delist = set(active.loc[active['is_delist_phase'] == True, 'ts_code'])  # noqa: E712
    return st_codes, delist


def load_quasi_st(asof: pd.Timestamp) -> tuple[set, set]:
    """(bps<0 集合, 连续两年年报亏损集合)，均剔除当时已 ST。"""
    fin = load_financials_extended()
    avail = fin[fin['available_date'] <= asof]
    latest = avail.sort_values(['ts_code', 'end_date', 'available_date']) \
        .drop_duplicates('ts_code', keep='last')
    neg_bps = set(latest[latest['bps'] < 0]['ts_code'])

    income = avail[['ts_code', 'end_date', 'available_date', 'n_income_attr_p']].copy()
    income = income[income['end_date'].dt.month == 12]
    income = income.sort_values(['ts_code', 'end_date', 'available_date']) \
        .drop_duplicates(['ts_code', 'end_date'], keep='last')
    two_loss = set()
    for code, grp in income.groupby('ts_code'):
        yrs = grp.sort_values('end_date', ascending=False).head(2)
        if len(yrs) >= 2 and (yrs['n_income_attr_p'] < 0).sum() == 2:
            two_loss.add(code)
    return neg_bps, two_loss


def fmt_pct(x) -> str:
    return f'{100 * x:.1f}%' if pd.notna(x) else '-'


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--trade-date', default=None, help='YYYYMMDD（默认最新）')
    ap.add_argument('--tail-pct', type=float, default=0.10, help='尾部档分位（默认 0.10）')
    ap.add_argument('--thresholds', type=float, nargs='*', default=[],
                    help='附加绝对市值阈值档（亿元），如 --thresholds 30 20')
    ap.add_argument('--with-quasi-st', action='store_true',
                    help='加载准ST统计（需读财务 PIT，较慢）')
    ap.add_argument('--out', default=None, help='CSV 落盘路径')
    args = ap.parse_args()

    df, date = load_cross_section(args.trade_date)
    asof = pd.Timestamp(date)
    n_total = len(df)
    print(f'截面: {date}（沪深三板块，北交所已排除） n={n_total}')
    print()

    # ---- 1. 板块分层市值分布 ----
    print('=== 1. 板块分层市值分布（总市值，亿元） ===')
    rows = []
    for b in ['沪主板', '深主板', '创业板', '科创板']:
        sub = df[df['board'] == b]['total_mv_yi'].dropna()
        rows.append({
            '板块': b, '数量': len(sub),
            '中位': round(sub.median(), 1), '均值': round(sub.mean(), 1),
            'p25': round(sub.quantile(.25), 1), 'p75': round(sub.quantile(.75), 1),
            'min': round(sub.min(), 1), 'max': round(sub.max(), 1),
        })
    board_tbl = pd.DataFrame(rows)
    print(board_tbl.to_string(index=False))
    print()

    # ---- 2. 市值分档 ----
    thr_pct = df['total_mv_yi'].quantile(args.tail_pct)
    buckets = [(f'末{args.tail_pct:.0%}(≤{thr_pct:.1f}亿)', df['total_mv_yi'] <= thr_pct)]
    for t in args.thresholds:
        buckets.append((f'≤{t}亿', df['total_mv_yi'] <= t))

    print(f'=== 2. 市值分档（阈值来自 --tail-pct / --thresholds） ===')
    bucket_rows = []
    for name, mask in buckets:
        sub = df[mask]
        by_board = sub['board'].value_counts().to_dict()
        bucket_rows.append({
            '档': name, '数量': len(sub), '占比': fmt_pct(len(sub) / n_total),
            '沪主板': by_board.get('沪主板', 0), '深主板': by_board.get('深主板', 0),
            '创业板': by_board.get('创业板', 0), '科创板': by_board.get('科创板', 0),
            '市值min': round(sub['total_mv_yi'].min(), 1) if len(sub) else None,
            '市值max': round(sub['total_mv_yi'].max(), 1) if len(sub) else None,
        })
    bucket_tbl = pd.DataFrame(bucket_rows)
    print(bucket_tbl.to_string(index=False))
    print()

    # ---- 3. ST / 退市 / 换手 ----
    st_codes, delist_codes = load_st_sets(asof)
    df['is_st'] = df['ts_code'].isin(st_codes)
    df['is_delist'] = df['ts_code'].isin(delist_codes)

    # ---- 4. 准ST（可选，先标记再切片，保证 tail 带上全部标记列） ----
    quasi_tbl = None
    if args.with_quasi_st:
        neg_bps, two_loss = load_quasi_st(asof)
        quasi = (neg_bps | two_loss)
        df['is_quasi'] = df['ts_code'].isin(quasi - st_codes)

    tail = df[buckets[0][1]].copy()

    print('=== 3. 风险状态与流动性（对照：末档 vs 全市场） ===')
    for name, sub in [('末档', tail), ('全市场', df)]:
        st_n = int(sub['is_st'].sum())
        dl_n = int(sub['is_delist'].sum())
        tr = sub['turnover_rate'].dropna()
        print(f'{name}: n={len(sub)}, ST={st_n}({fmt_pct(st_n/len(sub))}), '
              f'退市整理={dl_n}, 换手中位={tr.median():.2f}%, 量比中位={sub["volume_ratio"].median():.2f}')
    print()

    if args.with_quasi_st:
        print('=== 4. 准ST（bps<0 或 连续两年年报亏损，剔除已ST） ===')
        rows = []
        for name, sub in [('全市场', df), ('末档', tail)]:
            q = int(sub['is_quasi'].sum())
            s = int(sub['is_st'].sum())
            rows.append({'池': name, '数量': len(sub), '准ST': q,
                         '准ST占比': fmt_pct(q / len(sub)),
                         '已ST': s, 'ST+准ST': fmt_pct((q + s) / len(sub))})
        quasi_tbl = pd.DataFrame(rows)
        print(quasi_tbl.to_string(index=False))

    # ---- 落盘 ----
    if args.out:
        out = Path(args.out)
        out.parent.mkdir(parents=True, exist_ok=True)
        with open(out, 'w') as f:
            f.write(f'# 截面 {date}\n\n[板块分布]\n')
            board_tbl.to_csv(f, index=False)
            f.write('\n[市值分档]\n')
            bucket_tbl.to_csv(f, index=False)
            if quasi_tbl is not None:
                f.write('\n[准ST]\n')
                quasi_tbl.to_csv(f, index=False)
        print(f'\n已落盘: {out}')


if __name__ == '__main__':
    main()
