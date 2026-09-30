#!/usr/bin/env python
"""pershare 族（15 因子）本地复现 —— **单期科目子集**。

每股因子 = 某科目 / 总股本。其中 6 个含 TTM（``*_ttm``、``net_operate_cash_flow_per_share``）
受账号财务边界阻断（见 conventions.py F 段）；其余 9 个只需**最新一期**报表，可精确复现。

总股本口径：``valuation.capitalization`` 单位为**万股**，因子分母为**股** → ×1e4。
（与 market_cap 的亿元→元同理，属 D6 类单位陷阱。）
"""
from __future__ import annotations

import numpy as np
import pandas as pd

FAMILY = "pershare"
NEEDS_TABLES = True

BALANCE_FIELDS = ["capital_reserve_fund", "equities_parent_company_owners",
                  "other_equity_tools", "surplus_reserve_fund", "retained_profit"]
# 「现金及现金等价物余额」在 **cash_flow** 表（balance.cash_equivalents 是「货币资金」，
# 口径不同：实测用它 corr 仅 0.80，换成该字段后达 GOOD）
CASHFLOW_FIELDS = ["cash_and_equivalents_at_end", "net_operate_cash_flow"]
INCOME_FIELDS = ["operating_profit", "operating_revenue", "total_operating_revenue"]
VALUATION_FIELDS = ["capitalization"]
TTM_SPEC = {"income": ["net_profit", "np_parent_company_owners", "operating_profit",
                       "operating_revenue", "total_operating_revenue"],
            "cash_flow": ["cash_equivalent_increase", "net_operate_cash_flow",
                          "net_invest_cash_flow", "net_finance_cash_flow"]}

WAN = 1e4   # 万股 -> 股


def build(tables: dict[str, dict[str, pd.DataFrame]]) -> dict[str, pd.DataFrame]:
    bal, inc, val = tables["balance"], tables["income"], tables["valuation"]
    cfl = tables["cash_flow"]
    sh = (val["capitalization"] * WAN).replace(0, np.nan)   # 总股本（股）

    out: dict[str, pd.DataFrame] = {}
    # ---- 资产负债表科目 / 总股本 ----
    out["capital_reserve_fund_per_share"] = bal["capital_reserve_fund"] / sh
    out["cash_and_equivalents_per_share"] = cfl["cash_and_equivalents_at_end"] / sh
    out["net_asset_per_share"] = (
        bal["equities_parent_company_owners"] - bal["other_equity_tools"].fillna(0)) / sh
    out["retained_earnings_per_share"] = (
        bal["surplus_reserve_fund"] + bal["retained_profit"]) / sh
    out["retained_profit_per_share"] = bal["retained_profit"] / sh
    out["surplus_reserve_fund_per_share"] = bal["surplus_reserve_fund"] / sh

    # ---- 单期利润表科目 / 总股本 ----
    out["operating_profit_per_share"] = inc["operating_profit"] / sh
    out["operating_revenue_per_share"] = inc["operating_revenue"] / sh
    out["total_operating_revenue_per_share"] = inc["total_operating_revenue"] / sh

    # ---- TTM 科目 / 总股本（TTM 逐位一致，见 conventions.py F1）----
    ttm = tables["ttm"]
    # ⚠ 文档写「归属母公司所有者的净利润(TTM)/总股本」，实测分子是 **net_profit**（全部净利润）：
    #   归母版 maxerr 2.379 ❌ ｜ net_profit 版 maxerr 4.37e-07 ✅
    out["eps_ttm"] = ttm["net_profit"] / sh
    out["operating_profit_per_share_ttm"] = ttm["operating_profit"] / sh
    out["operating_revenue_per_share_ttm"] = ttm["operating_revenue"] / sh
    out["total_operating_revenue_per_share_ttm"] = ttm["total_operating_revenue"] / sh
    # ⚠ 名含 12 个月「TTM」但实测是**单期**值：单季/股本 maxerr 4.97e-07 ✅，
    #   TTM/股本 maxerr 42.2 ❌（文档公式栏确实未写 TTM）
    out["net_operate_cash_flow_per_share"] = cfl["net_operate_cash_flow"] / sh
    # ⚠ 「现金流量净额(TTM)」= **经营+投资+筹资三项净额之和**，不是现金流表里
    #   现成的 cash_equivalent_increase 字段：
    #   三项之和 maxerr 4.91e-07 ✅ ｜ cash_equivalent_increase 0.172 ❌
    out["cashflow_per_share_ttm"] = (
        ttm["net_operate_cash_flow"] + ttm["net_invest_cash_flow"]
        + ttm["net_finance_cash_flow"]) / sh

    return out


NOTES: dict[str, str] = {
    "eps_ttm": "需 TTM 归母净利润（过去四季之和），受财务边界阻断。见 conventions.py F 段。",
    "operating_profit_per_share_ttm": "同上：需 TTM 营业利润。",
    "operating_revenue_per_share_ttm": "同上：需 TTM 营业收入。",
    "total_operating_revenue_per_share_ttm": "同上：需 TTM 营业总收入。",
    "cashflow_per_share_ttm": "同上：需 TTM 现金流量净额。",
    "net_operate_cash_flow_per_share": "同上：需 TTM 经营活动现金流量净额。",
    "cash_and_equivalents_per_share": (
        "已实现（GOOD）。注意口径：余额取自 **cash_flow.cash_and_equivalents_at_end**，"
        "**不是** balance.cash_equivalents（后者是「货币资金」）。"
    ),
}
