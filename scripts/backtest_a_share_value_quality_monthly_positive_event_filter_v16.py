#!/usr/bin/env python3
"""Positive-event filter portfolio backtest v16 (protocol v1, combination stage).

Runs the v8 top-15 baseline AND the baseline + positive-event exclusion filters
in the same script so all arms share one data-loading environment.

Arms:
  baseline : v8 top-15 identical rules (TOP_K=15)
  p1       : baseline + exclude stocks with a 正面业绩预告 (forecast type in
             {预增,略增,扭亏,续盈}) announcement within the past 20 trading days
             of the rebalance date (event day = ann_date)
  p2       : baseline + exclude stocks with a 股东增持 (stk_holdertrade in_de==IN)
             announcement within the past 20 trading days (event day = ann_date)
  p3       : baseline + exclude stocks with a 涨幅上榜 (top_list reason contains
             涨幅偏离/涨幅达到) listing within the past 20 trading days
             (event day = trade_date)
  pall     : baseline + exclude stocks hit by ANY of p1/p2/p3

Eligibility (protocol §5): an arm is judged against the double gate ONLY if its
event-layer verdict is negative_drift_pass (利好兑现). P3 is always eligible
(event layer cited from labelfix closure). Eligibility is read from
output/analysis_static/a_share_positive_event_subtype_v1/decision.json if
present; otherwise p3 is the only eligible arm.

Acceptance (protocol §5.2), per eligible arm, filtered vs baseline:
  holdout (2023-2025-06) stress net excess annualized return does NOT drop
    (tolerance >= -0.5pp),
  AND new_coverage (2025-07~2026-06) stress net excess annualized return
    IMPROVES by >= +5pp.

Protocol: research/protocols/a_share_positive_event_subtype_protocol_v1.md
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
FORECAST_DIR = Path("data/external/tushare/a_share_forecast_v1/raw")
EVENT_LAYER_DECISION = Path("output/analysis_static/a_share_positive_event_subtype_v1/decision.json")
FILTER_WINDOW_DAYS = 20  # 调仓日前 20 个交易日内有事件则剔除
FORECAST_POSITIVE_TYPES = {"预增", "略增", "扭亏", "续盈"}
P3_POS_KEYWORDS = ("涨幅偏离", "涨幅达到")


def ts_to_qlib(code: str) -> str | float:
    if not isinstance(code, str) or "." not in code:
        return np.nan
    num, ex = code.split(".")
    if ex not in ("SH", "SZ", "BJ"):
        return np.nan
    return f"{ex}{num}"


def load_p1_events() -> pd.DataFrame:
    """P1 正面业绩预告：type ∈ 正面四类，事件日=ann_date。"""
    files = sorted(Path(p) for p in glob.glob(str(FORECAST_DIR / "*_forecast.csv.gz")))
    df = pd.concat([pd.read_csv(f, compression="gzip") for f in files], ignore_index=True)
    df["instrument"] = df["ts_code"].map(ts_to_qlib)
    df["ann_date"] = pd.to_datetime(df["ann_date"].astype(str), format="%Y%m%d")
    df = df[df["type"].isin(FORECAST_POSITIVE_TYPES)]
    out = df[["instrument", "ann_date"]].drop_duplicates().dropna(subset=["instrument"])
    out = out.rename(columns={"ann_date": "event_date"})
    return out


def load_p2_events() -> pd.DataFrame:
    """P2 增持：in_de==IN，事件日=ann_date。"""
    files = sorted(Path(p) for p in glob.glob(str(EVENTS_DIR / "*stk_holdertrade.csv.gz")))
    df = pd.concat([pd.read_csv(f, compression="gzip") for f in files], ignore_index=True)
    df["instrument"] = df["ts_code"].map(ts_to_qlib)
    df["ann_date"] = pd.to_datetime(df["ann_date"].astype(str), format="%Y%m%d")
    df = df[df["in_de"].eq("IN")]
    out = df[["instrument", "ann_date"]].drop_duplicates().dropna(subset=["instrument"])
    out = out.rename(columns={"ann_date": "event_date"})
    return out


def load_p3_events() -> pd.DataFrame:
    """P3 涨幅上榜：top_list reason 含正向关键词，事件日=trade_date（交易日）。"""
    files = sorted(Path(p) for p in glob.glob(str(EVENTS_DIR / "*top_list.csv.gz")))
    df = pd.concat([pd.read_csv(f, compression="gzip") for f in files], ignore_index=True)
    df["instrument"] = df["ts_code"].map(ts_to_qlib)
    df["trade_date"] = pd.to_datetime(df["trade_date"].astype(str), format="%Y%m%d")
    pos = df[df["reason"].str.contains("|".join(P3_POS_KEYWORDS), na=False)]
    out = pos[["instrument", "trade_date"]].drop_duplicates().dropna(subset=["instrument"])
    out = out.rename(columns={"trade_date": "event_date"})
    return out


def build_event_sets(events: pd.DataFrame, calendar: pd.DatetimeIndex,
                     rebalance_dates: list[pd.Timestamp]) -> dict[str, set[str]]:
    """每个调仓日：过去 FILTER_WINDOW_DAYS 个交易日内有事件的 ts_code 集合。"""
    cal_list = list(calendar)
    cal_pos = {d: i for i, d in enumerate(cal_list)}
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
        # Positive-event exclusion layer (the only change of filtered arms).
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
                        default=Path("output/analysis_fundamental/a_share_value_quality_monthly_strategy_v16_positive_event_filter"))
    args = parser.parse_args()
    out = args.output_dir
    if out.exists() and any(out.iterdir()):
        raise FileExistsError(f"Refusing to overwrite existing experiment output: {out}")
    out.mkdir(parents=True, exist_ok=True)

    qlib.init(provider_uri=str(QLIB_DIR), region=REG_CN)
    calendar = pd.DatetimeIndex(pd.to_datetime(pd.read_csv(QLIB_DIR / "calendars" / "day.txt", header=None)[0]))

    print("[1/8] Loading extended financials & daily grid ...", flush=True)
    fin = load_financials_extended()
    grid, size_daily = build_daily_grid()
    print(f"      months={len(grid)} {grid['rebalance_date'].min().date()} .. {grid['rebalance_date'].max().date()}", flush=True)

    industry = pd.read_csv(STYLE_DIR / "industry_l1_effective_intervals.csv.gz", compression="gzip", dtype=str)
    industry["in_date"] = pd.to_datetime(industry["in_date"], errors="coerce")
    industry["out_date"] = pd.to_datetime(industry["out_date"], errors="coerce")
    st = pd.read_csv(ST_INTERVALS, compression="gzip", parse_dates=["start_date", "end_date"])
    universe_codes = sorted(size_daily["ts_code"].unique())
    amount_avg = load_amount_avg(universe_codes, calendar)

    print("[2/8] Loading positive events (P1 正面预告 / P2 增持 / P3 涨幅上榜) ...", flush=True)
    p1 = load_p1_events()
    p2 = load_p2_events()
    p3 = load_p3_events()
    print(f"      P1 events={len(p1):,}  P2 events={len(p2):,}  P3 events={len(p3):,}", flush=True)

    print("[3/8] Eligibility from event-layer decision ...", flush=True)
    eligible = {"p3": True}  # P3: event layer cited from labelfix closure
    if EVENT_LAYER_DECISION.exists():
        try:
            ev_dec = json.loads(EVENT_LAYER_DECISION.read_text(encoding="utf-8"))["decisions"]
            for t, d in ev_dec.items():
                if d.get("verdict") == "negative_drift_pass":
                    eligible[t.lower()] = True
        except Exception as exc:  # noqa: BLE001
            print(f"      warning: cannot read event-layer decision: {exc}", flush=True)
    # 合并臂 = 仅合格事件类型的并集；至少一个合格才判定
    pall_eligible = bool(eligible)
    print(f"      eligible arms: {sorted(eligible)}  pall_eligible={pall_eligible}", flush=True)

    rb_dates = [pd.Timestamp(d) for d in grid["rebalance_date"]]
    print("[4/8] Building per-rebalance exclusion sets ...", flush=True)
    p1_sets = build_event_sets(p1, calendar, rb_dates)
    p2_sets = build_event_sets(p2, calendar, rb_dates)
    p3_sets = build_event_sets(p3, calendar, rb_dates)
    pall_sets = {}
    for d in rb_dates:
        hits: set[str] = set()
        for name, sets in (("p1", p1_sets), ("p2", p2_sets), ("p3", p3_sets)):
            if name in eligible:
                hits |= sets.get(d, set())
        pall_sets[d] = hits

    print("[5/8] Building baseline snapshots ...", flush=True)
    base_snaps = build_snapshots(fin, grid, industry, size_daily, st, amount_avg, None)
    print(f"      baseline valid months={len(base_snaps)}", flush=True)
    print("[6/8] Building filtered snapshots ...", flush=True)
    arm_snaps = {}
    for name, sets in [("p1", p1_sets), ("p2", p2_sets), ("p3", p3_sets), ("pall", pall_sets)]:
        arm_snaps[name] = build_snapshots(fin, grid, industry, size_daily, st, amount_avg, sets)
        print(f"      {name} valid months={len(arm_snaps[name])}", flush=True)

    print("[7/8] Building signals & backtesting ...", flush=True)
    arms = {"baseline": signal_from_snapshots(base_snaps, calendar)}
    for name, snaps in arm_snaps.items():
        arms[name] = signal_from_snapshots(snaps, calendar)
    bt_frames = []
    for name, sig in arms.items():
        bt_arm = run_backtest(sig)
        bt_arm["arm"] = name
        bt_frames.append(bt_arm)
        print(f"      {name}: signal rows={len(sig)}", flush=True)
    bt = pd.concat(bt_frames, ignore_index=True)
    bt.to_csv(out / "backtest_summary.csv", index=False)

    print("[7/8] Eligibility from event-layer decision ...", flush=True)
    eligible = {"p3": True}  # P3: event layer cited from labelfix closure
    if EVENT_LAYER_DECISION.exists():
        try:
            ev_dec = json.loads(EVENT_LAYER_DECISION.read_text(encoding="utf-8"))["decisions"]
            for t, d in ev_dec.items():
                if d.get("verdict") == "negative_drift_pass":
                    eligible[t.lower()] = True
        except Exception as exc:  # noqa: BLE001
            print(f"      warning: cannot read event-layer decision: {exc}", flush=True)
    print(f"      eligible arms: {sorted(eligible)}", flush=True)

    print("[8/8] Decision ...", flush=True)
    def pick(arm: str, stage: str, scenario: str, column: str) -> float:
        row = bt[(bt["arm"].eq(arm)) & (bt["stage"].eq(stage)) & (bt["cost_scenario"].eq(scenario))]
        return float(row[column].iloc[0]) if len(row) else np.nan

    decisions = {}
    arm_labels = {"p1": "P1 正面预告", "p2": "P2 增持", "p3": "P3 涨幅上榜", "pall": "P 合并(仅合格)"}
    for arm_name, arm_label in arm_labels.items():
        hol_base = pick("baseline", "holdout", "stress", "net_excess_annualized_return")
        hol_filt = pick(arm_name, "holdout", "stress", "net_excess_annualized_return")
        new_base = pick("baseline", "new_coverage", "stress", "net_excess_annualized_return")
        new_filt = pick(arm_name, "new_coverage", "stress", "net_excess_annualized_return")
        holdout_delta = hol_filt - hol_base
        new_coverage_delta = new_filt - new_base
        entry = {
            "arm": arm_name,
            "eligible": (arm_name in eligible) if arm_name != "pall" else pall_eligible,
            "baseline_holdout_stress_net": hol_base,
            "filtered_holdout_stress_net": hol_filt,
            "holdout_delta_pp": holdout_delta * 100,
            "baseline_new_coverage_stress_net": new_base,
            "filtered_new_coverage_stress_net": new_filt,
            "new_coverage_delta_pp": new_coverage_delta * 100,
        }
        arm_eligible = entry["eligible"]
        if arm_eligible:
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
            entry.update({"holdout_ok": holdout_ok, "new_coverage_ok": new_coverage_ok,
                          "decision": decision})
        else:
            entry.update({"holdout_ok": None, "new_coverage_ok": None,
                          "decision": "not_eligible"})
        decisions[arm_name] = entry
    (out / "decision.json").write_text(json.dumps(decisions, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    methodology = {
        "protocol": "research/protocols/a_share_positive_event_subtype_protocol_v1.md",
        "arms": {
            "baseline": "v8 top-15 identical rules (TOP_K=15)",
            "p1": "baseline + exclude 正面业绩预告 within past 20 trading days",
            "p2": "baseline + exclude 股东增持 within past 20 trading days",
            "p3": "baseline + exclude 涨幅上榜 within past 20 trading days",
            "pall": "baseline + exclude union of p1/p2/p3",
        },
        "grid": "daily_basic_pit month-end trading day",
        "topk": TOP_K,
        "execution": "TopkDropout t+1 open; limit_threshold 0.095; min_cost 5",
        "cost_scenarios": COST_SCENARIOS,
        "benchmark": BENCHMARK,
        "stages": {k: [v[0].isoformat(), v[1].isoformat()] for k, v in STAGES.items()},
        "backtest_window": [str(BT_START.date()), str(BT_END.date())],
        "event_data_coverage": "2022-01 onwards (dev/confirmation filter arms == baseline)",
        "eligibility": sorted(eligible),
        "created_at_utc": pd.Timestamp.utcnow().isoformat(),
    }
    (out / "methodology.json").write_text(json.dumps(methodology, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    lines = [
        "正面事件剔除层组合回测 v16（v8 top-15 基线 vs 基线+P1/P2/P3/P合并 剔除层）",
        "=" * 64,
        "对比（压力费后净超额，相对 SH000852）：",
        bt.pivot_table(index=["stage", "cost_scenario"], columns="arm",
                       values=["net_excess_annualized_return", "net_excess_ir", "net_excess_max_drawdown"]).to_string(),
        "",
    ]
    for arm_name, arm_label in arm_labels.items():
        d = decisions[arm_name]
        if d["eligible"]:
            lines.append(
                f"{arm_label}：holdout {d['baseline_holdout_stress_net']*100:.2f}% -> "
                f"{d['filtered_holdout_stress_net']*100:.2f}% (delta {d['holdout_delta_pp']:+.2f}pp, "
                f"门槛 >=-0.5pp → {'通过' if d['holdout_ok'] else '不通过'})")
            lines.append(
                f"  new_coverage {d['baseline_new_coverage_stress_net']*100:.2f}% -> "
                f"{d['filtered_new_coverage_stress_net']*100:.2f}% (delta {d['new_coverage_delta_pp']:+.2f}pp, "
                f"门槛 >=+5pp → {'通过' if d['new_coverage_ok'] else '不通过'}) → 判定 {d['decision']}")
        else:
            lines.append(f"{arm_label}：事件层未判'利好兑现'（verdict 非 negative_drift_pass）→ 不判定（not_eligible）")
    lines.append("")
    lines.append("注：事件数据自 2022-01 起，development/confirmation 期过滤臂无事件可剔除，等价基线。")
    (out / "strategy_report.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("\n".join(lines))


if __name__ == "__main__":
    main()
