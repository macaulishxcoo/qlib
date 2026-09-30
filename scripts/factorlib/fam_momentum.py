#!/usr/bin/env python3
"""Momentum 族（20 因子）。移植自 scripts/analyze_momentum20_dual_arm_v1.py。

代理声明：alpha_528d/792d/1320d_000001 因上证 bin 缺失，沿用沪深300 口径（与原实现一致）。
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from .context import Ctx

FAMILY = 'Momentum'
PROXY = {'alpha_528d_000001', 'alpha_792d_000001', 'alpha_1320d_000001'}


def _consec(flag: pd.DataFrame) -> pd.DataFrame:
    """逐列连续 True 计数（行循环 + 列向量化）。"""
    s = flag.fillna(0).astype(np.int32).values
    out = np.zeros_like(s, dtype=np.int32)
    run = np.zeros(s.shape[1], dtype=np.int32)
    for t in range(s.shape[0]):
        run = np.where(s[t] > 0, run + 1, 0)
        out[t] = run
    return pd.DataFrame(out, index=flag.index, columns=flag.columns)


def _capm_alpha(ctx: Ctx, idx_ret: pd.Series, w: int) -> pd.DataFrame:
    RET = ctx.RET
    mx = idx_ret.rolling(w).mean()
    my = RET.rolling(w).mean()
    xy = RET.mul(idx_ret, axis=0).rolling(w).mean()
    x2 = (idx_ret ** 2).rolling(w).mean()
    var = x2 - mx ** 2
    beta = (xy - my.mul(mx, axis=0)).div(var.where(var.abs() > 1e-12), axis=0)
    return my - beta.mul(mx, axis=0)


def build(ctx: Ctx) -> dict[str, pd.DataFrame]:
    F: dict[str, pd.DataFrame] = {}
    C, H, L, O = ctx.C, ctx.H, ctx.L, ctx.O
    RET = ctx.RET

    for w in [5, 21, 42, 63, 126, 252]:
        F[f'return_{w}d'] = np.expm1(np.log1p(RET).rolling(w).sum())

    F['ma_20d'] = C.rolling(20).mean()
    ema = lambda d, w: d.ewm(span=w, adjust=False).mean()  # noqa: E731
    dif = ema(C, 12) - ema(C, 26)
    F['dif'] = dif
    F['dea'] = ema(dif, 9)
    F['MACD'] = 2 * (dif - ema(dif, 9))

    if ctx.idx300_ret is not None:
        for w in [125, 250, 500, 1000]:
            F[f'alpha_{w}d_000300'] = _capm_alpha(ctx, ctx.idx300_ret, w)
        for w in [528, 792, 1320]:
            F[f'alpha_{w}d_000001'] = _capm_alpha(ctx, ctx.idx300_ret, w)  # 代理

    ratio = (C - O) / (H - L).replace(0, np.nan)
    F['price_position_ir_60d'] = ratio.rolling(60).mean() / ratio.rolling(60).std()

    mx, my = H.rolling(18).mean(), L.rolling(18).mean()
    slope = ((H * L).rolling(18).mean() - mx * my) / ((H ** 2).rolling(18).mean() - mx ** 2).replace(0, np.nan)
    F['rsrs'] = (slope - slope.rolling(200).mean()) / slope.rolling(200).std()

    cons_up = _consec(RET > 0)
    cons_dn = _consec(RET < 0)
    F['days_down_up'] = (cons_up - cons_dn - 1).abs()

    return {k: v for k, v in F.items() if v is not None}
