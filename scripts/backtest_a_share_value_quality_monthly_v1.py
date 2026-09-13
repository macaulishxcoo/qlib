#!/usr/bin/env python3
"""Monthly multi-factor strategy backtest for the validated value/quality factors.

Builds the frozen composite (equal-weight percentile-rank average of ep, bm,
div_yield, accruals), applies the frozen liquidity floor, and backtests a
monthly top-50 equal-weight portfolio in Qlib under base and stress costs.

Protocol: research/protocols/a_share_value_quality_monthly_strategy_protocol_v1.md
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
from qlib.contrib.evaluate import backtest_daily, risk_analysis
from qlib.contrib.strategy import TopkDropoutStrategy

from analyze_a_share_value_quality_level_factors_extension_v1 import (
    load_financials,
    build_snapshot,
    composite_score,
    STYLE_DIR,
    QLIB_DIR,
    HORIZONS,
)

COMPOSITE_FACTORS = ("ep", "bm", "div_yield", "accruals")
TOP_K = 50
LIQ_QUANTILE = 0.20
ACCOUNT = 100_000_000
BENCHMARK = "SH000852"
BT_START = pd.Timestamp("2014-01-01")
BT_END = pd.Timestamp("2025-06-30")
ANNUALIZATION_DAYS = 238
COST_SCENARIOS = {
    "base": {"open_cost": 0.0005, "close_cost": 0.0015},
    "stress": {"open_cost": 0.0010, "close_cost": 0.0030},
}
STAGES = {
    "development": (pd.Timestamp("2014-01-01"), pd.Timestamp("2019-12-31")),
    "confirmation": (pd.Timestamp("2020-01-01"), pd.Timestamp("2022-12-31")),
    "holdout": (pd.Timestamp("2023-01-01"), pd.Timestamp("2025-06-30")),
}


def qlib_symbol(code: str) -> str:
    number, suffix = code.split(".")
    return f"{suffix}{number}"


def load_amount_avg(codes: list[str], calendar: pd.DatetimeIndex) -> pd.DataFrame:
    """Prior-20-trading-day average dollar amount per code, indexed by asof date.

    ``codes`` are Tushare codes ('600519.SH'); converted to Qlib symbols for
    feature access.  Uses a 30-day warmup before BT_START so the first month has
    a valid average.
    """
    qlib_codes = [qlib_symbol(c) for c in codes]
    warm_start = calendar[calendar.searchsorted(BT_START) - 30]
    raw = (
        D.features(qlib_codes, ["$amount"], start_time=warm_start, end_time=BT_END, freq="day")
        .rename(columns={"$amount": "amount"})
        .reset_index()
    )
    raw["ts_code"] = raw["instrument"].map(lambda s: f"{s[2:]}.{s[:2]}")
    piv = raw.pivot_table(index="datetime", columns="ts_code", values="amount", aggfunc="sum")
    return piv.rolling(20, min_periods=5).mean().reindex(calendar)


def build_composite_snapshots(fin, grid, industry, size) -> dict[pd.Timestamp, pd.DataFrame]:
    """Monthly composite (percentile-rank average) with liquidity floor applied.

    Returns {rebalance_date: DataFrame[ts_code, composite, log_size, l1_code]}.
    """
    out = {}
    for _, row in grid.iterrows():
        date = row.rebalance_date
        snap = build_snapshot(fin, row, industry, size)
        if snap.empty:
            continue
        frame = snap.copy()
        frame["composite"] = composite_score(frame)
        out[date] = frame[["ts_code", "composite", "log_size", "l1_code"]]
    return out


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, default=Path("output/analysis_fundamental/a_share_value_quality_monthly_strategy_v1"))
    parser.add_argument("--panel-path", type=Path, default=None,
                        help="reuse an existing monthly_composite_signal.csv.gz (skips the 13-min snapshot build)")
    args = parser.parse_args()
    out = args.output_dir
    if out.exists() and any(out.iterdir()):
        raise FileExistsError(f"Refusing to overwrite existing experiment output: {out}")
    out.mkdir(parents=True, exist_ok=True)

    qlib.init(provider_uri=str(QLIB_DIR), region=REG_CN)
    calendar = pd.DatetimeIndex(pd.to_datetime(pd.read_csv(QLIB_DIR / "calendars" / "day.txt", header=None)[0]))

    print("[1/5] Loading financial PIT tables ...", flush=True)
    fin = load_financials()
    grid = pd.read_csv(STYLE_DIR / "monthly_rebalance_grid.csv.gz", compression="gzip", parse_dates=["rebalance_date", "asof_date"])
    grid = grid[grid["rebalance_date"].between(BT_START, BT_END)].copy()
    industry = pd.read_csv(STYLE_DIR / "industry_l1_effective_intervals.csv.gz", compression="gzip", dtype=str)
    industry["in_date"] = pd.to_datetime(industry["in_date"], errors="coerce")
    industry["out_date"] = pd.to_datetime(industry["out_date"], errors="coerce")
    size = pd.read_csv(STYLE_DIR / "monthly_free_float_size.csv.gz", compression="gzip")
    size["asof_date"] = pd.to_datetime(size["asof_date"], errors="coerce")
    print(f"      months={len(grid)}", flush=True)

    print("[2/5] Building composite monthly signals ...", flush=True)
    if args.panel_path is not None:
        panel = pd.read_csv(args.panel_path, compression="gzip")
        panel["rebalance_date"] = pd.to_datetime(panel["rebalance_date"])
        print(f"      resumed from {args.panel_path.name}: months={panel['rebalance_date'].nunique()}", flush=True)
        snapshots = {d: g[["ts_code", "composite", "log_size", "l1_code"]].copy()
                     for d, g in panel.groupby("rebalance_date")}
    else:
        snapshots = build_composite_snapshots(fin, grid, industry, size)

        # Liquidity floor: 20d average amount at each asof, exclude bottom 20%.
        all_codes = sorted({code for frame in snapshots.values() for code in frame["ts_code"]})
        amount_avg = load_amount_avg(all_codes, calendar)
        for date, frame in snapshots.items():
            asof = grid[grid["rebalance_date"].eq(date)].iloc[0]["asof_date"]
            # reindex to the snapshot's codes: delisted names absent from
            # D.instruments("all") become NaN and are kept (not filtered).
            liq = amount_avg.loc[asof].reindex(frame["ts_code"]).to_numpy(dtype=float)
            threshold = np.nanquantile(liq, LIQ_QUANTILE)
            frame.loc[liq < threshold, "composite"] = np.nan

        # Persist monthly composite panel.
        panel_rows = []
        for date, frame in snapshots.items():
            item = frame.copy()
            item["rebalance_date"] = date
            panel_rows.append(item)
        panel = pd.concat(panel_rows, ignore_index=True)
        panel.to_csv(out / "monthly_composite_signal.csv.gz", index=False, compression="gzip")

    # Build daily forward-filled signal for qlib: score assigned at rebalance_date,
    # carried forward until the next rebalance_date (TopkDropout trades at t+1 open).
    print("[3/5] Expanding to daily signal & backtest ...", flush=True)
    wide = pd.DataFrame({d: f.set_index("ts_code")["composite"] for d, f in snapshots.items()}).T  # index=rebalance_date
    wide = wide.reindex(calendar).ffill()
    long = wide.stack().rename("score").dropna().reset_index()
    long.columns = ["datetime", "ts_code", "score"]
    long["instrument"] = long["ts_code"].map(qlib_symbol)
    signal = long.set_index(["datetime", "instrument"])["score"].sort_index()

    # Daily IC of composite over the window.
    label_series = None  # computed below via D.features Ref expression
    label_df = D.features(
        D.instruments("all"),
        ["Ref($close,-2)/Ref($close,-1)-1"],
        start_time=BT_START,
        end_time=BT_END,
        freq="day",
    ).rename(columns={"Ref($close,-2)/Ref($close,-1)-1": "label"})
    label_series = label_df["label"].reorder_levels(["datetime", "instrument"]).sort_index()
    merged = pd.DataFrame({"score": signal, "label": label_series.reindex(signal.index)}).dropna()
    daily_ic = merged.groupby(level="datetime").apply(
        lambda x: pd.Series({"rank_ic": x["score"].corr(x["label"], method="spearman"), "count": len(x)})
    )
    daily_ic = daily_ic[daily_ic["count"] >= 50]
    daily_ic.to_csv(out / "daily_ic.csv.gz", compression="gzip")
    print(f"      composite daily RankIC mean={daily_ic['rank_ic'].mean():.4f} icir="
          f"{daily_ic['rank_ic'].mean()/daily_ic['rank_ic'].std():.3f} days={len(daily_ic)}", flush=True)

    print("[4/5] Backtest ...", flush=True)
    bt_rows = []
    for scenario, costs in COST_SCENARIOS.items():
        strategy = TopkDropoutStrategy(signal=signal, topk=TOP_K, n_drop=TOP_K)
        report, _ = backtest_daily(
            start_time=BT_START, end_time=BT_END, strategy=strategy,
            account=ACCOUNT, benchmark=BENCHMARK,
            exchange_kwargs={
                "limit_threshold": 0.095, "deal_price": "open",
                "open_cost": costs["open_cost"], "close_cost": costs["close_cost"],
                "min_cost": 5,
            },
        )
        bench_ann = float(risk_analysis(report["bench"], freq="day")["risk"]["annualized_return"])
        for stage, (s0, s1) in STAGES.items():
            sample = report.loc[s0:s1]
            if sample.empty:
                continue
            gross = risk_analysis(sample["return"] - sample["bench"], freq="day")["risk"]
            net = risk_analysis(sample["return"] - sample["bench"] - sample["cost"], freq="day")["risk"]
            bt_rows.append({
                "stage": stage, "cost_scenario": scenario,
                "start": str(sample.index.min().date()), "end": str(sample.index.max().date()),
                "trading_days": int(len(sample)),
                "gross_excess_annualized_return": float(gross["annualized_return"]),
                "gross_excess_ir": float(gross["information_ratio"]),
                "net_excess_annualized_return": float(net["annualized_return"]),
                "net_excess_ir": float(net["information_ratio"]),
                "net_excess_max_drawdown": float(net["max_drawdown"]),
                "average_daily_turnover_rate": float(sample["turnover"].mean()),
                "annualized_cost_drag": float(sample["cost"].mean() * ANNUALIZATION_DAYS),
                "benchmark_annualized_return": bench_ann,
            })
        full = report.loc[BT_START:BT_END]
        gross = risk_analysis(full["return"] - full["bench"], freq="day")["risk"]
        net = risk_analysis(full["return"] - full["bench"] - full["cost"], freq="day")["risk"]
        bt_rows.append({
            "stage": "full", "cost_scenario": scenario,
            "start": str(full.index.min().date()), "end": str(full.index.max().date()),
            "trading_days": int(len(full)),
            "gross_excess_annualized_return": float(gross["annualized_return"]),
            "gross_excess_ir": float(gross["information_ratio"]),
            "net_excess_annualized_return": float(net["annualized_return"]),
            "net_excess_ir": float(net["information_ratio"]),
            "net_excess_max_drawdown": float(net["max_drawdown"]),
            "average_daily_turnover_rate": float(full["turnover"].mean()),
            "annualized_cost_drag": float(full["cost"].mean() * ANNUALIZATION_DAYS),
            "benchmark_annualized_return": bench_ann,
        })
        print(f"      [{scenario}] full net excess={bt_rows[-1]['net_excess_annualized_return']:.4f} "
              f"IR={bt_rows[-1]['net_excess_ir']:.3f}", flush=True)

    bt = pd.DataFrame(bt_rows)
    bt.to_csv(out / "backtest_summary.csv", index=False)

    print("[5/5] Writing report & metadata ...", flush=True)
    stress_full = bt[(bt["stage"].eq("full")) & (bt["cost_scenario"].eq("stress"))].iloc[0]
    base_full = bt[(bt["stage"].eq("full")) & (bt["cost_scenario"].eq("base"))].iloc[0]
    if stress_full["net_excess_annualized_return"] > 0 and stress_full["net_excess_ir"] > 0:
        decision = "net_positive_stress"
    elif base_full["net_excess_annualized_return"] > 0:
        decision = "net_positive_base_only"
    else:
        decision = "not_net_positive"

    yearly_rows = []
    report_full = None
    strategy = TopkDropoutStrategy(signal=signal, topk=TOP_K, n_drop=TOP_K)
    report_full, _ = backtest_daily(
        start_time=BT_START, end_time=BT_END, strategy=strategy, account=ACCOUNT, benchmark=BENCHMARK,
        exchange_kwargs={"limit_threshold": 0.095, "deal_price": "open",
                         "open_cost": COST_SCENARIOS["base"]["open_cost"],
                         "close_cost": COST_SCENARIOS["base"]["close_cost"], "min_cost": 5},
    )
    for year, sample in report_full.loc[BT_START:BT_END].groupby(report_full.loc[BT_START:BT_END].index.year):
        if len(sample) < 50:
            continue
        net = risk_analysis(sample["return"] - sample["bench"] - sample["cost"], freq="day")["risk"]
        yearly_rows.append({
            "year": int(year), "trading_days": int(len(sample)),
            "net_excess_annualized_return": float(net["annualized_return"]),
            "net_excess_ir": float(net["information_ratio"]),
        })
    yearly = pd.DataFrame(yearly_rows)
    yearly.to_csv(out / "yearly_summary.csv", index=False)

    decision_json = {
        "decision": decision,
        "full_stress_net_excess_annualized_return": float(stress_full["net_excess_annualized_return"]),
        "full_stress_ir": float(stress_full["net_excess_ir"]),
        "full_base_net_excess_annualized_return": float(base_full["net_excess_annualized_return"]),
        "full_base_ir": float(base_full["net_excess_ir"]),
        "composite_daily_rank_ic_mean": float(daily_ic["rank_ic"].mean()),
        "composite_daily_rank_icir": float(daily_ic["rank_ic"].mean() / daily_ic["rank_ic"].std()),
    }
    (out / "decision.json").write_text(json.dumps(decision_json, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    methodology = {
        "protocol": "research/protocols/a_share_value_quality_monthly_strategy_protocol_v1.md",
        "composite": "equal-weight percentile-rank average of ep, bm, div_yield, accruals",
        "liquidity_floor": f"exclude bottom {LIQ_QUANTILE:.0%} by prior-20d avg amount",
        "topk": TOP_K,
        "rebalance": "monthly at rebalance_date, signal forward-filled",
        "execution": "TopkDropout trades at t+1 open; limit_threshold 0.095; min_cost 5",
        "st_filer": "not applied (data gap), disclosed",
        "benchmark": BENCHMARK,
        "backtest_window": [str(BT_START.date()), str(BT_END.date())],
        "cost_scenarios": COST_SCENARIOS,
    }
    (out / "methodology.json").write_text(json.dumps(methodology, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    lines = [
        "沪深非金融 A 股价值/质量多因子月度策略回测 v1",
        "=" * 64,
        "组合信号：ep/bm/div_yield/accruals 四因子等权百分位秩平均（月度）",
        f"股票池：非金融 A 股；流动性过滤剔除前20日均额最低20%；topk={TOP_K} 月度换手",
        f"执行：t+1 开盘价成交，涨跌停 9.5%，基准 {BENCHMARK}；ST 过滤缺失（已知偏差）",
        f"组合信号日频 RankIC 均值={daily_ic['rank_ic'].mean():.4f} ICIR="
        f"{daily_ic['rank_ic'].mean()/daily_ic['rank_ic'].std():.3f}",
        "",
        "回测（费后均为相对 SH000852 超额）：",
        bt.pivot_table(index="stage", columns="cost_scenario",
                       values=["net_excess_annualized_return", "net_excess_ir", "net_excess_max_drawdown"])
          .to_string(),
        "",
        "分年（基准成本费后）：",
        yearly.to_string(index=False),
        "",
        f"判定：{decision}",
        "结论边界：ST 过滤缺失与 1 日成交滞后是已知偏差；本结果只反映当前数据/成本假设下的可交易性。",
    ]
    (out / "strategy_report.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("\n".join(lines))


if __name__ == "__main__":
    main()
