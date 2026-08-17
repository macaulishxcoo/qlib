#!/usr/bin/env python3
"""日频策略回测 v1（基本面域 + 量价增强）。

协议：research/protocols/a_share_daily_strategy_protocol_v1.md

研究问题
--------
确立日频策略基线：domain_comp（基本面域内 composite 排序 + 日频 top50）为主力，
偏度低权重增强（0.7·comp + 0.3·skew）是否贡献增量。

三版本：
- main（domain_comp）：域内 composite_neutral rank pct，日频 top50
- enhanced：域内 0.7·comp_rank + 0.3·skew_rank
- domain_skew（对照）：域内 skew rank pct（引用上轮结论）

口径
----
- 主池：沪深普通 A 股母池；数据：cn_data_2026 + daily_basic_pit_v1 + style_pit_v1 + financial_pit_v1
- 域：composite_neutral 前 50%，42 个月度调仓日、月内固定
- 过滤：ST/*ST/退市（PIT）+ 停牌 + 涨停信号日
- 回测：TopkDropout topk=50 n_drop=5 日频，T+1 开盘，SH000852，base/stress
- 窗口：2022-01-01 ~ 2025-06-30（财务 PIT 上限 2025-06-28）

输出（拒绝覆盖非空目录）
------------------------
output/analysis_static/a_share_daily_strategy_v1/
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

ROOT = Path(__file__).resolve().parents[1]


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


neut = load_module("neut", ROOT / "scripts/analyze_a_share_price_volume_factor_neutralization_v1.py")
mq = load_module("mq", ROOT / "scripts/analyze_a_share_value_quality_level_factors_extension_v1.py")

QLIB_DIR = neut.QLIB_DIR
DATA_START = neut.DATA_START
BT_START = "2022-01-01"
BT_END = "2025-06-30"
TOP_K = 50
N_DROP = 5
ACCOUNT = 1_000_000
BENCHMARK = "SH000852"
ANNUALIZATION_DAYS = 238
COST_SCENARIOS = {
    "base": {"open_cost": 0.0005, "close_cost": 0.0015},
    "stress": {"open_cost": 0.0010, "close_cost": 0.0030},
}
DOMAIN_QUANTILE = 0.5
ICIR_ALIVE = 0.5
W_COMP, W_SKEW = 0.7, 0.3   # enhanced 权重


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--output-dir", type=Path,
                        default=Path("output/analysis_static/a_share_daily_strategy_v1"))
    args = parser.parse_args()
    out = args.output_dir
    if out.exists() and any(out.iterdir()):
        raise FileExistsError(f"Refusing to overwrite existing experiment output: {out}")
    out.mkdir(parents=True, exist_ok=True)

    qlib.init(provider_uri=str(QLIB_DIR), region=REG_CN)

    # ---- 1. 母池行情 + 因子 ----
    print("[1/6] Universe + market + factors ...", flush=True)
    codes, excluded = neut.build_universe()
    mkt = neut.load_market(codes)
    mask = neut.build_filter_mask(mkt)
    eval_all = mkt.loc[pd.Timestamp(BT_START): pd.Timestamp(BT_END)]
    mask_full = pd.Series(mask, index=mkt.index)
    eval_keep = eval_all.loc[mask_full.loc[eval_all.index].to_numpy()]
    print(f"      rows={len(eval_keep)}, instruments={eval_keep.index.get_level_values('instrument').nunique()}, "
          f"keep={mask.mean():.1%}", flush=True)

    # ---- 2. 逐日 SKEW_MVI（全市场截面）----
    print("[2/6] Daily SKEW_MVI residuals (full market) ...", flush=True)
    dates = eval_keep.index.get_level_values("datetime").unique()
    skew_mvi = {}
    for d in dates:
        g = eval_keep.loc[d]
        if len(g) < 300:
            continue
        resid = neut.neutralize_day(g, "SKEW60", "MVI")
        skew_mvi[d] = pd.Series(resid, index=g.index)
    print(f"      days={len(skew_mvi)}", flush=True)

    # ---- 3. 基本面域 + 域内 composite rank ----
    print("[3/6] Building fundamental domain + in-domain composite rank ...", flush=True)
    fin = mq.load_financials()
    grid = pd.read_csv(mq.STYLE_DIR / "monthly_rebalance_grid.csv.gz", compression="gzip",
                       parse_dates=["rebalance_date", "asof_date"])
    industry = pd.read_csv(mq.STYLE_DIR / "industry_l1_effective_intervals.csv.gz", compression="gzip", dtype=str)
    industry["in_date"] = pd.to_datetime(industry["in_date"], errors="coerce")
    industry["out_date"] = pd.to_datetime(industry["out_date"], errors="coerce")
    size = pd.read_csv(mq.STYLE_DIR / "monthly_free_float_size.csv.gz", compression="gzip")
    size["asof_date"] = pd.to_datetime(size["asof_date"], errors="coerce")

    g = grid[(grid["rebalance_date"] >= BT_START) & (grid["rebalance_date"] <= BT_END)].copy()
    domains = {}
    comp_rank_in_domain = {}   # rebalance_date -> dict(instrument -> 域内 rank pct)
    for _, row in g.iterrows():
        snap = mq.build_snapshot(fin, row, industry, size)
        if snap.empty:
            continue
        snap = snap.set_index("ts_code")
        # composite_score 返回 RangeIndex Series，snap index 是 ts_code：按位置赋值
        snap["composite"] = mq.composite_score(snap.reset_index(), ("ep", "bm", "div_yield", "accruals")).to_numpy()
        valid = snap.dropna(subset=["composite", "l1_code", "log_size"])
        if valid.empty:
            continue
        comp_neutral = mq.ols_residual(valid["composite"], valid["l1_code"], valid["log_size"])
        thr = comp_neutral.quantile(1 - DOMAIN_QUANTILE)
        in_domain = comp_neutral[comp_neutral >= thr]
        code_map = {c: neut.ts_to_qlib(c) for c in in_domain.index}
        domains[row["rebalance_date"]] = set(code_map.values())
        # 域内 comp rank pct（月内固定）
        comp_rank = in_domain.rank(pct=True)
        comp_rank_in_domain[row["rebalance_date"]] = {
            code_map[c]: v for c, v in comp_rank.items()
        }
    print(f"      domains built: {len(domains)} (avg size {np.mean([len(v) for v in domains.values()]):.0f})", flush=True)

    # ---- 4. 域 + comp_rank 映射到每日 ----
    print("[4/6] Mapping domain/comp_rank to each day ...", flush=True)
    rebal_dates = sorted(domains.keys())
    domain_by_day: dict[pd.Timestamp, set[str]] = {}
    comp_rank_by_day: dict[pd.Timestamp, pd.Series] = {}
    for d in dates:
        idx = np.searchsorted(rebal_dates, d, side="right") - 1
        if idx >= 0:
            domain_by_day[d] = domains[rebal_dates[idx]]
            comp_rank_by_day[d] = pd.Series(comp_rank_in_domain[rebal_dates[idx]])
        else:
            domain_by_day[d] = set()
            comp_rank_by_day[d] = pd.Series(dtype=float)

    # ---- 5. 三版本信号 ----
    print("[5/6] Building 3 version signals ...", flush=True)
    main_rows, enh_rows, skew_rows = [], [], []
    for d in dates:
        dom = domain_by_day.get(d, set())
        cr = comp_rank_by_day.get(d)
        sk = skew_mvi.get(d)
        if not dom or cr is None or len(cr) == 0 or sk is None:
            continue
        for inst in dom:
            if inst not in cr.index or inst not in sk.index:
                continue
            if not np.isfinite(cr.loc[inst]) or not np.isfinite(sk.loc[inst]):
                continue
            main_rows.append((d, inst, cr.loc[inst]))                                   # comp rank
            skew_rows.append((d, inst, sk.loc[inst]))                                   # skew rank（对照）
        # enhanced：域内 comp_rank 与 skew_rank 合成（skew 需逐日域内 rank）
        common = [i for i in dom if i in sk.index]
        sk_dom = sk.loc[common].dropna()
        if len(sk_dom) > 50:
            sk_rank = sk_dom.rank(pct=True)
            for inst in sk_rank.index:
                if inst in cr.index and np.isfinite(cr.loc[inst]):
                    enh_rows.append((d, inst, W_COMP * cr.loc[inst] + W_SKEW * sk_rank.loc[inst]))

    sig_main = pd.DataFrame(main_rows, columns=["datetime", "instrument", "score"]).set_index(["datetime", "instrument"])
    sig_enh = pd.DataFrame(enh_rows, columns=["datetime", "instrument", "score"]).set_index(["datetime", "instrument"])
    sig_skew = pd.DataFrame(skew_rows, columns=["datetime", "instrument", "score"]).set_index(["datetime", "instrument"])
    signals = {
        "main": sig_main["score"],
        "enhanced": sig_enh["score"],
        "domain_skew": sig_skew["score"],
    }
    for v, s in signals.items():
        print(f"      {v}: days={s.index.get_level_values('datetime').nunique()}, rows={len(s)}", flush=True)

    # ---- 6. 回测 ----
    print("[6/6] Backtest (3 versions × base/stress) ...", flush=True)
    all_rows = []
    yearly = {}
    for version in ["main", "enhanced", "domain_skew"]:
        for scenario in ["base", "stress"]:
            costs = COST_SCENARIOS[scenario]
            strategy = TopkDropoutStrategy(signal=signals[version], topk=TOP_K, n_drop=N_DROP)
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
            y2024 = full.loc["2024-01-01":"2024-12-31"]
            y2024_net = risk_analysis(y2024["return"] - y2024["bench"] - y2024["cost"], freq="day")["risk"] if len(y2024) > 50 else {}
            y25h1 = full.loc["2025-01-01":]
            y25h1_net = risk_analysis(y25h1["return"] - y25h1["bench"] - y25h1["cost"], freq="day")["risk"] if len(y25h1) > 50 else {}
            all_rows.append({
                "version": version, "cost_scenario": scenario,
                "gross_excess_annualized_return": float(gross["annualized_return"]),
                "gross_excess_ir": float(gross["information_ratio"]),
                "net_excess_annualized_return": float(net["annualized_return"]),
                "net_excess_ir": float(net["information_ratio"]),
                "net_excess_max_drawdown": float(net["max_drawdown"]),
                "average_daily_turnover_rate": float(full["turnover"].mean()),
                "annualized_cost_drag": float(full["cost"].mean() * ANNUALIZATION_DAYS),
                "y2024_net_excess": float(y2024_net.get("annualized_return", np.nan)),
                "y2025H1_net_excess": float(y25h1_net.get("annualized_return", np.nan)),
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

    # main base 日度 report
    print("[7] Saving daily report (main/base) ...", flush=True)
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
    m = bt[(bt["version"] == "main") & (bt["cost_scenario"] == "base")].iloc[0]
    e = bt[(bt["version"] == "enhanced") & (bt["cost_scenario"] == "base")].iloc[0]
    if m["net_excess_ir"] >= ICIR_ALIVE:
        if e["net_excess_ir"] >= ICIR_ALIVE and e["net_excess_annualized_return"] > m["net_excess_annualized_return"]:
            decision = "enhanced_adopted"
        else:
            decision = "main_baseline"
    else:
        decision = "not_viable"
    (out / "decision.json").write_text(json.dumps({"main_base": decision}, ensure_ascii=False, indent=2) + "\n",
                                      encoding="utf-8")

    lines = []
    lines.append(f"# 日频策略回测报告 v1（基本面域 + 量价增强）\n")
    lines.append(f"- 主池: 沪深普通 A 股 {len(codes)} 只（剔除 BJ/指数/B 股 {len(excluded)} 只）")
    lines.append(f"- 域: composite_neutral 前 {DOMAIN_QUANTILE:.0%}（月频更新，{len(domains)} 个月，"
                 f"平均 {np.mean([len(v) for v in domains.values()]):.0f} 只）")
    lines.append(f"- 信号: main=域内 comp_rank；enhanced=0.7·comp_rank+0.3·skew_rank；对照=域内 skew")
    lines.append(f"- 回测: TopkDropout topk={TOP_K} n_drop={N_DROP} 日频，T+1 开盘，基准 {BENCHMARK}")
    lines.append(f"- 窗口: {BT_START} ~ {BT_END}（财务 PIT 上限 2025-06-28；2025-06 后待财务更新）\n")

    lines.append(f"## 判定：**{decision}**\n")

    lines.append("### 回测汇总（全期）")
    lines.append("| 版本 | 费率 | gross超额 | gross IR | net超额 | net IR | net回撤 | 日均换手 | 年化成本 | 2024 net | 2025H1 net |")
    lines.append("|---|---|---|---|---|---|---|---|---|---|---|")
    for _, r in bt.iterrows():
        lines.append(f"| {r['version']} | {r['cost_scenario']} | {r['gross_excess_annualized_return']:+.3f} | "
                     f"{r['gross_excess_ir']:.2f} | {r['net_excess_annualized_return']:+.3f} | {r['net_excess_ir']:.2f} | "
                     f"{r['net_excess_max_drawdown']:.1%} | {r['average_daily_turnover_rate']:.1%} | "
                     f"{r['annualized_cost_drag']:.1%} | {r['y2024_net_excess']:+.3f} | {r['y2025H1_net_excess']:+.3f} |")

    lines.append("\n### 分年度 net 超额（base）")
    for version in ["main", "enhanced", "domain_skew"]:
        lines.append(f"\n**{version}**")
        lines.append("| 年份 | net超额年化 | net IR |")
        lines.append("|---|---|---|")
        for r in yearly.get(version, []):
            lines.append(f"| {r['year']} | {r['net_excess_annualized_return']:+.3f} | {r['net_excess_ir']:.2f} |")

    lines.append("\n### 关键对照（base）")
    lines.append(f"- 增强 vs 基线（偏度增强增量）: {e['net_excess_annualized_return']:+.3f} vs {m['net_excess_annualized_return']:+.3f}")
    lines.append(f"- 基线 vs 纯偏度（基线价值）: {m['net_excess_annualized_return']:+.3f} vs "
                 f"{bt[(bt['version']=='domain_skew') & (bt['cost_scenario']=='base')].iloc[0]['net_excess_annualized_return']:+.3f}")

    lines.append("\n### 判定解读（协议 §5）")
    lines.append("- enhanced_adopted: main 与 enhanced 均 IR≥0.5 且 enhanced > main → 偏度增强采纳")
    lines.append("- main_baseline: main IR≥0.5（增强不达标）→ 日频基线=main，增强不采纳")
    lines.append("- not_viable: main IR<0.5 → 日频基线不成立，收口")
    (out / "validation_report.txt").write_text("\n".join(lines), encoding="utf-8")

    meta = {
        "purpose": "日频策略基线（基本面域+日频调仓）+ 偏度低权重增强验证",
        "protocol": "research/protocols/a_share_daily_strategy_protocol_v1.md",
        "universe": f"沪深普通 A 股 {len(codes)} 只（剔除 {len(excluded)} 只）",
        "data_dir": str(QLIB_DIR),
        "bt_window": [BT_START, BT_END],
        "domain": f"composite_neutral top {DOMAIN_QUANTILE:.0%}, monthly rebalance ({len(domains)} months)",
        "signal_main": "in-domain composite_neutral rank pct",
        "signal_enhanced": f"{W_COMP}*comp_rank + {W_SKEW}*skew_rank (in-domain)",
        "strategy": f"TopkDropout topk={TOP_K} n_drop={N_DROP}",
        "benchmark": BENCHMARK,
        "cost_scenarios": COST_SCENARIOS,
        "coverage_limit": "financial PIT available_date <= 2025-06-28",
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
    }
    (out / "methodology.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"      report -> {out / 'validation_report.txt'}", flush=True)
    print(f"      decision = {decision}", flush=True)
    print("DONE", flush=True)


if __name__ == "__main__":
    main()
