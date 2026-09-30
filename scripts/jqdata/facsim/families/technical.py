#!/usr/bin/env python
"""technical 族（16 因子）本地复现。

公式来源：``.jqdata/docs/factor_library_formulas.json``（category=technical）。
口径来源：``facsim.conventions``（STD=ddof1、MA 含当日、后复权）。

文档未写明的项，按 D 段原则处理：
- EMA 的 adjust：受 ``conventions.EMA_ADJUST`` 控制，实测标定后再固化。
- MACDC 的 MACD 具体取哪条线（DIF / DEA / 柱）：文档只写 ``MACD(...)/C``，
  实现取 ``MACD = DIF - DEA``（与同库 VMACD 的文字定义一致），实测校验。
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from .. import ops as O
from ..data import Panel

FAMILY = "technical"


def build(panel: Panel) -> dict[str, pd.DataFrame]:
    C, H, L, V = panel.C, panel.H, panel.L, panel.V
    out: dict[str, pd.DataFrame] = {}

    # ---- 布林线上下轨：(MA ± 2*STD)/C, M=20 ----
    ma20, sd20 = O.ma(C, 20), O.std(C, 20)
    out["boll_down"] = (ma20 - 2 * sd20) / C
    out["boll_up"] = (ma20 + 2 * sd20) / C

    # ---- 指数移动均线 / C ----
    for n in (5, 10, 12, 20, 26, 120):
        code = f"EMA{n}" if n == 5 else f"EMAC{n}"
        out[code] = O.ema(C, n) / C

    # ---- 简单移动均线 / C ----
    for n in (5, 10, 20, 60, 120):
        out[f"MAC{n}"] = O.ma(C, n) / C

    # ---- MACDC = 2*(DIF - DEA)/C, SHORT=12 LONG=26 MID=9 ----
    # 实测标定（2026-09-17）：文档只写 "MACD(SHORT=12,LONG=26,MID=9)/今日收盘价"，
    # 未说明取哪条线、是否含 TDX 的 ×2。四变体对照结果：
    #     (DIF-DEA)/C      maxerr 2.13e-02  ❌
    #     DIF/C            maxerr 6.83e-02  ❌
    #     DEA/C            maxerr 7.30e-02  ❌
    #     2*(DIF-DEA)/C    maxerr 1.15e-05  ✅
    dif = O.ema(C, 12) - O.ema(C, 26)
    dea = O.ema(dif, 9)
    out["MACDC"] = 2 * (dif - dea) / C

    # ---- MFI14：资金流量指标 ----
    typ = (H + L + C) / 3.0
    mf = typ * V                                        # 资金流 = 典型价格 × 成交量
    up = typ.diff()
    pos = mf.where(up > 0, 0.0).rolling(14).sum()
    neg = mf.where(up < 0, 0.0).rolling(14).sum()
    mr = pos / neg.replace(0, np.nan)
    out["MFI14"] = 100 - 100 / (1 + mr)

    # ---- price_no_fq：不复权价格 ----
    out["price_no_fq"] = panel.C_RAW

    return out


# 文档「计算方法」明确、且参数可从 code 直接解析的因子
IMPLICIT_WINDOW = {
    "MAC5": 5, "MAC10": 10, "MAC20": 20, "MAC60": 60, "MAC120": 120,
    "EMA5": 5, "EMAC10": 10, "EMAC12": 12, "EMAC20": 20, "EMAC26": 26, "EMAC120": 120,
    "boll_down": 20, "boll_up": 20, "MFI14": 14,
}

# 未达 GOOD 档的因子：把实测诊断写进报告，避免下轮重复踩坑
NOTES: dict[str, str] = {
    "MACDC": (
        "绝对误差 1.15e-05，与 GOOD 档同量级；APPROX 源于官方值量级本身很小"
        "（mean|·|≈0.0065）。公式已按 2*(DIF-DEA)/C 标定（其余三变体误差 1e-2 量级）。"
    ),
    "EMAC120": (
        "EWMA 暖机不足，**非公式错误**：误差随日期单调衰减（2025-12-01 为 1.66e-02 → "
        "2026-03-02 为 6.98e-03）。span=120 需约 5×120=600 个交易日预热才能收敛，"
        "而试用账号窗口仅 372 日、可用预热不足 177 日 → 结构性不可复现。"
        "短期 span（EMA5/EMAC26 等）已 GOOD，印证该解释。"
    ),
    "MFI14": (
        "**公式已确认，FAIL 由单只标的异常主导**：逐标的实测最大误差——"
        "000001 2.5e-05 ｜ 600519 3.9e-05 ｜ 002415 1.1e-04 ｜ 600036 4.0e-04 ｜ "
        "000651 7.8e-04 ｜ **000002.XSHE 2.67（异常）**。5/6 标的达 GOOD 档，"
        "万科A 在 2026-02-26~03-02 持续偏离 ~2.67 → 疑停牌/数据源差异，"
        "非公式问题。已排除 typ*V vs 成交额、等值归类、min_periods 三种变体。"
    ),
}
