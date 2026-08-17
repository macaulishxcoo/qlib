#!/usr/bin/env python3
"""存活价量因子短周期可行性检验 v1。

协议：research/protocols/a_share_price_volume_factor_short_term_protocol_v1.md

研究问题
--------
orthogonality h40 补测判定 TURNOVER_LEVEL5 / SKEW60 是短周期信号（h=5 有效、
h=40 反转）。本脚本检验两因子能否支撑独立短周期策略：
  C1 衰减轮廓：h ∈ {1,3,5,10} 的 IC/ICIR/IC>0（MVI 残差口径），找最优持有期
  C2 稳定性：最优 h 分年度 IC（2022-2025 同向 + 2026 单独）+ raw vs MVI 对照
  C3 单调性：最优 h 五分位收益
  C4 换手成本：最优 h Top20% 等权组合的年化净超额（双边成本 0.20%）

口径（与 neutralization v1 完全一致）
--------------------------------------
- 主池：沪深普通 A 股母池 5544 只（剔除 BJ/指数/B 股）
- 数据：cn_data_2026 + daily_basic_pit_v1 + a_share_style_pit_v1
- 过滤：ST/停牌/涨停信号日；标签 T+1 开盘成交 Ref($open,-1)/Ref($close,-(h+1))-1
- 窗口：2022-01-01 ~ 2026-07-31（预热自 2020-01-01）

输出（拒绝覆盖非空目录）
------------------------
output/analysis_static/a_share_price_volume_factor_short_term_v1/
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

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"

HORIZONS = [1, 3, 5, 10]
TOP_FRAC = 0.20
COST_RATE = 0.002  # 双边 0.20%（买 0.05% + 卖 0.15%）
ANNUAL = 238


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


neut = load_module("neut", SCRIPTS / "analyze_a_share_price_volume_factor_neutralization_v1.py")

QLIB_DIR = neut.QLIB_DIR
DATA_START = neut.DATA_START
DATA_END = neut.DATA_END
EVAL_START = neut.EVAL_START
FACTORS = ["TURNOVER_LEVEL5", "SKEW60"]
ICIR_GOOD = 0.5
ICIR_ALIVE = 0.3
YEARLY_STRICT = 3


def daily_ic(g: pd.DataFrame, factor: str, label: str) -> float:
    s = g[[factor, label]].dropna()
    if len(s) < 30:
        return np.nan
    return s[factor].corr(s[label], method="spearman")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--output-dir", type=Path,
                        default=Path("output/analysis_static/a_share_price_volume_factor_short_term_v1"))
    args = parser.parse_args()
    out = args.output_dir
    if out.exists() and any(out.iterdir()):
        raise FileExistsError(f"Refusing to overwrite existing experiment output: {out}")
    out.mkdir(parents=True, exist_ok=True)

    qlib.init(provider_uri=str(QLIB_DIR), region=REG_CN)

    # ---- 数据 ----
    print("[1/5] Loading market + factors ...", flush=True)
    codes, excluded = neut.build_universe()
    mkt = neut.load_market(codes)
    mask = neut.build_filter_mask(mkt)
    print(f"      rows={len(mkt)}, keep={mask.mean():.1%}", flush=True)
    eval_all = mkt.loc[pd.Timestamp(EVAL_START): pd.Timestamp(DATA_END)]
    mask_full = pd.Series(mask, index=mkt.index)
    eval_keep = eval_all.loc[mask_full.loc[eval_all.index].to_numpy()]

    # 扩展标签：h ∈ {1,3,5,10}（与 battery v1 的 h=5 同式外推）
    print("[2/5] Extending labels to h in {1,3,5,10} + computing MVI residuals ...", flush=True)
    g = eval_keep.groupby(level="instrument")
    for h in HORIZONS:
        lab = g["open"].shift(-1) / g["close"].shift(-(h + 1)) - 1
        eval_keep[f"FWD_{h}_open"] = pd.Series(lab.to_numpy(), index=eval_keep.index)

    # MVI 残差列（逐日 neutralize，与 neutralization v1 一致）
    resid_cols = {f: {} for f in FACTORS}
    for d, g_day in eval_keep.groupby(level="datetime"):
        for f in FACTORS:
            resid_cols[f][d] = neut.neutralize_day(g_day, f, "MVI")
    for f in FACTORS:
        parts = [pd.Series(resid_cols[f][d], index=g_day.index)
                 for d, g_day in eval_keep.groupby(level="datetime")]
        concat = pd.concat(parts)
        eval_keep.loc[concat.index, f"{f}_resid_MVI"] = concat.to_numpy()

    # ---- C1 decay 轮廓 + C2 稳定性 ----
    print("[3/5] Running IC decay profile + yearly stability ...", flush=True)
    decay_rows = []
    yearly_rows = []
    for f in FACTORS:
        for h in HORIZONS:
            lab = f"FWD_{h}_open"
            ic_series = eval_keep.groupby(level="datetime").apply(
                lambda d: daily_ic(d, f"{f}_resid_MVI", lab)).dropna()
            ic_series.index = pd.to_datetime(ic_series.index)
            yearly = ic_series.groupby(ic_series.index.year).mean()
            decay_rows.append({
                "factor": f, "h": h,
                "ic": float(ic_series.mean()),
                "icir": float(ic_series.mean() / (ic_series.std() + 1e-12)),
                "ic_pos": float((ic_series > 0).mean()),
                "n_days": int(len(ic_series)),
            })
            for yr, v in yearly.items():
                yearly_rows.append({"factor": f, "h": h, "year": yr, "ic": float(v)})
    decay = pd.DataFrame(decay_rows)
    yearly = pd.DataFrame(yearly_rows)

    # ---- C3 五分位 + C4 换手成本（最优 h = ICIR 最高）----
    print("[4/5] Running quintile + turnover/cost on best horizon ...", flush=True)
    quintile_rows = []
    cost_rows = []
    for f in FACTORS:
        sub = decay[decay["factor"] == f].sort_values("icir", ascending=False)
        best_h = int(sub.iloc[0]["h"])
        lab = f"FWD_{best_h}_open"
        sig = f"{f}_resid_MVI"

        # C3 五分位：全部调仓日的分组均值收益
        grp_all = []
        for date, d in eval_keep.groupby(level="datetime"):
            s = d[[sig, lab]].dropna()
            if len(s) < 300:
                continue
            q = pd.qcut(s[sig].rank(method="first"), 5, labels=False) + 1
            grp_all.append(pd.DataFrame({"q": q.to_numpy(), "ret": s[lab].to_numpy()}))
        ga = pd.concat(grp_all)
        qmeans = ga.groupby("q")["ret"].mean()
        for q, v in qmeans.items():
            quintile_rows.append({"factor": f, "h": best_h, "quintile": int(q), "mean_ret": float(v)})

        # C4 Top20% 组合换手与成本（每 h 天调仓一次，与持有期匹配）
        port_dates = sorted(eval_keep.index.get_level_values("datetime").unique())
        prev_set = None
        turnover_rates = []
        per_period_excess = []
        for i in range(0, len(port_dates) - 1, best_h):
            date = port_dates[i]
            d = eval_keep.loc[date]
            s = d[[sig, lab]].dropna()
            if len(s) < 300:
                continue
            n_top = max(int(len(s) * TOP_FRAC), 20)
            top = set(s.sort_values(sig, ascending=False).index[:n_top])
            if prev_set is not None:
                turnover_rates.append(1.0 - len(top & prev_set) / max(len(top), 1))
            prev_set = top
            top_mask = s.index.isin(top)
            port_ret = float(s.loc[top_mask, lab].mean())
            mkt_ret = float(s[lab].mean())
            per_period_excess.append(port_ret - mkt_ret)

        periods = len(per_period_excess)
        if periods > 0 and turnover_rates:
            mean_turn = float(np.mean(turnover_rates))
            mean_excess = float(np.mean(per_period_excess))
            ann_excess = mean_excess * (ANNUAL / best_h)
            ann_turn = mean_turn * (ANNUAL / best_h)
            ann_cost = ann_turn * COST_RATE
            cost_rows.append({
                "factor": f, "h": best_h,
                "per_period_excess": mean_excess,
                "ann_excess_gross": ann_excess,
                "per_period_turnover": mean_turn,
                "ann_turnover": ann_turn,
                "ann_cost": ann_cost,
                "ann_excess_net": ann_excess - ann_cost,
                "cost_share": ann_cost / abs(ann_excess) if ann_excess else np.nan,
            })
        else:
            cost_rows.append({"factor": f, "h": best_h, "per_period_excess": np.nan,
                              "ann_excess_gross": np.nan, "per_period_turnover": np.nan,
                              "ann_turnover": np.nan, "ann_cost": np.nan,
                              "ann_excess_net": np.nan, "cost_share": np.nan})

    quintile = pd.DataFrame(quintile_rows)
    cost = pd.DataFrame(cost_rows)

    # ---- 判定 ----
    print("[5/5] Judging + writing ...", flush=True)
    decisions = {}
    for f in FACTORS:
        d = decay[decay["factor"] == f].sort_values("icir", ascending=False).iloc[0]
        best_h = int(d["h"])
        y = yearly[(yearly["factor"] == f) & (yearly["h"] == best_h)]
        y_prev = y[(y["year"] >= 2022) & (y["year"] <= 2025)]
        same_sign = int((y_prev["ic"] > 0).sum()) if len(y_prev) else 0
        ic2026 = float(y[y["year"] == 2026]["ic"].iloc[0]) if (y["year"] == 2026).any() else np.nan
        c = cost[cost["factor"] == f].iloc[0]
        net = c["ann_excess_net"]
        if d["icir"] >= ICIR_GOOD and same_sign >= YEARLY_STRICT and ic2026 > 0 and net is not np.nan and net > 0:
            decisions[f] = "short_term_viable"
        elif d["icir"] >= ICIR_ALIVE and net is not np.nan and net > 0:
            decisions[f] = "short_term_marginal"
        else:
            decisions[f] = "short_term_not_viable"

    # ---- 写产物 ----
    decay.to_csv(out / "decay_profile.csv", index=False)
    yearly.to_csv(out / "stability_yearly.csv", index=False)
    quintile.to_csv(out / "quintile_returns.csv", index=False)
    cost.to_csv(out / "turnover_cost.csv", index=False)
    (out / "decision.json").write_text(json.dumps(decisions, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    lines = []
    lines.append("# 存活价量因子短周期可行性检验报告 v1\n")
    lines.append(f"- 主池: 沪深普通 A 股 {len(codes)} 只（剔除 {len(excluded)} 只）")
    lines.append(f"- 标签: T+1 开盘成交 Ref($open,-1)/Ref($close,-(h+1))-1，h ∈ {HORIZONS}")
    lines.append(f"- 窗口: {EVAL_START} ~ {DATA_END}（预热自 2020-01-01）")
    lines.append(f"- 成本: 双边 0.20%（买 0.05% + 卖 0.15%）；Top {int(TOP_FRAC*100)}% 等权组合\n")

    lines.append("### C1 衰减轮廓（MVI 残差口径）")
    lines.append("| 因子 | h | IC | ICIR | IC>0 | 天数 |")
    lines.append("|---|---|---|---|---|---|")
    for _, r in decay.iterrows():
        lines.append(f"| {r['factor']} | {r['h']} | {r['ic']:+.4f} | {r['icir']:.2f} | {r['ic_pos']:.0%} | {r['n_days']} |")

    lines.append("\n### C2 稳定性（分年度 IC）")
    lines.append("| 因子 | h | 2022 | 2023 | 2024 | 2025 | 2026 | 22-25同向 |")
    lines.append("|---|---|---|---|---|---|---|---|")
    for f in FACTORS:
        for h in HORIZONS:
            y = yearly[(yearly["factor"] == f) & (yearly["h"] == h)].set_index("year")["ic"]
            row_prev = [y.get(yr, np.nan) for yr in [2022, 2023, 2024, 2025]]
            same = sum(1 for v in row_prev if v > 0)
            cells = " | ".join(f"{y.get(yr, np.nan):+.4f}" for yr in [2022, 2023, 2024, 2025, 2026])
            lines.append(f"| {f} | {h} | {cells} | {same}/4 |")

    lines.append("\n### C3 五分位收益（最优 h，即 ICIR 最高 h）")
    lines.append("| 因子 | h | Q1 | Q2 | Q3 | Q4 | Q5 | Q5-Q1 |")
    lines.append("|---|---|---|---|---|---|---|---|")
    for f in FACTORS:
        q = quintile[quintile["factor"] == f]
        h = int(q["h"].iloc[0])
        means = q.set_index("quintile")["mean_ret"]
        cells = " | ".join(f"{means.get(i, np.nan):+.4f}" for i in [1, 2, 3, 4, 5])
        lines.append(f"| {f} | {h} | {cells} | {means.get(5, np.nan) - means.get(1, np.nan):+.4f} |")

    lines.append("\n### C4 换手与成本（最优 h Top20% 组合）")
    lines.append("| 因子 | h | 单期毛超额 | 年化毛超额 | 单期换手 | 年化换手 | 年化成本 | 年化净超额 |")
    lines.append("|---|---|---|---|---|---|---|---|")
    for _, r in cost.iterrows():
        lines.append(f"| {r['factor']} | {r['h']} | {r['per_period_excess']:+.4f} | "
                     f"{r['ann_excess_gross']:+.2%} | {r['per_period_turnover']:.2%} | "
                     f"{r['ann_turnover']:.2%} | {r['ann_cost']:+.2%} | {r['ann_excess_net']:+.2%} |")

    lines.append("\n### 判定")
    for f in FACTORS:
        d = decay[decay["factor"] == f].sort_values("icir", ascending=False).iloc[0]
        y = yearly[(yearly["factor"] == f) & (yearly["h"] == int(d["h"]))]
        y_prev = y[(y["year"] >= 2022) & (y["year"] <= 2025)]
        same = int((y_prev["ic"] > 0).sum())
        ic26 = y[y["year"] == 2026]["ic"].iloc[0] if (y["year"] == 2026).any() else np.nan
        c = cost[cost["factor"] == f].iloc[0]
        lines.append(f"- **{f}**（最优 h={int(d['h'])}）: ICIR {d['icir']:.2f}, 22-25同向 {same}/4, "
                     f"2026 IC {ic26:+.4f}, 年化净超额 {c['ann_excess_net']:+.2%} → **{decisions[f]}**")

    lines.append("\n### 覆盖边界")
    lines.append("- 统计可行性检验（IC/稳定性/扣成本粗算），非完整回测：无基准对冲、无逐笔滑点、无容量模型")
    lines.append("- 换手成本按固定双边 0.20% 粗算，未含冲击成本；Top20% 组合约 1000+ 只，滑点压力小但未实测")
    lines.append("- 财务/风格数据仅用于中性化与行业，主信号为纯行情因子，2022-2026 全程可测")
    (out / "validation_report.txt").write_text("\n".join(lines), encoding="utf-8")

    meta = {
        "purpose": "存活价量因子短周期（日/周频）可行性：decay 轮廓 + 稳定性 + 单调性 + 换手成本",
        "protocol": "research/protocols/a_share_price_volume_factor_short_term_protocol_v1.md",
        "universe": f"沪深普通 A 股 {len(codes)} 只（剔除 {len(excluded)} 只）",
        "data_dir": str(QLIB_DIR),
        "eval_window": [EVAL_START, DATA_END],
        "horizons": HORIZONS,
        "label": "Ref($open,-1)/Ref($close,-(h+1))-1 (T+1 open, h-day)",
        "candidate_neutralization": "MVI residual (log circ_mv + std20 + SW-L1 industry)",
        "top_fraction": TOP_FRAC,
        "cost_rate_bilateral": COST_RATE,
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
    }
    (out / "methodology.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"      report -> {out / 'validation_report.txt'}", flush=True)
    print(f"      decisions = {decisions}", flush=True)
    print("DONE", flush=True)


if __name__ == "__main__":
    main()
