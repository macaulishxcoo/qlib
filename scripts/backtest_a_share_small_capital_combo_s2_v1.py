#!/usr/bin/env python3
"""S2：小资金集中持仓组合回测 v1（质量复合 + 两融/趋势风控）。

协议：research/protocols/a_share_small_capital_combo_s2_protocol_v1.md

设计
----
- 信号：质量复合（ep/bm/accruals 等权秩平均，日频市值 asof）
- 过滤：ST/*ST/退市 + 停牌/涨停 + 两融拥挤（rzye_zscore>2）+ 流动性后 20%
- 版本：主版 top15；对照 = 主版 + 趋势状态过滤（TS_UP60=0 剔除）
- 调仓：月末最后交易日选股，T+1 开盘成交，TopkDropout topk=15 n_drop=15（月末全换）
- 基准 SH000852，两套成本（base/stress），窗口 2022-01-01~2026-07-31

输出（拒绝覆盖非空目录）
------------------------
output/analysis_static/a_share_small_capital_combo_s2/
"""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

import qlib
from qlib.config import REG_CN
from qlib.contrib.evaluate import backtest_daily, risk_analysis
from qlib.contrib.strategy import TopkDropoutStrategy
from qlib.data import D

from analyze_a_share_daily_valuation_s1_v1 import (
    build_quality_slow_factors, load_daily_basic, load_margin, ts_to_qlib,
)
from analyze_a_share_trend_persistence_v1 import build_universe, is_gem

QLIB_DIR = Path("~/.qlib/qlib_data/cn_data_2026").expanduser()
ST_INTERVALS = Path("data/external/tushare/a_share_st_status_pit_v1/normalized/st_status_intervals.csv.gz")

LOAD_START = "2020-07-01"
BT_START = "2022-01-01"
# BT_END 截断到 2026-07-23：SH000852 基准数据在 2026-07-24 复权断层
# （stage-1 增量更新将指数写成原始点位，close 7.27→6995，单日 +96100%），
# 污染基准序列；截断到损坏前一天，数据管道修复后再延长。
BT_END = "2026-07-23"
TOP_K = 15
ACCOUNT = 1_000_000
BENCHMARK = "SH000852"
ANNUALIZATION_DAYS = 238
MARGIN_THRESH = 2.0
LIQUIDITY_TAIL = 0.20
LIMIT_MAIN, LIMIT_GEM = 0.095, 0.195
COST_SCENARIOS = {
    "base": {"open_cost": 0.0005, "close_cost": 0.0015},
    "stress": {"open_cost": 0.0010, "close_cost": 0.0030},
}


def qlib_symbol(code: str) -> str:
    return f"{code[2:]}.{code[:2]}"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--output-dir", type=Path,
                        default=Path("output/analysis_static/a_share_small_capital_combo_s2"))
    args = parser.parse_args()
    out = args.output_dir
    if out.exists() and any(out.iterdir()):
        raise FileExistsError(f"Refusing to overwrite existing experiment output: {out}")
    out.mkdir(parents=True, exist_ok=True)

    qlib.init(provider_uri=str(QLIB_DIR), region=REG_CN)
    calendar = pd.DatetimeIndex(pd.to_datetime(pd.read_csv(QLIB_DIR / "calendars" / "day.txt", header=None)[0]))
    cal_win = calendar[(calendar >= pd.Timestamp(BT_START)) & (calendar <= pd.Timestamp(BT_END))]

    # ---- 1. 母池行情 + TS_UP60 ----
    print("[1/6] Universe + market panel ...", flush=True)
    codes, excluded = build_universe()
    mkt = D.features(codes, ["$close", "$open", "$change", "$volume"],
                     start_time=LOAD_START, end_time=BT_END, freq="day")
    mkt.columns = ["$close", "$open", "$change", "$volume"]
    mkt = mkt.reset_index().set_index(["datetime", "instrument"]).sort_index()
    g = mkt.groupby(level="instrument")
    mkt["TS_UP60"] = ((mkt["$close"] / g["$close"].shift(60) - 1) > 0).astype(float)
    print(f"      rows={len(mkt)}, instruments={mkt.index.get_level_values('instrument').nunique()}", flush=True)

    # ---- 2. daily_basic + 质量慢因子 ----
    print("[2/6] daily_basic + quality slow factors ...", flush=True)
    db = load_daily_basic()
    mkt2 = mkt.reset_index().merge(
        db[["instrument", "trade_date", "total_mv", "total_share"]],
        left_on=["instrument", "datetime"], right_on=["instrument", "trade_date"], how="left",
    ).set_index(["datetime", "instrument"]).sort_index()

    slow = build_quality_slow_factors().rename(columns={"available_date": "datetime"})
    slow = slow.drop_duplicates(["instrument", "datetime"], keep="last").sort_values("datetime")
    q = pd.merge_asof(
        mkt2.reset_index().sort_values("datetime"), slow,
        on="datetime", by="instrument", direction="backward",
    ).set_index(["datetime", "instrument"]).sort_index()
    q["ep"] = q["profit_dedt_ttm"] / (q["total_mv"] * 1e4)
    q["bm"] = q["bps"] * q["total_share"] / q["total_mv"]
    q["accruals"] = -q["ni_minus_cfo_ttm"] / q["total_assets"]
    q.loc[q["ep"] <= 0, "ep"] = np.nan
    q.loc[q["bps"] <= 0, "bm"] = np.nan
    q.loc[q["ni_minus_cfo_ttm"] <= 0, "accruals"] = np.nan

    # 质量分 = 三因子横截面百分位秩均值
    for col in ["ep", "bm", "accruals"]:
        q[f"r_{col}"] = q.groupby(level="datetime")[col].rank(pct=True)
    q["quality"] = (q["r_ep"] + q["r_bm"] + q["r_accruals"]) / 3
    print(f"      quality coverage={q['quality'].notna().mean():.1%}", flush=True)

    # ---- 3. 两融 zscore + 流动性 ----
    print("[3/6] margin zscore + liquidity ...", flush=True)
    mg = load_margin()
    mg = mg.sort_values(["instrument", "trade_date"])
    mg["rzye_zscore"] = mg.groupby("instrument")["rzye"].transform(
        lambda s: (s - s.rolling(250, min_periods=120).mean()) / (s.rolling(250, min_periods=120).std() + 1e-12)
    )
    df = q.reset_index().merge(
        mg[["instrument", "trade_date", "rzye_zscore"]],
        left_on=["instrument", "datetime"], right_on=["instrument", "trade_date"], how="left",
    ).set_index(["datetime", "instrument"]).sort_index()

    # 流动性：20 日均成交额
    df["amount20"] = df.groupby(level="instrument")["$volume"].transform(lambda s: s.rolling(20).mean())
    df["liq_pct"] = df.groupby(level="datetime")["amount20"].rank(pct=True)
    print(f"      rows={len(df)}, margin coverage={df['rzye_zscore'].notna().mean():.1%}", flush=True)

    # ---- 4. ST 区间 + 月末调仓网格 ----
    print("[4/6] Filters + month-end grid ...", flush=True)
    st = pd.read_csv(ST_INTERVALS, compression="gzip", parse_dates=["start_date", "end_date"])
    st_active = st.loc[st["is_st"] | st["is_delist_phase"], ["ts_code", "start_date", "end_date"]]
    st_by_date: dict[pd.Timestamp, set[str]] = {}
    dates = df.index.get_level_values("datetime").unique()
    for d in dates:
        active = st_active[(st_active["start_date"] <= d) & (st_active["end_date"] >= d)]
        st_by_date[d] = set(active["ts_code"])

    # 月末调仓日（每月最后交易日）
    month_end = cal_win.to_series().groupby(cal_win.to_period("M")).max()

    # 过滤标记（逐日）
    keep = df["$close"].notna() & df["$volume"].notna() & (df["$volume"] > 0)
    gem = df.index.get_level_values("instrument").map(is_gem)
    keep &= ~(df["$change"] >= np.where(gem, LIMIT_GEM, LIMIT_MAIN))
    ts_code_s = df.index.get_level_values("instrument").map(qlib_symbol)
    keep &= ~pd.Series(
        [c in st_by_date.get(d, set()) for d, c in zip(df.index.get_level_values("datetime"), ts_code_s)],
        index=df.index,
    )
    keep &= df["liq_pct"].isna() | (df["liq_pct"] >= LIQUIDITY_TAIL)
    df["keep_flags"] = keep

    # ---- 5. 两个版本信号 ----
    print("[5/6] Building signals (main / control) ...", flush=True)
    df["score"] = df["quality"]
    df["score_margin_filtered"] = df["quality"].where(
        df["rzye_zscore"].isna() | (df["rzye_zscore"] <= MARGIN_THRESH)
    )
    df["score_control"] = df["score_margin_filtered"].where(df["TS_UP60"].eq(1))

    signals: dict[str, pd.Series] = {}
    for version, col in [("main", "score_margin_filtered"), ("control", "score_control")]:
        month_scores = df[df.index.get_level_values("datetime").isin(month_end)].copy()
        month_scores = month_scores[month_scores["keep_flags"]][col].dropna()
        wide = month_scores.unstack(level="instrument").reindex(month_end)
        wide = wide.reindex(cal_win).ffill()
        long = wide.stack().rename("score").dropna().reset_index()
        long.columns = ["datetime", "instrument", "score"]
        signals[version] = long.set_index(["datetime", "instrument"])["score"].sort_index()
        print(f"      {version}: signal rows={len(signals[version])}, "
              f"months={month_scores.groupby(level='datetime').size().shape[0]}", flush=True)

    # ---- 6. 回测 ----
    print("[6/6] Backtest ...", flush=True)
    all_rows = []
    yearly = {}
    for version, signal in signals.items():
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
            full = report.loc[BT_START:BT_END]
            gross = risk_analysis(full["return"] - full["bench"], freq="day")["risk"]
            net = risk_analysis(full["return"] - full["bench"] - full["cost"], freq="day")["risk"]
            stress = report.loc["2025-07-01":]
            stress_net = risk_analysis(stress["return"] - stress["bench"] - stress["cost"], freq="day")["risk"] if len(stress) > 20 else {}
            all_rows.append({
                "version": version, "cost_scenario": scenario,
                "gross_excess_annualized_return": float(gross["annualized_return"]),
                "gross_excess_ir": float(gross["information_ratio"]),
                "net_excess_annualized_return": float(net["annualized_return"]),
                "net_excess_ir": float(net["information_ratio"]),
                "net_excess_max_drawdown": float(net["max_drawdown"]),
                "average_daily_turnover_rate": float(full["turnover"].mean()),
                "annualized_cost_drag": float(full["cost"].mean() * ANNUALIZATION_DAYS),
                "stress_net_excess": float(stress_net.get("annualized_return", np.nan)),
            })
            if scenario == "base":
                for year, sample in full.groupby(full.index.year):
                    if len(sample) < 50:
                        continue
                    ynet = risk_analysis(sample["return"] - sample["bench"] - sample["cost"], freq="day")["risk"]
                    yearly.setdefault(version, []).append({
                        "year": int(year), "net_excess_annualized_return": float(ynet["annualized_return"]),
                        "net_excess_ir": float(ynet["information_ratio"]),
                    })
            print(f"      [{version}/{scenario}] net={all_rows[-1]['net_excess_annualized_return']:+.4f} "
                  f"IR={all_rows[-1]['net_excess_ir']:.3f}", flush=True)

    bt = pd.DataFrame(all_rows)
    bt.to_csv(out / "backtest_summary.csv", index=False)
    for version, rows in yearly.items():
        pd.DataFrame(rows).to_csv(out / f"yearly_summary_{version}.csv", index=False)

    # ---- 判定 + 报告 ----
    main_stress = bt[(bt["version"].eq("main")) & (bt["cost_scenario"].eq("stress"))].iloc[0]
    main_base = bt[(bt["version"].eq("main")) & (bt["cost_scenario"].eq("base"))].iloc[0]
    ctrl_stress = bt[(bt["version"].eq("control")) & (bt["cost_scenario"].eq("stress"))].iloc[0]
    if main_stress["net_excess_annualized_return"] > 0 and main_stress["net_excess_ir"] > 0:
        decision = "viable"
    elif main_base["net_excess_annualized_return"] > 0:
        decision = "base_only"
    else:
        decision = "not_viable"
    trend_improve = ctrl_stress["net_excess_annualized_return"] > main_stress["net_excess_annualized_return"]

    lines = []
    lines.append("# S2 小资金集中持仓组合回测报告 v1\n")
    lines.append(f"- 信号: 质量复合(ep/bm/accruals) top{TOP_K} 月末调仓，T+1 开盘成交")
    lines.append(f"- 过滤: ST/退市 + 停牌/涨停 + 两融拥挤(z>{MARGIN_THRESH}) + 流动性后20%")
    lines.append(f"- 对照: + 趋势状态过滤(TS_UP60=1)")
    lines.append(f"- 窗口: {BT_START} ~ {BT_END}，基准 {BENCHMARK}，账户 {ACCOUNT}\n")
    lines.append(f"## 判定：**{decision}**（趋势过滤提升: {'是' if trend_improve else '否'}）\n")

    lines.append("### 主版/对照 回测（全期）")
    lines.append("| 版本 | 成本 | 费后超额(年化) | IR | 最大回撤 | 日换手 | 成本损耗 | 2025-07后 |")
    lines.append("|---|---|---|---|---|---|---|---|")
    for _, r in bt.iterrows():
        lines.append(f"| {r['version']} | {r['cost_scenario']} | {r['net_excess_annualized_return']:+.2%} | "
                     f"{r['net_excess_ir']:.2f} | {r['net_excess_max_drawdown']:.1%} | "
                     f"{r['average_daily_turnover_rate']:.3f} | {r['annualized_cost_drag']:.2%} | "
                     f"{r['stress_net_excess']:+.2%} |")

    lines.append("\n### 分年度费后超额（base）")
    for version, rows in yearly.items():
        lines.append(f"- {version}: " + " ".join(f"{r['year']}:{r['net_excess_annualized_return']:+.2%}" for r in rows))

    lines.append("\n### 判定口径")
    lines.append("- viable: 主版 stress 费后超额>0 且 IR>0 → 实盘准备候选")
    lines.append("- base_only: base 正但 stress 非正 → 成本敏感性")
    lines.append("- not_viable: base 也非正 → 组件组装不成立")
    (out / "backtest_report.txt").write_text("\n".join(lines), encoding="utf-8")

    meta = {
        "purpose": "S2 小资金集中持仓组合回测",
        "protocol": "research/protocols/a_share_small_capital_combo_s2_protocol_v1.md",
        "universe": f"沪深普通 A 股 {len(codes)} 只",
        "topk": TOP_K, "n_drop": TOP_K, "account": ACCOUNT, "benchmark": BENCHMARK,
        "window": [BT_START, BT_END],
        "decision": decision,
        "trend_filter_improved": bool(trend_improve),
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
    }
    (out / "methodology.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    (out / "decision.json").write_text(json.dumps({"decision": decision, "trend_filter_improved": bool(trend_improve)}, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"      report -> {out / 'backtest_report.txt'}", flush=True)
    print(f"      decision = {decision}", flush=True)
    print("DONE", flush=True)


if __name__ == "__main__":
    main()
