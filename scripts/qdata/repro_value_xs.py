#!/usr/bin/env python
"""Value 族剩余 8 条因子的全市场横截面复现（``full/normalized`` 全列镜像）。

════════════════════════════════════════════════════════════════════════
为什么这条路可行
════════════════════════════════════════════════════════════════════════
此前这 8 条记为「未覆盖」，原因是本地 ``recent_3tables``（2025~2026）只有
revenue / n_income_attr_p / total_assets / n_cashflow_act 四列，缺
``profit_dedt`` / ``ebitda`` / 现金流量表明细。

实测发现 **``full/normalized`` 镜像（54 个 batch、2009-12-31 ~ 2024-12-31、全列）**
足以覆盖全部 8 条 —— 于是可以在 **2024 窗口**完成验证，且完全不调 API 取输入数据。

官方值类型（2024-08-12 单日实测，见本脚本 ``--probe``）：

| 因子 | N | min | max | 类型 |
|---|---|---|---|---|
| sales_to_market | 5285 | 1.89e-4 | 1.0 | rank/N |
| ocf_to_market | 4851 | 2.06e-4 | 1.0 | rank/N |
| ebitda_to_market | 5279 | 1.89e-4 | 1.0 | rank/N |
| earnings_cut_to_market | 5202 | 1.92e-4 | 1.0 | rank/N |
| ncf_to_market | 4218 | 2.37e-4 | 1.0 | rank/N |
| etp5 | 3427 | 2.92e-4 | 1.0 | rank/N |
| pegh5 | 3144 | 3.18e-4 | 1.0 | rank/N |
| **fcf_to_market** | 4838 | **−63.59** | **4.26** | **原始比值** |

⇒ 7 条用横截面 Spearman 判据，``fcf_to_market`` 用绝对误差判据。

判据分级（与 ``xs_compare`` 一致）：
``EXACT >= 0.9999``、``GOOD >= 0.999``、``APPROX >= 0.99``、否则 ``FAIL``。

用法::

    python scripts/qdata/repro_value_xs.py --probe
    python scripts/qdata/repro_value_xs.py --dates 20240812 20240910 20241105 20241216
"""
from __future__ import annotations

import argparse
import pickle
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

_SCRIPTS = Path(__file__).resolve().parents[1]
for p in (str(_SCRIPTS), str(_SCRIPTS / "qdata"), str(_SCRIPTS / "jqdata")):
    if p not in sys.path:
        sys.path.insert(0, p)

REPO_ROOT = Path(__file__).resolve().parents[2]

import ts_fin as TF                                    # noqa: E402
from qdata_env import QDataClient                      # noqa: E402
from xs_compare import (MIN_CROSS_SECTION, compare_xs,   # noqa: E402
                       summarize_xs)
from jqdata.facsim.compare import compare_family, summarize  # noqa: E402

FAMILY = "qdata_value"
OUT = REPO_ROOT / "output" / "qdata_factor_repro"
XCACHE = OUT / "cache" / "value_official_day"
XCACHE.mkdir(parents=True, exist_ok=True)

#: 8 条目标因子
VALUE_FACTORS = ["earnings_cut_to_market", "ebitda_to_market", "etp5", "fcf_to_market",
                 "ncf_to_market", "ocf_to_market", "pegh5", "sales_to_market"]

#: 官方值为原始比值（其余为 rank/N）
RAW_FACTORS = {"fcf_to_market"}

#: ``etp5`` 需要 5 年滚动均值 ⇒ 热身 1260 交易日，另加余量
WARMUP = {"etp5": 1400, "pegh5": 1400}
DEFAULT_WARMUP = 340


# ============================================================ 扩展数据层 =========
def patch_data_layer() -> None:
    """把新增字段接入 ``ts_fin``（只扩展，不改动原文件逻辑）。"""
    TF._MIRROR_TABLES.setdefault("income", [])
    for c in ("profit_dedt", "ebit", "ebitda"):
        if c not in TF._MIRROR_TABLES["income"]:
            TF._MIRROR_TABLES["income"].append(c)
    TF._MIRROR_TABLES.setdefault("cashflow", [])
    for c in ("n_cashflow_inv_act", "free_cashflow", "stot_cash_inv_fnc_act",
              "stot_cashout_fnc_act", "c_pay_acq_const_fiolta", "stot_out_inv_act",
              "n_cash_flows_fnc_act", "c_cash_equ_beg_period", "c_cash_equ_end_period"):
        if c not in TF._MIRROR_TABLES["cashflow"]:
            TF._MIRROR_TABLES["cashflow"].append(c)
    # 本地镜像的收入/现金流量表**没有** profit_dedt；它在 fina_indicator 里（116 列）
    TF._MIRROR_TABLES["fina_indicator"] = ["profit_dedt", "ebit", "ebitda",
                                           "roa", "roe", "grossprofit_margin"]

    # ``profit_dedt`` 只在 fina_indicator 里；其余是现金流量表（累计）
    from repro_quality import FIELD_TABLE, PANEL_SPECS, _CUMULATIVE_TABLES
    # fina_indicator（roa/roe/profit_dedt/ebitda…）同样是**年初至今累计**口径，
    # 必须登记为累计表，否则 TTM 构造会漏掉差分。
    _CUMULATIVE_TABLES.add("fina_indicator")
    FIELD_TABLE["profit_dedt"] = "fina_indicator"
    FIELD_TABLE["n_cashflow_inv_act"] = "cashflow"
    FIELD_TABLE["stot_cash_inv_fnc_act"] = "cashflow"
    FIELD_TABLE["stot_cashout_fnc_act"] = "cashflow"
    FIELD_TABLE["c_pay_acq_const_fiolta"] = "cashflow"
    FIELD_TABLE["stot_out_inv_act"] = "cashflow"

    extra = {
        # 营业总收入（单季 / TTM）—— sales_to_market 的分子
        "tots_rev_q": ("total_revenue", "q"),
        # 扣非净利润（fina_indicator 为累计口径）
        "dedt_ttm": ("profit_dedt", "ttm"), "dedt_y": ("profit_dedt", "y"),
        "dedt_q": ("profit_dedt", "q"),
        # EBITDA
        "ebitda_y": ("ebitda", "y"),
        # 现金流量表明细
        "ocf": ("n_cashflow_act", "ttm"),
        "icf_net": ("n_cashflow_inv_act", "ttm"),
        "fcf_ts": ("free_cashflow", "ttm"),
        "fcf_brut": ("c_pay_acq_const_fiolta", "ttm"),
        "inv_out": ("stot_out_inv_act", "ttm"),
        # 筹资活动现金流净额（镜像无 stot_cash_inv_fnc_act，但有净额字段）
        "fin_net": ("n_cash_flows_fnc_act", "ttm"),
        "fin_in": ("stot_cash_inv_fnc_act", "ttm"),
        "fin_out": ("stot_cashout_fnc_act", "ttm"),
    }
    PANEL_SPECS.update(extra)


# ============================================================ 官方值 =============
def official_day(factor: str, date: str, use_cache: bool = True) -> pd.Series:
    p = XCACHE / f"{factor}__{date}.pkl"
    if use_cache and p.is_file():
        with p.open("rb") as f:
            return pickle.load(f)
    cli = QDataClient()
    rows = None
    for att in range(6):
        try:
            rows = cli.factor_value(factor_name=factor, trade_date=date)
            if not rows:                 # ⚠ 限流返回 code=0/msg=ok/items=[] ⇒ 必须重试
                time.sleep(1.5 * (att + 1))
                continue
            break
        except Exception as exc:                      # noqa: BLE001
            print(f"    !! {factor} {date} 失败({exc}) → 退避", flush=True)
            time.sleep(2.0 * (att + 1))
    if not rows:
        return pd.Series(dtype=float)
    s = pd.Series({r["ts_code"]: float(r["factor_value"]) for r in rows}).dropna()
    with p.open("wb") as f:
        pickle.dump(s, f)
    return s


def fetch_official(dates: list[str], factors: list[str]) -> dict[str, pd.DataFrame]:
    off: dict[str, pd.DataFrame] = {}
    for f in factors:
        cols = {}
        for d in dates:
            s = official_day(f, d)
            if s is not None and len(s):
                cols[d] = s
        if cols:
            o = pd.DataFrame(cols).T
            o.index = pd.to_datetime(o.index, format="%Y%m%d")
            off[f] = o.sort_index()
    return off


# ============================================================ 本地构造 ===========
def warmup_days(compare_dates: list[str], lookback: int) -> list[str]:
    DB_RAW = REPO_ROOT / "data" / "external" / "tushare" / "a_share_daily_basic_pit_v1" / "raw"
    files = sorted(p.name[: -len(".csv.gz")] for p in DB_RAW.glob("*.csv.gz"))
    pos = {d: i for i, d in enumerate(files)}
    known = [d for d in compare_dates if d in pos]
    if not known:
        return sorted(compare_dates)
    i0, i1 = min(pos[d] for d in known), max(pos[d] for d in known)
    return files[max(0, i0 - lookback): i1 + 1]


def market_days(dates: list[str]) -> tuple[pd.DatetimeIndex, dict[str, pd.DataFrame]]:
    DB_RAW = REPO_ROOT / "data" / "external" / "tushare" / "a_share_daily_basic_pit_v1" / "raw"
    idx = pd.DatetimeIndex([pd.Timestamp(d) for d in dates])
    close, mv, sh = {}, {}, {}
    for d in dates:
        p = DB_RAW / f"{d}.csv.gz"
        if not p.is_file():
            close[d] = pd.Series(dtype=float); mv[d] = pd.Series(dtype=float)
            sh[d] = pd.Series(dtype=float)
            continue
        df = pd.read_csv(p, usecols=["ts_code", "close", "total_mv", "total_share"]).set_index("ts_code")
        close[d] = df["close"]; mv[d] = df["total_mv"]; sh[d] = df["total_share"]
    C = pd.DataFrame(close).T
    MV = pd.DataFrame(mv).T
    SH = pd.DataFrame(sh).T
    for x in (C, MV, SH):
        x.index = pd.to_datetime(x.index, format="%Y%m%d")
    return idx, {"C_RAW": C.sort_index(),
                 "TOTAL_MV": MV.sort_index() * 1e4,      # 万元 → 元
                 "TOTAL_SHARE": SH.sort_index()}


def build_local(dates: list[str], max_codes: int | None) -> dict[str, pd.DataFrame]:
    import repro_quality as R
    from ts_env import TSPanel

    lookback = max(WARMUP.get(f, DEFAULT_WARMUP) for f in VALUE_FACTORS)
    all_days = warmup_days(dates, lookback)
    print(f"  面板交易日 {len(all_days)}（含热身 {lookback} 日），比对日 {dates}", flush=True)

    if max_codes:
        # 只读切片：先取代码清单再按需加载，避免全量镜像重载
        probe_tabs = TF.load_mirror_full(codes=None, tables={"income": ["revenue"]})
        codes = sorted(probe_tabs["income"]["ts_code"].unique())[:max_codes]
        tabs = TF.load_mirror_full(codes=codes)
    else:
        tabs = TF.load_mirror_full()
        codes = sorted(tabs["income"]["ts_code"].unique())
    print(f"  本地股票池 {len(codes)} 只", flush=True)

    tables = {t: {c: g for c, g in df.groupby("ts_code", sort=False)}
              for t, df in tabs.items()}
    mats = TF.build_matrices(tables, codes)

    idx, fields = market_days(all_days)
    panel = TSPanel(codes=codes, fields=fields)
    P = R.build_panels(mats, codes, idx)
    inner = _build_value_inner(R, P, panel)
    print(f"  内层因子 {len(inner)} 条", flush=True)

    cidx = pd.DatetimeIndex([pd.Timestamp(d) for d in dates])
    local: dict[str, pd.DataFrame] = {}
    for f, v in inner.items():
        v = v.replace([np.inf, -np.inf], np.nan).reindex(cidx)
        v = v.loc[:, v.notna().any()]
        # 不带 ``__`` 的是正式因子（按实测判据施加排名包装）；带的只作变体扫描用
        if "__" in f or f in RAW_FACTORS:
            local[f] = v
        else:
            local[f] = R.xs_rank(v)
    return local


def _build_value_inner(R, P: dict[str, pd.DataFrame], mkt) -> dict[str, pd.DataFrame]:
    """构造 8 条因子的**内层比值**（排名包装由调用方施加）。

    市值统一取 ``ClosePrice × TotalShares``（= ``daily_basic.total_mv``，万元 → 元）。
    """
    div = R._div
    mv = mkt.TOTAL_MV
    out: dict[str, pd.DataFrame] = {}

    # sales_to_market = 营业总收入 / 总市值（单季 vs TTM 两版，选择由实测决定）
    out["sales_to_market"] = div(P["tots_rev_q"], mv)
    out["sales_to_market__ttm"] = div(P["tots_rev_ttm"], mv)

    # ocf_to_market = 经营现金流净额 TTM / 总市值
    out["ocf_to_market"] = div(P["ocf"], mv)

    # ebitda_to_market = EBITDA / 总市值（EBITDA 优先用 fina_indicator 字段）
    out["ebitda_to_market"] = div(P["ebitda_ttm"], mv)
    out["ebitda_to_market__y"] = div(P["ebitda_y"], mv)

    # earnings_cut_to_market = 归母净利润 TTM / 总市值
    # ⚠️ 文档写「扣非净利润」，但 2026-09-21 全市场实测（5381 只 @20240812）证明官方用的
    #    是**归母净利润**：归母 TTM Spearman **0.999997** vs 扣非 TTM **0.941175**。
    #    文档原文其实已给出提示：「使用归母净利润作为扣非净利润的替代」。
    out["earnings_cut_to_market"] = div(P["npp_ttm"], mv)
    out["earnings_cut_to_market__dedt"] = div(P["dedt_ttm"], mv)
    out["earnings_cut_to_market__attr"] = div(P["npp_ttm"], mv)

    # fcf_to_market = (经营 TTM − 投资现金流出 TTM) / 总市值
    out["fcf_to_market"] = div(P["ocf"] - P["inv_out"], mv)
    out["fcf_to_market__ts"] = div(P["fcf_ts"], mv)
    out["fcf_to_market__const"] = div(P["ocf"] - P["fcf_brut"], mv)

    # ncf_to_market = (OCF + ICF + FCF) / 总市值
    fin_net = P["fin_net"] if bool(P["fin_net"].notna().to_numpy().any()) else (P["fin_in"] - P["fin_out"])
    out["ncf_to_market"] = div(P["ocf"] + P["icf_net"] + fin_net, mv)
    out["ncf_to_market__invonly"] = div(P["ocf"] + P["icf_net"], mv)

    # etp5 = RollingMean(NetProfit_Y, 1260) / RollingMean(MarketCap, 1260)
    ni_y = P["npp_y"].ffill(limit=3)
    num = ni_y.rolling(1260, min_periods=1000).mean()
    den = mv.rolling(1260, min_periods=1000).mean()
    out["etp5"] = div(num, den)

    # pegh5 = -Close / (EPS_Growth_5Y * BasicEPS_TTM)
    eps_y = P["eps_y"].ffill(limit=3)
    eps_t = P["eps_ttm"]
    c_raw = mkt.C_RAW
    g5 = (div(eps_y, eps_y.shift(1260)) ** (1.0 / 5.0)) - 1.0
    out["pegh5"] = -div(c_raw, g5 * eps_t)
    return out


# ============================================================ 主流程 =============
def probe() -> int:
    """打印官方值的分布签名（判定 rank/N vs 原始比值）。"""
    for f in VALUE_FACTORS:
        for d in ("20240812",):
            s = official_day(f, d)
            if s is None or s.empty:
                print(f"{f:26s} {d} EMPTY"); continue
            N, u = len(s), s.nunique()
            mn, mx = s.min(), s.max()
            kind = "rank" if (abs(mx - 1.0) < 1e-9 and mn > 0) else "raw"
            print(f"{f:26s} {d} N={N:5d} uniq={u:5d} min={mn:.6g} max={mx:.6g}  {kind}")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--probe", action="store_true")
    ap.add_argument("--dates", nargs="*",
                    default=["20240812", "20240910", "20241105", "20241216"])
    ap.add_argument("--max-codes", type=int, default=None)
    ap.add_argument("--no-write", action="store_true")
    args = ap.parse_args()
    if args.probe:
        return probe()

    patch_data_layer()
    t0 = time.time()
    print("[1/4] 构造本地内层比值", flush=True)
    local = build_local(args.dates, args.max_codes)
    print(f"  用时 {time.time()-t0:.0f}s", flush=True)

    print("[2/4] 取官方单日全市场值", flush=True)
    official = fetch_official(args.dates, VALUE_FACTORS)

    rank_facs = [f for f in VALUE_FACTORS if f not in RAW_FACTORS and f in local]
    raw_facs = [f for f in VALUE_FACTORS if f in RAW_FACTORS and f in local]

    print("[3/4] 横截面 Spearman（rank 型）", flush=True)
    dxs = compare_xs(FAMILY, {f: local[f] for f in rank_facs},
                     {f: official[f] for f in rank_facs}, rank_facs) if rank_facs else pd.DataFrame()
    print("[4/4] 绝对误差（原始比值型）", flush=True)
    dabs = (compare_family(FAMILY, {f: local[f] for f in raw_facs},
                           {f: official[f] for f in raw_facs}, raw_facs)
            if raw_facs else pd.DataFrame())

    if not args.no_write:
        # 本地内层比值 / 因子值落盘：便于离线复检与变体扫描（省去 ~7 分钟的重建）
        with (OUT / "cache" / "value_local.pkl").open("wb") as fh:
            pickle.dump(local, fh)
        if not dxs.empty:
            dxs.to_csv(OUT / "value_xs_compare.csv", index=False)
        if not dabs.empty:
            dabs.to_csv(OUT / "value_abs_compare.csv", index=False)
        combo = pd.concat([d for d in (dxs, dabs) if not d.empty], ignore_index=True)
        combo.to_csv(OUT / "value_compare_settled.csv", index=False)
        print("  已写 output/qdata_factor_repro/value_compare_settled.csv", flush=True)

    print("\n=== 结果 ===", flush=True)
    for name, d in (("横截面 Spearman", dxs), ("绝对误差", dabs)):
        if d.empty:
            continue
        print(f"\n[{name}]")
        cols = [c for c in ("factor", "verdict", "spearman_med", "spearman_min", "n_days",
                            "verdict_med", "med_rel_err", "corr", "n_overlap", "note")
                if c in d.columns]
        print(d[cols].to_string(index=False))

    # ---- 隐藏列对照：内层比值是否逐位一致（rank 差异是否纯粹来自 N 不同）----
    print("\n=== 内层比值直接对照（官方 rank/N 的次序 vs 本次比值次序）===", flush=True)
    hidden = [f for f in local if "__" in f]
    hrows = []
    for f in hidden:
        base = f.split("__")[0]
        o = official.get(base)
        v = local[f]
        if o is None or v.empty:
            continue
        idx = v.index.intersection(o.index)
        if idx.empty:
            continue
        sp = []
        for t in idx:
            a = pd.to_numeric(o.loc[t], errors="coerce")
            b = pd.to_numeric(v.loc[t], errors="coerce")
            m = a.notna() & b.notna() & np.isfinite(a) & np.isfinite(b)
            if m.sum() < MIN_CROSS_SECTION:
                continue
            sp.append(a[m].corr(b[m], method="spearman"))
        if sp:
            hrows.append({"variant": f, "官方因子": base,
                          "spearman_med": float(np.median(sp)),
                          "n_days": len(sp)})
    if hrows:
        hd = pd.DataFrame(hrows).sort_values(["官方因子", "spearman_med"], ascending=[True, False])
        print(hd.to_string(index=False))
        if not args.no_write:
            hd.to_csv(OUT / "value_variant_scan.csv", index=False)
    print(f"\n总用时 {time.time()-t0:.0f}s")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
