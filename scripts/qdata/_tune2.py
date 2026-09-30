#!/usr/bin/env python
"""第二轮口径标定：对全市场横截面仍未达标的因子试变体（多日中位 Spearman）。"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

import repro_quality as R  # noqa: E402
import repro_quality_xs as X  # noqa: E402
import ts_fin as TF  # noqa: E402
from ts_env import TSPanel  # noqa: E402

DATES = ["20240812", "20240813", "20240910", "20241105", "20241216"]


def main() -> int:
    uni = X.load_universe("2024")
    codes = sorted(uni)
    mats = {c: TF.FinMatrix(uni[c]) for c in codes}
    all_days = X.warmup_days(DATES)
    idx, fields = X.market_days(all_days)
    panel = TSPanel(codes=codes, fields=fields)
    P = R.build_panels(mats, codes, idx)
    cidx = pd.DatetimeIndex([pd.Timestamp(d) for d in DATES])
    print(f"universe {len(codes)} days {len(all_days)}", flush=True)

    def rs0(m, spec):
        if spec == "npm_q":
            return sd(rs0(m, "ni_q"), rs0(m, "rev_q"))
        f, per = R.PANEL_SPECS[spec]
        return R._series_fn(f, per)(m)

    def sd(a, b):
        return a / b.replace(0, np.nan)

    def rp(fn):
        return TF.to_panel(mats, fn, idx, codes).reindex(cidx)

    def ratio_report(m, num, den):
        a = rs0(m, num)
        b = rs0(m, den) if isinstance(den, str) else den(m)
        return sd(a, b)

    def yoy4_series(s):
        return sd(s, s.shift(4)) - 1

    VAR = {
        "np_to_inventory_yoy": {
            "npp_q/inv yoy4": rp(lambda m: yoy4_series(ratio_report(m, "npp_q", "inv"))),
            "npp_ttm/inv yoy4": rp(lambda m: yoy4_series(ratio_report(m, "npp_ttm", "inv"))),
            "npp_y/inv yoy4": rp(lambda m: yoy4_series(ratio_report(m, "npp_y", "inv"))),
            "ni_q/inv yoy4": rp(lambda m: yoy4_series(ratio_report(m, "ni_q", "inv"))),
        },
        "np_to_fixed_assets_yoy": {
            "npp_q/fixa yoy4": rp(lambda m: yoy4_series(ratio_report(m, "npp_q", "fixa"))),
            "npp_ttm/fixa yoy4": rp(lambda m: yoy4_series(ratio_report(m, "npp_ttm", "fixa"))),
            "npp_q/fixa_total yoy4": rp(lambda m: yoy4_series(
                sd(rs0(m, "npp_q"), rs0(m, "fixa") + m.raw("cip")))),
        },
        "np_to_salary_yoy": {
            "npp_ttm/staff yoy4": rp(lambda m: yoy4_series(ratio_report(m, "npp_ttm", "staff_ttm"))),
            "npp_q/staff_ttm yoy4": rp(lambda m: yoy4_series(ratio_report(m, "npp_q", "staff_ttm"))),
            "npp_ttm/staff_q yoy4": rp(lambda m: yoy4_series(
                sd(rs0(m, "npp_ttm"), R._series_fn("c_paid_to_for_empl", "q")(m)))),
        },
        "np_to_total_expenses_yoy": {
            "npp_q/exp3 yoy4": rp(lambda m: yoy4_series(ratio_report(
                m, "npp_q", lambda mm: rs0(mm, "sellexp_q") + rs0(mm, "adminexp_q") + rs0(mm, "finexp_q")))),
            "npp_ttm/exp3_ttm yoy4": rp(lambda m: yoy4_series(sd(
                rs0(m, "npp_ttm"),
                R._series_fn("sell_exp", "ttm")(m) + R._series_fn("admin_exp", "ttm")(m)
                + R._series_fn("fin_exp", "ttm")(m)))),
        },
        "income_tax_yoy": {
            "tax_ttm yoy4": rp(lambda m: yoy4_series(rs0(m, "tax_ttm"))),
            "tax_q yoy4": rp(lambda m: yoy4_series(rs0(m, "tax_q"))),
            "tax_ttm sh252": R._div(P["tax_ttm"], P["tax_ttm"].shift(252)) - 1,
        },
        "tax_surcharge_yoy": {
            "biztax_ttm yoy4": rp(lambda m: yoy4_series(rs0(m, "biztax_ttm"))),
            "biztax_q yoy4": rp(lambda m: yoy4_series(rs0(m, "biztax_q"))),
        },
        "expenses_to_equity_yoy": {
            "exp3/eq_exc yoy4": rp(lambda m: yoy4_series(ratio_report(
                m, "sellexp_q", lambda mm: rs0(mm, "eq_exc")))),
        },
        "np_to_deferred_tax_yoy": {
            "npp_q/dta yoy4": rp(lambda m: yoy4_series(ratio_report(m, "npp_q", "dta"))),
            "npp_ttm/dta yoy4": rp(lambda m: yoy4_series(ratio_report(m, "npp_ttm", "dta"))),
        },
        "asset_growth_qoq": {
            "TA/prev_report": rp(lambda m: sd(rs0(m, "ta"), rs0(m, "ta").shift(1)) - 1),
            "TA/prev_quarter(end_date)": rp(lambda m: sd(rs0(m, "ta"), rs0(m, "ta").shift(1)) - 1),
            "TA yoy4": rp(lambda m: yoy4_series(rs0(m, "ta"))),
        },
        "np_ttm_qoq": {
            "npp_ttm prev_report": rp(lambda m: sd(rs0(m, "npp_ttm"), rs0(m, "npp_ttm").shift(1)) - 1),
            "npp_q prev_report": rp(lambda m: sd(rs0(m, "npp_q"), rs0(m, "npp_q").shift(1)) - 1),
            "npp_ttm sh63": R._div(P["npp_ttm"], P["npp_ttm"].shift(63)) - 1,
        },
        "npm_ttm_qoq": {
            "npm_ttm prev_report": rp(lambda m: sd(rs0(m, "npm_ttm"), rs0(m, "npm_ttm").shift(1)) - 1)
            if False else rp(lambda m: sd(sd(rs0(m, "ni_ttm"), rs0(m, "rev_ttm")),
                                          sd(rs0(m, "ni_ttm"), rs0(m, "rev_ttm")).shift(1)) - 1),
        },
        "gpm_qoq": {
            "gpm_ttm prev_report": rp(lambda m: sd(
                sd(rs0(m, "rev_ttm") - rs0(m, "cost_ttm"), rs0(m, "rev_ttm")),
                sd(rs0(m, "rev_ttm") - rs0(m, "cost_ttm"), rs0(m, "rev_ttm")).shift(1)) - 1),
            "gpm_q prev_report": rp(lambda m: sd(
                sd(rs0(m, "rev_q") - rs0(m, "cost_q"), rs0(m, "rev_q")),
                sd(rs0(m, "rev_q") - rs0(m, "cost_q"), rs0(m, "rev_q")).shift(1)) - 1),
        },
        "yoy_ocf": {
            "ocf_ttm sh252": R._div(P["ocf_ttm"], P["ocf_ttm"].shift(252)) - 1,
            "ocf_ttm yoy4": rp(lambda m: yoy4_series(rs0(m, "ocf_ttm"))),
            "ocf_y sh252": R._div(P["ocf_y"], P["ocf_y"].shift(252)) - 1,
        },
        "yoy_net_asset": {
            "eq_inc sh252": R._div(P["eq_inc"], P["eq_inc"].shift(252)) - 1,
            "eq_exc sh252": R._div(P["eq_exc"], P["eq_exc"].shift(252)) - 1,
            "eq_inc yoy4": rp(lambda m: yoy4_series(rs0(m, "eq_inc_y"))),
        },
        "yoy_roe": {
            "roe_ttm sh252": R._div(R._div(P["npp_ttm"], P["eq_inc"]),
                                    R._div(P["npp_ttm"], P["eq_inc"]).shift(252)) - 1,
            "roe_ttm(ni) sh252": R._div(R._div(P["ni_ttm"], P["eq_inc"]),
                                        R._div(P["ni_ttm"], P["eq_inc"]).shift(252)) - 1,
        },
        "yoy_roa": {
            "roa_ttm(ni) sh252": R._div(R._div(P["ni_ttm"], P["ta"]),
                                        R._div(P["ni_ttm"], P["ta"]).shift(252)) - 1,
            "roa_ttm(npp) sh252": R._div(R._div(P["npp_ttm"], P["ta"]),
                                         R._div(P["npp_ttm"], P["ta"]).shift(252)) - 1,
        },
        "delta_npm": {
            "npm(ni)ttm sh252": R._div(R._div(P["ni_ttm"], P["rev_ttm"]),
                                       R._div(P["ni_ttm"], P["rev_ttm"]).shift(252)) - 1,
        },
        "delta_de": {
            "de_q sh252": R._div(P["tl"], P["eq_inc"]) - R._div(P["tl"], P["eq_inc"]).shift(252),
            "de_fy sh252": R._div(P["tl_y"], P["eq_inc_y"]) - R._div(P["tl_y"], P["eq_inc_y"]).shift(252),
            "de_exc sh252": R._div(P["tl"], P["eq_exc"]) - R._div(P["tl"], P["eq_exc"]).shift(252),
        },
        "cash_profit_ratio": {
            "(ocf-ni)/ni": R._div(P["ocf_ttm"] - P["ni_ttm"], P["ni_ttm"]),
            "(ocf-npp)/npp": R._div(P["ocf_ttm"] - P["npp_ttm"], P["npp_ttm"]),
            "(ocf-ni)/|ni|": R._div(P["ocf_ttm"] - P["ni_ttm"], P["ni_ttm"].abs()),
        },
        "gpm_q": {
            "q diff": R._div(P["rev_q"] - P["cost_q"], P["rev_q"]),
            "ytd cum": R._div(P["rev_raw"], P["rev_raw"]) * np.nan,
        },
        "icr": {
            "ebit_ttm/int_exp_ttm": R._div(P["ebit_ttm"], P["intexp_ttm"]),
            "ebit_ttm/fin_exp_int_ttm": R._div(P["ebit_ttm"], P["intexp2_ttm"]),
            "(op+finexp)_ttm/int_ttm": R._div(P["op_ttm"] + P["finexp_ttm"], P["intexp_ttm"]),
            "(op+finexp)_ttm/fin_exp_int_ttm": R._div(P["op_ttm"] + P["finexp_ttm"], P["intexp2_ttm"]),
        },
        "cfcr": {
            "ocf_ttm/int_ttm": R._div(P["ocf_ttm"], P["intexp_ttm"]),
            "ocf_ttm/fin_exp_int_ttm": R._div(P["ocf_ttm"], P["intexp2_ttm"]),
            "ocf_ttm/finexp_ttm": R._div(P["ocf_ttm"], P["finexp_ttm"]),
        },
        "lra_yoy": {
            "lt_rec yoy4": rp(lambda m: yoy4_series(rs0(m, "ltr"))),
            "lt_rec sh252": R._div(P["ltr"], P["ltr"].shift(252)) - 1,
            "(lt_rec+oth) yoy4": rp(lambda m: yoy4_series(
                rs0(m, "ltr") + m.raw("oth_receiv"))),
        },
        "sa": {
            "rev_q/tshare 252/63": rp(lambda m: (lambda sg: sg - sg.shift(63))(
                sd(sd(rs0(m, "rev_q"), rs0(m, "tshare")),
                   sd(rs0(m, "rev_q"), rs0(m, "tshare")).shift(252)) - 1)),
            "rev_raw/tshare 252/63": rp(lambda m: (lambda sg: sg - sg.shift(63))(
                sd(sd(rs0(m, "rev_raw"), rs0(m, "tshare")),
                   sd(rs0(m, "rev_raw"), rs0(m, "tshare")).shift(252)) - 1)),
        },
        "eaa": {
            "eps_q 252/63": rp(lambda m: (lambda g: g - g.shift(63))(
                sd(rs0(m, "eps_q"), rs0(m, "eps_q").shift(252)) - 1)),
            "eps_raw 252/63": rp(lambda m: (lambda g: g - g.shift(63))(
                sd(rs0(m, "eps_raw"), rs0(m, "eps_raw").shift(252)) - 1)),
            "eps_q report4/1": rp(lambda m: (lambda g: g - g.shift(1))(
                sd(rs0(m, "eps_q"), rs0(m, "eps_q").shift(4)) - 1)),
        },
        "eap": {},
    }

    def sp_med(fac, s):
        out = []
        off_all = {d: X.official_day(fac, d) for d in DATES}
        for d in DATES:
            off = off_all[d]
            if off is None or not len(off):
                continue
            loc = s.loc[pd.Timestamp(d)] if pd.Timestamp(d) in s.index else None
            if loc is None:
                continue
            loc = loc.replace([np.inf, -np.inf], np.nan)
            both = loc.dropna().index.intersection(off.dropna().index)
            if len(both) < 30:
                continue
            if loc[both].nunique() < 2:
                continue
            out.append(off.reindex(both).corr(loc[both], method="spearman"))
        return (float(np.median(out)) if out else np.nan), len(out)

    for fac, cands in VAR.items():
        if not cands:
            continue
        for name, s in cands.items():
            if s is None:
                continue
            s = s.replace([np.inf, -np.inf], np.nan)
            v, n = sp_med(fac, s)
            print(f"{fac:24s} {name:32s} sp_med={v:.5f} n_days={n}", flush=True)
        print(flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
