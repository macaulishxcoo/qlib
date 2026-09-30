#!/usr/bin/env python3
"""Quality 族（官方 59；本实现 30 个可算因子）。

数据替代声明（balancesheet 无历史，见 Addendum 2 §QC8 缺陷 3）：
- 权益     = fina_indicator.bps × 总股本
- 总资产   = 权益 / (1 − debt_to_assets/100)   ← 资产负债率恒等式反推
- 周转率类 直接用 fina_indicator 的厂商周转率（assets_turn / fa_turn / ar_turn）→ B
- `*_ttm` 水平比率（roe/roa/gross_margin/netprofit_margin）为 fina_indicator 的
  **YTD 口径**，非 TTM → B；`eps_ttm` 经去累计化后为真 TTM → A
- `inventory_turnover` 无任何数据源 → 未实现 → C
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from . import pit as P
from .context import Ctx
from .ops import mad_clip

FAMILY = 'Quality'
PROXY = {'gpm_ttm', 'npm_ttm', 'roe_ttm', 'roa_ttm', 'asset_turnover',
         'fixed_asset_turnover', 'receivable_turnover', 'equity_turnover',
         'npm_tsh', 'quality_composite4', 'delta_de'}
UNIMPLEMENTED = {'inventory_turnover'}

FI = ['roe', 'roa', 'gross_margin', 'netprofit_margin', 'current_ratio', 'quick_ratio',
      'cash_ratio', 'debt_to_assets', 'eps', 'bps', 'assets_turn', 'fa_turn', 'ar_turn']
INC = ['total_revenue', 'operate_profit', 'total_profit', 'fin_exp', 'n_income_attr_p']
LAG1 = tuple((c, 1) for c in FI)
LAG4 = tuple((c, 4) for c in FI)


def _div(a, b):
    return a / b.replace(0, np.nan)


def build(ctx: Ctx) -> dict[str, pd.DataFrame]:
    cal, syms = ctx.cal, ctx.symbols
    fi = P.load_fi(FI)
    inc = P.load_stmt('income', INC)
    cf = P.load_stmt('cashflow', ['n_cashflow_act'])

    fp = P.pit_panels(fi, FI, cal, syms, lag_q=LAG1 + LAG4)
    ip = P.pit_panels(inc, INC, cal, syms, flow=tuple(INC),
                      ttm=('total_revenue', 'operate_profit', 'total_profit',
                           'n_income_attr_p', 'fin_exp'))
    cfp = P.pit_panels(cf, ['n_cashflow_act'], cal, syms,
                       flow=('n_cashflow_act',), ttm=('n_cashflow_act',))
    eq = P._quarterly(fi, ['eps'], ttm=('eps',), flow=('eps',)).sort_values(['sym', 'end_date'])
    eps_ttm = P.daily(eq, 'eps__ttm', cal, syms)

    ni_ttm = ip['n_income_attr_p__ttm']
    ocf_ttm = cfp['n_cashflow_act__ttm']
    shares = ctx.total_share * 1e4
    equity = fp['bps'] * shares
    dta = fp['debt_to_assets'] / 100.0
    assets = _div(equity, (1 - dta))
    rev_ttm = ip['total_revenue__ttm']

    F: dict[str, pd.DataFrame] = {}
    F['debt_asset_ratio'] = fp['debt_to_assets']
    F['quick_ratio'] = fp['quick_ratio']
    F['cash_ratio'] = fp['cash_ratio']
    F['current_ratio'] = fp['current_ratio']
    F['gpm_ttm'] = fp['gross_margin']
    F['npm_ttm'] = fp['netprofit_margin']
    F['roe_ttm'] = fp['roe']
    F['roa_ttm'] = fp['roa']
    F['eps_ttm'] = eps_ttm

    F['gpm_qoq'] = _div(fp['gross_margin'], fp['gross_margin__lag1']) - 1
    F['npm_q_qoq'] = _div(fp['netprofit_margin'], fp['netprofit_margin__lag1']) - 1

    F['delta_gpm'] = fp['gross_margin'] - fp['gross_margin__lag4']
    F['delta_npm'] = fp['netprofit_margin'] - fp['netprofit_margin__lag4']
    F['delta_roe'] = fp['roe'] - fp['roe__lag4']
    F['delta_roa'] = fp['roa'] - fp['roa__lag4']
    F['delta_quick_ratio'] = fp['quick_ratio'] - fp['quick_ratio__lag4']
    F['delta_current_ratio'] = fp['current_ratio'] - fp['current_ratio__lag4']
    F['delta_cash_ratio'] = fp['cash_ratio'] - fp['cash_ratio__lag4']
    F['delta_de'] = fp['debt_to_assets'] - fp['debt_to_assets__lag4']

    F['opt_tpro'] = _div(ip['operate_profit__q'], ip['total_profit__q'])
    F['opm_y'] = _div(ip['operate_profit__q'], ip['total_revenue__q'])
    F['icr'] = _div(ip['operate_profit__q'], ip['fin_exp__q'])
    F['cfcr'] = _div(ocf_ttm, ip['fin_exp__ttm'])
    F['cash_profit_ratio'] = _div(ocf_ttm - ni_ttm, ni_ttm)

    F['asset_turnover'] = fp['assets_turn']
    F['fixed_asset_turnover'] = fp['fa_turn']
    F['receivable_turnover'] = fp['ar_turn']
    F['equity_turnover'] = _div(rev_ttm, equity)
    F['npm_tsh'] = _div(ni_ttm, equity)
    F['de'] = _div(dta, (1 - dta))

    comp = None
    for q in [_div(ip['total_profit__ttm'], assets), _div(ni_ttm, equity),
              _div(ni_ttm, assets), _div(ocf_ttm, assets)]:
        q = mad_clip(q.replace([np.inf, -np.inf], np.nan))
        comp = q if comp is None else comp + q
    F['quality_composite4'] = comp

    return {k: v.replace([np.inf, -np.inf], np.nan) for k, v in F.items() if v is not None}
