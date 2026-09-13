#!/usr/bin/env python3
"""Short-interest (融券) signal test -- protocol v1.

Protocol: research/protocols/a_share_short_interest_signal_protocol_v1.md
Frozen before data. Answers three questions only:

  Q1  is the signal aligned to its disclosure lag (T-1 visible at T)?
  Q2  does it carry cross-sectional directional information (RankIC / ICIR)?
  Q3  is it orthogonal to the price-volume factors and to rzye?

Labels are open-to-open per the project's label discipline:
    label_h(t) = open(t+1+h) / open(t+1) - 1

Writes to output/analysis_fundamental/a_share_short_interest_signal_v1/.
"""

from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
MARGIN = ROOT / "data/external/tushare/margin_pit_v1/normalized/margin_detail.csv.gz"
DAILY_BASIC = ROOT / "data/external/tushare/a_share_daily_basic_pit_v1/normalized/daily_basic.csv.gz"
QLIB_DIR = Path.home() / ".qlib/qlib_data/cn_data_2026"
OUT = ROOT / "output/analysis_fundamental/a_share_short_interest_signal_v1"

WARMUP_START = "2015-01-01"
SAMPLE_START = "2018-01-01"
SAMPLE_END = "2026-06-30"
HORIZONS = (1, 5, 10, 20)
PRIMARY_HORIZON = 5
ZSCORE_WINDOW = 250
ZSCORE_MIN = 60
MIN_NAMES_PER_DATE = 30
LAG_TOLERANCE = 0.30          # |IC| loss allowed before declaring a look-ahead dependency
ORTHOGONALITY_LIMIT = 0.40
IC_MIN = 0.05
ICIR_MIN = 0.5
SECONDARY_IC_MIN = 0.03
SECONDARY_MIN_HITS = 2

SIGNALS = ("short_ratio", "short_z", "short_chg20", "short_flow")
PV_FACTORS = ("turnover_rate", "volume_ratio", "mom20", "vol20", "rzye_z")


def log(message: str) -> None:
    print(message, flush=True)


def ts_to_qlib(ts_code: str) -> str | None:
    if not isinstance(ts_code, str) or "." not in ts_code:
        return None
    number, suffix = ts_code.split(".", 1)
    if suffix not in {"SH", "SZ", "BJ"}:
        return None
    return f"{suffix}{number}"


def qlib_to_ts(symbol: str) -> str:
    return f"{symbol[2:]}.{symbol[:2]}"


def main() -> int:
    import qlib
    from qlib.config import REG_CN
    from qlib.data import D

    if OUT.exists() and any(OUT.iterdir()):
        raise SystemExit(f"refusing to overwrite existing output: {OUT}")
    OUT.mkdir(parents=True, exist_ok=True)

    started = datetime.now(timezone.utc)
    qlib.init(provider_uri=str(QLIB_DIR), region=REG_CN)

    # ------------------------------------------------------------------ #
    log("[1/6] loading margin data")
    margin = pd.read_csv(
        MARGIN, compression="gzip",
        usecols=["trade_date", "ts_code", "rzye", "rqye", "rqyl", "rqmcl", "rqchl"],
        dtype={"ts_code": str, "trade_date": str},
    )
    margin["date"] = pd.to_datetime(margin["trade_date"], format="%Y%m%d", errors="coerce")
    margin = margin.dropna(subset=["date"])
    for column in ("rzye", "rqye", "rqyl", "rqmcl", "rqchl"):
        margin[column] = pd.to_numeric(margin[column], errors="coerce")
    log(f"      rows={len(margin):,}  {margin['date'].min().date()}..{margin['date'].max().date()}"
        f"  instruments={margin['ts_code'].nunique():,}")

    # Names that ever carry a short balance -- the signal is only defined there.
    ever_short = margin.groupby("ts_code")["rqyl"].max()
    short_names = set(ever_short[ever_short > 0].index)
    log(f"      instruments with any short interest: {len(short_names):,}")

    margin = margin[margin["ts_code"].isin(short_names)].copy()
    margin["instrument"] = margin["ts_code"].map(ts_to_qlib)
    margin = margin.dropna(subset=["instrument"])

    # ------------------------------------------------------------------ #
    log("[2/6] loading size / turnover / volume-ratio")
    db = pd.read_csv(
        DAILY_BASIC, compression="gzip",
        usecols=["ts_code", "trade_date", "circ_mv", "turnover_rate", "volume_ratio"],
        dtype={"ts_code": str, "trade_date": str},
    )
    db = db[db["ts_code"].isin(short_names)]
    db["date"] = pd.to_datetime(db["trade_date"], format="%Y%m%d", errors="coerce")
    db = db.dropna(subset=["date"])
    for column in ("circ_mv", "turnover_rate", "volume_ratio"):
        db[column] = pd.to_numeric(db[column], errors="coerce")
    db["circ_mv"] = db["circ_mv"] * 1e4        # 万元 -> 元
    db = db[["ts_code", "date", "circ_mv", "turnover_rate", "volume_ratio"]]
    log(f"      rows={len(db):,}")

    # ------------------------------------------------------------------ #
    log("[3/6] loading prices from the qlib store")
    symbols = sorted({ts_to_qlib(c) for c in short_names} - {None})
    frame = D.features(symbols, ["$open", "$close", "$volume"],
                       start_time=WARMUP_START, end_time=SAMPLE_END, freq="day")
    prices = frame.reset_index()
    prices.columns = ["instrument", "date", "open", "close", "volume"]
    prices["ts_code"] = prices["instrument"].map(qlib_to_ts)
    for column in ("open", "close", "volume"):
        prices[column] = prices[column].astype("float32")
    log(f"      rows={len(prices):,}  instruments={prices['instrument'].nunique():,}")

    # ------------------------------------------------------------------ #
    log("[4/6] building the panel and the frozen signals")
    panel = prices.merge(
        margin[["instrument", "date", "rzye", "rqye", "rqyl", "rqmcl", "rqchl"]],
        on=["instrument", "date"], how="inner",
    )
    panel = panel.merge(db[["ts_code", "date", "circ_mv", "turnover_rate", "volume_ratio"]],
                        on=["ts_code", "date"], how="left")
    panel = panel.sort_values(["instrument", "date"]).reset_index(drop=True)
    log(f"      panel rows={len(panel):,}")

    grouped = panel.groupby("instrument", sort=False)

    # --- frozen signal definitions (all use t-1 or earlier) ---------------
    short_ratio = panel["rqye"] / panel["circ_mv"].replace(0, np.nan)
    panel["short_ratio"] = short_ratio.groupby(panel["instrument"], sort=False).shift(1)

    roll = panel.groupby("instrument", sort=False)["short_ratio"]
    mean = roll.transform(lambda s: s.rolling(ZSCORE_WINDOW, min_periods=ZSCORE_MIN).mean())
    std = roll.transform(lambda s: s.rolling(ZSCORE_WINDOW, min_periods=ZSCORE_MIN).std())
    panel["short_z"] = (panel["short_ratio"] - mean) / std.replace(0, np.nan)

    rqyl_lag1 = panel["rqyl"].groupby(panel["instrument"], sort=False).shift(1)
    rqyl_lag21 = panel["rqyl"].groupby(panel["instrument"], sort=False).shift(21)
    panel["short_chg20"] = rqyl_lag1 / rqyl_lag21.replace(0, np.nan) - 1.0

    rqmcl_lag1 = panel["rqmcl"].groupby(panel["instrument"], sort=False).shift(1)
    rqchl_lag1 = panel["rqchl"].groupby(panel["instrument"], sort=False).shift(1)
    rqyl_lag2 = panel["rqyl"].groupby(panel["instrument"], sort=False).shift(2)
    panel["short_flow"] = (rqmcl_lag1 - rqchl_lag1) / rqyl_lag2.replace(0, np.nan)

    # --- control signal: the already-tested margin financing balance ------
    rzye = panel["rzye"].groupby(panel["instrument"], sort=False).shift(1)
    panel["rzye_ratio"] = rzye / panel["circ_mv"].replace(0, np.nan)
    roll_r = panel.groupby("instrument", sort=False)["rzye_ratio"]
    rmean = roll_r.transform(lambda s: s.rolling(ZSCORE_WINDOW, min_periods=ZSCORE_MIN).mean())
    rstd = roll_r.transform(lambda s: s.rolling(ZSCORE_WINDOW, min_periods=ZSCORE_MIN).std())
    panel["rzye_z"] = (panel["rzye_ratio"] - rmean) / rstd.replace(0, np.nan)

    # --- price-volume controls (t-1 visible) ------------------------------
    close = panel["close"]
    panel["mom20"] = (close.groupby(panel["instrument"], sort=False).shift(1)
                      / close.groupby(panel["instrument"], sort=False).shift(21) - 1.0)
    panel["vol20"] = (close.groupby(panel["instrument"], sort=False)
                      .transform(lambda s: s.rolling(20, min_periods=10).std())
                      .groupby(panel["instrument"], sort=False).shift(1)
                      / close.groupby(panel["instrument"], sort=False).shift(1))
    panel["turnover_rate"] = grouped["turnover_rate"].shift(1)
    panel["volume_ratio"] = grouped["volume_ratio"].shift(1)

    # --- open-to-open labels ----------------------------------------------
    open_ = panel["open"]
    entry = open_.groupby(panel["instrument"], sort=False).shift(-1)
    for horizon in HORIZONS:
        exit_ = open_.groupby(panel["instrument"], sort=False).shift(-(1 + horizon))
        panel[f"label_{horizon}"] = exit_ / entry - 1.0

    # ------------------------------------------------------------------ #
    log("[5/6] computing RankIC per date")
    sample = panel[(panel["date"] >= SAMPLE_START) & (panel["date"] <= SAMPLE_END)].copy()
    log(f"      sample rows={len(sample):,}  dates={sample['date'].nunique():,}")

    def rank_ic(values: pd.Series, labels: pd.Series) -> pd.Series:
        tmp = pd.DataFrame({"date": sample["date"].to_numpy(),
                            "x": np.asarray(values, dtype="float64"),
                            "y": np.asarray(labels, dtype="float64")}).dropna()
        if tmp.empty:
            return pd.Series(dtype="float64")
        grp = tmp.groupby("date", sort=True)
        tmp["xr"] = grp["x"].rank(pct=True)
        tmp["yr"] = grp["y"].rank(pct=True)
        g2 = tmp.groupby("date", sort=True)
        n = g2["xr"].transform("size")
        mx = g2["xr"].transform("mean")
        my = g2["yr"].transform("mean")
        vx = g2["xr"].transform("var")
        vy = g2["yr"].transform("var")
        cov = ((tmp["xr"] - mx) * (tmp["yr"] - my)).groupby(tmp["date"]).transform("mean")
        with np.errstate(divide="ignore", invalid="ignore"):
            ic = cov / np.sqrt(vx * vy)
        ic = ic.where(n >= MIN_NAMES_PER_DATE)
        out = pd.Series(ic.to_numpy(), index=tmp.index).groupby(tmp["date"]).first()
        return out.sort_index()

    ic_frames = {}
    summary_rows = []
    for signal in SIGNALS:
        for horizon in HORIZONS:
            ic = rank_ic(sample[signal], sample[f"label_{horizon}"])
            ic_frames[f"{signal}__h{horizon}"] = ic
            clean = ic.dropna()
            if len(clean) < 30:
                summary_rows.append({"signal": signal, "horizon": horizon, "n_dates": len(clean)})
                continue
            std = float(clean.std(ddof=1))
            mean = float(clean.mean())
            summary_rows.append({
                "signal": signal, "horizon": horizon, "n_dates": int(len(clean)),
                "ic_mean": mean, "ic_std": std,
                "icir": mean / std if std > 0 else np.nan,
                "t_stat": mean / std * np.sqrt(len(clean)) if std > 0 else np.nan,
                "positive_rate": float((clean > 0).mean()),
                "abs_ic_mean": abs(mean),
                "abs_icir": abs(mean / std) if std > 0 else np.nan,
            })
    ic_by_date = pd.DataFrame(ic_frames)
    ic_by_date.index.name = "date"
    ic_by_date.to_csv(OUT / "ic_by_date.csv.gz", compression="gzip")
    summary = pd.DataFrame(summary_rows)
    summary.to_csv(OUT / "ic_summary.csv", index=False, encoding="utf-8-sig")
    log("      ic_summary.csv written")
    print(summary.to_string(index=False))

    # ------------------------------------------------------------------ #
    log("[6/6] lag alignment check + orthogonality")
    lag_rows = []
    for signal in SIGNALS:
        aligned = rank_ic(sample[signal], sample[f"label_{PRIMARY_HORIZON}"]).dropna()
        # misaligned: use the same-day value (a look-ahead) instead of t-1
        if signal == "short_ratio":
            raw = panel["rqye"] / panel["circ_mv"].replace(0, np.nan)
        elif signal == "short_chg20":
            raw = panel["rqyl"] / panel["rqyl"].groupby(panel["instrument"], sort=False).shift(20) - 1.0
        elif signal == "short_flow":
            raw = (panel["rqmcl"] - panel["rqchl"]) / panel["rqyl"].groupby(panel["instrument"], sort=False).shift(1)
        else:
            raw = panel["short_ratio"]
        raw_sample = raw[(panel["date"] >= SAMPLE_START) & (panel["date"] <= SAMPLE_END)]
        misaligned = rank_ic(raw_sample, sample[f"label_{PRIMARY_HORIZON}"]).dropna()
        a_ic = float(aligned.mean()) if len(aligned) else np.nan
        m_ic = float(misaligned.mean()) if len(misaligned) else np.nan
        loss = 1.0 - abs(a_ic) / abs(m_ic) if m_ic not in (0.0,) and np.isfinite(m_ic) and m_ic != 0 else np.nan
        lag_rows.append({"signal": signal, "aligned_ic": a_ic, "misaligned_ic": m_ic,
                         "abs_ic_loss_vs_misaligned": loss,
                         "lag_ok": bool(np.isfinite(loss) and loss < LAG_TOLERANCE)})
    lag_frame = pd.DataFrame(lag_rows)
    lag_frame.to_csv(OUT / "lag_alignment_check.csv", index=False, encoding="utf-8-sig")
    print(lag_frame.to_string(index=False))

    def cross_corr(left: pd.Series, right: pd.Series) -> float:
        tmp = pd.DataFrame({"date": sample["date"].to_numpy(),
                            "x": np.asarray(left, dtype="float64"),
                            "y": np.asarray(right, dtype="float64")}).dropna()
        if tmp.empty:
            return np.nan
        means = tmp.groupby("date")[["x", "y"]].mean()
        tmp = tmp.merge(means, on="date", suffixes=("", "_m"))
        tmp["dx"] = tmp["x"] - tmp["x_m"]
        tmp["dy"] = tmp["y"] - tmp["y_m"]
        num = tmp.groupby("date").apply(lambda g: (g["dx"] * g["dy"]).mean(), include_groups=False)
        den = tmp.groupby("date").apply(
            lambda g: np.sqrt((g["dx"] ** 2).mean() * (g["dy"] ** 2).mean()), include_groups=False)
        with np.errstate(divide="ignore", invalid="ignore"):
            corr = num / den
        return float(corr.replace([np.inf, -np.inf], np.nan).mean())

    corr_rows = []
    for signal in SIGNALS:
        for factor in PV_FACTORS:
            corr_rows.append({"signal": signal, "factor": factor,
                              "mean_cross_section_spearman": cross_corr(sample[signal], sample[factor])})
    corr_frame = pd.DataFrame(corr_rows)
    corr_frame["abs_corr"] = corr_frame["mean_cross_section_spearman"].abs()
    corr_frame.to_csv(OUT / "correlation_summary.csv", index=False, encoding="utf-8-sig")
    print()
    print(corr_frame.to_string(index=False))

    # ------------------------------------------------------------------ #
    def effective(signal: str) -> tuple[bool, str]:
        row = summary[(summary["signal"] == signal) & (summary["horizon"] == PRIMARY_HORIZON)]
        if row.empty:
            return False, "no primary-horizon IC"
        primary = row.iloc[0]
        if not (primary["abs_ic_mean"] >= IC_MIN and primary["abs_icir"] >= ICIR_MIN):
            return False, (f"primary h={PRIMARY_HORIZON} fails: "
                           f"|IC|={primary['abs_ic_mean']:.4f} (need {IC_MIN}), "
                           f"|ICIR|={primary['abs_icir']:.3f} (need {ICIR_MIN})")
        others = summary[(summary["signal"] == signal) & (summary["horizon"] != PRIMARY_HORIZON)]
        hits = int(((others["abs_ic_mean"] >= SECONDARY_IC_MIN)
                    & (np.sign(others["ic_mean"]) == np.sign(primary["ic_mean"]))).sum())
        if hits < SECONDARY_MIN_HITS:
            return False, f"only {hits} secondary horizons agree (need {SECONDARY_MIN_HITS})"
        return True, "primary and secondary horizons agree"

    decisions = {}
    for signal in SIGNALS:
        lag_ok = bool(lag_frame.loc[lag_frame["signal"] == signal, "lag_ok"].iloc[0])
        max_corr = float(corr_frame.loc[corr_frame["signal"] == signal, "abs_corr"].max())
        orthogonal = max_corr < ORTHOGONALITY_LIMIT
        is_effective, why = effective(signal)
        decisions[signal] = {
            "lag_ok": lag_ok,
            "orthogonal": orthogonal,
            "max_abs_cross_corr": max_corr,
            "effective": is_effective,
            "effective_reason": why,
            "decision": "supported" if (lag_ok and orthogonal and is_effective) else "not_supported",
        }

    any_supported = any(d["decision"] == "supported" for d in decisions.values())
    decision = {
        "overall": "supported" if any_supported else "not_supported",
        "per_signal": decisions,
        "primary_horizon": PRIMARY_HORIZON,
        "thresholds": {"ic_min": IC_MIN, "icir_min": ICIR_MIN,
                       "orthogonality_limit": ORTHOGONALITY_LIMIT,
                       "lag_tolerance": LAG_TOLERANCE},
        "sample": {"start": SAMPLE_START, "end": SAMPLE_END,
                   "rows": int(len(sample)), "dates": int(sample["date"].nunique())},
        "protocol": "research/protocols/a_share_short_interest_signal_protocol_v1.md",
    }
    (OUT / "decision.json").write_text(json.dumps(decision, indent=2, ensure_ascii=False), encoding="utf-8")
    (OUT / "methodology.json").write_text(json.dumps({
        "generated_utc": started.isoformat(),
        "finished_utc": datetime.now(timezone.utc).isoformat(),
        "signal_definitions": {
            "short_ratio": "rqye(t-1) / circ_mv(t-1)",
            "short_z": f"{ZSCORE_WINDOW}-day time-series z-score of short_ratio (min {ZSCORE_MIN})",
            "short_chg20": "rqyl(t-1) / rqyl(t-21) - 1",
            "short_flow": "(rqmcl(t-1) - rqchl(t-1)) / rqyl(t-2)",
        },
        "label": "open(t+1+h)/open(t+1)-1",
        "horizons": list(HORIZONS),
        "universe": "沪深普通A股 with any short interest; 30*/688*/BJ/B股/指数 excluded",
        "scripts": "scripts/analyze_a_share_short_interest_signal_v1.py",
    }, indent=2, ensure_ascii=False), encoding="utf-8")

    print()
    print("=" * 78)
    print(" decision")
    print("=" * 78)
    print(json.dumps(decision, indent=2, ensure_ascii=False))
    log("DONE")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
