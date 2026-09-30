#!/usr/bin/env python3
"""Value 族（11 因子）。移植自 scripts/analyze_value11_dual_arm_v1.py（日频化）。

代理声明：dividend_yield_3y_avg 用 dv_ttm 12 个月均值（B 类）。
C 类 fcf_to_market / ncf_to_market 未实现（与 ocf_to_market 同值，已被审计剔除）。
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from . import pit as P
from .context import Ctx
from .ops import mad_clip

FAMILY = 'Value'
PROXY = {'dividend_yield_3y_avg', 'book_to_market'}


def _div(a, b):
    return a / b.replace(0, np.nan)


def _asof_daily(frame: pd.DataFrame, value_col: str, cal: pd.DatetimeIndex,
                symbols: list[str]) -> pd.DataFrame:
    w = frame.pivot_table(index='available_date', columns='sym', values=value_col,
                          aggfunc='last')
    w = w.reindex(columns=symbols).sort_index()
    return P._asof(w, cal).astype('float32')


def build(ctx: Ctx) -> dict[str, pd.DataFrame]:
    cal, syms = ctx.cal, ctx.symbols
    inc = P.load_stmt('income', ['n_income_attr_p', 'total_revenue'])
    cf = P.load_stmt('cashflow', ['n_cashflow_act'])
    fi = P.load_fi(['profit_dedt', 'ebitda', 'eps', 'bps'])

    ip = P.pit_panels(inc, ['n_income_attr_p', 'total_revenue'], cal, syms,
                      ttm=('n_income_attr_p',), flow=('n_income_attr_p', 'total_revenue'))
    cfp = P.pit_panels(cf, ['n_cashflow_act'], cal, syms,
                       ttm=('n_cashflow_act',), flow=('n_cashflow_act',))
    fip = P.pit_panels(fi, ['profit_dedt', 'ebitda', 'eps', 'bps'], cal, syms,
                       ttm=('profit_dedt',), flow=('profit_dedt',))

    mcap = ctx.total_share * 1e4 * ctx.C_UNADJ
    F: dict[str, pd.DataFrame] = {}
    F['earnings_to_price'] = _div(ip['n_income_attr_p__ttm'], mcap)
    # book_to_market（代理）：balancesheet 在本库无权益列（recent_3tables 仅 4 列），
    # 改用 fina_indicator 的 bps / 未复权价，等价于 equity/mcap（省略递延所得税资产）
    F['book_to_market'] = _div(fip['bps'], ctx.C_UNADJ.where(ctx.C_UNADJ > 0))
    F['earnings_cut_to_market'] = _div(fip['profit_dedt__ttm'], mcap)
    F['ocf_to_market'] = _div(cfp['n_cashflow_act__ttm'], mcap)
    F['ebitda_to_market'] = _div(fip['ebitda'], mcap)
    F['sales_to_market'] = mad_clip(_div(ip['total_revenue__q'], mcap))

    # etp5: 5 年年均净利 / 当前市值
    ann = inc[inc['end_date'].dt.month == 12].sort_values(['sym', 'end_date']).copy()
    ann['ni5'] = ann.groupby('sym')['n_income_attr_p'].rolling(5, min_periods=5).mean() \
        .reset_index(level=0, drop=True)
    F['etp5'] = _div(_asof_daily(ann, 'ni5', cal, syms), mcap)

    # pegh5: -(价格 / (5年EPS复合增速 × EPS))
    ea = fi[fi['end_date'].dt.month == 12].sort_values(['sym', 'end_date']).copy()
    ea['eps_l5'] = ea.groupby('sym')['eps'].shift(5)
    r = (ea['eps'] / ea['eps_l5'].replace(0, np.nan)).abs() ** 0.2 - 1
    ea['denom'] = np.sign(ea['eps']) * r * ea['eps']
    F['pegh5'] = -_div(ctx.C_UNADJ, _asof_daily(ea, 'denom', cal, syms))

    # dividend_yield_3y_avg（代理：dv_ttm 12 个月均值，245 交易日）
    F['dividend_yield_3y_avg'] = ctx.dv_ttm.rolling(245, min_periods=60).mean()

    return {k: v for k, v in F.items() if v is not None}
