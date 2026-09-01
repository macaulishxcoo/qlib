#!/usr/bin/env python3
"""P3: industry-level US overnight conduction (protocol v1, H4 test).

For each SW L1 industry, regress industry gap / intraday / c2c on the US
overnight window return (per US index).  Tests the pre-registered
hypothesis H4 "sector-matched transmission": tech-chain (IXIC-weighted)
should show stronger gap response than traditional (DJI-weighted) if the
channel is compositional; if IXIC/DJI responses are uniform, the channel
is a market-level risk premium.

Pre-registered mapping (protocol §6 P3, adjusted for data availability:
  - '电子' index is absent from sw_industry_daily -> tech chain =
    {计算机, 通信, 传媒}
  - traditional = {银行, 非银金融, 采掘, 化工, 钢铁}
  - defensive  = {医药生物, 食品饮料, 公用事业}

Usage (conda activate qlib):
    python scripts/analyze_us_overnight_industry_v1.py
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
US_ALL = ["SPX", "IXIC", "DJI", "RUT"]
GROUPS = {
    "tech": ["计算机", "通信", "传媒"],
    "traditional": ["银行", "非银金融", "采掘", "化工", "钢铁"],
    "defensive": ["医药生物", "食品饮料", "公用事业"],
}


def build_us_window_maps(us: pd.DataFrame) -> dict[str, pd.DataFrame]:
    """R_us_window per A-share date for each US index (shared across industries)."""
    maps = {}
    for code in US_ALL:
        piv = us[us["ts_code"] == code].set_index("trade_date")[["close"]]
        # use any industry calendar; only date alignment is reused
        cal = pd.read_csv(ROOT / "data/external/tushare/sw_industry_index_v1/normalized/sw_industry_daily.csv.gz",
                          compression="gzip", usecols=["trade_date"])
        cal = pd.DatetimeIndex(pd.to_datetime(cal["trade_date"].astype(str),
                                              format="%Y%m%d").dropna().unique())
        cal = cal.sort_values()
        us_dates = pd.DatetimeIndex(piv.index.sort_values())
        rows = []
        for i, d in enumerate(cal):
            if i == 0:
                continue
            d_prev = cal[i - 1]
            win = us_dates[(us_dates >= d_prev) & (us_dates < d)]
            if len(win) == 0:
                continue
            u_last = win[-1]
            u_before = us_dates[us_dates < d_prev]
            if len(u_before) == 0:
                continue
            c_last = float(piv.loc[u_last, "close"])
            c_before = float(piv.loc[u_before[-1], "close"])
            if not (np.isfinite(c_last) and np.isfinite(c_before) and c_before > 0):
                continue
            rows.append({"a_date": d, "r_us": c_last / c_before - 1})
        maps[code] = pd.DataFrame(rows)
    return maps


def main() -> None:
    sw = pd.read_csv(SW_CSV, compression="gzip", parse_dates=["trade_date"])
    us = pd.read_csv(US_CSV, compression="gzip", parse_dates=["trade_date"])
    print(f"[data] SW rows={len(sw)} ({sw['trade_date'].min().date()}~{sw['trade_date'].max().date()}); "
          f"US codes={us['ts_code'].unique().tolist()}")

    maps = build_us_window_maps(us)

    rows = []
    for ind, sub in sw.groupby("industry_name"):
        sub = sub.sort_values("trade_date").set_index("trade_date").copy()
        sub["gap"] = sub["open"] / sub["close"].shift(1) - 1
        sub["c2c"] = sub["close"] / sub["close"].shift(1) - 1
        sub["intraday"] = sub["close"] / sub["open"] - 1
        sub = sub[sub.index >= START]
        for code in US_ALL:
            m = pd.merge(sub.reset_index()[["trade_date", "gap", "c2c", "intraday"]],
                         maps[code], left_on="trade_date", right_on="a_date", how="inner")
            for dep in ["gap", "intraday", "c2c"]:
                res = newey_west_beta(m["r_us"].values, m[dep].values)
                rows.append({"industry": ind, "us_index": code, "dep": dep, **res})
    tab = pd.DataFrame(rows)
    tab.to_csv(OUT / "P3_industry_regressions.csv", index=False)

    # group summaries (gap is the informative layer)
    tab["group"] = tab["industry"].map(
        {i: g for g, inds in GROUPS.items() for i in inds}).fillna("other")
    g = tab[(tab["dep"] == "gap") & (tab["group"] != "other")]
    summ = g.groupby(["group", "us_index"])["beta"].agg(["mean", "count"]).reset_index()
    summ.to_csv(OUT / "P3_group_summary.csv", index=False)

    print("\n===== P3a: industry gap beta (full sample, per US index) =====")
    piv = tab[tab["dep"] == "gap"].pivot(index="industry", columns="us_index", values="beta")
    piv = piv.reindex(columns=US_ALL)
    print(piv.round(3).to_string())

    print("\n===== P3b: group mean gap beta =====")
    print(summ.round(3).to_string(index=False))

    # differential: IXIC-DJI spread by group
    pivT = tab[tab["dep"] == "gap"].pivot(index="industry", columns="us_index", values="beta")
    for grp, inds in GROUPS.items():
        s = pivT.loc[[i for i in inds if i in pivT.index]]
        print(f"  {grp}: mean IXIC={s['IXIC'].mean():.3f} DJI={s['DJI'].mean():.3f} "
              f"spread={s['IXIC'].mean()-s['DJI'].mean():+.3f} "
              f"(n_industries={len(s)})")

    # matched vs unmatched: tech group responding to IXIC vs traditional responding to DJI
    tech = pivT.loc[[i for i in GROUPS["tech"] if i in pivT.index]]
    trad = pivT.loc[[i for i in GROUPS["traditional"] if i in pivT.index]]
    print(f"\n tech(IXIC)={tech['IXIC'].mean():.3f} vs tech(DJI)={tech['DJI'].mean():.3f} "
          f"| trad(IXIC)={trad['IXIC'].mean():.3f} vs trad(DJI)={trad['DJI'].mean():.3f}")
    print(f" matched-minus-unmatched spread delta = "
          f"{(tech['IXIC'].mean()-tech['DJI'].mean())-(trad['IXIC'].mean()-trad['DJI'].mean()):+.3f}")

    top = pivT.assign(spread=pivT["IXIC"] - pivT["DJI"]).sort_values("SPX", ascending=False)
    print("\n===== P3c: top/bottom sectors by SPX gap beta + IXIC-DJI spread =====")
    print(top.head(5).round(3).to_string())
    print(top.tail(3).round(3).to_string())


if __name__ == "__main__":
    main()
