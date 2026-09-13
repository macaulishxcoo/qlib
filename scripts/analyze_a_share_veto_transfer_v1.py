#!/usr/bin/env python
"""毒尾否决的【迁移检验】: 它对别的 alpha 源是否也有效?

问题: 此前 12 个变体全部只测过同一个底仓(五因子)。若否决只对五因子有效,
      说明它可能是与该底仓共同拟合出来的, 而非通用的风险因子。

做法: 换 5 个【完全不同的】alpha 源作为底仓, 每个都做"有无否决"对照:
        size_small  小市值 (-log total_mv)
        rev_20      20日反转 (-ret_20)
        rev_5       5日反转  (-ret_5)
        lowvol      低波动   (-std(cc_ret,20))
        lowturn     低换手   (-turnover_rate, 来自 daily_basic)

若否决在多数底仓上同样带来正增量 -> 通用机制;
若只在五因子上有效 -> 底仓特异, 过拟合嫌疑上升。

配置统一: 50万, top30, 行业cap3, 10交易日调仓, stress 成本, 复用缓存快照与同一回测器。
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

import backtest_a_share_value_growth_five_factor_industry_cap_v3 as v3  # noqa: E402
from backtest_a_share_value_growth_five_factor_industry_cap_v3 import (  # noqa: E402
    QLIB_DIR, BT_START, BT_END, signal_from_snapshots, run_backtest, ols_residual,
)
from backtest_a_share_five_factor_daily_execution_v1 import (  # noqa: E402
    OUT, TOP_K, CAP, build_toxic_rank, apply_veto, _to_ts_code,
)
from backtest_a_share_value_quality_monthly_dailygrid_v6 import DAILY_BASIC  # noqa: E402

CAPITAL = 500_000.0
SIGNALS = ["size_small", "rev_20", "rev_5", "lowvol", "lowturn", "lowprice"]


def log(m):
    print(m, flush=True)


def build_alt_panels(snap_dates: pd.DatetimeIndex) -> dict:
    """构造 5 个替代 alpha 的原始分 (列=ts_code)。"""
    from qlib.data import D
    df = D.features(D.instruments(market="all"), ["$close"],
                    start_time=str(BT_START.date()), end_time=str(BT_END.date()), freq="day")
    C = df["$close"].unstack(0).sort_index().astype("float32")
    C.columns = [_to_ts_code(c) for c in C.columns]
    C = C.where(C > 0)
    cc = C / C.shift(1) - 1.0

    db = pd.read_csv(DAILY_BASIC, compression="gzip",
                     usecols=["trade_date", "ts_code", "total_mv", "turnover_rate"])
    db["datetime"] = pd.to_datetime(db["trade_date"].astype(str), format="%Y%m%d")

    panels = {}
    idx = C.index
    raw = {
        "rev_20": -(C / C.shift(20) - 1.0),
        "rev_5": -(C / C.shift(5) - 1.0),
        "lowvol": -cc.rolling(20, min_periods=10).std(),
    }
    for k, v in raw.items():
        panels[k] = v.reindex(snap_dates)

    mv = db.pivot_table(index="datetime", columns="ts_code", values="total_mv", aggfunc="sum")
    to = db.pivot_table(index="datetime", columns="ts_code", values="turnover_rate", aggfunc="sum")
    panels["size_small"] = (-np.log(mv.where(mv > 0))).reindex(snap_dates)
    panels["lowturn"] = (-to).reindex(snap_dates)
    # 低名义价格: 用于检验"价格可行性过滤"里那部分选股贡献是否真是 alpha。
    # 注意这是【截面价格排序】, 不是"排除高价"这个可行性约束本身。
    panels["lowprice"] = (-C).reindex(snap_dates)
    log(f"      panels: { {k: v.shape for k, v in panels.items()} }")
    return panels


def substitute_scores(snaps: dict, panel: pd.DataFrame) -> dict:
    """把快照的 neutral_composite 换成替代 alpha (同样做 l1_code + log_size 中性化)。"""
    out = {}
    for date, frame in snaps.items():
        f = frame.copy()
        if date in panel.index:
            f["_alt"] = panel.loc[date].reindex(f["ts_code"]).to_numpy(dtype=float)
        else:
            f["_alt"] = np.nan
        valid = f.dropna(subset=["_alt", "log_size", "l1_code"])
        if len(valid) < 50:
            out[date] = f.assign(neutral_composite=np.nan)
            continue
        resid = ols_residual(valid["_alt"], valid["l1_code"], valid["log_size"])
        f["neutral_composite"] = resid.reindex(f.index)
        out[date] = f
    return out


def main() -> int:
    qlib.init(provider_uri=str(QLIB_DIR), region=REG_CN)
    v3.ACCOUNT = int(CAPITAL)
    calendar = pd.DatetimeIndex(pd.to_datetime(
        pd.read_csv(QLIB_DIR / "calendars" / "day.txt", header=None)[0]))

    snap_10 = pd.read_pickle(OUT / "snapshots_500k_10day.pkl")
    dates = pd.DatetimeIndex(sorted(snap_10.keys()))
    log(f"snapshots: {len(snap_10)}  dates {dates[0].date()}..{dates[-1].date()}")

    log("[1/3] building alternative alpha panels ...")
    panels = build_alt_panels(dates)

    log("[2/3] toxic panel ...")
    toxic = build_toxic_rank(calendar)

    log("[3/3] backtesting 5 alphas x {no-veto, veto} ...")
    rows = []
    for name in SIGNALS:
        base = substitute_scores(snap_10, panels[name])
        variants = {"noveto": base, "veto": apply_veto(base, toxic, TOP_K, CAP)}
        for tag, snaps in variants.items():
            sig = signal_from_snapshots(snaps, calendar, TOP_K, CAP)
            if len(sig) == 0:
                log(f"  {name:<11} {tag:<7} EMPTY")
                continue
            bt = run_backtest(sig, TOP_K)
            bt["alpha"] = name
            bt["variant"] = tag
            rows.append(bt)
            st = bt[bt["cost_scenario"] == "stress"].set_index("stage")
            log(f"  {name:<11} {tag:<7} full={st.loc['full','net_excess_annualized_return']:+.4f} "
                f"IR={st.loc['full','net_excess_ir']:+.3f} "
                f"holdout={st.loc['holdout','net_excess_annualized_return']:+.4f} "
                f"new_cov={st.loc['new_coverage','net_excess_annualized_return']:+.4f}")

    bt = pd.concat(rows, ignore_index=True)
    bt.to_csv(OUT / "veto_transfer_summary.csv", index=False)

    stress = bt[bt["cost_scenario"] == "stress"]
    log("\n=== 否决在各底仓上的增量 (stress, 净超额) ===")
    log(f"{'底仓':<12}{'无否决':>10}{'有否决':>10}{'增量':>10}"
        f"{'holdout增量':>13}{'new_cov增量':>13}")
    summary, pos = {}, 0
    for name in SIGNALS:
        s = stress[stress["alpha"] == name].pivot_table(
            index="stage", columns="variant", values="net_excess_annualized_return")
        if s.empty or "veto" not in s.columns:
            continue
        d = s["veto"] - s["noveto"]
        summary[name] = {k: float(d[k]) for k in d.index}
        pos += int(d["full"] > 0)
        log(f"{name:<12}{s.loc['full','noveto']:>+10.4f}{s.loc['full','veto']:>+10.4f}"
            f"{d['full']:>+10.4f}{d['holdout']:>+13.4f}{d['new_coverage']:>+13.4f}")

    verdict = "transfers" if pos >= 4 else ("partially_transfers" if pos >= 3 else "base_specific")
    log(f"\n>>> {pos}/{len(summary)} 个底仓上否决的全期增量为正 -> {verdict}")
    (OUT / "veto_transfer_decision.json").write_text(json.dumps(
        {"verdict": verdict, "n_positive": pos, "n_alphas": len(summary),
         "detail": summary}, indent=2, ensure_ascii=False))
    log(f"=== VERDICT: {verdict} ===")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
