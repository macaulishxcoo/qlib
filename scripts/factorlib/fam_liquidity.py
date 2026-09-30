#!/usr/bin/env python3
"""Liquidity 族（34 因子）。移植自 scripts/analyze_liquidity35_dual_arm_v1.py。

与原始实现的唯一差异（记录）：换手率分母用 daily_basic 的**当日** total_share /
float_share，而原始脚本用**月末快照前向填充**。当日值更精确且同样 PIT。
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from .context import Ctx

FAMILY = 'Liquidity'


def build(ctx: Ctx) -> dict[str, pd.DataFrame]:
    F: dict[str, pd.DataFrame] = {}
    turn = ctx.turn
    fs_ratio = ctx.fs_ratio
    AMT = ctx.AMT
    RET = ctx.RET
    V = ctx.V

    for w in [5, 10, 20, 21, 42, 63, 126, 252]:
        F[f'avg_turnover_{w}d'] = turn.rolling(w).mean()
    for w in [21, 42, 63, 126, 252]:
        F[f'std_turnover_{w}d'] = turn.rolling(w).std()

    for short in [21, 42, 63, 126]:
        ma_s = turn.rolling(short).mean()
        sd_s = turn.rolling(short).std()
        for long, lname in [(252, '252d'), (504, '504d')]:
            ma_l = turn.rolling(long).mean()
            sd_l = turn.rolling(long).std()
            F[f'bias_turn_{short}d_{lname}'] = ma_s / ma_l - 1
            F[f'bias_std_turn_{short}d_{lname}'] = sd_s / sd_l - 1

    F['amount_ma_20d'] = AMT.rolling(20).mean()
    F['sum_abs_rtn_amount_20d'] = RET.abs().rolling(20).sum() / AMT.rolling(20).sum()
    F['turnover_ma_20d'] = -fs_ratio.rolling(20).mean()
    F['turnover_ma_20d_120d'] = -(fs_ratio.rolling(20).mean() / fs_ratio.rolling(120).mean())

    vm300 = ctx.idx300_vol_mom
    if vm300 is not None:
        stock_mom = (V.rolling(5).sum() - V.rolling(5).sum().shift(1)) / V.rolling(5).sum().shift(1)
        mx = vm300.rolling(300).mean()
        my = stock_mom.rolling(300).mean()
        mxy = stock_mom.mul(vm300, axis=0).rolling(300).mean()
        mxx = (vm300 ** 2).rolling(300).mean()
        beta = (mxy - my.mul(mx, axis=0)).div((mxx - mx ** 2).replace(0, np.nan), axis=0)
        F['volume_alpha_300d_000300'] = my - beta.mul(mx, axis=0)

    return {k: v for k, v in F.items() if v is not None}
