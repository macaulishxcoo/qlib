#!/usr/bin/env python
"""risk 族（12 因子）本地复现。

文档给的只有一句话（如「20日年化收益方差」），**年化系数、收益率口径、
偏度/峰度的统计定义全部没写**。以下口径由四组变体对照实测标定（2026-09-17）：

Variance{w} = ``pct_change().rolling(w).var(ddof=1) * 250``
    变体对照（maxerr）：
        年化 250 + ddof=1  → 4.97e-07  ✅
        年化 252 + ddof=1  → 2.25e-03  ❌
        年化 244 + ddof=1  → 6.75e-03  ❌
        年化 250 + ddof=0  → 1.41e-02  ❌
        不年化             → 2.80e-01  ❌
        对数收益 × 250     → 1.17e-02  ❌
    ⇒ **简单收益率 + 250 + 样本方差**。

Skewness{w} = ``pct_change().rolling(w).skew()``
    pandas 的 ``.skew()`` 即**校正 Fisher-Pearson**（等价 scipy ``skew(bias=False)``）
    → 5.00e-07 ✅；而**未校正**的 g1（scipy ``bias=True``）→ 2.52e-01 ❌。

Kurtosis{w} = ``pct_change().rolling(w).kurt()``
    pandas ``.kurt()`` 返回**超额峰度**（Fisher，已校正）→ 5.00e-07 ✅；
    **+3 的 Pearson 峰度** → 3.00e+00 ❌。

sharpe_ratio{w} = ``(Rp - 0.04) / (std(ddof=1) * sqrt(250))``
    其中 ``Rp`` 为**几何年化收益率**：``expm1(sum(log1p(r), w) * 250 / w)``
    （等价 ``(∏(1+r))^(250/w) - 1``，实测 maxerr 5.00e-07）
    变体对照（maxerr）：
        几何年化 / std1·√250  → 5.00e-07  ✅
        算术均值×250 / std1·√250 → 7.69e+00  ❌
        累计收益×250/w / std1·√250 → 6.53e+00  ❌
        几何年化 / std0·√250  → 2.94e-01  ❌
        几何年化 / std1·√252  → 4.50e-02  ❌
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from ..data import Panel

FAMILY = "risk"

WINDOWS = (20, 60, 120)
ANNUAL_DAYS = 250          # 实测标定（≠ 252 / 244）
RF = 0.04                  # 官方文档明写


def _geom_annualized(ret: pd.DataFrame, w: int) -> pd.DataFrame:
    """几何年化收益率 = expm1(Σln(1+r) × 250/w)（等价 (∏(1+r))^(250/w) − 1）。"""
    return np.expm1(np.log1p(ret).rolling(w).sum() * (ANNUAL_DAYS / w))


def build(panel: Panel) -> dict[str, pd.DataFrame]:
    ret = panel.C.pct_change()
    out: dict[str, pd.DataFrame] = {}

    for w in WINDOWS:
        out[f"Variance{w}"] = ret.rolling(w).var(ddof=1) * ANNUAL_DAYS
        out[f"Skewness{w}"] = ret.rolling(w).skew()
        out[f"Kurtosis{w}"] = ret.rolling(w).kurt()
        sigma = ret.rolling(w).std(ddof=1) * np.sqrt(ANNUAL_DAYS)
        out[f"sharpe_ratio_{w}"] = (_geom_annualized(ret, w) - RF) / sigma.replace(0, np.nan)

    return out


NOTES: dict[str, str] = {}
