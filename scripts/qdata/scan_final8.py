#!/usr/bin/env python
"""最后一轮：8 条「真有问题但还能查」因子的内层口径标定（全市场，**多比对日**）。

目标清单
--------
Value 族：`ebitda_to_market` / `etp5` / `pegh5` / `ncf_to_market` / `ocf_to_market`
Quality 族：`cash_profit_ratio` / `gpm_q` / `np_ttm_qoq`

判定口径（**不采用最严口径**，按用户口径）
------------------------------------------
因子值是 ``rank/N`` ⇒ 用**名次相对偏差** ``|本地点位 − 官方名次| / N`` 与横截面 Spearman：

* **通过**：Spearman 中位 ≥ 0.99（对应 APPROX 档）**或** 名次偏差中位 ≤ 1%；
* 输出逐日明细 + 跨日中位，避免单日噪声误判。

用法::

    python scripts/qdata/scan_final8.py --dates 20240812 20240910 20241105 20241216
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
XCACHE = OUT / "cache" / "qg_official_day"
VCACHE = OUT / "cache" / "value_official_day"

FACTORS = ["ebitda_to_market", "etp5", "pegh5", "ncf_to_market", "ocf_to_market",
           "cash_profit_ratio", "gpm_q", "np_ttm_qoq"]


def official(f: str, d: str) -> pd.Series:
    for c in (XCACHE, VCACHE):
        p = c / f"{f}__{d}.pkl"
        if p.is_file():
            with p.open("rb") as fh:
                return pickle.load(fh)
    return pd.Series(dtype=float)


def build_panel(dates: list[str], rebuild: bool = False) -> dict:
    key = OUT / "cache" / f"final8_panel_{dates[0]}_{len(dates)}.pkl"
    if key.is_file() and not rebuild:
        with key.open("rb") as fh:
            return pickle.load(fh)

    import repro_value_xs as V
    import repro_quality as R
    import ts_fin as TF
    from repro_quality import PANEL_SPECS, FIELD_TABLE
    from ts_env import TSPanel

    V.patch_data_layer()
    for c in ("stot_out_inv_act", "depr_fa_coga_dpba"):
        if c not in TF._MIRROR_TABLES["cashflow"]:
            TF._MIRROR_TABLES["cashflow"].append(c)
    for c in ("fin_exp_int_exp",):
        if c not in TF._MIRROR_TABLES["income"]:
            TF._MIRROR_TABLES["income"].append(c)
    for c, tb in (("stot_out_inv_act", "cashflow"), ("depr_fa_coga_dpba", "cashflow"),
                  ("fin_exp_int_exp", "income")):
        FIELD_TABLE.setdefault(c, tb)

    PANEL_SPECS.update({
        "ebitda_y": ("ebitda", "y"), "ebitda_q": ("ebitda", "q"),
        "ebit_y": ("ebit", "y"), "ebit_q": ("ebit", "q"),
        "ocf_q": ("n_cashflow_act", "q"), "ocf_y": ("n_cashflow_act", "y"),
        "icf_ttm": ("n_cashflow_inv_act", "ttm"), "icf_q": ("n_cashflow_inv_act", "q"),
        "fin_ttm": ("n_cash_flows_fnc_act", "ttm"), "fin_q": ("n_cash_flows_fnc_act", "q"),
        "totsrev_y": ("total_revenue", "y"), "totsrev_q": ("total_revenue", "q"),
        "cost_y2": ("oper_cost", "y"), "cost_q2": ("oper_cost", "q"),
        "finexp_ttm": ("fin_exp", "ttm"),
        "rev_raw": ("revenue", "raw"), "cost_raw": ("oper_cost", "raw"),
        "depr_ttm": ("depr_fa_coga_dpba", "ttm"),
        "inv_out": ("stot_out_inv_act", "ttm"),
    })

    days = V.warmup_days(list(dates), 1400)
    idx, fields = V.market_days(days)
    probe = TF.load_mirror_full(codes=None, tables={"income": ["revenue"]})
    codes = sorted(probe["income"]["ts_code"].unique())
    tabs = TF.load_mirror_full(codes=codes)
    tables = {t: {c: g for c, g in df.groupby("ts_code", sort=False)}
              for t, df in tabs.items()}
    mats = TF.build_matrices(tables, codes)
    panel = TSPanel(codes=codes, fields=fields)
    P = R.build_panels(mats, codes, idx)
    obj = {"P": P, "mv": panel.TOTAL_MV, "close": panel.C_RAW,
           "tshare": panel.TOTAL_SHARE, "dates": list(dates), "codes": codes}
    with key.open("wb") as fh:
        pickle.dump(obj, fh)
    return obj


def variants_for(P, mv, close, tshare, t: pd.Timestamp) -> dict[str, dict[str, pd.Series]]:
    """在**单个比对日**上取截面，构造所有候选口径。"""

    def at(x: pd.DataFrame) -> pd.Series:
        return (x.loc[t].replace([np.inf, -np.inf], np.nan).dropna()
                if t in x.index else pd.Series(dtype=float))

    def div(a, b):
        return a / b.replace(0, np.nan)

    MV = at(mv)
    C = at(close)
    SH = at(tshare) * 1e4
    ocf_ttm, ocf_q, ocf_y = at(P["ocf"]), at(P["ocf_q"]), at(P["ocf_y"])
    icf, fin = at(P["icf_ttm"]), at(P["fin_ttm"])
    ebitda_ttm, ebitda_y, ebitda_q = at(P["ebitda_ttm"]), at(P["ebitda_y"]), at(P["ebitda_q"])
    ebit_ttm = at(P["ebit_ttm"])
    out: dict[str, dict[str, pd.Series]] = {}

    out["ebitda_to_market"] = {
        "EBITDA_TTM/mv": div(ebitda_ttm, MV),
        "EBITDA年报/mv": div(ebitda_y, MV),
        "EBITDA单季/mv": div(ebitda_q, MV),
        "EBITDA_TTM/(close*总股本)": div(ebitda_ttm, C * SH),
        "EBIT_TTM+折旧摊销/mv": div(ebit_ttm + at(P["depr_ttm"]), MV),
        "营业利润TTM/mv": at(div(P["op_ttm"], mv)),
    }
    out["ocf_to_market"] = {
        "OCF_TTM/mv": div(ocf_ttm, MV),
        "OCF单季/mv": div(ocf_q, MV),
        "OCF年报/mv": div(ocf_y, MV),
        "OCF_TTM+ICF_TTM/mv": div(ocf_ttm + icf, MV),
        "OCF_TTM/(close*总股本)": div(ocf_ttm, C * SH),
    }
    out["ncf_to_market"] = {
        "OCF+ICF+Fin(TTM)/mv": div(ocf_ttm + icf + fin, MV),
        "OCF+ICF(TTM)/mv": div(ocf_ttm + icf, MV),
        "OCF+ICF+Fin(单季)/mv": div(at(P["ocf_q"]) + at(P["icf_q"]) + at(P["fin_q"]), MV),
        "Fin(TTM)/mv": div(fin, MV),
    }
    ni_ttm, npp_ttm = at(P["ni_ttm"]), at(P["npp_ttm"])
    out["cash_profit_ratio"] = {
        "(OCF−净利润TTM)/净利润TTM": div(ocf_ttm - ni_ttm, ni_ttm),
        "(OCF−归母TTM)/归母TTM": div(ocf_ttm - npp_ttm, npp_ttm),
        "(OCF−净利润TTM)/营业收入TTM": div(ocf_ttm - ni_ttm, at(P["rev_ttm"])),
        "OCF_TTM/净利润TTM": div(ocf_ttm, ni_ttm),
        "(OCF−扣非TTM)/扣非TTM": div(ocf_ttm - at(P["dedt_ttm"]), at(P["dedt_ttm"])),
    }
    out["gpm_q"] = {
        "单季(差分) revenue": div(at(P["rev_q"]) - at(P["cost_q"]), at(P["rev_q"])),
        "单季(差分) totsrev": div(at(P["totsrev_q"]) - at(P["cost_q"]), at(P["totsrev_q"])),
        "累计(YTD) revenue": div(at(P["rev_raw"]) - at(P["cost_raw"]), at(P["rev_raw"])),
        "TTM": at(div(P["rev_ttm"] - P["cost_ttm"], P["rev_ttm"])),
    }
    npp = P["npp_ttm"]
    idx = npp.index
    out["np_ttm_qoq"] = {
        "归母TTM/t-63−1": at(div(npp, npp.shift(63)) - 1),
        "净利润TTM/t-63−1": at(div(P["ni_ttm"], P["ni_ttm"].shift(63)) - 1),
        "归母TTM/t-63−1(前值由日报重采样)": div(npp, npp.resample("QE").last()
                                             .shift(1).reindex(idx, method="ffill")) - 1,
        "归母单季/上季−1": at(div(P["npp_q"], P["npp_q"].shift(1)) - 1),
        "归母单季/t-63−1": at(div(P["npp_q"], P["npp_q"].shift(63)) - 1),
        "归母TTM/prev_report−1": at(div(npp, npp.shift(1)) - 1),
    }
    npp_y = P["npp_y"].ffill(limit=3)
    mv_roll = mv.rolling(1260, min_periods=1000).mean()
    out["etp5"] = {
        "mean(归母年报,1260)/mean(mv,1260)": at(div(npp_y.rolling(1260, min_periods=1000).mean(), mv_roll)),
        "mean(归母TTM,1260)/mean(mv,1260)": at(div(P["npp_ttm"].rolling(1260, min_periods=1000).mean(), mv_roll)),
        "mean(归母年报,1203)/mean(mv,1203)": at(div(npp_y.rolling(1203, min_periods=1000).mean(),
                                                   mv.rolling(1203, min_periods=1000).mean())),
        "mean(净利润TTM,1260)/mean(mv,1260)": at(div(P["ni_ttm"].rolling(1260, min_periods=1000).mean(), mv_roll)),
    }
    eps_y = P["eps_y"].ffill(limit=3)
    cand: dict[str, pd.Series] = {}
    for n, tag in ((1260, "1260"), (1250, "1250"), (1203, "1203")):
        g = (div(eps_y, eps_y.shift(n)) ** (1.0 / 5.0)) - 1.0
        cand[f"-Close/(g5_{tag}·EPS_TTM)"] = -div(C, at(g) * at(P["eps_ttm"]))
    cand["-1/(g5_1260·EPS_TTM)"] = -div(1.0, at((div(eps_y, eps_y.shift(1260)) ** 0.2) - 1.0) * at(P["eps_ttm"]))
    cand["-Close/(g5·EPS年报)"] = -div(C, at((div(eps_y, eps_y.shift(1260)) ** 0.2) - 1.0) * at(eps_y))
    # 用 EPS_TTM 做 5 年复合增速（而非 EPS 年报）
    eps_t = P["eps_ttm"]
    g_ttm = (div(eps_t, eps_t.shift(1260)) ** 0.2) - 1.0
    cand["-Close/(g5(EPS_TTM)·EPS_TTM)"] = -div(C, at(g_ttm) * at(eps_t))
    # 用净利润 5 年复合增速代替 EPS
    npp_y5 = P["npp_y"].ffill(limit=3)
    g_np = (div(npp_y5, npp_y5.shift(5)) ** 0.2) - 1.0
    cand["-mv/(g5(归母年报5期)·归母TTM)"] = -div(MV, at(g_np) * at(P["npp_ttm"]))
    cand["-1/(g5(EPS_TTM)·EPS_TTM)"] = -div(1.0, at(g_ttm) * at(eps_t))
    out["pegh5"] = cand
    return out


def prefetch(factors: list[str], dates: list[str]) -> None:
    """补取缺失的官方单日全市场值（限流时空结果必须重试）。"""
    import time
    from qdata_env import QDataClient
    cli = QDataClient()
    for f in factors:
        for d in dates:
            if any((c / f"{f}__{d}.pkl").is_file() for c in (XCACHE, VCACHE)):
                continue
            rows = None
            for att in range(6):
                try:
                    rows = cli.factor_value(factor_name=f, trade_date=d)
                    if not rows:                      # code=0/msg=ok/items=[]
                        time.sleep(1.5 * (att + 1))
                        continue
                    break
                except Exception:                     # noqa: BLE001
                    time.sleep(2.0 * (att + 1))
            if not rows:
                print(f"    !! {f} {d} 取不到（限流或无权）", flush=True)
                continue
            s = pd.Series({r["ts_code"]: float(r["factor_value"]) for r in rows}).dropna()
            with (XCACHE / f"{f}__{d}.pkl").open("wb") as fh:
                pickle.dump(s, fh)
            print(f"    取到 {f} {d} N={len(s)}", flush=True)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dates", nargs="*",
                    default=["20240812", "20240910", "20241105", "20241216"])
    ap.add_argument("--rebuild", action="store_true")
    ap.add_argument("--out", default="final8_scan.csv")
    ap.add_argument("--prefetch", action="store_true", help="先补齐缺失的官方值")
    args = ap.parse_args()

    if args.prefetch:
        print("补取官方值 …", flush=True)
        prefetch(FACTORS, args.dates)

    print("构造/加载面板 …", flush=True)
    obj = build_panel(args.dates, args.rebuild)
    P, mv = obj["P"], obj["mv"]
    close, tshare = obj["close"], obj["tshare"]

    rows = []
    for ds in args.dates:
        t = pd.Timestamp(ds)
        cand = variants_for(P, mv, close, tshare, t)
        for f, variants in cand.items():
            o = official(f, ds)
            if o.empty:
                continue
            N_o = len(o)
            orank = (o * N_o).round()
            for vname, s in variants.items():
                s = s.replace([np.inf, -np.inf], np.nan).dropna()
                if len(s) < 100:
                    continue
                N_l = len(s)
                lrank = (s.rank(method="max") / N_l * N_l).round()
                idx = o.index.intersection(s.index)
                a, b = orank.reindex(idx), lrank.reindex(idx)
                m = a.notna() & b.notna()
                if m.sum() < 100 or s.reindex(idx)[m].nunique() < 2:
                    continue
                sp = float(pd.to_numeric(o.reindex(idx)[m], errors="coerce")
                           .corr(s.reindex(idx)[m].rank(), method="spearman"))
                gap = (b[m] - a[m]).abs()
                rows.append(dict(factor=f, date=ds, variant=vname, n=int(m.sum()),
                                 N_off=N_o, N_loc=N_l, spearman=sp,
                                 rank_gap_pct=float(gap.median() / N_o)))

    raw = pd.DataFrame(rows)
    agg = (raw.groupby(["factor", "variant"])
              .agg(n_days=("date", "nunique"),
                   spearman_med=("spearman", "median"),
                   spearman_min=("spearman", "min"),
                   gap_med=("rank_gap_pct", "median"),
                   gap_max=("rank_gap_pct", "max"))
              .reset_index())
    agg["pass_sp"] = agg["spearman_med"] >= 0.99
    agg["pass_user"] = agg["gap_med"] <= 0.01
    agg["通过"] = agg["pass_sp"] | agg["pass_user"]
    agg = agg.sort_values(["factor", "spearman_med"], ascending=[True, False])

    pd.set_option("display.width", 240)
    print("\n=== 跨日汇总（各口径）===")
    print(agg.to_string(index=False, float_format=lambda x: f"{x:.6f}"))
    agg.to_csv(OUT / args.out, index=False)
    raw.to_csv(OUT / args.out.replace(".csv", "_daily.csv"), index=False)
    print(f"\n已写 {OUT / args.out}")

    print("\n=== 每因子最优口径 ===")
    for f, g in agg.groupby("factor"):
        best = g.iloc[0]
        mark = "✅ 通过" if best["通过"] else "✗ 未通过"
        print(f"  {f:22s} {best['variant'][:34]:36s} sp={best['spearman_med']:.6f} "
              f"(min {best['spearman_min']:.6f})  名次偏差={best['gap_med']:.2%}  {mark}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
