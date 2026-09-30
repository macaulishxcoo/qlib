#!/usr/bin/env python
"""抽取聚宽因子库（276 个因子）的计算公式，落盘为结构化 JSON。

    bash scripts/jqdata/run.sh scripts/jqdata/extract_factor_formulas.py
    bash scripts/jqdata/run.sh scripts/jqdata/extract_factor_formulas.py --check

为什么需要：JQData 文档里 `get_all_factors()` 只给 factor code / 中文名 / 分类，
**不含公式**；但官方「数据字典 - 聚宽因子」页（文档名 ``factor_values``，
`getContent` 接口，**免登录、不耗额度**）给出了每个因子的「计算方法」表格和
CNE5 风格描述因子的「定义 / 解释」正文。

产物：``.jqdata/docs/factor_library_formulas.json``（在 .gitignore 内）

    {
      "quick_ratio": {"name": "速动比率",
                      "formula": "速动比率=(流动资产合计-存货)/ 流动负债合计",
                      "category": "quality", "source": "table"},
      ...
    }

覆盖情况（2026-09-17 实测）：
- 276 / 276 因子全部有据可查
- 271 个有显式公式文本；5 个（VEMA5/10/12/26、MAWVAD）官方「计算方法」
  单元格本身为空，只有中文名即定义
- 256 个来自表格，20 个 CNE5 风格描述因子来自正文「解释」段

注意：公式是**官方文字描述**（部分为自然语言，如「过去252日超额收益的指数加权
标准差」），不是可直接执行的代码；技术类因子的公式多为通达信式伪代码
（``MA(CLOSE,M)``、``STD(CLOSE,M)``），可直接翻译实现。
"""

from __future__ import annotations

import argparse
import html
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _env import REPO_ROOT, auth, ensure_env  # noqa: E402

ensure_env()

DOC_NAME = "factor_values"
DOCS_DIR = REPO_ROOT / ".jqdata" / "docs"
HTML_PATH = DOCS_DIR / f"{DOC_NAME}.html"
TXT_PATH = DOCS_DIR / f"{DOC_NAME}.txt"
OUT_PATH = DOCS_DIR / "factor_library_formulas.json"

# 正文抽取时需排除的通用小标题，避免把「解释」当成因子中文名
_GENERIC = {"解释", "定义", "说明", "简介", "描述", "参数", "返回", "示例"}


def ensure_doc() -> None:
    """若本地缺少 factor_values 文档则抓取（免登录、不耗额度）。"""
    if HTML_PATH.is_file() and TXT_PATH.is_file():
        return
    from fetch_docs import fetch_doc
    import requests

    DOCS_DIR.mkdir(parents=True, exist_ok=True)
    s = requests.Session()
    s.headers.update({
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
        ),
        "Referer": "https://www.joinquant.com/help/api/help",
        "X-Requested-With": "XMLHttpRequest",
    })
    print(f"[extract] 本地缺 {DOC_NAME}.html，重新抓取…")
    fetch_doc(s, DOC_NAME)


def _cells(row_html: str) -> list[str]:
    out = []
    for m in re.finditer(r"<t([hd])([^>]*)>(.*?)</t\1>", row_html, re.S):
        txt = re.sub(r"<br\s*/?>", " ", m.group(3))
        txt = re.sub(r"<[^>]+>", "", txt)
        txt = re.sub(r"\s+", " ", html.unescape(txt)).strip()
        out.append(txt)
    return out


def parse_tables(html_text: str) -> dict[str, dict]:
    """解析因子表格。

    表头有两种：``因子 code / 因子名称 / 计算方法``（可直接实现）与
    ``因子 code / 因子名称 / 简介``（style / style_pro，只有文字说明，
    真正的加权定义在正文「定义：」段，由 :func:`parse_definitions` 补）。
    """
    rec: dict[str, dict] = {}
    for ti, tb in enumerate(re.findall(r"<table.*?</table>", html_text, re.S)):
        header = None
        for row in re.findall(r"<tr.*?</tr>", tb, re.S):
            vals = _cells(row)
            if len(vals) < 3:
                continue
            if vals[0] == "因子 code":
                header = vals[2]
                continue
            if header is None or vals[0] == "":
                continue
            code, name, third = vals[0], vals[1], vals[2]
            # 行业因子 code 形如 A01 / HY007 / 801780，也一并收
            if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*|\d{4,6}|[A-Z]{1,3}\d{2,3}", code):
                continue
            if header == "计算方法":
                rec[code] = {"name": name, "formula": third, "description": "",
                             "source": "table", "table": ti}
            else:  # 简介：只有说明，公式待正文补
                rec[code] = {"name": name, "formula": "", "description": third,
                             "source": "table-desc", "table": ti}
    return rec


def parse_definitions(txt: str, codes: list[str]) -> dict[str, dict]:
    """抽取正文「<中文名> <code>  \\n\\n 定义：<加权式>」段（CNE5 风格合成因子）。"""
    out: dict[str, dict] = {}
    for m in re.finditer(r"^(.{2,20}?)\s+([A-Za-z_][A-Za-z0-9_]*)\s*\n+\s*定义：(.*?)$", txt, re.M):
        label, code, formula = m.group(1).strip(), m.group(2), m.group(3).strip()
        if code in codes:
            out[code] = {"name": label, "formula": formula, "source": "prose-definition"}
    return out


def parse_prose(txt: str, codes: list[str], intro: dict[str, str]) -> tuple[dict[str, dict], list[str]]:
    """从正文「中文名 code：解释」段补 CNE5 风格描述因子。

    个别条目（如 raw_beta）正文里没有中文名前缀，行首是「解释」等小标题；
    此时仍保留公式，名称回退到因子库自带的 factor_intro。
    """
    rec: dict[str, dict] = {}
    for code in codes:
        m = re.search(rf"^(.{{2,20}}?)\s+{re.escape(code)}：(.*)$", txt, re.M)
        if not m:
            continue
        label = m.group(1).strip()
        rec[code] = {
            "name": intro.get(code, label) if label in _GENERIC else label,
            "formula": m.group(2).strip(),
            "source": "prose",
        }
    missing = [c for c in codes if c not in rec]
    return rec, missing


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--check", action="store_true",
                    help="只校验覆盖率，不写文件（需联网登录取因子清单）")
    args = ap.parse_args()

    ensure_doc()
    html_text = HTML_PATH.read_text(encoding="utf-8")
    txt = TXT_PATH.read_text(encoding="utf-8")

    auth(verbose=False)
    from jqdatasdk import get_all_factors

    fac = get_all_factors()
    codes = list(fac["factor"])
    cat = dict(zip(fac["factor"], fac["category"]))
    intro = dict(zip(fac["factor"], fac["factor_intro"]))

    rec = parse_tables(html_text)

    # style / style_pro 的加权定义在正文「定义：」段
    defs = parse_definitions(txt, [c for c in codes if c in rec and not rec[c]["formula"]])
    for c, v in defs.items():
        rec[c]["formula"] = v["formula"]
        rec[c]["source"] = v["source"]
        if not rec[c]["name"]:
            rec[c]["name"] = v["name"]

    # 表格里完全没有的 20 个 CNE5 描述因子，从正文「中文名 code：解释」段补
    prose, _ = parse_prose(txt, [c for c in codes if c not in rec], intro)
    for c, v in prose.items():
        rec[c] = {**v, "description": ""}

    # 兜底：用因子库自带 factor_intro 填充名称
    for c in codes:
        if c not in rec:
            rec[c] = {"name": intro.get(c, ""), "formula": "", "description": "",
                      "source": "intro-only"}
        rec[c].setdefault("description", "")
        rec[c]["category"] = cat.get(c, "")

    covered = len(set(codes) & set(rec))
    no_formula = [c for c in codes if not rec[c]["formula"]]

    print(f"因子库总数      : {len(codes)}")
    print(f"公式文件条数    : {len(rec)}")
    print(f"覆盖            : {covered}/{len(codes)}")
    from collections import Counter
    for src, n in Counter(rec[c]["source"] for c in codes).most_common():
        print(f"  {src:18s}: {n}")
    print(f"有显式公式文本  : {len(codes) - len(no_formula)}")
    print(f"仅名称/说明     : {len(no_formula)} {no_formula}")

    if args.check:
        return 0

    OUT_PATH.write_text(json.dumps(rec, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"\n[extract] 已写出 {OUT_PATH}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
