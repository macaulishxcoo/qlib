#!/usr/bin/env python3
"""指数定期调整纳入/剔除效应检验 v1（post-adjustment drift）。

协议：research/protocols/a_share_index_adjustment_protocol_v1.md

研究问题
--------
中证指数（csi300/500/800/1000）6/12 月定期调整成分：以月末快照确认纳入名单，
T+1 开盘入场、持有 20/40/60 日，纳入组相对对照组（既有成分）是否存在方向
一致、显著为正的市场调整超额？

口径
----
- 母池：沪深普通 A 股（all.txt 剔北交所/指数/B 股）
- 事件：a_share_index_membership_pit_v1 月末快照差分（纳入/剔除/对照）
- 主检验：定期调整批次（5→6 月、11→12 月），H=40
- 标签：正确 open-to-open `open[t+1+h]/open[t+1]−1`，超额 = − SH000852
- 窗口：2016-01 ~ 2026-07（约 84 个定期批次）

输出（拒绝覆盖非空目录）
------------------------
output/analysis_static/a_share_index_adjustment_v1/
  event_sets.csv / excess_by_group.csv / batch_stability.csv
  index_breakdown.csv / decision.json / methodology.json / validation_report.txt
"""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

import qlib
from qlib.config import REG_CN
from qlib.data import D

from analyze_a_share_negative_event_subtype_v1 import (
    ts_to_qlib, QLIB_DIR, ST_INTERVALS, LIMIT_MAIN, LIMIT_GEM, is_gem,
)
from analyze_a_share_trend_persistence_labelfix_v2 import build_universe

MEMBERSHIP = Path("data/external/tushare/a_share_index_membership_pit_v1/normalized/monthly_index_membership.csv.gz")
LOAD_START = "2015-07-01"
EVAL_START = "2016-01-01"
DATA_END = "2026-07-31"
HORIZONS = [20, 40, 60]
MAIN_H = 40
BENCHMARK = "SH000852"
T_CRIT = 2.5
TIME_BLOCKS = [
    ("2016-2019", pd.Timestamp("2016-01-01"), pd.Timestamp("2019-12-31")),
    ("2020-2022", pd.Timestamp("2020-01-01"), pd.Timestamp("2022-12-31")),
    ("2023-2026", pd.Timestamp("2023-01-01"), pd.Timestamp("2026-12-31")),
]
INDEXES = ["csi300", "csi500", "csi800", "csi1000"]


def load_membership() -> pd.DataFrame:
    df = pd.read_csv(MEMBERSHIP, compression="gzip")
    df["snapshot_date"] = pd.to_datetime(df["snapshot_date"].astype(str), format="%Y%m%d")
    df["instrument"] = df["ts_code"].map(ts_to_qlib)
    df = df.dropna(subset=["instrument"])
    return df


def build_event_sets(df: pd.DataFrame) -> pd.DataFrame:
    """相邻快照差分 → 纳入/剔除/对照事件表（仅定期调整批次进主检验）。"""
    rows = []
    for idx in INDEXES:
        sub = df[df["index_name"].eq(idx)]
        dates = sorted(sub["snapshot_date"].unique())
        prev_set, prev_d = None, None
        for d in dates:
            cur_set = set(sub[sub["snapshot_date"].eq(d)]["instrument"])
            if prev_set is not None and prev_d is not None:
                is_regular = (prev_d.month == 5 and d.month == 6) or \
                             (prev_d.month == 11 and d.month == 12)
                for inst in cur_set - prev_set:
                    rows.append({"index": idx, "batch_date": d, "group": "纳入",
                                 "regular": is_regular, "instrument": inst})
                for inst in prev_set - cur_set:
                    rows.append({"index": idx, "batch_date": d, "group": "剔除",
                                 "regular": is_regular, "instrument": inst})
                for inst in prev_set & cur_set:
                    rows.append({"index": idx, "batch_date": d, "group": "对照",
                                 "regular": is_regular, "instrument": inst})
            prev_set, prev_d = cur_set, d
    return pd.DataFrame(rows)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--output-dir", type=Path,
                        default=Path("output/analysis_static/a_share_index_adjustment_v1"))
    args = parser.parse_args()
    out = args.output_dir
    if out.exists() and any(out.iterdir()):
        raise FileExistsError(f"Refusing to overwrite existing experiment output: {out}")
    out.mkdir(parents=True, exist_ok=True)

    qlib.init(provider_uri=str(QLIB_DIR), region=REG_CN)
    calendar = pd.DatetimeIndex(pd.to_datetime(
        pd.read_csv(QLIB_DIR / "calendars" / "day.txt", header=None)[0]))
    cal_list = list(calendar)
    cal_pos = {d: i for i, d in enumerate(cal_list)}

    print("[1/6] Universe + market panel (correct open-to-open labels) ...", flush=True)
    codes, excluded = build_universe()
    mkt = D.features(codes, ["$close", "$open", "$change", "$volume"],
                     start_time=LOAD_START, end_time=DATA_END, freq="day")
    mkt.columns = ["$close", "$open", "$change", "$volume"]
    mkt = mkt.reset_index().set_index(["datetime", "instrument"]).sort_index()
    g = mkt.groupby(level="instrument")
    for h in HORIZONS:
        mkt[f"FWD_{h}"] = g["$open"].shift(-(h + 1)) / g["$open"].shift(-1) - 1
    mkt_df = mkt.reset_index()
    mask_close = mkt_df["$close"].notna() & mkt_df["$volume"].notna() & (mkt_df["$volume"] > 0)
    limit_thresh = np.where(mkt_df["instrument"].map(is_gem), LIMIT_GEM, LIMIT_MAIN)
    mask_close &= ~(mkt_df["$change"] >= limit_thresh)
    mkt_clean = mkt_df[mask_close].copy()
    mkt_clean["ts_code"] = mkt_clean["instrument"].map(
        lambda c: f"{c[2:]}.{c[:2]}" if isinstance(c, str) and len(c) == 8 else np.nan)
    print(f"      rows={len(mkt)}, keep={mask_close.mean():.1%}", flush=True)

    print("[2/6] Benchmark ...", flush=True)
    bench = D.features([BENCHMARK], ["$open"], start_time=LOAD_START, end_time=DATA_END, freq="day")
    bench.columns = ["$open"]
    bench = bench.reset_index().set_index(["datetime", "instrument"]).sort_index()
    bg = bench.groupby(level="instrument")
    for h in HORIZONS:
        bench[f"BENCH_{h}"] = bg["$open"].shift(-(h + 1)) / bg["$open"].shift(-1) - 1
    bench_fwd = bench.reset_index()[["datetime"] + [f"BENCH_{h}" for h in HORIZONS]]
    bench_fwd = bench_fwd.set_index("datetime").sort_index()

    print("[3/6] ST intervals ...", flush=True)
    st = pd.read_csv(ST_INTERVALS, compression="gzip", parse_dates=["start_date", "end_date"])
    st_active = st.loc[st["is_st"] | st["is_delist_phase"], ["ts_code", "start_date", "end_date"]]
    st_active["instrument"] = st_active["ts_code"].map(ts_to_qlib)
    st_active = st_active.dropna(subset=["instrument"])

    print("[4/6] Event sets + excess ...", flush=True)
    mem = load_membership()
    events = build_event_sets(mem)
    # 事件日对齐到交易日
    events["batch_date"] = calendar[np.searchsorted(calendar.values, events["batch_date"].values)]
    events = events[(events["batch_date"] >= pd.Timestamp(EVAL_START))
                    & (events["batch_date"] <= pd.Timestamp(DATA_END))]
    events.to_csv(out / "event_sets.csv", index=False)
    print(f"      events: {len(events):,} (纳入 {(events['group']=='纳入').sum():,} / "
          f"剔除 {(events['group']=='剔除').sum():,} / 对照 {(events['group']=='对照').sum():,})", flush=True)

    merge_cols = ["instrument", "datetime", "ts_code"] + [f"FWD_{h}" for h in HORIZONS]
    merged = events.merge(mkt_clean[merge_cols],
                          left_on=["instrument", "batch_date"], right_on=["instrument", "datetime"], how="left")
    merged = merged.dropna(subset=["FWD_40"])
    # ST 过滤（批次日 asof）
    dates_in_ev = merged["batch_date"].unique()
    st_by_date: dict[pd.Timestamp, set[str]] = {}
    for d in dates_in_ev:
        active = st_active[(st_active["start_date"] <= d) & (st_active["end_date"] >= d)]
        st_by_date[d] = set(active["ts_code"])
    merged = merged.assign(is_st=[
        c in st_by_date.get(d, set())
        for d, c in zip(merged["batch_date"], merged["ts_code"])
    ])
    merged = merged[~merged["is_st"]]
    merged = merged.merge(bench_fwd, left_on="batch_date", right_on="datetime", how="left")
    for h in HORIZONS:
        merged[f"EXC_{h}"] = merged[f"FWD_{h}"] - merged[f"BENCH_{h}"]
    print(f"      analyzable: {len(merged):,}", flush=True)

    # ---- 主检验：定期批次 × 组 × H ----
    print("[5/6] Main test ...", flush=True)
    reg = merged[merged["regular"]]
    e_rows = []
    for group in ["纳入", "剔除", "对照"]:
        sub = reg[reg["group"].eq(group)]
        for h in HORIZONS:
            s = sub[f"EXC_{h}"]
            n = len(s)
            tstat = s.mean() / (s.std(ddof=1) / np.sqrt(n)) if n > 30 and s.std(ddof=1) > 0 else np.nan
            e_rows.append({"group": group, "horizon": h, "n": n,
                           "excess_mean": s.mean(), "tstat": tstat})
    e1 = pd.DataFrame(e_rows)
    e1.to_csv(out / "excess_by_group.csv", index=False)

    # 时间段一致性（主检验：纳入组 H=40）
    inc40 = reg[reg["group"].eq("纳入")]
    block_rows = []
    for name, b0, b1 in TIME_BLOCKS:
        sub = inc40[(inc40["batch_date"] >= b0) & (inc40["batch_date"] <= b1)]
        if len(sub) >= 30:
            s = sub["EXC_40"]
            tstat = s.mean() / (s.std(ddof=1) / np.sqrt(len(s))) if s.std(ddof=1) > 0 else np.nan
            block_rows.append({"block": name, "n": len(sub), "excess_mean_h40": s.mean(), "tstat": tstat})
    blocks = pd.DataFrame(block_rows)
    blocks.to_csv(out / "time_block_breakdown.csv", index=False)

    # 分批次稳定性（纳入组 H=40，定期批次）
    batch_rows = []
    for (idx, bd), sub in inc40.groupby(["index", "batch_date"]):
        batch_rows.append({"index": idx, "batch_date": str(bd.date()),
                           "n": len(sub), "excess_mean_h40": sub["EXC_40"].mean()})
    batches = pd.DataFrame(batch_rows)
    batches.to_csv(out / "batch_stability.csv", index=False)

    # 分指数
    idx_rows = []
    for idx in INDEXES:
        sub = inc40[inc40["index"].eq(idx)]
        if len(sub) >= 30:
            s = sub["EXC_40"]
            tstat = s.mean() / (s.std(ddof=1) / np.sqrt(len(s))) if s.std(ddof=1) > 0 else np.nan
            idx_rows.append({"index": idx, "n": len(sub), "excess_mean_h40": s.mean(), "tstat": tstat})
    idx_df = pd.DataFrame(idx_rows)
    idx_df.to_csv(out / "index_breakdown.csv", index=False)

    # 次要观察：剔除组、临时批次
    exc40 = reg[reg["group"].eq("剔除")]["EXC_40"]
    temp_rows = []
    temp = merged[~merged["regular"] & merged["group"].eq("纳入")]
    if len(temp) >= 30:
        temp_rows.append({"group": "临时调整纳入", "n": len(temp),
                          "excess_mean_h40": temp["EXC_40"].mean()})
    obs_rows = [{"group": "剔除组(定期)", "n": len(exc40),
                 "excess_mean_h40": exc40.mean()}] + temp_rows
    obs = pd.DataFrame(obs_rows)
    obs.to_csv(out / "secondary_observations.csv", index=False)

    # ---- 判定 ----
    print("[6/6] Decision ...", flush=True)
    inc_main = e1[(e1["group"].eq("纳入")) & (e1["horizon"].eq(MAIN_H))].iloc[0]
    sig = bool(inc_main["tstat"] > T_CRIT)
    pos_blocks = int((blocks["excess_mean_h40"] > 0).sum())
    consistent = bool(pos_blocks >= 2)  # ≥2/3 时间段同向
    # 非单指数驱动：至少 2 个指数为正（若 ≥2 指数有样本）
    pos_idx = int((idx_df["excess_mean_h40"] > 0).sum())
    not_single = bool(pos_idx >= 2) if len(idx_df) >= 2 else bool(pos_idx >= 1)

    if sig and consistent and not_single:
        decision = "index_adjustment_effect_supported"
    else:
        decision = "index_adjustment_effect_not_supported"

    decision_json = {
        "decision": decision,
        "inc_h40": {"n": int(inc_main["n"]), "excess_mean": float(inc_main["excess_mean"]),
                    "tstat": float(inc_main["tstat"]), "significant": sig},
        "time_blocks": {"positive_blocks": pos_blocks, "total_blocks": len(blocks),
                        "consistent": consistent},
        "index_breakdown": {"positive_indexes": pos_idx, "total_indexes": len(idx_df),
                            "not_single_driven": not_single},
    }
    (out / "decision.json").write_text(json.dumps(decision_json, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    meta = {
        "purpose": "指数定期调整纳入/剔除效应（post-adjustment drift）",
        "protocol": "research/protocols/a_share_index_adjustment_protocol_v1.md",
        "universe": f"沪深普通 A 股 {len(codes)} 只",
        "eval_window": [EVAL_START, DATA_END],
        "benchmark": BENCHMARK,
        "main_horizon": MAIN_H,
        "label": "open[t+1+h]/open[t+1]-1（正确口径）",
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
    }
    (out / "methodology.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")

    lines = [
        "# 指数定期调整纳入/剔除效应报告 v1\n",
        f"- 数据: {len(mem):,} 行成分快照（{mem['snapshot_date'].min().date()} ~ {mem['snapshot_date'].max().date()}）",
        f"- 事件: 定期调整批次（5→6、11→12 月）纳入/剔除/对照，T+1 开盘入场",
        f"- 标签: 正确 open-to-open，市场调整超额（− SH000852）\n",
        "## 主检验（定期批次 × 组 × H）",
        e1.to_string(index=False),
        "\n## 时间段一致性（纳入组 H=40）",
        blocks.to_string(index=False),
        "\n## 分指数（纳入组 H=40）",
        idx_df.to_string(index=False),
        "\n## 次要观察",
        obs.to_string(index=False),
        "\n## 判定",
        f"- 纳入组 H={MAIN_H}: t={inc_main['tstat']:.2f}（门槛 >{T_CRIT}）→ {'显著' if sig else '不显著'}",
        f"- 时间段同向: {pos_blocks}/{len(blocks)} → {'一致' if consistent else '不一致'}",
        f"- 分指数: {pos_idx}/{len(idx_df)} 为正 → {'非单驱动' if not_single else '单驱动'}",
        f"- **判定: {decision}**",
    ]
    (out / "validation_report.txt").write_text("\n".join(lines), encoding="utf-8")
    print("\n".join(lines), flush=True)


if __name__ == "__main__":
    main()
