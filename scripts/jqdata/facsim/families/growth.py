#!/usr/bin/env python
"""growth 族（9 因子）本地复现 —— 仅 2 个可用。

**为什么只有 2 个**（实测取证，2026-09-17）：
- 7 个是**同比增速**：``TTM(最近四季) / TTM(去年同期) - 1``。2026-05 比对时
  最近四季 = 2025q2~2026q1（可及），但**去年同期 = 2024q2~2025q1 需要 2024 年财报**
  → 账号取不到（静默返回 0 行）。已实测确认：用「自然年 2025」当基期的替代算法
  与官方相差 ~100%（量纲）且方向都不对，**不可用替代口径**。
- 2 个是**资产/权益增长**，只要「4 个季度前」的资产负债表，2025q1 在可及范围内。

实测标定：
    total_asset_growth_rate = 总资产(当季) / 总资产(4 季度前) − 1   → 平均相对误差 0.0004%
    net_asset_growth_rate   = 股东权益(当季) / 股东权益(4 季度前) − 1 → 平均 0.0004%
    ⚠ 文档写「三季度前的股东权益」，实测是 **4 个季度前**（且用**总权益**而非归母：
      归母口径平均误差 11.0%）。又一处文档与实现不符。
"""
from __future__ import annotations

import numpy as np
import pandas as pd

FAMILY = "growth"
NEEDS_TABLES = True
BALANCE_FIELDS: list[str] = []
INCOME_FIELDS: list[str] = []
VALUATION_FIELDS: list[str] = []
# 同比基期：取 5 个季度，first = 4 季度前，last = 当季
LAGQ_SPEC = {"balance": ["total_assets", "total_owner_equities"]}


def build(tables: dict[str, dict[str, pd.DataFrame]]) -> dict[str, pd.DataFrame]:
    prev, cur = tables["lagq_first"], tables["lagq_last"]
    out: dict[str, pd.DataFrame] = {}
    out["total_asset_growth_rate"] = (
        cur["total_assets"] / prev["total_assets"].replace(0, np.nan) - 1)
    out["net_asset_growth_rate"] = (
        cur["total_owner_equities"] / prev["total_owner_equities"].replace(0, np.nan) - 1)
    return out


NOTES: dict[str, str] = {}
_YOY = ("**结构性阻断**：需「去年同期 TTM」= 2024q2~2025q1，而账号财务数据只到 2025q1 "
        "→ 2024 年财报取不到。已实测排除「自然年 2025 基期」等替代口径（与官方差 ~100%）。")
for _c in ("PEG", "financing_cash_growth_rate", "net_operate_cashflow_growth_rate",
           "net_profit_growth_rate", "np_parent_company_owners_growth_rate",
           "operating_revenue_growth_rate", "total_profit_growth_rate"):
    NOTES[_c] = _YOY
NOTES["net_asset_growth_rate"] = (
    "已实现（EXACT）。⚠ 文档写「三季度前」，实测是 **4 个季度前**且用**总权益**"
    "（归母口径平均误差 11%）。")
