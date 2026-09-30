#!/usr/bin/env python3
"""财务 PIT 数据层：季度表 → 日频 as-of 宽面板。

PIT 纪律（协议 §7）：一律以 `available_date`（公告可得日）为键，向后填充到日频；
禁止把未来报表倒填到过去。TTM = 最近 4 个报告期求和；prev4 = 同年前推 4 个季度。
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path('/home/xiaocong/worksapces/qlib')
sys.path.insert(0, str(ROOT / 'scripts'))

from load_financials_extended_v1 import (  # noqa: E402
    _fill_available, _read_full, _read_recent_3tables, load_financials_extended)

FIN = ROOT / 'data/external/tushare/a_share_financial_pit_v1'

_CACHE: dict[str, pd.DataFrame] = {}


def load_stmt(table: str, cols: list[str]) -> pd.DataFrame:
    """income / balancesheet / cashflow：full 批次 + recent_3tables，PIT 去重。"""
    key = f'stmt::{table}'
    if key in _CACHE:
        return _CACHE[key]
    use = ['ts_code', 'end_date', 'ann_date', 'available_date'] + cols
    full = _read_full(table, use)
    recent = _read_recent_3tables(table, use)
    frame = pd.concat([full, recent], ignore_index=True)
    frame = _fill_available(frame)
    frame = frame.dropna(subset=['available_date'])
    frame['sym'] = [f"{c.split('.')[1]}{c.split('.')[0]}".upper() for c in frame['ts_code']]
    frame = frame.drop_duplicates(['sym', 'end_date', 'available_date'], keep='last')
    _CACHE[key] = frame
    return frame


def load_fi(cols: list[str]) -> pd.DataFrame:
    """fina_indicator（顶层合并文件，含 recent）。"""
    key = f'fi::{",".join(cols)}'
    if key in _CACHE:
        return _CACHE[key]
    fin = pd.read_csv(FIN / 'normalized/fina_indicator.csv.gz', compression='gzip',
                      low_memory=False)
    use = ['ts_code', 'end_date', 'ann_date', 'available_date'] + cols
    fin = fin[[c for c in use if c in fin.columns]]
    fin = _fill_available(fin)
    fin = fin.dropna(subset=['available_date'])
    fin['sym'] = [f"{c.split('.')[1]}{c.split('.')[0]}".upper() for c in fin['ts_code']]
    fin = fin.drop_duplicates(['sym', 'end_date', 'available_date'], keep='last')
    _CACHE[key] = fin
    return fin


def _quarterly(frame: pd.DataFrame, cols: list[str], ttm: tuple[str, ...] = (),
               lag_q: tuple[tuple[str, int], ...] = (),
               flow: tuple[str, ...] = ()) -> pd.DataFrame:
    """每个 (sym, end_date) 只保留最新可得版本后，计算 TTM 与滞后列。

    **流量列必须先去累计化**：tushare 利润表/现金流量表是**年内累计（YTD）**值，
    直接 `rolling(4).sum()` 不是 TTM（会把 Q1 计 4 次、Q2 计 3 次…）。
    正确处理：单季 = 本期累计 − 同年上一期累计（Q1 直接取累计），再对单季做 4 期滚动求和。
    """
    f = frame.sort_values(['sym', 'end_date', 'available_date'])
    f = f.drop_duplicates(['sym', 'end_date'], keep='last').copy()
    f = f.sort_values(['sym', 'end_date'])

    if flow:
        g = f.groupby('sym', sort=False)
        prev_val = {c: g[c].shift(1) for c in flow}
        prev_yr = g['end_date'].shift(1).dt.year
        same_yr = prev_yr.values == f['end_date'].dt.year.values
        for c in flow:
            f[f'{c}__q'] = np.where(same_yr, f[c].values - prev_val[c].values, f[c].values)

    g = f.groupby('sym', sort=False)
    for c in ttm:
        src = f'{c}__q' if c in flow else c
        f[f'{c}__ttm'] = g[src].rolling(4, min_periods=4).sum().reset_index(level=0, drop=True)
    for c, k in lag_q:
        f[f'{c}__lag{k}'] = f.groupby('sym', sort=False)[c].shift(k)
    return f


def _asof(w: pd.DataFrame, cal: pd.DatetimeIndex) -> pd.DataFrame:
    """正确的 as-of 构造：索引级 union 后**按列**前向填充，再对齐到 cal。

    注意：`reindex(cal, method='ffill')` 只做索引级填充，行内 NaN 不会被填，
    会静默丢数据（本项目已踩过同类坑）。
    """
    idx = w.index.union(cal)
    return w.reindex(idx).sort_index().ffill().reindex(cal)


def pit_panels(frame: pd.DataFrame, cols: list[str], cal: pd.DatetimeIndex,
               symbols: list[str], ttm: tuple[str, ...] = (),
               lag_q: tuple[tuple[str, int], ...] = (),
               flow: tuple[str, ...] = (),
               prefix: str = '') -> dict[str, pd.DataFrame]:
    """返回 {列名: 日频 as-of 宽面板}。列名含 __ttm / __lagK 后缀。"""
    f = _quarterly(frame, cols, ttm=ttm, lag_q=lag_q, flow=flow)
    out_cols = (list(cols) + [f'{c}__q' for c in flow]
                + [f'{c}__ttm' for c in ttm] + [f'{c}__lag{k}' for c, k in lag_q])
    out: dict[str, pd.DataFrame] = {}
    for c in out_cols:
        if c not in f.columns:
            continue
        w = f.pivot_table(index='available_date', columns='sym', values=c, aggfunc='last')
        w = w.reindex(columns=symbols).sort_index()
        out[prefix + c] = _asof(w, cal).astype('float32')
    return out


def daily(frame: pd.DataFrame, value_col: str, cal: pd.DatetimeIndex,
          symbols: list[str]) -> pd.DataFrame:
    """季度 frame 的某一列 → 日频 as-of 宽面板（供模块内自定义派生列使用）。"""
    w = frame.pivot_table(index='available_date', columns='sym', values=value_col,
                          aggfunc='last')
    w = w.reindex(columns=symbols).sort_index()
    return _asof(w, cal).astype('float32')


def fin_extended() -> pd.DataFrame:
    return load_financials_extended()
