#!/usr/bin/env python
"""抓取 JoinQuant 帮助文档正文，落盘为离线参考。

    bash scripts/jqdata/run.sh scripts/jqdata/fetch_docs.py            # 默认抓取关键几篇
    bash scripts/jqdata/run.sh scripts/jqdata/fetch_docs.py --list     # 只看文档树

为什么需要：`www.joinquant.com/help/api/help` 是 SPA（GET 只返回 7KB 空壳），
但真正的正文由两个接口提供，**不需要登录、不需要额度**：

    GET /help/api/getHelpDocTree?name=<doc>   -> 目录树（JSON）
    GET /help/api/getContent?name=<doc>       -> 正文 HTML（JSON.data）

抓下来的公式文档是**重新实现付费模块**（技术指标 101 个、Alpha191）的依据。

产物写在 ``.jqdata/docs/``（已在 .gitignore 中，含站点内容，不入库）。
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _env import REPO_ROOT, ensure_env  # noqa: E402

ensure_env()

import requests  # noqa: E402

BASE = "https://www.joinquant.com/help/api"
OUT_DIR = REPO_ROOT / ".jqdata" / "docs"
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
    ),
    "Referer": "https://www.joinquant.com/help/api/help",
    "X-Requested-With": "XMLHttpRequest",
}
# 与研究相关的文档
DEFAULT_DOCS = ["technicalanalysis", "alpha191", "alpha101", "JQDatadoc"]


def _get(session: requests.Session, endpoint: str, name: str) -> dict:
    r = session.get(f"{BASE}/{endpoint}", params={"name": name}, timeout=60)
    r.raise_for_status()
    return r.json()


def _strip_tags(html: str) -> str:
    txt = re.sub(r"<br\s*/?>", "\n", html)
    txt = re.sub(r"</(p|h[1-6]|li|tr|div)>", "\n", txt)
    txt = re.sub(r"<[^>]+>", "", txt)
    txt = txt.replace("&nbsp;", " ").replace("&lt;", "<").replace("&gt;", ">")
    txt = txt.replace("&amp;", "&").replace("&quot;", '"').replace("&#39;", "'")
    return re.sub(r"\n{3,}", "\n\n", txt).strip()


def fetch_doc(session: requests.Session, name: str) -> dict:
    tree = _get(session, "getHelpDocTree", name)
    content = _get(session, "getContent", name)
    html = content.get("data", "")
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    (OUT_DIR / f"{name}.html").write_text(html, encoding="utf-8")
    txt = _strip_tags(html)
    (OUT_DIR / f"{name}.txt").write_text(txt, encoding="utf-8")
    (OUT_DIR / f"{name}.tree.json").write_text(
        json.dumps(tree, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    ids = re.findall(r'id="([^"]+)"', html)
    formulas = txt.count("因子公式")
    print(
        f"  {name:18s} html={len(html):>9,} chars  txt={len(txt):>9,} chars  "
        f"小节={len(ids):>4}  '因子公式'={formulas:>4}"
    )
    return {"name": name, "sections": len(ids), "formulas": formulas}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--docs", nargs="*", default=DEFAULT_DOCS)
    ap.add_argument("--list", action="store_true", help="只打印文档树")
    args = ap.parse_args()

    s = requests.Session()
    s.headers.update(HEADERS)
    print(f"输出目录: {OUT_DIR}")
    if args.list:
        for name in args.docs:
            tree = _get(s, "getHelpDocTree", name)
            items = tree.get("data", {}).get("tree", [])
            print(f"\n=== {name} ({len(items)} 项) ===")
            for it in items[:40]:
                print(f"  [{it.get('level')}] {re.sub(r'<[^>]+>', '', it.get('title', ''))}")
            time.sleep(0.3)
        return 0

    summary = []
    for name in args.docs:
        summary.append(fetch_doc(s, name))
        time.sleep(0.3)

    print("\n[fetch_docs] 完成")
    for r in summary:
        print(f"  {r['name']:18s} 小节 {r['sections']:>4}  公式 {r['formulas']:>4}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
