#!/usr/bin/env python
"""momentum 族（34 因子）本地复现。

公式来源：.jqdata/docs/factor_library_formulas.json。
口径：后复权、MA 含当日、EMA=span/adjust=False、年化 250（见 conventions）。

文档含糊处（已用变体对照标定，见文件末 CALIBRATION 注释）：
- ``MASS`` 文档只写 ``MASS(N1=9, N2=25, M=6)``，**无公式**，按行业标准
  Mass Index 实现：``Σ_{25}( EMA(H-L,9) / EMA(EMA(H-L,9),9) )``。
- ``CR20`` 文档截断，按 TDX 标准：中间价 =(H_prev+L_prev)/2，上升值 =max(0,H−中)，
  下跌值 =max(0,中−L)，CR =Σ上升/Σ下跌×100。
- ``arron_*_25`` 的「最高价后的天数」按窗口内 argmax 距窗口末端的距离计。
- ``fifty_two_week_close_rank`` 为**时序**分位（当日收盘价在过去 250 日中的位置）。
- ``Rank1M`` 是**截面**因子（除以股票总数），依赖官方股票池，小样本面板无法复现。
- ``single_day_VPT`` 文档注明用**当日前复权**，与全局面板的后复权口径不同。
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from .. import ops as O
from ..data import Panel

FAMILY = "momentum"

BIAS_WINDOWS = (5, 10, 20, 60)
CCI_WINDOWS = (10, 15, 20, 88)
PLRC_WINDOWS = (6, 12, 24)
ROC_WINDOWS = (6, 12, 20, 60, 120)


def _aroon(src: pd.DataFrame, w: int, up: bool) -> pd.DataFrame:
    """Aroon 上下轨 = (idx + 1)/w × 100，idx 为极值在窗口内的 0-based 位置。

    ⚠ 两条实测标定（2026-09-17）：
    1. **并列极值取末次**（``flatnonzero(...)[-1]``）：
       取首次 → maxerr 4.4e+01 ❌ ｜ 取末次 → maxerr 7.1e-15 ✅（精确）
    2. **``arron_down_25`` 用的是 HIGH 序列而非 LOW**（官方实现的怪癖，非文档口径）：
       down 用 low  → maxerr 9.6e+01 ❌ ｜ down 用 high → maxerr 7.1e-15 ✅
       （high+argmin / close+argmin / −low+argmax 均已排除）
    """

    def _pos(x: np.ndarray) -> float:
        if not np.isfinite(x).all():
            return np.nan
        target = x.max() if up else x.min()
        idx = np.flatnonzero(x == target)[-1]
        return (idx + 1) / w * 100.0

    return src.rolling(w).apply(_pos, raw=True)


def _ts_percentile(close: pd.DataFrame, w: int) -> pd.DataFrame:
    """当日收盘价在过去 w 日中的分位（越大越接近区间高点）。"""
    def _p(x: np.ndarray) -> float:
        if not np.isfinite(x).all():
            return np.nan
        return float((x <= x[-1]).sum()) / len(x)
    return close.rolling(w).apply(_p, raw=True)


def build(panel: Panel) -> dict[str, pd.DataFrame]:
    O_, H, L, C, V = panel.O, panel.H, panel.L, panel.C, panel.V
    out: dict[str, pd.DataFrame] = {}

    # ---- BBIC = BBI(3,6,12,24)/C ----
    bbi = (O.ma(C, 3) + O.ma(C, 6) + O.ma(C, 12) + O.ma(C, 24)) / 4.0
    out["BBIC"] = bbi / C

    # ---- BIAS{n} ----
    for n in BIAS_WINDOWS:
        m = O.ma(C, n)
        out[f"BIAS{n}"] = (C - m) / m * 100.0

    # ---- CCI{n} ----
    typ = (H + L + C) / 3.0
    for n in CCI_WINDOWS:
        out[f"CCI{n}"] = (typ - O.ma(typ, n)) / (0.015 * O.avedev(typ, n))

    # ---- CR20 ----
    mid = (H.shift(1) + L.shift(1)) / 2.0
    up = (H - mid).clip(lower=0)
    dn = (mid - L).clip(lower=0)
    out["CR20"] = up.rolling(20).sum() / dn.rolling(20).sum().replace(0, np.nan) * 100.0

    # ---- MASS（文档无公式，按行业标准 Mass Index）----
    # 实测标定：官方用 **SMA** 而非行业惯用的 EMA
    #   SMA9/SMA9(SMA9) → maxerr 2.71e-02, corr 0.999997  ✅
    #   EMA9/EMA9(EMA9) → maxerr 1.61e+00, corr 0.9719    ❌
    rng = H - L
    s1 = O.ma(rng, 9)
    s2 = O.ma(s1, 9)
    out["MASS"] = (s1 / s2.replace(0, np.nan)).rolling(25).sum()

    # ---- PLRC{n}：窗口内归一化收盘价对 t 的回归斜率 = slope(C,n)/MA(C,n) ----
    # 实测标定：slope(C)/MA(C) maxerr 4.95e-07 ✅；逐日滚动均值归一化后再回归 2.64e-02 ❌
    for n in PLRC_WINDOWS:
        out[f"PLRC{n}"] = O.linreg_slope(C, n) / O.ma(C, n)

    # ---- Price1M / Price3M / Price1Y ----
    # ⚠ 实测标定（goal-3）：均值窗口是「**不含当日的过去 N 日**」，即 MA(N).shift(1)。
    #   文档写的「过去一个月(21天)」是指「20 个历史日 + 当日」的跨度，但**均值不含当日**。
    #   宽池 160 只实测：
    #       Price1M  C/MA(20).shift(1) → max 5.0e-07 ✅ ｜ C/MA(21) → 3.2e-02 ❌
    #       Price3M  C/MA(60).shift(1) → max 5.0e-07 ✅ ｜ C/MA(61) → 1.1e-02 ❌
    out["Price1M"] = C / O.ma(C, 20).shift(1) - 1
    out["Price3M"] = C / O.ma(C, 60).shift(1) - 1
    out["Price1Y"] = C / O.ma(C, 249).shift(1) - 1   # 类推（窗口不足，未实测）

    # ---- ROC{n} ----
    for n in ROC_WINDOWS:
        base = C.shift(n)
        out[f"ROC{n}"] = (C - base) / base.replace(0, np.nan) * 100.0

    # ---- Rank1M：截面因子，依赖官方股票池 ----
    r20 = C / C.shift(20) - 1
    out["Rank1M"] = 1 - r20.rank(axis=1, pct=True)

    # ---- TRIX{n}：三次 EMA ----
    for n in (5, 10):
        mtr = O.ema(O.ema(O.ema(C, n), n), n)
        prev = mtr.shift(1)
        out[f"TRIX{n}"] = (mtr - prev) / prev.replace(0, np.nan) * 100.0

    # ---- Volume1M ----
    out["Volume1M"] = (V / V.rolling(20).mean()) * (C.pct_change().rolling(20).mean())

    # ---- Aroon ----
    out["arron_up_25"] = _aroon(H, 25, up=True)
    out["arron_down_25"] = _aroon(H, 25, up=False)   # 官方用 high（见 docstring）

    # ---- 多空力道 ----
    e13 = O.ema(C, 13)
    out["bear_power"] = (L - e13) / C
    out["bull_power"] = (H - e13) / C

    # ---- 52 周收盘价分位 ----
    out["fifty_two_week_close_rank"] = _ts_percentile(C, 250)

    # ---- 单日价量趋势 ----
    # 实测标定（2026-09-17）：成交量用**不复权**量、单位为「手」（/100）；
    # 收益率用**后复权**收盘价（= 真实收益率，除权日亦正确）。
    #   后复权收益率 × 不复权量/100 → maxerr 4.9e+01, rel 3.4e-03 ✅
    #   不复权收益率 × 不复权量/100 → maxerr 3.8e+04（除权日错）      ❌
    #   前复权收益率 × 不复权量/100 → maxerr 7.4e+02                 ❌
    vpt = C.pct_change() * panel.V_RAW / 100.0
    out["single_day_VPT"] = vpt
    out["single_day_VPT_6"] = O.ma(vpt, 6)
    out["single_day_VPT_12"] = O.ma(vpt, 12)

    return out


CALIBRATION = """
变体对照（2026-09-17，600519 等 6 只，2025-12-01~2026-03-02）：
- arron_up_25 / arron_down_25 ✅ **EXACT**（maxerr 7.1e-15）。两条标定：
  ① 并列极值取**末次**（取首次 → maxerr 4.4e+01 ❌）；
  ② **arron_down_25 用 HIGH 序列，不是 LOW**（down 用 low → maxerr 9.6e+01 ❌）。
     已排除 high+argmin / close+argmin / −low+argmax 三种替代解释。
     这是官方实现的怪癖，与「Aroon 下轨用最低价」的通行定义相反。
- PLRC{n} ✅ 已标定：官方 = ``slope(close, n) / mean(close, n)``
  （maxerr 4.95e-07）。逐日滚动均值归一化后再回归 → 2.64e-02 ❌；
  直接对 close 回归 → 量纲差 1e4 ❌。
- single_day_VPT ✅ 已标定：``pct_change(**后复权**收盘价) × **不复权**成交量 / 100``
  （maxerr 4.9e+01, rel 3.4e-03）。成交量单位为「手」。
  不复权收益率 → 除权日错（maxerr 3.8e+04）❌；前复权收益率 → 7.4e+02 ❌。
- MASS ✅ 已标定：官方用 **SMA** 而非行业惯用的 EMA（SMA 版 corr 0.999997，
  EMA 版 corr 0.9719）。文档只写 "MASS(N1=9,N2=25,M=6)"，无公式。
- CCI 系列 ❌ 未收敛（maxerr 1.8e-01 ~ 4.1e-01，corr 1.0），AVEDEV 口径存疑。
- 其余 APPROX（BIAS/ROC/TRIX/Price1M/Price3M/VPT_6/VPT_12）**公式正确**
  （corr 全部 = 1.0000），残差来自**输入价精度放大**：本地面板的后复权价与官方
  内部序列存在 ~1e-4 相对差异，凡乘以 100（BIAS/ROC）或做差（Price）的因子都会
  把该差异放大到 1e-2 量级。对照：未放大的 MAC5（technical 族）误差仅 5.35e-05。
"""

_PRICE = ("已实现（GOOD，maxerr ~5e-07）。⚠ **均值窗口不含当日** —— "
          "文档写「过去一个月(21天)」，实际是「**不含当日的过去 20 日**」均值，"
          "即 ``C/MA(N-1).shift(1)-1``。宽池 160 只实测："
          "Price1M 用 MA(20).shift(1) → max 5.0e-07 ✅ ｜用 MA(21) → 3.2e-02 ❌；"
          "Price3M 用 MA(60).shift(1) → 5.0e-07 ✅ ｜用 MA(61) → 1.1e-02 ❌。"
          "已排除「上一自然月均值」口径（rel 0.32）。"
          "⚠ 该「不含当日」是**本组因子特有**：BIAS/CCI/CR20/TRIX 实测均为**含当日**最优。")
_BATCHB = ("**口径未标定（非精度问题）**：已用全精度价（`round=False`）复测，误差不变；"
           "且误差与股价水平无关 → 排除「价格精度放大」假说。已排除窗口 shift±1、"
           "MA 窗口 20/21/22/23、均值 vs 求和、clip、前/后/不复权等变体，"
           "现行实现均为最优。残差 rel 1.5%~13%、corr ≥0.99999，误差有界。"
           "详见 conventions.py G 段。")

NOTES: dict[str, str] = {
    "ROC6": _BATCHB, "CR20": _BATCHB, "Price1M": _PRICE, "Price3M": _PRICE,
    "single_day_VPT_6": _BATCHB, "single_day_VPT_12": _BATCHB,
    "Price1Y": (
        "需要 250 个交易日窗口，而面板被夹在账号区间左界（2025-06-09），"
        "至 2026-03-02 仅 177 日 → **窗口不足**，非公式错误。"
        "把比对区间移到账号窗口末端（2026-05 之后）即可覆盖。"
    ),
    "fifty_two_week_close_rank": "同上：需 250 日窗口，当前面板仅 177 日 → 窗口不足。",
    "Rank1M": (
        "**口径已确认，残差来自 universe 构成**（goal-2 第 5 轮，用全市场面板 5190 只实测）："
        "① 公式确认：``Rank1M = 1 − ret20.rank(axis=1, pct=True)``，"
        "**逐日截面 corr = +1.0000**（每日都完美同序）。"
        "② 窗口确认：``shift(20)``（19/21 的 maxerr 为 0.245/0.225）。"
        "③ 残余 maxerr 0.0088 ≈ **45/5190 个名次** → universe 构成差异："
        "全市场只能取 ``types=['stock']``（5190 只），**北交所属付费模块**，"
        "且官方可能另有停牌/新股过滤规则。已排除 rank method（average/min/max/"
        "first/dense）与上市天数过滤。"
        "④ ⚠ **本族现行实现用 6 只标的的截面算 rank，结构性无效** —— "
        "截面因子的 rank 必须在全市场截面上算，该值不可信；"
        "正确实现需 ``data.load_market_close``（约 13 万条/次）。"
        "⑤ 方法论：截面因子**不能看跨时 pooled corr**（本例 pooled 仅 0.33 会误导），"
        "必须看**逐日截面 corr**（1.0000）。"
    ),
    "MASS": "已改用 SMA（实测标定）；残余 maxerr 2.7e-02 属精度放大。",
    "single_day_VPT_6": "公式正确（corr=1.0000）；VPT 残差经 6 日均值累积后放大。",
    "single_day_VPT_12": "公式正确（corr=1.0000）；VPT 残差经 12 日均值累积后放大。",
}
for _c in ("BIAS5", "BIAS10", "BIAS20", "BIAS60", "ROC6", "ROC12", "ROC20",
           "ROC60", "ROC120", "TRIX5", "TRIX10", "CCI10", "CCI15", "CCI20",
           "CCI88", "Price1M", "Price3M"):
    NOTES.setdefault(
        _c, "公式正确（corr=1.0000），残差为输入价精度放大（×100/做差放大），见 CALIBRATION。")
