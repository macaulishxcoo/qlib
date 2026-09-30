#!/usr/bin/env python3
"""Risk 族（25 因子）。移植自 scripts/analyze_risk25_dual_arm_v1.py。

代理声明（协议 §4）：beta_1320d_000001 / sigma_1320d_000001 因原始上证 bin 缺失，
沿用沪深300 口径，标记 is_proxy。
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from .context import Ctx

FAMILY = 'Risk'

PROXY = {'beta_1320d_000001', 'sigma_1320d_000001'}


def build(ctx: Ctx) -> dict[str, pd.DataFrame]:
    F: dict[str, pd.DataFrame] = {}
    RET = ctx.RET
    V = ctx.V
    C = ctx.C

    # R1 波动率
    for w in [21, 42, 63, 126, 252]:
        F[f'return_std_{w}d'] = RET.rolling(w).std()

    # R2 净值高低比
    cum = np.log1p(RET).cumsum()
    for w in [21, 42, 63, 126, 252]:
        F[f'high_low_{w}d'] = np.exp(cum.rolling(w).max() - cum.rolling(w).min())

    # R3 Sharpe
    F['sharpe_60d'] = RET.rolling(60).mean() / RET.rolling(60).std()
    F['sharpe_750d'] = RET.rolling(750).mean() / RET.rolling(750).std()
    F['adjusted_sharpe_750d'] = RET.rolling(750).mean() / RET.rolling(750).std() ** 4

    # R4 beta（相对沪深300）
    r300 = ctx.idx300_ret
    if r300 is not None:
        for w in [60, 125, 250, 500, 1000]:
            mxi = r300.rolling(w).mean()
            varx = (r300 ** 2).rolling(w).mean() - mxi ** 2
            my = RET.rolling(w).mean()
            mxy = RET.mul(r300, axis=0).rolling(w).mean()
            F[f'beta_{w}d_000300'] = (mxy - my.mul(mxi, axis=0)).div(varx.replace(0, np.nan), axis=0)
        w = 1320
        mxi = r300.rolling(w).mean()
        varx = (r300 ** 2).rolling(w).mean() - mxi ** 2
        my = RET.rolling(w).mean()
        mxy = RET.mul(r300, axis=0).rolling(w).mean()
        beta = (mxy - my.mul(mxi, axis=0)).div(varx.replace(0, np.nan), axis=0)
        resid = RET - beta.mul(r300, axis=0)
        F['sigma_1320d_000300'] = resid.rolling(w).std()
        F['beta_consistency_1320d_000300'] = (beta.mul(r300, axis=0).sub(
            beta.mul(mxi, axis=0), axis=0)).rolling(w).std()
        # 代理
        F['beta_1320d_000001'] = beta
        F['sigma_1320d_000001'] = F['sigma_1320d_000300']

    # R6 volume beta
    if ctx.idx300_vol_mom is not None:
        vm = (V.rolling(5).sum() - V.rolling(5).sum().shift(1)) / V.rolling(5).sum().shift(1)
        mx = ctx.idx300_vol_mom.rolling(120).mean()
        my = vm.rolling(120).mean()
        mxy = vm.mul(ctx.idx300_vol_mom, axis=0).rolling(120).mean()
        mxx = (ctx.idx300_vol_mom ** 2).rolling(120).mean()
        F['volume_beta_120d_000300'] = (mxy - my.mul(mx, axis=0)).div(
            (mxx - mx ** 2).replace(0, np.nan), axis=0)

    # R7 异常波动
    z = (C - C.rolling(21).mean()) / C.rolling(21).std().replace(0, np.nan)
    F['days_beyond_upper_lower_21d'] = (
        (z > 1).astype(int).rolling(21).sum() - (z < -1).astype(int).rolling(21).sum())

    # R8 log 未复权价
    F['log_price'] = np.log(ctx.C_UNADJ.where(ctx.C_UNADJ > 0))

    return {k: v for k, v in F.items() if v is not None}
