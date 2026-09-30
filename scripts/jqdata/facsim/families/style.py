#!/usr/bin/env python
"""style 族（CNE5，30 因子）本地复现 —— **仅近似**（目标即如此）。

文档给出的 style 定义分两层：
  ① 10 个**合成风格因子**（size/beta/momentum/... ）= 描述因子的加权和；
  ② 20 个**描述因子**（natural_log_of_market_cap / raw_beta / ...）。

但官方发布的 ``get_factor_values`` 值是**经过整套预处理**后的暴露度，文档 §风格因子
数据处理说明 写明了链路但**未给参数**：
    去极值(2.5σ 截断) → 市值加权标准化 → 按聚宽一级行业回归填缺失 → 对 beta/size 正交化
因此即便描述因子算得完全正确，**合成因子也不会数值一致**——这是本族"仅近似"的根源。

本模块只实现**数据可及**的部分；受阻项逐条归档于 NOTES：
  ✅ 可算（当期价量即可）：
     natural_log_of_market_cap、debt_to_assets、book_to_price_ratio、
     share_turnover_monthly、average_share_turnover_quarterly、
     market_leverage、book_leverage
  ❌ 窗口不足（需 252/504 日，账号仅 372 日、面板 177 日）：
     raw_beta、daily_standard_deviation、historical_sigma、cumulative_range、
     average_share_turnover_annual、relative_strength
  ❌ 需分析师一致预期（本地无此数据）：
     predicted_earnings_to_price_ratio、long/short_term_predicted_earnings_growth
  ❌ 需 5 年财务基期：earnings_growth、sales_growth
  ❌ 需 TTM 现金流：cash_earnings_to_price_ratio
  ❌ 需标准化后处理：cube_of_size
"""
from __future__ import annotations

import numpy as np
import pandas as pd

FAMILY = "style"
NEEDS_TABLES = True
NEEDS_FUND = True

BALANCE_FIELDS = ["total_liability", "total_assets", "longterm_loan",
                  "preferred_shares_equity", "equities_parent_company_owners"]
VALUATION_FIELDS = ["market_cap", "pb_ratio"]
INCOME_FIELDS: list[str] = []
FUND_FIELDS = ["turnover_ratio"]

YI = 1e8   # valuation 单位为亿元


def build(tables: dict[str, dict[str, pd.DataFrame]],
          fund: dict[str, pd.DataFrame] | None = None) -> dict[str, pd.DataFrame]:
    bal, val = tables["balance"], tables["valuation"]
    T = (fund or {})["turnover_ratio"]
    out: dict[str, pd.DataFrame] = {}

    mktcap = val["market_cap"] * YI          # 元
    out["natural_log_of_market_cap"] = np.log(mktcap.where(mktcap > 0))
    out["debt_to_assets"] = bal["total_liability"] / bal["total_assets"].replace(0, np.nan)
    out["book_to_price_ratio"] = 1.0 / val["pb_ratio"].replace(0, np.nan)

    # 换手率类（描述因子原文均要求「取对数」）
    # ⚠ 实测：官方先把换手率换算成**小数**（/100）再取对数。
    #   share_turnover_monthly 的 maxerr 恒为 4.605171 = ln(100)，corr=1.0 → 纯量纲差。
    Tf = T / 100.0
    out["share_turnover_monthly"] = np.log(Tf.rolling(21).sum().where(lambda x: x > 0))
    # ⚠ 「过去 3 个月平均换手率」= **3 个月度换手率之和的均值**，不是 63 日均值。
    #   数学等价于 sum(63)/3。实测：ln(mean63) 差 ln(21)=3.0445 恒定；
    #   ln(sum63/3) → maxerr 4.91e-07 ✅
    out["average_share_turnover_quarterly"] = np.log(
        (Tf.rolling(63).sum() / 3.0).where(lambda x: x > 0))
    # 年度同理 = sum(252)/12（窗口不足，仍不可算）
    out["average_share_turnover_annual"] = np.log(
        (Tf.rolling(252).sum() / 12.0).where(lambda x: x > 0))

    # 杠杆类：(普通股市值/账面 + 优先股账面 + 长期债务) / 普通股市值/账面
    pref = bal["preferred_shares_equity"].fillna(0)
    ltd = bal["longterm_loan"].fillna(0)
    book_eq = bal["equities_parent_company_owners"]
    out["market_leverage"] = (mktcap + pref + ltd) / mktcap.replace(0, np.nan)
    out["book_leverage"] = (book_eq + pref + ltd) / book_eq.replace(0, np.nan)

    # ---- 合成因子：按文档权重合成「描述因子原始值」（未经预处理，故仅近似）----
    out["size"] = out["natural_log_of_market_cap"]
    out["non_linear_size"] = out["natural_log_of_market_cap"] ** 3
    out["liquidity"] = (0.35 * out["share_turnover_monthly"]
                        + 0.35 * out["average_share_turnover_quarterly"]
                        + 0.30 * out["average_share_turnover_quarterly"])
    out["leverage"] = (0.38 * out["market_leverage"]
                       + 0.35 * out["debt_to_assets"]
                       + 0.27 * out["book_leverage"])
    return out


NOTES: dict[str, str] = {
    "average_share_turnover_annual": (
        "已按「12 个月度换手率之和的均值 = sum(252)/12」实现，但需 252 日窗口，"
        "面板仅 177 日 → 窗口不足。"
    ),
    "book_to_price_ratio": (
        "文档称「pb_ratio 的倒数」，但 1/pb_ratio 与原值 corr 仅 0.88 → 口径不符，未收敛。"
    ),
    "debt_to_assets": (
        "corr=0.99997、maxerr 7.2e-03。疑似官方对该描述因子也做了截断/标准化，未收敛。"
    ),
    "market_leverage": "覆盖率仅 25%（多数标的无优先股/长期借款科目），corr 0.20，未收敛。",
    "book_leverage": "覆盖率仅 25%，存在 0.31 的恒定偏移，未收敛。",
    "leverage": "依赖 market_leverage/book_leverage → 未收敛。",
}

_PREP = (
    "**仅近似**：官方发布值是经「去极值→市值加权标准化→行业回归填缺失→正交化」"
    "处理后的暴露度，文档未给该链路的参数 → 即便描述因子算对，数值也不会一致。"
)
_WINDOW = (
    "**窗口不足**：需 252/504 个交易日，试用账号窗口仅 372 日、本地面板 177 日 → "
    "结构性不可算（与 EMAC120 同源问题）。"
)
_ANALYST = "**数据不可及**：需分析师一致预期（未来 12 个月/1 年/3 年净利预测），本地无此数据。"
_FIN = "**财务基期不可及**：需 5 年财务history，账号仅覆盖 2025 年 → 不可算。"

NOTES.update({
    "raw_beta": _WINDOW, "daily_standard_deviation": _WINDOW, "historical_sigma": _WINDOW,
    "cumulative_range": _WINDOW, "average_share_turnover_annual": _WINDOW,
    "relative_strength": _WINDOW,
    "beta": _WINDOW, "momentum": _WINDOW, "residual_volatility": _WINDOW,
    "predicted_earnings_to_price_ratio": _ANALYST,
    "long_term_predicted_earnings_growth": _ANALYST,
    "short_term_predicted_earnings_growth": _ANALYST,
    "earnings_yield": _ANALYST, "growth": _ANALYST,
    "earnings_growth": _FIN, "sales_growth": _FIN,
    "cash_earnings_to_price_ratio": "需 TTM 净经营现金流，受财务 TTM 边界阻断（见 conventions F 段）。",
    "earnings_to_price_ratio": "需 TTM 归母净利润，受财务 TTM 边界阻断。",
    "cube_of_size": "需先对标准化后的 size 暴露求立方再正交化，链路参数未知 → 不可算。",
})
