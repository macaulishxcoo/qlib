#!/usr/bin/env python
"""批次三（Liquidity 部分）—— 换手率/成交额类流动性因子。

════════════════════════════════════════════════════════════════════════
公式要点与陷阱
════════════════════════════════════════════════════════════════════════
公式里反复出现的两个中间量需要标定：

1. ``DailyTurnoverRate = TurnoverVolume / AShares``
   ``AShares`` 未定义是**总股本 / 流通股本 / 自由流通股本**，故本脚本试多种候选：

   | 候选 | 依据 |
   |---|---|
   | ``TURNOVER_RATE / 100`` | Tushare 换手率 = 成交量/流通股本，单位 % |
   | ``TURNOVER_RATE_F / 100`` | 自由流通换手率 |
   | ``V_raw / TOTAL_SHARE`` | 成交量(股) / 总股本(股) |
   | ``V_raw / FLOAT_SHARE`` | 等价于 ``TURNOVER_RATE/100``（用于交叉校验单位换算） |
   | ``V_raw / FREE_SHARE`` | 等价于 ``TURNOVER_RATE_F/100`` |

   单位换算（务必注意）：
   - Tushare ``daily.vol`` 单位是 **手**（1 手 = 100 股）
   - ``daily_basic.total_share`` / ``float_share`` / ``free_share`` 单位是 **万股**
   - 故 ``V_raw / TOTAL_SHARE`` 与 ``TURNOVER_RATE`` 相差一个常数，
     对 MA/StdDev 后的**排序**影响不大，但对绝对值有影响 —— 必须实测。

2. ⚠️ ``ts_env.TSPanel`` 的 ``V`` / ``AMOUNT`` 字段**已经被乘过复权因子**
   （源码：``out[dst] = raw[src] * factor``）。流动性因子必须用**原始**成交量/成交额，
   故本脚本统一用 ``V / ADJ``、``AMOUNT / ADJ`` 还原。这是本批最容易踩的坑。

⚠️ **本脚本是独立交叉校验**，产出文件名刻意用 ``liquidity_turnover_verify*.csv``
（不以 ``_compare_settled.csv`` 结尾），**避免与 ``repro_liquidity_risk.py`` 的正式
60 因子报告争用** —— 汇总器优先采用覆盖更全的那份。两者在 17 个重叠因子上应给出
一致结论，可用于互相验证。

覆盖因子（17 个）：``avg_turnover_{5,10,20,21,42,63,126,252}d``、
``std_turnover_{21,42,63,126,252}d``、``turnover_ma_20d``、``turnover_ma_20d_120d``、
``amount_ma_20d``、``sum_abs_rtn_amount_20d``。

用法::

    python scripts/qdata/repro_liquidity.py
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

_SCRIPTS = Path(__file__).resolve().parents[1]
for p in (str(_SCRIPTS), str(_SCRIPTS / "jqdata"), str(_SCRIPTS / "qdata")):
    if p not in sys.path:
        sys.path.insert(0, p)

from jqdata.facsim.compare import compare_family, summarize  # noqa: E402
from qdata_env import QDataClient  # noqa: E402
from ts_env import TSPanel  # noqa: E402

FAMILY = "qdata_liquidity"
SETTLE_DAYS = 30

APPROX_FACTORS = [f"avg_turnover_{n}d" for n in (5, 10, 20, 21, 42, 63, 126, 252)]
STD_FACTORS = [f"std_turnover_{n}d" for n in (21, 42, 63, 126, 252)]
MISC_FACTORS = ["turnover_ma_20d", "turnover_ma_20d_120d",
                "amount_ma_20d", "sum_abs_rtn_amount_20d"]
IMPLEMENTED = APPROX_FACTORS + STD_FACTORS + MISC_FACTORS

VERDICT_ORDER = {"EXACT": 0, "GOOD": 1, "APPROX": 2, "FAIL": 3, "NO_DATA": 4}


# --------------------------------------------------------------------------
# 原始量还原与换手率候选
# --------------------------------------------------------------------------
def _raw_vol(p: TSPanel) -> pd.DataFrame:
    """原始成交量（手）—— 面板里的 V 已被乘过复权因子，须还原。"""
    return p.V / p.ADJ


def _raw_amount(p: TSPanel) -> pd.DataFrame:
    """原始成交额（千元）—— 同上。"""
    return p.AMOUNT / p.ADJ


def turnover_candidates(p: TSPanel) -> dict[str, pd.DataFrame]:
    """``DailyTurnoverRate`` 的候选口径。"""
    v = _raw_vol(p)
    out = {}
    if "TURNOVER_RATE" in p.fields:
        out["turnover_rate%"] = p.TURNOVER_RATE / 100.0
    if "TURNOVER_RATE_F" in p.fields:
        out["turnover_rate_f%"] = p.TURNOVER_RATE_F / 100.0
    if "TOTAL_SHARE" in p.fields:
        out["vol/total_share"] = v / (p.TOTAL_SHARE * 1e4 / 100.0)
    if "FLOAT_SHARE" in p.fields:
        out["vol/float_share"] = v / (p.FLOAT_SHARE * 1e4 / 100.0)
    if "FREE_SHARE" in p.fields:
        out["vol/free_share"] = v / (p.FREE_SHARE * 1e4 / 100.0)
    return out


def volcap_candidates(p: TSPanel) -> dict[str, pd.DataFrame]:
    """``VolCapRatio = TurnoverVolume / FloatMarketCap`` 的候选口径。

    ``FloatMarketCap = ClosePrice × FloatShares`` 即流通市值。``CIRC_MV`` 单位为万元，
    而成交量单位为手，故换算： ``股数 = 手 × 100``，``市值(元) = CIRC_MV × 1e4``。
    """
    v = _raw_vol(p)
    out = {}
    if "CIRC_MV" in p.fields:
        out["vol*100/(circ_mv*1e4)"] = v * 100.0 / (p.CIRC_MV * 1e4)
        out["vol/(circ_mv)"] = v / p.CIRC_MV
    out.update({f"dtr[{k}]": v2 for k, v2 in turnover_candidates(p).items()})
    return out


def build_variants(p: TSPanel) -> dict[str, dict[str, pd.DataFrame]]:
    """返回 ``factor -> {variant_name -> DataFrame}``。"""
    tcs = turnover_candidates(p)
    vcs = volcap_candidates(p)
    amt = _raw_amount(p)
    ret = p.PCT_CHG / 100.0 if "PCT_CHG" in p.fields else p.C.pct_change()

    V: dict[str, dict[str, pd.DataFrame]] = {}

    for f in APPROX_FACTORS:
        n = int(f[len("avg_turnover_"):-1])
        V[f] = {k: v.rolling(n).mean() for k, v in tcs.items()}

    for f in STD_FACTORS:
        n = int(f[len("std_turnover_"):-1])
        d: dict[str, pd.DataFrame] = {}
        for k, v in tcs.items():
            d[f"{k}|ddof1"] = v.rolling(n).std(ddof=1)
            d[f"{k}|ddof0"] = v.rolling(n).std(ddof=0)
        V[f] = d

    # turnover_ma_20d / _120d：-MA(VCR, short) 或 -MA(VCR,short)/MA(VCR,long)
    V["turnover_ma_20d"] = {}
    V["turnover_ma_20d_120d"] = {}
    for k, v in vcs.items():
        ma20 = v.rolling(20).mean()
        V["turnover_ma_20d"][f"{k}|short20"] = -ma20
        V["turnover_ma_20d_120d"][f"{k}|short20long120"] = -ma20 / v.rolling(120).mean()
        V["turnover_ma_20d_120d"][f"{k}|short20"] = -ma20

    # amount_ma_20d = Mean(TurnoverAmount, 20)
    # ⚠️ TurnoverAmount 单位是「元」：Tushare daily.amount 单位千元，故须 ×1e3。
    #    漏掉这个换算会让该因子产生 ~6.9× 的系统偏差（实测中位相对误差 0.67）。
    V["amount_ma_20d"] = {"raw_amount(元)": amt.rolling(20).mean() * 1e3,
                          "raw_amount(千元)": amt.rolling(20).mean(),
                          "adj_amount(千元)": p.AMOUNT.rolling(20).mean()}

    # sum_abs_rtn_amount_20d = Sum(|Return|,20) / Sum(TurnoverAmount,20) * 1e8
    num = ret.abs().rolling(20).sum()
    V["sum_abs_rtn_amount_20d"] = {
        "raw_amount(千元)": num / amt.rolling(20).sum() * 1e8,
        "raw_amount(元)": num / (amt.rolling(20).sum() * 1e3) * 1e8,
        "adj_amount": num / p.AMOUNT.rolling(20).sum() * 1e8,
    }
    return V


# --------------------------------------------------------------------------
# 官方值
# --------------------------------------------------------------------------
def official_panel(codes: list[str], factors: list[str], start: str, end: str,
                   use_cache: bool = True) -> dict[str, pd.DataFrame]:
    import pickle
    cache = Path("output/qdata_factor_repro/cache")
    cache.mkdir(parents=True, exist_ok=True)
    cname = cache / f"official_liq_{abs(hash((tuple(codes), tuple(factors), start, end))) % 10**12}.pkl"
    if use_cache and cname.is_file():
        print("  [qdata] 官方因子缓存命中")
        return pickle.load(open(cname, "rb"))
    cli = QDataClient()
    s_c, e_c = start.replace("-", ""), end.replace("-", "")
    rec: dict[str, dict[str, pd.Series]] = {f: {} for f in factors}
    for c in codes:
        for f in factors:
            try:
                rows = cli.factor_value(factor_name=f, ts_code=c,
                                        start_date=s_c, end_date=e_c)
            except Exception as e:  # noqa: BLE001
                print(f"   [warn] {f} {c}: {str(e)[:50]}")
                continue
            if not rows:
                continue
            d = pd.DataFrame(rows).drop_duplicates(subset=["trade_date"])
            d["trade_date"] = pd.to_datetime(d["trade_date"])
            rec[f][c] = d.set_index("trade_date")["factor_value"].astype(float)
    out = {f: pd.DataFrame(v).sort_index() for f, v in rec.items() if v}
    if use_cache:
        pickle.dump(out, open(cname, "wb"))
    print(f"  [qdata] 官方因子已取回并缓存（{len(out)} 个因子）")
    return out


def main() -> int:
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--codes", nargs="*",
                    default=["600519.SH", "000001.SZ", "000002.SZ",
                             "600036.SH", "002415.SZ", "000651.SZ"])
    ap.add_argument("--start", default="2026-06-01")
    ap.add_argument("--end", default="2026-09-10")
    ap.add_argument("--lookback", default="2024-06-01")
    ap.add_argument("--settle-days", type=int, default=SETTLE_DAYS)
    args = ap.parse_args()

    from ts_env import load_panel
    panel = load_panel(args.codes, args.lookback, args.end)
    print(f"  面板字段: {sorted(panel.fields)}")
    variants = build_variants(panel)
    off_all = official_panel(args.codes, IMPLEMENTED, args.start, args.end)

    def pick(offi: dict) -> tuple[dict, pd.DataFrame, dict]:
        """对每个因子选出最优变体。

        ⚠️ ``chosen`` 必须直接用**最优**变体名构造。早期版本写成
        ``{r["factor"]: r["variant"] for r in rows}``，而 ``rows`` 含全部候选、
        最优在最前 —— 字典推导会取到**最后一个（最差）**变体，
        导致"选中口径"标签与实际用于比对的 ``best`` 不一致（结果对、标签错）。
        """
        best: dict[str, pd.DataFrame] = {}
        chosen: dict[str, str] = {}
        rows = []
        for f in IMPLEMENTED:
            if f not in variants or f not in offi:
                continue
            scored = []
            for vn, df in variants[f].items():
                rep = compare_family(FAMILY, {f: df}, {f: offi[f]}, [f]).iloc[0]
                scored.append((VERDICT_ORDER.get(rep["verdict_med"], 9),
                               rep["med_rel_err"] if np.isfinite(rep["med_rel_err"]) else 9.9,
                               vn, df, rep))
            if not scored:
                continue
            scored.sort(key=lambda x: (x[0], x[1]))
            _, _, vn, df, _rep = scored[0]
            best[f] = df
            chosen[f] = vn
            for _, _, vn2, _, r2 in scored:
                d2 = r2.to_dict()
                d2["factor"], d2["variant"] = f, vn2
                d2["chosen"] = (vn2 == vn)
                rows.append(d2)
        return best, pd.DataFrame(rows), chosen

    out_dir = Path("output/qdata_factor_repro")

    def report(title: str, offi: dict, tag: str) -> pd.DataFrame:
        local, allv, chosen = pick(offi)
        print(f"\n===== {title} =====")
        print("选中的口径:")
        for f in IMPLEMENTED:
            if f in chosen:
                print(f"    {f:26s} {chosen[f]}")
        d = compare_family(FAMILY, local, offi, [f for f in IMPLEMENTED if f in local])
        cols = ["factor", "verdict_med", "verdict", "n_overlap", "coverage",
                "max_abs_err", "med_rel_err", "corr"]
        with pd.option_context("display.width", 200):
            print(d[cols].to_string(index=False, float_format=lambda x: f"{x:.4g}"))
        print(summarize(d))
        d.to_csv(out_dir / f"liquidity_turnover_verify{tag}.csv", index=False)
        allv.to_csv(out_dir / f"liquidity_turnover_variants{tag}.csv", index=False)
        # 只保留"选中变体"的全量变体表，避免重复行
        allv[allv["chosen"] == True].to_csv(
            out_dir / f"liquidity_turnover_variants_best{tag}.csv", index=False)
        print(f"报告: {out_dir / f'liquidity_turnover_verify{tag}.csv'}")
        return d

    report("全窗口（含 qdata 未沉淀尾部）", off_all, "")
    if args.settle_days > 0:
        cut = pd.Timestamp(args.end) - pd.Timedelta(days=args.settle_days)
        print(f"\n[settle] 排除 {cut.date()} 之后的 {args.settle_days} 个自然日")
        report(f"已沉淀窗口（--settle-days {args.settle_days}，判定口径）",
               {k: v.loc[:cut] for k, v in off_all.items()}, "_settled")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
