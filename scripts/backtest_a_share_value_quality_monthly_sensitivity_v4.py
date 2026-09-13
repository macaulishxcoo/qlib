#!/usr/bin/env python3
"""Slippage & capacity sensitivity grid for the neutralized+ST-filtered strategy (v4).

Runs a 4(slippage) x 3(participation) grid over the V3 pipeline (V1 panel +
ST/退市整理 filter + industry/size neutralization), reporting full-period and
holdout net-excess returns under stress costs plus one-sided slippage, and a
per-stock capacity (participation) cap.

Protocol: research/protocols/a_share_value_quality_monthly_strategy_protocol_v4.md
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

from analyze_a_share_value_quality_level_factors_extension_v1 import ols_residual, QLIB_DIR, STYLE_DIR

TOP_K = 50
ACCOUNT = 100_000_000
NOTIONAL = ACCOUNT / TOP_K
BENCHMARK = "SH000852"
BT_START = pd.Timestamp("2014-01-01")
BT_END = pd.Timestamp("2025-06-30")
ANNUALIZATION_DAYS = 238
STRESS_COST = {"open_cost": 0.0010, "close_cost": 0.0030}
SLIPPAGE_LEVELS = (0.000, 0.001, 0.003, 0.005)
PARTICIPATION_LEVELS = (1.00, 0.10, 0.05)
STAGES = {
    "development": (pd.Timestamp("2014-01-01"), pd.Timestamp("2019-12-31")),
    "confirmation": (pd.Timestamp("2020-01-01"), pd.Timestamp("2022-12-31")),
    "holdout": (pd.Timestamp("2023-01-01"), pd.Timestamp("2025-06-30")),
}
ST_INTERVALS = Path("data/external/tushare/a_share_st_status_pit_v1/normalized/st_status_intervals.csv.gz")
V1_PANEL_DEFAULT = Path("output/analysis_fundamental/a_share_value_quality_monthly_strategy_v1/monthly_composite_signal.csv.gz")


def qlib_symbol(code: str) -> str:
    number, suffix = code.split(".")
    return f"{suffix}{number}"


def load_amount_avg(codes: list[str], calendar: pd.DatetimeIndex) -> pd.DataFrame:
    """Prior-20-trading-day average dollar amount per code, indexed by asof date."""
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


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, default=Path("output/analysis_fundamental/a_share_value_quality_monthly_strategy_v4_sensitivity"))
    parser.add_argument("--panel-path", type=Path, default=V1_PANEL_DEFAULT)
    args = parser.parse_args()
    out = args.output_dir
    if out.exists() and any(out.iterdir()):
        raise FileExistsError(f"Refusing to overwrite existing experiment output: {out}")
    out.mkdir(parents=True, exist_ok=True)

    qlib.init(provider_uri=str(QLIB_DIR), region=REG_CN)
    calendar = pd.DatetimeIndex(pd.to_datetime(pd.read_csv(QLIB_DIR / "calendars" / "day.txt", header=None)[0]))
    cal_win = calendar[(calendar >= BT_START) & (calendar <= BT_END)]

    print("[1/5] Loading panel, ST, grid, amount ...", flush=True)
    panel = pd.read_csv(args.panel_path, compression="gzip")
    panel["rebalance_date"] = pd.to_datetime(panel["rebalance_date"])
    st = pd.read_csv(ST_INTERVALS, compression="gzip", parse_dates=["start_date", "end_date"])
    grid = pd.read_csv(STYLE_DIR / "monthly_rebalance_grid.csv.gz", compression="gzip",
                       parse_dates=["rebalance_date", "asof_date"])
    asof_by_rebal = grid.set_index("rebalance_date")["asof_date"]
    all_codes = sorted(panel["ts_code"].unique())
    amount_avg = load_amount_avg(all_codes, calendar)
    print(f"      months={panel['rebalance_date'].nunique()} amount_avg={amount_avg.shape}", flush=True)

    print("[2/5] Precomputing ST & capacity exclusion per month ...", flush=True)
    st_codes_by_month = {}
    cap_codes_by_month = {}
    for date, frame in panel.groupby("rebalance_date"):
        asof = asof_by_rebal.get(date, pd.NaT)
        if pd.notna(asof):
            active = st[(st["start_date"] <= asof) & (st["end_date"] >= asof)]
            st_codes_by_month[date] = set(active.loc[active["is_st"] | active["is_delist_phase"], "ts_code"])
            # qlib $amount is in thousands of yuan (Tushare convention); convert to yuan.
            avg = amount_avg.loc[asof].reindex(frame["ts_code"]) * 1000.0
            cap_codes_by_month[date] = {}
            for participation in PARTICIPATION_LEVELS:
                if participation >= 1.0:
                    cap_codes_by_month[date][participation] = set()
                else:
                    min_amount = NOTIONAL / participation
                    cap_codes_by_month[date][participation] = set(avg[avg < min_amount].dropna().index)

    print("[3/5] Grid backtests ...", flush=True)
    rows = []
    for participation in PARTICIPATION_LEVELS:
        for slippage in SLIPPAGE_LEVELS:
            # Build filtered + neutralized signal for this cell.
            neutral_parts = []
            for date, frame in panel.groupby("rebalance_date"):
                f = frame.copy()
                f.loc[f["ts_code"].isin(st_codes_by_month.get(date, set())), "composite"] = np.nan
                f.loc[f["ts_code"].isin(cap_codes_by_month.get(date, {}).get(participation, set())), "composite"] = np.nan
                valid = f.dropna(subset=["composite", "log_size", "l1_code"])
                if len(valid) < 50:
                    f["neutral_composite"] = np.nan
                else:
                    resid = ols_residual(valid["composite"], valid["l1_code"], valid["log_size"])
                    f["neutral_composite"] = resid.reindex(f.index)
                f["rebalance_date"] = date
                neutral_parts.append(f[["rebalance_date", "ts_code", "neutral_composite"]])
            neutral = pd.concat(neutral_parts, ignore_index=True)
            wide = neutral.pivot_table(index="rebalance_date", columns="ts_code", values="neutral_composite")
            wide.index = pd.to_datetime(wide.index)
            wide = wide.reindex(cal_win).ffill()
            long = wide.stack().rename("score").dropna().reset_index()
            long.columns = ["datetime", "ts_code", "score"]
            long["instrument"] = long["ts_code"].map(qlib_symbol)
            signal = long.set_index(["datetime", "instrument"])["score"].sort_index()

            costs = {
                "open_cost": STRESS_COST["open_cost"] + slippage,
                "close_cost": STRESS_COST["close_cost"] + slippage,
            }
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
            full = report.loc[BT_START:BT_END]
            full_net = risk_analysis(full["return"] - full["bench"] - full["cost"], freq="day")["risk"]
            hol = report.loc["2023-01-01":"2025-06-30"]
            hol_net = risk_analysis(hol["return"] - hol["bench"] - hol["cost"], freq="day")["risk"]
            rows.append({
                "participation": participation, "slippage": slippage,
                "effective_open_cost": costs["open_cost"], "effective_close_cost": costs["close_cost"],
                "full_net_excess_annualized_return": float(full_net["annualized_return"]),
                "full_net_ir": float(full_net["information_ratio"]),
                "full_net_max_drawdown": float(full_net["max_drawdown"]),
                "holdout_net_excess_annualized_return": float(hol_net["annualized_return"]),
                "holdout_net_ir": float(hol_net["information_ratio"]),
                "holdout_net_max_drawdown": float(hol_net["max_drawdown"]),
                "average_daily_turnover_rate": float(full["turnover"].mean()),
                "annualized_cost_drag": float(full["cost"].mean() * ANNUALIZATION_DAYS),
            })
            print(f"      p={participation} sl={slippage} -> full={rows[-1]['full_net_excess_annualized_return']:.4f} "
                  f"hol={rows[-1]['holdout_net_excess_annualized_return']:.4f}", flush=True)

    sensitivity = pd.DataFrame(rows)
    sensitivity.to_csv(out / "sensitivity_summary.csv", index=False)

    print("[4/5] Persisting extreme cell (S3+P2) panel ...", flush=True)
    extreme = sensitivity[(sensitivity["slippage"].eq(0.005)) & (sensitivity["participation"].eq(0.05))].iloc[0]
    print(f"      extreme S3+P2: full={extreme['full_net_excess_annualized_return']:.4f} "
          f"IR={extreme['full_net_ir']:.3f} | hol={extreme['holdout_net_excess_annualized_return']:.4f} "
          f"IR={extreme['holdout_net_ir']:.3f}", flush=True)

    print("[5/5] Report & decision ...", flush=True)
    viable = bool(extreme["holdout_net_excess_annualized_return"] > 0 and extreme["holdout_net_ir"] > 0)
    decision = "viable_under_stress" if viable else "not_viable_under_stress"
    decision_json = {
        "decision": decision,
        "extreme_cell": {
            "participation": 0.05, "slippage": 0.005,
            "full_net_excess_annualized_return": float(extreme["full_net_excess_annualized_return"]),
            "full_net_ir": float(extreme["full_net_ir"]),
            "holdout_net_excess_annualized_return": float(extreme["holdout_net_excess_annualized_return"]),
            "holdout_net_ir": float(extreme["holdout_net_ir"]),
        },
    }
    (out / "decision.json").write_text(json.dumps(decision_json, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    methodology = {
        "protocol": "research/protocols/a_share_value_quality_monthly_strategy_protocol_v4.md",
        "signal": "V1 composite -> ST/退市过滤 -> capacity cap -> industry/size OLS residual",
        "cost_model": "stress (open 0.0010, close 0.0030) + one-sided slippage on both sides",
        "capacity": "single-stock notional ACCOUNT/topk = 200万; excluded if notional/avg_amount > participation",
        "topk": TOP_K,
        "benchmark": BENCHMARK,
        "backtest_window": [str(BT_START.date()), str(BT_END.date())],
    }
    (out / "methodology.json").write_text(json.dumps(methodology, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    piv_full = sensitivity.pivot_table(index="slippage", columns="participation", values="full_net_excess_annualized_return")
    piv_hol = sensitivity.pivot_table(index="slippage", columns="participation", values="holdout_net_excess_annualized_return")
    lines = [
        "价值/质量多因子月度策略滑点/容量敏感性 v4",
        "=" * 64,
        "成本 = 压力成本(买0.10%/卖0.30%) + 单边滑点；容量 = 单票200万 / 日均额 参与率上限",
        "",
        "全期费后年化超额（行=滑点，列=参与率上限）：",
        piv_full.round(4).to_string(),
        "",
        "封存期 2023-2025 费后年化超额：",
        piv_hol.round(4).to_string(),
        "",
        f"极端格 S3+P2（滑点0.5% + 参与率5%）：全期 {extreme['full_net_excess_annualized_return']*100:.2f}%/yr "
        f"IR={extreme['full_net_ir']:.3f} | 封存期 {extreme['holdout_net_excess_annualized_return']*100:.2f}%/yr "
        f"IR={extreme['holdout_net_ir']:.3f}",
        "",
        f"判定：{decision}",
        "结论边界：滑点与容量为参数化假设，真实冲击成本需实盘验证。",
    ]
    (out / "sensitivity_report.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("\n".join(lines))


if __name__ == "__main__":
    main()
