#!/usr/bin/env python
"""第三轮：yoy4 的「除 |分母|」变体 + eaa/eap/sa 的日期面板变体。"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent)); sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import numpy as np, pandas as pd
import repro_quality as R, repro_quality_xs as X, ts_fin as TF
from ts_env import TSPanel
DATES = ["20240812", "20240813", "20240910", "20241105", "20241216"]

uni = X.load_universe("2024"); codes = sorted(uni)
mats = {c: TF.FinMatrix(uni[c]) for c in codes}
idx, fields = X.market_days(X.warmup_days(DATES))
P = R.build_panels(mats, codes, idx)
cidx = pd.DatetimeIndex([pd.Timestamp(d) for d in DATES])

def rp(fn): return TF.to_panel(mats, fn, idx, codes).reindex(cidx)
def sd(a, b): return a / b.replace(0, np.nan)
def y4(s): return sd(s, s.shift(4)) - 1
def y4a(s): return sd(s - s.shift(4), s.shift(4).abs())
def rs0(m, spec):
    f, per = R.PANEL_SPECS[spec]; return R._series_fn(f, per)(m)

VAR = {
 "np_to_inventory_yoy": {"div": rp(lambda m: y4(sd(rs0(m,'npp_q'), rs0(m,'inv')))),
                          "div|den|": rp(lambda m: y4a(sd(rs0(m,'npp_q'), rs0(m,'inv'))))},
 "np_to_fixed_assets_yoy": {"div": rp(lambda m: y4(sd(rs0(m,'npp_q'), rs0(m,'fixa')))),
                            "div|den|": rp(lambda m: y4a(sd(rs0(m,'npp_q'), rs0(m,'fixa'))))},
 "np_to_total_expenses_yoy": {"div": rp(lambda m: y4(sd(rs0(m,'npp_q'), rs0(m,'sellexp_q')+rs0(m,'adminexp_q')+rs0(m,'finexp_q')))),
                              "div|den|": rp(lambda m: y4a(sd(rs0(m,'npp_q'), rs0(m,'sellexp_q')+rs0(m,'adminexp_q')+rs0(m,'finexp_q'))))},
 "np_to_deferred_tax_yoy": {"div": rp(lambda m: y4(sd(rs0(m,'npp_q'), rs0(m,'dta')))),
                            "div|den|": rp(lambda m: y4a(sd(rs0(m,'npp_q'), rs0(m,'dta'))))},
 "np_to_salary_yoy": {"div": rp(lambda m: y4(sd(rs0(m,'npp_ttm'), rs0(m,'staff_ttm')))),
                      "div|den|": rp(lambda m: y4a(sd(rs0(m,'npp_ttm'), rs0(m,'staff_ttm'))))},
 "income_tax_yoy": {"div": rp(lambda m: y4(rs0(m,'tax_ttm'))), "div|den|": rp(lambda m: y4a(rs0(m,'tax_ttm')))},
 "tax_surcharge_yoy": {"div": rp(lambda m: y4(rs0(m,'biztax_ttm'))), "div|den|": rp(lambda m: y4a(rs0(m,'biztax_ttm')))},
 "expenses_to_equity_yoy": {"div": rp(lambda m: y4(sd(rs0(m,'sellexp_q')+rs0(m,'adminexp_q')+rs0(m,'finexp_q'), rs0(m,'eq_exc')))),
                            "div|den|": rp(lambda m: y4a(sd(rs0(m,'sellexp_q')+rs0(m,'adminexp_q')+rs0(m,'finexp_q'), rs0(m,'eq_exc'))))},
 "lra_yoy": {"div": rp(lambda m: y4(rs0(m,'ltr'))), "div|den|": rp(lambda m: y4a(rs0(m,'ltr')))},
 "yoy_ocf": {"sh252 div": R._div(P['ocf_ttm'], P['ocf_ttm'].shift(252))-1,
             "sh252 div|den|": R._div(P['ocf_ttm']-P['ocf_ttm'].shift(252), P['ocf_ttm'].shift(252).abs()),
             "ocf_q sh252": R._div(P['ocf_q'], P['ocf_q'].shift(252))-1},
 "icr": {"ebit/int": R._div(P['ebit_ttm'], P['intexp_ttm']),
         "op/int": R._div(P['op_ttm'], P['intexp_ttm']),
         "ebit/finexp": R._div(P['ebit_ttm'], P['finexp_ttm']),
         "npp?": None},
 "eaa": {"eps_q 252/63": (lambda s: s - s.shift(63))(R._div(P['eps_q'], P['eps_q'].shift(252))-1),
         "eps_raw 252/63": (lambda s: s - s.shift(63))(R._div(P['eps_raw'], P['eps_raw'].shift(252))-1),
         "eps_ytd 252/63": (lambda s: s - s.shift(63))(R._div(P['eps_raw'], P['eps_raw'].shift(252)).abs())},
 "eap": {"(epsq_diff)/close": R._div(P['eps_q']-P['eps_q'].shift(252), P['C_RAW']) if False else
                             R._div(P['eps_q']-P['eps_q'].shift(252), P['ta']*np.nan)},
 "sa": {"rev_q/tshare 252/63": (lambda s: s - s.shift(63))(R._div(R._div(P['rev_q'], P['tshare']), R._div(P['rev_q'], P['tshare']).shift(252))-1),
        "rev_raw/tshare 252/63": (lambda s: s - s.shift(63))(R._div(R._div(P['rev_raw'], P['tshare']), R._div(P['rev_raw'], P['tshare']).shift(252))-1),
        "rev_ttm/tshare 252/63": (lambda s: s - s.shift(63))(R._div(R._div(P['rev_ttm'], P['tshare']), R._div(P['rev_ttm'], P['tshare']).shift(252))-1)},
 "gpm_q": {"q diff": R._div(P['rev_q']-P['cost_q'], P['rev_q']),
           "q diff total_rev": R._div(P['rev_q']-P['cost_q'], P['rev_q']),
           "ttm": R._div(P['rev_ttm']-P['cost_ttm'], P['rev_ttm'])},
 "cash_profit_ratio": {"(ocf-ni)/ni": R._div(P['ocf_ttm']-P['ni_ttm'], P['ni_ttm']),
                       "ocf/ni - 1": R._div(P['ocf_ttm'], P['ni_ttm'])-1},
}
def sp_med(fac, s):
    out=[]; off_all={d: X.official_day(fac,d) for d in DATES}
    for d in DATES:
        off=off_all[d]
        if off is None or not len(off): continue
        t=pd.Timestamp(d)
        if t not in s.index: continue
        loc=s.loc[t].replace([np.inf,-np.inf],np.nan)
        both=loc.dropna().index.intersection(off.dropna().index)
        if len(both)<30 or loc[both].nunique()<2: continue
        out.append(off.reindex(both).corr(loc[both], method='spearman'))
    return (float(np.median(out)) if out else float('nan')), len(out)
for fac,cands in VAR.items():
    for name,s in cands.items():
        if s is None: continue
        s=s.replace([np.inf,-np.inf],np.nan)
        v,n=sp_med(fac,s); print(f'{fac:24s} {name:28s} sp_med={v:.5f} n={n}', flush=True)
    print(flush=True)
