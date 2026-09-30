#!/usr/bin/env python
"""全市场口径变体调参（单日，用于标定失败因子）。"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent)); sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import numpy as np, pandas as pd
import repro_quality_xs as X, repro_quality as R, ts_fin as TF
from ts_env import TSPanel

DATE = sys.argv[1] if len(sys.argv) > 1 else '20240812'

uni = X.load_universe('2024', None); codes = sorted(uni)
mats = {c: TF.FinMatrix(uni[c]) for c in codes}
idx, fields = X.market_days([DATE])
panel = TSPanel(codes=codes, fields=fields)
P = R.build_panels(mats, codes, idx)
inner = R.build_inner(P, panel); inner.update(R.build_inner_report(mats, codes, idx))
print(f'# universe {len(codes)} date {DATE}')

def sp(fac, s):
    off = X.official_day(fac, DATE)
    if off is None or not len(off):
        return float('nan'), 0
    loc = s.iloc[0].replace([np.inf, -np.inf], np.nan)
    both = loc.dropna().index.intersection(off.dropna().index)
    return off.reindex(both).corr(loc.reindex(both), method='spearman'), len(both)

TESTS = {
 'de': [('tl/eq_inc', R._div(P['tl'], P['eq_inc'])), ('tl/eq_exc', R._div(P['tl'], P['eq_exc'])),
        ('tl_y/eq_inc_y', R._div(P['tl_y'], P['eq_inc_y'])), ('tl_y/eq_exc_y', R._div(P['tl_y'], P['eq_exc_y'])),
        ('tl/(ta-tl)', R._div(P['tl'], P['ta'] - P['tl']))],
 'icr': [('ebit_ttm/int_ttm', R._div(P['ebit_ttm'], P['intexp_ttm'])),
         ('ebit_ttm/int2_ttm', R._div(P['ebit_ttm'], P['intexp2_ttm'])),
         ('(op+finexp)/int_ttm', R._div(P['op_ttm'] + P['finexp_ttm'], P['intexp_ttm'])),
         ('(op+finexp)/int2_ttm', R._div(P['op_ttm'] + P['finexp_ttm'], P['intexp2_ttm']))],
 'cfcr': [('ocf/int_ttm', R._div(P['ocf_ttm'], P['intexp_ttm'])),
          ('ocf/int2_ttm', R._div(P['ocf_ttm'], P['intexp2_ttm']))],
 'receivable_turnover': [('rev/ar', R._div(P['rev_ttm'], P['ar'])),
                         ('rev/(ar+arb)', R._div(P['rev_ttm'], P['ar'] + P['arb'])),
                         ('rev/arb', R._div(P['rev_ttm'], P['arb']))],
 'quality_composite': [('v_ni', inner['quality_composite'])],
 'yoy_net_profit': [('npp_ttm sh252', inner['yoy_net_profit']),
                    ('ni_ttm sh252', R._div(P['ni_ttm'], P['ni_ttm'].shift(252)) - 1),
                    ('npp_y sh252', R._div(P['npp_y'], P['npp_y'].shift(252)) - 1)],
 'yoy_ocf': [('ocf_ttm sh252', inner['yoy_ocf'])],
 'income_tax_yoy': [('yoy4 report', inner['income_tax_yoy']),
                    ('sh252', R._div(P['tax_ttm'], P['tax_ttm'].shift(252)) - 1)],
 'tax_surcharge_yoy': [('yoy4 report', inner['tax_surcharge_yoy']),
                       ('sh252', R._div(P['biztax_ttm'], P['biztax_ttm'].shift(252)) - 1)],
 'npm_ttm_qoq': [('report qoq', inner['npm_ttm_qoq']), ('trading sh1', R._div(R._div(P['ni_ttm'],P['rev_ttm']), R._div(P['ni_ttm'],P['rev_ttm']).shift(1)) - 1)],
 'asset_growth_qoq': [('report qoq', inner['asset_growth_qoq']), ('trading sh1', R._div(P['ta'], P['ta'].shift(1)) - 1)],
 'np_ttm_qoq': [('report qoq', inner['np_ttm_qoq']), ('trading sh1', R._div(P['npp_ttm'], P['npp_ttm'].shift(1)) - 1)],
 'yoy_net_asset': [('eq_inc sh252', inner['yoy_net_asset']), ('eq_exc sh252', R._div(P['eq_exc'], P['eq_exc'].shift(252)) - 1)],
 'np_to_fixed_assets_yoy': [('npp_q/fixa yoy4', inner['np_to_fixed_assets_yoy']),
                            ('npp_ttm/fixa yoy4', R._div(R._div(P['npp_ttm'], P['fixa']), R._div(P['npp_ttm'], P['fixa']).shift(4)) - 1)],
 'np_to_deferred_tax_yoy': [('npp_q/dta yoy4', inner['np_to_deferred_tax_yoy'])],
 'np_to_salary_yoy': [('npp_ttm/staff yoy4', inner['np_to_salary_yoy'])],
 'np_to_inventory_yoy': [('npp_q/inv yoy4', inner['np_to_inventory_yoy'])],
 'gpm_qoq': [('report qoq', inner['gpm_qoq'])],
 'expenses_to_equity_yoy': [('exp3/eq_exc yoy4', inner['expenses_to_equity_yoy']),
                            ('exp3/eq_inc yoy4', None)],
 'peg_252d': [('close raw', inner['peg_252d'])],
 'sa': [('q/tshare', inner['sa'])],
 'eaa': [('eps_q', inner['eaa'])],
 'eap': [('eps_q/close', inner['eap'])],
 'pa': [('roa_ttm', inner['pa'])],
 'yoy_revenue': [('rev_ttm sh252', inner['yoy_revenue'])],
}
for fac, cands in TESTS.items():
    for name, s in cands:
        if s is None:
            continue
        v, n = sp(fac, s)
        print(f'{fac:24s} {name:26s} sp={v:.5f} n={n}', flush=True)
    print(flush=True)
