#!/usr/bin/env python3
"""Size 族（3 因子）。官方: Size = -log(TotalShares×Close/1e6)；nl_size = Size^3 ~ Size 残差。"""
from __future__ import annotations

import numpy as np
import pandas as pd

from .context import Ctx

FAMILY = 'Size'


def _log_neg_mcap(shares_wan: pd.DataFrame, px: pd.DataFrame) -> pd.DataFrame:
    mcap = shares_wan * 1e4 * px / 1e6
    return -np.log(mcap.where(mcap > 0))


def build(ctx: Ctx) -> dict[str, pd.DataFrame]:
    F: dict[str, pd.DataFrame] = {}
    F['size'] = _log_neg_mcap(ctx.total_share, ctx.C_UNADJ)
    F['float_size'] = _log_neg_mcap(ctx.float_share, ctx.C_UNADJ)

    # nl_size: 逐日截面 OLS  y = size^3 ~ [1, size]，取残差
    s = F['size']
    y = s ** 3
    n = s.notna() & y.notna()
    x = s.where(n)
    yy = y.where(n)
    xm = x.mean(axis=1)
    ym = yy.mean(axis=1)
    xc = x.sub(xm, axis=0)
    yc = yy.sub(ym, axis=0)
    var = (xc ** 2).sum(axis=1)
    cov = (xc * yc).sum(axis=1)
    b = cov / var.replace(0, np.nan)
    a = ym - b * xm
    F['nl_size'] = yy.sub(a, axis=0).sub(x.mul(b, axis=0))
    return F
