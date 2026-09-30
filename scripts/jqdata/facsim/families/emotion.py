#!/usr/bin/env python
"""emotion 族（36 因子）本地复现。

数据依赖：换手率/成交额系列。换手率取自 ``valuation.turnover_ratio``（单位 %），
由 ``data.load_fundamentals_panel`` 提供（见该函数注释）。

文档含糊处（跑比对后逐项标定，见 CALIBRATION）：
- ``VOL{n}`` 的换手率来源与单位（官方注明「单位为%」）。
- ``VR`` 的 ``AVS/BVS/CVS`` 定义与窗口 N（文档未给 N）。
- ``AR``/``BR`` 的 N 文档明写 26。
- ``VEMA5/10/12/26``、``MAWVAD`` 官方「计算方法」单元格为空，按名称字面实现。
- ``money_flow_20`` 名为 20 日，公式却只说「当日」资金流量 → 两种口径都测。
- 成交量系列用后复权量（V）还是不复权量（V_RAW）需实测。
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from .. import ops as O
from ..data import Panel

FAMILY = "emotion"
NEEDS_FUND = True
FUND_FIELDS = ["turnover_ratio", "circulating_market_cap", "market_cap"]

VOL_WINDOWS = (5, 10, 20, 60, 120, 240)
DAVOL_WINDOWS = (5, 10, 20)
DAVOL_BASE = 120
VEMA_WINDOWS = (5, 10, 12, 26)
ATR_WINDOWS = (6, 14)
ARBR_N = 26          # 文档明写 n=26
VR_N = 24            # ⚠ 实测标定：官方用 24（TDX 惯例 26 → maxerr 4.4e-01 ❌）


def build(panel: Panel, fund: dict[str, pd.DataFrame] | None = None) -> dict[str, pd.DataFrame]:
    if fund is None:
        raise ValueError("emotion 族需要换手率面板（fund）")
    OPEN, H, L, C = panel.O, panel.H, panel.L, panel.C
    V, MONEY = panel.V, panel.MONEY
    T = fund["turnover_ratio"]           # 换手率（%）
    out: dict[str, pd.DataFrame] = {}

    # ---- VOL{n} / DAVOL{n} ----
    vol: dict[int, pd.DataFrame] = {}
    for n in VOL_WINDOWS:
        vol[n] = T.rolling(n).mean()
        out[f"VOL{n}"] = vol[n]
    for n in DAVOL_WINDOWS:
        out[f"DAVOL{n}"] = vol[n] / vol[DAVOL_BASE].replace(0, np.nan)

    # ---- 换手率相对波动率 = std(turnover, 20, ddof=1) / 100 ----
    # ⚠ 实测标定：文档说「取 20 个交易日换手率的标准差」，但官方返回的是**小数**
    #   而非常用的百分数（off/loc 恒为 0.010000，std 2e-06）。
    out["turnover_volatility"] = T.rolling(20).std(ddof=1) / 100.0

    # ---- VROC{n} = (V - REF(V, n-1))/REF(V, n-1) × 100 ----
    # ⚠ 实测标定：官方用 **n-1** 的滞后，不是文档字面的 n。
    #   VROC6  REF(V,6) → maxerr 1.5e+02 ❌ ｜ REF(V,5) → 4.96e-07 ✅
    for n in (6, 12):
        base = V.shift(n - 1)
        out[f"VROC{n}"] = (V - base) / base.replace(0, np.nan) * 100.0

    # ---- 成交额均/标准差 ----
    for n in (6, 20):
        out[f"TVMA{n}"] = MONEY.rolling(n).mean()
        out[f"TVSTD{n}"] = MONEY.rolling(n).std(ddof=1)

    # ---- 成交量标准差 ----
    for n in (10, 20):
        out[f"VSTD{n}"] = V.rolling(n).std(ddof=1)

    # ---- 成交量指数移动平均 ----
    vema: dict[int, pd.DataFrame] = {}
    for n in VEMA_WINDOWS:
        vema[n] = O.ema(V, n)
        out[f"VEMA{n}"] = vema[n]

    # ---- VDIFF / VDEA / VMACD ----
    vdiff = vema[12] - vema[26]
    vdea = O.ema(vdiff, 9)
    out["VDIFF"] = vdiff
    out["VDEA"] = vdea
    out["VMACD"] = vdiff - vdea

    # ---- VOSC = (VEMA12 - VEMA26)/VEMA12 × 100 ----
    out["VOSC"] = (vema[12] - vema[26]) / vema[12].replace(0, np.nan) * 100.0

    # ---- VR = (AVS + 0.5·CVS)/(BVS + 0.5·CVS) ----
    chg = C.diff()
    up = V.where(chg > 0, 0.0).rolling(VR_N).sum()
    dn = V.where(chg < 0, 0.0).rolling(VR_N).sum()
    flat = V.where(chg == 0, 0.0).rolling(VR_N).sum()
    out["VR"] = (up + 0.5 * flat) / (dn + 0.5 * flat).replace(0, np.nan)

    # ---- AR / BR / ARBR ----
    pc = C.shift(1)
    # ⚠ 实测标定：AR 需 clip 负值，**BR 不 clip**（官方口径不一致）
    #   BR clip   → maxerr 5.4e+01 ❌ ｜ BR no-clip → 4.97e-07 ✅
    ar = (H - OPEN).clip(lower=0).rolling(ARBR_N).sum() / \
         (OPEN - L).clip(lower=0).rolling(ARBR_N).sum().replace(0, np.nan) * 100.0
    br = (H - pc).rolling(ARBR_N).sum() / \
         (pc - L).rolling(ARBR_N).sum().replace(0, np.nan) * 100.0
    out["AR"], out["BR"] = ar, br
    out["ARBR"] = ar - br

    # ---- ATR{n} = MA(真实振幅, n) ----
    tr = O.true_range(H, L, C)
    for n in ATR_WINDOWS:
        out[f"ATR{n}"] = O.ma(tr, n)

    # ---- PSY = 12日内上涨天数/12×100 ----
    out["PSY"] = O.count_up_days(C.pct_change(), 12) / 12.0 * 100.0

    # ---- WVAD / MAWVAD ----
    wvad = (C - OPEN) / (H - L).replace(0, np.nan) * V
    out["WVAD"] = wvad.rolling(6).sum()
    out["MAWVAD"] = O.ma(out["WVAD"], 6)

    # ---- money_flow_20 = Σ_{20}(TYP × V) ----
    # ⚠ 实测标定：文档正文只说「当日资金流量」，但官方是**20 日求和**
    #   （单日 → maxerr 2.0e+11 ❌ ｜ 20 日求和 → rel 9.9e-12 ✅）
    out["money_flow_20"] = ((H + L + C) / 3.0 * V).rolling(20).sum()

    return out


CALIBRATION = """
变体对照（2026-09-17，600519 等 6 只，2025-12-01~2026-03-02）：
- VOL{n}/DAVOL{n} ✅ EXACT：直接取 ``valuation.turnover_ratio``（%）做滚动均值。
- VROC{n} ⚠ **滞后为 n-1，不是 n**（官方 off-by-one）：
  VROC6 用 REF(V,6) → maxerr 1.5e+02 ❌ ｜ 用 REF(V,5) → 4.96e-07 ✅。
- VR ⚠ **窗口 = 24，不是 TDX 惯例的 26**：N=26 → maxerr 4.4e-01 ❌ ｜ N=24 → 4.99e-07 ✅。
- AR / BR ⚠ **口径不一致**：AR 需 clip 负值，**BR 不 clip**。
  BR clip → maxerr 5.4e+01 ❌ ｜ BR no-clip → 4.97e-07 ✅。
- money_flow_20 ⚠ 文档正文只说「当日资金流量」，官方实为**20 日求和**：
  单日 → maxerr 2.0e+11 ❌ ｜ rolling(20).sum() → rel 9.9e-12 ✅。
- turnover_volatility ⚠ 官方返回**小数**而非百分数（off/loc = 0.010000 恒定）→ 需 /100。
- VDIFF/VDEA/VMACD/VOSC：公式正确（corr 1.0），残差为**成交量 EMA 的暖机不足**
  （span 26 需约 130 日预热，与 EMAC120 同类问题），rel 2e-04 ~ 8e-04。
- VOL240：需 240 日窗口，面板仅 177 日 → **窗口不足**。
"""

NOTES: dict[str, str] = {
    "MAWVAD": "官方「计算方法」单元格为空，按名称实现（WVAD 的 6 日均值）。",
    "VOL240": (
        "需要 240 个交易日窗口，面板被夹在账号区间左界（2025-06-09），"
        "至 2026-03-02 仅 177 日 → **窗口不足**，非公式错误。"
    ),
    "VDIFF": "公式正确（corr=1.0000）；成交量 EMA 暖机不足（span 26 需约 130 日预热）。",
    "VDEA": "公式正确（corr=1.0000）；VDIFF 的 EMA 二次暖机叠加。",
    "VMACD": "公式正确（corr=1.0000）；暖机不足导致 rel 2e-04。",
    "VOSC": "公式正确（corr=1.0000）；两个 VEMA 的暖机差异导致 rel 8e-04。",
    "turnover_volatility": (
        "已按 /100 标定（官方返回小数）。maxerr 仅 4.99e-07，但官方值量级本身极小"
        "（mean≈0.0013），故 rel 略超 GOOD 阈值 1e-4 → 落在 APPROX。"
    ),
}
for _c in ("VEMA5", "VEMA10", "VEMA12", "VEMA26"):
    NOTES.setdefault(_c, "官方「计算方法」单元格为空，按名称实现（成交量的 N 日指数移动平均）。")
