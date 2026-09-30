#!/usr/bin/env python
"""quality 族（71 因子）本地复现 —— **单期科目子集**。

与 ``basics`` 族同一策略：本族绝大多数因子含 TTM（过去四季之和）或多年度基期，
受试用账号财务数据边界阻断（见 ``conventions.py`` F 段）。本模块**只实现仅依赖
「最新一期报表」的因子**——这类可以精确复现；其余留空并在 NOTES 归档原因。

已实现的单期因子及文档依据：
    current_ratio                 流动比率=流动资产合计/流动负债合计
    quick_ratio                   速动比率=(流动资产合计-存货)/流动负债合计
    super_quick_ratio             (货币资金+交易性金融资产+应收票据+应收账款+其他应收款)/流动负债合计
    debt_to_asset_ratio           负债合计/总资产
    debt_to_equity_ratio          负债合计/归属母公司所有者权益合计
    debt_to_tangible_equity_ratio 负债合计/(股东权益-商誉-无形资产)
    equity_to_asset_ratio         股东权益/总资产
    equity_to_fixed_asset_ratio   股东权益/(固定资产+工程物资)      ← 缺「在建工程」字段
    fixed_asset_ratio             (固定资产+工程物资)/总资产        ← 同上
    intangible_asset_ratio        (无形资产+研发支出+商誉)/总资产
    non_current_asset_ratio       非流动资产合计/总资产
    long_debt_to_asset_ratio      长期借款/总资产
    long_term_debt_to_asset_ratio 非流动负债合计/总资产
    long_debt_to_working_capital_ratio  非流动负债合计/(流动资产合计-流动负债合计)
    MLEV                          非流动负债合计/(非流动负债合计+总市值)
    adjusted_profit_to_total_profit  扣除非经常损益后的净利润/利润总额
"""
from __future__ import annotations

import numpy as np
import pandas as pd

FAMILY = "quality"
NEEDS_TABLES = True

BALANCE_FIELDS = [
    "total_current_assets", "total_current_liability", "inventories",
    "cash_equivalents", "trading_assets", "bill_receivable", "account_receivable",
    "other_receivable", "total_assets", "total_liability",
    "equities_parent_company_owners", "total_owner_equities",
    "good_will", "intangible_assets", "development_expenditure",
    "fixed_assets", "construction_materials",
    "total_non_current_assets", "longterm_loan", "total_non_current_liability",
]
INCOME_FIELDS = ["total_profit", "net_profit", "np_parent_company_owners"]
CASHFLOW_FIELDS = ["net_operate_cash_flow", "cash_and_equivalents_at_end"]
INDICATOR_FIELDS = ["adjusted_profit"]
VALUATION_FIELDS = ["market_cap"]
BALANCE_FIELDS += ["cash_equivalents", "account_receivable", "bill_receivable",
                   "accounts_payable", "notes_payable", "total_current_assets",
                   "equities_parent_company_owners"]
# TTM（过去四季求和）
TTM_SPEC = {
    "income": ["operating_revenue", "total_operating_revenue", "operating_cost",
               "total_operating_cost", "operating_profit", "net_profit", "total_profit",
               "sale_expense", "administration_expense", "financial_expense",
               "operating_tax_surcharges", "np_parent_company_owners"],
    "cash_flow": ["net_operate_cash_flow"],
}
# AvgQ（过去四季均值，官方记法 AvgQ(X,4,0)）
AVGQ_SPEC = {
    "balance": ["inventories", "account_receivable", "bill_receivable",
                "accounts_payable", "notes_payable", "total_current_assets",
                "total_current_liability"],
}

YI = 1e8   # valuation 单位为亿元，因子单位为元


def build(tables: dict[str, dict[str, pd.DataFrame]]) -> dict[str, pd.DataFrame]:
    bal, inc = tables["balance"], tables["income"]
    ind, val = tables["indicator"], tables["valuation"]
    out: dict[str, pd.DataFrame] = {}

    ca = bal["total_current_assets"]
    cl = bal["total_current_liability"]
    ta = bal["total_assets"]
    tl = bal["total_liability"]

    # ---- 流动性与偿债 ----
    out["current_ratio"] = ca / cl.replace(0, np.nan)
    out["quick_ratio"] = (ca - bal["inventories"]) / cl.replace(0, np.nan)
    out["super_quick_ratio"] = (
        bal["cash_equivalents"] + bal["trading_assets"] + bal["bill_receivable"]
        + bal["account_receivable"] + bal["other_receivable"]
    ) / cl.replace(0, np.nan)

    out["debt_to_asset_ratio"] = tl / ta.replace(0, np.nan)
    out["debt_to_equity_ratio"] = tl / bal["equities_parent_company_owners"].replace(0, np.nan)
    tangible = bal["total_owner_equities"] - (bal["good_will"] + bal["intangible_assets"])
    out["debt_to_tangible_equity_ratio"] = tl / tangible.replace(0, np.nan)
    out["equity_to_asset_ratio"] = bal["total_owner_equities"] / ta.replace(0, np.nan)

    # ---- 资产结构 ----
    fixed_like = bal["fixed_assets"] + bal["construction_materials"]   # 缺「在建工程」
    out["fixed_asset_ratio"] = fixed_like / ta.replace(0, np.nan)
    out["equity_to_fixed_asset_ratio"] = (
        bal["total_owner_equities"] / fixed_like.replace(0, np.nan))
    out["intangible_asset_ratio"] = (
        bal["intangible_assets"] + bal["development_expenditure"] + bal["good_will"]
    ) / ta.replace(0, np.nan)
    out["non_current_asset_ratio"] = bal["total_non_current_assets"] / ta.replace(0, np.nan)

    # ---- 长期负债 ----
    out["long_debt_to_asset_ratio"] = bal["longterm_loan"] / ta.replace(0, np.nan)
    out["long_term_debt_to_asset_ratio"] = bal["total_non_current_liability"] / ta.replace(0, np.nan)
    out["long_debt_to_working_capital_ratio"] = (
        bal["total_non_current_liability"] / (ca - cl).replace(0, np.nan))

    # ---- 市场杠杆 ----
    ncl = bal["total_non_current_liability"]
    out["MLEV"] = ncl / (ncl + val["market_cap"] * YI).replace(0, np.nan)

    # ================= TTM / AvgQ 比率 =================
    t = tables["ttm"]
    q = tables["avgq"]
    ta, tl = bal["total_assets"], bal["total_liability"]
    ocf = t["net_operate_cash_flow"]
    ocf_s = tables["cash_flow"]["net_operate_cash_flow"]   # 单季 ocf（部分比率用）

    # ---- 现金流质量 ----
    # ACCA：实测单季版更优（maxerr 2.3e-03 vs TTM 版 1.02e-01），但仍未精确
    out["ACCA"] = ocf_s / ta.replace(0, np.nan) - inc["net_profit"] / ta.replace(0, np.nan)
    out["net_operate_cash_flow_to_asset"] = ocf / ta.replace(0, np.nan)
    # ⚠ 官方在 ocf 比率上口径**不一致**，逐项实测标定（见 NOTES）：
    #   to_total_liability / coverage → 用**单季** ocf（TTM 版误差 1.36 / 2.46）
    out["net_operate_cash_flow_to_total_liability"] = ocf_s / tl.replace(0, np.nan)
    # ⚠ 分母是 **AvgQ(流动负债)**（不是期末）：TTM/AvgQ → maxerr 4.99e-07 ✅
    #   TTM/期末 0.193 ❌ ｜ 单季/AvgQ 1.243 ❌（此前漏测了「TTM/AvgQ」这一组合）
    out["net_operate_cash_flow_to_total_current_liability"] = (
        ocf / q["total_current_liability"].replace(0, np.nan))
    # ⚠ 分母是「营业**总**收入 − 营业**总**成本」（文档如此，我起初误用营业收入）：
    #   总口径 maxerr 4.62e-07 ✅ ｜ 非总口径 2.60e-02 ❌
    out["net_operate_cash_flow_to_operate_income"] = (
        ocf / (t["total_operating_revenue"] - t["total_operating_cost"]).replace(0, np.nan))
    out["net_operating_cash_flow_coverage"] = (
        ocf_s / inc["np_parent_company_owners"].replace(0, np.nan))
    out["cash_rate_of_sales"] = ocf / t["operating_revenue"].replace(0, np.nan)
    out["cfo_to_ev"] = ocf / (val["market_cap"] * YI + tl
                              - bal["cash_equivalents"]).replace(0, np.nan)

    # ---- 周转率（AvgQ 口径）----
    ar_avg = q["account_receivable"] + q["bill_receivable"]
    ap_avg = q["accounts_payable"] + q["notes_payable"]
    ar_rate = t["operating_revenue"] / ar_avg.replace(0, np.nan)
    ap_rate = t["operating_cost"] / ap_avg.replace(0, np.nan)
    inv_rate = t["operating_cost"] / q["inventories"].replace(0, np.nan)
    out["account_receivable_turnover_rate"] = ar_rate
    out["account_receivable_turnover_days"] = 360.0 / ar_rate.replace(0, np.nan)
    out["accounts_payable_turnover_rate"] = ap_rate
    out["accounts_payable_turnover_days"] = 360.0 / ap_rate.replace(0, np.nan)
    out["inventory_turnover_rate"] = inv_rate
    out["inventory_turnover_days"] = 360.0 / inv_rate.replace(0, np.nan)
    out["OperatingCycle"] = (360.0 / ar_rate.replace(0, np.nan)
                             + 360.0 / inv_rate.replace(0, np.nan))
    out["total_asset_turnover_rate"] = t["operating_revenue"] / ta.replace(0, np.nan)
    out["current_asset_turnover_rate"] = (
        t["operating_revenue"] / q["total_current_assets"].replace(0, np.nan))
    # ⚠ **文档写反了**：文档称「股东权益周转率=营业收入(ttm)/股东权益」，
    #   但官方发布的是**倒数** 股东权益/营业收入(TTM)。
    #   实测：总权益/revTTM → maxerr 1.41e-07 ✅；revTTM/总权益 → corr **-0.96** ❌
    out["equity_turnover_rate"] = (
        bal["total_owner_equities"] / t["operating_revenue"].replace(0, np.nan))

    # ---- 利润率（TTM/TTM）----
    rev, trev, cost = t["operating_revenue"], t["total_operating_revenue"], t["operating_cost"]
    out["gross_income_ratio"] = (rev - cost) / rev.replace(0, np.nan)
    out["operating_cost_to_operating_revenue_ratio"] = cost / rev.replace(0, np.nan)
    out["net_profit_ratio"] = t["net_profit"] / rev.replace(0, np.nan)
    out["net_profit_to_total_operate_revenue_ttm"] = (
        t["net_profit"] / trev.replace(0, np.nan))
    out["operating_profit_ratio"] = t["operating_profit"] / rev.replace(0, np.nan)
    out["profit_margin_ttm"] = out["operating_profit_ratio"]
    out["operating_profit_to_operating_revenue"] = (
        t["operating_profit"] / trev.replace(0, np.nan))
    out["operating_tax_to_operating_revenue_ratio_ttm"] = (
        t["operating_tax_surcharges"] / rev.replace(0, np.nan))
    out["admin_expense_rate"] = t["administration_expense"] / trev.replace(0, np.nan)
    out["financial_expense_rate"] = t["financial_expense"] / trev.replace(0, np.nan)
    out["sale_expense_to_operating_revenue"] = t["sale_expense"] / trev.replace(0, np.nan)
    out["total_profit_to_cost_ratio"] = t["total_profit"] / (
        cost + t["financial_expense"] + t["sale_expense"]
        + t["administration_expense"]).replace(0, np.nan)

    # ---- 回报率 ----
    out["roa_ttm"] = t["net_profit"] / ta.replace(0, np.nan)
    # ⚠ 文档写「净利润/期末股东权益」，实测是 **归母净利润(TTM) / 归母权益**（maxerr 4.4e-07）
    out["roe_ttm"] = (t["np_parent_company_owners"]
                      / bal["equities_parent_company_owners"].replace(0, np.nan))
    # 「流动负债合计的 12 个月均值」→ AvgQ(流动负债,4,0)
    # ⚠ 分子也取自 **cash_flow.cash_and_equivalents_at_end**（期末现金及现金等价物余额），
    #   不是 balance.cash_equivalents（货币资金）：cf 口径 maxerr 3.26e-07 ✅ ｜
    #   bs 口径 maxerr 3.045, corr 0.749 ❌（与 pershare 的同名坑一致）
    out["cash_to_current_liability"] = (
        tables["cash_flow"]["cash_and_equivalents_at_end"]
        / q["total_current_liability"].replace(0, np.nan))

    # ---- 利润结构（单期）----
    out["adjusted_profit_to_total_profit"] = (
        ind["adjusted_profit"] / inc["total_profit"].replace(0, np.nan))

    return out


NOTES: dict[str, str] = {}

_TTM_NOTE = (
    "依赖 TTM（过去四季之和）或多年度基期。试用账号财务数据只覆盖 2025Q1~Q4，"
    "四季求和与官方有 0.35%~6.26% 残差（现金流类可达 137%）→ 无法达 GOOD 档。"
    "详见 conventions.py F 段。"
)
# 含 TTM / 需历史基期的因子：全部归档为不可复现
for _c in ("DEGM", "DEGM_8y", "DSRI", "GMI", "LVGI", "OperatingCycle",
           "ROAEBITTTM", "SGAI", "SGI",
           "asset_turnover_ttm", "cfo_to_ev",
           "equity_turnover_rate", "fixed_assets_turnover_rate",
           "margin_stability", "maximum_margin",
           "net_operate_cash_flow_to_net_debt",
           "operating_profit_growth_rate", "rnoa_ttm", "roa_ttm_8y",
           "roe_ttm_8y", "roic_ttm", "DEGM_8y"):
    NOTES[_c] = ("需 8 个季度（同比基期）或多年基期，账号财务数据不足以覆盖 → 未实现。"
                 "注意 TTM 本身**可精确复现**（conventions.py F1）。")

NOTES.update({
    "fixed_asset_ratio": (
        "**结构性不可复现**：分母需（固定资产+工程物资+在建工程），但 balance 表"
        "**无 construction_in_progress 字段**，且 construction_materials（工程物资）"
        "在 6 只标的上**非空计数为 0**（整列缺失）→ 本地全 NaN。"
    ),
    "equity_to_fixed_asset_ratio": "同上：缺「在建工程」且工程物资整列缺失 → 全 NaN。",
    "equity_turnover_rate": (
        "已实现（EXACT）。⚠ **文档公式写反**：官方发布的是 股东权益/营业收入(TTM) 的倒数"
        "（maxerr 1.41e-07），而非文档的 营业收入/股东权益（该写法 corr 为 -0.96）。"
    ),
    "ACCA": (
        "**口径部分收敛，仍 FAIL**：最优变体为 单季ocf/总资产 − 单季净利/总资产。"
        "**逐标的实测 5/6 精确**（maxerr ≤2.0e-04）：002415 2.0e-04、000651 1.8e-04、"
        "000002 1.1e-04、600036 8e-05、000001 1e-05；"
        "**仅 600519 异常**（官方 mean -0.00618 vs 本地 -0.00389，maxerr 2.3e-03）→ "
        "与 MFI14 同类：单只标的异常主导聚合 maxerr。已排除 TTM/TTM(-0.16)、"
        "归母口径(0.0051)、AvgQ 分母(0.0021)。"
    ),
    "net_operate_cash_flow_to_operate_income": (
        "已实现（EXACT）。分母须用「营业**总**收入 − 营业**总**成本」；"
        "误用营业收入时 maxerr 2.6e-02。"
    ),
    "net_operate_cash_flow_to_total_current_liability": (
        "已实现（EXACT）。分母须用 **AvgQ(流动负债)**：TTM/AvgQ maxerr 4.99e-07 ✅"
        "（TTM/期末 0.193，单季/AvgQ 1.243）。"
    ),
    "cash_to_current_liability": (
        "已实现（EXACT）。分子取自 **cash_flow.cash_and_equivalents_at_end**，"
        "非 balance.cash_equivalents；分母为 AvgQ(流动负债)。"
    ),
    "intangible_asset_ratio": (
        "分母科目不齐：development_expenditure（研发支出）在 6 只标的中仅 1 只有值"
        "（70/420），其余为 NaN → 求和后全 NaN，无法与官方比对。"
    ),
    "operating_profit_to_total_profit": (
        "文档为「经营活动净收益/利润总额」，中间量「经营活动净收益」无直接字段 → 未实现。"
    ),
    "invest_income_associates_to_total_profit": (
        "需「对联营和合营企业的投资收益」，income 表映射不唯一 → 未实现。"
    ),
    "net_non_operating_income_to_total_profit": (
        "需营业外收入/支出单期值，income 表有 non_operating_revenue/expense，但口径未验证 → 未实现。"
    ),
})
