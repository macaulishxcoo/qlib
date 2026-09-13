#!/usr/bin/env python3
"""负面事件分类型研究：事件后漂移检验 v1（经营类/制度类/资金类/交易类）。

协议：research/protocols/a_share_negative_event_subtype_protocol_v1.md

研究问题
--------
把"负面事件"按类型拆开（T1 经营类-预亏/预减、T2 制度类-ST 戴帽、T3 资金类-减持、
T4 资金类-解禁、T5 交易类-跌幅上榜），各类事件后 10/20/40 个交易日的市场调整
超额是否方向一致、非动量代理、且类型间存在显著行为差异？

口径
----
- 母池：沪深普通 A 股（all.txt 剔北交所/指数/B 股），口径同 events_daily 脚本
- 数据：cn_data_2026（后复权）+ a_share_forecast_v1（T1）+ a_share_events_daily_v1
  （T3/T4/T5）+ a_share_st_status_pit_v1（T2）
- 事件日：T1=ann_date（业绩预告公告日）、T2=start_date（戴帽生效日）、
  T3=ann_date、T4=float_date、T5=trade_date
- 未来收益：T+1 开盘成交，H=10/20/40；市场调整超额 = 个股未来收益 − SH000852 同期
- 过滤：ST/退市整理（事件日 asof）+ 停牌 + 涨停信号日
- 检验窗口：2022-01-01 ~ 2026-07-31
- 动量正交化：事件前 20 日收益 5 组（复用 PEAD 方法）
- 组间差异：四类事件 20 日超额两两 Welch t + 单因素 ANOVA

输出（拒绝覆盖非空目录）
------------------------
output/analysis_static/a_share_negative_event_subtype_v1/
  event_excess_by_type.csv / event_type_breakdown.csv
  momentum_orthogonality.csv / type_pairwise_diff.csv
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
FORECAST_DIR = Path("data/external/tushare/a_share_forecast_v1/raw")
ST_INTERVALS = Path("data/external/tushare/a_share_st_status_pit_v1/normalized/st_status_intervals.csv.gz")

LOAD_START = "2020-07-01"
EVAL_START = "2022-01-01"
DATA_END = "2026-07-31"
HORIZONS = [10, 20, 40]
LIMIT_MAIN, LIMIT_GEM = 0.095, 0.195
T_CRIT = 2.5          # 从紧口径（协议 §4.1）
YEARLY_STRICT = 3     # 2022-2025 至少 3 年同向
BENCHMARK = "SH000852"

# T1 经营类：负面业绩预告类型（冻结）
FORECAST_NEGATIVE_TYPES = {"预亏", "首亏", "续亏", "预减", "略减"}
# T2 制度类：is_st 由 false -> true 的区间起点（戴帽生效日）
# T3 资金类：in_de == DE（减持）
# T4 资金类：share_float.float_ratio（解禁比例）
# T5 交易类：reason 含"跌幅"或"负向异常波动"
T5_NEG_KEYWORDS = ("跌幅", "负向")
# 多重事件重叠优先级（冻结）：T1 > T2 > T3 > T4 > T5
TYPE_PRIORITY = {"T1": 1, "T2": 2, "T3": 3, "T4": 4, "T5": 5}


def ts_to_qlib(code: str) -> str | float:
    """600007.SH -> SH600007；老三板/退市整理（400xxx 等无交易所后缀）置 NaN。"""
    if not isinstance(code, str) or "." not in code:
        return np.nan
    num, ex = code.split(".")
    if ex not in ("SH", "SZ", "BJ"):
        return np.nan
    return f"{ex}{num}"


def load_forecast() -> pd.DataFrame:
    """T1：业绩预告负面类型（预亏/首亏/续亏/预减/略减），事件日=ann_date。"""
    files = sorted(Path(p) for p in glob.glob(str(FORECAST_DIR / "*_forecast.csv.gz")))
    if not files:
        raise FileNotFoundError(f"No forecast files in {FORECAST_DIR}")
    df = pd.concat([pd.read_csv(f, compression="gzip") for f in files], ignore_index=True)
    df["instrument"] = df["ts_code"].map(ts_to_qlib)
    df["ann_date"] = pd.to_datetime(df["ann_date"].astype(str), format="%Y%m%d")
    df = df[df["type"].isin(FORECAST_NEGATIVE_TYPES)]
    # 同股同日去重
    out = df.groupby(["instrument", "ann_date"], as_index=False).agg(
        type=("type", lambda s: "/".join(sorted(set(s)))),
        p_change_min=("p_change_min", "min"),
    )
    out = out.rename(columns={"ann_date": "date"})
    out["event_type"] = "T1"
    return out[["instrument", "date", "event_type", "type", "p_change_min"]]


def load_st_hat() -> pd.DataFrame:
    """T2：ST 戴帽事件 = is_st 由 false 变 true 的区间。

    - `ann_date`：公告日（用于 ST 状态 asof 检查——公告日当天通常尚未 ST，
      否则 prev_is_st=True 已被排除；避免戴帽当天被自身 ST 过滤剔除）；
    - `date`：生效日 start_date（= 复牌日，戴帽公告日停牌、次日复牌已有行情）。
    """
    st = pd.read_csv(ST_INTERVALS, compression="gzip", parse_dates=["start_date", "end_date", "ann_date"])
    st = st.sort_values(["ts_code", "start_date"])
    st["instrument"] = st["ts_code"].map(ts_to_qlib)
    st = st.dropna(subset=["instrument"])
    # 剔除北交所（920xxx 等，与母池 build_universe 口径一致，否则事件日无行情可对齐）
    st = st[~st["instrument"].str.startswith("BJ")]
    # 上一区间是否 ST（同股票、上一个 start_date 之前最近区间的 is_st）
    st["prev_is_st"] = st.groupby("instrument")["is_st"].shift(1)
    hat = st[(st["is_st"]) & (st["prev_is_st"].fillna(False) == False)]  # noqa: E712
    hat = hat.dropna(subset=["ann_date", "start_date"])
    out = hat.rename(columns={"start_date": "date", "ann_date": "st_check_date"})
    out["event_type"] = "T2"
    return out[["instrument", "date", "st_check_date", "event_type"]]


def load_holdertrade_de() -> pd.DataFrame:
    """T3：减持（in_de=DE），事件日=ann_date；保留身份与比例用于分层。"""
    files = sorted(Path(p) for p in glob.glob(str(EVENTS_DIR / "*stk_holdertrade.csv.gz")))
    df = pd.concat([pd.read_csv(f, compression="gzip") for f in files], ignore_index=True)
    df["instrument"] = df["ts_code"].map(ts_to_qlib)
    df["ann_date"] = pd.to_datetime(df["ann_date"].astype(str), format="%Y%m%d")
    df = df[df["in_de"].eq("DE")]
    df = df.rename(columns={"ann_date": "date"})
    # 同股同日：change_ratio 求和、holder_type 取众数
    agg = df.groupby(["instrument", "date"], as_index=False).agg(
        change_ratio=("change_ratio", "sum"),
        holder_type=("holder_type", lambda s: s.mode().iloc[0] if len(s) else np.nan),
        n_holders=("holder_name", "count"),
    )
    agg["event_type"] = "T3"
    return agg


def load_share_float() -> pd.DataFrame:
    """T4：解禁（事件日=float_date），float_ratio 求和用于分层。"""
    files = sorted(Path(p) for p in glob.glob(str(EVENTS_DIR / "*share_float.csv.gz")))
    df = pd.concat([pd.read_csv(f, compression="gzip") for f in files], ignore_index=True)
    df["instrument"] = df["ts_code"].map(ts_to_qlib)
    df["float_date"] = pd.to_datetime(df["float_date"].astype(str), format="%Y%m%d")
    agg = df.groupby(["instrument", "float_date"], as_index=False)["float_ratio"].sum()
    agg = agg.rename(columns={"float_date": "date"})
    agg["event_type"] = "T4"
    return agg


def load_top_list_neg() -> pd.DataFrame:
    """T5：跌幅上榜（reason 含跌幅/负向），事件日=trade_date。"""
    files = sorted(Path(p) for p in glob.glob(str(EVENTS_DIR / "*top_list.csv.gz")))
    df = pd.concat([pd.read_csv(f, compression="gzip") for f in files], ignore_index=True)
    df["instrument"] = df["ts_code"].map(ts_to_qlib)
    df["trade_date"] = pd.to_datetime(df["trade_date"].astype(str), format="%Y%m%d")
    neg = df[df["reason"].str.contains("|".join(T5_NEG_KEYWORDS), na=False)]
    agg = neg.groupby(["instrument", "trade_date"], as_index=False).agg(
        net_amount=("net_amount", "sum"),
        reasons=("reason", lambda s: "|".join(sorted(set(s)))[:200]),
    )
    agg = agg.rename(columns={"trade_date": "date"})
    agg["event_type"] = "T5"
    return agg


def load_events() -> pd.DataFrame:
    """合并五类事件 + 优先级去重（T1>T2>T3>T4>T5；同股 20 日内保留首个）。

    事件日统一对齐到下一个交易日（公告日常落在周末/节假日，如 T2 有 110 个周六
    公告）：事件锚点 T = >= 公告日 的第一个交易日，入场 = T+1 开盘（FWD 口径）。
    """
    parts = [load_forecast(), load_st_hat(), load_holdertrade_de(),
             load_share_float(), load_top_list_neg()]
    ev = pd.concat(parts, ignore_index=True)
    ev = ev[(ev["date"] >= pd.Timestamp(EVAL_START)) & (ev["date"] <= pd.Timestamp(DATA_END))]

    # 交易日历：对齐到下一个交易日（T2 的 date=生效日=复牌日，对齐后即有行情）
    cal = pd.DatetimeIndex(pd.to_datetime(
        pd.read_csv(QLIB_DIR / "calendars" / "day.txt", header=None)[0]))
    cal_sorted = cal.sort_values()
    ev["date"] = cal_sorted[np.searchsorted(cal_sorted.values, ev["date"].values)]
    # ST 检查日：T2 用公告日（st_check_date），其余类型默认 = 对齐后的事件日
    if "st_check_date" not in ev.columns:
        ev["st_check_date"] = ev["date"]
    else:
        ev["st_check_date"] = ev["st_check_date"].fillna(ev["date"])

    # 优先级：同一 (instrument, date) 只保留优先级最高的事件
    ev["prio"] = ev["event_type"].map(TYPE_PRIORITY)
    ev = ev.sort_values(["instrument", "date", "prio"]).drop_duplicates(["instrument", "date"], keep="first")
    ev = ev.drop(columns=["prio"]).reset_index(drop=True)
    return ev


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--output-dir", type=Path,
                        default=Path("output/analysis_static/a_share_negative_event_subtype_v1"))
    args = parser.parse_args()
    out = args.output_dir
    if out.exists() and any(out.iterdir()):
        raise FileExistsError(f"Refusing to overwrite existing experiment output: {out}")
    out.mkdir(parents=True, exist_ok=True)

    qlib.init(provider_uri=str(QLIB_DIR), region=REG_CN)

    # ---- 1. 母池行情面板 + FWD ----
    print("[1/6] Universe + market panel ...", flush=True)
    codes, excluded = build_universe()
    mkt = D.features(codes, ["$close", "$open", "$change", "$volume"],
                     start_time=LOAD_START, end_time=DATA_END, freq="day")
    mkt.columns = ["$close", "$open", "$change", "$volume"]
    mkt = mkt.reset_index().set_index(["datetime", "instrument"]).sort_index()
    g = mkt.groupby(level="instrument")
    # 正确口径：T+1 开盘入场、T+1+h 开盘出场（open-to-open），无未来函数。
    # 注意：不可沿用 events_daily 脚本的 open[t+1]/close[t+h+1]-1（该式 ≈ 1/(1+r)-1 ≈ -r，
    # 方向反了，实测与正确口径 corr=-0.93）。
    for h in HORIZONS:
        mkt[f"FWD_{h}"] = g["$open"].shift(-(h + 1)) / g["$open"].shift(-1) - 1
    print(f"      rows={len(mkt)}, instruments={mkt.index.get_level_values('instrument').nunique()}", flush=True)

    # ---- 2. 基准 ----
    print("[2/6] Benchmark SH000852 ...", flush=True)
    bench = D.features([BENCHMARK], ["$open", "$close"],
                       start_time=LOAD_START, end_time=DATA_END, freq="day")
    bench.columns = ["$open", "$close"]
    bench = bench.reset_index().set_index(["datetime", "instrument"]).sort_index()
    bg = bench.groupby(level="instrument")
    for h in HORIZONS:
        bench[f"BENCH_{h}"] = bg["$open"].shift(-(h + 1)) / bg["$open"].shift(-1) - 1
    bench_fwd = bench.reset_index()[["datetime"] + [f"BENCH_{h}" for h in HORIZONS]]
    bench_fwd = bench_fwd.set_index("datetime").sort_index()

    # ---- 3. ST 区间 ----
    print("[3/6] ST intervals ...", flush=True)
    st = pd.read_csv(ST_INTERVALS, compression="gzip", parse_dates=["start_date", "end_date"])
    st_active = st.loc[st["is_st"] | st["is_delist_phase"], ["ts_code", "start_date", "end_date"]]

    # ---- 4. 事件合并 + 超额 ----
    print("[4/6] Merging events + excess returns ...", flush=True)
    events = load_events()
    print(f"      total events (deduped): {len(events):,}", flush=True)
    print(f"      by type: {events['event_type'].value_counts().to_dict()}", flush=True)

    mkt_df = mkt.reset_index()
    mask_close = mkt_df["$close"].notna() & mkt_df["$volume"].notna() & (mkt_df["$volume"] > 0)
    limit_thresh = np.where(mkt_df["instrument"].map(is_gem), LIMIT_GEM, LIMIT_MAIN)
    mask_close &= ~(mkt_df["$change"] >= limit_thresh)
    mkt_clean = mkt_df[mask_close].copy()
    mkt_clean["ts_code"] = mkt_clean["instrument"].map(qlib_to_ts)

    merge_cols = (["instrument", "datetime", "ts_code", "$close", "$volume"]
                  + [f"FWD_{h}" for h in HORIZONS])
    merged = events.merge(mkt_clean[merge_cols],
                          left_on=["instrument", "date"], right_on=["instrument", "datetime"], how="left")
    merged = merged.dropna(subset=[f"FWD_{HORIZONS[0]}"])

    # ST 过滤（公告日 asof：T2 用 st_check_date=公告日，其余类型=事件日）
    dates_in_ev = merged["st_check_date"].unique()
    st_by_date: dict[pd.Timestamp, set[str]] = {}
    for d in dates_in_ev:
        active = st_active[(st_active["start_date"] <= d) & (st_active["end_date"] >= d)]
        st_by_date[d] = set(active["ts_code"])
    merged = merged.assign(is_st=[
        c in st_by_date.get(d, set())
        for d, c in zip(merged["st_check_date"], merged["ts_code"])
    ])
    merged = merged[~merged["is_st"]]

    # 基准超额
    merged = merged.merge(bench_fwd, left_on="date", right_on="datetime", how="left")
    for h in HORIZONS:
        merged[f"EXC_{h}"] = merged[f"FWD_{h}"] - merged[f"BENCH_{h}"]
    print(f"      analyzable events: {len(merged):,}", flush=True)

    # ---- 5. 主检验：每类型 × H ----
    print("[5/6] Main test: excess by type ...", flush=True)
    e1_rows = []
    for t in sorted(merged["event_type"].unique()):
        sub = merged[merged["event_type"] == t]
        for h in HORIZONS:
            s = sub[f"EXC_{h}"]
            yearly = sub.groupby(sub["date"].dt.year)[f"EXC_{h}"].mean()
            n = len(s)
            tstat = s.mean() / (s.std(ddof=1) / np.sqrt(n)) if n > 30 and s.std(ddof=1) > 0 else np.nan
            e1_rows.append({
                "event_type": t, "horizon": h, "n": n,
                "excess_mean": s.mean(), "tstat": tstat,
                "yearly": json.dumps({int(y): float(v) for y, v in yearly.items()}),
            })
    e1 = pd.DataFrame(e1_rows)
    e1.to_csv(out / "event_excess_by_type.csv", index=False)

    # 分层报告（h=20 代表）：规模层用 $close×$volume 近似——改用市值代理（close）
    e2_rows = []
    sub20 = merged[merged["event_type"].isin(TYPE_PRIORITY)].copy()
    # 规模分层：事件日 close 五等分（代理市值）
    for t in sorted(sub20["event_type"].unique()):
        s = sub20[sub20["event_type"] == t]
        if len(s) < 50:
            continue
        s = s.assign(size_q=pd.qcut(s["$close"].rank(method="first"), 5, labels=False) + 1)
        for q in range(1, 6):
            qs = s[s["size_q"] == q]
            e2_rows.append({"event_type": t, "layer": f"size_q{q}", "n": len(qs),
                            "excess_mean_20d": qs[f"EXC_20"].mean()})
        # 事件规模分层（T3/T4 有数值列）
        if "change_ratio" in s.columns and s["change_ratio"].notna().any():
            med = s["change_ratio"].median()
            for lab, mask in [("大额", s["change_ratio"] >= med), ("小额", s["change_ratio"] < med)]:
                e2_rows.append({"event_type": t, "layer": f"减持{lab}", "n": int(mask.sum()),
                                "excess_mean_20d": s.loc[mask, "EXC_20"].mean()})
        if "float_ratio" in s.columns and s["float_ratio"].notna().any():
            med = s["float_ratio"].median()
            for lab, mask in [("大比例", s["float_ratio"] >= med), ("小比例", s["float_ratio"] < med)]:
                e2_rows.append({"event_type": t, "layer": f"解禁{lab}", "n": int(mask.sum()),
                                "excess_mean_20d": s.loc[mask, "EXC_20"].mean()})
    e2 = pd.DataFrame(e2_rows)
    e2.to_csv(out / "event_type_breakdown.csv", index=False)

    # ---- 6. 动量正交化（h=20 代表）+ 组间差异 + 判定 ----
    print("[6/6] Momentum orthogonality + pairwise + decision ...", flush=True)
    # 事件前 20 日收益（T+1 开盘 vs 20 日前开盘）
    pre = mkt_clean[["instrument", "datetime", "$open"]].copy()
    pre = pre.sort_values(["instrument", "datetime"])
    pre["open_lag20"] = pre.groupby("instrument")["$open"].shift(20)
    pre["pre_mom"] = pre["$open"] / pre["open_lag20"] - 1
    pre = pre[["instrument", "datetime", "pre_mom"]].rename(columns={"datetime": "date"})

    mom_rows = []
    for t in sorted(merged["event_type"].unique()):
        sub = merged[merged["event_type"] == t].merge(pre, on=["instrument", "date"], how="left")
        sub = sub.dropna(subset=["pre_mom", "EXC_20"])
        if len(sub) < 100:
            continue
        sub = sub.assign(mom_q=pd.qcut(sub["pre_mom"].rank(method="first"), 5, labels=False) + 1)
        quintiles = []
        for q in range(1, 6):
            qs = sub[sub["mom_q"] == q]
            quintiles.append(qs["EXC_20"].mean())
            mom_rows.append({"event_type": t, "momentum_quintile": q, "n": len(qs),
                             "mean_excess_h20": quintiles[-1]})
        # 动量代理判定（PEAD 式）：五分位超额是否随动量单调
        # 若事件超额被动量驱动，Q1→Q5 应呈单调趋势且 |Q5-Q1| 显著
        q1, q5 = quintiles[0], quintiles[-1]
        monotonic = all(quintiles[i] <= quintiles[i + 1] + 1e-12 for i in range(4)) or \
                    all(quintiles[i] >= quintiles[i + 1] - 1e-12 for i in range(4))
        mom_rows.append({"event_type": t, "momentum_quintile": 0, "n": len(sub),
                         "mean_excess_h20": np.nan, "q5_minus_q1": q5 - q1,
                         "monotonic": bool(monotonic)})
    mom_df = pd.DataFrame(mom_rows)
    mom_df.to_csv(out / "momentum_orthogonality.csv", index=False)

    # 组间差异（两两 Welch t，h=20）
    pair_rows = []
    types = sorted([t for t in merged["event_type"].unique() if len(merged[merged["event_type"] == t]) >= 50])
    for i, a in enumerate(types):
        for b in types[i + 1:]:
            sa = merged.loc[merged["event_type"] == a, "EXC_20"].dropna()
            sb = merged.loc[merged["event_type"] == b, "EXC_20"].dropna()
            tst, pval = stats.ttest_ind(sa, sb, equal_var=False)
            pair_rows.append({"type_a": a, "type_b": b, "n_a": len(sa), "n_b": len(sb),
                              "mean_a": sa.mean(), "mean_b": sb.mean(),
                              "diff_a_minus_b": sa.mean() - sb.mean(), "welch_t": tst, "p": pval})
    pair_df = pd.DataFrame(pair_rows)
    pair_df.to_csv(out / "type_pairwise_diff.csv", index=False)
    # ANOVA（四类主事件）
    anova_rows = []
    main_types = [t for t in ("T1", "T3", "T4", "T5") if t in merged["event_type"].unique()
                  and len(merged[merged["event_type"] == t]) >= 50]
    if len(main_types) >= 2:
        groups = [merged.loc[merged["event_type"] == t, "EXC_20"].dropna().values for t in main_types]
        fstat, pval = stats.f_oneway(*groups)
        anova_rows.append({"types": "+".join(main_types), "fstat": fstat, "p": pval,
                           "means": {t: float(merged.loc[merged["event_type"] == t, "EXC_20"].mean())
                                     for t in main_types}})
    anova_df = pd.DataFrame(anova_rows)
    if not anova_df.empty:
        anova_df.to_csv(out / "type_anova.csv", index=False)

    # 判定：每类型独立（h=20 主口径）
    decisions = {}
    for t in sorted(merged["event_type"].unique()):
        row = e1[(e1["event_type"] == t) & (e1["horizon"] == 20)].iloc[0]
        yearly = json.loads(row["yearly"])
        years_main = {int(y): v for y, v in yearly.items() if int(y) <= 2025}
        neg_years = sum(1 for v in years_main.values() if v < 0)
        # 动量代理判定（PEAD 式）：五分位单调 + |Q5-Q1| 显著
        mom_row = mom_df[(mom_df["event_type"] == t) & (mom_df["momentum_quintile"] == 0)]
        if not mom_row.empty:
            q_spread = float(mom_row["q5_minus_q1"].iloc[0])
            monotonic = bool(mom_row["monotonic"].iloc[0])
            momentum_artifact = monotonic and abs(q_spread) > 0.02
        else:
            q_spread, monotonic, momentum_artifact = np.nan, False, False
        sig_raw = row["tstat"] < -T_CRIT
        consistent = neg_years >= YEARLY_STRICT
        verdict = "event_layer_pass" if (sig_raw and consistent and not momentum_artifact) else \
                  ("momentum_artifact" if (sig_raw and consistent and momentum_artifact) else "not_supported")
        decisions[t] = {
            "n": int(row["n"]), "excess_mean_h20": float(row["excess_mean"]),
            "tstat_h20": float(row["tstat"]), "negative_years_2022_2025": neg_years,
            "consistent": bool(consistent), "mom_q5_minus_q1": q_spread,
            "mom_monotonic": bool(monotonic), "momentum_artifact": bool(momentum_artifact),
            "verdict": verdict,
        }
    (out / "decision.json").write_text(
        json.dumps({"decisions": decisions}, ensure_ascii=False, indent=2), encoding="utf-8")

    # 报告
    lines = [
        "# 负面事件分类型研究：事件后漂移检验报告 v1\n",
        f"- 母池: 沪深普通 A 股 {len(codes)} 只（剔北交所/指数/B 股 {len(excluded)}）",
        f"- 窗口: {EVAL_START} ~ {DATA_END}",
        f"- 超额口径: 事件股 T+1 开盘成交 H 日收益 − SH000852 同期",
        f"- 事件类型: T1 经营类-预亏/预减 / T2 制度类-ST 戴帽 / T3 资金类-减持 / "
        f"T4 资金类-解禁 / T5 交易类-跌幅上榜",
        f"- 判定门槛: h=20 t<−{T_CRIT} 且 2022-2025 ≥{YEARLY_STRICT} 年同向且动量正交后仍负\n",
        "## 主检验（每类型 × H，市场调整超额）",
    ]
    lines.append("| 类型 | H | n | 超额均值(日) | t | 分年度 |")
    lines.append("|---|---|---|---|---|---|")
    for _, r in e1.iterrows():
        lines.append(f"| {r['event_type']} | {r['horizon']} | {r['n']} | {r['excess_mean']:+.5f} "
                     f"| {r['tstat']:.2f} | {r['yearly']} |")

    lines.append("\n## 判定（每类型独立，h=20）")
    lines.append("| 类型 | n | 超额均值(日) | t | 负向年数(22-25) | 动量Q5-Q1 | 动量单调 | 判定 |")
    lines.append("|---|---|---|---|---|---|---|---|")
    for t, d in decisions.items():
        lines.append(f"| {t} | {d['n']} | {d['excess_mean_h20']:+.5f} | {d['tstat_h20']:.2f} "
                     f"| {d['negative_years_2022_2025']} | {d['mom_q5_minus_q1']:.4f} "
                     f"| {d['mom_monotonic']} | {d['verdict']} |")

    if not pair_df.empty:
        lines.append("\n## 组间差异（两两 Welch t，h=20）")
        lines.append("| A | B | mean_A | mean_B | diff(A−B) | welch_t | p |")
        lines.append("|---|---|---|---|---|---|---|")
        for _, r in pair_df.iterrows():
            lines.append(f"| {r['type_a']} | {r['type_b']} | {r['mean_a']:+.5f} | {r['mean_b']:+.5f} "
                         f"| {r['diff_a_minus_b']:+.5f} | {r['welch_t']:.2f} | {r['p']:.3f} |")

    if not anova_df.empty:
        r = anova_df.iloc[0]
        lines.append(f"\n## 组间 ANOVA（{r['types']}）")
        lines.append(f"F={r['fstat']:.2f}, p={r['p']:.4f}, means={r['means']}")

    (out / "validation_report.txt").write_text("\n".join(lines), encoding="utf-8")

    meta = {
        "purpose": "负面事件分类型研究：事件后漂移检验",
        "protocol": "research/protocols/a_share_negative_event_subtype_protocol_v1.md",
        "universe": f"沪深普通 A 股 {len(codes)} 只",
        "eval_window": [EVAL_START, DATA_END],
        "benchmark": BENCHMARK,
        "event_types": {k: TYPE_PRIORITY[k] for k in sorted(TYPE_PRIORITY)},
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
    }
    (out / "methodology.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    print("\n".join(lines), flush=True)
    print("DONE", flush=True)


if __name__ == "__main__":
    main()
