#!/usr/bin/env python
"""qdata 因子本地复现 —— Quality / Growth 两族（74 条）。

公式来源：``output/qdata_factor_repro/factor_formulas.json``（逐条实读，不靠记忆）。
输入来源：``ts_fin.py``（Tushare 四大报表，按 ``ann_date`` 构 PIT）+ ``ts_env.py``（行情/市值）。
比对引擎：``xs_compare.py``（横截面秩相关）+ ``facsim.compare``（时序绝对误差）。

════════════════════════════════════════════════════════════════════════
两族的**结构性**特征（决定了验证方法）
════════════════════════════════════════════════════════════════════════
- Quality 59 条：**51 条**公式外层是 ``CrossSectionalRank(...)``
- Growth  15 条：**12 条**外层是 ``CrossSectionalRank(...)``
- 8 条 ``passthrough=True``：公式说明里显式写「直接使用预计算字段
  ``lake.financial_derivative.*``」→ 结构性不可复现，单独归档。

``CrossSectionalRank(x) = rank_ascending(x) / N``（实测：官方单日全市场 5430 行、
min=1/N、max=1.0、mean=(N+1)/(2N)）。它是 x 的**单调变换**，所以：

- 在小样本（6 只）上，把官方值**再排序**得到 ``rank_of(official)``，
  与本地内层比值的 ``rank_of(inner)`` 逐位比 → **等价于验证内层公式的横截面次序**，
  与 N（全市场股票数）无关。这是本模块的 ``mode=ordinal`` 判据。
- 在全市场（本地离线镜像）上，可直接算 ``rank_of(inner)`` 与官方值比 → ``mode=full``。
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

_SCRIPTS = Path(__file__).resolve().parents[1]
for p in (str(_SCRIPTS), str(_SCRIPTS / "jqdata"), str(_SCRIPTS / "qdata")):
    if p not in sys.path:
        sys.path.insert(0, p)

import ts_fin as TF  # noqa: E402
from jqdata.facsim.compare import compare_family, summarize  # noqa: E402
from qdata_env import QDataClient  # noqa: E402
from ts_env import TSPanel, load_panel  # noqa: E402
from xs_compare import compare_xs, summarize_xs  # noqa: E402

FAMILY = "qdata_quality_growth"
SETTLE_DAYS_DEFAULT = 30

CODES = ["600519.SH", "000001.SZ", "000002.SZ", "600036.SH", "002415.SZ", "000651.SZ"]

# ============================================================ 字段 → 报表 =========
_CUMULATIVE_TABLES = {"income", "cashflow"}

FIELD_TABLE: dict[str, str] = {
    # --- income ---
    "revenue": "income", "total_revenue": "income", "oper_cost": "income",
    "total_cogs": "income", "operate_profit": "income", "total_profit": "income",
    "n_income": "income", "n_income_attr_p": "income", "income_tax": "income",
    "basic_eps": "income", "diluted_eps": "income", "biz_tax_surchg": "income",
    "sell_exp": "income", "admin_exp": "income", "fin_exp": "income",
    "int_exp": "income", "fin_exp_int_exp": "income", "ebit": "income",
    "ebitda": "income", "rd_exp": "income", "invest_income": "income",
    # --- cashflow ---
    "n_cashflow_act": "cashflow", "c_fr_sale_sg": "cashflow",
    "c_paid_to_for_empl": "cashflow", "c_inf_fr_operate_a": "cashflow",
    "stot_inflows_inv_act": "cashflow", "free_cashflow": "cashflow",
    # --- balancesheet（时点值）---
    "total_assets": "balancesheet", "total_liab": "balancesheet",
    "total_cur_assets": "balancesheet", "total_cur_liab": "balancesheet",
    "inventories": "balancesheet", "accounts_receiv": "balancesheet",
    "money_cap": "balancesheet", "trad_asset": "balancesheet",
    "fix_assets": "balancesheet", "defer_tax_assets": "balancesheet",
    "lt_rec": "balancesheet", "prepayment": "balancesheet",
    "adv_receipts": "balancesheet",
    "total_hldr_eqy_exc_min_int": "balancesheet",
    "total_hldr_eqy_inc_min_int": "balancesheet",
    "total_share": "balancesheet", "total_ncl": "balancesheet",
    "accounts_receiv_bill": "balancesheet", "oth_receiv": "balancesheet",
    "minority_int": "balancesheet", "cip": "balancesheet",
    "fix_assets_total": "balancesheet",
}


def is_cumulative(field: str) -> bool:
    return FIELD_TABLE.get(field, "balancesheet") in _CUMULATIVE_TABLES


# ============================================================ 口径开关 ===========
CFG: dict[str, object] = {
    # 分母：股东权益取「归母权益」还是「含少数股东权益」
    # 实测标定（roe_ttm / roe_y，6 只股票逐位 EXACT）→ **含少数股东权益**
    "EQUITY_FIELD": "total_hldr_eqy_inc_min_int",
    # ROA/ROE 分子：归母净利润 vs 净利润(含少数股东)
    # 实测标定 → **归母净利润 n_income_attr_p**
    # 实测标定（全市场横截面 Spearman @2024-08-12）：
    #   roa_ttm = n_income(TTM)/期末总资产 → 0.99999；换 n_income_attr_p 只有 0.986
    #   roe_ttm(passthrough) = n_income_attr_p(TTM)/eq_inc → 1.0000
    # ⇒ ROA 用**净利润 n_income(含少数股东)**，ROE 用**归母净利润**
    "ROA_NUM": "ni",           # npp = n_income_attr_p(归母) / ni = n_income(含少数)
    "ROE_NUM": "npp",
    # 时点量分母：期末值 vs (期初+期末)/2  —— 实测期末值精确（roe_ttm）
    "DENOM": "end",
    # 收入/成本用 revenue/oper_cost 还是 total_revenue/total_cogs
    "REVENUE_FIELD": "revenue",
    "COST_FIELD": "oper_cost",
    # _q 口径：单季（差分）vs 累计
    "Q_MODE": "single",
    # 市场数据里的 Close 口径（peg_252d / eap 用）
    "CLOSE_MODE": "raw",
}


# ============================================================ 面板构建 ===========
def _series_fn(field: str, period: str):
    cum = is_cumulative(field)

    def fn(m: TF.FinMatrix) -> pd.Series:
        if m.empty:
            return pd.Series(dtype=float)
        if period == "raw":
            return m.raw(field)
        if period == "q":
            if CFG["Q_MODE"] == "cumulative":
                return m.raw(field)
            return m.q(field, cum)
        if period == "y":
            if cum:
                v = m.raw(field)
                return v.where(m.df["end_date"].dt.month == 12)
            return m.y(field)
        if period == "ttm":
            return m.ttm(field, cum)
        if period == "avg2":
            v = m.raw(field)
            return (v + v.shift(1)) / 2.0
        if period == "prev":
            return m.raw(field).shift(1)
        raise ValueError(period)
    return fn


#: 面板规格：``key -> (字段, 口径)``。口径 ``raw/q/y/ttm/avg2`` 见 ``_series_fn``。
PANEL_SPECS: dict[str, tuple[str, str]] = {
        # 利润表
        "rev_ttm": ("revenue", "ttm"), "rev_y": ("revenue", "y"), "rev_q": ("revenue", "q"),
        "rev_raw": ("revenue", "raw"),
        "tots_rev_ttm": ("total_revenue", "ttm"),
        "cost_ttm": ("oper_cost", "ttm"), "cost_y": ("oper_cost", "y"), "cost_q": ("oper_cost", "q"),
        "cost_raw": ("oper_cost", "raw"),        # gpm_q 用累计（YTD）口径，见 build_inner 注释
        "op_ttm": ("operate_profit", "ttm"), "op_y": ("operate_profit", "y"),
        "op_q": ("operate_profit", "q"),
        "tp_ttm": ("total_profit", "ttm"), "tp_q": ("total_profit", "q"),
        "ni_ttm": ("n_income", "ttm"), "ni_q": ("n_income", "q"), "ni_y": ("n_income", "y"),
        "npp_ttm": ("n_income_attr_p", "ttm"), "npp_q": ("n_income_attr_p", "q"),
        "npp_y": ("n_income_attr_p", "y"), "npp_raw": ("n_income_attr_p", "raw"),
        "tax_ttm": ("income_tax", "ttm"), "tax_q": ("income_tax", "q"),
        "biztax_ttm": ("biz_tax_surchg", "ttm"), "biztax_q": ("biz_tax_surchg", "q"),
        "sellexp_q": ("sell_exp", "q"), "adminexp_q": ("admin_exp", "q"),
        "finexp_q": ("fin_exp", "q"), "finexp_ttm": ("fin_exp", "ttm"),
        "intexp_ttm": ("int_exp", "ttm"), "intexp_q": ("int_exp", "q"),
        "intexp2_ttm": ("fin_exp_int_exp", "ttm"),
        "ebit_ttm": ("ebit", "ttm"), "ebit_q": ("ebit", "q"),
        "ebitda_ttm": ("ebitda", "ttm"),
        "eps_raw": ("basic_eps", "raw"), "eps_ttm": ("basic_eps", "ttm"),
        "eps_y": ("basic_eps", "y"), "eps_q": ("basic_eps", "q"),
        # 现金流量表
        "ocf_ttm": ("n_cashflow_act", "ttm"), "ocf_q": ("n_cashflow_act", "q"),
        "ocf_y": ("n_cashflow_act", "y"), "ocf_raw": ("n_cashflow_act", "raw"),
        "staff_ttm": ("c_paid_to_for_empl", "ttm"),
        "salein_ttm": ("c_fr_sale_sg", "ttm"), "salein_q": ("c_fr_sale_sg", "q"),
        "operin_ttm": ("c_inf_fr_operate_a", "ttm"),
        "invin_ttm": ("stot_inflows_inv_act", "ttm"),
        # 资产负债表（时点）
        "ta": ("total_assets", "raw"), "ta_avg": ("total_assets", "avg2"),
        "tl": ("total_liab", "raw"), "tl_avg": ("total_liab", "avg2"),
        "tca": ("total_cur_assets", "raw"), "tca_avg": ("total_cur_assets", "avg2"),
        "tcl": ("total_cur_liab", "raw"), "tcl_avg": ("total_cur_liab", "avg2"),
        "inv": ("inventories", "raw"), "inv_avg": ("inventories", "avg2"),
        "ar": ("accounts_receiv", "raw"), "ar_avg": ("accounts_receiv", "avg2"),
        "arb": ("accounts_receiv_bill", "raw"),
        "cash": ("money_cap", "raw"), "trad": ("trad_asset", "raw"),
        "fixa": ("fix_assets", "raw"), "fixa_avg": ("fix_assets", "avg2"),
        "fixa_tot": ("fix_assets_total", "raw"),
        "dta": ("defer_tax_assets", "raw"), "ltr": ("lt_rec", "raw"),
        "prepay": ("prepayment", "raw"), "advr": ("adv_receipts", "raw"),
        "eq_exc": ("total_hldr_eqy_exc_min_int", "raw"),
        "eq_exc_avg": ("total_hldr_eqy_exc_min_int", "avg2"),
        "eq_inc": ("total_hldr_eqy_inc_min_int", "raw"),
        "ncl": ("total_ncl", "raw"), "tshare": ("total_share", "raw"),
        # 年报（_y）口径的时点量：passthrough 因子 debt_asset_ratio / current_ratio /
        # quick_ratio / roe_y 实测均为**年报口径**
        "ta_y": ("total_assets", "y"), "tl_y": ("total_liab", "y"),
        "tca_y": ("total_cur_assets", "y"), "tcl_y": ("total_cur_liab", "y"),
        "inv_y": ("inventories", "y"),
        "eq_inc_y": ("total_hldr_eqy_inc_min_int", "y"),
        "eq_exc_y": ("total_hldr_eqy_exc_min_int", "y"),
    }
def build_panels(mats: dict[str, TF.FinMatrix], codes: list[str],
                 dates: pd.DatetimeIndex) -> dict[str, pd.DataFrame]:
    """生成所有需要的 ``date × code`` 面板（key = ``PANEL_SPECS``）。"""
    out: dict[str, pd.DataFrame] = {}
    for name, (f, per) in PANEL_SPECS.items():
        if per == "avg2" and CFG["DENOM"] != "avg2":
            continue
        out[name] = TF.to_panel(mats, _series_fn(f, per), dates, codes)
    if CFG["DENOM"] == "avg2":
        out["ta"] = out["ta_avg"]
    return out


def _div(a: pd.DataFrame, b: pd.DataFrame) -> pd.DataFrame:
    b = b.replace(0, np.nan)
    return a / b


def equity(P: dict[str, pd.DataFrame]) -> pd.DataFrame:
    """``TotalEquity`` = 股东权益合计（**含**少数股东权益）——由 roe_ttm/roe_y 实测标定。"""
    return P["eq_inc"] if CFG["EQUITY_FIELD"] == "total_hldr_eqy_inc_min_int" else P["eq_exc"]


def equity_exc(P: dict[str, pd.DataFrame]) -> pd.DataFrame:
    """``SEWithoutMI`` = 归母股东权益（不含少数股东权益）。"""
    return P["eq_exc"]


def denom(P: dict[str, pd.DataFrame], end_key: str) -> pd.DataFrame:
    if CFG["DENOM"] == "avg2" and end_key + "_avg" in P:
        return P[end_key + "_avg"]
    return P[end_key]


# ============================================================ 内层因子定义 =======
def build_inner(P: dict[str, pd.DataFrame],
                mkt: TSPanel | None = None) -> dict[str, pd.DataFrame]:
    """返回 ``dict[因子名 -> 内层原始比值面板]``（**不含** CrossSectionalRank 包装）。"""
    adv = P["advr"]
    rev = P["rev_ttm"]                       # 营业收入（TTM）
    rev_y, rev_q = P["rev_y"], P["rev_q"]
    outp: dict[str, pd.DataFrame] = {}

    # ---- 盈利能力 ------------------------------------------------------------
    # 实测标定：roa_ttm/roe_ttm 分子 = 归母净利润(TTM)，分母 = 同报告期期末值
    roa_ttm = _div(P[CFG["ROA_NUM"] + "_ttm"], denom(P, "ta"))
    roa_y = _div(P[CFG["ROA_NUM"] + "_y"], P["ta_y"])
    roa_q = _div(P[CFG["ROA_NUM"] + "_q"], denom(P, "ta"))
    roe_ttm = _div(P[CFG["ROE_NUM"] + "_ttm"], equity(P))
    eq_y = P["eq_inc_y"] if CFG["EQUITY_FIELD"] == "total_hldr_eqy_inc_min_int" else P["eq_exc_y"]
    roe_y = _div(P[CFG["ROE_NUM"] + "_y"], eq_y)
    outp["roa_ttm"], outp["roa_y"], outp["roa_q"] = roa_ttm, roa_y, roa_q
    outp["roe_ttm"], outp["roe_y"] = roe_ttm, roe_y
    outp["roe_ttm_lag63d"] = roe_ttm.shift(63)      # 实测：= roe_ttm 滞后 63 交易日

    npm_ttm = _div(P["ni_ttm"], rev)
    npm_y = _div(P["ni_y"], rev_y)
    npm_q = _div(P["ni_q"], rev_q)
    outp["npm_ttm"], outp["npm_y"], outp["npm_q"] = npm_ttm, npm_y, npm_q
    outp["opm_ttm"] = _div(P["op_ttm"], rev)
    outp["opm_y"] = _div(P["op_y"], rev_y)
    outp["opt_tpro"] = _div(P["op_q"], P["tp_q"])

    gpm_ttm = _div(rev - P["cost_ttm"], rev)
    gpm_y = _div(rev_y - P["cost_y"], rev_y)
    # ⚠️ `gpm_q` 的 q 口径是**累计（YTD）**，不是单季差分。
    #    2026-09-21 全市场实测（5381 只 × 8 个比对日，含 4 个样本外日期）：
    #      累计(YTD) revenue → Spearman **0.99998**（min 0.99996）、名次偏差 0.93%
    #      单季(差分)       → 0.9698      TTM → 0.9699
    #    与 factor_desc 的「q 用累计单季」一致。**该修正只针对 gpm_q**，
    #    不能改全局 `CFG["Q_MODE"]`（其余 `_q` 因子已用单季口径通过验证）。
    gpm_q = _div(P["rev_raw"] - P["cost_raw"], P["rev_raw"])
    outp["gpm_ttm"], outp["gpm_y"], outp["gpm_q"] = gpm_ttm, gpm_y, gpm_q
    outp["gpm_qoq"] = _div(gpm_ttm, gpm_ttm.shift(1)) - 1     # 环比（上一披露日）
    outp["gross_margin_qoq"] = _div(gpm_ttm, gpm_ttm.shift(1)) - 1   # Growth 族同名因子

    outp["eps_ttm"], outp["eps_y"], outp["eps_q"] = P["eps_ttm"], P["eps_y"], P["eps_q"]
    outp["npm_tsh"] = _div(P["npp_ttm"], P["tshare"])

    # ---- 杠杆 / 流动性（debt_asset_ratio / current_ratio / quick_ratio
    #       实测为**年报口径** passthrough，逐位 EXACT）-------------------------
    # 实测：de 官方值是**原始比值**（非 rank），且用**年报口径** tl_y/eq_inc_y → Spearman 0.9997
    outp["de"] = _div(P["tl_y"], P["eq_inc_y"])
    outp["debt_asset_ratio"] = _div(P["tl_y"], P["ta_y"])
    outp["financial_leverage"] = _div(P["ta"], equity(P))
    outp["current_ratio"] = _div(P["tca_y"], P["tcl_y"])
    outp["quick_ratio"] = _div(P["tca_y"] - P["inv_y"], P["tcl_y"])
    outp["cash_ratio"] = _div(P["cash"] + P["trad"], denom(P, "tcl"))
    outp["delta_cash_ratio"] = outp["cash_ratio"] - outp["cash_ratio"].shift(252)
    outp["delta_current_ratio"] = outp["current_ratio"] - outp["current_ratio"].shift(252)
    outp["delta_quick_ratio"] = outp["quick_ratio"] - outp["quick_ratio"].shift(252)
    # ⚠ 与独立的 de 因子不同：delta_de 用的是**最新报告期口径** DE（0.9992），
    #   而 de 官方值是**年报口径**（0.9997）——两者口径不同，实测确认。
    _de_q = _div(P["tl"], equity(P))
    outp["delta_de"] = _de_q - _de_q.shift(252)
    outp["delta_roe"] = roe_ttm - roe_ttm.shift(252)
    outp["delta_roa"] = roa_ttm - roa_ttm.shift(252)
    outp["delta_npm"] = npm_ttm - npm_ttm.shift(252)
    outp["delta_opm"] = outp["opm_ttm"] - outp["opm_ttm"].shift(252)
    outp["delta_gpm"] = gpm_ttm - gpm_ttm.shift(252)

    # ---- 周转率 --------------------------------------------------------------
    at = _div(rev, denom(P, "ta"))
    it = _div(P["cost_ttm"], denom(P, "inv"))
    rt = _div(rev, denom(P, "ar"))
    fat = _div(rev, denom(P, "fixa"))
    et = _div(rev, equity(P))
    outp["asset_turnover"] = at
    outp["delta_asset_turnover"] = at - at.shift(252)
    outp["inventory_turnover"] = it
    outp["delta_inventory_turnover"] = it - it.shift(252)
    outp["receivable_turnover"] = rt
    outp["fixed_asset_turnover"] = fat
    outp["equity_turnover"] = et

    # ---- 现金流 --------------------------------------------------------------
    outp["cfcr"] = _div(P["ocf_ttm"], P["intexp_ttm"])
    outp["icr"] = _div(P["ebit_ttm"], P["intexp_ttm"])
    outp["cash_profit_ratio"] = _div(P["ocf_ttm"] - P["ni_ttm"], P["ni_ttm"])
    outp["yoy_ocf"] = _div(P["ocf_ttm"], P["ocf_ttm"].shift(252)) - 1

    # ---- 预收/预付 ------------------------------------------------------------
    outp["ar_ap_to_revenue"] = _div(adv - P["prepay"], rev)

    # ---- 市值杠杆 ------------------------------------------------------------
    if mkt is not None:
        mv = mkt.TOTAL_MV.reindex(index=P["ta"].index, columns=P["ta"].columns)
        outp["market_value_leverage"] = _div(mv - P["ncl"], mv)

    # ⚠ yoy4（4 披露日 = 去年同期）系列同样在 build_inner_report 里实现。
    # ⚠ ``npm_q_qoq`` / ``npm_ttm_qoq`` / ``asset_growth_qoq`` / ``np_ttm_qoq``
    #   以及 yoy4 系列都按**披露序列** shift（见 build_inner_report），不能在此实现。

    # ---- 同比（交易日口径 t-252）--------------------------------------------
    outp["yoy_roe"] = _div(roe_ttm, roe_ttm.shift(252)) - 1
    outp["yoy_roa"] = _div(roa_ttm, roa_ttm.shift(252)) - 1
    outp["yoy_total_asset"] = _div(P["ta"], P["ta"].shift(252)) - 1
    # 实测：yoy_net_asset 用**归母权益 eq_exc**（0.9996），含少数股东只有 0.9614
    outp["yoy_net_asset"] = _div(equity_exc(P), equity_exc(P).shift(252)) - 1
    outp["yoy_net_profit"] = _div(P["npp_ttm"], P["npp_ttm"].shift(252)) - 1
    outp["yoy_revenue"] = _div(rev, rev.shift(252)) - 1

    # ---- 增长加速度 ----------------------------------------------------------
    # 实测：sa 里的 ``OperatingRevenue_Q`` 实际是**累计（YTD）revenue**
    #   rev_raw 252/63 → 0.9513；rev_q（单季）只有 0.5440
    sps = _div(P["rev_raw"], P["tshare"])
    sg = _div(sps, sps.shift(252)) - 1
    outp["sa"] = sg - sg.shift(63)
    pg = roa_ttm - roa_ttm.shift(252)
    outp["pa"] = pg - pg.shift(63)
    # 实测：eaa/eap 里的 ``EPS_Q`` 实际是**累计（YTD）basic_eps**，不是单季差分
    #   eps_raw 252/63 → Spearman 0.9983；eps_q（单季）只有 0.4667
    eps_g = _div(P["eps_raw"], P["eps_raw"].shift(252)) - 1
    outp["eaa"] = eps_g - eps_g.shift(63)
    if mkt is not None:
        close = (mkt.C_RAW if CFG["CLOSE_MODE"] == "raw" else mkt.C)
        close = close.reindex(index=P["ta"].index, columns=P["ta"].columns)
        egp = _div(P["eps_raw"] - P["eps_raw"].shift(252), close)   # 同 eaa：用 YTD EPS
        outp["eap"] = egp - egp.shift(63)
        outp["peg_252d"] = _div(
            _div(close, P["eps_ttm"]),
            (_div(P["eps_ttm"], P["eps_ttm"].shift(252)) - 1) * 100)

    # ---- 质量综合（AQR QMJ，6 项求和，filter=True 剔除 nan/inf）------------
    cashflow_assets = _div(P["operin_ttm"] + P["invin_ttm"], denom(P, "ta"))
    items = [
        _div(P["op_ttm"], denom(P, "ta")),
        _div(P["ni_ttm"], equity(P)),
        _div(P["ni_ttm"], denom(P, "ta")),
        cashflow_assets,
        _div(P["op_ttm"], rev),
        _div(P["ni_ttm"], P["operin_ttm"] + P["invin_ttm"]),
    ]
    stacked = [d.replace([np.inf, -np.inf], np.nan) for d in items]
    outp["quality_composite"] = sum(d.fillna(0) for d in stacked).where(
        sum(d.notna().astype(int) for d in stacked) > 0)

    return outp


#: 公式里外层是否含 ``CrossSectionalRank(...)``
RANK_FACTORS = {
    "cfcr", "delta_cash_ratio", "lra_yoy", "np_to_fixed_assets_yoy",
    "np_to_salary_yoy", "npm_q_qoq", "npm_ttm_qoq", "roa_y", "yoy_ocf",
    "delta_inventory_turnover", "delta_roa", "fixed_asset_turnover",
    "np_ttm_qoq", "npm_ttm", "opm_ttm", "receivable_turnover", "asset_growth_qoq",
    "delta_gpm", "gpm_y", "np_to_total_expenses_yoy", "npm_tsh", "opt_tpro",
    "delta_de", "eps_ttm", "financial_leverage", "gpm_ttm", "icr",
    "income_tax_yoy", "np_to_inventory_yoy", "npm_q", "ar_ap_to_revenue",
    "asset_turnover", "delta_current_ratio", "gpm_q", "np_to_deferred_tax_yoy",
    "cash_profit_ratio", "delta_opm", "eps_q", "eps_y", "yoy_roe",
    "yoy_total_asset", "cash_ratio", "delta_asset_turnover", "delta_quick_ratio",
    "delta_roe", "gross_margin_qoq", "inventory_turnover", "pa", "roa_ttm",
    "tax_surcharge_yoy", "yoy_roa", "delta_npm", "eaa", "eap",
    "market_value_leverage", "npm_y", "opm_y", "equity_turnover",
    "expenses_to_equity_yoy", "gpm_qoq", "roa_q", "sa", "yoy_net_asset",
    "yoy_total_asset",
}


def build_inner_report(mats: dict[str, TF.FinMatrix], codes: list[str],
                       dates: pd.DatetimeIndex) -> dict[str, pd.DataFrame]:
    """**披露序列**上 shift 的因子（公式里的 ``prev_report`` / ``4披露前``）。

    ⚠ 这些因子必须先在「报告期」维度做 shift，再前向填充到交易日；
    若直接在交易日面板上 ``shift(1)`` 只等于「昨天」，在阶梯函数上几乎恒为 0。
    """
    def sd0(a: pd.Series, b: pd.Series) -> pd.Series:
        return a / b.replace(0, np.nan)

    def rs(m: TF.FinMatrix, spec: str) -> pd.Series:
        if spec == "npm_q":
            return sd0(rs(m, "ni_q"), rs(m, "rev_q"))
        if spec == "npm_ttm":
            return sd0(rs(m, "ni_ttm"), rs(m, "rev_ttm"))
        if spec == "gpm_ttm":
            return sd0(rs(m, "rev_ttm") - rs(m, "cost_ttm"), rs(m, "rev_ttm"))
        if spec == "exp3":
            return rs(m, "sellexp_q") + rs(m, "adminexp_q") + rs(m, "finexp_q")
        f, per = PANEL_SPECS[spec]
        return _series_fn(f, per)(m)

    def rp(fn) -> pd.DataFrame:
        return TF.to_panel(mats, fn, dates, codes)

    def sd(a: pd.Series, b: pd.Series) -> pd.Series:
        return a / b.replace(0, np.nan)

    def qoq(m: TF.FinMatrix, spec: str) -> pd.Series:
        x = rs(m, spec)
        return sd(x, x.shift(1)) - 1

    def yoy4(m: TF.FinMatrix, spec: str) -> pd.Series:
        x = rs(m, spec)
        return sd(x, x.shift(4)) - 1

    def npm(m: TF.FinMatrix, num: str, den: str) -> pd.Series:
        return sd(rs(m, num), rs(m, den))

    def gpm(m: TF.FinMatrix) -> pd.Series:
        return sd(rs(m, "rev_ttm") - rs(m, "cost_ttm"), rs(m, "rev_ttm"))

    def exp3(m: TF.FinMatrix) -> pd.Series:
        return rs(m, "sellexp_q") + rs(m, "adminexp_q") + rs(m, "finexp_q")

    def ratio_yoy4(m: TF.FinMatrix, num: str, den) -> pd.Series:
        a = rs(m, num)
        b = den(m) if callable(den) else rs(m, den)
        x = sd(a, b)
        return sd(x, x.shift(4)) - 1

    out: dict[str, pd.DataFrame] = {}
    # ---- 环比（上一层披露日）------------------------------------------------
    out["asset_growth_qoq"] = rp(lambda m: qoq(m, "ta"))
    out["np_ttm_qoq"] = rp(lambda m: qoq(m, "npp_ttm"))
    out["npm_q_qoq"] = rp(lambda m: qoq(m, "npm_q"))
    out["npm_ttm_qoq"] = rp(lambda m: qoq(m, "npm_ttm"))
    out["gpm_qoq"] = rp(lambda m: qoq(m, "gpm_ttm"))
    out["gross_margin_qoq"] = out["gpm_qoq"]
    # ---- 同比（前 4 个披露日 = 去年同期）------------------------------------
    out["lra_yoy"] = rp(lambda m: yoy4(m, "ltr"))
    out["income_tax_yoy"] = rp(lambda m: yoy4(m, "tax_ttm"))
    out["tax_surcharge_yoy"] = rp(lambda m: yoy4(m, "biztax_ttm"))
    out["np_to_fixed_assets_yoy"] = rp(
        lambda m: ratio_yoy4(m, "npp_q", lambda mm: rs(mm, "fixa")))
    out["np_to_inventory_yoy"] = rp(
        lambda m: ratio_yoy4(m, "npp_q", lambda mm: rs(mm, "inv")))
    out["np_to_deferred_tax_yoy"] = rp(
        lambda m: ratio_yoy4(m, "npp_q", lambda mm: rs(mm, "dta")))
    out["np_to_salary_yoy"] = rp(lambda m: ratio_yoy4(m, "npp_ttm", "staff_ttm"))
    out["np_to_total_expenses_yoy"] = rp(
        lambda m: ratio_yoy4(m, "npp_q", lambda mm: exp3(mm)))
    out["expenses_to_equity_yoy"] = rp(
        lambda m: ratio_yoy4(m, "exp3", lambda mm: rs(mm, "eq_exc")))
    return out


def xs_rank(df: pd.DataFrame) -> pd.DataFrame:
    """``CrossSectionalRank``：逐日 ``rank(升序, **max**)/N``。

    ⚠️ 并列必须取**最大名次**（``count(x_i <= x)``），不是 ``average``。
    算术证据（``yoy_ocf`` @20260811，N=4927）：官方并列块的值为 ``3642/4927``，
    而该块下方有 1875 只、块内 1767 只，``1875 + 1767 = 3642`` 恰好是块内**最大**名次；
    ``np_ttm_qoq`` 同构（并列值 ``5294/5426``）。Alpha101 族亦独立确认
    （``alpha101_33`` 的 180 只并列块：average → 2196.5 ❌，max → 2289 = 官方 ✅）。

    此前用 ``method="average"`` 是**确定性缺陷**：对并列块大的因子
    （离散输出型 uniq 仅 2~8；`yoy_ocf` 1766 只并列、`eaa` 1167、`pa` 850、`sa` 564）
    会造成整块名次偏移约半个块宽。
    """
    n = df.notna().sum(axis=1)
    return df.rank(axis=1, method="max").div(n.replace(0, np.nan), axis=0)


def all_factor_names() -> list[str]:
    import json
    meta = json.loads((Path("output/qdata_factor_repro/factor_formulas.json"))
                      .read_text(encoding="utf-8"))
    return [k for k, v in meta.items()
            if v.get("factor_type") in ("Quality", "Growth") and "_old_" not in k]


def build_local(panel: TSPanel, mats: dict[str, TF.FinMatrix],
                codes: list[str]) -> tuple[dict[str, pd.DataFrame], dict[str, pd.DataFrame]]:
    """返回 ``(local_final, local_inner)``：final 对 rank 因子做了 ``rank/N``。"""
    P = build_panels(mats, codes, panel.dates)
    inner = build_inner(P, panel)
    inner.update(build_inner_report(mats, codes, panel.dates))
    final = {k: (xs_rank(v) if k in RANK_FACTORS else v) for k, v in inner.items()}
    return final, inner


# ============================================================ 主流程 =============
COLS = ["factor", "verdict_med", "verdict", "n_overlap", "coverage",
        "max_abs_err", "med_rel_err", "corr"]


def _clean(df: pd.DataFrame) -> pd.DataFrame:
    return df.replace([np.inf, -np.inf], np.nan)


def order_agreement(local: pd.DataFrame, off: pd.DataFrame) -> tuple[int, int]:
    """逐日比较 6 只股票的名次是否完全一致（**已降级为 sanity check**）。

    ⚠️ 只有 6 个观测，功效极低；真正的判据是全市场横截面的 ``compare_xs``。
    并列取 ``method="max"`` 与 ``xs_rank`` 保持一致。
    """
    idx = local.index.intersection(off.index)
    cols = local.columns.intersection(off.columns)
    ok = tot = 0
    for t in idx:
        a = off.loc[t, cols].astype(float)
        b = local.loc[t, cols].astype(float)
        m = a.notna() & b.notna()
        if m.sum() < 3:
            continue
        ra = a[m].rank(method="max")
        rb = b[m].rank(method="max")
        ok += int((ra == rb).all())
        tot += 1
    return ok, tot


def main() -> int:
    import argparse
    ap = argparse.ArgumentParser(description="Quality/Growth 因子复现 + 比对")
    ap.add_argument("--codes", nargs="*", default=CODES)
    ap.add_argument("--start", default="2026-06-01")
    ap.add_argument("--end", default="2026-09-10")
    ap.add_argument("--lookback", default="2024-06-01",
                    help="行情面板起点（需覆盖 252 交易日回看）")
    ap.add_argument("--fin-start", default="20200101",
                    help="财务数据取数起点（需覆盖 TTM 的上年同期）")
    ap.add_argument("--settle-days", type=int, default=SETTLE_DAYS_DEFAULT)
    ap.add_argument("--outdir", default="output/qdata_factor_repro")
    args = ap.parse_args()

    factors = all_factor_names()
    panel = load_panel(args.codes, args.lookback, args.end)
    tabs = TF.load_all(args.codes, args.fin_start, args.end.replace("-", ""))
    mats = TF.build_matrices(tabs, args.codes)
    local, inner = build_local(panel, mats, args.codes)
    missing = [f for f in factors if f not in local]
    if missing:
        print(f"  ⚠ 未实现 {len(missing)}: {missing}")
    local = {f: local[f] for f in factors if f in local}

    from qg_official import load_official
    s8, e8 = args.start.replace("-", ""), args.end.replace("-", "")
    official = load_official(factors, args.codes, s8, e8)
    # 横截面因子：对官方值再做一次 6 只样本内的 rank（等价于验证内层比值的横截面次序）
    off_cmp = {f: (_clean(xs_rank(_clean(v))) if f in RANK_FACTORS else v)
               for f, v in official.items()}
    loc_cmp = {f: _clean(v) for f, v in local.items()}
    inner_cmp = {f: _clean(v) for f, v in inner.items()}

    outdir = Path(args.outdir)
    outdir.mkdir(parents=True, exist_ok=True)

    def show(title: str, loc: dict, off: dict, tag: str) -> pd.DataFrame:
        print(f"\n===== {title} =====")
        d = compare_family(FAMILY, loc, off, factors)
        with pd.option_context("display.width", 220):
            print(d[COLS].to_string(index=False, float_format=lambda x: f"{x:.4g}"))
        print("\n" + summarize(d))
        if tag:
            p = outdir / f"quality_growth_compare_smallsample{tag}.csv"
            d.to_csv(p, index=False)
            print(f"报告: {p}")
        return d

    d_full = show("全窗口（含 qdata 未沉淀尾部）", loc_cmp, off_cmp, "")

    d_set = None
    if args.settle_days > 0:
        cut = pd.Timestamp(args.end) - pd.Timedelta(days=args.settle_days)
        print(f"\n[settle] 排除 {cut.date()} 之后的 {args.settle_days} 个自然日")
        d_set = show(f"已沉淀窗口（--settle-days {args.settle_days}，判定口径）",
                     {k: v.loc[:cut] for k, v in loc_cmp.items()},
                     {k: v.loc[:cut] for k, v in off_cmp.items()}, "_settled")

    # ---- 横截面因子的「名次完全一致」硬判据 ---------------------------------
    print("\n===== rank 因子 6 只样本内「名次完全一致」天数占比 =====")
    rows = []
    for f in factors:
        if f not in RANK_FACTORS:
            continue
        ok, tot = order_agreement(loc_cmp.get(f, pd.DataFrame()),
                                  off_cmp.get(f, pd.DataFrame()))
        ok2, tot2 = order_agreement(
            loc_cmp.get(f, pd.DataFrame()).loc[:pd.Timestamp(args.end) - pd.Timedelta(days=args.settle_days)],
            off_cmp.get(f, pd.DataFrame()).loc[:pd.Timestamp(args.end) - pd.Timedelta(days=args.settle_days)])
        rows.append(dict(factor=f, days=ok, days_total=tot,
                         days_settled=ok2, days_settled_total=tot2))
    od = pd.DataFrame(rows)
    with pd.option_context("display.width", 200):
        print(od.to_string(index=False))
    od.to_csv(outdir / "quality_growth_rank_order.csv", index=False)

    # ---- 内层比值（已通过 rank 验证的情况下，供后续全市场复算）--------------
    if d_set is not None and not d_set.empty:
        d_set.to_csv(outdir / "quality_growth_compare_smallsample_settled.csv", index=False)
    print(f"\n产出: {outdir}/quality_growth_compare_smallsample[_settled].csv / "
          f"quality_growth_rank_order.csv")
    print("⚠ 本表为 6 只样本股上的**横截面内次序**核验（弱判据，仅作 sanity check）；")
    print("   权威判据见 repro_quality_xs.py 产出的全市场 quality_growth_compare.csv")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
