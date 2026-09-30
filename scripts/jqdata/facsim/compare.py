#!/usr/bin/env python
"""比对引擎：本地复现 vs 官方 ``get_factor_values``，产出精度报告。

判定口径：**相对量级**误差，避免量纲与截面离散度干扰。

    rel = max_abs_err / mean(|官方值|)

以「官方值自身的平均量级」为分母，而不是截面标准差 —— 后者会被因子本身的
离散度放大或缩小（因子几乎不变时 std→0，误判为 FAIL）。

    EXACT   rel <= 1e-9   逐位一致
    GOOD    rel <= 1e-4   复现到 4 位有效数字，可视为精确复现
    APPROX  rel <= 1e-2   形状正确但口径有残差（需在报告 note 说明原因）
    FAIL    其他

三个判据并存，用途不同：
    verdict        (maxerr)  —— 「能否逐位复现对方流水线」；对尾部极值最敏感
    verdict_robust (p99)     —— 中间口径
    verdict_med    (中位)    —— 「这个因子实际能不能用」；**推荐作为可用性主判据**
maxerr 会被极少数观测（如某只低价股某天）完全支配。
    NO_DATA 无重叠样本（未实现 / 窗口不足 / 官方全 NaN）
"""
from __future__ import annotations

from dataclasses import asdict, dataclass

import numpy as np
import pandas as pd

EXACT, GOOD, APPROX, FAIL, NO_DATA = "EXACT", "GOOD", "APPROX", "FAIL", "NO_DATA"


@dataclass
class FactorReport:
    factor: str
    family: str
    verdict: str
    n_overlap: int          # 本地与官方都有值的样本数
    n_official: int         # 官方有值的样本数
    coverage: float         # n_overlap / n_official
    max_abs_err: float
    p99_abs_err: float
    mean_abs_err: float
    rel_err: float
    corr: float
    official_mag: float     # mean(|官方值|)
    verdict_robust: str = ""   # 基于 p99 误差的稳健判定（见下）
    p99_rel_err: float = float("nan")
    med_rel_err: float = float("nan")   # **中位**误差/量级 —— 实际可用性主判据
    mean_rel_err: float = float("nan")  # 平均误差/量级（含尾部）
    verdict_med: str = ""               # 基于中位误差的判定
    note: str = ""

    def as_row(self) -> dict:
        return asdict(self)


def _verdict(rel: float, n_overlap: int) -> str:
    if n_overlap == 0:
        return NO_DATA
    if rel <= 1e-9:
        return EXACT
    if rel <= 1e-4:
        return GOOD
    if rel <= 1e-2:
        return APPROX
    return FAIL


def compare_one(family: str, code: str, local: pd.DataFrame | None,
                official: pd.DataFrame | None) -> FactorReport:
    nan_row = dict(max_abs_err=np.nan, p99_abs_err=np.nan, mean_abs_err=np.nan,
                   rel_err=np.nan, corr=np.nan, official_mag=np.nan)
    if official is None or official.empty:
        return FactorReport(code, family, NO_DATA, 0, 0, 0.0, note="官方无数据", **nan_row)
    off = official.copy()
    off.index = pd.to_datetime(off.index)
    if local is None or local.empty:
        n_off = int(off.notna().sum().sum())
        return FactorReport(code, family, NO_DATA, 0, n_off, 0.0,
                            note="本地未实现", **nan_row)

    loc = local.copy()
    loc.index = pd.to_datetime(loc.index)
    # 对齐到相同 index/columns
    idx = loc.index.intersection(off.index)
    cols = loc.columns.intersection(off.columns)
    if len(idx) == 0 or len(cols) == 0:
        return FactorReport(code, family, NO_DATA, 0, int(off.notna().sum().sum()), 0.0,
                            note="无重叠日期/标的", **nan_row)
    l = loc.loc[idx, cols]
    o = off.loc[idx, cols]

    both = l.notna() & o.notna()
    n_overlap = int(both.sum().sum())
    n_official = int(o.notna().sum().sum())

    if n_overlap == 0:
        return FactorReport(code, family, NO_DATA, 0, n_official, 0.0,
                            note="官方与本地无共同有效值", **nan_row)

    diff = (l - o).abs().where(both)
    flat = diff.stack().dropna()
    max_err = float(flat.max())
    p99_err = float(flat.quantile(0.99))
    med_err = float(flat.median())
    mean_err = float(flat.mean())

    mag = float(o.where(both).stack().abs().mean())
    rel = max_err / mag if mag and np.isfinite(mag) and mag > 0 else np.nan

    ll = l.where(both).stack()
    oo = o.where(both).stack()
    corr = float(np.corrcoef(ll.values, oo.values)[0, 1]) if n_overlap > 2 else np.nan

    # 稳健判定：以 p99 误差为准。maxerr 会被个别离群标的支配
    # （实测：arron_* 中位误差 7e-15、98% 标的精确，却因 3~9 只离群而判 FAIL）
    p99_rel = p99_err / mag if mag and np.isfinite(mag) and mag > 0 else np.nan
    # 中位口径：maxerr 会被极少数观测支配（例如某只低价股某天），
    # 对「这个因子能不能用」这个问题，中位误差才是有代表性的统计量。
    med_rel = med_err / mag if mag and np.isfinite(mag) and mag > 0 else np.nan

    coverage = n_overlap / n_official if n_official else 0.0
    note = ""
    if coverage < 0.95 and n_official:
        note = f"覆盖率不足（官方 {n_official} / 重叠 {n_overlap}）"
    return FactorReport(code, family, _verdict(rel, n_overlap), n_overlap, n_official,
                        coverage, max_err, p99_err, mean_err, rel, corr, mag,
                        verdict_robust=_verdict(p99_rel, n_overlap),
                        p99_rel_err=p99_rel,
                        med_rel_err=med_rel, verdict_med=_verdict(med_rel, n_overlap),
                        mean_rel_err=(mean_err / mag if mag and mag > 0 else np.nan),
                        note=note)


def compare_family(family: str, local: dict[str, pd.DataFrame],
                   official: dict[str, pd.DataFrame],
                   expected: list[str]) -> pd.DataFrame:
    """对族内每个预期因子产出报告，返回按精度排序的 DataFrame。"""
    rows = []
    for code in expected:
        rows.append(compare_one(family, code,
                                local.get(code), official.get(code)).as_row())
    df = pd.DataFrame(rows)
    order = {EXACT: 0, GOOD: 1, APPROX: 2, FAIL: 3, NO_DATA: 4}
    df["_o"] = df["verdict"].map(order)
    df = df.sort_values(["_o", "rel_err"], na_position="last").drop(columns="_o")
    return df.reset_index(drop=True)


def summarize(df: pd.DataFrame) -> str:
    vc = df["verdict"].value_counts()
    parts = [f"{k}={vc.get(k, 0)}" for k in (EXACT, GOOD, APPROX, FAIL, NO_DATA)]
    total = len(df)
    ok = vc.get(EXACT, 0) + vc.get(GOOD, 0)
    return f"{ok}/{total} 达到可复现（EXACT+GOOD） | " + "  ".join(parts)
