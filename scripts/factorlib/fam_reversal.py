#!/usr/bin/env python3
"""Reversal 族（3 因子）。移植自 scripts/analyze_reversal3_dual_arm_v1.py。"""
from __future__ import annotations

import numpy as np
import pandas as pd

from .context import Ctx

FAMILY = 'Reversal'


def build(ctx: Ctx) -> dict[str, pd.DataFrame]:
    F: dict[str, pd.DataFrame] = {}
    RET = ctx.RET

    # 1) 21 日累计收益反转
    F['small_cap_reversal_21d'] = -np.expm1(np.log1p(RET).rolling(21).sum())

    # 2) RSI(14, Wilder)
    gain = RET.clip(lower=0)
    loss = (-RET).clip(lower=0)
    avg_gain = gain.ewm(alpha=1 / 14, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1 / 14, adjust=False).mean()
    rs = avg_gain / avg_loss.replace(0, np.nan)
    F['rsi'] = 100 - 100 / (1 + rs)

    # 3) 整数关口距离（未复权价）
    frac = ctx.C_UNADJ - np.floor(ctx.C_UNADJ)
    F['price_dist'] = frac.replace(0, np.nan)

    return F
