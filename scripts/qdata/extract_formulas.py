#!/usr/bin/env python
"""抽取 qdata.cc 因子库的公式，产出结构化清单。

    bash scripts/jqdata/run.sh scripts/qdata/extract_formulas.py
    bash scripts/jqdata/run.sh scripts/qdata/extract_formulas.py --check

产物：``output/qdata_factor_repro/factor_formulas.json``

结构（对标 ``.jqdata/docs/factor_library_formulas.json``）::

    {
      "MACD": {
        "factor_type": "Momentum",
        "desc": "计算 MACD ... 指标。",
        "formula": "1. DIF = EMA(Close, 12) - EMA(Close, 26)\\n2. DEA = EMA(DIF, 9)\\n3. MACD = 2 × (DIF - DEA)",
        "params": {"fast": "12", "slow": "26", "signal": "9"},
        "passthrough": false,
        "lang": "zh"
      }, ...
    }

``factor_desc`` 的版式（实测）::

    <中文描述>

    数学表达式:            ← 或 "Mathematical expression:"
    <公式若干行>

    参数:                  ← 可选
        fast: 快线周期，默认为 12

**预计算直通**：部分因子（实测 8 个 Quality）标注
「直接使用预计算字段 lake.financial_derivative.fin_xxx」——公式给了，
但值来自数据湖的预计算表，**无法从原始数据复现**，本抽取器会标记 ``passthrough``。
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from qdata_env import QDataClient  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parents[2]
OUT_DIR = REPO_ROOT / "output" / "qdata_factor_repro"
OUT_PATH = OUT_DIR / "factor_formulas.json"

# 公式块起始 / 结束标记（中英并列）
# 实测有三种标记：数学表达式 / 标准数学表达式 / 计算逻辑（另有英文版）
_FORMULA_START = re.compile(
    r"^\s*(?:标准\s*)?(数学表达式|Mathematical expression|计算逻辑|Calculation logic)"
    r"\s*[:：]\s*$", re.M | re.I)
_PARAM_START = re.compile(r"^\s*(参数|Parameters?)\s*[:：]\s*$", re.M | re.I)
_PASSTHROUGH = re.compile(r"预计算字段|precomputed field|lake\.financial_derivative",
                          re.I)
_PARAM_LINE = re.compile(r"^\s*([A-Za-z_][A-Za-z0-9_]*)\s*[:：]\s*(.+?)\s*$")


def parse_desc(desc: str) -> dict:
    """把 ``factor_desc`` 拆成 desc / formula / params / passthrough。"""
    desc = (desc or "").replace("\r\n", "\n").strip()
    formula, params_txt = "", ""
    body = desc

    m = _FORMULA_START.search(desc)
    if m:
        body = desc[:m.start()].strip()
        rest = desc[m.end():]
        p = _PARAM_START.search(rest)
        if p:
            formula = rest[:p.start()].strip()
            params_txt = rest[p.end():].strip()
        else:
            formula = rest.strip()

    params: dict[str, str] = {}
    for line in params_txt.splitlines():
        mm = _PARAM_LINE.match(line)
        if mm:
            params[mm.group(1)] = mm.group(2)
    return {
        "desc": body,
        "formula": formula,
        "params": params,
        "passthrough": bool(_PASSTHROUGH.search(desc)),
        "lang": "zh" if re.search(r"[\u4e00-\u9fff]", formula or desc) else "en",
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--check", action="store_true", help="只打印统计，不写文件")
    args = ap.parse_args()

    c = QDataClient()
    rows = c.factor_list()
    print(f"factor_list 返回 {len(rows)} 行")

    out: dict[str, dict] = {}
    for r in rows:
        name = r.get("factor_name")
        if not name:
            continue
        rec = parse_desc(r.get("factor_desc", ""))
        rec["factor_type"] = r.get("factor_type", "")
        rec["asset_type"] = r.get("asset_type", "")
        out[name] = rec

    cur = {k: v for k, v in out.items() if "_old_" not in k}
    old = {k: v for k, v in out.items() if "_old_" in k}
    has_f = [k for k, v in cur.items() if v["formula"]]
    passth = [k for k, v in cur.items() if v["passthrough"]]
    no_f = [k for k, v in cur.items() if not v["formula"]]

    from collections import Counter
    print(f"因子总数        : {len(out)}（当前 {len(cur)} + 历史快照 {len(old)}）")
    print(f"含数学表达式    : {len(has_f)}/{len(cur)}")
    print(f"预计算直通      : {len(passth)}")
    print(f"无公式          : {len(no_f)} {no_f}")
    print("\n按分类:")
    for k, v in sorted(Counter(x["factor_type"] for x in cur.values()).items()):
        n_f = sum(1 for x in cur.values() if x["factor_type"] == k and x["formula"])
        print(f"  {k:10s} {v:3d} 个（有公式 {n_f}）")

    if args.check:
        return 0

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    OUT_PATH.write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"\n[extract] 已写出 {OUT_PATH}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
