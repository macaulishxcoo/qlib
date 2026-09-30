#!/usr/bin/env python3
"""因子算子库：全部作用于「宽表」DataFrame(index=date, columns=symbol)。"""
from __future__ import annotations

import numpy as np
import pandas as pd

EPS = 1e-12


# ---- 截面算子 ----------------------------------------------------------------
def cs_rank(df: pd.DataFrame) -> pd.DataFrame:
    return df.rank(axis=1, pct=True)


def cs_zscore(df: pd.DataFrame) -> pd.DataFrame:
    return df.sub(df.mean(axis=1), axis=0).div(df.std(axis=1).replace(0, np.nan), axis=0)


def mad_clip(df: pd.DataFrame, k: float = 3.0) -> pd.DataFrame:
    med = df.median(axis=1)
    mad = (df.sub(med, axis=0)).abs().median(axis=1)
    lo = med - k * 1.4826 * mad
    hi = med + k * 1.4826 * mad
    return df.clip(lo, hi, axis=0)


def safe_div(a, b):
    if isinstance(b, pd.DataFrame):
        return a / b.replace(0, np.nan)
    return a / np.where(np.abs(b) < EPS, np.nan, b)


# ---- 时序算子（向量化，分块滑窗；语义与九族脚本一致） ------------------------
def _sw(a: np.ndarray, w: int):
    from numpy.lib.stride_tricks import sliding_window_view
    return sliding_window_view(a, w, axis=0)


def ts_rank(df: pd.DataFrame, w: int, chunk: int = 400) -> pd.DataFrame:
    """窗口内 <= 当前值的比例（等价于原 rolling.apply 的 pct rank）。"""
    a = df.values.astype('float64')
    T, S = a.shape
    out = np.full((T, S), np.nan)
    if T < w:
        return pd.DataFrame(out, index=df.index, columns=df.columns)
    for s0 in range(0, S, chunk):
        blk = a[:, s0:s0 + chunk]
        sw = _sw(blk, w)
        last = sw[:, :, -1:]
        with np.errstate(invalid='ignore'):
            cnt = (sw <= last).sum(axis=2)
        valid = np.isfinite(sw).all(axis=2)
        out[w - 1:, s0:s0 + chunk] = np.where(valid, cnt / w, np.nan)
    return pd.DataFrame(out, index=df.index, columns=df.columns)


def ts_argmax(df: pd.DataFrame, w: int, chunk: int = 400) -> pd.DataFrame:
    """窗口内最大值的位置（0-based）；全 NaN 窗口为 NaN。"""
    a = df.values.astype('float64')
    T, S = a.shape
    out = np.full((T, S), np.nan)
    if T < w:
        return pd.DataFrame(out, index=df.index, columns=df.columns)
    for s0 in range(0, S, chunk):
        sw = _sw(a[:, s0:s0 + chunk], w)
        finite = np.isfinite(sw).any(axis=2)
        filled = np.where(np.isfinite(sw), sw, -np.inf)
        idx = filled.argmax(axis=2).astype('float64')
        out[w - 1:, s0:s0 + chunk] = np.where(finite, idx, np.nan)
    return pd.DataFrame(out, index=df.index, columns=df.columns)


def decay_linear(df: pd.DataFrame, w: int, chunk: int = 400) -> pd.DataFrame:
    """线性衰减加权和（权重 1..w 归一化）；要求窗口内全 finite。"""
    a = df.values.astype('float64')
    T, S = a.shape
    out = np.full((T, S), np.nan)
    if T < w:
        return pd.DataFrame(out, index=df.index, columns=df.columns)
    weights = np.arange(1, w + 1, dtype=float)
    weights /= weights.sum()
    for s0 in range(0, S, chunk):
        sw = _sw(a[:, s0:s0 + chunk], w)
        valid = np.isfinite(sw).all(axis=2)
        val = sw @ weights
        out[w - 1:, s0:s0 + chunk] = np.where(valid, val, np.nan)
    return pd.DataFrame(out, index=df.index, columns=df.columns)


def signed_power(df: pd.DataFrame, p: float) -> pd.DataFrame:
    return np.sign(df) * (df.abs() ** p)


def delay(df: pd.DataFrame, d: int) -> pd.DataFrame:
    return df.shift(d)


def delta(df: pd.DataFrame, d: int) -> pd.DataFrame:
    return df - df.shift(d)


def rolling_corr(a: pd.DataFrame, b: pd.DataFrame, w: int):
    ma, mb = a.rolling(w).mean(), b.rolling(w).mean()
    cov = (a * b).rolling(w).mean() - ma * mb
    va = (a * a).rolling(w).mean() - ma ** 2
    vb = (b * b).rolling(w).mean() - mb ** 2
    return cov / np.sqrt(va * vb).replace(0, np.nan)


def rolling_cov(a: pd.DataFrame, b: pd.DataFrame, w: int):
    ma, mb = a.rolling(w).mean(), b.rolling(w).mean()
    return (a * b).rolling(w).mean() - ma * mb


def rolling_beta(y: pd.DataFrame, x: pd.DataFrame | pd.Series, w: int):
    """滚动 OLS beta（y ~ x），返回 (beta, alpha, resid)。

    ``x`` 为 ``Series``（如指数收益）时表示"同一市场因子作用于所有标的"，
    此时所有与 ``x`` 的乘法都必须用 ``.mul(x, axis=0)`` 按**行（日期）**对齐。
    """
    if isinstance(x, pd.Series):
        mx = x.rolling(w).mean()
        my = y.rolling(w).mean()
        cov = y.mul(x, axis=0).rolling(w).mean().sub(my.mul(mx, axis=0), axis=0)
        vx = (x * x).rolling(w).mean() - mx ** 2
        beta = cov.div(vx.replace(0, np.nan), axis=0)
        alpha = my.sub(beta.mul(mx, axis=0), axis=0)
        # ⚠️ 这里必须用 .mul(x, axis=0)。写成 `beta * x` 时 pandas 会把 Series 的
        #    **索引**（日期）去对齐 DataFrame 的**列**（股票代码），结果全为 NaN。
        resid = y - alpha.add(beta.mul(x, axis=0), axis=0)
    else:
        mx = x.rolling(w).mean()
        my = y.rolling(w).mean()
        cov = y.mul(x).rolling(w).mean().sub(my * mx)
        vx = (x * x).rolling(w).mean() - mx ** 2
        beta = cov / vx.replace(0, np.nan)
        alpha = my - beta * mx
        resid = y - (alpha + beta * x)
    return beta, alpha, resid


def ema(df: pd.DataFrame, w: int) -> pd.DataFrame:
    return df.ewm(span=w, adjust=False).mean()
