#!/usr/bin/env python3
"""P3 v2: idiosyncratic-sector transmission test (protocol v1, H4 strong version).

The index-level P3 only tested "IXIC vs DJI -> A-share sectors".  Both US
indices are ~90%+ common risk factor, so sector-idiosyncratic information is
drowned out.  This script extracts IDIOSYNCRATIC US sector returns:

    res_X[t] = r_X[t] - beta_roll[t] * r_SPX[t]   (beta from trailing 250 US days)

and tests whether A-share sector opening gaps respond to the sector-specific
component (matching test: tech sectors on IXIC-residual vs traditional sectors
on IXIC-residual, controlling for the market factor r_SPX and DJI-residual).

Spec (per industry):  gap_ind = a + b1*res_IXIC + b2*res_DJI + b3*r_SPX + e

Pre-registered judgment: H4' supported iff
    mean(b1 | tech) > mean(b1 | traditional)   (and > 0 consistently)
with group SE = std(b1 within group)/sqrt(n_industries).

Usage (conda activate qlib):
    python scripts/analyze_us_overnight_industry_v2.py
Outputs -> output/analysis_static/us_overnight_conduction_v1/
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

from analyze_us_overnight_conduction_v1 import newey_west_beta, OUT

ROOT = Path(__file__).resolve().parent.parent
SW_CSV = ROOT / "data/external/tushare/sw_industry_index_v1/normalized/sw_industry_daily.csv.gz"
US_CSV = ROOT / "data/external/tushare/us_index_v1/normalized/us_index.csv.gz"
START = "2016-01-01"
ROLL = 250  # trailing US trading days for beta
GROUPS = {
    "tech": ["计算机", "通信", "传媒"],
    "traditional": ["银行", "非银金融", "采掘", "化工", "钢铁"],
    "defensive": ["医药生物", "食品饮料", "公用事业"],
}


def us_returns(us: pd.DataFrame) -> dict[str, pd.Series]:
    out = {}
    for code in ["SPX", "IXIC", "DJI"]:
        s = us[us["ts_code"] == code].set_index("trade_date")["close"].sort_index()
        out[code] = s.pct_change()
    return out


def build_idio_window(res: pd.Series, cal: pd.DatetimeIndex) -> pd.DataFrame:
    """Sum idiosyncratic daily residual over each A-share info window."""
    rows = []
    for i, d in enumerate(cal):
        if i == 0:
            continue
        d_prev = cal[i - 1]
        win = res.index[(res.index >= d_prev) & (res.index < d)]
        if len(win) == 0:
            continue
        rows.append({"a_date": d, "res": float(res.loc[win].sum())})
    return pd.DataFrame(rows)


def main() -> None:
    sw = pd.read_csv(SW_CSV, compression="gzip", parse_dates=["trade_date"])
    us = pd.read_csv(US_CSV, compression="gzip", parse_dates=["trade_date"])
    rets = us_returns(us)
    spx, ixic, dji = rets["SPX"], rets["IXIC"], rets["DJI"]

    # rolling beta of IXIC/DJI on SPX (trailing 250 US days, no lookahead)
    def roll_beta(y: pd.Series, x: pd.Series) -> pd.Series:
        df = pd.concat([y.rename("y"), x.rename("x")], axis=1).dropna()
        cov = df["y"].rolling(ROLL).cov(df["x"])
        var = df["x"].rolling(ROLL).var()
        return (cov / var)

    b_ixic = roll_beta(ixic, spx)
    b_dji = roll_beta(dji, spx)
    res_ixic = (ixic - b_ixic * spx).dropna()
    res_dji = (dji - b_dji * spx).dropna()

    # diagnostics: correlations
    d = pd.concat([spx, ixic, dji, res_ixic, res_dji], axis=1, keys=["spx", "ixic", "dji", "r_ixic", "r_dji"]).dropna()
    print(f"[diag] corr(IXIC,DJI)={d['ixic'].corr(d['dji']):.3f}  "
          f"corr(res_IXIC,res_DJI)={d['r_ixic'].corr(d['r_dji']):.3f}  "
          f"std(res_IXIC)={d['r_ixic'].std()*100:.2f}%/d  std(res_DJI)={d['r_dji'].std()*100:.2f}%/d")

    cal = pd.DatetimeIndex(pd.to_datetime(sw["trade_date"]).dropna().unique())
    cal = cal.sort_values()
    w = build_idio_window(res_ixic, cal).rename(columns={"res": "r_ixic"})
    w = w.merge(build_idio_window(res_dji, cal).rename(columns={"res": "r_dji"}), on="a_date")
    w = w.merge(build_idio_window(spx, cal).rename(columns={"res": "r_spx"}), on="a_date")

    rows = []
    for ind, sub in sw.groupby("industry_name"):
        sub = sub.sort_values("trade_date").set_index("trade_date").copy()
        sub["gap"] = sub["open"] / sub["close"].shift(1) - 1
        sub = sub[sub.index >= START]
        m = pd.merge(sub.reset_index()[["trade_date", "gap"]], w,
                     left_on="trade_date", right_on="a_date", how="inner")
        # spec: gap = a + b1*res_IXIC + b2*res_DJI + b3*r_SPX
        x = np.column_stack([np.ones(len(m)), m["r_ixic"], m["r_dji"], m["r_spx"]])
        y = m["gap"].values
        b, *_ = np.linalg.lstsq(x, y, rcond=None)
        e = y - x @ b
        n = len(m)
        XtX_inv = np.linalg.inv(x.T @ x)
        se = np.sqrt(np.diag(XtX_inv * (e @ e / (n - 4))))
        rows.append({"industry": ind, "b1_ixic_res": b[1], "t1": b[1] / se[1],
                     "b2_dji_res": b[2], "t2": b[2] / se[2],
                     "b3_spx": b[3], "t3": b[3] / se[3], "n": n})
    tab = pd.DataFrame(rows).set_index("industry")
    tab.to_csv(OUT / "P3v2_idiosyncratic.csv")
    tab["group"] = tab.index.map({i: g for g, inds in GROUPS.items() for i in inds}).fillna("other")

    print("\n===== P3v2: idiosyncratic US sector -> A-share sector OPENING GAP =====")
    print("b1 = A-share gap beta on IXIC-idiosyncratic (tech-specific); t in parens")
    print(tab[["b1_ixic_res", "t1", "b3_spx", "t3"]].round(3).to_string())

    print("\n===== group comparison (mean b1_ixic_res ± group SE) =====")
    for grp, inds in GROUPS.items():
        g = tab.loc[[i for i in inds if i in tab.index]]
        mean = g["b1_ixic_res"].mean()
        se_g = g["b1_ixic_res"].std(ddof=1) / np.sqrt(len(g))
        print(f"  {grp:<12} mean_b1={mean:+.4f}  se={se_g:.4f}  n_ind={len(g)}  "
              f"industries: {', '.join(g.index.tolist())}")

    t_ind = tab.loc[[i for i in GROUPS["tech"] if i in tab.index]]
    tr_ind = tab.loc[[i for i in GROUPS["traditional"] if i in tab.index]]
    diff = t_ind["b1_ixic_res"].mean() - tr_ind["b1_ixic_res"].mean()
    se_pool = float(np.sqrt(t_ind["b1_ixic_res"].var(ddof=1) / len(t_ind) +
                            tr_ind["b1_ixic_res"].var(ddof=1) / len(tr_ind)))
    print(f"\n  matched test: b1(tech) - b1(traditional) = {diff:+.4f}  (pooled t = {diff/se_pool:+.2f})")


if __name__ == "__main__":
    main()
