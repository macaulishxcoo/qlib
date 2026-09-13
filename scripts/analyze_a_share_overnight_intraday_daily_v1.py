#!/usr/bin/env python
"""隔夜/日内收益分解 —— 日频因子线 v1。

协议: research/protocols/a_share_overnight_intraday_daily_protocol_v1.md
状态: design_frozen_before_data

设计要点（与协议一致，不在此处调参）:
  * 池     : 沪深主板 —— SH 60x + SZ 000/001/002/003；排除创业板 300/301、
             科创板 688/689、北交所、B 股、指数
  * 分量   : on_1 = open(t)/close(t-1)-1   id_1 = close(t)/open(t)-1
  * 标签   : label_h(t) = open(t+1+h)/open(t+1)-1, h in {1,5,10}
             等价于 open_ret 的 h 日复利, open_ret(t) = open(t+1)/open(t)-1
  * 执行   : t 收盘出信号 -> t+1 开盘成交；t+1 开盘涨停/停牌/低价 不可买
  * 组合   : 每 5 交易日决策一次, 多头 10%, 缓冲带 20%, 等权
  * 成本   : base 买 0.05% / 卖 0.15%;  stress 买 0.10% / 卖 0.30%
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

# 注意: 不要把 REPO 插入 sys.path —— 本地 qlib/ 源码树未编译,
# 会遮蔽 site-packages 中已安装的 pyqlib (setuptools_scm 缺失)。
REPO = Path(__file__).resolve().parents[1]

OUT = REPO / "output" / "analysis_static" / "a_share_overnight_intraday_daily_v1"
OUT.mkdir(parents=True, exist_ok=True)

STORE = Path.home() / ".qlib" / "qlib_data" / "cn_data_2026"

# ---------------- 冻结参数 ----------------
LOAD_START = "2016-01-01"      # 20 日窗口预热
EVAL_START = "2018-01-01"
EVAL_END = "2026-06-30"
HORIZONS = (1, 5, 10)
REBAL_STEP = 5                 # 每 5 交易日决策
TOP_FRAC = 0.10                # 多头 10%
BUFFER_FRAC = 0.20             # 跌出前 20% 才卖
MIN_NAMES = 100                # 截面最少有效标的
MIN_PRICE = 2.0
LIMIT_GAP = 0.095              # 开盘相对前收涨幅上限（不可买）
COSTS = {"base": (0.0005, 0.0015), "stress": (0.0010, 0.0030)}
ANN = 244.0

FACTORS = [
    "on_mom_5", "on_mom_10", "on_mom_20",
    "id_mom_5", "id_mom_10", "id_mom_20",
    "on_id_spread_5", "on_id_spread_10", "on_id_spread_20",
    "on_share_5", "on_share_10", "on_share_20",
    "on_vol_20", "id_vol_20", "on_id_vol_ratio_20",
]


def log(msg: str) -> None:
    print(msg, flush=True)


# ---------------- 1. 取数 ----------------
def load_panel() -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    import qlib
    from qlib.config import REG_CN
    from qlib.data import D

    qlib.init(provider_uri=str(STORE), region=REG_CN)

    instr = D.instruments(market="all")
    df = D.features(instr, ["$open", "$close", "$volume"],
                    start_time=LOAD_START, end_time=EVAL_END, freq="day")
    df.columns = ["open", "close", "volume"]
    df = df[~df.index.duplicated()]
    log(f"raw panel rows={len(df):,} insts={df.index.get_level_values(0).nunique():,}")

    codes = df.index.get_level_values(0)
    # 沪深主板严格口径: SH 60x (沪主板) + SZ 000/001/002/003 (深主板含原中小板)
    # 该规则同时排除 创业板 30x、科创板 688/689、北交所、B 股 (SH900/SZ200)、
    # 以及 SH000xxx / SZ399xxx 指数
    keep = codes.str.startswith("SH6") | codes.str.startswith("SZ00")
    df = df[keep]
    log(f"main-board panel rows={len(df):,} insts={df.index.get_level_values(0).nunique():,}")

    O = df["open"].unstack(0).sort_index()
    C = df["close"].unstack(0).sort_index()
    V = df["volume"].unstack(0).sort_index()
    O = O.where(O > 0)
    C = C.where(C > 0)
    return O.astype("float32"), C.astype("float32"), V.astype("float32")


# ---------------- 2. 因子 ----------------
def build_factors(O: pd.DataFrame, C: pd.DataFrame) -> dict[str, pd.DataFrame]:
    on1 = O / C.shift(1) - 1.0
    id1 = C / O - 1.0
    eps = 1e-8
    f: dict[str, pd.DataFrame] = {}
    for n in (5, 10, 20):
        on = on1.rolling(n, min_periods=max(3, n // 2)).sum()
        idr = id1.rolling(n, min_periods=max(3, n // 2)).sum()
        f[f"on_mom_{n}"] = on
        f[f"id_mom_{n}"] = idr
        f[f"on_id_spread_{n}"] = on - idr
        f[f"on_share_{n}"] = on / (on.abs() + idr.abs() + eps)
    f["on_vol_20"] = on1.rolling(20, min_periods=10).std()
    f["id_vol_20"] = id1.rolling(20, min_periods=10).std()
    f["on_id_vol_ratio_20"] = f["on_vol_20"] / (f["id_vol_20"] + eps)
    return f


# ---------------- 3. IC ----------------
def ic_table(F: dict[str, pd.DataFrame], fwd: dict[int, pd.DataFrame],
             eval_dates: pd.DatetimeIndex) -> pd.DataFrame:
    rows = []
    for name, fac in F.items():
        sub = fac.reindex(eval_dates)
        rk = sub.rank(axis=1)
        for h, lab in fwd.items():
            lk = lab.reindex(eval_dates).rank(axis=1)
            both = rk.notna() & lk.notna()
            n = both.sum(axis=1)
            rr = rk.where(both)
            ll = lk.where(both)
            rr = rr.sub(rr.mean(axis=1), axis=0)
            ll = ll.sub(ll.mean(axis=1), axis=0)
            num = (rr * ll).sum(axis=1)
            den = np.sqrt((rr ** 2).sum(axis=1) * (ll ** 2).sum(axis=1))
            ic = (num / den).where(n >= MIN_NAMES)
            rows.append(pd.DataFrame({"factor": name, "h": h, "ic": ic}).dropna(subset=["ic"]))
    return pd.concat(rows, ignore_index=True)


# ---------------- 4. 组合 ----------------
def simulate(fac: pd.DataFrame, open_ret: pd.DataFrame, bench: pd.Series,
             dates: pd.DatetimeIndex, direction: int,
             buy_rate: float, sell_rate: float,
             buy_ok: pd.DataFrame, sell_ok: pd.DataFrame) -> dict:
    """每 REBAL_STEP 日决策, 多头 TOP_FRAC, 缓冲带 BUFFER_FRAC, 等权。

    成交约束: 决策 i -> 在 open(i+1) 成交; 涨停开盘不建仓, 跌停开盘不卖出
    (无法卖出的持仓被强制保留到下一期)。
    """
    sign = fac.reindex(dates).mul(direction)
    trade = open_ret.reindex(dates)                 # open_ret(t): open(t)->open(t+1)
    b_ok = buy_ok.reindex(dates)
    s_ok = sell_ok.reindex(dates)
    n_dates = len(dates)

    # 可交易掩码: 决策 i -> 成交于 open(i+1)
    held: list = []
    gross = np.full(n_dates, np.nan)
    cost_ser = np.zeros(n_dates)
    turn_ser = np.zeros(n_dates)
    w_prev: pd.Series | None = None

    rebal_idx = list(range(0, n_dates - 1, REBAL_STEP))
    for k, i in enumerate(rebal_idx):
        j = i + 1                                    # 成交日
        if j >= n_dates:
            break
        s = sign.iloc[i].dropna()
        bj = b_ok.iloc[j]
        s = s[s.index.isin(bj[bj].index)]        # 只保留 open(j) 买得进的
        if len(s) < MIN_NAMES:
            continue
        n_pick = max(1, int(len(s) * TOP_FRAC))
        n_keep = max(1, int(len(s) * BUFFER_FRAC))
        ranked = s.sort_values(ascending=False)
        keep_band = set(ranked.index[:n_keep])
        # 缓冲带: 保留仍在 band 内的旧持仓, 再补入新的 top 名单 (dedup 去重)
        new_held = [c for c in held if c in keep_band]
        new_held += list(ranked.index[:n_pick])
        # 跌停开盘无法卖出 -> 强制保留 (仅针对已在持仓中的标的)
        sj = s_ok.iloc[j].fillna(False)
        unsellable = set(sj.index[~sj])
        new_held += [c for c in held if c in unsellable]
        new_held = list(dict.fromkeys(new_held))
        if not new_held:
            continue
        w_new = pd.Series(1.0 / len(new_held), index=new_held)
        if w_prev is None:
            buys = 1.0
            sells = 0.0
            turn = 1.0
        else:
            allc = w_new.index.union(w_prev.index)
            a = w_new.reindex(allc).fillna(0.0)
            b = w_prev.reindex(allc).fillna(0.0)
            d = a - b
            buys, sells = float(d[d > 0].sum()), float(-d[d < 0].sum())
            turn = (buys + sells) / 2.0
        cost_ser[j] = buys * buy_rate + sells * sell_rate
        turn_ser[j] = turn
        # 持有区间 [j, j+REBAL_STEP)
        end = min(j + REBAL_STEP, n_dates)
        for d in range(j, end):
            r = trade.iloc[d].reindex(new_held)
            if r.notna().sum() > 0:
                gross[d] = float(r.mean(skipna=True))
        held = new_held
        w_prev = w_new

    gross_s = pd.Series(gross, index=dates)
    port = gross_s - pd.Series(cost_ser, index=dates)
    port = port.where(gross_s.notna())
    bm = bench.reindex(dates)
    excess = (port - bm).dropna()
    if len(excess) < 250:
        return {"ok": False}
    sd = float(excess.std())
    ann_ex = float(excess.mean()) * ANN
    ir = ann_ex / (sd * np.sqrt(ANN)) if sd > 0 else float("nan")
    cum = (1 + excess).cumprod()
    mdd = float((cum / cum.cummax() - 1).min())
    yrs = len(excess) / ANN
    return {
        "ok": True,
        "ann_excess": ann_ex,
        "ann_vol": sd * np.sqrt(ANN),
        "ir": ir,
        "mdd": mdd,
        "ann_turnover": float(turn_ser.sum()) / yrs,
        "t_stat": float(excess.mean() / (sd / np.sqrt(len(excess)))) if sd > 0 else float("nan"),
        "n_days": int(len(excess)),
        "win_rate_12m": _rolling_win(excess),
        "excess_series": excess,
    }


def tradeability(O: pd.DataFrame, C: pd.DataFrame, V: pd.DataFrame):
    """返回 (buy_ok, sell_ok): 在 **open(t)** 能否建仓 / 平仓。

    open(t) 的涨跌幅以 close(t-1) 为基准：
      gap(t) = open(t)/close(t-1) - 1
    涨停开盘 (gap >= +9.5%) 买不进；跌停开盘 (gap <= -9.5%) 卖不出。
    另要求当日有成交量且价格 >= MIN_PRICE。
    """
    pc = C.shift(1)
    gap = O / pc - 1.0
    live = O.notna() & (V > 0) & (O >= MIN_PRICE)
    return live & (gap < LIMIT_GAP), live & (gap > -LIMIT_GAP)


def _rolling_win(excess: pd.Series) -> float:
    c = (1 + excess).cumprod()
    wins, tot = 0, 0
    for start in pd.date_range(excess.index[0], excess.index[-1], freq="YE"):
        seg = c[c.index <= start]
        if len(seg) < 250:
            continue
        yr = seg.iloc[-1] / seg.iloc[-min(len(seg), 245)] - 1
        wins += int(yr > 0)
        tot += 1
    return float(wins / tot) if tot else float("nan")


# ---------------- main ----------------
def main() -> int:
    log("-> loading panel")
    O, C, V = load_panel()

    log("-> building factors")
    F = build_factors(O, C)

    open_ret = (O.shift(-1) / O) - 1.0            # open(t) -> open(t+1)
    bench = open_ret.mean(axis=1, skipna=True)
    buy_ok, sell_ok = tradeability(O, C, V)
    log(f"-> tradeability: buy_ok mean={buy_ok.to_numpy().mean():.3f} "
        f"sell_ok mean={sell_ok.to_numpy().mean():.3f}")

    fwd = {}
    for h in HORIZONS:
        fwd[h] = (O.shift(-(1 + h)) / O.shift(-1)) - 1.0

    all_dates = O.index
    eval_dates = all_dates[(all_dates >= EVAL_START) & (all_dates <= EVAL_END)]
    log(f"-> eval dates {eval_dates[0].date()} .. {eval_dates[-1].date()} ({len(eval_dates)})")

    log("-> IC")
    ic = ic_table(F, fwd, eval_dates)
    ic.to_csv(OUT / "ic_by_date.csv.gz", index=False, compression="gzip")
    summ = (ic.groupby(["factor", "h"])["ic"]
              .agg(ic_mean="mean", ic_std="std", n="count").reset_index())
    summ["icir"] = summ["ic_mean"] / summ["ic_std"] * np.sqrt(ANN)
    summ["t_stat"] = summ["ic_mean"] / summ["ic_std"] * np.sqrt(summ["n"])
    summ = summ.sort_values(["h", "ic_mean"], key=lambda s: s.abs() if s.name == "ic_mean" else s)
    summ.to_csv(OUT / "ic_summary.csv", index=False)
    log("\n=== IC (top by |mean|) ===")
    for h in HORIZONS:
        sub = summ[summ["h"] == h].reindex(
            summ[summ["h"] == h]["ic_mean"].abs().sort_values(ascending=False).index)
        log(f"-- h={h}")
        for _, r in sub.head(6).iterrows():
            log(f"   {r['factor']:<22} IC={r['ic_mean']:+.4f} ICIR={r['icir']:+.2f} t={r['t_stat']:+.1f}")

    log("\n=== portfolio (long-only, 5d hold, 20% buffer) ===")
    prows = []
    keep_series: dict[str, pd.Series] = {}
    for name, fac in F.items():
        for direction, dlabel in ((1, "pos"), (-1, "neg")):
            for cname, (br, sr) in COSTS.items():
                res = simulate(fac, open_ret, bench, eval_dates, direction, br, sr,
                               buy_ok, sell_ok)
                if not res.get("ok"):
                    continue
                ser = res.pop("excess_series")
                keep_series[f"{name}|{dlabel}|{cname}"] = ser
                prows.append({"factor": name, "dir": dlabel, "cost": cname, **res})
    pf = pd.DataFrame(prows)
    pf.to_csv(OUT / "portfolio_summary.csv", index=False)

    base = pf[pf["cost"] == "base"].copy()
    for _, r in base.sort_values("ann_excess", ascending=False).head(12).iterrows():
        st = pf[(pf["factor"] == r["factor"]) & (pf["dir"] == r["dir"]) & (pf["cost"] == "stress")]
        s = st.iloc[0] if len(st) else None
        extra = f" | stress net={s['ann_excess']:+.3f} IR={s['ir']:+.2f}" if s is not None else ""
        log(f"   {r['factor']:<22} {r['dir']} base net={r['ann_excess']:+.4f} "
            f"IR={r['ir']:+.2f} mdd={r['mdd']:+.3f} turn={r['ann_turnover']:.1f}{extra}")

    # ---------------- 判定 ----------------
    ic_ok = summ[(summ["h"] == 5) & (summ["ic_mean"].abs() >= 0.02) & (summ["icir"].abs() >= 0.30)]
    stress = pf[pf["cost"] == "stress"]
    passed = stress[(stress["ann_excess"] >= 0.0)]
    best = stress.sort_values("ann_excess", ascending=False).head(1)
    verdict = "supported" if (len(ic_ok) > 0 and len(passed) > 0) else "not_supported"

    decision = {
        "verdict": verdict,
        "criteria": {
            "A_ic": "h=5 |IC|>=0.02 and |ICIR|>=0.30",
            "B_portfolio": "stress cost net excess >= 0",
        },
        "ic_pass_factors": sorted(ic_ok["factor"].unique().tolist()),
        "stress_nonneg_count": int(len(passed)),
        "best_stress": None if best.empty else {
            "factor": str(best.iloc[0]["factor"]), "dir": str(best.iloc[0]["dir"]),
            "ann_excess": float(best.iloc[0]["ann_excess"]), "ir": float(best.iloc[0]["ir"]),
            "mdd": float(best.iloc[0]["mdd"]),
            "ann_turnover": float(best.iloc[0]["ann_turnover"]),
        },
        "n_eval_days": int(len(eval_dates)),
        "universe": "SH 60x + SZ 000/001/002/003",
    }
    (OUT / "decision.json").write_text(json.dumps(decision, indent=2, ensure_ascii=False))
    (OUT / "methodology.json").write_text(json.dumps({
        "protocol": "research/protocols/a_share_overnight_intraday_daily_protocol_v1.md",
        "load_start": LOAD_START, "eval_start": EVAL_START, "eval_end": EVAL_END,
        "horizons": list(HORIZONS), "rebal_step": REBAL_STEP, "top_frac": TOP_FRAC,
        "buffer_frac": BUFFER_FRAC, "costs": COSTS,
        "factors": FACTORS, "min_names": MIN_NAMES, "min_price": MIN_PRICE,
    }, indent=2, ensure_ascii=False))

    if len(keep_series):
        pd.DataFrame(keep_series).to_csv(OUT / "daily_returns.csv.gz", compression="gzip")

    log("\n=== VERDICT: " + verdict.upper() + " ===")
    log(f"IC pass: {decision['ic_pass_factors']}")
    if decision["best_stress"]:
        b = decision["best_stress"]
        log(f"best stress: {b['factor']} {b['dir']} net={b['ann_excess']:+.4f} IR={b['ir']:+.2f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
