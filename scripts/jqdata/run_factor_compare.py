#!/usr/bin/env python
"""按族运行「聚宽因子本地复现 vs 官方值」比对，产出精度报告。

    # 单族
    bash scripts/jqdata/run.sh scripts/jqdata/run_factor_compare.py --family technical

    # 指定标的与区间
    bash scripts/jqdata/run.sh scripts/jqdata/run_factor_compare.py \
        --family technical --codes 600519.XSHG 000002.XSHE --start 2025-12-01 --end 2026-03-02

    # 列出各族预期因子数
    bash scripts/jqdata/run.sh scripts/jqdata/run_factor_compare.py --list

设计的可重复性保证：
- 面板与官方因子值均按 (codes,start,end) 强缓存（.jqdata_cache/facsim/），
  第二次运行**不联网、不耗额度**；
- 每次网络取数都打印实际额度消耗；
- 报告落盘到 output/jqdata_factor_repro/，并附带当时的生效口径。
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
from facsim.registry import FAMILIES  # noqa: E402

FORMULAS = REPO_ROOT / ".jqdata/docs/factor_library_formulas.json"
OUT_DIR = REPO_ROOT / "output/jqdata_factor_repro"

DEFAULT_CODES = [
    "600519.XSHG",  # 贵州茅台（非金融）
    "000002.XSHE",  # 万科A（非金融）
    "000651.XSHE",  # 格力电器（非金融）
    "002415.XSHE",  # 海康威视（非金融）
    "600036.XSHG",  # 招商银行（金融）
    "000001.XSHE",  # 平安银行（金融）
]
DEFAULT_START, DEFAULT_END = "2025-12-01", "2026-03-02"


def family_codes(family: str) -> list[str]:
    d = json.loads(FORMULAS.read_text(encoding="utf-8"))
    return [k for k, v in d.items() if v.get("category") == family]


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--family", default="technical")
    ap.add_argument("--codes", nargs="*", default=None)
    ap.add_argument("--codes-file", default=None,
                    help="从文件读标的池（每行一个代码）；宽池运行时避免超长命令行")
    ap.add_argument("--start", default=DEFAULT_START)
    ap.add_argument("--end", default=DEFAULT_END)
    ap.add_argument("--ttm-stat-date", default="2026q1",
                    help="TTM 所用最新单季（须为截至 --end 已披露的最新季）")
    ap.add_argument("--lookback", type=int, default=400, help="面板回溯自然日")
    ap.add_argument("--list", action="store_true", help="只列出各族因子数")
    ap.add_argument("--no-cache", action="store_true")
    args = ap.parse_args()

    if args.codes is None:
        if args.codes_file:
            args.codes = [ln.strip() for ln in open(args.codes_file, encoding="utf-8")
                          if ln.strip()]
        else:
            args.codes = list(DEFAULT_CODES)

    if args.list:
        print("族           因子数  已实现")
        for fam in list(FAMILIES) + [f for f in ("risk", "momentum", "emotion",
                                                 "pershare", "basics", "growth",
                                                 "quality", "style", "style_pro")
                                     if f not in FAMILIES]:
            n = len(family_codes(fam))
            mark = "✅" if fam in FAMILIES else "—"
            print(f"  {fam:12s} {n:5d}   {mark}")
        return 0

    if args.family not in FAMILIES:
        print(f"[x] 族 {args.family} 尚未实现。已实现: {list(FAMILIES)}", file=sys.stderr)
        return 2

    mod = FAMILIES[args.family]
    expected = family_codes(args.family)
    print(f"=== 族 {args.family} | {len(expected)} 因子 | "
          f"{len(args.codes)} 标的 | {args.start}~{args.end} ===")
    print(f"口径: {KV.describe()}\n")

    panel = load_panel(args.codes, args.start, args.end,
                       lookback_days=args.lookback, use_cache=not args.no_cache)
    fund = None
    if getattr(mod, "NEEDS_FUND", False):
        fund = load_fundamentals_panel(args.codes, end=args.end, count=len(panel.dates),
                                       fields=mod.FUND_FIELDS, use_cache=not args.no_cache)
    ttm = {}
    if getattr(mod, "TTM_SPEC", None):
        for _tbl, _flds in mod.TTM_SPEC.items():
            ttm.update(load_ttm_panel(args.codes, args.ttm_stat_date, _tbl, _flds, panel.dates,
                                      use_cache=not args.no_cache))
    if getattr(mod, "TTM_NAN0_SPEC", None):
        for _tbl, _flds in mod.TTM_NAN0_SPEC.items():
            ttm.update(load_ttm_panel(args.codes, args.ttm_stat_date, _tbl, _flds, panel.dates,
                                      nan_as_zero=True, use_cache=not args.no_cache))
    avgq = {}
    if getattr(mod, "AVGQ_SPEC", None):
        for _tbl, _flds in mod.AVGQ_SPEC.items():
            avgq.update(load_ttm_panel(args.codes, args.ttm_stat_date, _tbl, _flds, panel.dates,
                                       agg="mean", use_cache=not args.no_cache))
    lagq = {}
    if getattr(mod, "LAGQ_SPEC", None):
        for _tbl, _flds in mod.LAGQ_SPEC.items():
            for _lbl, _agg in (("first", "first"), ("last", "last")):
                lagq[_lbl] = {**lagq.get(_lbl, {}), **load_ttm_panel(
                    args.codes, args.ttm_stat_date, _tbl, _flds, panel.dates,
                    agg=_agg, count=5, use_cache=not args.no_cache)}
    if getattr(mod, "NEEDS_TABLES", False):
        tmap = {"balance": getattr(mod, "BALANCE_FIELDS", []),
                "income": getattr(mod, "INCOME_FIELDS", []),
                "valuation": getattr(mod, "VALUATION_FIELDS", []),
                "indicator": getattr(mod, "INDICATOR_FIELDS", []),
                "cash_flow": getattr(mod, "CASHFLOW_FIELDS", [])}
        tables = {t: load_table_panel(args.codes, end=args.end, count=len(panel.dates),
                                      table=t, fields=f, use_cache=not args.no_cache)
                  for t, f in tmap.items() if f}
        tables["ttm"] = ttm
        tables["avgq"] = avgq
        tables["lagq_first"] = lagq.get("first", {})
        tables["lagq_last"] = lagq.get("last", {})
        local = mod.build(tables, fund) if fund is not None else mod.build(tables)
    elif fund is not None:
        local = mod.build(panel, fund)
    else:
        local = mod.build(panel)
    print(f"  本地实现 {len(local)}/{len(expected)} 个")
    print(f"  面板有效日 {len(panel.dates)}，列 {list(panel.C.columns)}\n")

    official = load_official(args.codes, expected, args.start, args.end,
                             use_cache=not args.no_cache)
    print()

    df = C.compare_family(args.family, local, official, expected)
    # 合并族内声明的诊断说明（未达标因子的原因归档）
    fam_notes = getattr(mod, "NOTES", {})
    if fam_notes:
        df["note"] = [
            (fam_notes.get(r.factor, "") or r.note) for r in df.itertuples()
        ]
    show = ["factor", "verdict", "n_overlap", "coverage", "max_abs_err", "p99_abs_err",
            "mean_abs_err", "rel_err", "corr"]
    with pd.option_context("display.width", 200, "display.max_colwidth", 40):
        print(df[show].to_string(index=False,
                                 float_format=lambda x: f"{x:.3e}" if abs(x) < 1e-3 else f"{x:.4f}"))
    print(f"\n{C.summarize(df)}")

    noted = df[df["note"].astype(bool)]
    if len(noted):
        print(f"\n--- 未达标/需说明的因子（{len(noted)}）---")
        for r in noted.itertuples():
            print(f"  [{r.verdict}] {r.factor}\n      {r.note}")

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    csv = OUT_DIR / f"{args.family}_{stamp}.csv"
    df.to_csv(csv, index=False)
    meta = OUT_DIR / f"{args.family}_{stamp}.meta.json"
    meta.write_text(json.dumps({
        "family": args.family, "codes": args.codes, "start": args.start, "end": args.end,
        "lookback_days": args.lookback, "conventions": KV.describe(),
        "n_factors_expected": len(expected), "n_factors_implemented": len(local),
        "panel_days": int(len(panel.dates)),
        "summary": C.summarize(df),
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n报告: {csv.relative_to(REPO_ROOT)}")
    print(f"元数据: {meta.relative_to(REPO_ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
