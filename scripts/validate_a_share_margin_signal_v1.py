#!/usr/bin/env python3
"""融资融券信号有效性验证（建议2）

验证目标：融资融券信号是否有独立选股 alpha，重点看 2021 后是否独立于价量衰减。

数据来源：
- 融资融券明细：/tmp/margin_probe/ (2016~2026, tushare margin_detail)
- 行情数据：qlib cn_data_2026 (后复权)

候选信号（均规模无关，无需流通市值标准化）：
- rzjme_zs: 融资净买入额每日横截面z-score(消除规模效应)
- rzye_chg5d: 融资余额5日变化率(规模无关)
- rzye_zscore: 融资余额250日时序z-score(历史偏离,规模无关)

检验项：
- IC / ICIR (Spearman rank IC)
- 5分组多空收益
- 市值+行业中性化后重测
- 分时段稳定性 (2016-2020 / 2021-2026)
"""
import sys
import gzip
import warnings
from pathlib import Path

import numpy as np
import pandas as pd

warnings.filterwarnings("ignore")

# qlib 初始化
import qlib
from qlib.config import REG_CN
from qlib.data import D

PROBE_DIR = Path("/tmp/margin_probe")
HISTORY_DIR = PROBE_DIR / "history"
RECENT_FILES = sorted(PROBE_DIR.glob("20*.csv.gz"))  # 建议拉取的近6个月文件
HORIZONS = [1, 5, 10, 20]  # 前向收益持有期
ZSCORE_WINDOW = 250  # 250日z-score窗口


def init_qlib():
    qlib.init(provider_uri="~/.qlib/qlib_data/cn_data_2026", region=REG_CN)


def load_margin_data():
    """加载全部融资融券数据(历史+近期)，合并去重"""
    files = list(HISTORY_DIR.glob("*.csv.gz")) + RECENT_FILES
    parts = []
    for f in files:
        df = pd.read_csv(f, dtype={"ts_code": str, "trade_date": str})
        parts.append(df)
    df = pd.concat(parts, ignore_index=True)
    df = df.drop_duplicates(subset=["ts_code", "trade_date"]).sort_values(
        ["ts_code", "trade_date"]
    ).reset_index(drop=True)
    return df


def ts_to_qlib(code: str) -> str:
    """000001.SZ -> SZ000001"""
    num, exch = code.split(".")
    return f"{exch}{num}"


def build_signals(margin: pd.DataFrame) -> pd.DataFrame:
    """构造候选信号"""
    df = margin.copy()
    df["trade_date"] = df["trade_date"].astype(str)

    # 信号1: 融资净买入额 = 融资买入额 - 融资偿还额
    df["rzjme"] = df["rzmre"].fillna(0) - df["rzche"].fillna(0)
    # 每日横截面z-score(消除规模效应)
    df["rzjme_zs"] = df.groupby("trade_date")["rzjme"].transform(
        lambda x: (x - x.mean()) / x.std() if x.std() > 0 else 0
    )

    # 信号2: 融资余额5日变化率(规模无关)
    df["rzye_prev5"] = df.groupby("ts_code")["rzye"].shift(5)
    df["rzye_chg5d"] = df["rzye"] / df["rzye_prev5"] - 1

    # 信号3: 融资余额250日时序z-score(规模无关)
    roll = df.groupby("ts_code")["rzye"].rolling(
        ZSCORE_WINDOW, min_periods=120
    )
    mean = roll.mean().reset_index(level=0, drop=True)
    std = roll.std().reset_index(level=0, drop=True)
    df["rzye_zscore"] = (df["rzye"] - mean) / std

    return df


def fetch_forward_returns(
    calendar: list, codes: list, horizons: list
) -> pd.DataFrame:
    """用qlib行情取前向收益(open-to-open)"""
    start = calendar[0]
    max_end = calendar[-1] + pd.Timedelta(days=max(horizons) + 10)
    # 取open价
    df = D.features(
        codes, ["$open"], start_time=start, end_time=max_end, freq="day"
    )
    df = df.reset_index()
    df = df.rename(columns={"$open": "open", "instrument": "code"})
    df["datetime"] = pd.to_datetime(df["datetime"])
    df = df.sort_values(["code", "datetime"]).reset_index(drop=True)

    # 为每个交易日算 horizon 日前向收益
    result_parts = []
    pivot = df.pivot(index="datetime", columns="code", values="open")
    for h in horizons:
        fwd = pivot.shift(-h) / pivot - 1
        fwd = fwd.stack().reset_index()
        fwd.columns = ["datetime", "code", f"ret_{h}"]
        result_parts.append(fwd)
    result = result_parts[0]
    for p in result_parts[1:]:
        result = result.merge(p, on=["datetime", "code"])
    return result


def compute_ic(panel: pd.DataFrame, signal_col: str, horizons: list):
    """计算IC/ICIR"""
    rows = []
    for h in horizons:
        ret_col = f"ret_{h}"
        valid = panel.dropna(subset=[signal_col, ret_col])
        if len(valid) < 30:
            continue
        # 每日rank IC
        daily_ic = valid.groupby("datetime").apply(
            lambda g: g[signal_col].corr(g[ret_col], method="spearman")
            if len(g) >= 10 else np.nan
        ).dropna()
        if len(daily_ic) < 10:
            continue
        rows.append({
            "signal": signal_col,
            "horizon": h,
            "n_days": len(daily_ic),
            "mean_ic": daily_ic.mean(),
            "ic_std": daily_ic.std(),
            "icir": daily_ic.mean() / daily_ic.std() * np.sqrt(252)
                    if daily_ic.std() > 0 else 0,
            "ic_pos_ratio": (daily_ic > 0).mean(),
        })
    return pd.DataFrame(rows)


def compute_quantile_returns(panel: pd.DataFrame, signal_col: str, horizon: int):
    """5分组多空收益"""
    ret_col = f"ret_{horizon}"
    valid = panel.dropna(subset=[signal_col, ret_col])
    if len(valid) < 100:
        return None
    # 每日分组
    def assign_group(g):
        if len(g) < 10:
            return g
        g = g.copy()
        g["group"] = pd.qcut(
            g[signal_col].rank(method="first"), 5, labels=False
        ) + 1
        return g
    grouped = valid.groupby("datetime", group_keys=False).apply(assign_group)
    grouped = grouped.dropna(subset=["group"])
    if len(grouped) < 50:
        return None
    daily_group_ret = grouped.groupby(["datetime", "group"])[ret_col].mean().unstack("group")
    long_short = daily_group_ret[5] - daily_group_ret[1]
    return {
        "daily_group_mean": daily_group_ret.mean(),
        "long_short_daily": long_short,
        "long_short_annual": long_short.mean() * 252,
        "long_short_sharpe": long_short.mean() / long_short.std() * np.sqrt(252)
                             if long_short.std() > 0 else 0,
    }


def neutralize(panel: pd.DataFrame, signal_col: str) -> pd.Series:
    """市值+行业中性化(残差化)"""
    # 需要市值和行业字段
    if "circ_mv" not in panel.columns or "l1_code" not in panel.columns:
        return panel[signal_col]
    valid = panel.dropna(subset=[signal_col, "circ_mv", "l1_code"]).copy()
    # log市值
    valid["log_mv"] = np.log(valid["circ_mv"].clip(lower=1))
    # 行业dummy
    dummies = pd.get_dummies(valid["l1_code"], prefix="ind", drop_first=True)
    X = pd.concat([valid[["log_mv"]], dummies], axis=1).astype(float)
    X = X.fillna(0)
    y = valid[signal_col].astype(float)
    # OLS残差
    beta = np.linalg.lstsq(X.values, y.values, rcond=None)[0]
    resid = y - X.values @ beta
    return pd.Series(resid, index=valid.index, name=f"{signal_col}_neut")


def main():
    init_qlib()
    print("=== 加载融资融券数据 ===", flush=True)
    margin = load_margin_data()
    print(f"  记录: {len(margin):,}, 日期: {margin.trade_date.min()}~{margin.trade_date.max()}", flush=True)
    print(f"  股票数: {margin.ts_code.nunique()}", flush=True)

    print("\n=== 构造信号 ===", flush=True)
    sig = build_signals(margin)
    print(f"  rzjme_zs 非空: {sig.rzjme_zs.notna().sum():,}", flush=True)
    print(f"  rzye_chg5d 非空: {sig.rzye_chg5d.notna().sum():,}", flush=True)
    print(f"  rzye_zscore 非空: {sig.rzye_zscore.notna().sum():,}", flush=True)

    print("\n=== 准备qlib行情取前向收益 ===", flush=True)
    # 转换代码格式
    sig["qlib_code"] = sig["ts_code"].map(ts_to_qlib)
    codes = sorted(sig["qlib_code"].unique())
    print(f"  需要行情的股票数: {len(codes)}", flush=True)

    # qlib交易日历
    cal = D.calendar(start_time="2016-01-01", end_time="2026-08-07")
    print(f"  交易日历: {len(cal)} 天", flush=True)

    print("\n=== 拉取前向收益 ===", flush=True)
    returns = fetch_forward_returns(list(cal), codes, HORIZONS)
    print(f"  收益记录: {len(returns):,}", flush=True)

    # 合并信号和收益
    sig["datetime"] = pd.to_datetime(sig["trade_date"], format="%Y%m%d")
    returns["datetime"] = pd.to_datetime(returns["datetime"])
    panel = sig.merge(
        returns, left_on=["datetime", "qlib_code"], right_on=["datetime", "code"], how="inner"
    )
    print(f"  合并后记录: {len(panel):,}", flush=True)

    # 信号列表
    signals = ["rzjme_zs", "rzye_chg5d", "rzye_zscore"]
    # 对每个信号做横截面排名(每日)
    for s in signals:
        panel[f"{s}_rank"] = panel.groupby("datetime")[s].rank(pct=True)

    # ===== IC 检验 =====
    print("\n" + "=" * 70, flush=True)
    print("IC / ICIR 检验", flush=True)
    print("=" * 70, flush=True)
    ic_results = []
    for s in signals:
        r = compute_ic(panel, f"{s}_rank", HORIZONS)
        r["signal"] = s
        ic_results.append(r)
    ic_df = pd.concat(ic_results, ignore_index=True)
    print(ic_df.to_string(index=False), flush=True)

    # ===== 分时段IC =====
    print("\n" + "=" * 70, flush=True)
    print("分时段IC (重点看2021后)", flush=True)
    print("=" * 70, flush=True)
    panel["period"] = pd.cut(
        panel["datetime"],
        bins=[pd.Timestamp("2016-01-01"), pd.Timestamp("2021-01-01"),
              pd.Timestamp("2026-08-07")],
        labels=["2016-2020", "2021-2026"],
    )
    for period in ["2016-2020", "2021-2026"]:
        sub = panel[panel["period"] == period]
        print(f"\n--- {period} (样本: {len(sub):,}) ---", flush=True)
        for s in signals:
            r = compute_ic(sub, f"{s}_rank", [5, 20])
            if len(r) > 0:
                r["signal"] = s
                print(r[["signal", "horizon", "mean_ic", "icir", "ic_pos_ratio"]].to_string(index=False), flush=True)

    # ===== 5分组多空收益 =====
    print("\n" + "=" * 70, flush=True)
    print("5分组多空收益 (horizon=20)", flush=True)
    print("=" * 70, flush=True)
    for s in signals:
        res = compute_quantile_returns(panel, f"{s}_rank", 20)
        if res:
            print(f"\n--- {s} ---", flush=True)
            print("  各组日均收益:", flush=True)
            print(res["daily_group_mean"].to_string(), flush=True)
            print(f"  多空年化: {res['long_short_annual']:.4f}", flush=True)
            print(f"  多空Sharpe: {res['long_short_sharpe']:.2f}", flush=True)

    # ===== 市值+行业中性化IC (csi1000口径, 2023-2026) =====
    print("\n" + "=" * 70, flush=True)
    print("市值+行业中性化IC (csi1000口径, 2023-2026)", flush=True)
    print("=" * 70, flush=True)
    # 加载中性化数据(两段合并)
    db1 = pd.read_csv(
        "data/external/tushare/csi1000_neutralization_2023-01-01_2024-12-31/daily_basic_csi1000.csv.gz",
        dtype={"ts_code": str, "trade_date": str},
        usecols=["ts_code", "trade_date", "circ_mv"],
    )
    db2 = pd.read_csv(
        "data/external/tushare/csi1000_neutralization_2025-01-01_2026-07-23/daily_basic_csi1000.csv.gz",
        dtype={"ts_code": str, "trade_date": str},
        usecols=["ts_code", "trade_date", "circ_mv"],
    )
    db = pd.concat([db1, db2], ignore_index=True).drop_duplicates(
        subset=["ts_code", "trade_date"]
    )
    # 行业归属(带历史区间)
    ind = pd.read_csv(
        "data/external/tushare/csi1000_neutralization_2023-01-01_2024-12-31/industry_member_history_csi1000.csv.gz",
        dtype={"ts_code": str},
    )
    # 展开行业为每日面板
    ind_rows = []
    for _, r in ind.iterrows():
        in_d = str(int(r["in_date"])) if pd.notna(r["in_date"]) else "19900101"
        out_d = str(int(r["out_date"])) if pd.notna(r["out_date"]) else "99991231"
        ind_rows.append({"ts_code": r["ts_code"], "l1_code": r["l1_code"],
                         "in_date": in_d, "out_date": out_d})
    ind_df = pd.DataFrame(ind_rows)

    # 合并市值
    db["datetime"] = pd.to_datetime(db["trade_date"], format="%Y%m%d")
    panel = panel.merge(db[["ts_code", "datetime", "circ_mv"]], on=["ts_code", "datetime"], how="left")
    # 合并行业(按日期匹配区间)
    panel["td8"] = panel["trade_date"]
    panel = panel.merge(ind_df[["ts_code", "l1_code", "in_date", "out_date"]], on="ts_code", how="left")
    panel = panel[(panel["td8"] >= panel["in_date"]) & (panel["td8"] <= panel["out_date"])].copy()

    neut_sub = panel[panel["circ_mv"].notna()].copy()
    print(f"  中性化样本(有市值+行业): {len(neut_sub):,}", flush=True)
    if len(neut_sub) > 1000:
        for s in signals:
            resid = neutralize(neut_sub, f"{s}_rank")
            neut_sub = neut_sub.assign(**{f"{s}_neut_rank": resid})
            # 中性化后IC
            for h in [5, 20]:
                ret_col = f"ret_{h}"
                valid = neut_sub.dropna(subset=[f"{s}_neut_rank", ret_col])
                if len(valid) < 500:
                    continue
                daily_ic = valid.groupby("datetime").apply(
                    lambda g: g[f"{s}_neut_rank"].corr(g[ret_col], method="spearman")
                    if len(g) >= 10 else np.nan
                ).dropna()
                if len(daily_ic) > 10:
                    print(f"  {s} h={h}: neut_ic={daily_ic.mean():.4f} "
                          f"neut_icir={daily_ic.mean()/daily_ic.std()*np.sqrt(252):.2f} "
                          f"pos_ratio={((daily_ic>0).mean()):.2f}", flush=True)
    else:
        print("  中性化样本不足，跳过", flush=True)

    # ===== 保存结果 =====
    out_dir = Path("/tmp/margin_probe/results")
    out_dir.mkdir(exist_ok=True)
    ic_df.to_csv(out_dir / "ic_results.csv", index=False)
    panel[["datetime", "ts_code", "qlib_code", "rzjme", "rzjme_zs",
           "rzye_chg5d", "rzye_zscore",
           "rzjme_zs_rank", "rzye_chg5d_rank", "rzye_zscore_rank",
           "ret_1", "ret_5", "ret_10", "ret_20", "period"]].to_csv(
        out_dir / "panel_sample.csv.gz", compression="gzip", index=False
    )
    print(f"\n结果已保存到 {out_dir}", flush=True)


if __name__ == "__main__":
    main()
