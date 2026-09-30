#!/usr/bin/env python
"""Value 族内层口径变体扫描（**全量面板版**，一次建面板、多口径对照）。

动机
----
``repro_value_xs.py`` 的首轮结果暴露了明显的口径梯度：

| 因子 | 首轮 Spearman | 文档公式分子 | 推测 |
|---|---|---|---|
| `sales_to_market` | **1.0000** | 单季营业总收入 | 口径已对 |
| `earnings_cut_to_market` | 0.9486 | 「扣非净利润」 | **实测应为归母净利润**（变体 0.999997）|
| `etp5` | 0.9844 | 5 年滚动均值 | 窗口/口径待定 |
| `pegh5` | 0.9409 | EPS 5 年复合增速 | 口径待定 |
| `ebitda_to_market` | 0.9100 | EBITDA（TTM） | **单季/年报更优**（年报变体 0.973）|
| `ocf_to_market` | 0.8623 | OCF_TTM | 口径待定 |
| `ncf_to_market` | 0.7128 | OCF+ICF+Fin | 口径待定 |

本脚本一次性把候选口径全部实测（含**单季**版本 —— 注意 `sales_to_market` 用单季成功，
说明 qdata 对「_Q 后缀」的实现可能与我们默认的 TTM 假设不同），输出最优变体。

用法::

    python scripts/qdata/scan_value_variants.py --date 20240812
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

FACTORS = ["earnings_cut_to_market", "ebitda_to_market", "etp5",
           "ncf_to_market", "ocf_to_market", "pegh5", "sales_to_market"]


def official(factor: str, date: str) -> pd.Series:
    p = XCACHE / f"{factor}__{date}.pkl"
    if not p.is_file():
        return pd.Series(dtype=float)
    with p.open("rb") as fh:
        return pickle.load(fh)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", default="20240812")
    ap.add_argument("--out", default="value_variant_scan.csv")
    args = ap.parse_args()
    t0s = args.date
    t0 = pd.Timestamp(t0s)

    import repro_value_xs as V
    import repro_quality as R
    import ts_fin as TF
    from repro_quality import PANEL_SPECS, FIELD_TABLE
    from ts_env import TSPanel

    V.patch_data_layer()
    FIELD_TABLE.setdefault("total_revenue", "income")
    PANEL_SPECS.update({
        "ocf_q": ("n_cashflow_act", "q"), "ocf_y": ("n_cashflow_act", "y"),
        "icf_q": ("n_cashflow_inv_act", "q"), "icf_ttm": ("n_cashflow_inv_act", "ttm"),
        "fin_q": ("n_cash_flows_fnc_act", "q"), "fin_ttm": ("n_cash_flows_fnc_act", "ttm"),
        "inv_out_q": ("stot_out_inv_act", "q"),
        "npp_q": ("n_income_attr_p", "q"),
        "ebitda_q": ("ebitda", "q"), "ebit_y": ("ebit", "y"), "ebit_q": ("ebit", "q"),
        "cost_y": ("oper_cost", "y"), "cost_q": ("oper_cost", "q"),
        "totsrev_y": ("total_revenue", "y"),
        "cashin_ttm": ("c_fr_sale_sg", "ttm"), "cashin_q": ("c_fr_sale_sg", "q"),
    })
    PANEL_SPECS.setdefault("totsrev_q", ("total_revenue", "q"))

    days = V.warmup_days([t0s], 1400)
    idx, fields = V.market_days(days)
    probe = TF.load_mirror_full(codes=None, tables={"income": ["revenue"]})
    codes = sorted(probe["income"]["ts_code"].unique())
    tabs = TF.load_mirror_full(codes=codes)
    print(f"股票池 {len(codes)} 只，面板 {len(days)} 天", flush=True)
    tables = {t: {c: g for c, g in df.groupby("ts_code", sort=False)}
              for t, df in tabs.items()}
    mats = TF.build_matrices(tables, codes)
    panel = TSPanel(codes=codes, fields=fields)
    P = R.build_panels(mats, codes, idx)
    div = R._div
    mv = panel.TOTAL_MV
    c_raw = panel.C_RAW

    def at(x: pd.DataFrame) -> pd.Series:
        return x.loc[t0].replace([np.inf, -np.inf], np.nan).dropna() if t0 in x.index \
            else pd.Series(dtype=float)

    # ---------------- 候选口径 ----------------
    cand: dict[str, dict[str, pd.Series]] = {}
    cand["sales_to_market"] = {
        "单季营业总收入/mv": at(div(P["totsrev_q"], mv)),
        "TTM营业总收入/mv": at(div(P["tots_rev_ttm"], mv)),
        "单季营业收入/mv": at(div(P["rev_q"], mv)),
        "TTM营业收入/mv": at(div(P["rev_ttm"], mv)),
        "年报营业总收入/mv": at(div(P["totsrev_y"], mv)),
    }
    cand["earnings_cut_to_market"] = {
        "归母净利润TTM/mv": at(div(P["npp_ttm"], mv)),
        "扣非净利润TTM/mv": at(div(P["dedt_ttm"], mv)),
        "净利润TTM(含少数)/mv": at(div(P["ni_ttm"], mv)),
        "归母单季/mv": at(div(P["npp_q"], mv)),
    }
    cand["ebitda_to_market"] = {
        "EBITDA_TTM/mv": at(div(P["ebitda_ttm"], mv)),
        "EBITDA年报/mv": at(div(P["ebitda_y"], mv)),
        "EBITDA单季/mv": at(div(P["ebitda_q"], mv)),
        "EBIT_TTM+营业成本TTM": at(div(P["ebit_ttm"] + P["cost_ttm"], mv)),
        "营业利润TTM/mv": at(div(P["op_ttm"], mv)),
    }
    cand["ocf_to_market"] = {
        "OCF_TTM/mv": at(div(P["ocf"], mv)),
        "OCF单季/mv": at(div(P["ocf_q"], mv)),
        "OCF年报/mv": at(div(P["ocf_y"], mv)),
        "销售商品收到现金TTM/mv": at(div(P["cashin_ttm"], mv)),
        "OCF_TTM−投资流出TTM": at(div(P["ocf"] - P["inv_out"], mv)),
        "OCF_TTM+ICF_TTM": at(div(P["ocf"] + P["icf_ttm"], mv)),
    }
    cand["ncf_to_market"] = {
        "OCF+ICF+Fin(TTM)": at(div(P["ocf"] + P["icf_ttm"] + P["fin_ttm"], mv)),
        "OCF+ICF+Fin(单季)": at(div(P["ocf_q"] + P["icf_q"] + P["fin_q"], mv)),
        "OCF+ICF(TTM)": at(div(P["ocf"] + P["icf_ttm"], mv)),
        "OCF_TTM": at(div(P["ocf"], mv)),
        "Fin(TTM)": at(div(P["fin_ttm"], mv)),
    }
    # etp5 —— 5 年 ≈ 1260 交易日
    npp_y = P["npp_y"].ffill(limit=3)
    mv_mean = mv.rolling(1260, min_periods=1000).mean()
    cand["etp5"] = {
        "mean(npp年报,1260)/mean(mv,1260)": at(div(npp_y.rolling(1260, min_periods=1000).mean(), mv_mean)),
        "mean(npp_TTM,1260)/mean(mv,1260)": at(div(P["npp_ttm"].rolling(1260, min_periods=1000).mean(), mv_mean)),
        "mean(npp年报,1260)/mv": at(div(npp_y.rolling(1260, min_periods=1000).mean(), mv)),
        "mean(npp年报,252*5)/mv": at(div(npp_y.rolling(1260, min_periods=1000).mean(), mv)),
        "5年年报均值/5年mv均值": at(div(
            npp_y.rolling(15, min_periods=10).mean(), mv.rolling(1260, min_periods=1000).mean())),
    }
    # pegh5
    eps_y = P["eps_y"].ffill(limit=3)
    def growth(n: int) -> pd.DataFrame:
        return (div(eps_y, eps_y.shift(n)) ** (1.0 / 5.0)) - 1.0
    g1260, g15 = growth(1260), growth(15)
    cand["pegh5"] = {
        "-Close/(g*eps_TTM)": at(-div(c_raw, g1260 * P["eps_ttm"])),
        "Close/(g*eps_TTM)": at(div(c_raw, g1260 * P["eps_ttm"])),
        "-Close/(g*eps年报)": at(-div(c_raw, g1260 * P["eps_y"].ffill(limit=3))),
        "-Close/(g15*eps_TTM)": at(-div(c_raw, g15 * P["eps_ttm"])),
        "-mv/(g*npp年报)": at(-div(mv, g1260 * npp_y)),
        "-Close/(g*eps_TTM) 无符号": at(div(c_raw, g1260 * P["eps_ttm"])),
    }

    # 补充：官方 fcf_to_market 是**原始比值**，用绝对误差判据，这里只报 sp 供参考
    cand["fcf_to_market"] = {
        "(OCF−投资流出)TTM": at(div(P["ocf"] - P["inv_out"], mv)),
        "Tushare free_cashflow": at(div(P["fcf_ts"], mv)),
        "(单季OCF−单季投资流出)": at(div(P["ocf_q"] - P["inv_out_q"], mv)),
    }

    rows = []
    for f, variants in cand.items():
        o = official(f, t0s)
        if o.empty:
            continue
        N = len(o)
        orank = (o * N).round()
        for vname, s in variants.items():
            if s.empty:
                continue
            sr = s[np.isfinite(s)]
            if len(sr) < 200:
                continue
            lr = sr.rank(method="max") / len(sr)          # 最终判据口径：本地全池 rank/N
            idx3 = o.index.intersection(lr.index)
            a3 = pd.to_numeric(o.reindex(idx3), errors="coerce")
            b3 = lr.reindex(idx3)
            m3 = a3.notna() & b3.notna()
            if m3.sum() < 200:
                continue
            sp_final = float(a3[m3].corr(b3[m3], method="spearman"))
            gap = (b3[m3] * len(sr) - orank.reindex(idx3)[m3]).abs()
            rows.append(dict(factor=f, variant=vname, n_pool=len(sr), N_off=N,
                             sp_final=sp_final,
                             rank_gap_med=float(gap.median()),
                             rank_gap_p99=float(gap.quantile(0.99))))

    d = pd.DataFrame(rows).sort_values(["factor", "sp_final"], ascending=[True, False])
    pd.set_option("display.width", 220)
    print(d.to_string(index=False, float_format=lambda x: f"{x:.6f}"))
    d.to_csv(OUT / args.out, index=False)
    print(f"\n已写 {OUT / args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
