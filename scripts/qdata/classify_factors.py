#!/usr/bin/env python
"""逐因子「横截面 vs 原始比值」的**实证**判别。

════════════════════════════════════════════════════════════════════════
为什么必须实证，不能只看公式文本
════════════════════════════════════════════════════════════════════════
`audit_formulas.py` 按**公式文本**是否出现 `CrossSectionalRank` / `Rank` 来判断因子
是否需要横截面校验。但实测证明**公式文本不可全信**：

* `de` 的公式文本含 `CrossSectionalRank`，但官方值实测是**原始比值**
  （min = −166.29、max = 412.61，不是 `rank/N`）。
* `roe_ttm` / `quality_composite` / `nl_size` 等 `passthrough` / 复合因子的公式文本
  **省略了**外层排名包装，但官方值确实是 `rank/N` 型。

误判的代价很大：对 `rank/N` 型因子用**绝对误差**判据，在 6 只样本股上会得到
**不可能真实成立的 EXACT**（本地只能得到 {1/6…1}，官方是 {1/N…1}），从而虚报成果。

════════════════════════════════════════════════════════════════════════
判别规则（取单日全市场官方值，检查分布签名）
════════════════════════════════════════════════════════════════════════
记 N = 当日返回行数，uniq = 互异值个数：

| 类型 | 判据 |
|---|---|
| `rank_N` | `min ≈ 1/N` 且 `max ≈ 1.0` 且 `uniq == N` → 升序排名 / N |
| `rank_minus1_N` | `min ≈ 0` 且 `max ≈ 1 − 1/N` 且 `uniq == N` → (rank−1)/N |
| `raw` | 其他（值是原始比值，绝对误差判据即可） |

用法::

    python scripts/qdata/classify_factors.py            # 用缓存
    python scripts/qdata/classify_factors.py --refresh  # 强制重新取数
"""
from __future__ import annotations

import argparse
import json
import pickle
import time
from pathlib import Path

import numpy as np
import pandas as pd

import sys
_SCRIPTS = Path(__file__).resolve().parents[1]
for p in (str(_SCRIPTS), str(_SCRIPTS / "qdata"), str(_SCRIPTS / "jqdata")):
    if p not in sys.path:
        sys.path.insert(0, p)

from qdata_env import QDataClient  # noqa: E402

OUT = Path("output/qdata_factor_repro")
CACHE = OUT / "cache"
FORMULAS = OUT / "factor_formulas.json"
RESULT = OUT / "FACTOR_CLASSIFICATION.json"

#: 判别容差（以 1/N 为单位）
TOL = 0.5


def classify(v: pd.Series) -> tuple[str, dict]:
    v = pd.to_numeric(v, errors="coerce").dropna()
    n, uniq = len(v), int(v.nunique())
    info = {"n": n, "uniq": uniq,
            "min": float(v.min()) if n else np.nan,
            "max": float(v.max()) if n else np.nan,
            "mean": float(v.mean()) if n else np.nan}
    if n < 10 or uniq == 0:
        return "no_data", info
    lo, hi = v.min(), v.max()
    step = 1.0 / n
    tol = TOL * step
    if abs(lo) < tol and abs(hi - (1.0 - step)) < tol and uniq == n:
        return "rank_minus1_N", info

    # ⚠️ 不能要求 ``uniq == n``：**并列会让互异值个数少于行数**
    #    （实测 `eps_ttm` N=5417 / uniq=3337、`eaa` N=5401 / uniq=4234，
    #     但 min≈1/N、max=1.0，仍是排名型）。
    # 改用**量化检验**：排名型的取值必然是 ``k/M`` 的形式，故
    #   ① ``M = round(1/lo)``（横截面参与排名的股票数）
    #   ② ``v * M`` 应几乎全为整数
    if abs(hi - 1.0) < tol and lo > 0:
        m = int(round(1.0 / lo))
        if m >= 10:
            frac = np.abs(v.values * m - np.round(v.values * m))
            if float((frac < 1e-6).mean()) > 0.999:
                info["implied_M"] = m
                info["quantized_frac"] = float((frac < 1e-6).mean())
                return ("rank_N" if uniq == n else "rank_N_ties"), info
    return "raw", info


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--trade-date", default="20260811")
    ap.add_argument("--refresh", action="store_true")
    args = ap.parse_args()

    CACHE.mkdir(parents=True, exist_ok=True)
    meta = json.load(open(FORMULAS, encoding="utf-8"))
    cur = sorted(k for k in meta if "_old_" not in k)
    pkl = CACHE / f"daily_cross_section_{args.trade_date}.pkl"

    if pkl.is_file() and not args.refresh:
        store = pickle.load(open(pkl, "rb"))
        print(f"  [cache] 命中 {pkl.name}（{len(store)} 个因子）")
    else:
        store = {}
    todo = [f for f in cur if f not in store]
    if todo:
        cli = QDataClient()
        print(f"  取 {len(todo)} 个因子的单日全市场值 @{args.trade_date} …")
        for i, f in enumerate(todo, 1):
            vals = None
            for attempt in range(5):
                try:
                    rows = cli.factor_value(factor_name=f, trade_date=args.trade_date)
                except Exception:  # noqa: BLE001
                    rows = []
                # ⚠️ 限流时接口返回 code=0/msg=ok 但 items=[] —— 空结果必须重试
                if rows:
                    vals = pd.to_numeric(pd.DataFrame(rows)["factor_value"], errors="coerce")
                    break
                time.sleep(2 + 3 * attempt)
            store[f] = vals if vals is not None else pd.Series(dtype=float)
            if i % 40 == 0:
                print(f"    …{i}/{len(todo)}")
        pickle.dump(store, open(pkl, "wb"))

    rec = {}
    for f in cur:
        kind, info = classify(store.get(f, pd.Series(dtype=float)))
        rec[f] = {"kind": kind, "factor_type": meta[f].get("factor_type", "?"), **info}

    # 与公式文本的结论对照
    status = {}
    if (OUT / "FACTOR_STATUS.json").is_file():
        status = json.load(open(OUT / "FACTOR_STATUS.json", encoding="utf-8"))
    n_flip_a = n_flip_b = 0
    for f, r in rec.items():
        txt_xs = bool(status.get(f, {}).get("has_cross_sectional"))
        emp_xs = r["kind"].startswith("rank")
        r["formula_text_cross_sectional"] = txt_xs
        r["empirical_cross_sectional"] = emp_xs
        if txt_xs and not emp_xs:
            r["note"] = "公式文本说含横截面，但官方值是原始比值 → 文本不可信，用绝对误差判据"
            n_flip_a += 1
        elif emp_xs and not txt_xs:
            r["note"] = "公式文本未体现横截面，但官方值是 rank/N → 必须用横截面判据"
            n_flip_b += 1
        else:
            r["note"] = ""

    RESULT.write_text(json.dumps(rec, ensure_ascii=False, indent=1), encoding="utf-8")

    kinds = pd.Series([r["kind"] for r in rec.values()]).value_counts().to_dict()
    print(f"\n判别结果（{len(rec)} 个因子）: {kinds}")
    print(f"与公式文本不一致：文本说横截面但实为 raw = {n_flip_a}；"
          f"文本未说但实为 rank = {n_flip_b}")
    print(f"\n产出: {RESULT}")
    print("\n实为 raw 但公式文本说含横截面的因子（这些应改用绝对误差判据）:")
    for f, r in rec.items():
        if r.get("note", "").startswith("公式文本说"):
            print(f"    {f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
