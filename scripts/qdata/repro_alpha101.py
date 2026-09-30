#!/usr/bin/env python
"""Alpha101 批量复现 + 官方比对（qdata.cc）。

流程
----
1. :mod:`ts_market` 取全市场面板（按日落盘缓存）。
2. :mod:`alpha101_eval` 解析 ``factor_formulas.json`` 的公式并按 AST 求值。
3. ``factor_value(factor_name, trade_date=YYYYMMDD)`` 取**单日全市场**官方值
   （≈5542 行 < 6000 上限，1 次调用即一整日，天然绕开 offset 分页的重复行问题）。
4. :func:`jqdata.facsim.compare.compare_family` 判定，输出
   ``output/qdata_factor_repro/alpha101_compare.csv``。

关键：横截面算子需要「与官方相同的股票全集」
------------------------------------------
``--universe official``（默认）：在**被比对的那些交易日**上，把面板列集合限制为
官方当日返回的 ts_code 集合（其余日期不限制，保证时序窗口完整）。这样
``Rank`` 的分母与官方一致，能把「算子语义是否正确」与「股票池是否一致」两个
问题**解耦**。
``--universe none``：全 Tushare 口径（用于量化股票池差异的影响）。

用法
----
    python scripts/qdata/repro_alpha101.py --phase-a          # 阶段 A 小规模验证
    python scripts/qdata/repro_alpha101.py --n-dates 4        # 阶段 B
"""
from __future__ import annotations

import json
import sys
import time
import warnings
from pathlib import Path

import numpy as np
import pandas as pd

warnings.filterwarnings("ignore")

_SCRIPTS = Path(__file__).resolve().parents[1]
for _p in (str(_SCRIPTS), str(_SCRIPTS / "jqdata"), str(_SCRIPTS / "qdata")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import alpha101_eval as E                                    # noqa: E402
import xs_ops as X                                           # noqa: E402
from jqdata.facsim.compare import compare_family, summarize  # noqa: E402
from qdata_env import QDataClient                            # noqa: E402
from ts_market import (alive_mask, day_cache_path, load_market,  # noqa: E402
                       trade_dates)
from xs_compare import compare_xs, summarize_xs              # noqa: E402

REPO_ROOT = Path(__file__).resolve().parents[2]
OUT_DIR = REPO_ROOT / "output" / "qdata_factor_repro"
CACHE = OUT_DIR / "cache"
OFF_DAY_CACHE = CACHE / "official_day"
OFF_DAY_CACHE.mkdir(parents=True, exist_ok=True)

FAMILY = "qdata_alpha101"
FORMULAS = OUT_DIR / "factor_formulas.json"
SETTLE_DAYS_DEFAULT = 30

#: 阶段 A 的探针因子：覆盖「纯逐元素 / 纯 Rank / VWAP / 成交量符号」
PHASE_A_FACTORS = ["alpha101_101", "alpha101_33", "alpha101_41", "alpha101_42",
                   "alpha101_12", "alpha101_54"]


# ============================================================ 公式清单 ==========
def alpha101_names(include_old: bool = False) -> list[str]:
    d = json.loads(FORMULAS.read_text())
    ks = [k for k, v in d.items()
          if v.get("factor_type") == "Alpha101" and (include_old or "_old_" not in k)]
    ks.sort(key=lambda x: int(x.rsplit("_", 1)[1]))
    return ks


def load_formula(name: str) -> str:
    return json.loads(FORMULAS.read_text())[name]["formula"]


#: ``factor_desc`` 里的公式**括号丢失/笔误**修正（实测对照后才加入，见 ALPHA101_NOTES.md §5）
#: alpha101_30：文档写 ``(1 - Rank(...) * Sum(V,5)) / Sum(V,20)``，
#: 但原始 WorldQuant alpha#30 是 ``(1 - Rank(...)) * Sum(V,5) / Sum(V,20)``。
#: 实测 @20260811：文档版 Spearman 0.576 / 中位误差 0.234；
#: 原始版 **Spearman 1.000000 / 中位误差 1.3e-4**。
FORMULA_FIXES: dict[str, str] = {
    "alpha101_30": (
        "(1 - Rank(Sign(Close - Delay(Close, 1)) + Sign(Delay(Close, 1) - Delay(Close, 2))"
        " + Sign(Delay(Close, 2) - Delay(Close, 3)))) * Sum(Volume, 5) / Sum(Volume, 20)"
    ),
}


def formula_of(name: str) -> str:
    """取因子表达式（优先用实测修正版）。"""
    return FORMULA_FIXES.get(name) or load_formula(name)


# ============================================================ 面板 → 变量 ======
def build_vars(panel, mask: pd.DataFrame | None = None) -> dict[str, pd.DataFrame]:
    """面板 → Alpha101 变量表。``mask`` 为 True 的位置保留，其余置 NaN。

    价格口径由 ``xs_ops.CFG`` 控制（实测默认：**不复权 raw + 停牌日走平**）：
        ``PRICE_MODE``      ``raw`` / ``hfq`` / ``fq``
        ``FLAT_SUSPENDED``  停牌日 ``O=H=L=C=前收盘``，``V``/``AMOUNT`` 仍为 NaN
    """
    def m(df):
        if mask is not None:
            df = df.where(mask)
        if alive is not None:
            df = df.where(alive.reindex(index=df.index, columns=df.columns))
        return df

    alive = None
    if int(X.CFG.get("ALIVE_FILTER", 1)):
        alive = alive_mask(panel.dates, panel.C.columns)
    px = panel.prices(mode=str(X.CFG["PRICE_MODE"]),
                      flat=bool(X.CFG["FLAT_SUSPENDED"]))
    C, O, H, L = m(px["C"]), m(px["O"]), m(px["H"]), m(px["L"])
    V = m(px["V"] * px["ADJ"]) if X.CFG["VOLUME_MODE"] == "hfq" else m(px["V"])
    VWAP = m(px["VWAP"]) if X.CFG["VWAP_MODE"] != "hfq" else m(px["VWAP"])

    out = {
        "Open": O, "High": H, "Low": L, "Close": C, "Volume": V, "VWAP": VWAP,
        "Returns": C.pct_change(),
    }
    for n in (15, 20, 30, 50, 60, 120, 180):
        out[f"ADV{n}"] = V.rolling(n).mean()
    if "TOTAL_MV" in panel.fields:
        out["Cap"] = m(panel.TOTAL_MV)
    else:
        out["Cap"] = m(panel.C_RAW * panel.TOTAL_SHARE) if "TOTAL_SHARE" in panel.fields else None
    # alpha101_64 的 ``Delta_Mix`` 在 factor_desc 里**没有定义**（厂商私有字段）。
    # 候选解释（原始 WorldQuant alpha#64 的对应子式）由 --cfg DELTA_MIX=1 打开做对照。
    if int(X.CFG.get("DELTA_MIX", 0)):
        out["Delta_Mix"] = -1.0 * O / C
    return {k: v for k, v in out.items() if v is not None}


# ============================================================ 官方取数 ==========
def _client() -> QDataClient:
    return QDataClient(qps=8, retries=5)


def official_day(cli: QDataClient, factor: str, date: str, use_cache: bool = True):
    """单因子单日全市场官方值 → ``dict[ts_code -> float]``（含逐日缓存）。"""
    p = OFF_DAY_CACHE / f"{factor}__{date}.pkl"
    if use_cache and p.is_file():
        return pd.read_pickle(p)
    rows: list[dict] = []
    for att in range(4):
        try:
            rows = cli.factor_value(factor_name=factor, trade_date=date)
            break
        except Exception as exc:                       # noqa: BLE001
            print(f"      !! {factor} {date} 取数失败(第{att+1}次): {exc}")
            time.sleep(2.0 * (att + 1))
    if not rows:
        return {}
    df = pd.DataFrame(rows).drop_duplicates(subset=["ts_code"])
    s = dict(zip(df["ts_code"], pd.to_numeric(df["factor_value"], errors="coerce")))
    if use_cache:
        pd.to_pickle(s, p)
    return s


def official_panel(factors: list[str], dates: list[str],
                   use_cache: bool = True) -> dict[str, pd.DataFrame]:
    cli = _client()
    out: dict[str, pd.DataFrame] = {}
    for f in factors:
        cols = {}
        for d in dates:
            s = official_day(cli, f, d, use_cache=use_cache)
            if s:
                cols[pd.Timestamp(d)] = pd.Series(s, dtype=float)
            print(f"    [qdata] {f} {d}: {len(s)} 行")
        if cols:
            out[f] = pd.DataFrame(cols).T.sort_index()
    return out


# ============================================================ 本地计算 ==========
def compute_local(panel, factors: list[str], eval_dates: list[str],
                  mask: pd.DataFrame | None = None, verbose: bool = True):
    """逐因子求值，只保留 ``eval_dates`` 行。"""
    env = E.build_env(build_vars(panel, mask))
    # IndNeutralize 需要行业分类（Tushare ``stock_basic.industry``，非申万 ⇒ 口径未标定）
    try:
        from ts_market import industry_map
        env.ind_mat = X.industry_matrix(industry_map(), panel.C.columns)
        print(f"    [ind] IndNeutralize 行业矩阵就绪："
              f"{env.ind_mat.shape[1]} 个行业 × {env.ind_mat.shape[0]} 只")
    except Exception as exc:                           # noqa: BLE001
        print(f"    [ind] 行业分类不可用（{exc}），IndNeutralize 因子将跳过")
        env.ind_mat = None
    local: dict[str, pd.DataFrame] = {}
    errors: dict[str, str] = {}
    for f in factors:
        try:
            ast = E.parse(E.clean_formula(formula_of(f)))
        except Exception as exc:                       # noqa: BLE001
            errors[f] = f"解析失败: {exc}"
            continue
        env.cache = {}                                 # 逐因子清缓存，控制内存
        # 注意：env.vars 常驻（ADV*/Returns 等共享序列），env.cache 每因子清空，
        # 否则 71 个因子 × 每个中间量 ~13 MB 会把内存打爆。
        try:
            full = E.evaluate(ast, env)
        except KeyError as exc:
            errors[f] = f"未定义标识符 {exc}"
            continue
        except Exception as exc:                       # noqa: BLE001
            errors[f] = f"求值异常: {type(exc).__name__}: {exc}"
            continue
        sub = full.reindex([pd.Timestamp(d) for d in eval_dates])
        # 布尔型因子（形如 ``A < B``）必须先转 float，否则 compare.py 的
        # ``np.corrcoef`` 会在 bool 数组上抛 AttributeError。
        local[f] = sub.astype(float).replace([np.inf, -np.inf], np.nan)
        if verbose:
            nn = int(local[f].notna().sum().sum())
            print(f"    [loc] {f}: {nn} 个有效值 / {sub.size}")
    return local, errors


# ============================================================ 比对（容错） ======
def safe_compare_family(family: str, local: dict, official: dict,
                        expected: list[str]) -> pd.DataFrame:
    """``compare_family`` 的容错版：``np.corrcoef`` 在常数序列上会抛
    ``AttributeError``（compare.py 未做保护，且不允许改动）。逐因子 try/except。"""
    from jqdata.facsim.compare import NO_DATA, FactorReport, compare_one
    nan = dict(max_abs_err=np.nan, p99_abs_err=np.nan, mean_abs_err=np.nan,
               rel_err=np.nan, corr=np.nan, official_mag=np.nan)
    rows = []
    for code in expected:
        try:
            rep = compare_one(family, code, local.get(code), official.get(code))
        except Exception as exc:                       # noqa: BLE001
            off = official.get(code)
            rep = FactorReport(code, family, NO_DATA, 0,
                               int(off.notna().sum().sum()) if off is not None else 0,
                               0.0, note=f"比对异常: {type(exc).__name__}", **nan)
        rows.append(rep.as_row())
    df = pd.DataFrame(rows)
    order = {"EXACT": 0, "GOOD": 1, "APPROX": 2, "FAIL": 3, "NO_DATA": 4}
    df["_o"] = df["verdict"].map(order)
    return df.sort_values(["_o", "rel_err"], na_position="last").drop(
        columns="_o").reset_index(drop=True)


# ============================================================ 归因 ==============
#: 归因类别（顺序即判定优先级）
ATTR = {
    "STRUCT_TAIL": "结构性不可复现（qdata 尾部未沉淀窗口）",
    "UNIVERSE": "股票池/停牌口径未标定",
    "IND_NEUTRAL": "口径未标定（IndNeutralize 行业分类口径）",
    "CALIB": "口径未标定（算子统计量定义）",
    "MISSING_IDENT": "公式含未定义标识符（厂商私有字段）",
    "PARSE": "公式解析/求值错误",
    "DISCRETE": "离散输出（布尔/±1）跳变放大（历史横截面池差异）",
    "MAGNITUDE": "数值口径差异（横截面名次一致，绝对量级不同）",
    "OK": "已复现",
}


def classify(row, formula: str) -> str:
    """按证据给不通过因子归类。判定顺序：解析 → 未定义标识符 → 口径 → 池。"""
    if isinstance(row.get("attribution"), str) and row["attribution"].startswith("未实现"):
        return row["attribution"]
    sp = row.get("spearman_med")
    v_med = row.get("verdict_med")
    v_max = row.get("verdict")
    v_xs = row.get("verdict_xs")
    nd = row.get("n_distinct", np.nan)
    if str(row.get("attribution", "")).startswith("公式已修正"):
        return row["attribution"]
    if v_med == "NO_DATA" and (not np.isfinite(sp) if sp is not None else True):
        return ATTR["PARSE"]
    if v_med in ("EXACT", "GOOD") and v_xs in ("EXACT", "GOOD", "NO_DATA"):
        return ATTR["OK"]
    # 离散输出（布尔/三元 ±1）会被历史横截面池的微小差异放大成 ±1 跳变
    if np.isfinite(nd) and nd <= 4:
        return ATTR["DISCRETE"]
    if v_xs in ("EXACT", "GOOD") and v_med not in ("EXACT", "GOOD"):
        return ATTR["MAGNITUDE"]
    if v_xs == "NO_DATA" and v_max == "NO_DATA":
        return ATTR["PARSE"]
    if v_xs == "APPROX":
        return ATTR["IND_NEUTRAL"] if "IndNeutralize" in formula else ATTR["CALIB"]
    if v_xs == "FAIL":
        if "IndNeutralize" in formula:
            return ATTR["IND_NEUTRAL"]
        return ATTR["UNIVERSE"]
    return ATTR["CALIB"]


# ============================================================ 主流程 ============
def pick_dates(start: str, end: str, settle: int, n: int) -> list[str]:
    days = trade_dates(start, end)
    cut = (pd.Timestamp(end) - pd.Timedelta(days=settle)).strftime("%Y%m%d")
    days = [d for d in days if d <= cut]
    if not days:
        return []
    if n >= len(days):
        return days
    idx = np.linspace(0, len(days) - 1, n).round().astype(int)
    return [days[i] for i in dict.fromkeys(idx)]


def main() -> int:
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--factors", nargs="*", default=None)
    ap.add_argument("--phase-a", action="store_true",
                    help="阶段 A 小规模验证（探针因子 + 单日 + 数值对照）")
    ap.add_argument("--dates", nargs="*", default=None, help="显式交易日 YYYYMMDD")
    ap.add_argument("--n-dates", type=int, default=4)
    ap.add_argument("--start", default="2026-06-01")
    ap.add_argument("--end", default="2026-09-10")
    ap.add_argument("--settle-days", type=int, default=SETTLE_DAYS_DEFAULT)
    ap.add_argument("--lookback", default="2025-05-01")
    ap.add_argument("--universe", choices=["official", "none"], default="official")
    ap.add_argument("--cfg", nargs="*", default=None, help="口径覆盖 形如 STD_DDOF=1")
    ap.add_argument("--out", default=None)
    ap.add_argument("--no-cache", action="store_true")
    args = ap.parse_args()

    if args.cfg:
        kw = {}
        for kv in args.cfg:
            k, v = kv.split("=")
            kw[k] = int(v) if v.lstrip("-").isdigit() else v
        X.set_cfg(**kw)
        print(f"  [cfg] {kw}")

    factors = args.factors or (PHASE_A_FACTORS if args.phase_a else alpha101_names())
    if args.phase_a and not args.dates:
        args.dates = ["20260811"]
        args.n_dates = 1
    dates = args.dates or pick_dates(args.start, args.end, args.settle_days, args.n_dates)
    if not dates:
        print("!! 无可比对交易日")
        return 1
    print(f"因子 {len(factors)} 个；交易日 {dates}")

    # ---- 官方值（先取，顺便得到官方股票全集）--------------------------------
    print("[1/4] 取官方因子值（单日全市场）…")
    off = official_panel(factors, dates, use_cache=not args.no_cache)
    if not off:
        print("!! 官方取数为空")
        return 1

    # ---- 面板 ---------------------------------------------------------------
    print("[2/4] 组装全市场面板…")
    panel = load_market(args.lookback, args.end, fields="core")
    panel = type(panel)(codes=panel.codes,
                        fields={k: v.loc[:pd.Timestamp(max(dates))]
                                for k, v in panel.fields.items()})

    # ---- 股票池掩码 ---------------------------------------------------------
    mask = None
    if args.universe == "official":
        codes = sorted({c for df in off.values() for c in df.columns})
        keep = panel.C.columns.intersection(codes)
        mask = pd.DataFrame(False, index=panel.C.index, columns=panel.C.columns)
        mask.loc[:, keep] = True                       # 默认全开（历史窗口完整）
        for d in dates:
            dt = pd.Timestamp(d)
            uni = set()
            for f in off:
                if dt in off[f].index:
                    uni |= set(off[f].loc[dt].dropna().index)
            if uni:
                row = panel.C.columns.isin(sorted(uni))
                mask.loc[dt, :] = row
        print(f"  [uni] 官方全集 {len(codes)} 只；面板 {len(panel.codes)} 只；"
              f"交集 {len(keep)} 只")
        miss = sorted(set(codes) - set(keep))
        if miss:
            print(f"  [uni] 官方有而面板缺失 {len(miss)} 只，例：{miss[:8]}")

    # ---- 本地计算（带缓存，重跑不必重算）------------------------------------
    print("[3/4] 本地求值…")
    import hashlib
    ckey = hashlib.sha1(json.dumps(
        [factors, dates, args.lookback, args.end, args.universe, "v2",
         {k: str(v) for k, v in X.CFG.items()}], sort_keys=True).encode()).hexdigest()[:16]
    lcache = CACHE / f"alpha101_local_{ckey}.pkl"
    if lcache.is_file() and not args.no_cache:
        local, errors = pd.read_pickle(lcache)
        print(f"    [cache] 本地结果缓存命中（{len(local)} 个因子）")
    else:
        local, errors = compute_local(panel, factors, dates, mask)
        if not args.no_cache:
            pd.to_pickle((local, errors), lcache)
    for f, msg in errors.items():
        print(f"    !! {f}: {msg}")

    # ---- 比对 ---------------------------------------------------------------
    print("[4/4] 比对…")
    have = [f for f in factors if f in local and f in off]
    d = safe_compare_family(FAMILY, local, off, have)
    xs = compare_xs(FAMILY, local, off, have)
    cols = ["factor", "verdict_med", "verdict", "n_overlap", "coverage",
            "max_abs_err", "med_rel_err", "corr"]
    merged = d[cols + ["p99_abs_err", "mean_abs_err", "official_mag",
                       "verdict_robust", "p99_rel_err", "mean_rel_err", "note"]].merge(
        xs[["factor", "verdict_xs", "spearman_med", "spearman_min", "n_stocks_med"]],
        on="factor", how="left")
    merged["n_distinct"] = [
        int(off[f].stack().dropna().nunique()) if f in off else -1 for f in merged["factor"]]
    merged["formula_fixed"] = merged["factor"].isin(FORMULA_FIXES)
    merged["attribution"] = [
        ("公式已修正（factor_desc 括号丢失）" if r["formula_fixed"] else "")
        or classify(r, formula_of(r["factor"])) for _, r in merged.iterrows()]
    if errors:
        merged = pd.concat([merged, pd.DataFrame([
            dict(factor=k, verdict_med="NO_DATA", verdict="NO_DATA", n_overlap=0,
                 coverage=0.0, max_abs_err=np.nan, med_rel_err=np.nan, corr=np.nan,
                 verdict_xs="NO_DATA", spearman_med=np.nan, spearman_min=np.nan,
                 attribution=f"未实现：{v}") for k, v in errors.items()])],
            ignore_index=True)

    with pd.option_context("display.width", 240, "display.max_rows", 200):
        print(merged[cols + ["verdict_xs", "spearman_med", "spearman_min",
                             "n_stocks_med", "attribution"]].to_string(
            index=False, float_format=lambda x: f"{x:.4g}"))
    print("\n[compare.py 口径] " + summarize(d))
    print("[横截面 Spearman 口径] " + summarize_xs(xs))
    for tag, col in (("verdict_med", "verdict_med"), ("verdict", "verdict"),
                     ("verdict_xs", "verdict_xs")):
        vc = merged[col].value_counts()
        print(f"  {tag:12s}：" + "  ".join(
            f"{k}={vc.get(k, 0)}" for k in ("EXACT", "GOOD", "APPROX", "FAIL", "NO_DATA")))
    print("\n[归因] " + "  ".join(
        f"{k}={v}" for k, v in merged["attribution"].value_counts().items()))

    out = Path(args.out) if args.out else (OUT_DIR / "alpha101_compare.csv")
    merged.to_csv(out, index=False)
    print(f"报告: {out}")

    # ---- 逐日横截面 Spearman（用于区分「已沉淀 / 未沉淀」尾部）---------------
    per_day = {}
    for f in have:
        lo, of = local.get(f), off.get(f)
        if lo is None or of is None:
            continue
        row = {}
        for t in lo.index.intersection(of.index):
            a, b = of.loc[t], lo.loc[t]
            m = a.notna() & b.notna() & np.isfinite(a) & np.isfinite(b)
            row[str(t.date())] = (a[m].corr(b[m], method="spearman")
                                  if m.sum() > 30 and a[m].nunique() > 1 else np.nan)
        per_day[f] = row
    if per_day:
        pdf = pd.DataFrame(per_day).T
        pdf.index.name = "factor"
        pdf.to_csv(OUT_DIR / "alpha101_spearman_by_date.csv")
        print("\n[逐日横截面 Spearman 均值] " + "  ".join(
            f"{c}={pdf[c].mean():.4f}" for c in pdf.columns))
        print(f"逐日 Spearman 明细: {OUT_DIR / 'alpha101_spearman_by_date.csv'}")

    # ---- 数值抽样对照（阶段 A 必需）----------------------------------------
    if args.phase_a:
        print("\n===== 数值抽样对照（本地 vs 官方）=====")
        for f in have:
            if f not in local or f not in off:
                continue
            l, o = local[f], off[f]
            idx = l.index.intersection(o.index)
            c = l.columns.intersection(o.columns)
            ll, oo = l.loc[idx, c].stack(), o.loc[idx, c].stack()
            j = pd.DataFrame({"local": ll, "official": oo}).dropna()
            j["abs_err"] = (j["local"] - j["official"]).abs()
            j = j.sort_values("abs_err")
            print(f"\n--- {f} ---  共同有效 {len(j)} 个 (stock,date)")
            print("  最吻合 3 个：")
            print(j.head(3).to_string(float_format=lambda x: f"{x:.10f}"))
            print("  最差 3 个：")
            print(j.tail(3).to_string(float_format=lambda x: f"{x:.10f}"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
