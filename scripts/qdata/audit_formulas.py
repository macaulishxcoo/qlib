#!/usr/bin/env python
"""qdata 因子公式静态审计（不调用任何 API）。

产出三份分析，写入 ``output/qdata_factor_repro/FORMULA_AUDIT.md``：

1. **横截面依赖扫描** —— 哪些因子含 ``Rank`` / ``Scale`` / ``IndNeutralize`` /
   ``CrossSectionalRank`` 等横截面算子。这些因子**必须在全市场股票池上校验**，
   用小样本股验证会必然 FAIL（与实现正确性无关）。见 CONVENTIONS §3.1。
2. **参数化因子清单** —— ``params`` 非空的因子及其默认参数。
3. **与聚宽体系交叉验证** —— 同名因子的公式对照。见 CONVENTIONS §3.3。

用法::

    python scripts/qdata/audit_formulas.py
"""
from __future__ import annotations

import collections
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "output" / "qdata_factor_repro"
QDATA_JSON = OUT / "factor_formulas.json"
JQ_JSON = ROOT / ".jqdata" / "docs" / "factor_library_formulas.json"

#: 横截面算子模式。``CrossSectionalRank`` 必须排在 ``Rank`` 之前匹配。
XS_PATTERN = re.compile(
    r"(CrossSectionalRank|CrossSectional\w*|IndNeutralize|Scale|Rank)\s*\(", re.I)
#: 一些算子名是 ``Rank`` 的子串（如 ``Ts_Rank``），需排除。
XS_EXCLUDE = re.compile(r"Ts_Rank", re.I)

FAMILY_ORDER = ["Alpha101", "Quality", "Liquidity", "Risk",
                "Momentum", "Growth", "Value", "Reversal", "Size"]


def scan_cross_sectional(cur: dict) -> tuple[dict[str, list[str]], set[str]]:
    canonical = {"crosssectionalrank": "CrossSectionalRank", "indneutralize": "IndNeutralize",
                 "scale": "Scale", "rank": "Rank"}
    hits: dict[str, list[str]] = collections.defaultdict(list)
    for name, v in cur.items():
        text = XS_EXCLUDE.sub("", v.get("formula", ""))
        for m in {x.group(1) for x in XS_PATTERN.finditer(text)}:
            hits[canonical.get(m.lower(), m)].append(name)
    involved = {n for names in hits.values() for n in names}
    return dict(hits), involved


def main() -> int:
    meta = json.load(open(QDATA_JSON, encoding="utf-8"))
    cur = {k: v for k, v in meta.items() if "_old_" not in k}
    old = {k: v for k, v in meta.items() if "_old_" in k}

    hits, involved = scan_cross_sectional(cur)
    fam_total = collections.Counter(v.get("factor_type", "?") for v in cur.values())
    fam_xs = collections.Counter(cur[k].get("factor_type", "?") for k in involved)

    L: list[str] = []
    L.append("# qdata 因子公式静态审计\n")
    L.append(f"> 由 `scripts/qdata/audit_formulas.py` 生成（不调用 API）。")
    L.append(f"> 当前因子 **{len(cur)}** 条；历史快照 `_old_` **{len(old)}** 条。\n")

    # ---------------- 1. 横截面 ----------------
    L.append("## 1. 横截面依赖扫描\n")
    L.append(f"**{len(involved)}/{len(cur)} 条（{len(involved)/len(cur):.0%}）含横截面算子，"
             f"必须在全市场股票池上校验。**\n")
    L.append("| 族 | 含横截面 | 总数 |")
    L.append("|---|---|---|")
    for fam in FAMILY_ORDER:
        if fam_total.get(fam):
            L.append(f"| {fam} | {fam_xs.get(fam, 0)} | {fam_total[fam]} |")
    L.append("")
    L.append("### 按算子分组\n")
    L.append("| 算子 | 条数 | 因子 |")
    L.append("|---|---|---|")
    for op, names in sorted(hits.items(), key=lambda x: -len(x[1])):
        L.append(f"| `{op}` | {len(names)} | " + "、".join(f"`{n}`" for n in sorted(names)) + " |")
    L.append("")
    L.append("> `CrossSectionalRank` 不只出现在 Alpha101：Quality/Growth/Value 大量"
             "在原始比值外额外套一层全市场排名。用小样本股验证这些因子**必然 FAIL**，"
             "与实现正确性无关 —— 应剥壳后做秩相关检验，或建全市场面板。\n")

    # ---------------- 2. 参数化因子 ----------------
    param = {k: (v.get("params") or {}) for k, v in cur.items() if v.get("params")}
    L.append("## 2. 参数化因子\n")
    L.append(f"共 **{len(param)}** 条带 `params`。\n")
    L.append("| 因子 | 族 | 参数 |")
    L.append("|---|---|---|")
    for k in sorted(param):
        ps = "；".join(f"`{a}`: {b}" for a, b in param[k].items())
        L.append(f"| `{k}` | {cur[k].get('factor_type','?')} | {ps} |")
    L.append("")

    # ---------------- 3. 直通因子 ----------------
    pt = sorted(k for k, v in cur.items() if v.get("passthrough"))
    L.append("## 3. 直通（passthrough）因子\n")
    L.append(f"共 **{len(pt)}** 条，qdata 直接用预计算的 `lake.financial_derivative.*` 字段，"
             f"预计**结构性不可复现**。\n")
    L.append("| 因子 | 族 | 文档公式 |")
    L.append("|---|---|---|")
    for k in pt:
        f = cur[k].get("formula", "").replace("\n", " ")[:90]
        L.append(f"| `{k}` | {cur[k].get('factor_type','?')} | {f} |")
    L.append("")

    # ---------------- 4. 与聚宽交叉验证 ----------------
    L.append("## 4. 与聚宽体系交叉验证\n")
    if not JQ_JSON.is_file():
        L.append(f"⚠️ 未找到 `{JQ_JSON}`，跳过。\n")
    else:
        jq = json.load(open(JQ_JSON, encoding="utf-8"))
        ov = sorted(set(cur) & set(jq))
        L.append(f"qdata **{len(cur)}** 条 / 聚宽 **{len(jq)}** 条 / **同名仅 {len(ov)} 条**。\n")
        L.append("| 因子 | qdata 族 | qdata 公式 | 聚宽类别 | 聚宽公式 |")
        L.append("|---|---|---|---|---|")
        for k in ov:
            fq = cur[k].get("formula", "").replace("\n", " ")[:80]
            fj = (jq[k].get("formula") or "").replace("\n", " ")[:60]
            L.append(f"| `{k}` | {cur[k].get('factor_type','?')} | {fq} | "
                     f"{jq[k].get('category','?')} | {fj} |")
        L.append("")
        L.append("**结论：同名不代表同口径** —— 不可跨体系套用实现或符号。"
                 "典型：`size` 在 qdata 是 `−log(市值)`（负对数，值越小市值越大），"
                 "聚宽是 `natural_log_of_market_cap`（正对数），**符号相反**；"
                 "`roa_ttm`/`eps_ttm` 在 qdata 额外套了 `CrossSectionalRank`。\n")

    out = OUT / "FORMULA_AUDIT.md"
    out.write_text("\n".join(L), encoding="utf-8")

    # ---------------- 5. 逐因子状态登记表 ----------------
    # 供 run_factor_summary.py 合并，实现交付项 ④「未达标与不可复现因子逐条归档原因」。
    registry = {}
    for k, v in sorted(cur.items()):
        registry[k] = {
            "factor_type": v.get("factor_type", "?"),
            # 该因子应当用哪套判据（见 CONVENTIONS §3.4）
            "criterion": "横截面Spearman" if k in involved else "绝对误差",
            "has_cross_sectional": k in involved,
            "passthrough": bool(v.get("passthrough")),
            "params": v.get("params") or {},
            "formula": (v.get("formula") or "").strip(),
            "archived_reason": (
                "直通候选（需实测确认）：qdata 文档给了公式，但实际直接取预计算字段 "
                "lake.financial_derivative.*，其派生口径可能与公式不同。"
                "应先实测比对；若确认无法还原，再归档为结构性不可复现。"
                if v.get("passthrough") else ""
            ),
        }
    (OUT / "FACTOR_STATUS.json").write_text(
        json.dumps(registry, ensure_ascii=False, indent=1), encoding="utf-8")

    print(f"当前因子 {len(cur)} 条（另有 _old_ {len(old)} 条）")
    print(f"含横截面算子: {len(involved)}/{len(cur)} ({len(involved)/len(cur):.0%})")
    for op, names in sorted(hits.items(), key=lambda x: -len(x[1])):
        print(f"   {op:20s} {len(names):3d}")
    print(f"参数化因子: {len(param)} | 直通因子: {len(pt)}")
    print(f"\n产出: {out}\n      {OUT / 'FACTOR_STATUS.json'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
