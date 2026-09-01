#!/usr/bin/env python3
"""US overnight -> A-share next-day conduction analysis v1 (protocol v1, P1/P2).

Implements research/protocols/us_market_overnight_conduction_protocol_v1.md:
  5.1 calendar pairing (information-window & single-day), 5.2 A-share returns,
  P1 main test (SPX -> SH000300, M1 gap / M2 intraday / M3 c2c, Newey-West),
  P2 robustness (other US indices, size indices, sub-periods, asymmetry,
  state stratification, rolling correlation).

Usage (conda activate qlib):
    python scripts/analyze_us_overnight_conduction_v1.py
Outputs -> output/analysis_static/us_overnight_conduction_v1/
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd
import qlib
from qlib.config import REG_CN
from qlib.data import D

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "output/analysis_static/us_overnight_conduction_v1"
US_CSV = ROOT / "data/external/tushare/us_index_v1/normalized/us_index.csv.gz"
QLIB_DIR = Path.home() / ".qlib/qlib_data/cn_data_2026"
BENCH_MAIN = "SH000300"
MAIN_US = "SPX"
MAIN_START = "2016-01-01"
SUBPERIODS = {
    "2016-2019": ("2016-01-01", "2019-12-31"),
    "2020-2021": ("2020-01-01", "2021-12-31"),
    "2022": ("2022-01-01", "2022-12-31"),
    "2023-2026": ("2023-01-01", "2099-12-31"),
}
ALL_US = ["SPX", "IXIC", "DJI", "RUT"]
SIZE_INDEX = {"SH000852": "csi1000", "SH000905": "csi500"}
NW_LAGS = 5


def newey_west_beta(x: np.ndarray, y: np.ndarray, lags: int = NW_LAGS) -> dict:
    """OLS with Newey-West (HAC) standard errors; returns beta, se, t, r2, n."""
    x = np.asarray(x, float)
    y = np.asarray(y, float)
    mask = np.isfinite(x) & np.isfinite(y)
    x, y = x[mask], y[mask]
    n = len(x)
    if n < 30:
        return {"beta": np.nan, "se": np.nan, "t": np.nan, "r2": np.nan, "n": n}
    X = np.column_stack([np.ones(n), x])
    XtX_inv = np.linalg.inv(X.T @ X)
    b = XtX_inv @ X.T @ y
    e = y - X @ b
    # Newey-West (HAC) sandwich variance with Bartlett kernel, lag=NW_LAGS
    E = X * e[:, None]
    S0 = (E.T @ E) / n
    G = np.zeros((X.shape[1], X.shape[1]))
    for lag in range(1, lags + 1):
        w = 1 - lag / (lags + 1)
        Gm = (E[lag:].T @ E[:-lag]) / n
        G += w * (Gm + Gm.T)
    S = S0 + G
    # classic HAC: Var = (X'X)^-1 [n*S] (X'X)^-1, S already 1/n-normalized
    cov = XtX_inv @ (n * S) @ XtX_inv
    se = np.sqrt(np.diag(cov))
    t = b / se
    ybar = y.mean()
    r2 = 1 - (e @ e) / ((y - ybar) @ (y - ybar))
    return {"beta": float(b[1]), "se": float(se[1]), "t": float(t[1]),
            "r2": float(r2), "n": n}


def subdict(keys: list, res: dict) -> dict:
    return {k: res.get(k, np.nan) for k in keys}


def make_panel(us_piv: pd.DataFrame, a_ret: pd.DataFrame) -> pd.DataFrame:
    """For each A-share trading day, window/single R_us and A-share gap/c2c/intraday.

    us_piv: index=us trade_date, columns=US index close (per one index)
    a_ret:  index=A-share trade_date, columns={open, close_pre, c2c...} - raw closes
    """
    us_dates = pd.DatetimeIndex(us_piv.index.dropna().sort_values())
    a_dates = pd.DatetimeIndex(a_ret.index.dropna().sort_values())
    rows = []
    for i, d in enumerate(a_dates):
        if i == 0:
            continue
        d_prev = a_dates[i - 1]
        # window: US dates x with d_prev <= x <= d-1  (US day x closes x+1 early-morning CST)
        win = us_dates[(us_dates >= d_prev) & (us_dates < d)]
        if len(win) == 0:
            continue
        u_last = win[-1]
        if u_last == us_dates[0]:
            continue
        u_before = us_dates[us_dates < d_prev]
        if len(u_before) == 0:
            continue
        u_before_last = u_before[-1]
        c_last = float(us_piv.loc[u_last, "close"])
        c_before = float(us_piv.loc[u_before_last, "close"])
        if not (np.isfinite(c_last) and np.isfinite(c_before) and c_before > 0):
            continue
        r_window = c_last / c_before - 1
        # single-day: previous US day
        us_idx = us_dates.get_loc(u_last)
        r_single = np.nan
        if us_idx >= 1:
            c_pu = float(us_piv.loc[us_dates[us_idx - 1], "close"])
            if np.isfinite(c_pu) and c_pu > 0:
                r_single = c_last / c_pu - 1
        row = a_ret.loc[d]
        o = float(row["open"])
        c = float(row["close"])
        c_p = float(row["close_prev"])
        if not all(np.isfinite([o, c, c_p])) or c_p <= 0:
            continue
        rows.append({
            "a_date": d, "d_prev": d_prev, "n_window": len(win),
            "r_us_window": r_window, "r_us_single": r_single,
            "gap": o / c_p - 1, "c2c": c / c_p - 1, "intraday": c / o - 1,
        })
    return pd.DataFrame(rows)


def load_a_shares(codes: list[str]) -> dict[str, pd.DataFrame]:
    qlib.init(provider_uri=str(QLIB_DIR), region=REG_CN)
    df = D.features(codes, ["$close", "$open"], start_time="2010-01-01",
                    end_time="2026-12-31", freq="day")
    out = {}
    for code in codes:
        sub = df.xs(code, level="instrument").sort_index()
        sub = sub.reset_index()
        sub = sub.rename(columns={"datetime": "date", "$close": "close", "$open": "open"})
        sub["date"] = pd.to_datetime(sub["date"])
        sub = sub.set_index("date")
        out[code] = sub
    return out


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    us = pd.read_csv(US_CSV, compression="gzip")
    us["trade_date"] = pd.to_datetime(us["trade_date"])
    print(f"[data] US rows={len(us)}, codes={us['ts_code'].unique().tolist()}")

    a_data = load_a_shares([BENCH_MAIN] + list(SIZE_INDEX))
    cal = pd.DatetimeIndex(pd.to_datetime(
        pd.read_csv(QLIB_DIR / "calendars/day.txt", header=None)[0]))

    def a_frame(code: str) -> pd.DataFrame:
        df = a_data[code]
        df = df.copy()
        df["close_prev"] = df["close"].shift(1)
        return df

    # ---------------- P1 main: SPX -> SH000300 ----------------
    spx_piv = us[us["ts_code"] == MAIN_US].set_index("trade_date")[["close"]]
    main_panel = make_panel(spx_piv, a_frame(BENCH_MAIN))
    main_panel["a_date"] = pd.to_datetime(main_panel["a_date"])
    print(f"[panel] SPX->{BENCH_MAIN}: {len(main_panel)} paired days "
          f"({main_panel['a_date'].min().date()}~{main_panel['a_date'].max().date()})")

    full = main_panel[main_panel["a_date"] >= MAIN_START].copy()
    rows = []
    for dep in ["gap", "intraday", "c2c"]:
        for period, (s, e) in {"full": (MAIN_START, "2099-01-01"), **SUBPERIODS}.items():
            sub = full[(full["a_date"] >= s) & (full["a_date"] <= e)] if period != "full" else full
            res = newey_west_beta(sub["r_us_window"].values, sub[dep].values)
            rows.append({"period": period, "dep": dep, **subdict(["beta", "se", "t", "r2", "n"], res)})
    tab_main = pd.DataFrame(rows)
    tab_main.to_csv(OUT / "P1_main_SPX_SH000300.csv", index=False)

    # ---------------- P2a: other US indices -> SH000300 ----------------
    rows = []
    for code in ALL_US:
        piv = us[us["ts_code"] == code].set_index("trade_date")[["close"]]
        panel = make_panel(piv, a_frame(BENCH_MAIN))
        panel = panel[panel["a_date"] >= MAIN_START]
        for dep in ["gap", "intraday"]:
            res = newey_west_beta(panel["r_us_window"].values, panel[dep].values)
            rows.append({"us_index": code, "a_index": BENCH_MAIN, "dep": dep,
                         **subdict(["beta", "se", "t", "r2", "n"], res)})
    tab_combos = pd.DataFrame(rows)
    tab_combos.to_csv(OUT / "P2a_index_combos.csv", index=False)

    # ---------------- P2b: SPX -> size indices ----------------
    rows = []
    for code in SIZE_INDEX:
        panel = make_panel(spx_piv, a_frame(code))
        panel = panel[panel["a_date"] >= MAIN_START]
        for dep in ["gap", "intraday"]:
            res = newey_west_beta(panel["r_us_window"].values, panel[dep].values)
            rows.append({"a_index": code, "dep": dep, **subdict(["beta", "se", "t", "r2", "n"], res)})
    tab_size = pd.DataFrame(rows)
    tab_size.to_csv(OUT / "P2b_size_indices.csv", index=False)

    # ---------------- P2c: asymmetry (U_down < -0.5%) ----------------
    x = full["r_us_window"].values
    up = (x >= -0.005).astype(float)
    inter = x * (1 - up)  # interaction: x on down days only
    rows = []
    for dep in ["gap", "intraday", "c2c"]:
        y = full[dep].values
        m = np.isfinite(x) & np.isfinite(y) & np.isfinite(inter)
        X = np.column_stack([np.ones(m.sum()), x[m], (1 - up[m]), x[m] * (1 - up[m])])
        yy = y[m]
        b, *_ = np.linalg.lstsq(X, yy, rcond=None)
        e = yy - X @ b
        n = len(yy)
        nobs = int(n)
        # naive OLS se for the interaction (report only direction/magnitude)
        XtX_inv = np.linalg.inv(X.T @ X)
        se = np.sqrt(np.diag(XtX_inv * (e @ e / (n - X.shape[1]))))
        rows.append({"dep": dep, "beta_up": float(b[1]), "t_up": float(b[1] / se[1]),
                     "down_slope_extra": float(b[3]), "t_extra": float(b[3] / se[3]),
                     "down_intercept": float(b[2]), "n": nobs})
    tab_asym = pd.DataFrame(rows)
    tab_asym.to_csv(OUT / "P2c_asymmetry.csv", index=False)

    # ---------------- P2d: state stratification (pre-registered) ----------------
    a300 = a_frame(BENCH_MAIN)
    c2c_300 = (a300["close"] / a300["close_prev"] - 1)
    vol20 = c2c_300.rolling(20).std() * np.sqrt(252)
    vol_med = vol20.median()
    spx_close = spx_piv["close"]
    spx_ma = spx_close.rolling(60).mean()
    rows = []
    for dep in ["gap", "intraday"]:
        for state, mask in [
            ("vol_high", vol20.reindex(full["a_date"]).values > vol_med),
            ("vol_low", vol20.reindex(full["a_date"]).values <= vol_med),
        ]:
            sub = full[mask]
            res = newey_west_beta(sub["r_us_window"].values, sub[dep].values)
            rows.append({"state": state, "dep": dep, **subdict(["beta", "se", "t", "n"], res)})
        # us_trend by mapping u_last
        trend_sig = []
        for _, r in full.iterrows():
            u = spx_close.index[spx_close.index <= r["a_date"] - pd.Timedelta(days=1)]
            if len(u) > 60:
                c = spx_close.loc[u[-1]]
                trend_sig.append(c > spx_ma.loc[u[-1]])
            else:
                trend_sig.append(np.nan)
        full_t = full.copy()
        full_t["us_trend_up"] = trend_sig
        for state, mask in [("us_trend_up", True), ("us_trend_down", False)]:
            sub = full_t[full_t["us_trend_up"] == mask]
            res = newey_west_beta(sub["r_us_window"].values, sub[dep].values)
            rows.append({"state": state, "dep": dep, **subdict(["beta", "se", "t", "n"], res)})
    tab_states = pd.DataFrame(rows)
    tab_states.to_csv(OUT / "P2d_states.csv", index=False)

    # ---------------- P2e: rolling correlation ----------------
    rolls = []
    for dep in ["gap", "intraday", "c2c"]:
        w = 120
        rc = full["r_us_window"].rolling(w).corr(full[dep])
        rolls.append(pd.DataFrame({"date": full["a_date"], "dep": dep, "corr": rc.values}, index=None))
    tab_roll = pd.concat(rolls, ignore_index=True)
    tab_roll.to_csv(OUT / "P2e_rolling_corr.csv", index=False)

    # ---------------- diagnostics ----------------
    diag = {
        "paired_days": len(main_panel),
        "main_sample_days": len(full),
        "n_window_gt1_share": float((main_panel["n_window"] > 1).mean()),
        "r_us_window_mean_pct": float(full["r_us_window"].mean() * 100),
        "r_us_window_std_pct": float(full["r_us_window"].std() * 100),
        "gap_mean_bp": float(full["gap"].mean() * 10000),
        "gap_std_pct": float(full["gap"].std() * 100),
    }
    pd.Series(diag).to_csv(OUT / "diagnostics.csv")

    print("\n===== P1 main: SPX -> SH000300 (beta; t) =====")
    piv = tab_main.pivot(index="dep", columns="period", values="t")
    print(tab_main[["period", "dep", "beta", "t", "r2", "n"]].to_string(index=False))
    print("\n===== P2a combos (intraday beta; t) =====")
    print(tab_combos[tab_combos["dep"] == "intraday"][["us_index", "beta", "t", "n"]].to_string(index=False))
    print("\n===== P2b size =====")
    print(tab_size.to_string(index=False))
    print("\n===== P2c asymmetry =====")
    print(tab_asym.to_string(index=False))
    print("\n===== P2d states (intraday) =====")
    print(tab_states[tab_states["dep"] == "intraday"].to_string(index=False))
    print("\n===== diagnostics =====")
    print(pd.Series(diag).to_string())


if __name__ == "__main__":
    main()
