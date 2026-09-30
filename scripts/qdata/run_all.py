#!/usr/bin/env python
"""qdata 因子复现 —— 一键编排入口。

按顺序跑完全部批次脚本，再重跑公式审计与汇总，产出统一报告。

════════════════════════════════════════════════════════════════════════
为什么必须**顺序**跑
════════════════════════════════════════════════════════════════════════
所有批次都要调用 qdata ``factor_value``，而配额是 **QPS 30 / QPM 200**（全局共享）。
并行跑会互相挤爆配额、触发 429 与静默截断，得到不可信的结论。故本脚本串行执行。

各批次脚本自带 ``output/qdata_factor_repro/cache/`` 缓存，重复运行会命中缓存、快速返回。

用法::

    python scripts/qdata/run_all.py            # 只列出将执行的步骤（dry-run）
    python scripts/qdata/run_all.py --run      # 真正执行
    python scripts/qdata/run_all.py --run --only repro_batch2 repro_quality
"""
from __future__ import annotations

import argparse
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
QD = ROOT / "scripts" / "qdata"
OUT = ROOT / "output" / "qdata_factor_repro"

#: 本项目约定的解释器（tushare / pandas 版本正确的那个）；
#: 不存在时回退到当前解释器。
QLIB_PY = Path("/home/xiaocong/anaconda3/envs/qlib/bin/python")
PY = str(QLIB_PY) if QLIB_PY.is_file() else sys.executable

#: 批次脚本 → 说明。按「成本从低到高」排序，先跑便宜的把框架跑通。
BATCHES: list[tuple[str, str]] = [
    ("repro.py", "批次一：价量类 15 个因子（后复权价 / MA / EMA / 区间收益 / 波动 / 夏普）"),
    ("repro_batch2.py", "批次二：Momentum + Reversal + Size + Value（纯时序部分）"),
    ("repro_value.py", "批次二补充：Value 族需财报科目的因子（book_to_market）"),
    ("repro_value_xs.py", "批次六：Value 族剩余 8 条（2024 窗口，用 full/normalized 全列镜像）"),
    ("repro_liquidity_risk.py", "批次三：Liquidity + Risk（全部纯时序，含指数相关因子）"),
    ("repro_quality.py", "批次四：Quality + Growth（财报类，横截面因子用 xs_compare 判据）"),
    ("repro_quality_xs.py", "批次四（横截面部分）：Quality/Growth 的 CrossSectionalRank 因子"),
    ("repro_alpha101.py", "批次五：Alpha101（全市场横截面，须先有 ts_market/xs_ops）"),
]

#: 收尾步骤：静态审计（不调 API）→ 汇总
FINALIZE: list[tuple[str, str]] = [
    ("audit_formulas.py", "公式静态审计：横截面扫描 / 参数清单 / 直通因子 / 跨体系对照"),
    ("run_factor_summary.py", "全批次汇总：总账 / 按族通过率 / 未通过归因 / 覆盖清单"),
]


def _run_one(script: str, desc: str, timeout: int) -> tuple[bool, float, str]:
    path = QD / script
    if not path.is_file():
        return False, 0.0, f"脚本不存在：{path}"
    print(f"\n{'=' * 72}\n▶ {script} —— {desc}\n{'=' * 72}", flush=True)
    t0 = time.time()
    try:
        p = subprocess.run([PY, str(path)], cwd=ROOT, timeout=timeout,
                           capture_output=True, text=True)
    except subprocess.TimeoutExpired:
        return False, time.time() - t0, f"超时（>{timeout}s）"
    dt = time.time() - t0
    tail = "\n".join((p.stdout or "").rstrip().splitlines()[-40:])
    if tail:
        print(tail, flush=True)
    if p.returncode != 0:
        err = "\n".join((p.stderr or "").rstrip().splitlines()[-15:])
        print(f"[stderr]\n{err}", flush=True)
        return False, dt, f"退出码 {p.returncode}"
    return True, dt, "OK"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--run", action="store_true", help="真正执行（默认只列出步骤）")
    ap.add_argument("--only", nargs="*", default=None,
                    help="只跑指定的脚本名（可含或不含 .py）")
    ap.add_argument("--timeout", type=int, default=3600, help="单个脚本超时秒数")
    ap.add_argument("--skip-batches", action="store_true", help="只跑收尾步骤")
    args = ap.parse_args()

    only = {s if s.endswith(".py") else s + ".py" for s in args.only} if args.only else None
    plan = ([] if args.skip_batches else BATCHES) + FINALIZE
    if only:
        plan = [(s, d) for s, d in plan if s in only]

    if not args.run:
        print("将要执行的步骤（dry-run；加 --run 真正执行）：\n")
        for s, d in plan:
            mark = "✅" if (QD / s).is_file() else "❌ 缺失"
            print(f"  {mark}  {s:28s} {d}")
        print(f"\n解释器: {PY}")
        print(f"输出目录: {OUT}")
        print("\n⚠️ 所有批次必须**顺序**执行：qdata 配额 QPS 30 / QPM 200 是全局共享的。")
        return 0

    results = []
    for s, d in plan:
        ok, dt, msg = _run_one(s, d, args.timeout)
        results.append((s, ok, dt, msg))

    print(f"\n\n{'=' * 72}\n编排结果\n{'=' * 72}")
    print(f"{'脚本':<30s}{'状态':<8s}{'耗时':>9s}  说明")
    for s, ok, dt, msg in results:
        print(f"{s:<30s}{'✅ OK' if ok else '❌ 失败':<8s}{dt:>8.1f}s  {msg}")
    n_ok = sum(1 for _, ok, _, _ in results if ok)
    print(f"\n通过 {n_ok}/{len(results)}")

    summary = OUT / "SUMMARY.md"
    if summary.is_file():
        print(f"汇总报告: {summary}")
    return 0 if n_ok == len(results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
