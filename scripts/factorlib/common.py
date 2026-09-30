#!/usr/bin/env python3
"""沪深主板 tushare 因子库评估 —— 公共数据层（协议 v1）。

冻结口径唯一来源：
  research/protocols/a_share_mainboard_tushare_factor_library_evaluation_protocol_v1.md

本模块只负责：日历、标的池（PIT）、价格面板、daily_basic 面板、ST PIT、size 分桶、缓存。
不做任何因子计算，也不做任何判定。
"""
from __future__ import annotations

import os
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path('/home/xiaocong/worksapces/qlib')
QLIB_DIR = Path(os.path.expanduser('~')) / '.qlib/qlib_data/cn_data_2026'
TUSHARE = ROOT / 'data/external/tushare'
OUT = ROOT / 'output/analysis_mainboard_factor_eval_v1'
CACHE = OUT / 'cache'

# ---- 协议冻结常量 ------------------------------------------------------------
PANEL_START = '2015-01-01'
PANEL_END = '2026-09-10'
SEGMENTS = {
    'dev':   ('2017-01-01', '2021-12-31'),
    'valid': ('2022-01-01', '2023-12-31'),
    'oos':   ('2024-01-01', '2026-09-10'),
}
WARMUP = ('2015-01-01', '2016-12-31')

MAIN_PREFIX = ('SH60', 'SZ000', 'SZ001', 'SZ002', 'SZ003')
SME_PREFIX = ('SZ002', 'SZ003')          # 原中小板，独立分层
EXCLUDE_PREFIX = ('SH688', 'SH689', 'SZ300', 'SZ301', 'BJ', 'SH689')

PRICE_FIELDS = ['open', 'high', 'low', 'close', 'volume', 'factor', 'vwap', 'amount']
DB_COLS = ['close', 'turnover_rate', 'turnover_rate_f', 'volume_ratio',
           'pe_ttm', 'pb', 'ps_ttm', 'dv_ttm',
           'total_share', 'float_share', 'free_share', 'total_mv', 'circ_mv']

MIN_LISTED_DAYS = 365                    # 上市满 12 个月
SIZE_N = 5                               # size 五分位


# ---- 基础工具 ----------------------------------------------------------------
def qlib_to_ts(sym: str) -> str:
    """'SH600000' -> '600000.SH'"""
    return f"{sym[2:]}.{sym[:2]}"


def ts_to_qlib(ts_code: str) -> str:
    """'600000.SH' -> 'SH600000'"""
    c, e = ts_code.split('.')
    return f"{e}{c}".upper()


def calendar(start: str = PANEL_START, end: str = PANEL_END) -> pd.DatetimeIndex:
    full = pd.DatetimeIndex(pd.read_csv(QLIB_DIR / 'calendars' / 'day.txt',
                                        header=None)[0])
    full = pd.DatetimeIndex(pd.to_datetime(full))
    return full[(full >= pd.Timestamp(start)) & (full <= pd.Timestamp(end))]


def instruments() -> pd.DataFrame:
    inst = pd.read_csv(QLIB_DIR / 'instruments' / 'all.txt', sep='\t', header=None,
                       names=['code', 'start', 'end'], parse_dates=['start', 'end'])
    inst['code'] = inst['code'].str.upper()
    return inst.drop_duplicates('code').reset_index(drop=True)


def symbols_mainboard(cal: pd.DatetimeIndex | None = None) -> list[str]:
    inst = instruments()
    m = inst['code'].str.startswith(MAIN_PREFIX)
    inst = inst[m]
    if cal is not None:
        inst = inst[(inst['start'] <= cal[-1]) & (inst['end'] >= cal[0])]
    return sorted(inst['code'].unique())


def read_bin(sym: str, field: str, cal_full: pd.DatetimeIndex) -> pd.Series | None:
    """读单个 qlib bin 文件，返回按 cal_full 索引的 float32 Series。"""
    p = QLIB_DIR / 'features' / sym.lower() / f'{field}.day.bin'
    if not p.exists():
        return None
    arr = np.frombuffer(p.read_bytes(), dtype='<f')
    if arr.size < 2:
        return None
    s0 = int(arr[0])
    vals = arr[1:]
    idx = cal_full[s0:s0 + len(vals)]
    return pd.Series(vals.astype('float32'), index=idx, name=sym)


def _cache_path(name: str) -> Path:
    CACHE.mkdir(parents=True, exist_ok=True)
    return CACHE / f'{name}.parquet'


# ---- 价格面板 ----------------------------------------------------------------
def build_price_panels(symbols: list[str] | None = None,
                       fields: list[str] = PRICE_FIELDS,
                       cal: pd.DatetimeIndex | None = None,
                       force: bool = False,
                       verbose: bool = True) -> dict[str, pd.DataFrame]:
    """构建 {field: DataFrame(index=date, columns=SYMBOL)}，落 parquet 缓存。"""
    cal = calendar() if cal is None else cal
    symbols = symbols_mainboard(cal) if symbols is None else symbols
    cal_full = pd.DatetimeIndex(pd.read_csv(QLIB_DIR / 'calendars' / 'day.txt',
                                            header=None)[0])
    cal_full = pd.DatetimeIndex(pd.to_datetime(cal_full))

    out: dict[str, pd.DataFrame] = {}
    for f in fields:
        cp = _cache_path(f'price_{f}')
        if cp.exists() and not force:
            df = pd.read_parquet(cp)
            out[f] = df.reindex(cal)
            continue
        if verbose:
            print(f'[price] building {f} for {len(symbols)} symbols ...', flush=True)
        cols = {}
        for s in symbols:
            ser = read_bin(s, f, cal_full)
            if ser is None:
                continue
            cols[s] = ser.reindex(cal)
        df = pd.DataFrame(cols, dtype='float32')
        df.index.name = 'date'
        df.to_parquet(cp)
        out[f] = df
        if verbose:
            print(f'[price] {f}: shape={df.shape} nonnull={df.notna().mean().mean():.2%}',
                  flush=True)
    return out


# ---- daily_basic 面板 --------------------------------------------------------
def build_db_panels(symbols: list[str] | None = None,
                    cols: list[str] = DB_COLS,
                    cal: pd.DatetimeIndex | None = None,
                    force: bool = False,
                    verbose: bool = True) -> dict[str, pd.DataFrame]:
    """daily_basic 宽面板（PIT：直接使用当日值，信号在收盘后生成）。"""
    cal = calendar() if cal is None else cal
    symbols = symbols_mainboard(cal) if symbols is None else symbols
    symset = set(symbols)

    out: dict[str, pd.DataFrame] = {}
    need = [c for c in cols if not (_cache_path(f'db_{c}').exists() and not force)]
    if not need:
        for c in cols:
            out[c] = pd.read_parquet(_cache_path(f'db_{c}')).reindex(cal)
        return out

    if verbose:
        print(f'[daily_basic] reading {len(need)} cols ...', flush=True)
    path = TUSHARE / 'a_share_daily_basic_pit_v1/normalized/daily_basic.csv.gz'
    keep = ['ts_code', 'trade_date'] + need
    chunks = []
    for ch in pd.read_csv(path, compression='gzip', usecols=keep,
                          dtype={'trade_date': str}, chunksize=1_000_000):
        ch['sym'] = [ts_to_qlib(t) for t in ch['ts_code']]
        ch = ch[ch['sym'].isin(symset)]
        if len(ch):
            chunks.append(ch)
    raw = pd.concat(chunks, ignore_index=True)
    raw['date'] = pd.to_datetime(raw['trade_date'], format='%Y%m%d')
    raw = raw[(raw['date'] >= cal[0]) & (raw['date'] <= cal[-1])]

    for c in need:
        piv = raw.pivot_table(index='date', columns='sym', values=c, aggfunc='last')
        piv = piv.reindex(index=cal, columns=symbols).astype('float32')
        piv.index.name = 'date'
        piv.to_parquet(_cache_path(f'db_{c}'))
        out[c] = piv
        if verbose:
            print(f'[daily_basic] {c}: nonnull={piv.notna().mean().mean():.2%}', flush=True)
    for c in cols:
        if c not in out:
            out[c] = pd.read_parquet(_cache_path(f'db_{c}')).reindex(cal)
    return out


# ---- ST / 退市整理期 PIT -----------------------------------------------------
def build_st_flags(symbols: list[str], cal: pd.DatetimeIndex,
                   force: bool = False, verbose: bool = True) -> pd.DataFrame:
    """bool DataFrame [date x symbol]：True = 当日处于 ST/*ST 或退市整理期。"""
    cp = _cache_path('st_flags')
    if cp.exists() and not force:
        return pd.read_parquet(cp).reindex(index=cal, columns=symbols).fillna(False)
    path = TUSHARE / 'a_share_st_status_pit_v1/normalized/st_status_intervals.csv.gz'
    st = pd.read_csv(path, compression='gzip', parse_dates=['start_date', 'end_date'])
    st = st[st['is_st'] | st['is_delist_phase']].copy()
    st['sym'] = [ts_to_qlib(t) for t in st['ts_code']]
    sym_pos = {s: i for i, s in enumerate(symbols)}
    flags = np.zeros((len(cal), len(symbols)), dtype=bool)
    dpos = cal.values
    for sym, s0, s1 in zip(st['sym'].values, st['start_date'].values, st['end_date'].values):
        j = sym_pos.get(sym)
        if j is None:
            continue
        i0 = np.searchsorted(dpos, np.datetime64(s0, 'ns'), side='left')
        i1 = np.searchsorted(dpos, np.datetime64(s1, 'ns'), side='right')
        if i1 > i0:
            flags[i0:i1, j] = True
    df = pd.DataFrame(flags, index=cal, columns=symbols)
    df.index.name = 'date'
    df.to_parquet(cp)
    if verbose:
        print(f'[st] flagged cells={flags.sum():,} '
              f'({flags.sum() / flags.size:.3%})', flush=True)
    return df


# ---- 标的池 ------------------------------------------------------------------
def build_universe(cal: pd.DatetimeIndex | None = None,
                   symbols: list[str] | None = None,
                   price: dict[str, pd.DataFrame] | None = None,
                   force: bool = False, verbose: bool = True) -> dict:
    """返回 dict: pool_ic / pool_tradable / listed / st / sme / symbols / cal。"""
    cal = calendar() if cal is None else cal
    symbols = symbols_mainboard(cal) if symbols is None else symbols
    if price is None:
        price = build_price_panels(symbols, ['open', 'volume'], cal, verbose=verbose)

    inst = instruments().set_index('code')
    listed = pd.DataFrame(False, index=cal, columns=symbols)
    inst = inst.reindex(symbols)
    dpos = cal.values
    for sym, s0, s1 in zip(inst.index.values, inst['start'].values, inst['end'].values):
        i0 = np.searchsorted(dpos, np.datetime64(s0, 'ns') + np.timedelta64(MIN_LISTED_DAYS, 'D'),
                             side='left')
        i1 = np.searchsorted(dpos, np.datetime64(s1, 'ns'), side='right')
        if i1 > i0:
            listed.iloc[i0:i1, listed.columns.get_loc(sym)] = True

    st = build_st_flags(symbols, cal, force=force, verbose=verbose)
    openp, vol = price['open'], price['volume']
    tradable = openp.notna() & (vol.fillna(0) > 0)
    pool_ic = listed & (~st)
    pool_tradable = pool_ic & tradable
    sme = np.array([s.startswith(SME_PREFIX) for s in symbols])

    if verbose:
        n = pool_ic.sum(axis=1)
        nt = pool_tradable.sum(axis=1)
        print(f'[universe] symbols={len(symbols)}  '
              f'pool_ic/day: min={n.min()} p50={int(n.median())} max={n.max()}', flush=True)
        print(f'[universe] pool_tradable/day: min={nt.min()} p50={int(nt.median())} max={nt.max()}',
              flush=True)
        print(f'[universe] 002/003 占比: {sme.mean():.1%}', flush=True)
    return dict(cal=cal, symbols=symbols, listed=listed, st=st, sme=sme,
                pool_ic=pool_ic, pool_tradable=pool_tradable, price=price)


def size_bucket(total_mv: pd.DataFrame, pool: pd.DataFrame,
                n: int = SIZE_N) -> pd.DataFrame:
    """按当日 total_mv 在池内做 n 分位分桶（1=最小 ... n=最大）。非池内为 NaN。"""
    masked = total_mv.where(pool)
    ranks = masked.rank(axis=1, pct=True)
    b = np.ceil(ranks * n).clip(1, n)
    return b.where(pool)


def in_segment(cal: pd.DatetimeIndex, seg: str) -> pd.DatetimeIndex:
    s, e = SEGMENTS[seg]
    return cal[(cal >= pd.Timestamp(s)) & (cal <= pd.Timestamp(e))]
