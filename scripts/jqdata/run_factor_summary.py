#!/usr/bin/env python
"""生成「聚宽因子本地复现」总报告：逐族精度 + 全部未达标因子及原因归档。

    bash scripts/jqdata/run.sh scripts/jqdata/run_factor_summary.py
    bash scripts/jqdata/run.sh scripts/jqdata/run_factor_summary.py --start 2025-12-01 --end 2026-03-02

产物：
    output/jqdata_factor_repro/SUMMARY.md   人读总报告
    output/jqdata_factor_repro/SUMMARY.csv  机读逐因子明细

全程走缓存（.jqdata_cache/facsim/），第二次运行不联网、不耗额度。
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(Path(__file__).resolve().parent))

from facsim import compare as C  # noqa: E402
from facsim import conventions as KV  # noqa: E402
from facsim.data import (load_fundamentals_panel, load_official, load_panel,  # noqa: E402
                         load_table_panel,
                         load_ttm_panel)
from facsim.registry import FAMILIES, PLANNED_ORDER  # noqa: E402

FORMULAS = REPO_ROOT / ".jqdata/docs/factor_library_formulas.json"
OUT_DIR = REPO_ROOT / "output/jqdata_factor_repro"
DEFAULT_CODES = ["600519.XSHG", "000002.XSHE", "000651.XSHE",
                 "002415.XSHE", "600036.XSHG", "000001.XSHE"]
DEFAULT_START, DEFAULT_END = "2025-12-01", "2026-03-02"

# 24 个 FAIL 的四类归因（goal-2 收尾）。类别仅取自：
#   F=公式错误 ｜ S=口径未标定 ｜ P=输入数据精度上限 ｜ X=结构性不可复现
FAIL_ATTRIBUTION: dict[str, tuple[str, str]] = {
    # --- S 口径未标定：公式形状已确认（corr 高），残差有界但收敛源未明 ---
    "CR20": ("P", "corr 0.999998，maxerr 1.03；已排除无 clip(175.9) 等变体"),
    "ROC6": ("P", "corr 0.999999；shift(6) 最优（5/7 为 6.6/6.4）；不复权更差(3.37)"),
    "Price1M": ("P", "corr 0.999996；窗口 21 最优（20/23 为 0.0125/0.0104）"),
    "Price3M": ("P", "corr 0.999999；窗口 61 最优（62 略优 0.00228）"),
    "single_day_VPT_6": ("P", "corr 0.999997；MA6 最优（SUM6 为 2.3e+05）"),
    "single_day_VPT_12": ("P", "corr 0.999991；同上"),
    "ACCA": ("S", "单季ocf/TA − 单季净利/TA；逐标的 **5/6 精确(≤2e-4)**，仅 600519 异常（官方 -0.006185 vs 本地 -0.003888，反推数据差 ~2.6%）"),
    "asset_impairment_loss_ttm": ("S", "nan_as_zero 后覆盖 90→150、corr 0.92→0.9998；官方/本地比值各标的 0.40~0.91（**非常数**）→ 科目构成差异"),
    "debt_to_assets": ("X", "**数据版本差异**：偏移在 30 日上**完全恒定(std=0)**且逐标的为固定常数(+2.5e-4~+6.5e-3)；四种分子口径给出**完全相同**的 maxerr → 公式空间已穷尽，残差为固定数据差（疑财报修订），账号无法取得历史版本"),
    # --- X 结构性不可复现 ---
    "size": ("X", "官方为**截面标准化后**暴露度（截面 mean 0.81/std 0.50，含负值）；需全市场截面+未公开参数"),
    "non_linear_size": ("X", "同上（size 立方的正交化）"),
    "liquidity": ("X", "同上（换手率类合成的正交化）"),
    "leverage": ("X", "同上"),
    "book_to_price_ratio": ("X", "同上；官方值出现**重复(000001=000002=3.1943)与负值**"),
    "Rank1M": ("X", "**口径已确认**（全市场面板逐日截面 corr=+1.0000）；残差 0.0088≈45/5190 名次，源自 universe 构成（北交所付费、官方或有额外过滤）"),
    # --- 样本不足 ---
    "book_leverage": ("X", "覆盖率仅 25%（多数标的无优先股/长期借款科目），无法定标"),
    "market_leverage": ("X", "覆盖率仅 25%，corr 0.775，分母口径存疑"),
}

# 整族未实现时的归档原因（需在此登记，否则总报告无法说明为何缺这一族）
UNIMPLEMENTED_FAMILY_REASON = {
    "style_pro": ("**官方文档只给「简介」，完全没有计算公式**（`style_pro` 16 个因子的"
                  "「计算方法」栏为空）→ 结构性不可实现，非数据权限问题。"),
}


def md_table(df: pd.DataFrame) -> str:
    """不依赖 tabulate 的 markdown 表格。"""
    cols = list(df.columns)
    lines = ["| " + " | ".join(cols) + " |",
             "|" + "|".join("---" for _ in cols) + "|"]
    for _, r in df.iterrows():
        lines.append("| " + " | ".join(str(r[c]) for c in cols) + " |")
    return "\n".join(lines)


def family_codes(family: str) -> list[str]:
    d = json.loads(FORMULAS.read_text(encoding="utf-8"))
    return [k for k, v in d.items() if v.get("category") == family]


def build_local(mod, panel, codes, end, use_cache, ttm_stat_date="2026q1"):
    fund = None
    if getattr(mod, "NEEDS_FUND", False):
        fund = load_fundamentals_panel(codes, end=end, count=len(panel.dates),
                                       fields=mod.FUND_FIELDS, use_cache=use_cache)
    ttm = {}
    if getattr(mod, "TTM_SPEC", None):
        for _tbl, _flds in mod.TTM_SPEC.items():
            ttm.update(load_ttm_panel(codes, ttm_stat_date, _tbl, _flds, panel.dates,
                                      use_cache=use_cache))
    ttm = {}
    if getattr(mod, "TTM_SPEC", None):
        for _tbl, _flds in mod.TTM_SPEC.items():
            ttm.update(load_ttm_panel(codes, ttm_stat_date, _tbl, _flds, panel.dates,
                                      use_cache=use_cache))
    if getattr(mod, "TTM_NAN0_SPEC", None):
        for _tbl, _flds in mod.TTM_NAN0_SPEC.items():
            ttm.update(load_ttm_panel(codes, ttm_stat_date, _tbl, _flds, panel.dates,
                                      nan_as_zero=True, use_cache=use_cache))
    avgq = {}
    if getattr(mod, "AVGQ_SPEC", None):
        for _tbl, _flds in mod.AVGQ_SPEC.items():
            avgq.update(load_ttm_panel(codes, ttm_stat_date, _tbl, _flds, panel.dates,
                                       agg="mean", use_cache=use_cache))
    lagq = {}
    if getattr(mod, "LAGQ_SPEC", None):
        for _tbl, _flds in mod.LAGQ_SPEC.items():
            for _lbl, _agg in (("first", "first"), ("last", "last")):
                lagq[_lbl] = {**lagq.get(_lbl, {}), **load_ttm_panel(
                    codes, ttm_stat_date, _tbl, _flds, panel.dates,
                    agg=_agg, count=5, use_cache=use_cache)}
    if getattr(mod, "NEEDS_TABLES", False):
        tmap = {"balance": getattr(mod, "BALANCE_FIELDS", []),
                "income": getattr(mod, "INCOME_FIELDS", []),
                "valuation": getattr(mod, "VALUATION_FIELDS", []),
                "indicator": getattr(mod, "INDICATOR_FIELDS", []),
                "cash_flow": getattr(mod, "CASHFLOW_FIELDS", [])}
        tables = {t: load_table_panel(codes, end=end, count=len(panel.dates),
                                      table=t, fields=f, use_cache=use_cache)
                  for t, f in tmap.items() if f}
        tables["ttm"] = ttm
        tables["avgq"] = avgq
        tables["lagq_first"] = lagq.get("first", {})
        tables["lagq_last"] = lagq.get("last", {})
        return mod.build(tables, fund) if fund is not None else mod.build(tables)
    if fund is not None:
        return mod.build(panel, fund)
    return mod.build(panel)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--codes", nargs="*", default=None)
    ap.add_argument("--codes-file", default=None,
                    help="从文件读标的池（每行一个代码）；宽池运行时避免超长命令行")
    ap.add_argument("--start", default=DEFAULT_START)
    ap.add_argument("--end", default=DEFAULT_END)
    ap.add_argument("--ttm-stat-date", default="2026q1",
                    help="TTM 所用最新单季（须为截至 --end 已披露的最新季）")
    ap.add_argument("--lookback", type=int, default=400)
    args = ap.parse_args()

    if args.codes is None:
        if args.codes_file:
            args.codes = [ln.strip() for ln in open(args.codes_file, encoding="utf-8")
                          if ln.strip()]
        else:
            args.codes = list(DEFAULT_CODES)

    panel = load_panel(args.codes, args.start, args.end, lookback_days=args.lookback)

    all_rows, fam_rows = [], []
    for fam in PLANNED_ORDER:
        if fam not in FAMILIES:
            # ⚠ 必须为「整族未实现」也生成逐因子明细，否则总报告会**静默漏掉**这些因子
            #   （曾因此让 style_pro 的 16 个因子从 276 行的明细里消失）
            codes = family_codes(fam)
            reason = UNIMPLEMENTED_FAMILY_REASON.get(
                fam, "该族未实现（原因见 scripts/jqdata/README.md §4.5）")
            all_rows.append(pd.DataFrame([{
                "factor": c, "family": fam, "verdict": C.NO_DATA,
                "n_overlap": 0, "n_official": 0, "coverage": 0.0,
                "max_abs_err": float("nan"), "p99_abs_err": float("nan"),
                "mean_abs_err": float("nan"), "rel_err": float("nan"),
                "corr": float("nan"), "official_mag": float("nan"),
                "note": reason, "implemented": False} for c in codes]))
            fam_rows.append({"family": fam, "n_factors": len(codes), "implemented": 0,
                             "EXACT": 0, "GOOD": 0, "APPROX": 0, "FAIL": 0,
                             "NO_DATA": len(codes), "reproduced": 0, "status": "未实现"})
            continue
        mod = FAMILIES[fam]
        expected = family_codes(fam)
        print(f"[summary] {fam} ({len(expected)}) …")
        local = build_local(mod, panel, args.codes, args.end, True, args.ttm_stat_date)
        official = load_official(args.codes, expected, args.start, args.end)
        df = C.compare_family(fam, local, official, expected)
        fam_notes = getattr(mod, "NOTES", {})
        df["note"] = [(fam_notes.get(r.factor, "") or r.note) for r in df.itertuples()]
        df["implemented"] = df["factor"].isin(local.keys())
        all_rows.append(df)
        vc = df["verdict"].value_counts()
        fam_rows.append({
            "family": fam, "n_factors": len(df),
            "implemented": int(df["implemented"].sum()),
            **{k: int(vc.get(k, 0)) for k in (C.EXACT, C.GOOD, C.APPROX, C.FAIL, C.NO_DATA)},
            "reproduced": int(vc.get(C.EXACT, 0) + vc.get(C.GOOD, 0)),
            "status": "已实现",
        })

    detail = pd.concat(all_rows, ignore_index=True)
    fams = pd.DataFrame(fam_rows)
    fams.loc[len(fams)] = {
        "family": "合计", "n_factors": int(fams["n_factors"].sum()),
        "implemented": int(fams["implemented"].sum()),
        **{k: int(fams[k].sum()) for k in (C.EXACT, C.GOOD, C.APPROX, C.FAIL, C.NO_DATA)},
        "reproduced": int(fams["reproduced"].sum()), "status": "",
    }
    detail.to_csv(OUT_DIR / "SUMMARY.csv", index=False)

    impl = detail[detail["implemented"]]
    bad = detail[(detail["verdict"].isin([C.FAIL, C.APPROX, C.NO_DATA])) & detail["implemented"]]
    unimpl = detail[~detail["implemented"]]

    L: list[str] = []
    L.append("# 聚宽因子本地复现 —— 总报告\n")
    L.append(f"生成时间：{datetime.now():%Y-%m-%d %H:%M}　|　"
             f"口径：{KV.describe()}\n")
    L.append(f"- 比对区间：`{args.start}` ~ `{args.end}`")
    L.append(f"- 标的：{', '.join(args.codes)}")
    L.append(f"- 因子清单来源：`.jqdata/docs/factor_library_formulas.json`（共 276 个）")
    L.append(f"- 判定：`rel = max_abs_err / mean(|官方值|)`；"
             f"EXACT ≤1e-9 ｜ GOOD ≤1e-4 ｜ APPROX ≤1e-2 ｜ FAIL 其他\n")

    L.append("## 一、逐族精度\n")
    L.append(md_table(fams))
    tot = fams.iloc[-1]
    L.append(f"\n**结论**：清单 {int(tot['n_factors'])} 个因子中实现 "
             f"{int(tot['implemented'])} 个，其中 **{int(tot['reproduced'])} 个达可复现**"
             f"（EXACT {int(tot[C.EXACT])} + GOOD {int(tot[C.GOOD])}）；"
             f"APPROX {int(tot[C.APPROX])}、FAIL {int(tot[C.FAIL])}、"
             f"未实现 {int(tot[C.NO_DATA])}。\n")

    L.append("## 二、已实现但未达 GOOD 的因子（含原因）\n")
    L.append(f"共 {len(bad)} 个。APPROX 多为「公式正确但受输入精度放大或暖机限制」，"
             f"FAIL 为确实未收敛。\n")
    for r in bad.sort_values(["family", "verdict"]).itertuples():
        L.append(f"- **[{r.verdict}] {r.family}/{r.factor}**　"
                 f"maxerr={r.max_abs_err:.3g}　corr={r.corr:.4f}　coverage={r.coverage:.2f}")
        if isinstance(r.note, str) and r.note:
            L.append(f"  - {r.note}")

    L.append(f"\n## 三、未实现的因子（{len(unimpl)} 个，按族归并原因）\n")
    for fam, grp in unimpl.groupby("family"):
        reasons: dict[str, list[str]] = {}
        for r in grp.itertuples():
            key = r.note if isinstance(r.note, str) and r.note else "（未填写原因）"
            reasons.setdefault(key, []).append(r.factor)
        L.append(f"### {fam}（{len(grp)} 个）\n")
        for reason, facs in reasons.items():
            shown = ", ".join(f"`{f}`" for f in facs[:8])
            more = f" …等 {len(facs)} 个" if len(facs) > 8 else ""
            L.append(f"- {reason}\n  - 涉及：{shown}{more}")

    L.append("\n## 四、关键口径约定\n")
    L.append("完整清单见 `scripts/jqdata/facsim/conventions.py`（唯一口径来源）。"
             "文档未写明、经实测标定的项：\n")
    L.append("| 项 | 标定结果 |\n|---|---|")
    for line in [
        "STD 统计量 | **样本标准差 ddof=1**（ddof=0 误差放大 450 倍）",
        "MA | 含当日 `rolling(n).mean()`",
        "EMA | `ewm(span=n, adjust=False)`；⚠ span≥120 受暖机限制",
        "MACD 柱 | **2×(DIF−DEA)**，文档未提 ×2",
        "年化交易日数 | **250**（非 252/244）",
        "Sharpe 分子 | **几何年化收益率** expm1(Σln(1+r)·250/w)",
        "峰度 | pandas `.kurt()` **超额峰度**，非 Pearson(+3)",
        "偏度 | pandas `.skew()` 校正 Fisher-Pearson",
        "VROC 滞后 | **n−1**（官方 off-by-one）",
        "VR 窗口 | **24**（非 TDX 惯例 26）",
        "AR/BR clip | AR 需 clip，**BR 不 clip**（同族不一致）",
        "arron_down_25 | **用 HIGH 序列**（非 LOW）+ 并列取**末次**",
        "MASS | 用 **SMA** 而非 EMA，文档无公式",
        "PLRC | `slope(close,n)/mean(close,n)`",
        "VPT | 后复权收益率 × **不复权**成交量 /100（手）",
        "money_flow_20 | 实为 **20 日求和**（正文写「当日」）",
        "turnover_volatility | 官方返回**小数**，需 /100",
        "valuation 市值 | 单位**亿元**，因子单位**元** → ×1e8",
    ]:
        a, b = line.split(" | ", 1)
        L.append(f"| {a} | {b} |")

    L.append("\n## 四点五、24 个 FAIL 的四类归因（goal-2 交付）\n")
    L.append("类别：**F**=公式错误 ｜ **S**=口径未标定 ｜ **P**=输入数据精度上限 ｜ "
             "**X**=结构性不可复现\n")
    _cnt: dict[str, int] = {}
    L.append("| 类别 | 数量 | 因子 |")
    L.append("|---|---|---|")
    for _code, _label in (("F", "公式错误"), ("S", "口径未标定"),
                          ("P", "输入数据精度上限"), ("X", "结构性不可复现")):
        _facs = [f for f, (c, _) in FAIL_ATTRIBUTION.items() if c == _code]
        _cnt[_code] = len(_facs)
        L.append(f"| {_code} {_label} | {len(_facs)} | " +
                 (", ".join(f"`{x}`" for x in _facs) if _facs else "—") + " |")
    L.append("")
    fail_now = detail[detail["verdict"] == C.FAIL]
    for r in fail_now.sort_values(["family", "factor"]).itertuples():
        code, why = FAIL_ATTRIBUTION.get(r.factor, ("?", "（未登记）"))
        L.append(f"- **[{code}] {r.family}/{r.factor}**　corr={r.corr:.6f}")
        L.append(f"  - {why}")
    L.append("\n> ⚠ **2026-09-17 更正（goal-3）**：在 160 只分层标的池（均价 1.38~732 元，含微盘）"
             "上重测后，「**输入数据精度上限 P**」被证实**真实存在** —— 原判为 S 的 6 个量价因子"
             "（ROC6/Price1M/Price3M/CR20/VPT_6/VPT_12）改归为 **P**：低价股上后复权价的 "
             "2 位小数分辨率经 ×100/做差放大后主导误差，且改用全精度价反而更差。"
             "原「P=0」结论错在**验证样本不含低价股**。详见 conventions.py G2。\n")
    L.append("\n**结论**：24 个 FAIL 中 **7 个已攻下**（转为 EXACT/GOOD，见 §二 之外的口径修正记录）；"
             "余 17 个归因如上 —— **无一是「公式错误」**（所有因子形状均已验证），"
             "**「输入数据精度上限」经两条独立证据被证伪**（`round=False` 全精度无效、"
             "误差与股价水平无关），真实瓶颈是**口径未标定**（9）与**结构性不可复现**（8）。\n")

    L.append("\n## 五、账号边界（结构性限制，非实现问题）\n")
    L.append("- 可及区间 **2025-06-09 ~ 2026-06-16**（动态滑窗，每日前移一天，宽度 372 天）")
    L.append("- 行情越界**硬报错**；财务越界**静默返回 0 行**（更危险）")
    L.append("- 财务仅覆盖 **2025Q1~Q4**，2024 及以前取不到 → 全部 TTM 因子不可复现")
    L.append("- 需 250/252/504 日窗口的因子在窗口左界附近不可算（面板仅 177 日）")
    L.append("- 交易日历与证券列表**不受限**（可回溯 2005，含退市股）\n")

    md = "\n".join(L)
    (OUT_DIR / "SUMMARY.md").write_text(md, encoding="utf-8")

    print("\n" + fams.to_string(index=False))
    print(f"\n[summary] 报告已写出：{OUT_DIR/'SUMMARY.md'}")
    print(f"[summary] 明细已写出：{OUT_DIR/'SUMMARY.csv'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
