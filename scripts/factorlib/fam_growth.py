#!/usr/bin/env python3
"""Growth 族（15 因子）。移植自 scripts/analyze_growth15_dual_arm_v1.py（日频化）。

数据替代声明（balancesheet 无历史，见 Addendum 2 §QC8 缺陷 3）：
- `yoy_total_asset` 改用 fina_indicator.assets_yoy（厂商预计算同比）→ B
- `yoy_net_asset`  改用 fina_indicator.bps_yoy（厂商预计算同比；原实现误赋 bps 水平值）→ B
- `asset_growth_qoq` 需总资产环比，无法从 fina_indicator 得 → 未实现 → C
- `sa` / `eaa` 官方要求加速度，本地退化为同比 → B（与原实现一致）
- `pa` 官方要求 ROA 加速度，本地为 ROA 同比差 → B（与原实现一致）
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from . import pit as P
from .context import Ctx

FAMILY = 'Growth'
PROXY = {'yoy_total_asset', 'yoy_net_asset', 'sa', 'eaa', 'pa'}

FI_COLS = ['eps', 'roa', 'roe', 'bps', 'gross_margin', 'netprofit_yoy',
           'or_yoy', 'ocf_yoy', 'total_revenue_ps', 'assets_yoy', 'bps_yoy']


def _div(a, b):
    return a / b.replace(0, np.nan)


def build(ctx: Ctx) -> dict[str, pd.DataFrame]:
    cal, syms = ctx.cal, ctx.symbols
    fi = P.load_fi(FI_COLS)
    inc = P.load_stmt('income', ['n_income_attr_p'])
    cf = P.load_stmt('cashflow', ['n_cashflow_act'])

    lag = tuple((c, k) for c in ['eps', 'roa', 'roe', 'gross_margin', 'total_revenue_ps']
                for k in (1, 4))
    fp = P.pit_panels(fi, FI_COLS, cal, syms, lag_q=lag)
    C_U = ctx.C_UNADJ
    F: dict[str, pd.DataFrame] = {}

    # 1 peg_252d: PE / (EPS 同比增速 × 100)，年报到年报
    eps, eps_y = fp['eps'], fp['eps__lag4']
    F['peg_252d'] = _div(_div(C_U, eps), (_div(eps, eps_y) - 1) * 100)

    # 2 np_ttm_qoq: 净利 TTM 环比
    q = P._quarterly(inc, ['n_income_attr_p'], ttm=('n_income_attr_p',),
                     flow=('n_income_attr_p',)).sort_values(['sym', 'end_date'])
    q['ni_ttm_prev'] = q.groupby('sym', sort=False)['n_income_attr_p__ttm'].shift(1)
    F['np_ttm_qoq'] = _div(P.daily(q, 'n_income_attr_p__ttm', cal, syms),
                           P.daily(q, 'ni_ttm_prev', cal, syms)) - 1

    # 3/4 厂商预计算同比
    F['yoy_net_profit'] = fp['netprofit_yoy'] / 100.0
    F['yoy_ocf'] = fp['ocf_yoy'] / 100.0

    # 5 sa（退化：每股营收同比）
    F['sa'] = _div(fp['total_revenue_ps'], fp['total_revenue_ps__lag4']) - 1

    # 6 毛利率环比
    F['gross_margin_qoq'] = _div(fp['gross_margin'], fp['gross_margin__lag1']) - 1

    # 7 pa（退化：ROA 同比差）
    F['pa'] = fp['roa'] - fp['roa__lag4']

    # 8 ROA 同比增速
    F['yoy_roa'] = _div(fp['roa'], fp['roa__lag4']) - 1

    # 9 净资产同比（厂商 bps_yoy；修正原实现误用 bps 水平值）
    F['yoy_net_asset'] = fp['bps_yoy'] / 100.0

    # 10 营收同比
    F['yoy_revenue'] = fp['or_yoy'] / 100.0

    # 11 ROE 同比增速
    F['yoy_roe'] = _div(fp['roe'], fp['roe__lag4']) - 1

    # 12 总资产同比（厂商 assets_yoy）
    F['yoy_total_asset'] = fp['assets_yoy'] / 100.0

    # 13 eaa（退化：EPS 同比）
    F['eaa'] = _div(eps, eps_y) - 1

    # 14 eap: EPS 增量 / 价格
    F['eap'] = _div(eps - eps_y, C_U.where(C_U > 0))

    return {k: v for k, v in F.items() if v is not None}
