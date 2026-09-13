#!/usr/bin/env python
"""毒尾否决 —— 定义稳健性检验 (防止"只有我那一组参数有效"的过拟合)。

背景: 五因子+否决线得到 full 净超额 8.36% -> 14.08%。但否决定义
(id_mom_20 / id_vol_20 / on_vol_20 复合, 阈值 0.90) 是我看过 2018-2026 数据后选的,
存在"参数过拟合"风险。

检验逻辑: 若【一族】毒尾定义都能给出相近增益 -> 是真实效应;
          若【只有】我那一组有效 -> 过拟合。

关键变体: `comp_cc` —— 完全用 close-to-close 数据构造的毒尾分
(20日涨幅 + 20日波动 + 20日振幅), 不含任何隔夜/日内分解。
若它与原复合分效果相当, 说明效应来自"避开极端近期涨幅"这一通用机制,
而非我那条隔夜/日内构造的偶然产物。
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

from backtest_a_share_value_growth_five_factor_industry_cap_v3 import (  # noqa: E402
    QLIB_DIR, BT_START, BT_END, signal_from_snapshots, run_backtest,
)
from backtest_a_share_five_factor_daily_execution_v1 import (  # noqa: E402
    OUT, TOP_K, CAP, _to_ts_code,
)

VARIANTS = [
    # (名称, 构造key, 阈值)
    ("comp_id_q90 (原)",      "comp_id", 0.90),
    ("comp_id_q80",           "comp_id", 0.80),
    ("comp_id_q85",           "comp_id", 0.85),
    ("comp_id_q95",           "comp_id", 0.95),
    ("id_mom_20_q90",         "id_mom_20", 0.90),
    ("id_vol_20_q90",         "id_vol_20", 0.90),
    ("on_vol_20_q90",         "on_vol_20", 0.90),
    ("comp_cc_q90 (纯c2c)",   "comp_cc", 0.90),
    ("comp_cc_q80",           "comp_cc", 0.80),
    ("ret_20_q90 (纯涨幅)",   "ret_20", 0.90),
    ("vol_20_q90 (纯波动)",   "vol_20", 0.90),
    ("amp_20_q90 (纯振幅)",   "amp_20", 0.90),
]


def log(m):
    print(m, flush=True)


def build_panels() -> dict:
    from qlib.data import D
    inst = D.instruments(market="all")
    df = D.features(inst, ["$open", "$high", "$low", "$close", "$volume"],
                    start_time=str(BT_START.date()), end_time=str(BT_END.date()), freq="day")
    df.columns = ["open", "high", "low", "close", "volume"]
    df = df[~df.index.duplicated()]
    W = {}
    for c in df.columns:
        m = df[c].unstack(0).sort_index().astype("float32")
        W[c] = m.where(m > 0) if c != "volume" else m
    O, H, L, C, V = W["open"], W["high"], W["low"], W["close"], W["volume"]

    on1 = O / C.shift(1) - 1.0
    id1 = C / O - 1.0
    cc1 = C / C.shift(1) - 1.0

    raw = {
        "id_mom_20": id1.rolling(20, min_periods=10).sum(),
        "id_vol_20": id1.rolling(20, min_periods=10).std(),
        "on_vol_20": on1.rolling(20, min_periods=10).std(),
        "ret_20": C / C.shift(20) - 1.0,
        "vol_20": cc1.rolling(20, min_periods=10).std(),
        "amp_20": ((H - L) / C).rolling(20, min_periods=10).mean(),
    }
    R = {k: v.rank(axis=1, pct=True) for k, v in raw.items()}
    R["comp_id"] = (R["id_mom_20"] + R["id_vol_20"] + R["on_vol_20"]) / 3.0
    R["comp_cc"] = (R["ret_20"] + R["vol_20"] + R["amp_20"]) / 3.0
    out = {}
    for k, v in R.items():
        v = v.copy()
        v.columns = [_to_ts_code(c) for c in v.columns]
        out[k] = v
    log(f"      panels: {sorted(out)}")
    return out


def apply_veto(snapshots: dict, rank_panel: pd.DataFrame, q: float) -> dict:
    out = {}
    hit = tot = 0
    for date, frame in snapshots.items():
        f = frame.copy()
        if date in rank_panel.index:
            tr = rank_panel.loc[date].reindex(f["ts_code"]).to_numpy(dtype=float)
        else:
            tr = np.full(len(f), np.nan)
        is_veto = np.nan_to_num(tr, nan=-1.0) > q
        cand = f["neutral_composite"].notna().to_numpy()
        hit += int((cand & is_veto).sum())
        tot += int(cand.sum())
        f.loc[is_veto, "neutral_composite"] = -999.0
        out[date] = f
    return out, (hit, tot)


def main() -> int:
    qlib.init(provider_uri=str(QLIB_DIR), region=REG_CN)
    calendar = pd.DatetimeIndex(pd.to_datetime(
        pd.read_csv(QLIB_DIR / "calendars" / "day.txt", header=None)[0]))

    cache = OUT / "snapshots_cache.pkl"
    if not cache.exists():
        raise SystemExit(f"missing snapshot cache: {cache}")
    snap_m, snap_d = pd.read_pickle(cache)
    log(f"snapshots: 月末 {len(snap_m)} ; 10日 {len(snap_d)}")

    log("[1/2] building rank panels ...")
    panels = build_panels()

    log("[2/2] running variants ...")
    rows = []
    # 基线 B (10日, 无否决)
    sig_b = signal_from_snapshots(snap_d, calendar, TOP_K, CAP)
    bt_b = run_backtest(sig_b, TOP_K)
    bt_b["variant"] = "B_10day_noveto"
    rows.append(bt_b)
    log("  --- B_10day_noveto ---")

    for name, key, q in VARIANTS:
        snaps, (hit, tot) = apply_veto(snap_d, panels[key], q)
        sig = signal_from_snapshots(snaps, calendar, TOP_K, CAP)
        if len(sig) == 0:
            log(f"  --- {name}: empty signal, skipped")
            continue
        bt = run_backtest(sig, TOP_K)
        bt["variant"] = name
        rows.append(bt)
        st = bt[bt["cost_scenario"] == "stress"].set_index("stage")
        log(f"  --- {name:<22} mask={hit/max(tot,1):.3f}  "
            f"full={st.loc['full','net_excess_annualized_return']:+.4f} "
            f"IR={st.loc['full','net_excess_ir']:+.3f} "
            f"holdout={st.loc['holdout','net_excess_annualized_return']:+.4f}")

    bt = pd.concat(rows, ignore_index=True)
    bt.to_csv(OUT / "veto_robustness_summary.csv", index=False)

    stress = bt[bt["cost_scenario"] == "stress"]
    base = stress[stress["variant"] == "B_10day_noveto"].set_index("stage")
    log("\n=== 各变体相对 B 的净超额增量 (stress) ===")
    log(f"{'variant':<24}{'full':>10}{'holdout':>10}{'new_cov':>10}{'dev':>10}{'full_IR':>9}")
    summary = {}
    for name in ["B_10day_noveto"] + [v[0] for v in VARIANTS]:
        s = stress[stress["variant"] == name].set_index("stage")
        if s.empty:
            continue
        gains = {k: float(s.loc[k, "net_excess_annualized_return"]
                         - base.loc[k, "net_excess_annualized_return"])
                 for k in ("full", "holdout", "new_coverage", "development")}
        summary[name] = {**gains,
                         "full_net": float(s.loc["full", "net_excess_annualized_return"]),
                         "full_IR": float(s.loc["full", "net_excess_ir"])}
        log(f"{name:<24}{gains['full']:>+10.4f}{gains['holdout']:>+10.4f}"
            f"{gains['new_coverage']:>+10.4f}{gains['development']:>+10.4f}"
            f"{summary[name]['full_IR']:>9.3f}")

    gains_all = [v["full"] for k, v in summary.items() if k != "B_10day_noveto"]
    pos = sum(1 for g in gains_all if g > 0)
    log(f"\n>>> {pos}/{len(gains_all)} 个变体的全期增量为正; "
        f"中位数 {np.median(gains_all):+.4f}; 区间 [{min(gains_all):+.4f}, {max(gains_all):+.4f}]")
    verdict = ("definition_robust" if pos >= len(gains_all) * 0.75
               else "definition_sensitive")
    (OUT / "veto_robustness.json").write_text(json.dumps(
        {"verdict": verdict, "n_positive": pos, "n_variants": len(gains_all),
         "median_gain": float(np.median(gains_all)), "detail": summary},
        indent=2, ensure_ascii=False))
    log(f"\n=== VERDICT: {verdict} ===")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
