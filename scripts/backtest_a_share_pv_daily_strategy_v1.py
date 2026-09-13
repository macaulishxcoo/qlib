#!/usr/bin/env python3
"""纯量价日频策略回测 v1。

协议：research/protocols/a_share_pv_daily_strategy_protocol_v1.md

研究问题
--------
换手率水平（TURNOVER_LEVEL5）+ 收益偏度（SKEW60）的 MVI 残差合成信号，在真实
日频调仓（TopkDropout topk=50 n_drop=5）+ 扣成本后，是否能产生正超额（相对
SH000852）？验证"纯量价日频是否值得继续投入"，是组合版（基本面域+量价快信号）
的前置。

口径
----
- 主池：沪深普通 A 股母池（all.txt 历史在市，剔除 BJ/指数/B 股）
- 数据：cn_data_2026（后复权）+ daily_basic_pit_v1（换手率/市值）+ style_pit_v1（行业）
- 信号：逐日 MVI 残差（log circ_mv + std20 + 申万 L1）；合成 = 0.5*rank_pct(TURN) + 0.5*rank_pct(SKEW)
- 过滤：ST/*ST/退市（PIT）+ 停牌 + 涨停信号日
- 回测：TopkDropout topk=50 n_drop=5，deal_price=open，SH000852，base/stress 两套费率
- 窗口：2022-01-01 ~ 2026-07-31（预热自 2020-01-01）

输出（拒绝覆盖非空目录）
------------------------
output/analysis_static/a_share_pv_daily_strategy_v1/
  backtest_summary.csv       版本×费率 全期指标
  yearly_summary_main.csv    主版本分年度 net 超额（base）
  daily_report_main_base.csv.gz  主版本 base 日度 report
  decision.json              预设判定
  methodology.json           口径快照
  validation_report.txt      中文报告
"""

from __future__ import annotations

import argparse
import importlib.util
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

ROOT = Path(__file__).resolve().parents[1]


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


neut = load_module("neut", ROOT / "scripts/analyze_a_share_price_volume_factor_neutralization_v1.py")

QLIB_DIR = neut.QLIB_DIR
DATA_START = neut.DATA_START
BT_START = "2022-01-01"
BT_END = "2026-07-31"
TOP_K = 50
N_DROP = 5
ACCOUNT = 1_000_000
BENCHMARK = "SH000852"
ANNUALIZATION_DAYS = 238
COST_SCENARIOS = {
    "base": {"open_cost": 0.0005, "close_cost": 0.0015},
    "stress": {"open_cost": 0.0010, "close_cost": 0.0030},
}
FACTORS = ["TURNOVER_LEVEL5", "SKEW60"]

ICIR_ALIVE = 0.5   # net IR 门槛（协议 §5）
WEAK_IR = 0.0


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--output-dir", type=Path,
                        default=Path("output/analysis_static/a_share_pv_daily_strategy_v1"))
    args = parser.parse_args()
    out = args.output_dir
    if out.exists() and any(out.iterdir()):
        raise FileExistsError(f"Refusing to overwrite existing experiment output: {out}")
    out.mkdir(parents=True, exist_ok=True)

    qlib.init(provider_uri=str(QLIB_DIR), region=REG_CN)

    # ---- 1. 母池行情 + 因子 ----
    print("[1/5] Building SH/SZ ordinary A-share universe + factors ...", flush=True)
    codes, excluded = neut.build_universe()
    mkt = neut.load_market(codes)
    mask = neut.build_filter_mask(mkt)
    print(f"      rows={len(mkt)}, instruments={mkt.index.get_level_values('instrument').nunique()}, "
          f"keep={mask.mean():.1%}", flush=True)
    eval_all = mkt.loc[pd.Timestamp(BT_START): pd.Timestamp(BT_END)]
    mask_full = pd.Series(mask, index=mkt.index)
    eval_keep = eval_all.loc[mask_full.loc[eval_all.index].to_numpy()]

    # ---- 2. 逐日 MVI 残差 → 信号 ----
    print("[2/5] Computing daily MVI residuals + signals (main/turn/skew) ...", flush=True)
    sig_rows = []
    dates = eval_keep.index.get_level_values("datetime").unique()
    for d in dates:
        g = eval_keep.loc[d]
        if len(g) < 300:
            continue
        resid = {}
        for f in FACTORS:
            resid[f] = pd.Series(neut.neutralize_day(g, f, "MVI"), index=g.index)
        z_turn = resid["TURNOVER_LEVEL5"].rank(pct=True)
        z_skew = resid["SKEW60"].rank(pct=True)
        score_main = 0.5 * z_turn + 0.5 * z_skew
        for inst in g.index:
            sig_rows.append((d, inst, score_main.loc[inst],
                             resid["TURNOVER_LEVEL5"].loc[inst], resid["SKEW60"].loc[inst]))
    sig_df = pd.DataFrame(sig_rows, columns=["datetime", "instrument", "score_main", "score_turn", "score_skew"])
    sig_df = sig_df.set_index(["datetime", "instrument"]).sort_index()
    signals = {
        "main": sig_df["score_main"],
        "turnonly": sig_df["score_turn"],
        "skewonly": sig_df["score_skew"],
    }
    print(f"      signal days={sig_df.index.get_level_values('datetime').nunique()}, "
          f"rows={len(sig_df)}", flush=True)

    # ---- 3. 回测 ----
    print("[3/5] Running backtests (3 versions × 2 cost scenarios) ...", flush=True)
    all_rows = []
    yearly = {}
    for version, signal in signals.items():
        for scenario, costs in COST_SCENARIOS.items():
            strategy = TopkDropoutStrategy(signal=signal, topk=TOP_K, n_drop=N_DROP)
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
            recent = report.loc["2025-07-01":]
            recent_net = risk_analysis(
                recent["return"] - recent["bench"] - recent["cost"], freq="day")["risk"] if len(recent) > 20 else {}
            all_rows.append({
                "version": version, "cost_scenario": scenario,
                "gross_excess_annualized_return": float(gross["annualized_return"]),
                "gross_excess_ir": float(gross["information_ratio"]),
                "net_excess_annualized_return": float(net["annualized_return"]),
                "net_excess_ir": float(net["information_ratio"]),
                "net_excess_max_drawdown": float(net["max_drawdown"]),
                "average_daily_turnover_rate": float(full["turnover"].mean()),
                "annualized_cost_drag": float(full["cost"].mean() * ANNUALIZATION_DAYS),
                "recent_2025H2_net_excess": float(recent_net.get("annualized_return", np.nan)),
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

    # 主版本 base 日度 report（存档）
    print("[4/5] Saving daily report (main/base) ...", flush=True)
    strategy = TopkDropoutStrategy(signal=signals["main"], topk=TOP_K, n_drop=N_DROP)
    report_main, _ = backtest_daily(
        start_time=BT_START, end_time=BT_END, strategy=strategy,
        account=ACCOUNT, benchmark=BENCHMARK,
        exchange_kwargs={"limit_threshold": 0.095, "deal_price": "open",
                         "open_cost": COST_SCENARIOS["base"]["open_cost"],
                         "close_cost": COST_SCENARIOS["base"]["close_cost"], "min_cost": 5},
    )
    report_main.loc[BT_START:BT_END].to_csv(out / "daily_report_main_base.csv.gz", compression="gzip")

    # ---- 判定 ----
    print("[5/5] Decision + report ...", flush=True)
    m_base = bt[(bt["version"] == "main") & (bt["cost_scenario"] == "base")].iloc[0]
    if m_base["net_excess_annualized_return"] > 0 and m_base["net_excess_ir"] >= ICIR_ALIVE:
        decision = "viable"
    elif m_base["net_excess_annualized_return"] > 0 and m_base["net_excess_ir"] > WEAK_IR:
        decision = "weak"
    else:
        decision = "dead"
    (out / "decision.json").write_text(json.dumps({"main_base": decision}, ensure_ascii=False, indent=2) + "\n",
                                      encoding="utf-8")

    lines = []
    lines.append(f"# 纯量价日频策略回测报告 v1\n")
    lines.append(f"- 主池: 沪深普通 A 股 {len(codes)} 只（剔除 BJ/指数/B 股 {len(excluded)} 只）")
    lines.append(f"- 数据: {QLIB_DIR}（后复权）+ daily_basic_pit_v1 + style_pit_v1")
    lines.append(f"- 信号: TURNOVER_LEVEL5 + SKEW60 的 MVI 残差；合成 = 0.5·rank(TURN)+0.5·rank(SKEW)")
    lines.append(f"- 回测: TopkDropout topk={TOP_K} n_drop={N_DROP}，T+1 开盘成交，基准 {BENCHMARK}")
    lines.append(f"- 窗口: {BT_START} ~ {BT_END}（预热自 {DATA_START}），过滤保留率 {mask.mean():.1%}")
    lines.append(f"- 费率: base {COST_SCENARIOS['base']}，stress {COST_SCENARIOS['stress']}\n")

    lines.append(f"## 判定：**{decision}**\n")

    lines.append("### 回测汇总（全期）")
    lines.append("| 版本 | 费率 | gross超额年化 | gross IR | net超额年化 | net IR | net最大回撤 | 日均换手 | 年化成本拖累 | 2025H2 net |")
    lines.append("|---|---|---|---|---|---|---|---|---|---|")
    for _, r in bt.iterrows():
        lines.append(f"| {r['version']} | {r['cost_scenario']} | {r['gross_excess_annualized_return']:+.3f} | "
                     f"{r['gross_excess_ir']:.2f} | {r['net_excess_annualized_return']:+.3f} | "
                     f"{r['net_excess_ir']:.2f} | {r['net_excess_max_drawdown']:.2%} | "
                     f"{r['average_daily_turnover_rate']:.2%} | {r['annualized_cost_drag']:.2%} | "
                     f"{r['recent_2025H2_net_excess']:+.3f} |")

    lines.append("\n### 分年度 net 超额（base，各版本）")
    for version, rows in yearly.items():
        lines.append(f"\n**{version}**")
        lines.append("| 年份 | net超额年化 | net IR |")
        lines.append("|---|---|---|")
        for r in rows:
            lines.append(f"| {r['year']} | {r['net_excess_annualized_return']:+.3f} | {r['net_excess_ir']:.2f} |")

    lines.append("\n### 判定解读（协议 §5）")
    lines.append(f"- viable: net超额>0 且 net IR≥{ICIR_ALIVE} → 值得进组合版（另行立项）")
    lines.append("- weak: net超额>0 但 IR 不足 → 需组合/择时增强")
    lines.append("- dead: net超额≤0 → 纯量价日频收口")
    (out / "validation_report.txt").write_text("\n".join(lines), encoding="utf-8")

    meta = {
        "purpose": "纯量价日频策略（换手率水平+偏度 MVI 信号）真实调仓扣成本验证",
        "protocol": "research/protocols/a_share_pv_daily_strategy_protocol_v1.md",
        "universe": f"沪深普通 A 股 {len(codes)} 只（剔除 {len(excluded)} 只）",
        "data_dir": str(QLIB_DIR),
        "bt_window": [BT_START, BT_END],
        "data_warmup_from": DATA_START,
        "signal": "0.5*rank_pct(TURNOVER_LEVEL5_MVI) + 0.5*rank_pct(SKEW60_MVI)",
        "strategy": f"TopkDropout topk={TOP_K} n_drop={N_DROP}",
        "benchmark": BENCHMARK,
        "cost_scenarios": COST_SCENARIOS,
        "filters": "ST/*ST/退市整理(PIT) + 停牌 + 涨停信号日",
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
    }
    (out / "methodology.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"      report -> {out / 'validation_report.txt'}", flush=True)
    print(f"      decision = {decision}", flush=True)
    print("DONE", flush=True)


if __name__ == "__main__":
    main()
