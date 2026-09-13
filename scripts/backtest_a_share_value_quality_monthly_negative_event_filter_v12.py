#!/usr/bin/env python3
"""Negative-event filter portfolio backtest v12 (protocol v1, combination stage).

Runs the v8 top-15 baseline AND the baseline + negative-event exclusion filters
in the same script so all arms share one data-loading environment.

Arms:
  baseline : v8 top-15 identical rules (TOP_K=15)
  t5       : baseline + exclude stocks with a 跌幅上榜 (top_list reason contains
             跌幅/负向) event within the past 20 trading days of the rebalance
             date (event day = trade_date)
  t2       : baseline + exclude stocks with an ST-hat (namechange is_st
             false->true) announcement within the past 20 trading days
             (event day = ann_date; announced-but-not-yet-effective window)

Event data coverage starts 2022-01; the acceptance stages (holdout 2023-2025-06,
new_coverage 2025-07~2026-06) are inside coverage. In development/confirmation
the filter arms have no events to exclude -> identical to baseline.

Acceptance (protocol §5.2), per passing event type, filtered vs baseline:
  holdout (2023-2025-06) stress net excess annualized return does NOT drop
    (tolerance >= -0.5pp),
  AND new_coverage (2025-07~2026-06) stress net excess annualized return
    IMPROVES by >= +5pp.

Protocol: research/protocols/a_share_negative_event_subtype_protocol_v1.md
"""

from __future__ import annotations

import argparse
import glob
import json
from pathlib import Path

import numpy as np
import pandas as pd
import qlib
from qlib.config import REG_CN
from qlib.contrib.evaluate import backtest_daily, risk_analysis
from qlib.contrib.strategy import TopkDropoutStrategy

from load_financials_extended_v1 import load_financials_extended, FIN, _fill_available
from analyze_a_share_value_quality_level_factors_extension_v1 import (
    build_snapshot,
    ols_residual,
    composite_score,
    STYLE_DIR,
    QLIB_DIR,
)
from backtest_a_share_value_quality_monthly_dailygrid_v6 import build_daily_grid
from backtest_a_share_value_quality_monthly_sensitivity_v4 import load_amount_avg
from run_daily_signal_pipeline_v1 import st_codes_at, qlib_symbol

TOP_K = 15
PARTICIPATION = 0.05
ACCOUNT = 100_000_000
NOTIONAL = ACCOUNT // TOP_K
BENCHMARK = "SH000852"
ANNUALIZATION_DAYS = 238
COST_SCENARIOS = {
    "base": {"open_cost": 0.0005, "close_cost": 0.0015},
    "stress": {"open_cost": 0.0010, "close_cost": 0.0030},
}
STAGES = {
    "development": (pd.Timestamp("2016-01-01"), pd.Timestamp("2019-12-31")),
    "confirmation": (pd.Timestamp("2020-01-01"), pd.Timestamp("2022-12-31")),
    "holdout": (pd.Timestamp("2023-01-01"), pd.Timestamp("2025-06-30")),
    "new_coverage": (pd.Timestamp("2025-07-01"), pd.Timestamp("2026-06-30")),
}
BT_START = pd.Timestamp("2016-01-01")
BT_END = pd.Timestamp("2026-06-30")
ST_INTERVALS = Path("data/external/tushare/a_share_st_status_pit_v1/normalized/st_status_intervals.csv.gz")
EVENTS_DIR = Path("data/external/tushare/a_share_events_daily_v1/raw")
FILTER_WINDOW_DAYS = 20  # 调仓日前 20 个交易日内有事件则剔除


def ts_to_qlib(code: str) -> str | float:
    if not isinstance(code, str) or "." not in code:
        return np.nan
    num, ex = code.split(".")
    if ex not in ("SH", "SZ", "BJ"):
        return np.nan
    return f"{ex}{num}"


def load_t5_events() -> pd.DataFrame:
    """T5 跌幅上榜：top_list reason 含跌幅/负向，事件日=trade_date（交易日）。"""
    files = sorted(Path(p) for p in glob.glob(str(EVENTS_DIR / "*top_list.csv.gz")))
    df = pd.concat([pd.read_csv(f, compression="gzip") for f in files], ignore_index=True)
    df["instrument"] = df["ts_code"].map(ts_to_qlib)
    df["trade_date"] = pd.to_datetime(df["trade_date"].astype(str), format="%Y%m%d")
    neg = df[df["reason"].str.contains("跌幅|负向", na=False)]
    out = neg[["instrument", "trade_date"]].drop_duplicates()
    out = out.rename(columns={"trade_date": "event_date"})
    out = out.dropna(subset=["instrument"])
    return out


def load_t2_events() -> pd.DataFrame:
    """T2 ST 戴帽：namechange is_st false->true，事件日=ann_date（公告日）。"""
    st = pd.read_csv(ST_INTERVALS, compression="gzip", parse_dates=["start_date", "end_date", "ann_date"])
    st = st.sort_values(["ts_code", "start_date"])
    st["instrument"] = st["ts_code"].map(ts_to_qlib)
    st = st.dropna(subset=["instrument"])
    st = st[~st["instrument"].str.startswith("BJ")]
    st["prev_is_st"] = st.groupby("instrument")["is_st"].shift(1)
    hat = st[(st["is_st"]) & (st["prev_is_st"].fillna(False) == False)]  # noqa: E712
    hat = hat.dropna(subset=["ann_date"])
    out = hat[["instrument", "ann_date"]].drop_duplicates()
    out = out.rename(columns={"ann_date": "event_date"})
    return out


def build_event_sets(events: pd.DataFrame, calendar: pd.DatetimeIndex,
                     rebalance_dates: list[pd.Timestamp]) -> dict[str, set[str]]:
    """每个调仓日：过去 FILTER_WINDOW_DAYS 个交易日内有事件的 ts_code 集合。

    事件表 instrument 为 qlib 格式（SH600000），返回集合用 ts_code 格式
    （600000.SH），与 build_snapshots 中 frame["ts_code"] 匹配。
    """
    cal_list = list(calendar)
    cal_pos = {d: i for i, d in enumerate(cal_list)}
    # ts_code -> sorted event dates
    ev = events.copy()
    ev["ts_code"] = ev["instrument"].map(
        lambda c: f"{c[2:]}.{c[:2]}" if isinstance(c, str) and len(c) == 8 else np.nan)
    ev = ev.dropna(subset=["ts_code"])
    ev_by_code = ev.groupby("ts_code")["event_date"].apply(
        lambda s: np.array(sorted(s))).to_dict()

    out: dict[pd.Timestamp, set[str]] = {}
    for rb in rebalance_dates:
        if rb not in cal_pos:
            continue
        pos = cal_pos[rb]
        win_start = cal_list[max(0, pos - FILTER_WINDOW_DAYS)]
        hits = set()
        for code, dates in ev_by_code.items():
            idx = np.searchsorted(dates, win_start)
            if idx < len(dates) and dates[idx] <= rb:
                hits.add(code)
        out[rb] = hits
    return out


def build_snapshots(fin, grid, industry, size_daily, st, amount_avg,
                    exclude_by_rebalance: dict[pd.Timestamp, set[str]] | None) -> dict:
    snapshots = {}
    for _, row in grid.iterrows():
        snap = build_snapshot(fin, row, industry, size_daily)
        if snap.empty:
            continue
        frame = snap.copy()
        frame["composite"] = composite_score(frame)
        frame.loc[frame["ts_code"].isin(st_codes_at(st, row.asof_date)), "composite"] = np.nan
        avg = amount_avg.loc[row.asof_date].reindex(frame["ts_code"]).to_numpy(dtype=float) * 1000.0
        min_amount = NOTIONAL / PARTICIPATION
        frame.loc[avg < min_amount, "composite"] = np.nan
        # Negative-event exclusion layer (the only change of filtered arms).
        if exclude_by_rebalance is not None:
            hits = exclude_by_rebalance.get(row.rebalance_date, set())
            if hits:
                frame.loc[frame["ts_code"].isin(hits), "composite"] = np.nan
        valid = frame.dropna(subset=["composite", "log_size", "l1_code"])
        if len(valid) < 50:
            continue
        resid = ols_residual(valid["composite"], valid["l1_code"], valid["log_size"])
        frame["neutral_composite"] = resid.reindex(frame.index)
        snapshots[row.rebalance_date] = frame
    return snapshots


def signal_from_snapshots(snapshots: dict, calendar: pd.DatetimeIndex) -> pd.Series:
    wide = pd.DataFrame({d: f.set_index("ts_code")["neutral_composite"] for d, f in snapshots.items()}).T
    cal_win = calendar[(calendar >= BT_START) & (calendar <= BT_END)]
    wide = wide.reindex(cal_win).ffill()
    long = wide.stack().rename("score").dropna().reset_index()
    long.columns = ["datetime", "ts_code", "score"]
    long["instrument"] = long["ts_code"].map(qlib_symbol)
    return long.set_index(["datetime", "instrument"])["score"].sort_index()


def run_backtest(signal: pd.Series) -> pd.DataFrame:
    bt_rows = []
    for scenario, costs in COST_SCENARIOS.items():
        strategy = TopkDropoutStrategy(signal=signal, topk=TOP_K, n_drop=TOP_K)
        report, _ = backtest_daily(
            start_time=BT_START, end_time=BT_END, strategy=strategy,
            account=ACCOUNT, benchmark=BENCHMARK,
            exchange_kwargs={"limit_threshold": 0.095, "deal_price": "open",
                             "open_cost": costs["open_cost"], "close_cost": costs["close_cost"],
                             "min_cost": 5},
        )
        for stage, (s0, s1) in STAGES.items():
            sample = report.loc[s0:s1]
            if sample.empty:
                continue
            gross = risk_analysis(sample["return"] - sample["bench"], freq="day")["risk"]
            net = risk_analysis(sample["return"] - sample["bench"] - sample["cost"], freq="day")["risk"]
            bt_rows.append({
                "stage": stage, "cost_scenario": scenario,
                "trading_days": int(len(sample)),
                "gross_excess_annualized_return": float(gross["annualized_return"]),
                "gross_excess_ir": float(gross["information_ratio"]),
                "net_excess_annualized_return": float(net["annualized_return"]),
                "net_excess_ir": float(net["information_ratio"]),
                "net_excess_max_drawdown": float(net["max_drawdown"]),
                "average_daily_turnover_rate": float(sample["turnover"].mean()),
                "annualized_cost_drag": float(sample["cost"].mean() * ANNUALIZATION_DAYS),
            })
    return pd.DataFrame(bt_rows)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path,
                        default=Path("output/analysis_fundamental/a_share_value_quality_monthly_strategy_v12_negative_event_filter"))
    args = parser.parse_args()
    out = args.output_dir
    if out.exists() and any(out.iterdir()):
        raise FileExistsError(f"Refusing to overwrite existing experiment output: {out}")
    out.mkdir(parents=True, exist_ok=True)

    qlib.init(provider_uri=str(QLIB_DIR), region=REG_CN)
    calendar = pd.DatetimeIndex(pd.to_datetime(pd.read_csv(QLIB_DIR / "calendars" / "day.txt", header=None)[0]))

    print("[1/7] Loading extended financials & daily grid ...", flush=True)
    fin = load_financials_extended()
    grid, size_daily = build_daily_grid()
    print(f"      months={len(grid)} {grid['rebalance_date'].min().date()} .. {grid['rebalance_date'].max().date()}", flush=True)

    industry = pd.read_csv(STYLE_DIR / "industry_l1_effective_intervals.csv.gz", compression="gzip", dtype=str)
    industry["in_date"] = pd.to_datetime(industry["in_date"], errors="coerce")
    industry["out_date"] = pd.to_datetime(industry["out_date"], errors="coerce")
    st = pd.read_csv(ST_INTERVALS, compression="gzip", parse_dates=["start_date", "end_date"])
    universe_codes = sorted(size_daily["ts_code"].unique())
    amount_avg = load_amount_avg(universe_codes, calendar)

    print("[2/7] Loading negative events (T5 跌幅上榜 / T2 ST 戴帽) ...", flush=True)
    t5 = load_t5_events()
    t2 = load_t2_events()
    print(f"      T5 events={len(t5):,}  T2 events={len(t2):,}", flush=True)

    rb_dates = [pd.Timestamp(d) for d in grid["rebalance_date"]]
    print("[3/7] Building per-rebalance exclusion sets ...", flush=True)
    t5_sets = build_event_sets(t5, calendar, rb_dates)
    t2_sets = build_event_sets(t2, calendar, rb_dates)

    print("[4/7] Building baseline snapshots ...", flush=True)
    base_snaps = build_snapshots(fin, grid, industry, size_daily, st, amount_avg, None)
    print(f"      baseline valid months={len(base_snaps)}", flush=True)
    print("[5/7] Building T5/T2 filtered snapshots ...", flush=True)
    t5_snaps = build_snapshots(fin, grid, industry, size_daily, st, amount_avg, t5_sets)
    t2_snaps = build_snapshots(fin, grid, industry, size_daily, st, amount_avg, t2_sets)
    print(f"      t5 valid months={len(t5_snaps)}  t2 valid months={len(t2_snaps)}", flush=True)

    print("[6/7] Building signals & backtesting ...", flush=True)
    arms = {
        "baseline": signal_from_snapshots(base_snaps, calendar),
        "t5": signal_from_snapshots(t5_snaps, calendar),
        "t2": signal_from_snapshots(t2_snaps, calendar),
    }
    bt_frames = []
    for name, sig in arms.items():
        bt_arm = run_backtest(sig)
        bt_arm["arm"] = name
        bt_frames.append(bt_arm)
        print(f"      {name}: signal rows={len(sig)}", flush=True)
    bt = pd.concat(bt_frames, ignore_index=True)
    bt.to_csv(out / "backtest_summary.csv", index=False)

    print("[7/7] Decision ...", flush=True)
    def pick(arm: str, stage: str, scenario: str, column: str) -> float:
        row = bt[(bt["arm"].eq(arm)) & (bt["stage"].eq(stage)) & (bt["cost_scenario"].eq(scenario))]
        return float(row[column].iloc[0]) if len(row) else np.nan

    decisions = {}
    for arm_name, arm_label in [("t5", "T5 跌幅上榜"), ("t2", "T2 ST 戴帽")]:
        hol_base = pick("baseline", "holdout", "stress", "net_excess_annualized_return")
        hol_filt = pick(arm_name, "holdout", "stress", "net_excess_annualized_return")
        new_base = pick("baseline", "new_coverage", "stress", "net_excess_annualized_return")
        new_filt = pick(arm_name, "new_coverage", "stress", "net_excess_annualized_return")
        holdout_delta = hol_filt - hol_base
        new_coverage_delta = new_filt - new_base
        holdout_ok = bool(holdout_delta >= -0.005)
        new_coverage_ok = bool(new_coverage_delta >= 0.05)
        if holdout_ok and new_coverage_ok:
            decision = f"{arm_name}_filter_adopted"
        elif holdout_ok and not new_coverage_ok:
            decision = f"{arm_name}_filter_neutral_holdout_ok"
        elif not holdout_ok and new_coverage_ok:
            decision = f"{arm_name}_filter_holdout_erosion"
        else:
            decision = f"{arm_name}_filter_not_adopted"
        decisions[arm_name] = {
            "decision": decision,
            "baseline_holdout_stress_net": hol_base,
            "filtered_holdout_stress_net": hol_filt,
            "holdout_delta_pp": holdout_delta * 100,
            "holdout_ok": holdout_ok,
            "baseline_new_coverage_stress_net": new_base,
            "filtered_new_coverage_stress_net": new_filt,
            "new_coverage_delta_pp": new_coverage_delta * 100,
            "new_coverage_ok": new_coverage_ok,
        }
    (out / "decision.json").write_text(json.dumps(decisions, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    methodology = {
        "protocol": "research/protocols/a_share_negative_event_subtype_protocol_v1.md",
        "arms": {
            "baseline": "v8 top-15 identical rules (TOP_K=15)",
            "t5": "baseline + exclude 跌幅上榜 events within past 20 trading days",
            "t2": "baseline + exclude ST-hat announcements within past 20 trading days",
        },
        "grid": "daily_basic_pit month-end trading day",
        "topk": TOP_K,
        "execution": "TopkDropout t+1 open; limit_threshold 0.095; min_cost 5",
        "cost_scenarios": COST_SCENARIOS,
        "benchmark": BENCHMARK,
        "stages": {k: [v[0].isoformat(), v[1].isoformat()] for k, v in STAGES.items()},
        "backtest_window": [str(BT_START.date()), str(BT_END.date())],
        "event_data_coverage": "2022-01 onwards (dev/confirmation filter arms == baseline)",
        "created_at_utc": pd.Timestamp.utcnow().isoformat(),
    }
    (out / "methodology.json").write_text(json.dumps(methodology, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    lines = [
        "负面事件剔除层组合回测 v12（v8 top-15 基线 vs 基线+T5/T2 剔除层）",
        "=" * 64,
        "对比（压力费后净超额，相对 SH000852）：",
        bt.pivot_table(index=["stage", "cost_scenario"], columns="arm",
                       values=["net_excess_annualized_return", "net_excess_ir", "net_excess_max_drawdown"]).to_string(),
        "",
    ]
    for arm_name, arm_label in [("t5", "T5 跌幅上榜"), ("t2", "T2 ST 戴帽")]:
        d = decisions[arm_name]
        lines.append(
            f"{arm_label}：holdout {d['baseline_holdout_stress_net']*100:.2f}% -> "
            f"{d['filtered_holdout_stress_net']*100:.2f}% (delta {d['holdout_delta_pp']:+.2f}pp, "
            f"门槛 >=-0.5pp → {'通过' if d['holdout_ok'] else '不通过'})")
        lines.append(
            f"  new_coverage {d['baseline_new_coverage_stress_net']*100:.2f}% -> "
            f"{d['filtered_new_coverage_stress_net']*100:.2f}% (delta {d['new_coverage_delta_pp']:+.2f}pp, "
            f"门槛 >=+5pp → {'通过' if d['new_coverage_ok'] else '不通过'}) → 判定 {d['decision']}")
    lines.append("")
    lines.append("注：事件数据自 2022-01 起，development/confirmation 期过滤臂无事件可剔除，等价基线。")
    (out / "strategy_report.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("\n".join(lines))


if __name__ == "__main__":
    main()
