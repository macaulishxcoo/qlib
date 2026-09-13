#!/usr/bin/env python3
"""存活价量因子与主线正交性检验 v1。

协议：research/protocols/a_share_price_volume_factor_orthogonality_protocol_v1.md

研究问题
--------
battery v1 + neutralization v1 判定 TURNOVER_LEVEL5 / SKEW60（MVI 中性化后）
alpha_confirmed。本脚本检验第二步：候选因子与主线（价值质量四因子 composite，
行业+log_size 中性化）在月度调仓日是否正交、等权合并是否产生 IC 增量。

口径
----
- 主池：沪深普通 A 股母池（与 v1/v2 一致，ST/停牌/涨停过滤）
- 主线：composite_score(ep,bm,div_yield,accruals; ≥3 因子) → ols_residual(l1_code, log_size)
  （复用 analyze_a_share_value_quality_level_factors_extension_v1.py）
- 候选：TURNOVER_LEVEL5 / SKEW60 的 MVI 残差（log circ_mv + std20 + 申万L1，
  与 neutralization v1 一致）
- 窗口：42 个调仓日 2022-01-04 ~ 2025-06-03（财务 PIT 上限 2025-06-28）
- 标签：T+1 开盘成交 h=5

输出（拒绝覆盖非空目录）
------------------------
output/analysis_static/a_share_price_volume_factor_orthogonality_v1/
  orthogonality_daily.csv     每调仓日 相关性（O1）
  orthogonality_summary.csv   O1 全期 + 分年度中位数/均值
  complementarity_daily.csv   每调仓日 三信号 RankIC（O2）
  complementarity_summary.csv O2 全期 IC/ICIR/IC>0
  decision.json               预设判定（每候选）
  methodology.json            口径快照
  validation_report.txt       中文报告
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


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


neut = load_module("neut", SCRIPTS / "analyze_a_share_price_volume_factor_neutralization_v1.py")
mq = load_module("mq", SCRIPTS / "analyze_a_share_value_quality_level_factors_extension_v1.py")

QLIB_DIR = neut.QLIB_DIR
DATA_START = neut.DATA_START
DATA_END = neut.DATA_END
EVAL_START = neut.EVAL_START
FACTORS = ["TURNOVER_LEVEL5", "SKEW60"]
FACTORS_MAIN = ("ep", "bm", "div_yield", "accruals")
CORR_ORTH = 0.5
CORR_REDUNDANT = 0.7


def ts_to_qlib(ts: str) -> str:
    return f"{ts[-2:].upper()}{ts[:6]}"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--output-dir", type=Path,
                        default=Path("output/analysis_static/a_share_price_volume_factor_orthogonality_v1"))
    args = parser.parse_args()
    out = args.output_dir
    if out.exists() and any(out.iterdir()):
        raise FileExistsError(f"Refusing to overwrite existing experiment output: {out}")
    out.mkdir(parents=True, exist_ok=True)

    qlib.init(provider_uri=str(QLIB_DIR), region=REG_CN)

    # ---- 主线 composite ----
    print("[1/5] Loading financial PIT + building mainline composite (42 rebalance dates) ...", flush=True)
    fin = mq.load_financials()
    grid = pd.read_csv(mq.STYLE_DIR / "monthly_rebalance_grid.csv.gz", compression="gzip",
                       parse_dates=["rebalance_date", "asof_date"])
    industry = pd.read_csv(mq.STYLE_DIR / "industry_l1_effective_intervals.csv.gz", compression="gzip", dtype=str)
    industry["in_date"] = pd.to_datetime(industry["in_date"], errors="coerce")
    industry["out_date"] = pd.to_datetime(industry["out_date"], errors="coerce")
    size = pd.read_csv(mq.STYLE_DIR / "monthly_free_float_size.csv.gz", compression="gzip")
    size["asof_date"] = pd.to_datetime(size["asof_date"], errors="coerce")

    g = grid[(grid["rebalance_date"] >= EVAL_START) & (grid["rebalance_date"] <= "2025-06-30")].copy()
    print(f"      rebalance dates: {len(g)} ({g['rebalance_date'].min().date()} ~ {g['rebalance_date'].max().date()})", flush=True)

    snapshots = {}
    for _, row in g.iterrows():
        snap = mq.build_snapshot(fin, row, industry, size)
        if snap.empty:
            continue
        snap = snap.set_index("ts_code")
        # composite_score 返回 RangeIndex Series，snap 的 index 是 ts_code：按位置赋值（行序一致）
        snap["composite"] = mq.composite_score(snap.reset_index(), FACTORS_MAIN).to_numpy()
        valid = snap.dropna(subset=["composite", "l1_code", "log_size"])
        snap["composite_neutral"] = mq.ols_residual(
            valid["composite"], valid["l1_code"], valid["log_size"])
        snap["composite_raw"] = snap["composite"]
        snap["code"] = snap.index.map(ts_to_qlib)
        snapshots[row["rebalance_date"]] = snap[["code", "composite_raw", "composite_neutral"]].reset_index(drop=True)
    print(f"      snapshots built: {len(snapshots)}", flush=True)

    # ---- 候选因子（MVI 残差 + raw）+ 过滤 ----
    print("[2/5] Loading market + candidate factors ...", flush=True)
    codes, excluded = neut.build_universe()
    mkt = neut.load_market(codes)
    mask = neut.build_filter_mask(mkt)
    print(f"      rows={len(mkt)}, keep={mask.mean():.1%}", flush=True)
    eval_all = mkt.loc[pd.Timestamp(EVAL_START): pd.Timestamp(DATA_END)]
    mask_full = pd.Series(mask, index=mkt.index)
    eval_keep = eval_all.loc[mask_full.loc[eval_all.index].to_numpy()]

    # ---- 逐调仓日 相关性 + 互补性 ----
    print("[3/5] Running O1 (orthogonality) + O2 (complementarity) per rebalance date ...", flush=True)
    o1_rows, o2_rows = [], []
    for date, snap in snapshots.items():
        g_day = eval_keep.loc[pd.Timestamp(date)]
        cand_raw, cand_mvi = {}, {}
        for f in FACTORS:
            raw_ic_series = g_day[f]
            resid = neut.neutralize_day(g_day, f, "MVI")
            cand_raw[f] = pd.Series(raw_ic_series.to_numpy(), index=g_day.index)
            cand_mvi[f] = pd.Series(resid, index=g_day.index)

        m = pd.DataFrame({"instrument": g_day.index})
        m = m.set_index("instrument")
        for f in FACTORS:
            m[f"{f}_raw"] = cand_raw[f].to_numpy()
            m[f"{f}_MVI"] = cand_mvi[f].to_numpy()
        m["FWD_5_open"] = g_day["FWD_5_open"].to_numpy()
        m = m.reset_index().merge(snap, left_on="instrument", right_on="code", how="inner")
        m = m.set_index("instrument").dropna(subset=["composite_neutral", "FWD_5_open"])

        for f in FACTORS:
            a = m[f"{f}_MVI"].astype(float)
            b = m["composite_neutral"].astype(float)
            a_raw = m[f"{f}_raw"].astype(float)
            b_raw = m["composite_raw"].astype(float)
            if len(m) >= 300:
                o1_rows.append({"date": date, "factor": f,
                                "corr_mvi_neutral": m[f"{f}_MVI"].corr(m["composite_neutral"], method="spearman"),
                                "corr_raw_raw": m[f"{f}_raw"].corr(m["composite_raw"], method="spearman"),
                                "n": len(m)})
            # O2 互补性：z = 横截面 rank pct
            z_comp = m["composite_neutral"].rank(method="first", pct=True)
            z_cand = m[f"{f}_MVI"].rank(method="first", pct=True)
            combined = 0.5 * z_comp + 0.5 * z_cand
            lab = m["FWD_5_open"]
            o2_rows.append({
                "date": date, "factor": f,
                "ic_comp": m["composite_neutral"].corr(lab, method="spearman"),
                "ic_cand": m[f"{f}_MVI"].corr(lab, method="spearman"),
                "ic_combined": combined.corr(lab, method="spearman"),
            })

    o1 = pd.DataFrame(o1_rows)
    o2 = pd.DataFrame(o2_rows)

    # ---- 汇总 + 判定 ----
    print("[4/5] Summarizing ...", flush=True)
    o1_summary_rows = []
    for f in FACTORS:
        s = o1[o1["factor"] == f]
        s["year"] = pd.to_datetime(s["date"]).dt.year
        yearly = s.groupby("year")["corr_mvi_neutral"].agg(["median", "mean"])
        o1_summary_rows.append({
            "factor": f,
            "corr_mvi_neutral_median": s["corr_mvi_neutral"].median(),
            "corr_mvi_neutral_mean": s["corr_mvi_neutral"].mean(),
            "corr_raw_raw_median": s["corr_raw_raw"].median(),
            "corr_yearly_min_abs": float(yearly["median"].abs().min()) if len(yearly) else np.nan,
            "corr_yearly_max_abs": float(yearly["median"].abs().max()) if len(yearly) else np.nan,
            "n_dates": len(s),
        })
    o1_summary = pd.DataFrame(o1_summary_rows)

    o2_summary_rows = []
    for f in FACTORS:
        s = o2[o2["factor"] == f]
        row = {"factor": f}
        for col in ["ic_comp", "ic_cand", "ic_combined"]:
            x = s[col].dropna()
            row[f"{col}_mean"] = x.mean()
            row[f"{col}_icir"] = x.mean() / (x.std() + 1e-12)
            row[f"{col}_pos"] = (x > 0).mean()
        o2_summary_rows.append(row)
    o2_summary = pd.DataFrame(o2_summary_rows)

    decisions = {}
    for f in FACTORS:
        r = o1_summary[o1_summary["factor"] == f].iloc[0]
        comp = o2_summary[o2_summary["factor"] == f].iloc[0]
        corr = abs(r["corr_mvi_neutral_median"])
        if corr < CORR_ORTH:
            if comp["ic_combined_mean"] > comp["ic_comp_mean"] and comp["ic_combined_mean"] > comp["ic_cand_mean"]:
                decisions[f] = "orthogonal_positive"
            else:
                decisions[f] = "orthogonal_neutral"
        elif corr < CORR_REDUNDANT:
            decisions[f] = "partially_overlapping"
        else:
            decisions[f] = "redundant"

    # ---- 写产物 ----
    o1.to_csv(out / "orthogonality_daily.csv", index=False)
    o1_summary.to_csv(out / "orthogonality_summary.csv", index=False)
    o2.to_csv(out / "complementarity_daily.csv", index=False)
    o2_summary.to_csv(out / "complementarity_summary.csv", index=False)
    (out / "decision.json").write_text(json.dumps(decisions, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    # ---- 报告 ----
    print("[5/5] Writing report ...", flush=True)
    lines = []
    lines.append(f"# 存活价量因子与主线正交性检验报告 v1\n")
    lines.append(f"- 主池: 沪深普通 A 股 {len(codes)} 只（剔除 BJ/指数/B 股 {len(excluded)} 只）")
    lines.append(f"- 主线: 价值质量四因子 composite（≥3 因子）→ 行业+log_size 残差（total_mv 口径）")
    lines.append(f"- 候选: TURNOVER_LEVEL5 / SKEW60 的 MVI 残差（circ_mv 口径）")
    lines.append(f"- 窗口: {len(g)} 个调仓日 {g['rebalance_date'].min().date()} ~ {g['rebalance_date'].max().date()}")
    lines.append(f"  （财务 PIT 上限 2025-06-28；2025-06 后待财务更新补测）")
    lines.append(f"- 标签: T+1 开盘成交 h=5；相关性 = 调仓日截面 Spearman\n")

    lines.append("### O1 正交性（候选 MVI vs 主线 composite_neutral）")
    lines.append("| 因子 | corr中位数 | corr均值 | raw_raw中位数 | 分年度|corr|范围 | n | 判定 |")
    lines.append("|---|---|---|---|---|---|---|")
    for _, r in o1_summary.iterrows():
        lines.append(f"| {r['factor']} | {r['corr_mvi_neutral_median']:+.3f} | {r['corr_mvi_neutral_mean']:+.3f} | "
                     f"{r['corr_raw_raw_median']:+.3f} | {r['corr_yearly_min_abs']:.3f}~{r['corr_yearly_max_abs']:.3f} | "
                     f"{r['n_dates']} | {decisions[r['factor']]} |")

    lines.append("\n### O2 互补性（调仓日 RankIC，h=5）")
    lines.append("| 因子 | 主线IC/ICIR | 候选IC/ICIR | 合并IC/ICIR | 合并增益 |")
    lines.append("|---|---|---|---|---|")
    for _, r in o2_summary.iterrows():
        gain = r["ic_combined_mean"] - max(r["ic_comp_mean"], r["ic_cand_mean"])
        lines.append(f"| {r['factor']} | {r['ic_comp_mean']:+.4f}/{r['ic_comp_icir']:.2f} | "
                     f"{r['ic_cand_mean']:+.4f}/{r['ic_cand_icir']:.2f} | "
                     f"{r['ic_combined_mean']:+.4f}/{r['ic_combined_icir']:.2f} | {gain:+.4f} |")

    lines.append("\n### 判定解读（协议 §5）")
    lines.append("- orthogonal_positive: |corr|<0.5 且合并 IC>任一分量 → 确认主线正交信号源")
    lines.append("- orthogonal_neutral: |corr|<0.5 但合并无增益 → 正交不增量，暂不投入")
    lines.append("- partially_overlapping: |corr|∈[0.5,0.7) → 需先在主线轴上正交化再评")
    lines.append("- redundant: |corr|≥0.7 → 与主线同信息，判死")
    for f in FACTORS:
        lines.append(f"- **{f}: {decisions[f]}**")

    lines.append("\n### 覆盖边界")
    lines.append("- 财务 PIT 可用到 2025-06-28；2025-06 之后的调仓日未测（数据未更新），不伪造")
    lines.append("- 主线市值口径 total_mv，候选 MVI 用 circ_mv，两轴市值口径不同，如实报告")
    (out / "validation_report.txt").write_text("\n".join(lines), encoding="utf-8")

    meta = {
        "purpose": "候选价量因子与主线价值质量 composite 的正交性 + 互补性检验",
        "protocol": "research/protocols/a_share_price_volume_factor_orthogonality_protocol_v1.md",
        "universe": f"沪深普通 A 股 {len(codes)} 只（剔除 {len(excluded)} 只）",
        "data_dir": str(QLIB_DIR),
        "eval_window": [str(g['rebalance_date'].min().date()), str(g['rebalance_date'].max().date())],
        "n_rebalance_dates": len(g),
        "factors": FACTORS,
        "mainline_composite": "composite_score(ep,bm,div_yield,accruals; min_factors=3) -> ols_residual(l1_code, log_size)",
        "candidate_neutralization": "MVI residual (log circ_mv + std20 + SW-L1 industry)",
        "label": "Ref($open,-1)/Ref($close,-6)-1 (h=5)",
        "thresholds": {"corr_orth": CORR_ORTH, "corr_redundant": CORR_REDUNDANT},
        "coverage_limit": "financial PIT available_date <= 2025-06-28; dates after 2025-06 not tested",
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
    }
    (out / "methodology.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"      report -> {out / 'validation_report.txt'}", flush=True)
    print(f"      decisions = {decisions}", flush=True)
    print("DONE", flush=True)


if __name__ == "__main__":
    main()
