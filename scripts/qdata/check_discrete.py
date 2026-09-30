#!/usr/bin/env python
"""离散输出型因子的「分档归属一致率」判定（离线，复用已缓存值）。

════════════════════════════════════════════════════════════════════════
为什么单独一套判据
════════════════════════════════════════════════════════════════════════
Alpha101 有 11 个因子是**离散输出**（官方值只有 2~8 档）：
`alpha101_21/27/62/65/68` 仅 ±1 两档；`alpha101_58` 6 档、`alpha101_59` 8 档、
`alpha101_1` 5 档、`alpha101_7` 120 档。

对这类因子：
* **Spearman 不适合** —— 3~10% 的档位跳变会把相关系数严重拉低；
* **逐值一致率也不适合** —— 档位值 = `rank_max/N`，块大小差几只就会让整块的值在
  第 4 位小数上全变。实测 `alpha101_1` 官方/本地 5 档值只差 4e-4，但逐值一致率
  仅 **6.5%**，完全掩盖了它 Spearman 0.9982 的事实；
* **正确做法 = 分档归属一致率**：两侧各自 dense-rank 成档位序号再比。

用法::

    python scripts/qdata/check_discrete.py
"""
from __future__ import annotations

import pickle
import sys
from pathlib import Path

import numpy as np
import pandas as pd

_SCRIPTS = Path(__file__).resolve().parents[1]
for p in (str(_SCRIPTS), str(_SCRIPTS / "qdata"), str(_SCRIPTS / "jqdata")):
    if p not in sys.path:
        sys.path.insert(0, p)

from xs_compare import compare_agreement  # noqa: E402

CACHE = Path("output/qdata_factor_repro/cache")
OUT = Path("output/qdata_factor_repro")

#: 「离散输出型」判据：官方值的**并列率** ``1 - uniq/N`` ≥ 该阈值即视为离散。
#: 用相对判据而非绝对档数 —— `alpha101_7` 有 120 档，但 N≈5522 ⇒ 并列率 97.8%，
#: 平均每档 46 只，仍是典型的分档输出（其分档一致率 0.9962，本就该判通过）。
DISCRETE_TIE_RATIO = 0.90
#: 兜底清单（缓存里的已知离散因子；alpha101_64 公式含未定义 Delta_Mix，无本地值）
KNOWN_DISCRETE = ["alpha101_1", "alpha101_7", "alpha101_21", "alpha101_27",
                  "alpha101_58", "alpha101_59", "alpha101_61", "alpha101_62",
                  "alpha101_65", "alpha101_68"]


def load_local() -> dict[str, pd.DataFrame]:
    """合并所有 ``alpha101_local_*.pkl``（每个是 ``(dict[factor -> DataFrame], errors)``）。"""
    out: dict[str, pd.DataFrame] = {}
    for p in sorted(CACHE.glob("alpha101_local_*.pkl")):
        try:
            obj = pickle.load(open(p, "rb"))
        except Exception:  # noqa: BLE001
            continue
        loc = obj[0] if isinstance(obj, tuple) else obj
        if isinstance(loc, dict):
            out.update(loc)
    return out


def official_day(factor: str, date: str) -> pd.Series | None:
    """``official_day`` 缓存是 ``{ts_code: value}`` 字典，需转成 Series。"""
    p = CACHE / "official_day" / f"{factor}__{date}.pkl"
    if not p.is_file():
        return None
    try:
        d = pd.read_pickle(p)
    except Exception:  # noqa: BLE001
        return None
    return pd.Series(d) if isinstance(d, dict) else d


def build_official(local: dict[str, pd.DataFrame], factors: list[str]) -> dict[str, pd.DataFrame]:
    off: dict[str, pd.DataFrame] = {}
    for f in factors:
        if f not in local:
            continue
        cols = {}
        for t in local[f].index:
            s = official_day(f, t.strftime("%Y%m%d"))
            if s is not None and len(s):
                cols[t] = s
        if cols:
            off[f] = pd.DataFrame(cols).T.sort_index()
    return off


def main() -> int:
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--factors", nargs="*", default=None)
    ap.add_argument("--all", action="store_true",
                    help="不止用兜底清单，还自动纳入官方档位数 <= 阈值的因子")
    args = ap.parse_args()

    local_all = load_local()
    print(f"本地值缓存：{len(local_all)} 个因子")

    facs = list(args.factors) if args.factors else list(KNOWN_DISCRETE)
    if args.all:
        facs = sorted(local_all)
    facs = [f for f in facs if f in local_all]
    official = build_official(local_all, facs)

    # 自动识别离散因子
    lvl = {}
    for f in facs:
        o = official.get(f)
        if o is not None and not o.empty:
            lvl[f] = int(np.nanmedian([o.loc[t].nunique() for t in o.index]))
    tie = {}
    for f in facs:
        o = official.get(f)
        if o is not None and not o.empty:
            t0 = o.index[0]
            v = pd.to_numeric(o.loc[t0], errors="coerce").dropna()
            tie[f] = 1.0 - (v.nunique() / max(len(v), 1))
    if args.all or not args.factors:
        facs = [f for f in facs if tie.get(f, 0.0) >= DISCRETE_TIE_RATIO]
    print(f"判定 {len(facs)} 个离散因子（官方档位数中位：{ {f: lvl.get(f) for f in facs} }）")

    # compare_agreement 需要 dict[factor -> DataFrame(index=日期, columns=代码)]
    d = compare_agreement("qdata_alpha101_discrete", local_all, official, facs)
    # 附带 Spearman 供对照
    from xs_compare import compare_xs
    sp = compare_xs("qdata_alpha101_discrete", local_all, official, facs)
    d = d.merge(sp[["factor", "verdict_xs", "spearman_med"]], on="factor", how="left")
    d["n_levels"] = d["factor"].map(lvl)
    d["tie_ratio"] = d["factor"].map(tie).round(4)

    # ⚠️ 两个指标对**并列型输出**各有假阴性，必须都报、取较优者并标注来源：
    #   * `alpha101_1/21/27/7`：Spearman 低估（档位跳变）→ 一致率才对
    #   * `alpha101_43`(86档)/`alpha101_46`(412档)：一致率是**假阴性**
    #     （Spearman 0.999912 / 0.999997 = EXACT，但块边界差几只 ⇒ 逐值全不等）
    #   理论上：一致率衡量"档位归属"（适合粗档），Spearman 衡量"次序"（适合细档）。
    _ord = {"EXACT": 0, "GOOD": 1, "APPROX": 2, "FAIL": 3, "NO_DATA": 4}
    va = d["verdict_agree"].map(_ord).fillna(9)
    vx = d["verdict_xs"].map(_ord).fillna(9)
    d["verdict_best"] = np.where(va <= vx, d["verdict_agree"], d["verdict_xs"])
    d["judged_by"] = np.where(va <= vx, "分档一致率", "横截面Spearman")

    cols = ["factor", "verdict_best", "judged_by", "verdict_agree", "agree_med",
            "verdict_xs", "spearman_med", "n_levels", "tie_ratio", "n_days"]
    with pd.option_context("display.width", 200):
        print(d[cols].to_string(index=False, float_format=lambda x: f"{x:.6f}"))

    out = OUT / "alpha101_discrete_agreement.csv"
    d.to_csv(out, index=False)
    n_b = int(d["verdict_best"].isin(["EXACT", "GOOD"]).sum())
    n_a = int(d["verdict_agree"].isin(["EXACT", "GOOD"]).sum())
    n_s = int(d["verdict_xs"].isin(["EXACT", "GOOD"]).sum())
    print(f"\n通过数：**取较优者 {n_b}/{len(d)}**（单用分档一致率 {n_a}，单用 Spearman {n_s}）")
    print(f"产出: {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
