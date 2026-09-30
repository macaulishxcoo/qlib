#!/usr/bin/env python
"""聚宽因子复现用的算子库。

约定：全部作用于**宽表** ``DataFrame(index=date, columns=code)``。
统计量口径来自 :mod:`.conventions`（STD 为样本标准差 ddof=1，MA 含当日）。

复杂时序算子（ts_rank / ts_argmax / decay_linear / rolling_corr / rolling_cov）
直接复用 ``scripts/factorlib/ops.py``，避免重复实现导致语义漂移。
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

from . import conventions as KV

# 复用 factorlib 的向量化算子（语义已与九族脚本一致）
_SCRIPTS = Path(__file__).resolve().parents[2]
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

from factorlib.ops import (  # noqa: E402,F401
    cs_rank, cs_zscore, decay_linear, rolling_corr, rolling_cov, safe_div,
    signed_power, ts_argmax, ts_rank,
)

EPS = 1e-12


# ---- 基础时序算子（口径受 conventions 控制） ---------------------------------
def ma(df: pd.DataFrame, n: int) -> pd.DataFrame:
    """MA(X, N)：简单移动平均，含当日（B2）。"""
    assert KV.MA_INCLUDE_CURRENT
    return df.rolling(n).mean()


def std(df: pd.DataFrame, n: int) -> pd.DataFrame:
    """STD(X, N)：**样本**标准差（B1，实测标定 ddof=1）。"""
    return df.rolling(n).std(ddof=KV.STD_DDOF)


def ema(df: pd.DataFrame, n: int) -> pd.DataFrame:
    """EMA(X, N)：指数移动平均（B3）。"""
    return df.ewm(span=n, adjust=KV.EMA_ADJUST).mean()


def ref(df: pd.DataFrame, n: int) -> pd.DataFrame:
    """REF(X, N)：N 日前值（B5）。"""
    return df.shift(n)


def delta(df: pd.DataFrame, n: int) -> pd.DataFrame:
    return df - df.shift(n)


def avedev(df: pd.DataFrame, n: int) -> pd.DataFrame:
    """AVEDEV(X, N)：窗口内平均绝对偏差 mean(|x - mean(x)|)（B4）。"""
    return df.rolling(n).apply(lambda x: np.abs(x - x.mean()).mean(), raw=True)


def tsum(df: pd.DataFrame, n: int) -> pd.DataFrame:
    return df.rolling(n).sum()


def tmax(df: pd.DataFrame, n: int) -> pd.DataFrame:
    return df.rolling(n).max()


def tmin(df: pd.DataFrame, n: int) -> pd.DataFrame:
    return df.rolling(n).min()


def hhv(df: pd.DataFrame, n: int) -> pd.DataFrame:
    """HHV：N 日内最高（同 tmax，保留 TDX 命名）。"""
    return df.rolling(n).max()


def llv(df: pd.DataFrame, n: int) -> pd.DataFrame:
    return df.rolling(n).min()


def count_up_days(ret: pd.DataFrame, n: int) -> pd.DataFrame:
    """N 日内收益为正的天数（PSY 用）。"""
    return (ret > 0).astype(float).rolling(n).sum()


def true_range(high: pd.DataFrame, low: pd.DataFrame, close: pd.DataFrame) -> pd.DataFrame:
    """真实振幅 TR = max(H-L, |H-REF(C,1)|, |L-REF(C,1)|)。"""
    pc = ref(close, 1)
    return pd.concat([
        (high - low).stack(),
        (high - pc).abs().stack(),
        (low - pc).abs().stack(),
    ], axis=1).max(axis=1).unstack()


def vwap_proxy(money: pd.DataFrame, volume: pd.DataFrame) -> pd.DataFrame:
    """成交均价 = 成交额 / 成交量。"""
    return money / volume.replace(0, np.nan)


def linreg_slope(df: pd.DataFrame, n: int) -> pd.DataFrame:
    """窗口内 X 对 t=1..n 的 OLS 斜率（PLRC* 用）。

    实测标定（2026-09-17）：PLRC 的官方口径是 ``slope(close, n) / mean(close, n)``，
    即文档 ``(close / mean(close)) = beta * t + alpha`` 中把**窗口均值**整体提出，
    而不是逐日用滚动均值归一化后再回归（后者 maxerr 2.6e-02，前者 5.0e-07）。
    """
    def _slope(y: np.ndarray) -> float:
        if not np.isfinite(y).all():
            return np.nan
        t = np.arange(1, len(y) + 1, dtype=float)
        t -= t.mean()
        return float((t * (y - y.mean())).sum() / (t * t).sum())

    return df.rolling(n).apply(_slope, raw=True)
