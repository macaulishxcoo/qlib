#!/usr/bin/env python3
"""因子计算上下文：把 common 的面板组装成因子函数需要的宽表对象。"""
from __future__ import annotations

import numpy as np
import pandas as pd

from . import common as C


class Ctx:
    """所有宽表均为 index=date, columns=SYMBOL（大写，如 SH600000）。"""

    def __init__(self, u: dict, db: dict, price: dict):
        self.cal: pd.DatetimeIndex = u['cal']
        self.symbols: list[str] = u['symbols']
        self.pool: pd.DataFrame = u['pool_ic']
        self.pool_tradable: pd.DataFrame = u['pool_tradable']
        self.sme: np.ndarray = u['sme']

        self.O = price['open']
        self.H = price['high']
        self.L = price['low']
        self.C = price['close']
        self.V = price['volume']
        self.FAC = price['factor']
        self.VWAP = price['vwap']

        self.RET = self.C.pct_change(fill_method=None)
        self.C_UNADJ = self.C / self.FAC
        self.O_UNADJ = self.O / self.FAC
        # 成交额（元）：未复权价 × 股数（volume 单位为手 → ×100）
        self.AMT = self.C_UNADJ * self.V * 100

        self.db = db
        self.total_mv = db['total_mv']
        self.circ_mv = db['circ_mv']
        self.total_share = db['total_share']       # 万股
        self.float_share = db['float_share']       # 万股
        self.free_share = db['free_share']         # 万股
        self.turnover_rate = db['turnover_rate']   # %
        self.dv_ttm = db['dv_ttm']

        # 换手率（股数口径，与九族脚本一致）
        self.turn = (self.V * 100) / (self.total_share * 1e4).where(
            (self.total_share * 1e4) > 0)
        self.fs_ratio = (self.V * 100) / (self.float_share * 1e4).where(
            (self.float_share * 1e4) > 0)

        idx = self._index_panels()
        self.idx300_ret = idx['ret300']
        self.idx300_close = idx['close300']
        self.idx300_vol_mom = idx['volmom300']

    def _index_panels(self) -> dict:
        cal_full = pd.DatetimeIndex(pd.to_datetime(
            pd.read_csv(C.QLIB_DIR / 'calendars' / 'day.txt', header=None)[0]))
        out = {}
        for key, sym in [('close300', 'sh000300')]:
            p = C.QLIB_DIR / 'features' / sym / 'close.day.bin'
            s = pd.Series(np.frombuffer(p.read_bytes(), dtype='<f')[1:]) if p.exists() else None
            if s is not None:
                arr = np.frombuffer(p.read_bytes(), dtype='<f')
                s = pd.Series(arr[1:], index=cal_full[int(arr[0]):int(arr[0]) + len(arr) - 1])
                out[key] = s.reindex(self.cal)
        out['ret300'] = out['close300'].pct_change(fill_method=None) if 'close300' in out else None
        p = C.QLIB_DIR / 'features' / 'sh000300' / 'volume.day.bin'
        if p.exists():
            arr = np.frombuffer(p.read_bytes(), dtype='<f')
            v = pd.Series(arr[1:], index=cal_full[int(arr[0]):int(arr[0]) + len(arr) - 1]).reindex(self.cal)
            out['volmom300'] = (v.rolling(5).sum() - v.rolling(5).sum().shift(1)) / v.rolling(5).sum().shift(1)
        else:
            out['volmom300'] = None
        return out


def load_ctx(verbose: bool = True) -> Ctx:
    cal = C.calendar()
    symbols = C.symbols_mainboard(cal)
    price = C.build_price_panels(symbols, C.PRICE_FIELDS, cal, verbose=verbose)
    db = C.build_db_panels(symbols, C.DB_COLS, cal, verbose=verbose)
    u = C.build_universe(cal, symbols, price, verbose=verbose)
    return Ctx(u, db, price)


def save_factor(df: pd.DataFrame, fam: str, name: str, ctx: Ctx) -> None:
    d = C.OUT / 'factors' / fam
    d.mkdir(parents=True, exist_ok=True)
    out = df.reindex(index=ctx.cal, columns=ctx.symbols).astype('float32')
    out.index.name = 'date'
    out.to_parquet(d / f'{name}.parquet', compression='zstd')
