#!/usr/bin/env python3
"""Stage-2 signal production pipeline: value/quality monthly strategy (protocol v1).

For a given trading day T, produce the top-50 holding list using only data
available at T (no lookahead), and maintain daily signal/holding/portfolio
ledgers.  Supports:
  --replay --from A --to B   step through rebalance dates, verify consistency
                             against the frozen v2 neutralization signal, and
                             emit the three ledgers.
  --date T                   single-day mode (rebalance if T is a rebalance date,
                             otherwise hold the latest list).

Rules are frozen in research/protocols/signal_production_pipeline_protocol_v1.md
and are identical to the validated v4 strategy: four fundamental factors ->
ST/退市整理 filter -> capacity filter (participation 5%) -> industry/size
neutralization -> top-50 equal weight, monthly rebalance.
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

from analyze_a_share_value_quality_level_factors_extension_v1 import (
    build_snapshot,
    ols_residual,
    composite_score,
    STYLE_DIR,
    QLIB_DIR,
)
from load_financials_extended_v1 import load_financials_extended as load_financials
from backtest_a_share_value_quality_monthly_sensitivity_v4 import load_amount_avg, NOTIONAL

TOP_K = 50
PARTICIPATION = 0.05
ACCOUNT = 100_000_000
BENCHMARK = "SH000852"
ST_INTERVALS = Path("data/external/tushare/a_share_st_status_pit_v1/normalized/st_status_intervals.csv.gz")
# Consistency reference: the v6 daily-grid panel (fixed composite >=3 factors,
# ST + capacity filtered, neutralized) - identical logic+data to this pipeline.
V6_REFERENCE = Path("output/analysis_fundamental/a_share_value_quality_monthly_strategy_v6_dailygrid/monthly_composite_dailygrid.csv.gz")
LEDGER_DIR = Path("output/signal_ledger")
LIVE_LEDGER_DIR = Path("output/live_ledger")

# Overbought filter parameters (protocol v11, frozen)
REBO_WINDOW = 20                # past trading days for return calculation
REBO_THRESHOLD = 0.20           # exclude candidates with past-20d return > +20%
REBO_SLACK = 5                  # extra candidates as replacement pool

# T5 跌幅上榜 filter parameters (v12 protocol, frozen)
T5_WINDOW = 20                  # exclude stocks with a 跌幅上榜 event in past N trading days
EVENTS_DIR = Path("data/external/tushare/a_share_events_daily_v1/raw")


def qlib_symbol(code: str) -> str:
    number, suffix = code.split(".")
    return f"{suffix}{number}"


def ts_to_qlib(code) -> str | float:
    """tushare ts_code -> qlib instrument id; defensive for non-exchange codes."""
    if not isinstance(code, str) or "." not in code:
        return np.nan
    num, ex = code.split(".")
    if ex not in ("SH", "SZ", "BJ"):
        return np.nan
    return f"{ex}{num}"


def load_financials_with_yoy():
    """Frozen load_financials + the four YoY deterioration columns (v13 protocol).

    The YoY columns live in the same merged fina_indicator file; merged
    externally so load_financials_extended is not modified.
    """
    from load_financials_extended_v1 import FIN, _fill_available
    fin = load_financials()
    yoy = pd.read_csv(
        FIN / "normalized/fina_indicator.csv.gz",
        usecols=["ts_code", "end_date", "ann_date", "available_date",
                 "netprofit_yoy", "or_yoy", "ocf_yoy", "dt_netprofit_yoy"],
        low_memory=False,
    )
    yoy = _fill_available(yoy)
    yoy = yoy.dropna(subset=["available_date"])
    yoy = yoy.drop_duplicates(["ts_code", "end_date", "available_date"], keep="last")
    return fin.merge(yoy, on=["ts_code", "end_date", "available_date"], how="left")


def deterioration_flags(latest: pd.DataFrame) -> pd.DataFrame:
    """Frozen value-trap flags from a per-code latest frame (v13 protocol).

    deter_any2 = >=2 of {netprofit_yoy, or_yoy, ocf_yoy} < 0, with >=2 observed.
    """
    out = pd.DataFrame(index=latest.index)
    out["deter_ni"] = (latest["netprofit_yoy"] < 0).astype(float)
    out["deter_or"] = (latest["or_yoy"] < 0).astype(float)
    out["deter_ocf"] = (latest["ocf_yoy"] < 0).astype(float)
    n_obs = out[["deter_ni", "deter_or", "deter_ocf"]].notna().sum(axis=1)
    n_hit = out[["deter_ni", "deter_or", "deter_ocf"]].sum(axis=1)
    any2 = pd.Series(np.nan, index=latest.index)
    any2[n_obs >= 2] = (n_hit[n_obs >= 2] >= 2).astype(float)
    out["deter_any2"] = any2
    return out


def build_vt_by_rebalance(fin: pd.DataFrame, grid: pd.DataFrame) -> dict[pd.Timestamp, set[str]]:
    """Per-rebalance-date set of ts_codes flagged deter_any2 (frozen v13 rule)."""
    out = {}
    for _, row in grid.iterrows():
        date = row.rebalance_date
        current = fin[fin["available_date"].le(date)].copy()
        current = current.sort_values(["ts_code", "end_date", "available_date"], kind="mergesort")
        current = current.drop_duplicates(["ts_code", "end_date"], keep="last")
        latest = current.sort_values(["ts_code", "end_date"], kind="mergesort").drop_duplicates("ts_code", keep="last")
        latest = latest.set_index("ts_code")
        flags = deterioration_flags(latest)
        out[date] = set(flags.index[flags["deter_any2"].eq(1)])
    return out


def load_t5_events() -> pd.DataFrame:
    """T5 跌幅上榜：top_list reason 含跌幅/负向，事件日 = trade_date（v12 frozen rule)."""
    import glob
    files = sorted(Path(p) for p in glob.glob(str(EVENTS_DIR / "*top_list.csv.gz")))
    df = pd.concat([pd.read_csv(f, compression="gzip") for f in files], ignore_index=True)
    df["instrument"] = df["ts_code"].map(ts_to_qlib)
    df["trade_date"] = pd.to_datetime(df["trade_date"].astype(str), format="%Y%m%d")
    neg = df[df["reason"].str.contains("跌幅|负向", na=False)]
    out = neg[["instrument", "trade_date"]].drop_duplicates()
    out = out.rename(columns={"trade_date": "event_date"}).dropna(subset=["instrument"])
    return out


def build_t5_by_rebalance(events: pd.DataFrame, calendar: pd.DatetimeIndex,
                          rebalance_dates: list, window: int = T5_WINDOW) -> dict[pd.Timestamp, set[str]]:
    """Per-rebalance-date set of ts_codes with a T5 event in the past `window` days."""
    cal_list = list(calendar)
    cal_pos = {d: i for i, d in enumerate(cal_list)}
    ev = events.copy()
    ev["ts_code"] = ev["instrument"].map(
        lambda c: f"{c[2:]}.{c[:2]}" if isinstance(c, str) and len(c) == 8 else np.nan)
    ev = ev.dropna(subset=["ts_code"])
    ev_by_code = ev.groupby("ts_code")["event_date"].apply(lambda s: np.array(sorted(s))).to_dict()
    out: dict[pd.Timestamp, set[str]] = {}
    for rb in rebalance_dates:
        if rb not in cal_pos:
            continue
        pos = cal_pos[rb]
        win_start = cal_list[max(0, pos - window)]
        hits = set()
        for code, dates in ev_by_code.items():
            idx = np.searchsorted(dates, win_start)
            if idx < len(dates) and dates[idx] <= rb:
                hits.add(code)
        out[rb] = hits
    return out


def load_aux(grid_window=None, end=None):
    """Daily-basis month-end grid + daily size (protocol v6).

    Grid: last trading day of each month from a_share_daily_basic_pit_v1
    (rebalance_date = asof_date = month-end).  Size carries daily total_mv,
    total_share, dv_ttm plus a size_control placeholder used only internally
    by build_snapshot; the v6 neutralization uses log(total_mv).

    `end` extends the grid past the frozen backtest end (BT_END) so the
    production pipeline reaches the latest month-end rebalance.  Backtest
    callers omit it to keep the frozen window.
    """
    from backtest_a_share_value_quality_monthly_dailygrid_v6 import build_daily_grid
    grid, size_daily = build_daily_grid(end=end)
    if grid_window is not None:
        grid = grid[grid["rebalance_date"].between(*grid_window)].copy()
    industry = pd.read_csv(STYLE_DIR / "industry_l1_effective_intervals.csv.gz", compression="gzip", dtype=str)
    industry["in_date"] = pd.to_datetime(industry["in_date"], errors="coerce")
    industry["out_date"] = pd.to_datetime(industry["out_date"], errors="coerce")
    st = pd.read_csv(ST_INTERVALS, compression="gzip", parse_dates=["start_date", "end_date"])
    return grid, industry, size_daily, st


def st_codes_at(st, asof: pd.Timestamp) -> set:
    active = st[(st["start_date"] <= asof) & (st["end_date"] >= asof)]
    return set(active.loc[active["is_st"] | active["is_delist_phase"], "ts_code"])


def compute_past_returns(codes: list[str], cal: pd.DatetimeIndex,
                         window: int = REBO_WINDOW) -> dict[pd.Timestamp, dict[str, float]]:
    """Pre-compute past-N-day returns for given codes at each calendar date.

    Returns {date: {qlib_instrument_id: past_return}}.
    Used by the overbought filter to exclude stocks with extreme recent gains.
    """
    if not codes:
        return {}
    qlib_codes = [qlib_symbol(c) for c in codes]
    frames = []
    warm_start = cal[0]
    for year in range(warm_start.year, cal[-1].year + 1):
        df = D.features(qlib_codes, ["$close"], start_time=f"{year}-01-01", end_time=f"{year}-12-31", freq="day")
        frames.append(df)
    raw = pd.concat(frames)["$close"].unstack(level="instrument")
    raw.columns = [f"{c[2:]}.{c[:2]}" for c in raw.columns]
    raw = raw.reindex(cal)

    ret_lookup = {}
    for i in range(len(cal)):
        date = cal[i]
        if i < window:
            ret_lookup[date] = {}
            continue
        past_date = cal[i - window]
        ret_map = {}
        for code in codes:
            if code in raw.columns:
                p0 = raw.loc[past_date, code] if past_date in raw.index else np.nan
                p1 = raw.loc[date, code] if date in raw.index else np.nan
                if pd.notna(p0) and pd.notna(p1) and p0 > 0:
                    ret_map[qlib_symbol(code)] = float(p1 / p0 - 1.0)
        ret_lookup[date] = ret_map
    return ret_lookup


def process_month(fin, grid_row, industry, size, st, amount_avg, calendar,
                  top_k=TOP_K, overbought_filter=False, ret_lookup=None,
                  value_trap_filter=False, vt_hits=None,
                  t5_filter=False, t5_hits=None) -> pd.DataFrame:
    """Return top-k (or fewer) stocks for one rebalance date, frozen rules.

    If overbought_filter=True, candidates with past-20d return > +20% are
    excluded (replaced by next-ranked stock).  Requires ret_lookup to be
    pre-computed via compute_past_returns().
    If value_trap_filter=True, stocks flagged deter_any2 (financial YoY < 0,
    v13 rule) are excluded.  Requires vt_hits pre-computed via build_vt_by_rebalance().
    If t5_filter=True, stocks with a 跌幅上榜 event in the past 20 trading days
    (v12 rule) are excluded.  Requires t5_hits pre-computed via build_t5_by_rebalance().
    """
    date = grid_row.rebalance_date
    asof = grid_row.asof_date
    snap = build_snapshot(fin, grid_row, industry, size)
    if snap.empty:
        return pd.DataFrame()
    frame = snap.copy()

    # 0. Composite = equal-weight percentile-rank average of the four factors
    #    with a >=3-factor gate (identical to the validated composite_score).
    frame["composite"] = composite_score(frame)

    # 1. ST / 退市整理 filter.
    frame.loc[frame["ts_code"].isin(st_codes_at(st, asof)), "composite"] = np.nan

    # 2. Capacity filter: single-stock notional / 20d avg amount <= 5%.
    notional = ACCOUNT // top_k
    avg = amount_avg.loc[asof].reindex(frame["ts_code"]).to_numpy(dtype=float) * 1000.0
    min_amount = notional / PARTICIPATION
    frame.loc[avg < min_amount, "composite"] = np.nan

    # 2.5. Value-trap filter: exclude financially deteriorating stocks (v13 rule).
    if value_trap_filter and vt_hits is not None:
        hits = vt_hits.get(date, set())
        if hits:
            frame.loc[frame["ts_code"].isin(hits), "composite"] = np.nan

    # 2.6. T5 filter: exclude stocks with a 跌幅上榜 event in the past 20 days (v12 rule).
    if t5_filter and t5_hits is not None:
        hits = t5_hits.get(date, set())
        if hits:
            frame.loc[frame["ts_code"].isin(hits), "composite"] = np.nan

    # 3. Neutralize composite against log-size + industry dummies.
    valid = frame.dropna(subset=["composite", "log_size", "l1_code"])
    if len(valid) < 50:
        return pd.DataFrame()
    resid = ols_residual(valid["composite"], valid["l1_code"], valid["log_size"])
    frame["neutral_composite"] = resid.reindex(frame.index)

    # 3.5. Overbought filter: exclude candidates with past-20d return > threshold.
    #      Takes top_k + SLACK candidates, masks overbought ones, re-selects top_k.
    if overbought_filter and ret_lookup is not None:
        candidates = frame.dropna(subset=["neutral_composite"]).nlargest(
            top_k + REBO_SLACK, "neutral_composite")
        ret_map = ret_lookup.get(date, {})
        excluded = []
        for idx, r in candidates.iterrows():
            qc = qlib_symbol(r["ts_code"])
            past_ret = ret_map.get(qc, np.nan)
            if pd.notna(past_ret) and past_ret > REBO_THRESHOLD:
                frame.loc[idx, "neutral_composite"] = np.nan
                excluded.append((r["ts_code"], past_ret))
        if excluded:
            print(f"      [filter] {date.date()}: excluded {len(excluded)} overbought: "
                  f"{', '.join(f'{c}({r:+.1%})' for c, r in excluded[:3])}", flush=True)

    # 4. Top-k by neutralized score.
    top = frame.dropna(subset=["neutral_composite"]).nlargest(top_k, "neutral_composite").copy()
    top = top.sort_values("neutral_composite", ascending=False).reset_index(drop=True)
    top["rank"] = np.arange(1, len(top) + 1)
    top["weight"] = 1.0 / len(top)
    top["rebalance_date"] = date
    return top[["rebalance_date", "rank", "ts_code", "neutral_composite", "weight"]]


def consistency_check(holdings: dict[pd.Timestamp, pd.DataFrame]) -> dict:
    """Compare pipeline top-50 against the v6 daily-grid reference panel.

    The v6 panel is produced by the same logic and data as this pipeline
    (composite >=3-factor gate, ST/退市 + capacity filters, industry/size
    neutralization), so the raw neutral_composite top-50 is the reference —
    no additional filtering needed here.
    """
    if not V6_REFERENCE.exists():
        return {"status": "skipped_no_v6_reference"}
    ref = pd.read_csv(V6_REFERENCE, compression="gzip")
    ref["rebalance_date"] = pd.to_datetime(ref["rebalance_date"])
    overlap = {}
    for date, hold in holdings.items():
        ref_date = ref[ref["rebalance_date"].eq(date)].dropna(subset=["neutral_composite"])
        if ref_date.empty:
            overlap[str(date.date())] = np.nan
            continue
        ref_top = set(ref_date.nlargest(TOP_K, "neutral_composite")["ts_code"])
        shared = set(hold["ts_code"]) & ref_top
        overlap[str(date.date())] = len(shared) / TOP_K if len(ref_top) else np.nan
    values = [v for v in overlap.values() if not np.isnan(v)]
    mean = float(np.mean(values)) if values else np.nan
    return {"status": "ok" if mean >= 0.90 else "mismatch", "mean_top50_overlap": mean, "per_date": overlap}


def daily_returns(codes: list[str], calendar: pd.DatetimeIndex, start: pd.Timestamp, end: pd.Timestamp) -> pd.DataFrame:
    """Daily close-to-close returns for codes plus benchmark over [start, end]."""
    qlib_codes = [qlib_symbol(c) for c in codes] + [BENCHMARK]
    raw = D.features(qlib_codes, ["$close"], start_time=start, end_time=end, freq="day")
    wide = raw["$close"].unstack(level="instrument")
    wide.columns = [f"{c[2:]}.{c[:2]}" if c != BENCHMARK else BENCHMARK for c in wide.columns]
    rets = wide.pct_change().dropna(how="all")
    return rets


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--replay", action="store_true")
    parser.add_argument("--from", dest="from_", default="2024-01-01")
    parser.add_argument("--to", dest="to_", default="2025-06-30")
    parser.add_argument("--date", default=None, help="single-day mode")
    parser.add_argument("--top-k", type=int, default=TOP_K,
                        help=f"number of stocks to select (default {TOP_K}; use 15 for live top-15)")
    parser.add_argument("--live", action="store_true",
                        help="live mode: output actionable trading list with BUY/SELL/HOLD diff vs previous month")
    parser.add_argument("--overbought-filter", action="store_true",
                        help="exclude candidates with past-20d return > +20% (protocol v11)")
    parser.add_argument("--value-trap-filter", action="store_true",
                        help="exclude financially deteriorating stocks, deter_any2 (v13 protocol)")
    parser.add_argument("--t5-filter", action="store_true",
                        help="exclude stocks with a 跌幅上榜 event in the past 20 trading days (v12 protocol)")
    args = parser.parse_args()
    top_k = args.top_k
    use_filter = args.overbought_filter
    use_vt = args.value_trap_filter
    use_t5 = args.t5_filter

    LEDGER_DIR.mkdir(parents=True, exist_ok=True)
    qlib.init(provider_uri=str(QLIB_DIR), region=REG_CN)
    calendar = pd.DatetimeIndex(pd.to_datetime(pd.read_csv(QLIB_DIR / "calendars" / "day.txt", header=None)[0]))

    # Financial loader: value-trap filter needs the YoY columns.
    fin = load_financials_with_yoy() if use_vt else load_financials()
    # Production grid extends to the latest calendar day (month-end rebalance
    # keeps extending as new data arrives); backtest callers keep BT_END.
    grid, industry, size, st = load_aux(end=calendar[-1])

    # Pre-compute past returns for overbought filter if enabled.
    ret_lookup = None
    if use_filter:
        print("[filter] pre-computing past-20d returns for overbought filter ...", flush=True)
        all_codes = sorted(size["ts_code"].unique())
        ret_lookup = compute_past_returns(all_codes, calendar)
        print(f"[filter] done, {len(ret_lookup)} dates computed", flush=True)

    # Pre-compute value-trap flag sets per rebalance date.
    vt_hits = None
    if use_vt:
        print("[filter] pre-computing value-trap (deter_any2) flag sets ...", flush=True)
        vt_hits = build_vt_by_rebalance(fin, grid)
        total = sum(len(v) for v in vt_hits.values())
        print(f"[filter] done, {len(vt_hits)} dates, {total} flagged stock-months", flush=True)

    # Pre-compute T5 event exclusion sets per rebalance date.
    t5_hits = None
    if use_t5:
        print("[filter] loading T5 跌幅上榜 events ...", flush=True)
        t5_events = load_t5_events()
        t5_hits = build_t5_by_rebalance(t5_events, calendar, list(grid["rebalance_date"]))
        print(f"[filter] done, {len(t5_events)} events, "
              f"{sum(1 for v in t5_hits.values() if v)} rebalance days with hits", flush=True)

    if args.replay:
        start, end = pd.Timestamp(args.from_), pd.Timestamp(args.to_)
        grid_win = grid[grid["rebalance_date"].between(start, end)].copy()
        print(f"[replay] {len(grid_win)} rebalance dates from {start.date()} to {end.date()}", flush=True)

        # Pre-load 20-day avg amount for the daily-grid universe once.
        all_codes = sorted(size["ts_code"].unique())
        amount_avg = load_amount_avg(all_codes, calendar)

        holdings = {}
        for _, row in grid_win.iterrows():
            hold = process_month(fin, row, industry, size, st, amount_avg, calendar,
                                 top_k=top_k, overbought_filter=use_filter, ret_lookup=ret_lookup,
                                 value_trap_filter=use_vt, vt_hits=vt_hits,
                                 t5_filter=use_t5, t5_hits=t5_hits)
            if hold.empty:
                print(f"      {row.rebalance_date.date()}: no holdings (data gap?)", flush=True)
                continue
            holdings[row.rebalance_date] = hold
            print(f"      {row.rebalance_date.date()}: top {len(hold)} "
                  f"(top3: {','.join(hold['ts_code'].head(3))})", flush=True)

        # Ledgers.
        held_codes = sorted({c for h in holdings.values() for c in h["ts_code"]})
        rets = daily_returns(held_codes, calendar, start, end)
        bench = rets.get(BENCHMARK)
        rets = rets.drop(columns=[BENCHMARK]) if BENCHMARK in rets.columns else rets

        # Build daily holding + portfolio ledgers with monthly rebalance.
        signal_rows, holding_rows, portfolio_rows = [], [], []
        current_hold = None
        rebal_dates = sorted(holdings)
        trading_days = calendar[(calendar >= start) & (calendar <= end)]
        for day in trading_days:
            if day in rebal_dates:
                current_hold = holdings[day]
            if current_hold is None:
                continue
            for _, r in current_hold.iterrows():
                holding_rows.append({
                    "datetime": day, "rank": int(r["rank"]), "ts_code": r["ts_code"],
                    "neutral_score": r["neutral_composite"], "weight": r["weight"],
                    "is_rebalance_day": bool(day in rebal_dates),
                })
            # portfolio return for this day (close-to-close of held names).
            if day in rets.index:
                day_rets = rets.loc[day].reindex(current_hold["ts_code"]).to_numpy(dtype=float)
                port_ret = np.nanmean(day_rets)
                bench_ret = bench.loc[day] if day in bench.index and pd.notna(bench.loc[day]) else np.nan
                portfolio_rows.append({
                    "datetime": day, "portfolio_return": float(port_ret) if np.isfinite(port_ret) else np.nan,
                    "benchmark_return": float(bench_ret) if np.isfinite(bench_ret) else np.nan,
                    "excess_return": (float(port_ret) - float(bench_ret)) if np.isfinite(port_ret) and np.isfinite(bench_ret) else np.nan,
                    "is_rebalance_day": bool(day in rebal_dates),
                })

        sig_df = pd.concat([h for h in holdings.values()], ignore_index=True)
        sig_df.to_csv(LEDGER_DIR / "signal_ledger.csv", index=False)
        pd.DataFrame(holding_rows).to_csv(LEDGER_DIR / "holding_ledger.csv", index=False)
        pd.DataFrame(portfolio_rows).to_csv(LEDGER_DIR / "portfolio_ledger.csv", index=False)

        check = consistency_check(holdings)
        meta = {
            "mode": "replay", "window": [args.from_, args.to_],
            "rebalance_dates": len(holdings), "holding_days": len(holding_rows),
            "portfolio_days": len(portfolio_rows),
            "consistency": check,
        }
        print(json.dumps(meta, ensure_ascii=False, indent=2), flush=True)
        print(f"consistency: {check['status']} mean_top50_overlap={check.get('mean_top50_overlap')}", flush=True)

    elif args.date:
        T = pd.Timestamp(args.date)
        if T not in set(calendar):
            raise ValueError(f"{args.date} is not a trading day")
        grid_row = grid[grid["rebalance_date"].le(T)].iloc[-1]
        amount_avg = load_amount_avg(sorted(size["ts_code"].unique()), calendar)
        hold = process_month(fin, grid_row, industry, size, st, amount_avg, calendar,
                             top_k=top_k, overbought_filter=use_filter, ret_lookup=ret_lookup,
                             value_trap_filter=use_vt, vt_hits=vt_hits,
                             t5_filter=use_t5, t5_hits=t5_hits)
        rebalance_date = grid_row.rebalance_date
        tags = []
        if use_filter:
            tags.append("revf")
        if use_vt:
            tags.append("vt")
        if use_t5:
            tags.append("t5")
        filter_tag = " +" + "+".join(tags) if tags else ""
        print(f"[date {args.date}] effective rebalance {rebalance_date.date()}: top {len(hold)} (top_k={top_k}{filter_tag})")
        print(hold.to_string(index=False))

        # Live mode: compute BUY/SELL/HOLD diff vs previous month, save actionable list.
        if args.live:
            LIVE_LEDGER_DIR.mkdir(parents=True, exist_ok=True)

            # Find previous rebalance date.
            prev_grid = grid[grid["rebalance_date"].lt(rebalance_date)]
            prev_hold = pd.DataFrame()
            if not prev_grid.empty:
                prev_row = prev_grid.iloc[-1]
                prev_hold = process_month(fin, prev_row, industry, size, st, amount_avg, calendar,
                                          top_k=top_k, overbought_filter=use_filter, ret_lookup=ret_lookup,
                                          value_trap_filter=use_vt, vt_hits=vt_hits,
                                          t5_filter=use_t5, t5_hits=t5_hits)

            current_codes = set(hold["ts_code"]) if not hold.empty else set()
            prev_codes = set(prev_hold["ts_code"]) if not prev_hold.empty else set()
            buy_codes = current_codes - prev_codes
            sell_codes = prev_codes - current_codes
            hold_codes = current_codes & prev_codes

            # Build actionable list with action labels.
            action_rows = []
            if not hold.empty:
                for _, r in hold.iterrows():
                    action = "BUY" if r["ts_code"] in buy_codes else "HOLD"
                    action_rows.append({
                        "rank": int(r["rank"]), "ts_code": r["ts_code"],
                        "weight": round(r["weight"], 6), "action": action,
                    })
            if not prev_hold.empty:
                for _, r in prev_hold.iterrows():
                    if r["ts_code"] in sell_codes:
                        action_rows.append({
                            "rank": 0, "ts_code": r["ts_code"],
                            "weight": 0.0, "action": "SELL",
                        })

            actions = pd.DataFrame(action_rows)
            # Sort: BUY first, then HOLD by rank, then SELL
            action_order = {"BUY": 0, "HOLD": 1, "SELL": 2}
            actions["_order"] = actions["action"].map(action_order)
            actions = actions.sort_values(["_order", "rank"]).drop(columns=["_order"]).reset_index(drop=True)

            live_file = LIVE_LEDGER_DIR / f"signal_{rebalance_date.date()}{'_' + '+'.join(tags) if tags else ''}.csv"
            actions.to_csv(live_file, index=False)

            print(f"\n{'='*64}")
            print(f"LIVE TRADING LIST - rebalance {rebalance_date.date()} (top-{top_k}{filter_tag})")
            print(f"{'='*64}")
            print(f"BUY  ({len(buy_codes)}):  {', '.join(sorted(buy_codes)) if buy_codes else '(none)'}")
            print(f"SELL ({len(sell_codes)}): {', '.join(sorted(sell_codes)) if sell_codes else '(none)'}")
            print(f"HOLD ({len(hold_codes)}): {', '.join(sorted(hold_codes)) if hold_codes else '(none)'}")
            print(f"\nActionable list saved to: {live_file}")
            print(f"\nNext trading day: buy BUY names at open ±0.5%, sell SELL names at open ±0.5%")
            print(f"Each stock weight: {1.0/top_k:.4%} of strategy capital")
    else:
        parser.error("specify --replay or --date")


if __name__ == "__main__":
    main()
