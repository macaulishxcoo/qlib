#!/usr/bin/env python3
"""Factor attribution v2 for the v8 value/quality top-15 strategy.

Fixes vs v1 (analyze_factor_attribution_v1.py), whose regression was void:
  - BUG (v1): factor return indexed on formation day t but holding the (t, t+1]
    return, while strategy return at day t is (t-1, t].  The one-day mismatch
    zeroed all betas (R^2 ~ 0.0005) and the "alpha" was just the raw mean.
    v2 aligns both series on the holding day.
  - v1 sampled 2000 stocks for factor construction; v2 uses the full universe.
  - v2 adds MKT (market excess) and a coaxial composite-value leg (CVW) built
    from the v8 panel's own neutral_composite (same axis as the strategy), plus
    a low-volatility leg (LMV).  HML here uses daily BM=1/PB.
  - v2 clusters standard errors (Newey-West, ~10 lags).

Regression (per stage):  excess_t = a + b_m*MKT + b_h*HML + b_s*SMB + b_mom*MOM
                          + b_c*CVW + b_l*LMV + e_t
alpha is the intercept; annualized x238.

Usage:
  python scripts/analyze_factor_attribution_v2.py [--output-dir DIR]
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
import pandas as pd
import qlib
from qlib.config import REG_CN
from qlib.data import D
from scipy import stats

QLIB_DIR = Path.home() / ".qlib/qlib_data/cn_data_2026"
DAILY_BASIC = Path("data/external/tushare/a_share_daily_basic_pit_v1/normalized/daily_basic.csv.gz")
V8_PANEL = Path("output/analysis_fundamental/a_share_value_quality_monthly_strategy_v8_top15/monthly_composite_top15.csv.gz")
BENCH_QLIB = "SH000852"
BENCH_TS = "000852.SH"
BT_START = pd.Timestamp("2015-12-01")  # buffer for 20d momentum
BT_END = pd.Timestamp("2026-06-30")
STAGES = {
    "development": ("2016-01-01", "2019-12-31"),
    "confirmation": ("2020-01-01", "2022-12-31"),
    "holdout": ("2023-01-01", "2025-06-30"),
    "new_coverage": ("2025-07-01", "2026-06-30"),
    "full": ("2016-01-01", "2026-06-30"),
}
ANNUAL_DAYS = 238
NW_LAGS = 10
FACTOR_COLS = ["MKT", "HML", "SMB", "MOM", "CVW", "LMV"]


def qlib_symbol(code: str) -> str:
    n, s = code.split(".")
    return f"{s}{n}"


def ts_symbol(qcode: str) -> str:
    return f"{qcode[2:]}.{qcode[:2]}"


def load_calendar() -> pd.DatetimeIndex:
    return pd.DatetimeIndex(pd.to_datetime(pd.read_csv(QLIB_DIR / "calendars" / "day.txt", header=None)[0]))


def load_close_wide(cal: pd.DatetimeIndex) -> pd.DataFrame:
    """Full-universe close, wide (index=day, columns=ts_code)."""
    all_inst = D.list_instruments(D.instruments("all"), as_list=True)
    frames = []
    for year in range(2015, 2027):
        frames.append(D.features(all_inst, ["$close"], start_time=f"{year}-01-01", end_time=f"{year}-12-31", freq="day"))
    raw = pd.concat(frames)["$close"].unstack(level="instrument")
    raw = raw.reindex(cal)
    raw.columns = [ts_symbol(c) for c in raw.columns]
    return raw


def strategy_daily_excess(close_wide: pd.DataFrame, panel: pd.DataFrame, cal: pd.DatetimeIndex) -> pd.Series:
    """v8 top-15 equal-weight daily excess vs SH000852, holdings from month t-1."""
    top15 = {pd.Timestamp(d): g.dropna(subset=["neutral_composite"]).nlargest(15, "neutral_composite")["ts_code"].tolist()
             for d, g in panel.groupby("rebalance_date")}
    rets = close_wide.pct_change(fill_method=None)
    bench = rets[BENCH_TS] if BENCH_TS in rets.columns else None
    rdates = sorted(top15.keys())
    rows = []
    cur = None
    for t in cal:
        if t > BT_END:
            break
        prior = [d for d in rdates if d <= t]
        cur = top15[prior[-1]] if prior else cur
        if cur is None or t not in rets.index:
            continue
        port = float(np.nanmean(rets.loc[t].reindex(cur).to_numpy(dtype=float)))
        b = float(bench.loc[t]) if bench is not None and pd.notna(bench.loc[t]) else np.nan
        rows.append({"date": t, "excess": port - b})
    return pd.DataFrame(rows).set_index("date")["excess"]


def factor_daily_returns(close_wide: pd.DataFrame, cal: pd.DatetimeIndex, panel: pd.DataFrame) -> pd.DataFrame:
    """Daily factor returns, INDEXED ON THE HOLDING DAY t (formation at t-1).

    This is the v1 fix: portfolio formed with info up to day t-1 close earns
    the (t-1, t] return, stored at index t -- same convention as the strategy
    series, so a plain join aligns them.
    """
    rets = close_wide.pct_change(fill_method=None)
    mom20 = rets.rolling(20, min_periods=15).sum()
    bench_ret = rets[BENCH_TS]

    db = pd.read_csv(DAILY_BASIC, compression="gzip", usecols=["ts_code", "trade_date", "total_mv", "pb"])
    db["trade_date"] = pd.to_datetime(db["trade_date"].astype(str), format="%Y%m%d")
    db = db[(db["trade_date"] >= BT_START) & (db["trade_date"] <= BT_END)]
    db["bm"] = 1.0 / db["pb"].clip(lower=0.01)
    db["log_mv"] = np.log(db["total_mv"].astype(float))
    db_by_day = {d: g.set_index("ts_code")[["bm", "log_mv"]] for d, g in db.groupby("trade_date")}

    # CVW: coaxial value leg from the strategy's own monthly neutral_composite
    cvw_scores = {}
    for d, g in panel.groupby("rebalance_date"):
        scores = g.dropna(subset=["neutral_composite"]).set_index("ts_code")["neutral_composite"]
        cvw_scores[pd.Timestamp(d)] = scores
    cvw_dates = sorted(cvw_scores.keys())

    rows = []
    cal_pos = {t: i for i, t in enumerate(cal)}
    for i in range(1, len(cal)):
        t = cal[i]
        t_prev = cal[i - 1]
        if t > BT_END or t not in rets.index or t_prev not in rets.index:
            continue
        day_ret = rets.loc[t]                      # holding-day return (t-1, t]
        prev_db = db_by_day.get(t_prev)            # formation info at t-1
        if prev_db is None or len(prev_db) < 200:
            continue

        universe = prev_db.index.intersection(day_ret.dropna().index)
        if len(universe) < 200:
            continue
        info = prev_db.loc[universe]
        r = day_ret.loc[universe].astype(float)

        def leg_hi_lo(sort_col: pd.Series, hi_mask: pd.Series, lo_mask: pd.Series) -> float:
            hi = r[hi_mask.reindex(r.index).fillna(False)].dropna()
            lo = r[lo_mask.reindex(r.index).fillna(False)].dropna()
            return float(hi.mean() - lo.mean()) if len(hi) > 10 and len(lo) > 10 else np.nan

        q = info["bm"].quantile([0.30, 0.70])
        hml = leg_hi_lo(info["bm"], info["bm"] >= q[0.70], info["bm"] <= q[0.30])

        sq = info["log_mv"].quantile([0.30, 0.70])
        smb = leg_hi_lo(info["log_mv"], info["log_mv"] <= sq[0.30], info["log_mv"] >= sq[0.70])

        m = mom20.loc[t_prev].reindex(universe)
        mq = m.quantile([0.30, 0.70])
        mom = leg_hi_lo(m, m >= mq[0.70], m <= mq[0.30]) if m.notna().sum() > 200 else np.nan

        # LMV: 60d low-vol leg (formation: vol up to t-1; return on t)
        vol60 = rets.loc[:t_prev].tail(61).std()
        v = vol60.reindex(universe)
        vq = v.quantile([0.30, 0.70])
        lmv = leg_hi_lo(v, v <= vq[0.30], v >= vq[0.70]) if v.notna().sum() > 200 else np.nan

        # CVW: coaxial leg (top/bottom 20% neutral_composite from the last rebalance <= t-1)
        prior_cv = [d for d in cvw_dates if d <= t_prev]
        cvw = np.nan
        if prior_cv:
            scores = cvw_scores[prior_cv[-1]]
            common = scores.index.intersection(universe)
            if len(common) > 100:
                s = scores.loc[common]
                cq = s.quantile([0.20, 0.80])
                hi = r.loc[s[s >= cq[0.80]].index.intersection(r.index)].dropna()
                lo = r.loc[s[s <= cq[0.20]].index.intersection(r.index)].dropna()
                if len(hi) > 10 and len(lo) > 10:
                    cvw = float(hi.mean() - lo.mean())

        mkt = float(r.mean() - day_ret[BENCH_TS]) if BENCH_TS in day_ret.index and pd.notna(day_ret[BENCH_TS]) else np.nan

        rows.append({"date": t, "MKT": mkt, "HML": hml, "SMB": smb, "MOM": mom, "CVW": cvw, "LMV": lmv})

    return pd.DataFrame(rows).set_index("date")


def newey_west_t(y: np.ndarray, X: np.ndarray, lags: int) -> tuple[np.ndarray, np.ndarray]:
    """OLS with Newey-West HAC standard errors. X already includes constant."""
    n, k = X.shape
    beta, *_ = np.linalg.lstsq(X, y, rcond=None)
    resid = y - X @ beta
    XtX_inv = np.linalg.inv(X.T @ X)
    # Meat: S0 + sum_w w * (S_w + S_w')
    S = (X * resid[:, None]).T @ (X * resid[:, None])
    for w in range(1, min(lags, n - 1) + 1):
        G = (X[w:] * resid[w:, None]).T @ (X[:-w] * resid[:-w, None])
        S += (1.0 - w / (lags + 1.0)) * (G + G.T)
    cov = XtX_inv @ S @ XtX_inv
    se = np.sqrt(np.diag(cov))
    return beta, beta / se


def run_regression(excess: pd.Series, factors: pd.DataFrame, label: str, start: str, end: str) -> dict:
    seg = excess.loc[start:end]
    aligned = pd.DataFrame({"excess": seg}).join(factors.loc[start:end]).dropna()
    if len(aligned) < 60:
        return {"label": label, "n": len(aligned), "error": "insufficient data"}
    y = aligned["excess"].to_numpy(dtype=float)
    X = np.column_stack([np.ones(len(aligned))] + [aligned[c].to_numpy(dtype=float) for c in FACTOR_COLS])
    beta, t = newey_west_t(y, X, NW_LAGS)
    y_pred = X @ beta
    ss_res = float(np.sum((y - y_pred) ** 2))
    ss_tot = float(np.sum((y - y.mean()) ** 2))
    n, k = X.shape
    pvals = 2 * (1 - stats.t.cdf(np.abs(t), df=n - k))
    out = {"label": label, "n": n,
           "alpha_daily": float(beta[0]), "alpha_annual": float(beta[0] * ANNUAL_DAYS),
           "alpha_t": float(t[0]), "alpha_pvalue": float(pvals[0])}
    for j, c in enumerate(FACTOR_COLS, start=1):
        out[f"{c.lower()}_beta"] = float(beta[j])
        out[f"{c.lower()}_t"] = float(t[j])
        out[f"{c.lower()}_pvalue"] = float(pvals[j])
    out["r_squared"] = 1 - ss_res / ss_tot if ss_tot > 0 else np.nan
    # correlation of strategy excess with each factor for sanity
    for c in FACTOR_COLS:
        out[f"corr_{c.lower()}"] = float(aligned["excess"].corr(aligned[c]))
    return out


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path,
                        default=Path("output/analysis_static/a_share_factor_attribution_v2"))
    args = parser.parse_args()
    out = args.output_dir
    if out.exists() and any(out.iterdir()):
        raise FileExistsError(f"Refusing to overwrite existing experiment output: {out}")
    out.mkdir(parents=True, exist_ok=True)

    qlib.init(provider_uri=str(QLIB_DIR), region=REG_CN)
    cal = load_calendar()

    print("[1/4] Loading full-universe close prices ...", flush=True)
    close_wide = load_close_wide(cal)
    print(f"      {close_wide.shape[1]} instruments x {close_wide.shape[0]} days", flush=True)

    print("[2/4] Reconstructing v8 strategy daily excess ...", flush=True)
    panel = pd.read_csv(V8_PANEL, compression="gzip")
    panel["rebalance_date"] = pd.to_datetime(panel["rebalance_date"])
    excess = strategy_daily_excess(close_wide, panel, cal)
    print(f"      {len(excess)} days {excess.index.min().date()}~{excess.index.max().date()}", flush=True)

    print("[3/4] Constructing daily factor returns (aligned on holding day) ...", flush=True)
    factors = factor_daily_returns(close_wide, cal, panel)
    print(f"      {len(factors)} factor days; NaN ratio: "
          + ", ".join(f"{c}={factors[c].isna().mean():.1%}" for c in FACTOR_COLS), flush=True)
    factors.to_csv(out / "factor_returns_daily.csv.gz", compression="gzip")
    excess.rename("excess").to_csv(out / "strategy_excess_daily.csv")

    print("[4/4] Regressions by stage (Newey-West {} lags) ...".format(NW_LAGS), flush=True)
    results = [run_regression(excess, factors, stage, s, e) for stage, (s, e) in STAGES.items()]
    res_df = pd.DataFrame(results)
    res_df.to_csv(out / "attribution_by_stage.csv", index=False)

    show_cols = ["label", "n", "alpha_annual", "alpha_t", "alpha_pvalue", "r_squared"] + \
                [f"{c.lower()}_beta" for c in FACTOR_COLS] + [f"{c.lower()}_t" for c in FACTOR_COLS]
    print(res_df[show_cols].to_string(index=False), flush=True)

    full = next(r for r in results if r["label"] == "full")
    holdout = next(r for r in results if r["label"] == "holdout")
    alpha_sig = full["alpha_pvalue"] < 0.05 and full["alpha_annual"] > 0
    if alpha_sig:
        interp = "策略存在统计显著的 pure alpha（扣除 MKT/HML/SMB/MOM/CVW/LMV 后仍有真实选股能力）"
    elif full["alpha_annual"] > 0 and full["alpha_pvalue"] < 0.10:
        interp = "策略存在弱显著 pure alpha（p<0.10），证据不强"
    else:
        interp = "策略超额收益可被风格/因子暴露解释，pure alpha 不显著"

    decision = {
        "interpretation": interp,
        "full": {k: full.get(k) for k in ["n", "alpha_annual", "alpha_t", "alpha_pvalue", "r_squared"]},
        "holdout": {k: holdout.get(k) for k in ["n", "alpha_annual", "alpha_t", "alpha_pvalue", "r_squared"]},
        "method_note": "v2 fixes v1's one-day factor/strategy misalignment; factors indexed on holding day; "
                       "full universe; Newey-West(10) standard errors; adds MKT/CVW/LMV legs.",
        "v1_bug": "v1 factor returns indexed on formation day while holding next-day return; join vs strategy "
                  "return was misaligned by one day; all betas ~0 (R^2=0.0005); alpha==raw mean excess.",
    }
    (out / "decision.json").write_text(json.dumps(decision, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"\n结论：{interp}", flush=True)


if __name__ == "__main__":
    main()
