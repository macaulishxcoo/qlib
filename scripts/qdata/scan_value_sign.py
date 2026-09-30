#!/usr/bin/env python
"""假设检验：qdata 的现金流类价值因子是否对分子取了**绝对值**？

线索（2026-09-21 实测）
----------------------
`diag_value_gap.py` 显示 `ocf_to_market` 的最大偏差**全部是金融股**，且方向一致：

| 股票 | 官方名次 | 本地点位 |
|---|---|---|
| 601577.SH | 39 | 5073 |
| 600649.SH | 17 | 5035 |
| 601128.SH | 59 | 5070 |
| 600926.SH | 48 | 5055 |
| 601658.SH | 109 | 5069 |

银行的经营现金流因「客户存款/同业拆借」变动常为**大额负值**。若官方对分子取了
绝对值（或对负值做了翻转），这些股票就会从底部跳到顶部 —— 与观测完全吻合。

同样地 `ncf_to_market` 的 top 偏差也是 601916/601997/601658/600919（银行）。

本脚本一次性检验多种「符号处理」口径。

用法::

    python scripts/qdata/scan_value_sign.py --date 20240812
"""
from __future__ import annotations

import argparse
import pickle
import sys
from pathlib import Path

import numpy as np
import pandas as pd

_SCRIPTS = Path(__file__).resolve().parents[1]
for p in (str(_SCRIPTS), str(_SCRIPTS / "qdata"), str(_SCRIPTS / "jqdata")):
    if p not in sys.path:
        sys.path.insert(0, p)

REPO_ROOT = Path(__file__).resolve().parents[2]
OUT = REPO_ROOT / "output" / "qdata_factor_repro"
XCACHE = OUT / "cache" / "value_official_day"
PANEL_CACHE = OUT / "cache" / "value_panel.pkl"


def official(f: str, d: str) -> pd.Series:
    with (XCACHE / f"{f}__{d}.pkl").open("rb") as fh:
        return pickle.load(fh)


def build_panel(date: str) -> dict:
    """建一次面板并落盘（后续实验直接复用）。"""
    if PANEL_CACHE.is_file():
        with PANEL_CACHE.open("rb") as fh:
            return pickle.load(fh)

    import repro_value_xs as V
    import repro_quality as R
    import ts_fin as TF
    from repro_quality import PANEL_SPECS, FIELD_TABLE
    from ts_env import TSPanel

    V.patch_data_layer()
    # 金融类经营现金流明细（银行/券商的 OCF 常为负，正是本假设的检验对象）
    for c in ("n_depos_incr_fi", "n_incr_loans_oth_bank", "n_inc_borr_oth_fi"):
        if c not in TF._MIRROR_TABLES["cashflow"]:
            TF._MIRROR_TABLES["cashflow"].append(c)
    FIELD_TABLE.setdefault("total_revenue", "income")
    PANEL_SPECS.update({
        "ocf_q": ("n_cashflow_act", "q"), "ocf_y": ("n_cashflow_act", "y"),
        "icf_ttm": ("n_cashflow_inv_act", "ttm"), "icf_q": ("n_cashflow_inv_act", "q"),
        "fin_ttm": ("n_cash_flows_fnc_act", "ttm"), "fin_q": ("n_cash_flows_fnc_act", "q"),
        "totsrev_q": ("total_revenue", "q"),
        "cashin_ttm": ("c_fr_sale_sg", "ttm"),
        "deposit_incr": ("n_depos_incr_fi", "ttm"),
        "loan_incr": ("n_incr_loans_oth_bank", "ttm"),
        "borrow_incr": ("n_inc_borr_oth_fi", "ttm"),
    })
    days = V.warmup_days([date], 1400)
    idx, fields = V.market_days(days)
    probe = TF.load_mirror_full(codes=None, tables={"income": ["revenue"]})
    codes = sorted(probe["income"]["ts_code"].unique())
    tabs = TF.load_mirror_full(codes=codes)
    tables = {t: {c: g for c, g in df.groupby("ts_code", sort=False)}
              for t, df in tabs.items()}
    mats = TF.build_matrices(tables, codes)
    panel = TSPanel(codes=codes, fields=fields)
    P = R.build_panels(mats, codes, idx)
    obj = {"P": P, "mv": panel.TOTAL_MV, "close": panel.C_RAW, "date": date}
    with PANEL_CACHE.open("wb") as fh:
        pickle.dump(obj, fh)
    return obj


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", default="20240812")
    ap.add_argument("--rebuild", action="store_true")
    args = ap.parse_args()
    if args.rebuild and PANEL_CACHE.is_file():
        PANEL_CACHE.unlink()

    print("构造/加载面板 …", flush=True)
    obj = build_panel(args.date)
    P, mv = obj["P"], obj["mv"]
    t = pd.Timestamp(args.date)

    def at(x: pd.DataFrame) -> pd.Series:
        return (x.loc[t].replace([np.inf, -np.inf], np.nan).dropna()
                if t in x.index else pd.Series(dtype=float))

    def div(a, b):
        return a / b.replace(0, np.nan)

    ocf = at(P["ocf"])
    ncf = at(div(P["ocf"] + P["icf_ttm"] + P["fin_ttm"], mv))
    ebitda = at(P["ebitda_ttm"])
    mv_ = at(mv)

    cand = {
        "ocf_to_market": {
            "OCF_TTM/mv": ocf / mv_.reindex(ocf.index),
            "|OCF_TTM|/mv": ocf.abs() / mv_.reindex(ocf.index),
            "max(OCF,0)/mv": ocf.clip(lower=0) / mv_.reindex(ocf.index),
            "OCF_TTM/mv（含存款同业）": at(div(P["ocf"] + P["deposit_incr"]
                                              + P["loan_incr"] + P["borrow_incr"], mv)),
            "-OCF_TTM/mv": -ocf / mv_.reindex(ocf.index),
        },
        "ncf_to_market": {
            "(OCF+ICF+Fin)/mv": ncf,
            "|OCF+ICF+Fin|/mv": ncf.abs(),
            "(|OCF|+|ICF|+|Fin|)/mv": at(
                (P["ocf"].abs() + P["icf_ttm"].abs() + P["fin_ttm"].abs()) / mv),
        },
        "ebitda_to_market": {
            "EBITDA_TTM/mv": at(div(P["ebitda_ttm"], mv)),
            "|EBITDA_TTM|/mv": at(div(P["ebitda_ttm"].abs(), mv)),
        },
        "earnings_cut_to_market": {
            "归母TTM/mv": at(div(P["npp_ttm"], mv)),
            "|归母TTM|/mv": at(div(P["npp_ttm"].abs(), mv)),
        },
    }

    rows = []
    for f, variants in cand.items():
        o = official(f, args.date)
        N = len(o)
        orank = (o * N).round()
        for vname, s in variants.items():
            s = s[np.isfinite(s)]
            if len(s) < 200:
                continue
            lr = s.rank(method="max") / len(s)
            idx = o.index.intersection(lr.index)
            a = pd.to_numeric(o.reindex(idx), errors="coerce")
            b = lr.reindex(idx)
            m = a.notna() & b.notna()
            if m.sum() < 200:
                continue
            sp = float(a[m].corr(b[m], method="spearman"))
            gap = (b[m] * len(s) - orank.reindex(idx)[m]).abs()
            rows.append(dict(factor=f, variant=vname, n=len(s), sp=sp,
                             gap_med=float(gap.median()), gap_p99=float(gap.quantile(0.99))))

    d = pd.DataFrame(rows).sort_values(["factor", "sp"], ascending=[True, False])
    pd.set_option("display.width", 200)
    print(d.to_string(index=False, float_format=lambda x: f"{x:.6f}"))
    d.to_csv(OUT / "value_sign_scan.csv", index=False)
    print(f"\n已写 {OUT / 'value_sign_scan.csv'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
