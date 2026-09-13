#!/usr/bin/env python
"""五因子基本面信号 —— 日频执行 + 毒尾否决 叠加实验。

协议: research/protocols/a_share_five_factor_daily_execution_protocol_v1.md

问题: 五因子是本项目唯一有实测净 alpha 的信号, 但既有实现是【月频调仓】。
      本脚本只改两件事, alpha 本身完全不动:
        ① 把调仓网格由月末加密到每 10 个交易日
        ② 叠加毒尾否决 (复用 v1 冻结定义: toxic > 0.90)
      三臂对照隔离两个改动各自的贡献:
        A 月末网格 + 无否决   = 既有基线 (复现)
        B 10日网格 + 无否决   = 只加密
        C 10日网格 + 否决     = 加密 + 否决
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import qlib  # noqa: E402
from qlib.config import REG_CN  # noqa: E402

from load_financials_extended_v1 import load_financials_extended  # noqa: E402
from analyze_a_share_value_quality_level_factors_extension_v1 import build_snapshot  # noqa: E402
from backtest_a_share_value_quality_monthly_sensitivity_v4 import load_amount_avg  # noqa: E402
from run_daily_signal_pipeline_v1 import (  # noqa: E402
    st_codes_at, qlib_symbol, load_g2_series, g2_at,
)
from backtest_a_share_value_growth_five_factor_industry_cap_v3 import (  # noqa: E402
    QLIB_DIR, STYLE_DIR, ST_INTERVALS, BT_START, BT_END,
    composite5_score, build_snapshots, signal_from_snapshots, run_backtest,
    ols_residual,
)

OUT = HERE.parent / "output" / "analysis_fundamental" / "a_share_five_factor_daily_execution_v1"
OUT.mkdir(parents=True, exist_ok=True)

STEP = 10                 # 日频执行: 每 10 个交易日
TOP_K = 30
CAP = 3
VETO_Q = 0.90             # 与毒尾否决线 v1 冻结值一致
DAILY_BASIC = HERE.parent / "data" / "external" / "tushare" / "a_share_daily_basic_pit_v1" / "normalized"


def log(m):
    print(m, flush=True)


def build_ten_day_grid(calendar: pd.DatetimeIndex) -> tuple[pd.DataFrame, pd.DataFrame]:
    """每 STEP 个交易日一个调仓日 (替代月末网格)。"""
    from backtest_a_share_value_quality_monthly_dailygrid_v6 import DAILY_BASIC as DB_PATH
    db = pd.read_csv(DB_PATH, compression="gzip",
                     usecols=["trade_date", "ts_code", "total_mv", "total_share", "dv_ttm"])
    db["datetime"] = pd.to_datetime(db["trade_date"].astype(str), format="%Y%m%d")
    cal = calendar[(calendar >= BT_START) & (calendar <= BT_END)]
    rebal = cal[::STEP]
    have = set(db["datetime"].unique())
    rebal = pd.DatetimeIndex([d for d in rebal if d in have])
    grid = pd.DataFrame({"rebalance_date": rebal.values, "asof_date": rebal.values})
    size_daily = db[db["datetime"].isin(rebal)].copy()
    size_daily["asof_date"] = size_daily["datetime"]
    size_daily = size_daily[["ts_code", "asof_date", "total_mv", "total_share", "dv_ttm"]]
    size_daily["size_control"] = size_daily.groupby("asof_date")["total_mv"].rank(pct=True)
    return grid, size_daily


def _to_ts_code(qlib_code: str) -> str:
    """qlib 代码 -> tushare ts_code。D.features 返回的索引已经是 qlib 代码
    (SH600000), 不能再用 qlib_symbol 转一次 (那是 ts_code -> qlib 的方向)。"""
    ex, num = qlib_code[:2], qlib_code[2:]
    return f"{num}.{ex}"


def build_toxic_rank(calendar: pd.DatetimeIndex, end: str | None = None) -> pd.DataFrame:
    """毒尾分 (与毒尾否决线 v1 完全一致的定义), 返回 日期 x **ts_code** 的 pct rank。

    end: 结束日期, 默认 BT_END。生成实盘信号时须传最新日期,
         否则毒尾面板会在 BT_END 截止, 导致最新日无法做否决 (曾因此静默漏掉否决)。
    """
    from qlib.data import D
    inst = D.instruments(market="all")
    end_s = end if end is not None else str(BT_END.date())
    df = D.features(inst, ["$open", "$close", "$volume"],
                    start_time=str(BT_START.date()), end_time=end_s, freq="day")
    df.columns = ["open", "close", "volume"]
    df = df[~df.index.duplicated()]
    O = df["open"].unstack(0).sort_index().astype("float32")
    C = df["close"].unstack(0).sort_index().astype("float32")
    O = O.where(O > 0)
    C = C.where(C > 0)
    on1 = O / C.shift(1) - 1.0
    id1 = C / O - 1.0
    toxic = (id1.rolling(20, min_periods=10).sum().rank(axis=1, pct=True)
             + id1.rolling(20, min_periods=10).std().rank(axis=1, pct=True)
             + on1.rolling(20, min_periods=10).std().rank(axis=1, pct=True)) / 3.0
    log(f"      toxic rank panel: {toxic.shape[0]} 日 x {toxic.shape[1]} 只")
    toxic.columns = [_to_ts_code(c) for c in toxic.columns]
    return toxic


def apply_veto(snapshots: dict, toxic: pd.DataFrame, top_k: int, cap: int) -> dict:
    """在快照上施加否决: 将 toxic>0.90 的候选 score 置 -999 (与行业内 cap 同机制)。"""
    out = {}
    masked_total, base_total = 0, 0
    for date, frame in snapshots.items():
        f = frame.copy()
        if date in toxic.index:
            tr = toxic.loc[date].reindex(f["ts_code"]).to_numpy(dtype=float)
        else:
            tr = np.full(len(f), np.nan)
        is_veto = np.nan_to_num(tr, nan=-1.0) > VETO_Q
        cand = f["neutral_composite"].notna().to_numpy()
        base_total += int(cand.sum())
        masked_total += int((cand & is_veto).sum())
        f.loc[is_veto, "neutral_composite"] = -999.0
        out[date] = f
    log(f"      否决屏蔽候选: {masked_total:,} / {base_total:,} "
        f"({masked_total / max(base_total,1):.3f})")
    return out


def main() -> int:
    qlib.init(provider_uri=str(QLIB_DIR), region=REG_CN)
    calendar = pd.DatetimeIndex(pd.to_datetime(
        pd.read_csv(QLIB_DIR / "calendars" / "day.txt", header=None)[0]))

    log("[1/4] loading shared data ...")
    fin = load_financials_extended()
    fin_g2 = load_g2_series()
    industry = pd.read_csv(STYLE_DIR / "industry_l1_effective_intervals.csv.gz",
                           compression="gzip", dtype=str)
    industry["in_date"] = pd.to_datetime(industry["in_date"], errors="coerce")
    industry["out_date"] = pd.to_datetime(industry["out_date"], errors="coerce")
    st = pd.read_csv(ST_INTERVALS, compression="gzip", parse_dates=["start_date", "end_date"])

    from backtest_a_share_value_quality_monthly_dailygrid_v6 import build_daily_grid
    grid_m, size_m = build_daily_grid()
    grid_m = grid_m[(grid_m["rebalance_date"] >= BT_START) & (grid_m["rebalance_date"] <= BT_END)]
    grid_d, size_d = build_ten_day_grid(calendar)
    log(f"      月末网格 {len(grid_m)} 期 ; 10日网格 {len(grid_d)} 期")

    universe = sorted(set(size_m["ts_code"]) | set(size_d["ts_code"]))
    amount_avg = load_amount_avg(universe, calendar)

    log("[2/4] building snapshots ...")
    cache = OUT / "snapshots_cache.pkl"
    if cache.exists():
        snap_m, snap_d = pd.read_pickle(cache)
        log(f"      [cache hit] 月末 {len(snap_m)} ; 10日 {len(snap_d)}")
    else:
        import time as _t
        t0 = _t.time()
        snap_m = build_snapshots(fin, fin_g2, grid_m, industry, size_m, st, amount_avg)
        log(f"      月末快照 {len(snap_m)} ({_t.time()-t0:.0f}s)")
        t0 = _t.time()
        snap_d = build_snapshots(fin, fin_g2, grid_d, industry, size_d, st, amount_avg)
        log(f"      10日快照 {len(snap_d)} ({_t.time()-t0:.0f}s)")
        pd.to_pickle((snap_m, snap_d), cache)
        log(f"      [cached] {cache}")

    log("[3/4] toxic veto overlay ...")
    toxic = build_toxic_rank(calendar)
    snap_dv = apply_veto(snap_d, toxic, TOP_K, CAP)

    # --- 前瞻性检验: 用【上一交易日】的毒尾分做否决 ---
    # 毒尾分用 close(asof_date) 计算。若 qlib 以 open(asof_date) 成交, 则同日使用
    # 即为 1 日前瞻。把毒尾分整体滞后 1 个交易日, 若增量仍在, 说明不是前瞻造成的。
    toxic_lag = toxic.shift(1)
    log("      [look-ahead check] 使用滞后 1 日的毒尾分重建 C 臂")
    snap_dv_lag = apply_veto(snap_d, toxic_lag, TOP_K, CAP)

    log("[4/4] backtesting 3 arms ...")
    arms = [("A_monthly_noveto", snap_m, "monthly"),
            ("B_10day_noveto", snap_d, "10day"),
            ("C_10day_veto", snap_dv, "10day"),
            ("D_10day_veto_lag1", snap_dv_lag, "10day")]
    all_bt = []
    for name, snaps, freq in arms:
        sig = signal_from_snapshots(snaps, calendar, TOP_K, CAP)
        log(f"  --- {name}: signal rows={len(sig):,} ---")
        bt = run_backtest(sig, TOP_K)
        bt["arm"] = name
        bt["freq"] = freq
        all_bt.append(bt)
        for _, r in bt.iterrows():
            if r["cost_scenario"] == "stress":
                log(f"      {r['stage']:<10} net={r['net_excess_annualized_return']:+.4f} "
                    f"IR={r['net_excess_ir']:+.3f} MDD={r['net_excess_max_drawdown']:+.4f}")
    bt = pd.concat(all_bt, ignore_index=True)
    bt.to_csv(OUT / "backtest_summary.csv", index=False)

    log("\n=== 三臂对照 (stress) ===")
    piv = bt[bt["cost_scenario"] == "stress"].pivot_table(
        index="stage", columns="arm",
        values=["net_excess_annualized_return", "net_excess_ir", "net_excess_max_drawdown"])
    log(piv.round(4).to_string())

    # 判定: C 相对 A 的增量, 以及 C 相对 B 的增量 (否决的独立贡献)
    def get(arm, stage, col):
        r = bt[(bt["arm"] == arm) & (bt["stage"] == stage) & (bt["cost_scenario"] == "stress")]
        return float(r.iloc[0][col]) if len(r) else np.nan

    summary = {}
    for stage in ("full", "holdout", "new_coverage", "development", "confirmation"):
        a = get("A_monthly_noveto", stage, "net_excess_annualized_return")
        b = get("B_10day_noveto", stage, "net_excess_annualized_return")
        c = get("C_10day_veto", stage, "net_excess_annualized_return")
        d = get("D_10day_veto_lag1", stage, "net_excess_annualized_return")
        summary[stage] = {"A_monthly_noveto": a, "B_10day_noveto": b, "C_10day_veto": c,
                          "D_10day_veto_lag1": d,
                          "daily_exec_gain": b - a, "veto_gain": c - b,
                          "veto_gain_lag1": d - b, "total_gain": c - a,
                          "C_IR": get("C_10day_veto", stage, "net_excess_ir"),
                          "D_IR": get("D_10day_veto_lag1", stage, "net_excess_ir"),
                          "A_IR": get("A_monthly_noveto", stage, "net_excess_ir")}
    log("\n=== 增量分解 (净超额, stress) ===")
    log(f"{'stage':<14}{'A基线':>9}{'B日频':>9}{'C否决':>9}{'D滞后1日':>10}"
        f"{'日频':>8}{'否决':>8}{'否决(滞后)':>11}")
    for k, v in summary.items():
        log(f"{k:<14}{v['A_monthly_noveto']:>+9.4f}{v['B_10day_noveto']:>+9.4f}"
            f"{v['C_10day_veto']:>+9.4f}{v['D_10day_veto_lag1']:>+10.4f}"
            f"{v['daily_exec_gain']:>+8.4f}{v['veto_gain']:>+8.4f}{v['veto_gain_lag1']:>+11.4f}")

    (OUT / "decision.json").write_text(json.dumps({
        "step": STEP, "top_k": TOP_K, "cap": CAP, "veto_q": VETO_Q,
        "increments": summary,
        "note": "alpha 定义未改动, 只改调仓网格与叠加否决",
    }, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
