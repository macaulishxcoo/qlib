"""
验证"交易集中度 + 优化比值(RSI比值)"策略能否识别 A 股风格切换。

策略来源（截图）：
  - 集中度 = 成交额前 5% 股票成交额之和 / 全市场总成交额
      阈值: > 45% 伴随反转或风格切换
  - 优化比值 = 前 5% 成交额股票的 RSI 均值 / 全市场所有股票 RSI 均值
      阈值: > 130% 过热; < 90% 错杀; = 100% 健康
  - 风格切换判别: 集中度与优化比值同时处于极端位置

本脚本：
  1) 逐日向量化计算两指标（含 RSI14 序列）。
  2) 标记三种信号: 过热 / 错杀 / 风格切换概率。
  3) 对照已知 A 股风格切换时点（2024-2026）检验命中情况。
  4) 输出: 时间序列 CSV + 信号命中表 + 图表 + Markdown 报告。
"""

import argparse
import os
import sys
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

# ---- 已知 A 股风格切换/极端事件时点（用于回测验证） ----
# 每个事件: (名称, 窗口起, 窗口止, 预期信号方向)
#   direction: "overheat"=过热后回落 / "miskill"=错杀反弹 / "switch"=风格切换
STYLE_EVENTS = [
    ("2024年初小盘股崩塌 (小微盘→大盘价值切换)", "2024-01-15", "2024-02-08", "switch"),
    ("2024年4月新国九条 (红利风格强化)",       "2024-04-10", "2024-04-30", "switch"),
    ("2024年9月底急涨普涨 (市场情绪反转)",      "2024-09-20", "2024-10-08", "overheat"),
    ("2024年11月-12月小微盘反弹",              "2024-11-15", "2024-12-20", "miskill"),
    ("2025年初科技抱团起步 (科技→红利切换)",     "2025-01-15", "2025-02-15", "switch"),
    ("2025年3-4月科技股过热回调",              "2025-03-15", "2025-04-15", "overheat"),
    ("2025年6-7月风格再切换",                  "2025-06-15", "2025-07-15", "switch"),
]

RSI_PERIOD = 14
TOP_PCT = 0.05  # 前 5%

OUTPUT_DIR = Path("output/style_switch_verification")
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)


def load_market_data(start: str, end: str) -> pd.DataFrame:
    """加载全市场 close + amount，返回长表 (instrument, datetime)。"""
    inst = D.list_instruments(instruments=D.instruments(market="all"), as_list=True)
    df = D.features(inst, ["$close", "$amount"], start_time=start, end_time=end)
    df = df.dropna(subset=["$close", "$amount"])
    df = df[df["$amount"] > 0]
    df = df.rename(columns={"$close": "close", "$amount": "amount"})
    df["datetime"] = df.index.get_level_values("datetime")
    df["instrument"] = df.index.get_level_values("instrument")
    return df.reset_index(drop=True)


def compute_rsi_panel(df: pd.DataFrame, period: int = RSI_PERIOD) -> pd.DataFrame:
    """对每只股票算 RSI14，返回含 rsi 列的 DataFrame。"""
    df = df.sort_values(["instrument", "datetime"])
    # 用 groupby + transform 做向量化 RSI
    g = df.groupby("instrument")["close"]
    delta = g.transform(lambda x: x.diff())
    gain = delta.clip(lower=0)
    loss = (-delta).clip(lower=0)
    # Wilder 平均 = ewm(alpha=1/period)
    avg_gain = gain.groupby(df["instrument"]).transform(
        lambda x: x.ewm(alpha=1 / period, adjust=False).mean()
    )
    avg_loss = loss.groupby(df["instrument"]).transform(
        lambda x: x.ewm(alpha=1 / period, adjust=False).mean()
    )
    rs = avg_gain / avg_loss.replace(0, np.nan)
    df["rsi"] = 100 - 100 / (1 + rs)
    return df


def compute_daily_metrics(df: pd.DataFrame, top_pct: float = TOP_PCT) -> pd.DataFrame:
    """逐日计算集中度、优化比值、top5% RSI 均值、全市场 RSI 均值。"""
    rows = []
    for dt, grp in df.groupby("datetime"):
        grp = grp.dropna(subset=["rsi"])
        if len(grp) < 100:  # 当日有效股票太少跳过
            continue
        grp = grp.sort_values("amount", ascending=False)
        n = len(grp)
        k = max(int(np.ceil(n * top_pct)), 1)
        total_amt = grp["amount"].sum()
        top_amt = grp["amount"].head(k).sum()
        concentration = top_amt / total_amt if total_amt > 0 else np.nan
        top_rsi = grp["rsi"].head(k).mean()
        mkt_rsi = grp["rsi"].mean()
        ratio = (top_rsi / mkt_rsi * 100) if mkt_rsi > 0 else np.nan
        rows.append(
            {
                "datetime": dt,
                "n_stocks": n,
                "top_k": k,
                "concentration": concentration * 100,  # 百分比
                "top_rsi": top_rsi,
                "market_rsi": mkt_rsi,
                "ratio": ratio,  # 百分比
            }
        )
    out = pd.DataFrame(rows).set_index("datetime").sort_index()
    return out


def label_signals(m: pd.DataFrame) -> pd.DataFrame:
    """按截图阈值标记三种信号 + 滚动分位数自适应信号（默认窗口在 build_adaptive 中给定）。"""
    m = m.copy()
    # 过热: 比值 > 130 且集中度高位(>40)
    m["signal_overheat"] = (m["ratio"] > 130) & (m["concentration"] > 40)
    # 错杀: 比值 < 90 且集中度依然较高(>40)
    m["signal_miskill"] = (m["ratio"] < 90) & (m["concentration"] > 40)
    # 风格切换: 集中度 > 45 且 比值极端(<90 或 >130)
    m["signal_switch"] = (m["concentration"] > 45) & (
        (m["ratio"] < 90) | (m["ratio"] > 130)
    )
    return m


def build_adaptive_signals(m: pd.DataFrame, windows=(20, 60, 120, 252)) -> pd.DataFrame:
    """
    对每个滚动窗口 w, 构造自适应信号:
      conc_w >= 该窗口分位90  且  ratio 越过该窗口 10/90 分位
    命名: signal_switch_w20 / signal_switch_w60 ...
    返回拼接所有窗口信号的 DataFrame (以 datetime 为索引, 各列为布尔)。
    """
    cols = []
    for w in windows:
        cq = m["concentration"].rolling(w, min_periods=max(w // 3, 10)).quantile(0.90)
        rq_lo = m["ratio"].rolling(w, min_periods=max(w // 3, 10)).quantile(0.10)
        rq_hi = m["ratio"].rolling(w, min_periods=max(w // 3, 10)).quantile(0.90)
        sw = (m["concentration"] >= cq) & ((m["ratio"] <= rq_lo) | (m["ratio"] >= rq_hi))
        oh = (m["ratio"] >= rq_hi) & (m["concentration"] >= cq)
        mk = (m["ratio"] <= rq_lo) & (m["concentration"] >= cq)
        cols.append(pd.DataFrame({
            f"signal_switch_w{w}": sw,
            f"signal_overheat_w{w}": oh,
            f"signal_miskill_w{w}": mk,
        }, index=m.index))
    return pd.concat([m] + cols, axis=1)


def window_predictive_comparison(m: pd.DataFrame, windows=(20, 60, 120, 252), horizons=(3, 5, 10, 20)) -> pd.DataFrame:
    """
    对比不同滚动窗口下自适应信号的前向预测力。
    每个窗口 w × 每个 horizon h: t 检验 (触发日 vs 非触发日的 diff_h)。
    """
    # 先算 diff_h (头部 - 全市场未来收益)
    # 这里 m 已含 concentration/ratio, 但前向收益需要在原始个股上算;
    # 为避免重复, 此函数只接受已含 diff_h 列的 m。
    fwd_cols = [c for c in m.columns if c.startswith("diff_")]
    if not fwd_cols:
        return pd.DataFrame()
    rows = []
    from scipy import stats
    for w in windows:
        for h in horizons:
            dcol = f"diff_{h}"
            scol = f"signal_switch_w{w}"
            if scol not in m.columns or dcol not in m.columns:
                continue
            on = m.loc[m[scol], dcol].dropna()
            off = m.loc[~m[scol], dcol].dropna()
            if len(on) < 3 or len(off) < 3:
                rows.append({"window": w, "horizon": h, "n_on": len(on), "n_off": len(off),
                             "diff_on": np.nan, "diff_off": np.nan, "t_stat": np.nan, "p_value": np.nan})
                continue
            t, p = stats.ttest_ind(on, off, equal_var=False)
            rows.append({"window": w, "horizon": h, "n_on": len(on), "n_off": len(off),
                         "diff_on": round(on.mean(), 5), "diff_off": round(off.mean(), 5),
                         "t_stat": round(t, 2), "p_value": round(p, 4)})
    return pd.DataFrame(rows)


def evaluate_events(m: pd.DataFrame, events=STYLE_EVENTS, windows=(20, 60, 120, 252)) -> pd.DataFrame:
    """对每个已知事件窗口，统计固定阈值 + 各滚动窗口信号的触发情况。"""
    rec = []
    for name, s, e, direction in events:
        s = pd.Timestamp(s)
        e = pd.Timestamp(e)
        win = m.loc[s:e]
        row = {"event": name, "expected": direction, "days": len(win)}
        if len(win) == 0:
            row["hit_fixed"] = "NO_DATA"
            for w in windows:
                row[f"sw_w{w}"] = 0
                row[f"hit_w{w}"] = "NO_DATA"
            rec.append(row)
            continue
        oh = win["signal_overheat"].sum()
        mk = win["signal_miskill"].sum()
        sw = win["signal_switch"].sum()
        row.update({
            "conc_mean": round(win["concentration"].mean(), 2),
            "ratio_mean": round(win["ratio"].mean(), 2),
            "ratio_min": round(win["ratio"].min(), 2),
            "ratio_max": round(win["ratio"].max(), 2),
            "oh_fixed": int(oh), "mk_fixed": int(mk), "sw_fixed": int(sw),
        })
        # 固定命中
        if direction == "overheat":
            row["hit_fixed"] = "HIT" if (oh > 0 or sw > 0) else "MISS"
        elif direction == "miskill":
            row["hit_fixed"] = "HIT" if (mk > 0 or sw > 0) else "MISS"
        else:
            row["hit_fixed"] = "HIT" if (sw > 0 or oh > 0 or mk > 0) else "MISS"
        # 各窗口自适应命中
        for w in windows:
            scol = f"signal_switch_w{w}"
            n = int(win[scol].sum()) if scol in win.columns else 0
            row[f"sw_w{w}"] = n
            row[f"hit_w{w}"] = "HIT" if n > 0 else "MISS"
        rec.append(row)
    return pd.DataFrame(rec)


def compute_forward_diff(raw: pd.DataFrame, horizons=(3, 5, 10, 20)) -> pd.DataFrame:
    """
    计算每日: 前5%成交额股票未来h日收益 - 全市场未来h日收益 (diff_h)。
    diff_h > 0 -> 头部相对走强; < 0 -> 头部走弱(风格切向小盘)。
    """
    df = raw[["instrument", "datetime", "close", "amount"]].sort_values(["instrument", "datetime"])
    for h in horizons:
        # t 行的未来 h 日收益 = (close[t+h] - close[t]) / close[t]
        df[f"fwd_{h}"] = df.groupby("instrument")["close"].pct_change(periods=h).shift(-h)
    df = df.dropna(subset=["close", "amount"])
    df = df[df["amount"] > 0]
    rows = []
    for dt, grp in df.groupby("datetime"):
        grp = grp.dropna(subset=[f"fwd_{h}" for h in horizons], how="all")
        if len(grp) < 100:
            continue
        grp = grp.sort_values("amount", ascending=False)
        rec = {"datetime": dt}
        for h in horizons:
            col = f"fwd_{h}"
            sub = grp.dropna(subset=[col])
            if len(sub) < 50:
                rec[f"diff_{h}"] = np.nan
            else:
                kk = max(int(np.ceil(len(sub) * TOP_PCT)), 1)
                top_r = sub[col].head(kk).mean()
                mkt_r = sub[col].mean()
                rec[f"diff_{h}"] = top_r - mkt_r
        rows.append(rec)
    return pd.DataFrame(rows).set_index("datetime").sort_index()


def forward_predictive_test(raw: pd.DataFrame, m: pd.DataFrame, horizons=(3, 5, 10, 20)) -> pd.DataFrame:
    """
    固定阈值信号的前向预测力 t 检验 (触发日 vs 非触发日 diff_h)。
    多窗口自适应信号的对比由 window_predictive_comparison 完成。
    """
    fwd = compute_forward_diff(raw, horizons)
    merged = m.join(fwd, how="inner")
    from scipy import stats
    test_rows = []
    sig_cols = [
        ("signal_overheat", "过热(固定)"),
        ("signal_miskill", "错杀(固定)"),
        ("signal_switch", "切换(固定)"),
    ]
    for col, label in sig_cols:
        for h in horizons:
            dcol = f"diff_{h}"
            on = merged.loc[merged[col], dcol].dropna()
            off = merged.loc[~merged[col], dcol].dropna()
            if len(on) < 3 or len(off) < 3:
                continue
            t, p = stats.ttest_ind(on, off, equal_var=False)
            test_rows.append({
                "signal": label, "horizon": h, "n_on": len(on), "n_off": len(off),
                "diff_on": round(on.mean(), 5), "diff_off": round(off.mean(), 5),
                "t_stat": round(t, 2), "p_value": round(p, 4),
            })
    return pd.DataFrame(test_rows)


def plot_metrics(m: pd.DataFrame, events=STYLE_EVENTS):
    fig, axes = plt.subplots(3, 1, figsize=(14, 10), sharex=True)
    ax1, ax2, ax3 = axes

    ax1.plot(m.index, m["concentration"], color="#2c7fb8", lw=0.8, label="集中度(%)")
    ax1.axhline(45, color="red", ls="--", lw=1, label="45% 切换阈值")
    ax1.set_ylabel("集中度 (%)")
    ax1.set_title("成交额前5%股票 集中度")
    ax1.legend(loc="upper left")
    ax1.grid(alpha=0.3)

    ax2.plot(m.index, m["ratio"], color="#d95f0e", lw=0.8, label="优化比值(%)")
    ax2.axhline(130, color="red", ls="--", lw=1, label="130% 过热")
    ax2.axhline(90, color="green", ls="--", lw=1, label="90% 错杀")
    ax2.axhline(100, color="gray", ls=":", lw=1)
    ax2.set_ylabel("优化比值 (%)")
    ax2.set_title("前5% RSI均值 / 全市场 RSI均值")
    ax2.legend(loc="upper left")
    ax2.grid(alpha=0.3)

    # 信号叠加
    ax3.plot(m.index, m["ratio"], color="#7570b3", lw=0.6, alpha=0.5)
    ax3.scatter(m.index[m["signal_overheat"]], m["ratio"][m["signal_overheat"]],
                color="red", s=8, label="过热")
    ax3.scatter(m.index[m["signal_miskill"]], m["ratio"][m["signal_miskill"]],
                color="green", s=8, label="错杀")
    ax3.scatter(m.index[m["signal_switch"]], m["ratio"][m["signal_switch"]],
                color="black", s=10, marker="x", label="风格切换")
    ax3.axhline(130, color="red", ls="--", lw=0.8)
    ax3.axhline(90, color="green", ls="--", lw=0.8)
    ax3.set_ylabel("优化比值 (%)")
    ax3.set_title("信号标记")
    ax3.legend(loc="upper left")
    ax3.grid(alpha=0.3)

    # 事件窗口阴影
    for name, s, e, _ in events:
        for ax in axes:
            ax.axvspan(pd.Timestamp(s), pd.Timestamp(e), color="orange", alpha=0.12)

    plt.tight_layout()
    out = OUTPUT_DIR / "style_switch_metrics.png"
    plt.savefig(out, dpi=130)
    plt.close(fig)
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--start", default="2023-11-01", help="数据起点(含RSI预热)")
    ap.add_argument("--end", default="2026-08-20")
    ap.add_argument("--eval-start", default="2024-01-01", help="指标评估起点")
    args = ap.parse_args()

    qlib.init(provider_uri="~/.qlib/qlib_data/cn_data_2026", region="cn")

    print(f"[1/5] 加载全市场数据 {args.start} ~ {args.end} ...")
    raw = load_market_data(args.start, args.end)
    print(f"      行数={len(raw):,}, 股票数={raw['instrument'].nunique()}")

    print("[2/5] 计算 RSI14 ...")
    with_rsi = compute_rsi_panel(raw, RSI_PERIOD)
    with_rsi = with_rsi[with_rsi["datetime"] >= pd.Timestamp(args.eval_start)]
    print(f"      评估区间行数={len(with_rsi):,}")

    print("[3/5] 逐日计算集中度 / 优化比值 ...")
    m = compute_daily_metrics(with_rsi)
    m = label_signals(m)
    WINDOWS = (20, 60, 120, 252)
    m = build_adaptive_signals(m, windows=WINDOWS)
    print(f"      交易日数={len(m)}")
    print(m[["concentration", "ratio"]].describe().round(2))

    print("[4/5] 对照已知风格切换事件 ...")
    ev = evaluate_events(m, windows=WINDOWS)
    print(ev.to_string(index=False))

    print("[4.5/5] 前向预测力检验 (信号 vs 头部-全市场未来收益差) ...")
    HORIZONS = (3, 5, 10, 20)
    fwd = compute_forward_diff(raw, horizons=HORIZONS)
    m_with_fwd = m.join(fwd, how="inner")
    fwd_test = forward_predictive_test(raw, m, horizons=HORIZONS)
    print("--- 固定阈值 ---")
    print(fwd_test.to_string(index=False))
    win_test = window_predictive_comparison(m_with_fwd, windows=WINDOWS, horizons=HORIZONS)
    print("--- 多窗口自适应 (滚动分位数) ---")
    print(win_test.to_string(index=False))

    print("[5/5] 输出 ...")
    m_out = OUTPUT_DIR / "daily_metrics.csv"
    m.to_csv(m_out)
    ev_out = OUTPUT_DIR / "event_hit_table.csv"
    ev.to_csv(ev_out, index=False)
    fwd_out = OUTPUT_DIR / "forward_predictive_test.csv"
    fwd_test.to_csv(fwd_out, index=False)
    win_out = OUTPUT_DIR / "window_predictive_test.csv"
    win_test.to_csv(win_out, index=False)
    fig = plot_metrics(m)
    print(f"      指标序列:     {m_out}")
    print(f"      命中表:       {ev_out}")
    print(f"      前向检验(固定): {fwd_out}")
    print(f"      前向检验(多窗口): {win_out}")
    print(f"      图表:         {fig}")

    # 统计
    hit = (ev["hit_fixed"] == "HIT").sum()
    print(f"\n命中统计(固定阈值): {hit}/{len(ev)}")
    for w in WINDOWS:
        h = (ev[f"hit_w{w}"] == "HIT").sum()
        print(f"命中统计(滚动 w={w}): {h}/{len(ev)}")


if __name__ == "__main__":
    main()
