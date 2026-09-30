#!/usr/bin/env python
"""basics 族（37 因子）本地复现 —— **单期报表科目子集**。

背景（重要）：本族多数因子是 **TTM（过去 4 个单季之和）**，而试用账号只覆盖
2025Q1~Q4 四季，且 TTM 求和与官方存在 0.35%~6.26% 残差（现金流类可达 137%）
——见 ``conventions.py`` F 段。因此本模块**只实现不依赖 TTM 的单期科目因子**，
这些可以精确复现；其余因子留空（报告会显示为 NO_DATA），不猜测、不硬凑。

已实现的单期因子及其文档依据：
    market_cap / circulating_market_cap  直接取 valuation（官方文档即「市值」「流通市值」）
    cash_flow_to_price_ratio             1 / pcf_ratio (ttm)
    sales_to_price_ratio                 1 / ps_ratio (ttm)
    net_working_capital                  流动资产 － 流动负债
    retained_earnings                    盈余公积金 + 未分配利润
    interest_free_current_liability      应付票据+应付账款+预收款项+应付职工薪酬
                                         +应交税费+应付利息+其他应付款+其他流动负债
    interest_carry_current_liability     流动负债合计 － 无息流动负债
    net_interest_expense                 利息支出 － 利息收入
    operating_assets                     总资产 － 金融资产
    operating_liability                  总负债 － 金融负债

未实现（依赖 TTM 或映射不唯一，原因归档于 NOTES）：
    net_profit_ttm / operating_revenue_ttm / *_ttm 系列、EBIT/EBITDA、
    financial_assets、net_debt、non_recurring_gain_loss 等。
"""
from __future__ import annotations

import numpy as np
import pandas as pd

FAMILY = "basics"
NEEDS_TABLES = True          # 提示 runner：本族需要报表面板
BALANCE_FIELDS = ["total_current_assets", "total_current_liability",
                  "total_assets", "total_liability", "surplus_reserve_fund",
                  "retained_profit", "notes_payable", "accounts_payable",
                  "advance_peceipts", "salaries_payable", "taxs_payable",
                  "interest_payable", "other_payable", "other_current_liability"]
INCOME_FIELDS = ["interest_expense", "interest_income", "net_profit",
                 "income_tax_expense", "financial_expense"]
# TTM：截至比对日最新 4 个单季之和（实测逐位一致，见 conventions.py F1）
# 官方把该科目的缺失季度按 0 计入（实测 2025q1 常为 NaN）：覆盖度 90→150、corr 0.92→0.9998
TTM_NAN0_SPEC = {"income": ["asset_impairment_loss"]}
TTM_SPEC = {
    "income": ["administration_expense", "financial_expense",
               "operating_cost", "operating_profit", "operating_revenue", "sale_expense",
               "total_operating_cost", "total_operating_revenue", "total_profit",
               "net_profit", "np_parent_company_owners", "income_tax_expense",
               "non_operating_revenue", "non_operating_expense"],
    "cash_flow": ["goods_sale_and_service_render_cash", "net_finance_cash_flow",
                  "net_invest_cash_flow", "net_operate_cash_flow"],
}
VALUATION_FIELDS = ["market_cap", "circulating_market_cap", "pcf_ratio", "ps_ratio"]

# 金融资产/负债的构成科目在新会计准则下映射不唯一，暂不臆断
FINANCIAL_ASSET_FIELDS: list[str] = []
FINANCIAL_LIABILITY_FIELDS: list[str] = []


def build(tables: dict[str, dict[str, pd.DataFrame]]) -> dict[str, pd.DataFrame]:
    """tables: {"balance": {...}, "income": {...}, "valuation": {...}}"""
    bal = tables["balance"]
    inc = tables["income"]
    val = tables["valuation"]
    ttm = tables["ttm"]
    out: dict[str, pd.DataFrame] = {}

    # ---- TTM 科目：直接取 4 季之和 ----
    for _c, _f in [("administration_expense_ttm", "administration_expense"),
                   ("asset_impairment_loss_ttm", "asset_impairment_loss"),
                   ("financial_expense_ttm", "financial_expense"),
                   ("goods_sale_and_service_render_cash_ttm", "goods_sale_and_service_render_cash"),
                   ("net_finance_cash_flow_ttm", "net_finance_cash_flow"),
                   ("net_invest_cash_flow_ttm", "net_invest_cash_flow"),
                   ("net_operate_cash_flow_ttm", "net_operate_cash_flow"),
                   ("net_profit_ttm", "net_profit"),
                   ("np_parent_company_owners_ttm", "np_parent_company_owners"),
                   ("operating_cost_ttm", "operating_cost"),
                   ("operating_profit_ttm", "operating_profit"),
                   ("operating_revenue_ttm", "operating_revenue"),
                   ("sale_expense_ttm", "sale_expense"),
                   ("total_operating_cost_ttm", "total_operating_cost"),
                   ("total_operating_revenue_ttm", "total_operating_revenue"),
                   ("total_profit_ttm", "total_profit")]:
        out[_c] = ttm[_f]
    # 毛利润 = 营业收入(TTM) - 营业成本(TTM)
    out["gross_profit_ttm"] = ttm["operating_revenue"] - ttm["operating_cost"]
    # 营业外收支净额(TTM)
    out["non_operating_net_profit_ttm"] = (ttm["non_operating_revenue"]
                                           - ttm["non_operating_expense"])
    # ⚠ EBIT 是**单期**口径（文档未写 TTM）：单季(净利+所得税+财务费用) → rel 3.2e-12 ✅
    #   TTM 版 maxerr 7.7e+10（corr 仅 0.92）❌
    out["EBIT"] = inc["net_profit"] + inc["income_tax_expense"] + inc["financial_expense"]

    # ---- 市值类：valuation 的单位是**亿元**，因子单位是**元** → ×1e8 ----
    # 实测：官方/valuation 恒为 100000000.0
    YI = 1e8
    out["market_cap"] = val["market_cap"] * YI
    out["circulating_market_cap"] = val["circulating_market_cap"] * YI

    # ---- 价格比倒数 ----
    out["cash_flow_to_price_ratio"] = 1.0 / val["pcf_ratio"].replace(0, np.nan)
    out["sales_to_price_ratio"] = 1.0 / val["ps_ratio"].replace(0, np.nan)

    # ---- 营运资本 / 留存收益 ----
    out["net_working_capital"] = bal["total_current_assets"] - bal["total_current_liability"]
    out["retained_earnings"] = bal["surplus_reserve_fund"] + bal["retained_profit"]

    # ---- 无息 / 有息流动负债 ----
    interest_free = (bal["notes_payable"] + bal["accounts_payable"] + bal["advance_peceipts"]
                     + bal["salaries_payable"] + bal["taxs_payable"] + bal["interest_payable"]
                     + bal["other_payable"] + bal["other_current_liability"])
    out["interest_free_current_liability"] = interest_free
    out["interest_carry_current_liability"] = bal["total_current_liability"] - interest_free

    # ---- 净利息费用 ----
    out["net_interest_expense"] = inc["interest_expense"] - inc["interest_income"]

    return out


NOTES: dict[str, str] = {
    "interest_carry_current_liability": (
        "已实现。覆盖率低（银行等金融类无「无息/有息」划分，官方对 000001.XSHE 直接返回 nan）。"
    ),
    "net_interest_expense": (
        "已实现（EXACT）。覆盖率 50%：金融类标的的 interest_income/interest_expense 缺失。"
    ),
    "market_cap": "已实现。注意 valuation 表单位为亿元，因子单位为元 → ×1e8。",
    "circulating_market_cap": "已实现。同 market_cap，需 ×1e8。",
}

NOTES.update({
    "value_change_profit_ttm": (
        "「价值变动净收益」在 income 表映射不唯一（fair_value_variable_income / "
        "investment_income / asset_deal_income 均可疑）→ 未实现。"
    ),
    "EBITDA": "构成科目跨表且含折旧摊销，映射不唯一 → 未实现。",
    "EBIT": "已实现（EXACT）。实测为**单期**口径（净利+所得税+财务费用），非 TTM。",
    "asset_impairment_loss_ttm": (
        "**口径部分收敛，仍 FAIL**：官方把缺失季度按 0 计入（nan_as_zero 后覆盖度 "
        "90→150、corr 0.92→**0.9998**），但量级仍系统性偏大（如 000002 我算 4.14e10 "
        "vs 官方 2.19e10，约 1.9 倍）。仅用 asset_impairment_loss 单科目不足以复现，"
        "疑官方口径含其它减值科目或采用不同期间。"
    ),
    "OperateNetIncome": "文档为「经营活动净收益/利润总额(%) × 利润总额」，中间量无直接字段 → 未实现。",
    "financial_assets": "构成含「可供出售金融资产/持有至到期投资」，新准则下映射不唯一 → 未实现。",
    "financial_liability": "文档定义被截断，有息非流动负债构成不完整 → 未实现。",
    "operating_assets": "依赖 financial_assets → 未实现。",
    "operating_liability": "依赖 financial_liability → 未实现。",
    "net_debt": "需「总债务」定义，构成科目不唯一 → 未实现。",
    "non_recurring_gain_loss": "需归母净利润与扣非净利润之差，归母字段映射不唯一 → 未实现。",
})
