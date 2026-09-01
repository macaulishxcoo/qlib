"""
对"优化比值(ratio)月频 Rank IC=0.258"做样本外验证(OOS)。

之前的 IC=0.258 是全样本(in-sample)结果: 既用2018-2026全部数据发现
"ratio在20日horizon有效", 又在同一份数据上测出 IC。这是看答案打分。

本脚本做三件样本外检验:
  1) 时间切分OOS: train(2018-2022)选规则 -> test(2023-2026)测IC
  2) 滚动IC: 每12个月滚动, 看IC是稳定还是只在某段爆发
  3) 极端值影响: 逐个去掉极端月份, 看IC是否由个别点撑起
"""

from pathlib import Path
import numpy as np
import pandas as pd
from scipy import stats

OUTPUT_DIR = Path("output/style_switch_verification/lowfreq")


def load_monthly_with_fwd():
    """合并月频指标 + 未来20日收益差(diff_20)。"""
    m = pd.read_csv(OUTPUT_DIR / "monthly_metrics.csv", parse_dates=["datetime"]).set_index("datetime")
    fwd = pd.read_csv(OUTPUT_DIR / "monthly_metrics.csv", parse_dates=["datetime"]).set_index("datetime")
    # daily_fwd 重采样到月末的 diff_h
    # 这里直接从日频 fwd 重算, 保证 diff_20 是"月末未来20交易日"的头部-市场收益差
    # 但 monthly_metrics.csv 没存 diff, 需从日频重算
    return m, fwd


def compute_ic(data, indicator, target, min_n=8):
    sub = data[[indicator, target]].dropna()
    if len(sub) < min_n:
        return np.nan, np.nan, len(sub)
    r, p = stats.spearmanr(sub[indicator], sub[target])
    return r, p, len(sub)


def oos_time_split(m_with_fwd, indicators=("ratio", "concentration", "top_rsi", "market_rsi"),
                   targets=("diff_20", "diff_40", "diff_60"), split="2023-01-01"):
    """时间切分样本外验证: train选最优(indicator+target), test测IC。"""
    train = m_with_fwd.loc[:split]
    test = m_with_fwd.loc[split:]
    rows = []
    # 在train上, 扫所有 indicator×target, 选 IC p值最小的组合作为"发现"
    best = None
    for ind in indicators:
        for tgt in targets:
            r, p, n = compute_ic(train, ind, tgt)
            rows.append({"phase": "train", "indicator": ind, "target": tgt,
                         "rank_ic": round(r, 3) if not np.isnan(r) else np.nan,
                         "p_value": round(p, 4) if not np.isnan(p) else np.nan,
                         "n": n})
            if not np.isnan(p) and (best is None or p < best[3]):
                best = (ind, tgt, r, p, n)
    # 把这个"在train上发现的最优组合"冻结, 在test上测IC
    if best:
        ind, tgt, r_in, p_in, n_in = best
        r_out, p_out, n_out = compute_ic(test, ind, tgt)
        rows.append({"phase": "TEST_OOS", "indicator": ind, "target": tgt,
                     "rank_ic": round(r_out, 3) if not np.isnan(r_out) else np.nan,
                     "p_value": round(p_out, 4) if not np.isnan(p_out) else np.nan,
                     "n": n_out})
        rows.append({"phase": "train(参考)", "indicator": ind, "target": tgt,
                     "rank_ic": round(r_in, 3), "p_value": round(p_in, 4), "n": n_in})
    # 同时也把每个 indicator 在 test 上的 diff_20 IC 列出, 看全貌
    for ind in indicators:
        r_out, p_out, n_out = compute_ic(test, ind, "diff_20")
        rows.append({"phase": "test_all(diff_20)", "indicator": ind, "target": "diff_20",
                     "rank_ic": round(r_out, 3) if not np.isnan(r_out) else np.nan,
                     "p_value": round(p_out, 4) if not np.isnan(p_out) else np.nan,
                     "n": n_out})
    return pd.DataFrame(rows), best


def rolling_ic(m_with_fwd, indicator, target, window=24):
    """滚动 window 个月算IC, 看时变稳定性。"""
    df = m_with_fwd[[indicator, target]].dropna().sort_index()
    rows = []
    for i in range(window, len(df) + 1):
        sub = df.iloc[i - window:i]
        if len(sub) < 8:
            continue
        r, p = stats.spearmanr(sub[indicator], sub[target])
        rows.append({"end_month": sub.index[-1], "rank_ic": round(r, 3),
                     "p_value": round(p, 4), "n": len(sub)})
    return pd.DataFrame(rows).set_index("end_month")


def leave_one_out_extremes(m_with_fwd, indicator, target, top_k=5):
    """逐个去掉 ratio 最大的 top_k 个月, 看IC是否由极端点撑起。"""
    df = m_with_fwd[[indicator, target]].dropna().sort_values(indicator, ascending=False)
    extreme_months = df.head(top_k).index.tolist()
    base_r, base_p, base_n = compute_ic(m_with_fwd, indicator, target)
    rows = [{"removed_month": "(全样本)", "rank_ic": round(base_r, 3),
             "p_value": round(base_p, 4), "n": base_n}]
    all_df = m_with_fwd[[indicator, target]].dropna()
    for m_ in extreme_months:
        sub = all_df.drop(m_)
        r, p, n = compute_ic(sub, indicator, target)
        rows.append({"removed_month": m_.strftime("%Y-%m"),
                     "rank_ic": round(r, 3), "p_value": round(p, 4), "n": n})
    # 同时去掉所有 top_k
    sub = all_df.drop(extreme_months)
    r, p, n = compute_ic(sub, indicator, target)
    rows.append({"removed_month": f"(去掉最大{top_k}个月)", "rank_ic": round(r, 3),
                 "p_value": round(p, 4), "n": n})
    return pd.DataFrame(rows)


def main():
    import qlib
    from qlib.data import D
    # 直接复用 lowfreq 脚本的计算, 重新算月频指标+前向收益差
    import sys
    sys.path.insert(0, "scripts")
    from verify_style_switch_lowfreq_v1 import (
        load_market_data, compute_rsi_panel, compute_daily_metrics,
        compute_daily_fwd_diff, resample_to_freq,
    )

    qlib.init(provider_uri="~/.qlib/qlib_data/cn_data_2026", region="cn")
    print("[1/4] 加载 2017-2026 全市场数据 ...")
    raw = load_market_data("2017-10-01", "2026-08-20")
    with_rsi = compute_rsi_panel(raw)
    with_rsi = with_rsi[with_rsi["datetime"] >= pd.Timestamp("2018-01-01")]
    daily = compute_daily_metrics(with_rsi)
    daily_fwd = compute_daily_fwd_diff(raw, horizons=(20, 40, 60))
    monthly = resample_to_freq(daily, "M", "last")
    monthly_fwd = resample_to_freq(daily_fwd, "M", "last")
    m = monthly.join(monthly_fwd[[c for c in monthly_fwd.columns if c.startswith("diff_")]], how="inner")
    print(f"      月数={len(m)}")

    print("\n[2/4] 时间切分OOS (train 2018-2022 / test 2023-2026) ...")
    oos, best = oos_time_split(m)
    print(oos.to_string(index=False))
    if best:
        print(f"\ntrain发现最优: {best[0]} vs {best[1]} IC={best[2]:.3f} p={best[3]:.4f}")

    print("\n[3/4] 滚动24个月IC (ratio vs diff_20) ...")
    ric = rolling_ic(m, "ratio", "diff_20", window=24)
    print(ric.to_string())
    print(f"\n滚动IC: 均值={ric['rank_ic'].mean():.3f} 正值占比={((ric['rank_ic']>0).mean()*100):.0f}%")
    print(f"显著(p<0.05)月份占比={((ric['p_value']<0.05).mean()*100):.0f}%")

    print("\n[4/4] 极端值影响 (ratio最大的5个月) ...")
    loo = leave_one_out_extremes(m, "ratio", "diff_20", top_k=5)
    print(loo.to_string(index=False))

    # 保存
    oos.to_csv(OUTPUT_DIR / "oos_time_split.csv", index=False)
    ric.to_csv(OUTPUT_DIR / "rolling_ic_24m.csv")
    loo.to_csv(OUTPUT_DIR / "leave_one_out_extremes.csv", index=False)
    print(f"\n输出到 {OUTPUT_DIR}/")


if __name__ == "__main__":
    main()
