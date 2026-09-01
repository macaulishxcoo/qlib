"""
验证"交易集中度 + 优化比值"在周频/月频上是否对市场结构健康度有监测价值。

承接 verify_style_switch_v1.py 的结论:
  - 日频下指标前向预测力弱/不显著(短窗口p>0.2)、且慢变量共振伪显著。
  - 本脚本把同样的指标重采样到 W(周) / M(月) 末, 检验:
    1) 周频: 信号触发周 vs 非触发周的未来1-4周头部-全市场收益差 t 检验
    2) 月频: 指标未来1-3月头部-全市场收益差的 Rank IC
    3) 事件案例: 对照2018-2026已知A股风格切换月, 看指标在那些月的状态

样本: 2018-01 ~ 2026-08 (约105个月, 435周)
"""

import argparse
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

import qlib
from qlib.data import D

plt.rcParams["font.sans-serif"] = ["Noto Sans CJK SC", "Noto Serif CJK SC", "DejaVu Sans"]
plt.rcParams["axes.unicode_minus"] = False

RSI_PERIOD = 14
TOP_PCT = 0.05
OUTPUT_DIR = Path("output/style_switch_verification/lowfreq")
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

# 已知A股风格切换/极端月 (2018-2026), 用于案例对照
# (名称, 月份, 期望方向)
MONTHLY_EVENTS = [
    ("2018Q4 小市值危机(股权质押爆雷)",   "2018-10", "switch"),
    ("2019Q1 春季躁动(成长->价值切换)",    "2019-02", "switch"),
    ("2020Q1 疫情冲击(科技->医药切换)",     "2020-03", "switch"),
    ("2020Q7 题材股狂热(7月急涨回调)",      "2020-07", "overheat"),
    ("2021Q1 茅指数见顶(核心资产抱团破裂)", "2021-02", "switch"),
    ("2021Q9 周期股见顶(煤炭钢铁过热)",     "2021-09", "overheat"),
    ("2022Q4 防御->疫后复苏切换",          "2022-11", "switch"),
    ("2023Q1 GPT科技抱团起步",             "2023-02", "switch"),
    ("2023Q5 TMT见顶回落(中特估接力)",      "2023-05", "switch"),
    ("2024Q1 小微盘崩塌(微盘->大盘价值)",    "2024-01", "switch"),
    ("2024Q4 924急涨普涨",                 "2024-09", "overheat"),
    ("2025Q1 科技抱团起步",                 "2025-01", "switch"),
    ("2025Q3 科技回调",                    "2025-07", "overheat"),
]


def load_market_data(start, end):
    inst = D.list_instruments(instruments=D.instruments(market="all"), as_list=True)
    df = D.features(inst, ["$close", "$amount"], start_time=start, end_time=end)
    df = df.dropna(subset=["$close", "$amount"])
    df = df[df["$amount"] > 0]
    df = df.rename(columns={"$close": "close", "$amount": "amount"})
    df["datetime"] = df.index.get_level_values("datetime")
    df["instrument"] = df.index.get_level_values("instrument")
    return df.reset_index(drop=True)


def compute_rsi_panel(df, period=RSI_PERIOD):
    df = df.sort_values(["instrument", "datetime"])
    g = df.groupby("instrument")["close"]
    delta = g.transform(lambda x: x.diff())
    gain = delta.clip(lower=0)
    loss = (-delta).clip(lower=0)
    avg_gain = gain.groupby(df["instrument"]).transform(
        lambda x: x.ewm(alpha=1 / period, adjust=False).mean())
    avg_loss = loss.groupby(df["instrument"]).transform(
        lambda x: x.ewm(alpha=1 / period, adjust=False).mean())
    rs = avg_gain / avg_loss.replace(0, np.nan)
    df["rsi"] = 100 - 100 / (1 + rs)
    return df


def compute_daily_metrics(df):
    """逐日算 concentration / ratio / top_rsi / market_rsi。"""
    rows = []
    for dt, grp in df.groupby("datetime"):
        grp = grp.dropna(subset=["rsi"])
        if len(grp) < 100:
            continue
        grp = grp.sort_values("amount", ascending=False)
        n = len(grp)
        k = max(int(np.ceil(n * TOP_PCT)), 1)
        total = grp["amount"].sum()
        conc = grp["amount"].head(k).sum() / total if total > 0 else np.nan
        top_rsi = grp["rsi"].head(k).mean()
        mkt_rsi = grp["rsi"].mean()
        rows.append({
            "datetime": dt, "n_stocks": n, "top_k": k,
            "concentration": conc * 100,
            "top_rsi": top_rsi, "market_rsi": mkt_rsi,
            "ratio": (top_rsi / mkt_rsi * 100) if mkt_rsi > 0 else np.nan,
        })
    return pd.DataFrame(rows).set_index("datetime").sort_index()


def compute_daily_fwd_diff(df, horizons=(5, 10, 20, 40, 60)):
    """逐日 diff_h = 前5%成交额股票未来h日收益 - 全市场未来h日收益。"""
    d = df[["instrument", "datetime", "close", "amount"]].sort_values(["instrument", "datetime"])
    for h in horizons:
        d[f"fwd_{h}"] = d.groupby("instrument")["close"].pct_change(periods=h).shift(-h)
    d = d.dropna(subset=["close", "amount"])
    d = d[d["amount"] > 0]
    rows = []
    for dt, grp in d.groupby("datetime"):
        grp = grp.dropna(subset=[f"fwd_{h}" for h in horizons], how="all")
        if len(grp) < 100:
            continue
        grp = grp.sort_values("amount", ascending=False)
        rec = {"datetime": dt}
        for h in horizons:
            sub = grp.dropna(subset=[f"fwd_{h}"])
            if len(sub) < 50:
                rec[f"diff_{h}"] = np.nan
            else:
                kk = max(int(np.ceil(len(sub) * TOP_PCT)), 1)
                rec[f"diff_{h}"] = sub[f"fwd_{h}"].head(kk).mean() - sub[f"fwd_{h}"].mean()
        rows.append(rec)
    return pd.DataFrame(rows).set_index("datetime").sort_index()


def resample_to_freq(daily_df, freq, how="last"):
    """重采样: 周末/月末快照。how=last取期末值, how=mean取区间均值。"""
    s = daily_df.copy()
    if how == "last":
        s = s.resample(freq).last()
    elif how == "mean":
        s = s.resample(freq).mean()
    return s.dropna(how="all")


def build_quantile_signals(df, windows=(12, 24, 52), freq_label="W"):
    """对重采样后的指标序列, 按滚动窗口分位数构造切换信号。"""
    out = df.copy()
    for w in windows:
        cq = out["concentration"].rolling(w, min_periods=max(w // 2, 3)).quantile(0.90)
        rq_lo = out["ratio"].rolling(w, min_periods=max(w // 2, 3)).quantile(0.10)
        rq_hi = out["ratio"].rolling(w, min_periods=max(w // 2, 3)).quantile(0.90)
        out[f"conc_q90_w{w}"] = cq
        out[f"ratio_q10_w{w}"] = rq_lo
        out[f"ratio_q90_w{w}"] = rq_hi
        out[f"signal_switch_w{w}"] = (out["concentration"] >= cq) & (
            (out["ratio"] <= rq_lo) | (out["ratio"] >= rq_hi))
        out[f"signal_overheat_w{w}"] = (out["ratio"] >= rq_hi) & (out["concentration"] >= cq)
        out[f"signal_miskill_w{w}"] = (out["ratio"] <= rq_lo) & (out["concentration"] >= cq)
    return out


def predictive_t_test(merged, signal_col, diff_cols):
    from scipy import stats
    rows = []
    for dc in diff_cols:
        on = merged.loc[merged[signal_col], dc].dropna()
        off = merged.loc[~merged[signal_col], dc].dropna()
        if len(on) < 3 or len(off) < 3:
            rows.append({"signal": signal_col, "horizon": dc, "n_on": len(on),
                         "n_off": len(off), "diff_on": np.nan, "diff_off": np.nan,
                         "t_stat": np.nan, "p_value": np.nan})
            continue
        t, p = stats.ttest_ind(on, off, equal_var=False)
        rows.append({"signal": signal_col, "horizon": dc, "n_on": len(on),
                     "n_off": len(off), "diff_on": round(on.mean(), 5),
                     "diff_off": round(off.mean(), 5),
                     "t_stat": round(t, 2), "p_value": round(p, 4)})
    return pd.DataFrame(rows)


def rank_ic_test(merged, indicator_cols, diff_cols):
    """Spearman秩相关: 指标值 vs 未来收益差。"""
    from scipy import stats
    rows = []
    for ic in indicator_cols:
        for dc in diff_cols:
            sub = merged[[ic, dc]].dropna()
            if len(sub) < 8:
                rows.append({"indicator": ic, "horizon": dc, "n": len(sub),
                             "rank_ic": np.nan, "p_value": np.nan})
                continue
            r, p = stats.spearmanr(sub[ic], sub[dc])
            rows.append({"indicator": ic, "horizon": dc, "n": len(sub),
                         "rank_ic": round(r, 3), "p_value": round(p, 4)})
    return pd.DataFrame(rows)


def event_case_study(monthly, events=MONTHLY_EVENTS):
    rec = []
    for name, ym, direction in events:
        ts = pd.Timestamp(ym) + pd.offsets.MonthEnd(0)
        # 取该月末及前后1月的指标
        ctx = monthly.loc[:ts].tail(3) if len(monthly.loc[:ts]) > 0 else pd.DataFrame()
        if len(ctx) == 0:
            rec.append({"event": name, "month": ym, "expected": direction,
                        "conc": np.nan, "ratio": np.nan, "note": "no data"})
            continue
        last = ctx.iloc[-1]
        rec.append({
            "event": name, "month": ym, "expected": direction,
            "conc": round(last["concentration"], 1) if "concentration" in last else np.nan,
            "ratio": round(last["ratio"], 1) if "ratio" in last else np.nan,
            "conc_prev3_mean": round(ctx["concentration"].mean(), 1) if "concentration" in ctx else np.nan,
            "ratio_prev3_mean": round(ctx["ratio"].mean(), 1) if "ratio" in ctx else np.nan,
        })
    return pd.DataFrame(rec)


def plot_lowfreq(weekly, monthly):
    fig, axes = plt.subplots(2, 1, figsize=(14, 8), sharex=False)
    ax1, ax2 = axes
    ax1.plot(weekly.index, weekly["concentration"], color="#2c7fb8", lw=0.8, label="集中度(%)")
    ax1x = ax1.twinx()
    ax1x.plot(weekly.index, weekly["ratio"], color="#d95f0e", lw=0.8, label="优化比值(%)")
    ax1.axhline(weekly["concentration"].median(), color="#2c7fb8", ls=":", lw=0.8)
    ax1x.axhline(100, color="gray", ls=":", lw=0.8)
    ax1.set_ylabel("集中度 (%)")
    ax1x.set_ylabel("优化比值 (%)")
    ax1.set_title("周频: 集中度与优化比值 (2018-2026)")
    ax1.grid(alpha=0.3)

    ax2.plot(monthly.index, monthly["concentration"], color="#2c7fb8", marker="o", ms=3, label="集中度(%)")
    ax2x = ax2.twinx()
    ax2x.plot(monthly.index, monthly["ratio"], color="#d95f0e", marker="o", ms=3, label="优化比值(%)")
    for name, ym, _ in MONTHLY_EVENTS:
        ts = pd.Timestamp(ym) + pd.offsets.MonthEnd(0)
        if ts in monthly.index:
            ax2.axvline(ts, color="red", alpha=0.3, lw=0.8)
    ax2.set_ylabel("集中度 (%)")
    ax2x.set_ylabel("优化比值 (%)")
    ax2.set_title("月频: 集中度与优化比值 (红线=已知风格切换月)")
    ax2.grid(alpha=0.3)
    plt.tight_layout()
    out = OUTPUT_DIR / "lowfreq_metrics.png"
    plt.savefig(out, dpi=130)
    plt.close(fig)
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--start", default="2017-10-01", help="含RSI预热")
    ap.add_argument("--end", default="2026-08-20")
    ap.add_argument("--eval-start", default="2018-01-01")
    args = ap.parse_args()

    qlib.init(provider_uri="~/.qlib/qlib_data/cn_data_2026", region="cn")

    print(f"[1/6] 加载全市场 {args.start} ~ {args.end} ...")
    raw = load_market_data(args.start, args.end)
    print(f"      行数={len(raw):,} 股票数={raw['instrument'].nunique()}")

    print("[2/6] 计算RSI14 + 逐日指标 ...")
    with_rsi = compute_rsi_panel(raw)
    with_rsi = with_rsi[with_rsi["datetime"] >= pd.Timestamp(args.eval_start)]
    daily = compute_daily_metrics(with_rsi)
    print(f"      日频交易日={len(daily)}")

    print("[3/6] 重采样到周/月频 ...")
    weekly = resample_to_freq(daily, "W", how="last")
    monthly = resample_to_freq(daily, "M", how="last")
    print(f"      周数={len(weekly)} 月数={len(monthly)}")
    print("--- 周频描述 ---")
    print(weekly[["concentration", "ratio"]].describe().round(2))
    print("--- 月频描述 ---")
    print(monthly[["concentration", "ratio"]].describe().round(2))

    print("[4/6] 计算日频前向收益差, 再重采样到周/月 ...")
    # 日频 diff, 周频 horizon=5,10,20,40 日; 月频=20,40,60 日
    daily_fwd = compute_daily_fwd_diff(raw, horizons=(5, 10, 20, 40, 60))
    weekly_fwd = resample_to_freq(daily_fwd, "W", how="last")
    monthly_fwd = resample_to_freq(daily_fwd, "M", how="last")

    print("[5/6] 周频 t 检验 + 月频 Rank IC ...")
    # 周频: 滚动窗口用 12/24/52 周(约3/6/12月)
    weekly_full = build_quantile_signals(weekly, windows=(12, 24, 52), freq_label="W")
    weekly_merged = weekly_full.join(weekly_fwd[[c for c in weekly_fwd.columns if c.startswith("diff_")]], how="inner")
    w_diff_cols = ["diff_5", "diff_10", "diff_20", "diff_40"]
    w_t_results = []
    for w in (12, 24, 52):
        for sig in [f"signal_switch_w{w}", f"signal_overheat_w{w}", f"signal_miskill_w{w}"]:
            r = predictive_t_test(weekly_merged, sig, w_diff_cols)
            w_t_results.append(r)
    w_t = pd.concat(w_t_results, ignore_index=True)
    print("--- 周频 t 检验 ---")
    print(w_t.to_string(index=False))

    # 月频: 滚动窗口 6/12/24 月
    monthly_full = build_quantile_signals(monthly, windows=(6, 12, 24), freq_label="M")
    monthly_merged = monthly_full.join(monthly_fwd[[c for c in monthly_fwd.columns if c.startswith("diff_")]], how="inner")
    # Rank IC: 指标水平 vs 未来收益差
    m_ic_cols = ["diff_20", "diff_40", "diff_60"]
    m_ic = rank_ic_test(monthly_merged, ["concentration", "ratio", "top_rsi", "market_rsi"], m_ic_cols)
    print("--- 月频 Rank IC ---")
    print(m_ic.to_string(index=False))
    # 月频 t 检验
    m_t_results = []
    for w in (6, 12, 24):
        for sig in [f"signal_switch_w{w}", f"signal_overheat_w{w}", f"signal_miskill_w{w}"]:
            r = predictive_t_test(monthly_merged, sig, m_ic_cols)
            m_t_results.append(r)
    m_t = pd.concat(m_t_results, ignore_index=True)
    print("--- 月频 t 检验 ---")
    print(m_t.to_string(index=False))

    print("[5.5/6] 事件案例对照 ...")
    ev = event_case_study(monthly)
    print(ev.to_string(index=False))

    print("[6/6] 输出 ...")
    weekly.to_csv(OUTPUT_DIR / "weekly_metrics.csv")
    monthly.to_csv(OUTPUT_DIR / "monthly_metrics.csv")
    w_t.to_csv(OUTPUT_DIR / "weekly_t_test.csv", index=False)
    m_ic.to_csv(OUTPUT_DIR / "monthly_rank_ic.csv", index=False)
    m_t.to_csv(OUTPUT_DIR / "monthly_t_test.csv", index=False)
    ev.to_csv(OUTPUT_DIR / "monthly_event_cases.csv", index=False)
    fig = plot_lowfreq(weekly, monthly)
    print(f"      图表: {fig}")


if __name__ == "__main__":
    main()
