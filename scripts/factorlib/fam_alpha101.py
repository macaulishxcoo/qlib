#!/usr/bin/env python3
"""Alpha101 族（31 因子）。移植自 scripts/analyze_alpha101_dual_arm_v1.py。

算子语义与九族脚本一致（ts_rank / ts_argmax / decay_linear / signed_power）；
rolling corr/cov 用协方差恒等式向量化实现（等价于 rolling().corr()）。
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from .context import Ctx
from .ops import (cs_rank, decay_linear, rolling_corr, rolling_cov, signed_power,
                  ts_argmax, ts_rank)

FAMILY = 'Alpha101'
PROXY: set[str] = set()


def build(ctx: Ctx) -> dict[str, pd.DataFrame]:
    O, H, L, C, V, VW = ctx.O, ctx.H, ctx.L, ctx.C, ctx.V, ctx.VWAP
    RET = ctx.RET
    ADV20 = V.rolling(20).mean()
    F: dict[str, pd.DataFrame] = {}
    idx, cols = C.index, C.columns

    cond_pd = RET < 0
    std20 = RET.rolling(20).std()
    base = pd.DataFrame(np.where(cond_pd, std20, C), index=idx, columns=cols)
    F['alpha101_1'] = cs_rank(ts_argmax(signed_power(base, 2), 5)) - 0.5

    F['alpha101_2'] = -1 * rolling_corr(cs_rank(np.log(V + 1)).diff(2), cs_rank((C - O) / O), 6)
    F['alpha101_3'] = -1 * rolling_corr(cs_rank(O), cs_rank(V), 10)
    F['alpha101_4'] = -1 * ts_rank(cs_rank(L), 9)
    F['alpha101_5'] = cs_rank(O - VW.rolling(10).mean()) * (-1 * cs_rank(C - VW).abs())
    F['alpha101_6'] = -1 * rolling_corr(O, V, 10)

    d7 = C.diff(7)
    cond7 = ADV20 < V
    F['alpha101_7'] = pd.DataFrame(
        np.where(cond7, -1 * ts_rank(d7.abs(), 60) * np.sign(d7), -1.0), index=idx, columns=cols)

    so5 = O.rolling(5).sum() * RET.rolling(5).sum()
    F['alpha101_8'] = -1 * cs_rank(so5 - so5.shift(10))

    d1 = C.diff(1)
    tsmin5, tsmax5 = d1.rolling(5).min(), d1.rolling(5).max()
    a9 = np.where(tsmin5 > 0, d1, np.where(tsmax5 < 0, d1, -1 * d1))
    F['alpha101_9'] = pd.DataFrame(a9, index=idx, columns=cols)
    F['alpha101_10'] = cs_rank(pd.DataFrame(a9, index=idx, columns=cols))

    F['alpha101_11'] = ((cs_rank((VW - C).rolling(3).max()) + cs_rank((VW - C).rolling(3).min()))
                        * cs_rank(V.diff(3)))
    F['alpha101_12'] = np.sign(V.diff(1)) * (-1 * C.diff(1))
    F['alpha101_13'] = -1 * cs_rank(rolling_cov(cs_rank(C), cs_rank(V), 5))
    F['alpha101_14'] = -1 * cs_rank(RET.diff(3)) * rolling_corr(O, V, 10)
    F['alpha101_15'] = -1 * cs_rank(rolling_corr(cs_rank(H), cs_rank(V), 3)).rolling(3).sum()
    F['alpha101_16'] = -1 * cs_rank(rolling_cov(cs_rank(H), cs_rank(V), 5))
    F['alpha101_17'] = ((-1 * cs_rank(ts_rank(C, 10))) * cs_rank(C.diff(1).diff(1))
                        * cs_rank(ts_rank(V / ADV20, 5)))
    F['alpha101_18'] = -1 * cs_rank((C - O).abs().rolling(5).std() + (C - O) + rolling_corr(C, O, 10))
    F['alpha101_19'] = -1 * np.sign((C - C.shift(7)) + C.diff(7)) * (1 + cs_rank(1 + RET.rolling(250).sum()))
    F['alpha101_20'] = (-1 * cs_rank(O - H.shift(1)) * cs_rank(O - C.shift(1))
                        * cs_rank(O - L.shift(1)))
    F['alpha101_22'] = -1 * rolling_corr(H, V, 5).diff(5) * cs_rank(C.rolling(20).std())
    F['alpha101_23'] = pd.DataFrame(np.where(H.rolling(20).mean() < H, -1 * H.diff(2), 0.0),
                                    index=idx, columns=cols)
    F['alpha101_25'] = cs_rank(-1 * RET * ADV20 * VW * (H - C))
    F['alpha101_33'] = cs_rank(-1 * (1 - O / C))
    F['alpha101_34'] = (cs_rank(1 - cs_rank(RET.rolling(2).std() / RET.rolling(5).std()))
                        + 1 - cs_rank(C.diff(1)))
    F['alpha101_41'] = (H * L) ** 0.5 - VW

    tsmin_low5 = L.rolling(5).min()
    F['alpha101_52'] = ((-1 * tsmin_low5 + tsmin_low5.shift(5))
                        * cs_rank((RET.rolling(240).sum() - RET.rolling(20).sum()) / 220)
                        * ts_rank(V, 5))
    F['alpha101_53'] = -1 * (((C - L) - (H - C)) / (C - L)).diff(9)
    F['alpha101_54'] = (-1 * (L - C) * O ** 5) / ((L - H) * C ** 5)
    F['alpha101_57'] = -1 * (C - VW) / decay_linear(cs_rank(ts_argmax(C, 30)), 2)
    F['alpha101_101'] = (C - O) / ((H - L) + 0.001)

    return {k: v.replace([np.inf, -np.inf], np.nan) for k, v in F.items() if v is not None}
