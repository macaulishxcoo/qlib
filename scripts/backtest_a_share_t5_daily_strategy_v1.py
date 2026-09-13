#!/usr/bin/env python3
"""T5 跌幅上榜事件日频策略回测 v1（协议 v1，候选形态 A：超跌组反转）。

提案：research/decisions/a_share_t5_daily_strategy_proposal_v1.md

研究问题
--------
当日跌幅上榜（top_list reason 含跌幅/负向，放量大跌）且事件前 20 日收益处于
最低五分组（跌透组 Q1）的股票，T+1 开盘买入、持有 H 日，是否获得扣成本后
显著为正的市场调整超额？与裸反转（全市场前 20 日收益最低 5%）对照，验证
"事件条件"是否有增量。

口径
----
- 母池：沪深普通 A 股（all.txt 剔北交所/指数/B 股）
- 事件：a_share_events_daily_v1 top_list reason 含"跌幅|负向异常波动"（T5）
- 信号（冻结）：
  - q1   ：事件日 T 前 20 日收益最低五分组的 T5 事件股，score=1，持续 H 日
  - t5   ：全部 T5 事件股，score=1，持续 H 日
  - naked：全市场前 20 日收益最低 5% 的股票（裸反转对照），score 每日重算
- 持有期 H ∈ {5, 10, 20}（主口径 20，与事件层验收一致）
- 执行：TopkDropout topk=20 n_drop=5，T+1 开盘，base/stress 两档费率，SH000852
- 窗口：2022-01-01 ~ 2026-07-31

输出（拒绝覆盖非空目录）
------------------------
output/analysis_static/a_share_t5_daily_strategy_v1/
  event_layer_q1.csv         事件层：Q1 组各 H 超额/t/分年度（复用正确标签）
  backtest_summary.csv       组合层：三臂 × 两费率 × 分年度
  decision.json / methodology.json / validation_report.txt
"""

from __future__ import annotations

import argparse
import glob
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

from analyze_a_share_negative_event_subtype_v1 import (
    load_top_list_neg, ts_to_qlib, qlib_to_ts, is_gem,
    QLIB_DIR, ST_INTERVALS, LIMIT_MAIN, LIMIT_GEM,
)
from analyze_a_share_trend_persistence_labelfix_v2 import build_universe

LOAD_START = "2020-07-01"
EVAL_START = "2022-01-01"
DATA_END = "2026-07-31"
HORIZONS = [5, 10, 20]
MAIN_H = 20
TOP_K = 20
N_DROP = 5
ACCOUNT = 1_000_000
BENCHMARK = "SH000852"
ANNUALIZATION_DAYS = 238
T_CRIT = 2.5
YEARLY_STRICT = 3
COST_SCENARIOS = {
    "base": {"open_cost": 0.0005, "close_cost": 0.0015},
    "stress": {"open_cost": 0.0010, "close_cost": 0.0030},
}


def load_market(codes: list[str]) -> pd.DataFrame:
    mkt = D.features(codes, ["$close", "$open", "$change", "$volume"],
                     start_time=LOAD_START, end_time=DATA_END, freq="day")
    mkt.columns = ["$close", "$open", "$change", "$volume"]
    mkt = mkt.reset_index().set_index(["datetime", "instrument"]).sort_index()
    g = mkt.groupby(level="instrument")
    # 正确 open-to-open 标签：T+1 开盘入场、T+1+h 开盘出场
    for h in HORIZONS:
        mkt[f"FWD_{h}"] = g["$open"].shift(-(h + 1)) / g["$open"].shift(-1) - 1
    # 事件前 20 日收益（open-to-open，事件日收盘后已知）。
    # 注意：groupby 除法在 MultiIndex 上会触发对齐错误，用 transform 保持行序。
    open_now = g["$open"].transform(lambda s: s)
    open_lag = g["$open"].transform(lambda s: s.shift(20))
    mkt["PRE_MOM20"] = open_now.to_numpy() / open_lag.to_numpy() - 1
    return mkt


def build_signal(sig_rows: list[tuple], calendar: pd.DatetimeIndex,
                 hold: int) -> pd.Series:
    """事件信号：事件日 T 赋值 score，持续到 T+hold 日（含）。

    score = 事件日的前 20 日收益负值（-PRE_MOM20）：跌得越透分越高，
    TopkDropout 据此选出候选池中"最跌透"的 topk（避免同分任意选择）。
    """
    sig = pd.DataFrame(sig_rows, columns=["instrument", "date", "score"])
    cal_list = list(calendar)
    cal_pos = {d: i for i, d in enumerate(cal_list)}
    rows = []
    for _, r in sig.iterrows():
        if r["date"] not in cal_pos:
            continue
        pos = cal_pos[r["date"]]
        for k in range(hold + 1):
            if pos + k < len(cal_list):
                rows.append((cal_list[pos + k], r["instrument"], r["score"]))
    out = pd.DataFrame(rows, columns=["datetime", "instrument", "score"])
    return out.set_index(["datetime", "instrument"])["score"].sort_index()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--output-dir", type=Path,
                        default=Path("output/analysis_static/a_share_t5_daily_strategy_v1"))
    parser.add_argument("--hold", type=int, default=MAIN_H, choices=HORIZONS)
    args = parser.parse_args()
    out = args.output_dir
    if out.exists() and any(out.iterdir()):
        raise FileExistsError(f"Refusing to overwrite existing experiment output: {out}")
    out.mkdir(parents=True, exist_ok=True)
    hold = args.hold

    qlib.init(provider_uri=str(QLIB_DIR), region=REG_CN)
    calendar = pd.DatetimeIndex(pd.to_datetime(
        pd.read_csv(QLIB_DIR / "calendars" / "day.txt", header=None)[0]))
    cal_list = list(calendar)
    cal_pos = {d: i for i, d in enumerate(cal_list)}

    print(f"[1/6] Universe + market panel (hold={hold}) ...", flush=True)
    codes, excluded = build_universe()
    mkt = load_market(codes)
    mkt_df = mkt.reset_index()
    mask_close = mkt_df["$close"].notna() & mkt_df["$volume"].notna() & (mkt_df["$volume"] > 0)
    limit_thresh = np.where(mkt_df["instrument"].map(is_gem), LIMIT_GEM, LIMIT_MAIN)
    mask_close &= ~(mkt_df["$change"] >= limit_thresh)
    mkt_clean = mkt_df[mask_close].copy()
    print(f"      rows={len(mkt)}, instruments={mkt.index.get_level_values('instrument').nunique()}, "
          f"keep={mask_close.mean():.1%}", flush=True)

    # ---- 事件 + 前 20 日收益分组 ----
    print("[2/6] T5 events + PRE_MOM20 quintiles ...", flush=True)
    t5 = load_top_list_neg()
    t5 = t5[(t5["date"] >= pd.Timestamp(EVAL_START)) & (t5["date"] <= pd.Timestamp(DATA_END))]
    t5["date"] = calendar[np.searchsorted(calendar.values, t5["date"].values)]
    ev = t5.merge(mkt_clean[["instrument", "datetime", "PRE_MOM20"]],
                  left_on=["instrument", "date"], right_on=["instrument", "datetime"], how="left")
    ev = ev.dropna(subset=["PRE_MOM20"])
    ev = ev.assign(mom_q=pd.qcut(ev["PRE_MOM20"].rank(method="first"), 5, labels=False) + 1)
    q1 = ev[ev["mom_q"].eq(1)]
    print(f"      T5 events={len(ev):,}, Q1(跌透)={len(q1):,} ({len(q1)/len(ev):.0%})", flush=True)

    # ---- 事件层：Q1 各 H 超额 ----
    print("[3/6] Event layer: Q1 excess by H ...", flush=True)
    mkt_merge = mkt_clean[["instrument", "datetime", "ts_code"] + [f"FWD_{h}" for h in HORIZONS]] \
        if "ts_code" in mkt_clean.columns else mkt_clean[["instrument", "datetime"] + [f"FWD_{h}" for h in HORIZONS]]
    bench = D.features([BENCHMARK], ["$open"], start_time=LOAD_START, end_time=DATA_END, freq="day")
    bench.columns = ["$open"]
    bench = bench.reset_index().set_index(["datetime", "instrument"]).sort_index()
    bg = bench.groupby(level="instrument")
    for h in HORIZONS:
        bench[f"BENCH_{h}"] = bg["$open"].shift(-(h + 1)) / bg["$open"].shift(-1) - 1
    bench_fwd = bench.reset_index()[["datetime"] + [f"BENCH_{h}" for h in HORIZONS]]
    bench_fwd = bench_fwd.set_index("datetime").sort_index()

    q1_merged = q1.merge(mkt_merge, left_on=["instrument", "date"], right_on=["instrument", "datetime"], how="left")
    q1_merged = q1_merged.dropna(subset=["FWD_20"])
    q1_merged = q1_merged.merge(bench_fwd, left_on="date", right_on="datetime", how="left")
    for h in HORIZONS:
        q1_merged[f"EXC_{h}"] = q1_merged[f"FWD_{h}"] - q1_merged[f"BENCH_{h}"]

    el_rows = []
    for h in HORIZONS:
        s = q1_merged[f"EXC_{h}"]
        yearly = q1_merged.groupby(q1_merged["date"].dt.year)[f"EXC_{h}"].mean()
        n = len(s)
        tstat = s.mean() / (s.std(ddof=1) / np.sqrt(n)) if n > 30 and s.std(ddof=1) > 0 else np.nan
        el_rows.append({"signal": "Q1", "horizon": h, "n": n, "excess_mean": s.mean(),
                        "tstat": tstat, "yearly": json.dumps({int(y): float(v) for y, v in yearly.items()})})
    el = pd.DataFrame(el_rows)
    el.to_csv(out / "event_layer_q1.csv", index=False)
    print(el.to_string(index=False), flush=True)

    # ---- 组合层信号（三臂）----
    print(f"[4/6] Building signals (hold window={hold}) ...", flush=True)
    # Q1/T5 臂：score = -PRE_MOM20（跌得越透分越高）
    q1_rows = q1[["instrument", "date", "PRE_MOM20"]].copy()
    q1_rows["score"] = -q1_rows["PRE_MOM20"]
    q1_sig = build_signal(q1_rows[["instrument", "date", "score"]].values.tolist(), calendar, hold)
    t5_rows = ev[["instrument", "date", "PRE_MOM20"]].copy()
    t5_rows["score"] = -t5_rows["PRE_MOM20"]
    t5_sig = build_signal(t5_rows[["instrument", "date", "score"]].values.tolist(), calendar, hold)
    print(f"      q1 signal rows={len(q1_sig)}, t5 rows={len(t5_sig)}", flush=True)

    # 裸反转：每日全市场 PRE_MOM20 最低 5% 的股票（score 每日重算 = 持续信号）
    naked_rows = []
    for d in mkt_clean["datetime"].unique():
        g = mkt_clean[mkt_clean["datetime"].eq(d)]
        g = g.dropna(subset=["PRE_MOM20"])
        if len(g) < 300:
            continue
        thr = g["PRE_MOM20"].quantile(0.05)
        bot = g[g["PRE_MOM20"] <= thr]
        for inst, pm in zip(bot["instrument"], bot["PRE_MOM20"]):
            naked_rows.append((d, inst, -pm))
    naked_sig = pd.DataFrame(naked_rows, columns=["datetime", "instrument", "score"])
    naked_sig = naked_sig.set_index(["datetime", "instrument"])["score"].sort_index()
    print(f"      naked(裸反转) rows={len(naked_sig)}", flush=True)

    # ---- 回测 ----
    print("[5/6] Backtesting 3 arms × 2 cost scenarios ...", flush=True)
    signals = {"q1": q1_sig, "t5": t5_sig, "naked": naked_sig}
    bt_rows = []
    for arm, signal in signals.items():
        for scenario, costs in COST_SCENARIOS.items():
            strategy = TopkDropoutStrategy(signal=signal, topk=TOP_K, n_drop=N_DROP)
            report, _ = backtest_daily(
                start_time=EVAL_START, end_time=DATA_END, strategy=strategy,
                account=ACCOUNT, benchmark=BENCHMARK,
                exchange_kwargs={"limit_threshold": 0.095, "deal_price": "open",
                                 "open_cost": costs["open_cost"], "close_cost": costs["close_cost"],
                                 "min_cost": 5},
            )
            sample = report.loc[EVAL_START:DATA_END]
            gross = risk_analysis(sample["return"] - sample["bench"], freq="day")["risk"]
            net = risk_analysis(sample["return"] - sample["bench"] - sample["cost"], freq="day")["risk"]
            yearly = {}
            for y in range(2022, 2027):
                ys = sample.loc[f"{y}-01-01":f"{y}-12-31"]
                if len(ys):
                    yearly[str(y)] = float((ys["return"] - ys["bench"] - ys["cost"]).mean() * ANNUALIZATION_DAYS)
            bt_rows.append({
                "arm": arm, "cost_scenario": scenario,
                "trading_days": int(len(sample)),
                "gross_excess_annualized_return": float(gross["annualized_return"]),
                "gross_excess_ir": float(gross["information_ratio"]),
                "net_excess_annualized_return": float(net["annualized_return"]),
                "net_excess_ir": float(net["information_ratio"]),
                "net_excess_max_drawdown": float(net["max_drawdown"]),
                "average_daily_turnover_rate": float(sample["turnover"].mean()),
                "annualized_cost_drag": float(sample["cost"].mean() * ANNUALIZATION_DAYS),
                "yearly_net": json.dumps(yearly),
            })
    bt = pd.DataFrame(bt_rows)
    bt.to_csv(out / "backtest_summary.csv", index=False)

    # ---- 判定 ----
    print("[6/6] Decision ...", flush=True)
    def pick(arm: str, scenario: str, column: str) -> float:
        row = bt[(bt["arm"].eq(arm)) & (bt["cost_scenario"].eq(scenario))]
        return float(row[column].iloc[0]) if len(row) else np.nan

    el20 = el[el["horizon"].eq(MAIN_H)].iloc[0]
    yearly_main = json.loads(el20["yearly"])
    neg_free = {int(y): v for y, v in yearly_main.items() if int(y) <= 2025}
    pos_years = sum(1 for v in neg_free.values() if v > 0)

    q1_net_ir = pick("q1", "stress", "net_excess_ir")
    q1_net_ret = pick("q1", "stress", "net_excess_annualized_return")
    naked_net_ir = pick("naked", "stress", "net_excess_ir")
    naked_net_ret = pick("naked", "stress", "net_excess_annualized_return")

    el_pass = bool(el20["tstat"] > T_CRIT and pos_years >= YEARLY_STRICT)
    combo_pass = bool(q1_net_ir >= 0.5 and q1_net_ret > 0 and q1_net_ret > naked_net_ret)

    if el_pass and combo_pass:
        decision = "t5_daily_adopted"
    elif el_pass and not combo_pass:
        decision = "t5_daily_event_layer_pass_combo_fail"
    else:
        decision = "t5_daily_not_adopted"

    decision_json = {
        "decision": decision,
        "hold": hold,
        "event_layer": {"n": int(el20["n"]), "excess_mean_h20": float(el20["excess_mean"]),
                        "tstat_h20": float(el20["tstat"]), "pos_years_2022_2025": pos_years,
                        "pass": el_pass},
        "combo_layer": {"q1_net_ir_stress": q1_net_ir, "q1_net_ret_stress": q1_net_ret,
                        "naked_net_ir_stress": naked_net_ir, "naked_net_ret_stress": naked_net_ret,
                        "q1_beats_naked": bool(q1_net_ret > naked_net_ret), "pass": combo_pass},
    }
    (out / "decision.json").write_text(json.dumps(decision_json, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    meta = {
        "purpose": "T5 跌幅上榜事件日频策略（超跌组反转 vs 裸反转）",
        "protocol": "research/protocols/a_share_t5_daily_strategy_protocol_v1.md",
        "universe": f"沪深普通 A 股 {len(codes)} 只",
        "eval_window": [EVAL_START, DATA_END],
        "benchmark": BENCHMARK,
        "hold_days": hold,
        "topk": TOP_K, "n_drop": N_DROP,
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
    }
    (out / "methodology.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")

    lines = [
        "# T5 跌幅上榜事件日频策略报告 v1\n",
        f"- 持有期: {hold} 日；组合: TopkDropout topk={TOP_K} n_drop={N_DROP}，T+1 开盘",
        f"- 费率: base 买0.05%/卖0.15%，stress 买0.10%/卖0.30%\n",
        "## 事件层（Q1 跌透组，市场调整超额）",
        el.to_string(index=False),
        f"\n## 判定: **{decision}**",
        f"- 事件层: Q1 h={MAIN_H} t={el20['tstat']:.2f}（门槛 >{T_CRIT}），"
        f"2022-2025 正向年数 {pos_years}（门槛 ≥{YEARLY_STRICT}）→ {'通过' if el_pass else '不通过'}",
        f"- 组合层(stress): Q1 净IR={q1_net_ir:.2f} 净超额={q1_net_ret*100:.2f}%/yr（门槛 IR≥0.5 且 >0），"
        f"裸反转 净IR={naked_net_ir:.2f} 净超额={naked_net_ret*100:.2f}%/yr，Q1 优于裸反转="
        f"{'是' if q1_net_ret > naked_net_ret else '否'} → {'通过' if combo_pass else '不通过'}",
        "",
        "## 组合层明细（年化，相对 SH000852）",
        bt[["arm", "cost_scenario", "gross_excess_annualized_return", "gross_excess_ir",
            "net_excess_annualized_return", "net_excess_ir", "average_daily_turnover_rate",
            "annualized_cost_drag"]].to_string(index=False),
        "",
        "## 分年度净超额（stress，年化）",
        bt[bt["cost_scenario"].eq("stress")][["arm", "yearly_net"]].to_string(index=False),
    ]
    (out / "validation_report.txt").write_text("\n".join(lines), encoding="utf-8")
    print("\n".join(lines), flush=True)


if __name__ == "__main__":
    main()
