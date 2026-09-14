#!/usr/bin/env python
"""风格中性化 —— 量化"牺牲多少超额换取市场中性"。

协议: research/protocols/a_share_style_neutralization_protocol_v1.md

V0 基线(行业+市值) / V1 +beta / V2 +动量 / V3 +波动 / V4 全价格风格 / V5 V4+价值
每个变体重做 OLS 中性化 -> 毒尾否决 -> 价格过滤 -> top30 cap3 -> 回测。
报告: 净超额 / IR / corr(超额,市场) / 上下行捕获 / 风格暴露残留 / 上实盘口径。
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
from qlib.contrib.evaluate import backtest_daily  # noqa: E402
from qlib.contrib.strategy import TopkDropoutStrategy  # noqa: E402

import backtest_a_share_value_growth_five_factor_industry_cap_v3 as v3  # noqa: E402
from backtest_a_share_value_growth_five_factor_industry_cap_v3 import (  # noqa: E402
    QLIB_DIR, BT_START, BT_END, BENCHMARK, COST_SCENARIOS, signal_from_snapshots,
    ols_residual, select_with_industry_cap,
)
from backtest_a_share_five_factor_daily_execution_v1 import (  # noqa: E402
    OUT, TOP_K, CAP, build_toxic_rank, apply_veto, _to_ts_code,
)
from analyze_a_share_price_feasibility_v1 import price_panel, apply_price_filter  # noqa: E402
from backtest_a_share_value_quality_monthly_dailygrid_v6 import DAILY_BASIC  # noqa: E402

CAPITAL = 500_000.0
ANN, W = 244, 244
FACTORS5 = ["ep", "bm", "div_yield", "accruals", "g2"]

VARIANTS = {
    "V0_baseline": [],
    "V1_plus_beta": ["beta_60"],
    "V2_plus_momentum": ["mom_12_1"],
    "V3_plus_vol": ["vol_60"],
    "V4_price_style_neutral": ["beta_60", "mom_12_1", "vol_60", "turn_20"],
    "V5_full_incl_value": ["beta_60", "mom_12_1", "vol_60", "turn_20", "value_ctrl"],
}


def log(m):
    print(m, flush=True)


def residualize(score: pd.Series, industry: pd.Series, X: np.ndarray) -> pd.Series:
    """与项目 ols_residual 完全同构: [1, X..., 行业哑变量(去首个)] 取残差。"""
    dummies = pd.get_dummies(industry, dtype=float)
    if dummies.shape[1] > 0:
        dummies = dummies.iloc[:, 1:]
    design = np.column_stack([np.ones(len(score)), X, dummies.to_numpy(dtype=float)])
    beta, *_ = np.linalg.lstsq(design, score.to_numpy(dtype=float), rcond=None)
    return pd.Series(score.to_numpy(dtype=float) - design @ beta, index=score.index)


def build_style_panel(dates: pd.DatetimeIndex) -> dict:
    """构造风格控制变量面板 (每个 snapshot 日期一个 DataFrame)。

    价格从 2015-01 起载入(store 起点), 让 mom_12_1(需 252 日) 与 beta_60/vol_60
    在 2016-01 即有值 —— 否则 2016 年快照会因 mom 全 NaN 被整年剔除,
    造成各变体样本期不一致, 无法公平对比。
    """
    from qlib.data import D
    df = D.features(D.instruments(market="all"), ["$close", "$volume"],
                    start_time="2015-01-01", end_time=str(BT_END.date()), freq="day")
    df.columns = ["close", "volume"]
    df = df[~df.index.duplicated()]
    C = df["close"].unstack(0).sort_index().astype("float32")
    C.columns = [_to_ts_code(c) for c in C.columns]
    C = C.where(C > 0)
    ret = C / C.shift(1) - 1.0
    mkt = ret.mean(axis=1, skipna=True)          # 等权全池做市场代理

    # 滚动 beta: cov(r, m)/var(m), 60 日
    mkt_df = pd.DataFrame(np.repeat(mkt.values[:, None], 1, axis=1), index=ret.index)
    cov = ret.rolling(60, min_periods=30).cov(mkt)
    var = mkt.rolling(60, min_periods=30).var()
    beta = cov.div(var, axis=0)

    mom = C.shift(21) / C.shift(252) - 1.0
    vol = ret.rolling(60, min_periods=30).std()

    db = pd.read_csv(DAILY_BASIC, compression="gzip",
                     usecols=["trade_date", "ts_code", "turnover_rate"])
    db["datetime"] = pd.to_datetime(db["trade_date"].astype(str), format="%Y%m%d")
    to = db.pivot_table(index="datetime", columns="ts_code", values="turnover_rate", aggfunc="sum")
    turn = to.rolling(20, min_periods=10).mean()

    panels = {k: v.reindex(dates) for k, v in
              (("beta_60", beta), ("mom_12_1", mom), ("vol_60", vol), ("turn_20", turn))}
    log(f"      style panels: { {k: v.shape for k, v in panels.items()} }")
    return panels


def neutralize(snaps: dict, extra_cols: list, style: dict) -> dict:
    """把 extra_cols 加入 OLS 解释变量, 重算 neutral_composite。"""
    out = {}
    for date, f in snaps.items():
        g = f.copy()
        for c in ("beta_60", "mom_12_1", "vol_60", "turn_20"):
            if c in style and date in style[c].index:
                g[c] = style[c].loc[date].reindex(g["ts_code"]).to_numpy(dtype=float)
            elif c not in g.columns:
                g[c] = np.nan
        if "value_ctrl" in extra_cols:
            vr = pd.concat([g["ep"].rank(pct=True), g["bm"].rank(pct=True)], axis=1).mean(axis=1)
            g["value_ctrl"] = vr
        regs = ["log_size"] + extra_cols
        valid = g.dropna(subset=["composite5"] + regs + ["l1_code"])
        if len(valid) < 50:
            g["neutral_composite"] = np.nan
        else:
            g["neutral_composite"] = residualize(
                valid["composite5"], valid["l1_code"],
                valid[regs].to_numpy(dtype=float)).reindex(g.index)
        out[date] = g
    return out


def run_arm(snaps: dict, calendar, P, toxic, tag: str):
    s = apply_veto(snaps, toxic, TOP_K, CAP)
    s, _ = apply_price_filter(s, P, TOP_K, CAPITAL, shift=0)
    sig = signal_from_snapshots(s, calendar, TOP_K, CAP)
    strat = TopkDropoutStrategy(signal=sig, topk=TOP_K, n_drop=TOP_K)
    rep, _ = backtest_daily(
        start_time=BT_START, end_time=BT_END, strategy=strat, account=CAPITAL,
        benchmark=BENCHMARK,
        exchange_kwargs={"limit_threshold": 0.095, "deal_price": "open",
                         "open_cost": COST_SCENARIOS["stress"]["open_cost"],
                         "close_cost": COST_SCENARIOS["stress"]["close_cost"],
                         "min_cost": 5})
    ex = (rep["return"] - rep["bench"] - rep["cost"]).rename(tag)
    # 风格暴露残留
    expo = {}
    for date, f in s.items():
        sel = select_with_industry_cap(f, TOP_K, CAP)
        if sel.empty or date not in P.index:
            continue
        for c in ("beta_60", "mom_12_1", "vol_60", "turn_20"):
            if c in f.columns:
                r = f[c].rank(pct=True)
                expo.setdefault(c, []).append(float(r.reindex(sel.index).mean()))
    return ex, rep, {k: float(np.mean(v)) for k, v in expo.items()}


def main() -> int:
    qlib.init(provider_uri=str(QLIB_DIR), region=REG_CN)
    v3.ACCOUNT = int(CAPITAL)
    calendar = pd.DatetimeIndex(pd.to_datetime(
        pd.read_csv(QLIB_DIR / "calendars" / "day.txt", header=None)[0]))

    snap = pd.read_pickle(OUT / "snapshots_500k_10day.pkl")
    dates = pd.DatetimeIndex(sorted(snap.keys()))
    P = price_panel()
    toxic = build_toxic_rank(calendar)
    log(f"snapshots {len(snap)} ; dates {dates[0].date()}..{dates[-1].date()}")

    log("[1/3] building style panels ...")
    style = build_style_panel(dates)

    log("[2/3] running variants ...")
    series, summ, expo_all = {}, [], {}
    for tag, extra in VARIANTS.items():
        snaps = neutralize(snap, extra, style)
        ex, rep, expo = run_arm(snaps, calendar, P, toxic, tag)
        series[tag] = ex
        expo_all[tag] = expo
        m = rep.resample("ME").apply(lambda x: pd.Series({
            "net": (1 + x["return"] - x["cost"]).prod() - 1,
            "bench": (1 + x["bench"]).prod() - 1}) if len(x) else pd.Series(
            {"net": np.nan, "bench": np.nan})).dropna()
        mu, md = m[m["bench"] > 0], m[m["bench"] < 0]
        n = len(ex)
        row = {"variant": tag,
               "full": float((1 + ex).prod() ** (ANN / n) - 1),
               "IR": float(ex.mean() / ex.std() * np.sqrt(ANN)),
               "corr_excess_market": float(np.corrcoef(ex, rep["bench"])[0, 1]),
               "up_capture": float(mu["net"].mean() / mu["bench"].mean()),
               "down_capture": float(md["net"].mean() / md["bench"].mean())}
        for seg, (a, b) in (("y2020", ("2020-01-01", "2026-06-30")),
                            ("holdout", ("2023-01-01", "2025-06-30")),
                            ("new_cov", ("2025-07-01", "2026-06-30"))):
            seg_ex = ex.loc[a:b]
            row[seg] = float((1 + seg_ex).prod() ** (ANN / len(seg_ex)) - 1) if len(seg_ex) > 20 else np.nan
        summ.append(row)
        log(f"  {tag:<24} full={row['full']:+.4f} IR={row['IR']:+.3f} "
            f"corr={row['corr_excess_market']:+.3f} up/dn={row['up_capture']:.2f}/{row['down_capture']:.2f}")

    df = pd.DataFrame(summ).set_index("variant")
    df.to_csv(OUT / "style_neutralization_summary.csv")
    pd.DataFrame(series).to_csv(OUT / "style_neutralization_daily.csv")

    log("\n=== 代价表 (相对 V0) ===")
    log(f"{'变体':<24}{'全期':>9}{'2020起':>9}{'holdout':>9}{'最近1年':>9}"
        f"{'IR':>7}{'corr':>7}{'上/下行捕获':>13}{'代价':>9}")
    base = df.loc["V0_baseline"]
    for tag, r in df.iterrows():
        cost = base["full"] - r["full"]
        log(f"{tag:<24}{r['full']:>+9.4f}{r['y2020']:>+9.4f}{r['holdout']:>+9.4f}"
            f"{r['new_cov']:>+9.4f}{r['IR']:>7.3f}{r['corr_excess_market']:>+7.3f}"
            f"{r['up_capture']:>7.2f}/{r['down_capture']:<5.2f}{cost:>+9.4f}")

    neutral_ok = df[(df["corr_excess_market"].abs() < 0.10)
                    & ((df["up_capture"] - df["down_capture"]).abs() < 0.20)]
    log(f"\n>>> 达成'市场中中性'判据(|corr|<0.10 且 上下行捕获差<0.20)的变体: "
        f"{list(neutral_ok.index) if len(neutral_ok) else '无'}")

    (OUT / "style_neutralization.json").write_text(json.dumps({
        "cost_table": {t: float(base["full"] - r["full"]) for t, r in df.iterrows()},
        "neutral_achieved": list(neutral_ok.index),
        "detail": df.reset_index().to_dict(orient="records"),
        "style_exposure_residual": expo_all,
    }, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
