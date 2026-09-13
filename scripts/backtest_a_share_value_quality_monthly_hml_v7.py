#!/usr/bin/env python3
"""HML style risk-control revalidation of the value/quality strategy (protocol v7).

Adds a style-timing overlay to the validated v6 strategy: when HML
(high-BM minus low-BM future-20d return spread, 6-month average) is negative
(value underperforms growth), cut the portfolio to the top-15 (30% of top-50)
equal-weight names; otherwise hold the full top-50.  Uses the same holdings,
filters and daily equal-weight return math as the v6 pipeline, so the v6 vs v7
difference is purely the risk-control overlay.

Protocol: research/protocols/a_share_value_quality_monthly_strategy_protocol_v7.md
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

from load_financials_extended_v1 import load_financials_extended
from analyze_a_share_value_quality_level_factors_extension_v1 import (
    build_snapshot,
    STYLE_DIR,
    QLIB_DIR,
)
from backtest_a_share_value_quality_monthly_dailygrid_v6 import build_daily_grid

TOP_K = 50
HML_TOPK_FRACTION = 0.15
HML_WINDOW = 6          # months of HML average
HML_HORIZON = 20        # trading days
RISK_CUT_KEEP = 15      # top-15 (30% of top-50) when value headwind
BENCHMARK = "SH000852"
BT_START = pd.Timestamp("2016-01-01")
BT_END = pd.Timestamp("2026-06-30")
V6_PANEL = Path("output/analysis_fundamental/a_share_value_quality_monthly_strategy_v6_dailygrid/monthly_composite_dailygrid.csv.gz")


def qlib_symbol(code: str) -> str:
    number, suffix = code.split(".")
    return f"{suffix}{number}"


def load_open(codes: list[str], cal: pd.DatetimeIndex) -> pd.DataFrame:
    """Open prices for codes over the backtest window, as (datetime x ts_code)."""
    qlib_codes = [qlib_symbol(c) for c in codes]
    frames = []
    for year in range(BT_START.year, BT_END.year + 1):
        df = D.features(qlib_codes, ["$open"], start_time=f"{year}-01-01", end_time=f"{year}-12-31", freq="day")
        frames.append(df)
    wide = pd.concat(frames)["$open"].unstack(level="instrument")
    wide.columns = [f"{c[2:]}.{c[:2]}" for c in wide.columns]
    return wide.reindex(cal)


def compute_hml(grid, fin, industry, size_daily, cal) -> pd.DataFrame:
    """Monthly BM high/low combos + future-20d return spread.

    Returns DataFrame[rebalance_date, hml_20d].
    """
    # 1. Monthly BM from v6 snapshots.
    bm_by_month = {}
    union_codes = set()
    for _, row in grid.iterrows():
        snap = build_snapshot(fin, row, industry, size_daily)
        if snap.empty:
            continue
        s = snap.dropna(subset=["bm"])
        if len(s) < 500:
            continue
        q = s["bm"].quantile([HML_TOPK_FRACTION, 1 - HML_TOPK_FRACTION])
        hi = set(s[s["bm"] >= q[1 - HML_TOPK_FRACTION]]["ts_code"])
        lo = set(s[s["bm"] <= q[HML_TOPK_FRACTION]]["ts_code"])
        bm_by_month[row.rebalance_date] = (hi, lo)
        union_codes |= hi | lo

    # 2. Open prices once for the union of BM-combo codes.
    codes = sorted(union_codes)
    open_wide = load_open(codes, cal)

    # 3. Monthly HML = mean future-20d return of hi - mean of lo.
    rows = []
    for d, (hi, lo) in bm_by_month.items():
        pos = cal.searchsorted(d)
        if pos + HML_HORIZON >= len(cal):
            continue
        d0, d20 = cal[pos], cal[pos + HML_HORIZON]
        if d0 not in open_wide.index or d20 not in open_wide.index:
            continue
        p0, p20 = open_wide.loc[d0], open_wide.loc[d20]
        r = p20 / p0 - 1.0
        r[(p0 <= 0) | (p20 <= 0) | ~np.isfinite(r)] = np.nan
        r_hi = r.reindex(list(hi)).dropna()
        r_lo = r.reindex(list(lo)).dropna()
        if len(r_hi) < 30 or len(r_lo) < 30:
            continue
        rows.append({"rebalance_date": d, "hml_20d": float(r_hi.mean() - r_lo.mean())})
    hml = pd.DataFrame(rows)
    hml["S"] = hml["hml_20d"].rolling(HML_WINDOW, min_periods=HML_WINDOW).mean()
    return hml


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, default=Path("output/analysis_fundamental/a_share_value_quality_monthly_strategy_v7_hml"))
    args = parser.parse_args()
    out = args.output_dir
    if out.exists() and any(out.iterdir()):
        raise FileExistsError(f"Refusing to overwrite existing experiment output: {out}")
    out.mkdir(parents=True, exist_ok=True)

    qlib.init(provider_uri=str(QLIB_DIR), region=REG_CN)
    cal = pd.DatetimeIndex(pd.to_datetime(pd.read_csv(QLIB_DIR / "calendars" / "day.txt", header=None)[0]))

    print("[1/5] Loading data ...", flush=True)
    fin = load_financials_extended()
    grid, size_daily = build_daily_grid()
    grid = grid[grid["rebalance_date"].between(BT_START, BT_END)].copy()
    industry = pd.read_csv(STYLE_DIR / "industry_l1_effective_intervals.csv.gz", compression="gzip", dtype=str)
    industry["in_date"] = pd.to_datetime(industry["in_date"], errors="coerce")
    industry["out_date"] = pd.to_datetime(industry["out_date"], errors="coerce")
    panel = pd.read_csv(V6_PANEL, compression="gzip")
    panel["rebalance_date"] = pd.to_datetime(panel["rebalance_date"])
    print(f"      months={len(grid)}", flush=True)

    print("[2/5] Computing HML series ...", flush=True)
    hml = compute_hml(grid, fin, industry, size_daily, cal)
    hml.to_csv(out / "hml_signal_series.csv", index=False)
    print(f"      HML months={len(hml)}", flush=True)
    if len(hml) < HML_WINDOW + 2:
        raise RuntimeError("Not enough HML observations")
    sig_by_month = hml.set_index("rebalance_date")["S"]
    headwind_months = sig_by_month[sig_by_month < 0].index
    print(f"      headwind months (S<0): {len(headwind_months)}/{len(sig_by_month)}", flush=True)

    print("[3/5] Building v6 (full) and v7 (risk-controlled) holdings ...", flush=True)
    # Monthly top-50 from the v6 panel (neutral_composite).
    top50_by_month = {}
    for d, g in panel.groupby("rebalance_date"):
        top = g.dropna(subset=["neutral_composite"]).nlargest(TOP_K, "neutral_composite")
        top50_by_month[d] = list(top["ts_code"])

    def monthly_holdings(cut: bool) -> dict[pd.Timestamp, list[str]]:
        holdings = {}
        for d, full in top50_by_month.items():
            if cut and d in headwind_months:
                holdings[d] = full[:RISK_CUT_KEEP]
            else:
                holdings[d] = full
        return holdings

    holdings_v6 = monthly_holdings(cut=False)
    holdings_v7 = monthly_holdings(cut=True)

    print("[4/5] Daily equal-weight returns ...", flush=True)
    held_codes = sorted({c for h in holdings_v7.values() for c in h})
    qlib_codes = [qlib_symbol(c) for c in held_codes] + [BENCHMARK]
    close_frames = []
    for year in range(BT_START.year, BT_END.year + 1):
        close_frames.append(D.features(qlib_codes, ["$close"], start_time=f"{year}-01-01", end_time=f"{year}-12-31", freq="day"))
    close_wide = pd.concat(close_frames)["$close"].unstack(level="instrument")
    close_wide.columns = [f"{c[2:]}.{c[:2]}" if c != BENCHMARK else BENCHMARK for c in close_wide.columns]
    close_wide = close_wide.reindex(cal)
    rets = close_wide.pct_change()
    bench = rets[BENCHMARK]

    trading_days = cal[(cal >= BT_START) & (cal <= BT_END)]
    rebal_dates = sorted(top50_by_month)

    def portfolio_excess(holdings_map) -> pd.Series:
        current = None
        daily_excess = []
        for day in trading_days:
            if day in rebal_dates:
                current = holdings_map[day]
            if current is None or day not in rets.index:
                continue
            day_ret = rets.loc[day].reindex(current).to_numpy(dtype=float)
            port = np.nanmean(day_ret)
            b = bench.loc[day] if day in bench.index and pd.notna(bench.loc[day]) else np.nan
            daily_excess.append(pd.Series({"datetime": day, "excess": port - b}))
        return pd.DataFrame(daily_excess).set_index("datetime")["excess"]

    excess_v6 = portfolio_excess(holdings_v6)
    excess_v7 = portfolio_excess(holdings_v7)

    def yearly_cum(series):
        out = {}
        for year, g in series.groupby(series.index.year):
            out[year] = float((1 + g.dropna()).prod() - 1)
        return out

    yearly_v6, yearly_v7 = yearly_cum(excess_v6), yearly_cum(excess_v7)
    yr = pd.DataFrame({"v6_full": yearly_v6, "v7_hml": yearly_v7})
    yr.to_csv(out / "yearly_summary.csv", index=False)

    def stage_stats(series, s0, s1):
        sample = series.loc[s0:s1].dropna()
        if len(sample) < 20:
            return {}
        ann = float(sample.mean() * 238)
        ir = float(sample.mean() / sample.std() * np.sqrt(238)) if sample.std() > 0 else np.nan
        return {"annualized_excess": ann, "ir": ir}

    stages = {
        "development": ("2016-01-01", "2019-12-31"),
        "confirmation": ("2020-01-01", "2022-12-31"),
        "holdout": ("2023-01-01", "2025-06-30"),
        "new_coverage": ("2025-07-01", "2026-06-30"),
        "full": (str(BT_START.date()), str(BT_END.date())),
    }
    bt_rows = []
    for name, (s0, s1) in stages.items():
        s6 = stage_stats(excess_v6, s0, s1)
        s7 = stage_stats(excess_v7, s0, s1)
        bt_rows.append({
            "stage": name,
            "v6_full_ann": s6.get("annualized_excess", np.nan), "v6_full_ir": s6.get("ir", np.nan),
            "v7_hml_ann": s7.get("annualized_excess", np.nan), "v7_hml_ir": s7.get("ir", np.nan),
        })
    bt = pd.DataFrame(bt_rows)
    bt.to_csv(out / "backtest_summary.csv", index=False)
    print(bt.to_string(index=False), flush=True)

    print("[5/5] Decision ...", flush=True)
    # 2026H1 improvement + holdout not materially worse.
    h26_v6 = yearly_v6.get(2026, 0.0)
    h26_v7 = yearly_v7.get(2026, 0.0)
    hol6 = stage_stats(excess_v6, "2023-01-01", "2025-06-30")
    hol7 = stage_stats(excess_v7, "2023-01-01", "2025-06-30")
    improved_2026 = (h26_v7 - h26_v6) > 0.05
    holdout_ok = (hol6.get("ir", 0) - hol7.get("ir", 0)) < 0.3
    decision = "hml_risk_control_effective" if (improved_2026 and holdout_ok) else "hml_risk_control_not_effective"

    decision_json = {
        "decision": decision,
        "2026_v6_excess": h26_v6, "2026_v7_excess": h26_v7, "2026_improvement": h26_v7 - h26_v6,
        "holdout_v6_ir": hol6.get("ir"), "holdout_v7_ir": hol7.get("ir"),
        "headwind_months": len(headwind_months),
    }
    (out / "decision.json").write_text(json.dumps(decision_json, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    methodology = {
        "protocol": "research/protocols/a_share_value_quality_monthly_strategy_protocol_v7.md",
        "hml": f"BM top/bottom {HML_TOPK_FRACTION:.0%} future-{HML_HORIZON}d return spread, {HML_WINDOW}-month avg",
        "risk_rule": "S<0 -> hold top-15 (30% of top-50), else full top-50",
        "return_math": "daily equal-weight close-to-close, same as v6 pipeline",
        "benchmark": BENCHMARK,
    }
    (out / "methodology.json").write_text(json.dumps(methodology, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    lines = [
        "HML 风格风控对照 v7",
        "=" * 64,
        f"HML: BM top/bottom 15% 未来20日收益差, {HML_WINDOW}月均值; S<0(价值逆风) → 仅持 top15",
        "",
        "分阶段（年化超额，费前等权，相对 SH000852）：",
        bt.to_string(index=False),
        "",
        "分年累计超额：",
        yr.to_string(),
        "",
        f"2026: v6={h26_v6:.2%} → v7={h26_v7:.2%} (改善 {h26_v7-h26_v6:+.2%})",
        f"封存期 IR: v6={hol6.get('ir')} → v7={hol7.get('ir')}",
        "",
        f"判定：{decision}",
        "结论边界：费前等权近似（无成本/涨跌停），仅作风控方向性检验。",
    ]
    (out / "strategy_report.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("\n".join(lines))


if __name__ == "__main__":
    main()
