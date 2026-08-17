#!/usr/bin/env python3
"""每日结构化事件流事件后漂移检验 v1（股东增减持 / 限售解禁 / 龙虎榜）。

协议：research/protocols/a_share_events_daily_protocol_v1.md

研究问题
--------
事件（增/减持公告、解禁日、龙虎榜上榜）发生后 5/10/20 个交易日内，事件股的
市场调整超额是否显著且方向一致？增减持 IN/DE 方向、解禁比例、龙虎榜净买入
符号是否具有单调区分力？

口径
----
- 母池：沪深普通 A 股（all.txt 剔北交所，约 5542 只，含退市）
- 数据：cn_data_2026（后复权）+ a_share_events_daily_v1（事件）
- 事件日锚定：增减持=ann_date、解禁=float_date、龙虎榜=trade_date
- 未来收益：T+1 开盘成交 Ref($open,-1)/(Ref($close,-(h+1))-1)，h=5/10/20
- 市场调整超额 = 事件股未来收益 − 同期 SH000852 未来收益
- 过滤：ST/*ST/退市整理（事件日 asof）+ 停牌 + 涨停信号日
- 检验窗口：2022-01-01 ~ 2026-07-31

输出（拒绝覆盖非空目录）
------------------------
output/analysis_static/a_share_events_daily_v1/
  e1_event_excess.csv / e2_direction.csv / e3_size_layers.csv
  decision.json / methodology.json / validation_report.txt
"""

from __future__ import annotations

import argparse
import glob
import json
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd
from scipy import stats

import qlib
from qlib.config import REG_CN
from qlib.data import D

from analyze_a_share_trend_persistence_v1 import build_universe, qlib_to_ts, is_gem

QLIB_DIR = Path("~/.qlib/qlib_data/cn_data_2026").expanduser()
EVENTS_DIR = Path("data/external/tushare/a_share_events_daily_v1/raw")
ST_INTERVALS = Path("data/external/tushare/a_share_st_status_pit_v1/normalized/st_status_intervals.csv.gz")

LOAD_START = "2020-07-01"
EVAL_START = "2022-01-01"
DATA_END = "2026-07-31"
HORIZONS = [5, 10, 20]
LIMIT_MAIN, LIMIT_GEM = 0.095, 0.195
ANNUALIZATION_DAYS = 238
T_CRIT = 2.0
BENCHMARK = "SH000852"


def ts_to_qlib(code: str) -> str | float:
    """600007.SH -> SH600007；老三板/退市整理（400xxx 等无交易所后缀）置 NaN，合并时剔除。"""
    if not isinstance(code, str) or "." not in code:
        return np.nan
    num, ex = code.split(".")
    if ex not in ("SH", "SZ", "BJ"):
        return np.nan
    return f"{ex}{num}"


def load_events() -> dict[str, pd.DataFrame]:
    """读三类事件原始文件，返回聚合到 (instrument, event_date) 的事件表。"""
    files = sorted(Path(p) for p in glob.glob(str(EVENTS_DIR / "*.csv.gz")))

    hold = pd.concat([pd.read_csv(f, compression="gzip") for f in files if "holdertrade" in f.name],
                     ignore_index=True)
    float_ = pd.concat([pd.read_csv(f, compression="gzip") for f in files if "share_float" in f.name],
                       ignore_index=True)
    top = pd.concat([pd.read_csv(f, compression="gzip") for f in files if "top_list" in f.name],
                    ignore_index=True)

    # 增减持：按 (code, ann_date, in_de) 聚合，事件日=ann_date
    hold["instrument"] = hold["ts_code"].map(ts_to_qlib)
    hold["ann_date"] = pd.to_datetime(hold["ann_date"].astype(str), format="%Y%m%d")
    h_in = hold.loc[hold["in_de"].eq("IN")].groupby(["instrument", "ann_date"])["change_vol"].sum().reset_index()
    h_de = hold.loc[hold["in_de"].eq("DE")].groupby(["instrument", "ann_date"])["change_vol"].sum().reset_index()
    h_in["event"] = "增持"
    h_de["event"] = "减持"

    # 解禁：事件日=float_date（实际解禁日），按 (code, float_date) 聚合比例
    float_["instrument"] = float_["ts_code"].map(ts_to_qlib)
    float_["float_date"] = pd.to_datetime(float_["float_date"].astype(str), format="%Y%m%d")
    fl = float_.groupby(["instrument", "float_date"])["float_ratio"].sum().reset_index()
    fl = fl.rename(columns={"float_date": "ann_date"})
    fl["event"] = "解禁"

    # 龙虎榜：事件日=trade_date，按 (code, trade_date) 聚合净买入
    top["instrument"] = top["ts_code"].map(ts_to_qlib)
    top["trade_date"] = pd.to_datetime(top["trade_date"].astype(str), format="%Y%m%d")
    tp = top.groupby(["instrument", "trade_date"])["net_amount"].sum().reset_index()
    tp = tp.rename(columns={"trade_date": "ann_date"})
    tp["event"] = "龙虎榜"

    out = {
        "增持": h_in.rename(columns={"ann_date": "date", "change_vol": "value"}),
        "减持": h_de.rename(columns={"ann_date": "date", "change_vol": "value"}),
        "解禁": fl.rename(columns={"ann_date": "date", "float_ratio": "value"}),
        "龙虎榜": tp.rename(columns={"ann_date": "date", "net_amount": "value"}),
    }
    return out


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--output-dir", type=Path,
                        default=Path("output/analysis_static/a_share_events_daily_v1"))
    args = parser.parse_args()
    out = args.output_dir
    if out.exists() and any(out.iterdir()):
        raise FileExistsError(f"Refusing to overwrite existing experiment output: {out}")
    out.mkdir(parents=True, exist_ok=True)

    qlib.init(provider_uri=str(QLIB_DIR), region=REG_CN)

    # ---- 1. 母池行情面板 + FWD ----
    print("[1/5] Universe + market panel ...", flush=True)
    codes, excluded = build_universe()
    mkt = D.features(codes, ["$close", "$open", "$change", "$volume"],
                     start_time=LOAD_START, end_time=DATA_END, freq="day")
    mkt.columns = ["$close", "$open", "$change", "$volume"]
    mkt = mkt.reset_index().set_index(["datetime", "instrument"]).sort_index()
    g = mkt.groupby(level="instrument")
    for h in HORIZONS:
        mkt[f"FWD_{h}"] = g["$open"].shift(-1) / g["$close"].shift(-(h + 1)) - 1
    print(f"      rows={len(mkt)}, instruments={mkt.index.get_level_values('instrument').nunique()}", flush=True)

    # ---- 2. 基准 SH000852 同口径 FWD ----
    print("[2/5] Benchmark SH000852 ...", flush=True)
    bench = D.features([BENCHMARK], ["$open", "$close"],
                       start_time=LOAD_START, end_time=DATA_END, freq="day")
    bench.columns = ["$open", "$close"]
    bench = bench.reset_index().set_index(["datetime", "instrument"]).sort_index()
    bg = bench.groupby(level="instrument")
    for h in HORIZONS:
        bench[f"BENCH_{h}"] = bg["$open"].shift(-1) / bg["$close"].shift(-(h + 1)) - 1
    bench_fwd = bench.reset_index()[["datetime", f"BENCH_{HORIZONS[0]}", f"BENCH_{HORIZONS[1]}", f"BENCH_{HORIZONS[2]}"]]
    bench_fwd = bench_fwd.set_index("datetime").sort_index()
    print(f"      bench rows={len(bench)}", flush=True)

    # ---- 3. ST 区间 ----
    print("[3/5] ST intervals ...", flush=True)
    st = pd.read_csv(ST_INTERVALS, compression="gzip", parse_dates=["start_date", "end_date"])
    st_active = st.loc[st["is_st"] | st["is_delist_phase"], ["ts_code", "start_date", "end_date"]]

    # ---- 4. 事件合并 + 超额 ----
    print("[4/5] Merging events + excess returns ...", flush=True)
    events = load_events()
    mkt_df = mkt.reset_index()
    mask_close = mkt_df["$close"].notna() & mkt_df["$volume"].notna() & (mkt_df["$volume"] > 0)
    limit_thresh = np.where(mkt_df["instrument"].map(is_gem), LIMIT_GEM, LIMIT_MAIN)
    mask_close &= ~(mkt_df["$change"] >= limit_thresh)
    mkt_clean = mkt_df[mask_close]

    ts_codes = mkt_clean["instrument"].map(qlib_to_ts)
    mkt_clean = mkt_clean.assign(ts_code=ts_codes)

    e1_rows, e2_rows = [], []
    for ev_name, ev in events.items():
        ev = ev[(ev["date"] >= pd.Timestamp(EVAL_START)) & (ev["date"] <= pd.Timestamp(DATA_END))]
        if ev.empty:
            continue
        merged = ev.merge(mkt_clean[["instrument", "datetime", "ts_code", "$close", "$volume",
                                     "FWD_5", "FWD_10", "FWD_20"]],
                          left_on=["instrument", "date"], right_on=["instrument", "datetime"], how="left")
        merged = merged.dropna(subset=["FWD_5"])
        if merged.empty:
            continue

        # ST 过滤（事件日 asof，向量化）
        dates_in_ev = merged["date"].unique()
        st_by_date: dict[pd.Timestamp, set[str]] = {}
        for d in dates_in_ev:
            active = st_active[(st_active["start_date"] <= d) & (st_active["end_date"] >= d)]
            st_by_date[d] = set(active["ts_code"])
        merged = merged.assign(is_st=[
            c in st_by_date.get(d, set())
            for d, c in zip(merged["date"], merged["ts_code"])
        ])
        merged = merged[~merged["is_st"]]

        # 基准超额
        merged = merged.merge(bench_fwd, left_on="date", right_on="datetime", how="left")
        for h in HORIZONS:
            merged[f"EXC_{h}"] = merged[f"FWD_{h}"] - merged[f"BENCH_{h}"]

        print(f"      {ev_name}: events={len(merged)}", flush=True)

        # E1 全期 + 分年度
        for h in HORIZONS:
            s = merged[f"EXC_{h}"]
            yearly = merged.groupby(merged["date"].dt.year)[f"EXC_{h}"].mean()
            e1_rows.append({
                "event": ev_name, "horizon": h, "n": len(s),
                "excess_mean": s.mean(), "tstat": s.mean() / (s.std(ddof=1) / np.sqrt(len(s))) if len(s) > 30 else np.nan,
                "yearly": json.dumps({int(y): float(v) for y, v in yearly.items()}),
            })

        # E2 方向分层
        if ev_name == "增持":
            e2_rows.append({"event": ev_name, "horizon": HORIZONS[0], "n": len(merged),
                            "excess_mean": merged[f"EXC_{HORIZONS[0]}"].mean()})
        elif ev_name == "减持":
            e2_rows.append({"event": ev_name, "horizon": HORIZONS[0], "n": len(merged),
                            "excess_mean": merged[f"EXC_{HORIZONS[0]}"].mean()})
        elif ev_name == "解禁":
            med = merged["value"].median()
            hi = merged[merged["value"] >= med]
            lo = merged[merged["value"] < med]
            e2_rows.append({"event": "解禁高比例", "horizon": HORIZONS[0], "n": len(hi),
                            "excess_mean": hi[f"EXC_{HORIZONS[0]}"].mean()})
            e2_rows.append({"event": "解禁低比例", "horizon": HORIZONS[0], "n": len(lo),
                            "excess_mean": lo[f"EXC_{HORIZONS[0]}"].mean()})
        elif ev_name == "龙虎榜":
            pos = merged[merged["value"] >= 0]
            neg = merged[merged["value"] < 0]
            e2_rows.append({"event": "龙虎榜净买", "horizon": HORIZONS[0], "n": len(pos),
                            "excess_mean": pos[f"EXC_{HORIZONS[0]}"].mean()})
            e2_rows.append({"event": "龙虎榜净卖", "horizon": HORIZONS[0], "n": len(neg),
                            "excess_mean": neg[f"EXC_{HORIZONS[0]}"].mean()})

    e1 = pd.DataFrame(e1_rows)
    e1.to_csv(out / "e1_event_excess.csv", index=False)
    e2 = pd.DataFrame(e2_rows)
    e2.to_csv(out / "e2_direction.csv", index=False)

    # ---- 5. 判定 + 报告 ----
    print("[5/5] Decision + report ...", flush=True)
    sig_h5 = e1[e1["horizon"].eq(5)].copy()
    sig_h5["sig"] = sig_h5["tstat"].abs().gt(T_CRIT)
    viable_h5 = int((sig_h5["sig"] & sig_h5["n"].ge(100)).sum())
    any_viable = viable_h5 > 0
    decision = "event_stream_viable" if any_viable else "not_supported"

    lines = []
    lines.append("# 每日结构化事件流事件后漂移检验报告 v1\n")
    lines.append(f"- 母池: 沪深普通 A 股 {len(codes)} 只（剔北交所 {len(excluded)}）")
    lines.append(f"- 窗口: {EVAL_START} ~ {DATA_END}")
    lines.append(f"- 超额口径: 事件股 T+1 开盘成交 h 日收益 − SH000852 同期\n")
    lines.append(f"## 判定：**{decision}**\n")

    lines.append("### E1 事件后超额（全期）")
    lines.append("| 事件 | h | n | 超额均值(日) | t | 分年度 |")
    lines.append("|---|---|---|---|---|---|")
    for _, r in e1.iterrows():
        yr = r["yearly"]
        lines.append(f"| {r['event']} | {r['horizon']} | {r['n']} | {r['excess_mean']:+.5f} | {r['tstat']:.2f} | {yr} |")

    lines.append("\n### E2 方向单调性（h=5）")
    lines.append("| 组 | n | 超额均值(日) |")
    lines.append("|---|---|---|")
    for _, r in e2.iterrows():
        lines.append(f"| {r['event']} | {r['n']} | {r['excess_mean']:+.5f} |")

    (out / "validation_report.txt").write_text("\n".join(lines), encoding="utf-8")

    meta = {
        "purpose": "每日结构化事件流事件后漂移检验",
        "protocol": "research/protocols/a_share_events_daily_protocol_v1.md",
        "universe": f"沪深普通 A 股 {len(codes)} 只",
        "eval_window": [EVAL_START, DATA_END],
        "benchmark": BENCHMARK,
        "decision": decision,
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
    }
    (out / "methodology.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    (out / "decision.json").write_text(json.dumps({"decision": decision}, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"      report -> {out / 'validation_report.txt'}", flush=True)
    print(f"      decision = {decision}", flush=True)
    print("DONE", flush=True)


if __name__ == "__main__":
    main()
