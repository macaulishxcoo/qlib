#!/usr/bin/env python
"""Quality / Growth 的**全市场横截面**验证（qdata 因子本质是 ``rank/N``，必须全市场复算）。

为什么要单独一套判据
--------------------
74 条 Quality・Growth 因子里 **62 条的官方值是 ``rank/N`` 型**（实测判定，见
``qg_rank_classification.csv``：单日全市场官方值满足 ``min ≈ 1/N`` 且 ``max = 1.0``）。
在 6 只样本股上本地只能得到 ``{1/6..1}``，与官方 ``{1/N..1}`` 不可能逐位相等
（把官方值**再排序**可等价验证内层次序，但只有 6 个观测，统计功效极低）。
因此主判据必须是**全市场横截面**：

1. 用本地离线全市场财务镜像（``data/external/tushare/a_share_financial_pit_v1``）
   算出内层比值 ``x``（PIT：按 ``ann_date`` 前向填充）；
2. ``rank`` 型因子再做 ``rank(x)/N``；
3. 与官方单日全市场因子值（``factor_value(trade_date=...)``，1 次调用 ≈5500 行）比：
   - ``rank`` 型 → ``compare_xs``（逐日 Spearman）
   - 原始比值型 → ``compare_family``（绝对/相对误差）

窗口
----
- ``--window 2024``：本地 ``full/normalized`` 三大报表**全列**可用（2009~2024）→ 覆盖全部 74 条；
- ``--window 2026``：本地 ``recent_3tables`` 仅有 revenue / n_income_attr_p / total_assets /
  n_cashflow_act → 只覆盖 10 条（其余判 NO_DATA）。

用法::

    python scripts/qdata/repro_quality_xs.py --window 2024 --dates 20240812 20240910 20241105 20241216
"""
from __future__ import annotations

import pickle
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

_SCRIPTS = Path(__file__).resolve().parents[1]
for p in (str(_SCRIPTS), str(_SCRIPTS / "jqdata"), str(_SCRIPTS / "qdata")):
    if p not in sys.path:
        sys.path.insert(0, p)

import repro_quality as R  # noqa: E402
import ts_fin as TF  # noqa: E402
from jqdata.facsim.compare import compare_family, summarize  # noqa: E402
from qdata_env import QDataClient  # noqa: E402
from ts_env import TSPanel  # noqa: E402
from xs_compare import compare_xs, summarize_xs  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parents[2]
XCACHE = REPO_ROOT / "output" / "qdata_factor_repro" / "cache" / "qg_official_day"
XCACHE.mkdir(parents=True, exist_ok=True)
DB_RAW = REPO_ROOT / "data" / "external" / "tushare" / "a_share_daily_basic_pit_v1" / "raw"

FAMILY = "qdata_quality_growth"

#: 实测为 ``rank/N`` 型的因子（由 ``qg_rank_classification.csv`` 的经验判别得出）
RANK_EMPIRICAL = {
    "cfcr", "delta_cash_ratio", "np_to_fixed_assets_yoy", "np_to_salary_yoy",
    "npm_q_qoq", "npm_ttm_qoq", "roa_y", "yoy_ocf", "delta_inventory_turnover",
    "delta_roa", "fixed_asset_turnover", "np_ttm_qoq", "npm_ttm", "opm_ttm",
    "receivable_turnover", "asset_growth_qoq", "delta_gpm", "gpm_y",
    "np_to_total_expenses_yoy", "npm_tsh", "opt_tpro", "delta_de", "eps_ttm",
    "financial_leverage", "gpm_ttm", "icr", "income_tax_yoy", "np_to_inventory_yoy",
    "npm_q", "ar_ap_to_revenue", "asset_turnover", "delta_current_ratio", "gpm_q",
    "np_to_deferred_tax_yoy", "cash_profit_ratio", "delta_opm", "eps_q", "eps_y",
    "yoy_roe", "yoy_total_asset", "cash_ratio", "delta_asset_turnover",
    "delta_quick_ratio", "delta_roe", "gross_margin_qoq", "inventory_turnover",
    "pa", "roa_ttm", "tax_surcharge_yoy", "yoy_roa", "delta_npm", "eaa", "eap",
    "market_value_leverage", "npm_y", "opm_y", "equity_turnover",
    "expenses_to_equity_yoy", "gpm_qoq", "roa_q", "sa", "yoy_net_asset",
}


# ---------------------------------------------------------------- 官方单日全市场
def official_day(factor: str, date: str, use_cache: bool = True) -> pd.Series:
    p = XCACHE / f"{factor}__{date}.pkl"
    if use_cache and p.is_file():
        with p.open("rb") as f:
            return pickle.load(f)
    cli = QDataClient()
    for att in range(6):
        try:
            rows = cli.factor_value(factor_name=factor, trade_date=date)
            if not rows:            # ⚠ 限流会返回 code=0/msg=ok/items=[] → 必须重试
                time.sleep(1.5 * (att + 1))
                continue
            break
        except Exception as exc:                      # noqa: BLE001
            print(f"    !! {factor} {date} 失败({exc}) → 退避")
            time.sleep(2.0 * (att + 1))
    else:
        return pd.Series(dtype=float)
    d = pd.DataFrame(rows)
    s = d.set_index("ts_code")["factor_value"].astype(float)
    with p.open("wb") as f:
        pickle.dump(s, f)
    return s


# ---------------------------------------------------------------- 本地全市场
def load_universe(window: str,
                  codes: list[str] | None = None) -> dict[str, dict[str, pd.DataFrame]]:
    """``{code: {table: long_df}}``。"""
    tabs = TF.load_mirror_full(codes) if window == "2024" else TF.load_mirror_recent(codes)
    out: dict[str, dict[str, pd.DataFrame]] = {}
    for t, df in tabs.items():
        if df is None or df.empty:
            continue
        for c, g in df.groupby("ts_code", sort=False):
            out.setdefault(c, {})[t] = g
    return out


def market_days(dates: list[str]) -> tuple[pd.DatetimeIndex, dict[str, pd.DataFrame]]:
    """读本地 ``daily_basic`` 单日切片（close / total_mv）。

    ``dates`` 可含**热身日**（``_t-252`` 类因子回看用），由调用方按比对日落裁。
    """
    idx = pd.DatetimeIndex([pd.Timestamp(d) for d in dates])
    close, mv = {}, {}
    for d in dates:
        p = DB_RAW / f"{d}.csv.gz"
        if not p.is_file():
            # 行情镜像只覆盖到 2026-08-07；缺日仍保留在日期索引里（仅财务类因子不受影响）
            close[d] = pd.Series(dtype=float)
            mv[d] = pd.Series(dtype=float)
            continue
        df = pd.read_csv(p, usecols=["ts_code", "close", "total_mv"]).set_index("ts_code")
        close[d] = df["close"]
        mv[d] = df["total_mv"]
    C = pd.DataFrame(close).T
    MV = pd.DataFrame(mv).T
    for x in (C, MV):
        x.index = pd.to_datetime(x.index, format="%Y%m%d")
    return idx, {"C_RAW": C.sort_index(), "TOTAL_MV": MV.sort_index()}


def warmup_days(compare_dates: list[str]) -> list[str]:
    """比对日 + 最早期比对日之前 340 个交易日。

    ``_t-252`` 类因子只回看 252 个交易日，但 ``pa``/``sa``/``eaa``/``eap`` 还要再
    ``shift(63)``，共需 315 日 → 取 340 留余量；否则这些因子在比对日全为 NaN（NO_DATA）。
    """
    all_files = sorted(p.name[: -len(".csv.gz")] for p in DB_RAW.glob("*.csv.gz"))
    pos = {d: i for i, d in enumerate(all_files)}
    known = [d for d in compare_dates if d in pos]
    if not known:
        return sorted(compare_dates)
    i0 = min(pos[d] for d in known)
    i1 = max(pos[d] for d in known)
    lo = max(0, i0 - 340)
    warm = all_files[lo: i1 + 1]
    return sorted(set(warm) | set(compare_dates))


def build_local(window: str, dates: list[str], factors: list[str], max_codes: int | None):
    uni = load_universe(window)
    all_codes = sorted(uni)
    if max_codes:
        all_codes = all_codes[:max_codes]
    print(f"  本地股票池 {len(all_codes)} 只（窗口 {window}）", flush=True)
    t0 = time.time()
    mats = {c: TF.FinMatrix(uni[c]) for c in all_codes}
    print(f"  FinMatrix 构建完成 {time.time()-t0:.1f}s", flush=True)

    all_days = warmup_days(dates)
    print(f"  面板交易日 {len(all_days)}（含热身），比对日 {dates}", flush=True)
    idx, fields = market_days(all_days)
    panel = TSPanel(codes=all_codes, fields=fields)
    P = R.build_panels(mats, all_codes, idx)
    inner = R.build_inner(P, panel)
    inner.update(R.build_inner_report(mats, all_codes, idx))
    print(f"  内层因子 {len(inner)} 条", flush=True)

    cidx = pd.DatetimeIndex([pd.Timestamp(d) for d in dates])
    local = {}
    for f, v in inner.items():
        if f not in factors:
            continue
        v = v.replace([np.inf, -np.inf], np.nan).reindex(cidx)
        v = v.loc[:, v.notna().any()]
        local[f] = R.xs_rank(v) if f in RANK_EMPIRICAL else v
    return local


def fetch_official(dates: list[str], factors: list[str]) -> dict[str, pd.DataFrame]:
    official = {}
    for f in factors:
        cols = {}
        for d in dates:
            s = official_day(f, d)
            if s is not None and len(s):
                cols[d] = s
        if cols:
            o = pd.DataFrame(cols).T
            o.index = pd.to_datetime(o.index, format="%Y%m%d")
            official[f] = o.sort_index()
    return official


def run(window: str, dates: list[str], factors: list[str], max_codes: int | None,
        outdir: Path, tag: str) -> tuple[pd.DataFrame, pd.DataFrame]:
    local = build_local(window, dates, factors, max_codes)
    official = fetch_official(dates, factors)

    rank_facs = [f for f in factors if f in RANK_EMPIRICAL]
    raw_facs = [f for f in factors if f not in RANK_EMPIRICAL]

    print(f"\n===== ① rank 型 {len(rank_facs)} 条：全市场逐日 Spearman =====")
    dxs = compare_xs(FAMILY, local, official, rank_facs)
    with pd.option_context("display.width", 220):
        print(dxs.to_string(index=False, float_format=lambda x: f"{x:.5g}"))
    print("\n" + summarize_xs(dxs))

    cols_abs = ["factor", "verdict_med", "verdict", "n_overlap", "coverage",
                "max_abs_err", "med_rel_err", "corr"]
    print(f"\n===== ② 原始比值型 {len(raw_facs)} 条：逐值比对 =====")
    dabs = (compare_family(FAMILY, local, official, raw_facs) if raw_facs
            else pd.DataFrame(columns=["factor", "verdict_med", "verdict", "n_overlap",
                                       "coverage", "max_abs_err", "med_rel_err", "corr"]))
    with pd.option_context("display.width", 220):
        print(dabs[cols_abs].to_string(index=False, float_format=lambda x: f"{x:.4g}"))
    print("\n" + summarize(dabs))

    xs_map = dxs.set_index("factor")["verdict_xs"].to_dict() if not dxs.empty else {}
    sp_map = dxs.set_index("factor")["spearman_med"].to_dict() if not dxs.empty else {}
    nd_map = dxs.set_index("factor")["n_days"].to_dict() if not dxs.empty else {}
    abs_map = dabs.set_index("factor").to_dict("index") if not dabs.empty else {}
    rows = []
    for f in factors:
        is_rank = f in RANK_EMPIRICAL
        a = abs_map.get(f, {})
        rows.append(dict(
            factor=f,
            mode="rank" if is_rank else "raw",
            verdict_med=xs_map.get(f) if is_rank else a.get("verdict_med"),
            verdict=xs_map.get(f) if is_rank else a.get("verdict"),
            spearman_med=sp_map.get(f),
            n_days=nd_map.get(f),
            n_overlap=a.get("n_overlap"),
            coverage=a.get("coverage"),
            max_abs_err=a.get("max_abs_err"),
            med_rel_err=a.get("med_rel_err"),
            corr=a.get("corr"),
        ))
    dall = pd.DataFrame(rows)
    outdir.mkdir(parents=True, exist_ok=True)
    dall.to_csv(outdir / f"quality_growth_compare{tag}.csv", index=False)
    dxs.to_csv(outdir / f"quality_growth_xs_{window}{tag}.csv", index=False)
    dabs.to_csv(outdir / f"quality_growth_abs_{window}{tag}.csv", index=False)
    print(f"\n汇总: {outdir / f'quality_growth_compare{tag}.csv'}")
    vc = dall["verdict_med"].value_counts().to_dict()
    ok = vc.get("EXACT", 0) + vc.get("GOOD", 0)
    print(f"全市场口径：{ok}/{len(dall)} 达到 EXACT+GOOD | " +
          "  ".join(f"{k}={vc.get(k,0)}" for k in ("EXACT", "GOOD", "APPROX", "FAIL", "NO_DATA")))
    return dall, dxs


def main() -> int:
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--window", default="2024", choices=["2024", "2026"])
    ap.add_argument("--dates", nargs="*",
                    default=["20240812", "20240813", "20240910", "20241105", "20241216"])
    ap.add_argument("--factors", nargs="*", default=None)
    ap.add_argument("--max-codes", type=int, default=None)
    ap.add_argument("--tag", default="")
    ap.add_argument("--outdir", default="output/qdata_factor_repro")
    a = ap.parse_args()
    facs = a.factors or R.all_factor_names()
    run(a.window, a.dates, facs, a.max_codes, Path(a.outdir), a.tag)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
