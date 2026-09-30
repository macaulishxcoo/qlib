#!/usr/bin/env python
"""Alpha101 算子库（横截面 + 时序），**独立于** ``scripts/jqdata/``。

设计
----
全部算子作用于宽表 ``DataFrame(index=date, columns=code)``。

横截面算子（依赖**全市场股票全集**，故必须配 :mod:`ts_market` 的全市场面板）：
    ``Rank`` / ``Scale`` / ``IndNeutralize``

时序算子（个股独立）：
    ``Delta``/``Delay``/``Sum``/``Product``/``Ts_Min``/``Ts_Max``/``StdDev``/
    ``Ts_Rank``/``Ts_ArgMax``/``Decay_Linear``/``Correlation``/``Covariance``
逐元素：
    ``Sign``/``Abs``/``Log``/``SignedPower``/``Min``/``Max``/``If``/``Pow``

口径开关
--------
qdata 官方文档只给公式、不给统计量定义，因此所有**有歧义**的口径都做成
:data:`CFG` 开关，由驱动脚本做变体对照实验（这是本项目的既定方法论）。
默认值取「Alpha101 社区通行实现」：

===============  ==========================================================
``STD_DDOF``     ``StdDev`` 自由度，1=样本（pandas 默认）/ 0=总体
``TSARGMAX_BASE````Ts_ArgMax`` 返回值基，0=i=0..d-1，1=i=1..d
``TSRANK_CMP``   ``Ts_Rank`` 计数口径，``"le"``=含并列(<=) / ``"lt"``=(<)
``DECAY_ORDER``  ``Decay_Linear`` 权重方向，``"recent_heavy"``=最新权重最大
``RANK_PCT``     ``Rank`` 分母，``"n"``=rank/N / ``"n-1"``=(rank-1)/(N-1)
``VWAP_MODE``    成交均价，``"hfq"``=与后复权价可比 / ``"raw"``=原始成交均价
``VOLUME_MODE``  成交量，``"raw"`` / ``"hfq"``（是否乘复权因子）
===============  ==========================================================
"""
from __future__ import annotations

import numpy as np
import pandas as pd

EPS = 1e-12

#: 全局口径开关（驱动脚本可临时覆盖）
CFG: dict[str, object] = {
    "STD_DDOF": 1,
    "TSARGMAX_BASE": 0,
    "TSARGMAX_MODE": "since",
    "TSARGMAX_TIE": "last",
    "TSRANK_CMP": "le",
    "DECAY_ORDER": "recent_heavy",
    "RANK_PCT": "n",
    "RANK_METHOD": "max",
    "VWAP_MODE": "hfq",
    "VOLUME_MODE": "raw",
    "PRICE_MODE": "raw",
    "FLAT_SUSPENDED": 1,
    "ALIVE_FILTER": 1,
}


def set_cfg(**kw) -> dict:
    """覆盖口径开关，返回旧值（便于还原）。未知键允许动态加入。"""
    for k in kw:
        CFG.setdefault(k, None)
    old = {k: CFG[k] for k in kw}
    CFG.update(kw)
    return old


# ======================================================== 横截面算子 ============
def rank(df: pd.DataFrame) -> pd.DataFrame:
    """``Rank(x)`` —— 截面百分位排名 ``count(x_i <= x) / N``。

    ⚠ **实测标定（2026-09-17，alpha101_33 @20260811）**：
    官方 ``Rank`` 的并列（tie）取的是**并列块的最大名次**，即
    ``count(x_i <= x)``，等价 ``pandas.rank(method="max")``，而不是 ``average``。

    证据：``alpha101_33 = Rank(Open/Close - 1)``，当日有 180 只 ``Open == Close``。
    本地按 ``average`` 时该并列块名次为 2196.5，官方为 2289（= 块内最大名次）；
    换成 ``method="max"`` 后，5539 只股票的 ``官方名次 − 本地名次``
    **只取 {0, 3} 两个值**（3 = 官方多纳入的 3 只停牌股），零残差。

    ``CFG["RANK_METHOD"]`` 可切回 ``"average"`` 做变体对照。
    """
    method = str(CFG["RANK_METHOD"])
    r = df.rank(axis=1, method=method, pct=False, na_option="keep")
    n = df.notna().sum(axis=1)
    if CFG["RANK_PCT"] == "n-1":
        return r.sub(1).div((n - 1).replace(0, np.nan), axis=0)
    return r.div(n.replace(0, np.nan), axis=0)


def scale(df: pd.DataFrame, a: float = 1.0) -> pd.DataFrame:
    """``Scale(x, a)`` = ``a · x / Σ|x|``（按行求和）。"""
    return df.mul(a).div(df.abs().sum(axis=1).replace(0, np.nan), axis=0)


def industry_matrix(groups: pd.Series, columns) -> np.ndarray:
    """``(n_codes, n_groups)`` 的 0/1 指示矩阵（缺失行业归入独立组）。"""
    g = groups.reindex(pd.Index(columns)).astype(object).where(
        lambda s: s.notna(), "__UNKNOWN__")
    cats = pd.Categorical(g.tolist())
    m = np.zeros((len(columns), len(cats.categories)), dtype=float)
    m[np.arange(len(columns)), cats.codes] = 1.0
    return m


def ind_neutralize(df: pd.DataFrame, ind_mat: np.ndarray) -> pd.DataFrame:
    """``IndNeutralize(x, Industry)`` = ``x − mean(x | industry)``（逐日截面）。

    ``ind_mat`` 由 :func:`industry_matrix` 生成（列顺序须与 ``df.columns`` 一致）。
    """
    v = df.values.astype(float)
    mask = np.isfinite(v)
    v0 = np.where(mask, v, 0.0)
    sums = v0 @ ind_mat                     # (T, G)
    cnts = mask.astype(float) @ ind_mat
    # ⚠ 空组（全员 NaN，例如被股票池掩码剔掉）必须填 0 再矩阵乘：
    # IEEE 下 NaN×0 = NaN，若保留 NaN 会把**整行**的所有股票污染成 NaN。
    means = np.where(cnts > 0, sums / np.where(cnts > 0, cnts, 1.0), 0.0)
    grp_mean = means @ ind_mat.T            # (T, S)
    out = v - grp_mean
    out[~mask] = np.nan
    return pd.DataFrame(out, index=df.index, columns=df.columns)


# ======================================================== 时序算子 ==============
def delay(df: pd.DataFrame, d: int) -> pd.DataFrame:
    return df.shift(int(d))


def delta(df: pd.DataFrame, d: int) -> pd.DataFrame:
    d = int(d)
    return df - df.shift(d)


def ts_sum(df: pd.DataFrame, d: int) -> pd.DataFrame:
    return df.rolling(int(d)).sum()


def ts_mean(df: pd.DataFrame, d: int) -> pd.DataFrame:
    return df.rolling(int(d)).mean()


def stddev(df: pd.DataFrame, d: int, ddof: int | None = None) -> pd.DataFrame:
    return df.rolling(int(d)).std(ddof=int(CFG["STD_DDOF"] if ddof is None else ddof))


def ts_min(df: pd.DataFrame, d: int) -> pd.DataFrame:
    return df.rolling(int(d)).min()


def ts_max(df: pd.DataFrame, d: int) -> pd.DataFrame:
    return df.rolling(int(d)).max()


def product(df: pd.DataFrame, d: int) -> pd.DataFrame:
    d = int(d)
    if d <= 1:
        return df.copy()
    return df.rolling(d).apply(np.prod, raw=True)


def _sw(a: np.ndarray, w: int):
    from numpy.lib.stride_tricks import sliding_window_view
    return sliding_window_view(a, w, axis=0)


def ts_rank(df: pd.DataFrame, d: int, chunk: int = 300) -> pd.DataFrame:
    """``Ts_Rank(x, d)`` —— 窗口内当前值的百分位（0~1）。

    ``CFG["TSRANK_CMP"]="le"``：``count(x_i <= x_t) / d``（含并列，社区通行）。
    ``"lt"``：``count(x_i < x_t) / d``。
    """
    w = int(d)
    a = df.values.astype(float)
    T, S = a.shape
    out = np.full((T, S), np.nan)
    if T < w:
        return pd.DataFrame(out, index=df.index, columns=df.columns)
    cmp_mode = str(CFG["TSRANK_CMP"])
    for s0 in range(0, S, chunk):
        blk = a[:, s0:s0 + chunk]
        sw = _sw(blk, w)
        last = sw[:, :, -1:]
        with np.errstate(invalid="ignore"):
            if cmp_mode == "lt":
                cnt = (sw < last).sum(axis=2).astype(float)
            elif cmp_mode == "avg":
                # 当前值的**平均名次**（等价 scipy.stats.rankdata 1-based，并列取中）
                lt = (sw < last).sum(axis=2).astype(float)
                eq = (sw == last).sum(axis=2).astype(float)
                cnt = lt + (eq + 1.0) / 2.0
            elif cmp_mode == "min":
                # 并列取**最小名次**：count(<) + 1（实测 qdata Ts_Rank 口径）
                cnt = (sw < last).sum(axis=2).astype(float) + 1.0
            else:
                cnt = (sw <= last).sum(axis=2).astype(float)
        valid = np.isfinite(sw).all(axis=2)
        out[w - 1:, s0:s0 + chunk] = np.where(valid, cnt / w, np.nan)
    return pd.DataFrame(out, index=df.index, columns=df.columns)


def ts_argmax(df: pd.DataFrame, d: int, chunk: int = 300) -> pd.DataFrame:
    """``Ts_ArgMax(x, d)`` —— 窗口内最大值的位置。

    ``CFG["TSARGMAX_MODE"]``：
        ``"pos"``   自**最旧一日**起算的位置 ``0..d-1``（``np.argmax`` 口径）
        ``"since"`` 距**最大值出现**的天数 ``d-1..0``（WorldQuant 论文「days since
                    the max」口径，与 ``"pos"`` 的排序**恰好相反**）

    实测（2026-09-17）：``alpha101_1 = Rank(Ts_ArgMax(...,5)) - 0.5`` 在 ``"pos"`` 下
    与官方 Spearman = **−0.9385**（几乎完全反序），⇒ 官方是 ``"since"`` 口径。
    ``CFG["TSARGMAX_BASE"]`` 只做整体加常数（Rank 不变），仅供非 Rank 场景微调。
    """
    w = int(d)
    a = df.values.astype(float)
    T, S = a.shape
    out = np.full((T, S), np.nan)
    if T < w:
        return pd.DataFrame(out, index=df.index, columns=df.columns)
    base = int(CFG["TSARGMAX_BASE"])
    since = str(CFG["TSARGMAX_MODE"]) == "since"
    tie_last = str(CFG["TSARGMAX_TIE"]) == "last"
    for s0 in range(0, S, chunk):
        sw = _sw(a[:, s0:s0 + chunk], w)
        finite = np.isfinite(sw).any(axis=2)
        filled = np.where(np.isfinite(sw), sw, -np.inf)
        if tie_last:                       # 并列取**最近**一次出现
            idx = (w - 1) - filled[:, :, ::-1].argmax(axis=2).astype(float)
        else:                              # 并列取**最早**一次出现（np.argmax 默认）
            idx = filled.argmax(axis=2).astype(float)
        val = (w - 1 - idx + base) if since else (idx + base)
        out[w - 1:, s0:s0 + chunk] = np.where(finite, val, np.nan)
    return pd.DataFrame(out, index=df.index, columns=df.columns)


def decay_linear(df: pd.DataFrame, d: int, chunk: int = 300) -> pd.DataFrame:
    """``Decay_Linear(x, d)`` —— 窗口内线性衰减加权平均（要求窗口全 finite）。"""
    w = int(d)
    a = df.values.astype(float)
    T, S = a.shape
    out = np.full((T, S), np.nan)
    if T < w:
        return pd.DataFrame(out, index=df.index, columns=df.columns)
    weights = np.arange(1, w + 1, dtype=float)          # 旧 → 新
    if CFG["DECAY_ORDER"] == "recent_light":
        weights = weights[::-1].copy()
    weights /= weights.sum()
    for s0 in range(0, S, chunk):
        sw = _sw(a[:, s0:s0 + chunk], w)
        valid = np.isfinite(sw).all(axis=2)
        out[w - 1:, s0:s0 + chunk] = np.where(valid, sw @ weights, np.nan)
    return pd.DataFrame(out, index=df.index, columns=df.columns)


def correlation(a: pd.DataFrame, b: pd.DataFrame, d: int) -> pd.DataFrame:
    """``Correlation(x, y, d)`` —— 滚动窗口内 Pearson 相关（逐股票）。"""
    w = int(d)
    ma, mb = a.rolling(w).mean(), b.rolling(w).mean()
    cov = (a * b).rolling(w).mean() - ma * mb
    va = (a * a).rolling(w).mean() - ma ** 2
    vb = (b * b).rolling(w).mean() - mb ** 2
    return cov / np.sqrt(va * vb).replace(0, np.nan)


def covariance(a: pd.DataFrame, b: pd.DataFrame, d: int,
               ddof: int | None = None) -> pd.DataFrame:
    """``Covariance(x, y, d)`` —— 滚动协方差（默认样本口径，与 STD_DDOF 一致）。"""
    w = int(d)
    k = int(CFG["STD_DDOF"] if ddof is None else ddof)
    ma, mb = a.rolling(w).mean(), b.rolling(w).mean()
    cov = (a * b).rolling(w).mean() - ma * mb
    if k == 1:
        cov = cov * w / (w - 1)
    return cov


# ======================================================== 逐元素算子 ============
def sign(df):  return np.sign(df) if isinstance(df, pd.DataFrame) else np.sign(df)


def abs_(df):
    return df.abs() if isinstance(df, pd.DataFrame) else np.abs(df)


def log(df):
    return np.log(df.where(df > 0) if isinstance(df, pd.DataFrame) else df)


def signed_power(df, p):
    if isinstance(df, pd.DataFrame):
        return np.sign(df) * (df.abs() ** p)
    return np.sign(df) * (np.abs(df) ** p)


def power(a, b):
    if isinstance(a, pd.DataFrame):
        b2 = b if not isinstance(b, pd.DataFrame) else b
        return np.sign(a) * (a.abs() ** b2) if False else a ** b2
    return a ** b


def elem_min(a, b):
    if isinstance(a, pd.DataFrame) and isinstance(b, pd.DataFrame):
        return pd.DataFrame(np.minimum(a.values, b.values), index=a.index, columns=a.columns)
    return a.where(a <= b, b) if isinstance(a, pd.DataFrame) else np.minimum(a, b)


def elem_max(a, b):
    if isinstance(a, pd.DataFrame) and isinstance(b, pd.DataFrame):
        return pd.DataFrame(np.maximum(a.values, b.values), index=a.index, columns=a.columns)
    return a.where(a >= b, b) if isinstance(a, pd.DataFrame) else np.maximum(a, b)


def if_else(cond, a, b):
    """``cond ? a : b``（cond 为 bool DataFrame）。"""
    if isinstance(cond, pd.DataFrame):
        ca = a.values if isinstance(a, pd.DataFrame) else a
        cb = b.values if isinstance(b, pd.DataFrame) else b
        out = np.where(cond.values.astype(bool), ca, cb)
        return pd.DataFrame(out, index=cond.index, columns=cond.columns)
    return a if cond else b
