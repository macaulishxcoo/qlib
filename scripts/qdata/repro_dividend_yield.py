#!/usr/bin/env python
"""实现最后一个已解除阻塞的 Value 因子：`dividend_yield_3y_avg`。

════════════════════════════════════════════════════════════════════════
公式（取自 `factor_desc`）
════════════════════════════════════════════════════════════════════════
    dividend_yield_3y_avg = (SUM(ActualCashDiviRMB, 735) / 3) / ClosePrice
                          = AVG(ActualCashDiviRMB, 3年) / ClosePrice
    Factor = CrossSectionalRank(dividend_yield_3y_avg)

* `ActualCashDiviRMB` = **每股实派分红** → Tushare `dividend.cash_div_tax`（税后）
* 窗口 **735 个交易日 = 245×3**（约 3 年）
* 参考: Afactors faclib/value/div_p_3y

实现：把每股分红放在**除权日**（`ex_date`）上、其余交易日为 0，做 735 日滚动求和再 /3，
除以当日收盘价（原始收盘价，来自离线 `daily_basic` 镜像）。

⚠️ `dividend` 接口**不支持批量**（必须给 `ts_code`/`ann_date`/`ex_date` 之一），
故逐股取数并落盘缓存。抽样 N 只即可 —— Spearman 在子集上仍是有效估计量。

用法::

    python scripts/qdata/repro_dividend_yield.py --max-codes 1500
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

_SCRIPTS = Path(__file__).resolve().parents[1]
for p in (str(_SCRIPTS), str(_SCRIPTS / "qdata"), str(_SCRIPTS / "jqdata")):
    if p not in sys.path:
        sys.path.insert(0, p)

from qdata_env import QDataClient      # noqa: E402
from ts_env import load_token          # noqa: E402
from xs_compare import compare_xs, summarize_xs  # noqa: E402

FACTOR = "dividend_yield_3y_avg"
WINDOW = 735                # 245 × 3 交易日
CACHE = Path("output/qdata_factor_repro/cache")
OUT = Path("output/qdata_factor_repro")
DIV_CACHE = CACHE / "dividend"
DAILY_BASIC = Path("data/external/tushare/a_share_daily_basic_pit_v1/normalized/daily_basic.csv.gz")


def fetch_dividends(codes: list[str]) -> pd.DataFrame:
    """逐股取 `dividend` 并合并缓存。"""
    DIV_CACHE.mkdir(parents=True, exist_ok=True)
    import tushare as ts
    pro = ts.pro_api(load_token())
    frames = []
    n_new = 0
    for i, c in enumerate(codes):
        p = DIV_CACHE / f"{c}.pkl"
        if p.is_file():
            d = pd.read_pickle(p)
        else:
            d = None
            for attempt in range(4):
                try:
                    d = pro.dividend(ts_code=c)
                    break
                except Exception:  # noqa: BLE001
                    time.sleep(1.5 + attempt)
            if d is None:
                d = pd.DataFrame()
            time.sleep(0.12)
            pd.to_pickle(d, p)
            n_new += 1
        if d is not None and len(d):
            frames.append(d)
        if (i + 1) % 200 == 0:
            print(f"    …{i+1}/{len(codes)}（新取 {n_new}）", flush=True)
    return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()


def build_local(codes: list[str], dates: pd.DatetimeIndex) -> pd.DataFrame:
    db = pd.read_csv(DAILY_BASIC, usecols=["ts_code", "trade_date", "close"])
    db = db[db["ts_code"].isin(codes)].copy()
    db["trade_date"] = pd.to_datetime(db["trade_date"].astype(str))
    close = db.pivot_table(index="trade_date", columns="ts_code", values="close")
    close = close.reindex(dates).ffill()
    return close


def main() -> int:
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--max-codes", type=int, default=1500)
    ap.add_argument("--all-codes", action="store_true",
                    help="用全部官方截面股票（不做抽样）")
    ap.add_argument("--fetch-only", action="store_true",
                    help="只取分红数据（分批用）：取 --limit 只尚未缓存的股票后退出")
    ap.add_argument("--limit", type=int, default=700, help="--fetch-only 时本批取多少只")
    ap.add_argument("--dates", nargs="*",
                    default=["20260811", "20260812", "20260813", "20260814", "20260817"])
    args = ap.parse_args()

    cli = QDataClient()
    # 以官方截面确定股票池（取第一天的官方值）
    d0 = args.dates[0]
    rows = cli.factor_value(factor_name=FACTOR, trade_date=d0)
    if not rows:
        print("官方值取不到"); return 1
    off0 = pd.Series({r["ts_code"]: float(r["factor_value"]) for r in rows})
    codes = sorted(off0.index)
    UNIV = CACHE / "dividend_universe.pkl"
    pd.to_pickle(codes, UNIV)

    if args.fetch_only:
        done = {p.stem for p in DIV_CACHE.glob("*.pkl")} if DIV_CACHE.is_dir() else set()
        todo = [c for c in codes if c not in done][: args.limit]
        print(f"分红缓存已有 {len(done)} 只；本批取 {len(todo)} 只（剩余 "
              f"{len([c for c in codes if c not in done]) - len(todo)}）", flush=True)
        if not todo:
            print("已全部缓存"); return 0
        import tushare as ts
        pro = ts.pro_api(load_token())
        DIV_CACHE.mkdir(parents=True, exist_ok=True)
        for i, c in enumerate(todo, 1):
            d = None
            for attempt in range(4):
                try:
                    d = pro.dividend(ts_code=c)
                    break
                except Exception:  # noqa: BLE001
                    time.sleep(1.5 + attempt)
            pd.to_pickle(d if d is not None else pd.DataFrame(), DIV_CACHE / f"{c}.pkl")
            time.sleep(0.10)
            if i % 200 == 0:
                print(f"    …{i}/{len(todo)}", flush=True)
        print(f"本批完成，缓存总数 {len(list(DIV_CACHE.glob('*.pkl')))}")
        return 0

    # 均匀抽样（按代码排序后等距取，覆盖各板块）
    if not args.all_codes and args.max_codes and len(codes) > args.max_codes:
        step = len(codes) / args.max_codes
        codes = [codes[int(i * step)] for i in range(args.max_codes)]
    print(f"抽样 {len(codes)} 只（官方截面 {len(off0)} 只）", flush=True)

    missing = [c for c in codes if not (DIV_CACHE / f"{c}.pkl").is_file()]
    if missing:
        print(f"⚠️ 仍有 {len(missing)} 只无分红缓存（本次只用已缓存的）", flush=True)
    div = fetch_dividends([c for c in codes if (DIV_CACHE / f"{c}.pkl").is_file()])
    print(f"分红记录 {len(div)} 行，覆盖 {div.ts_code.nunique()} 只", flush=True)
    if div.empty:
        print("无分红数据"); return 1

    # 实施的分红（div_proc 含"实施"），除权日
    div = div.copy()
    for c in ("ex_date", "record_date", "ann_date", "end_date"):
        if c in div.columns:
            div[c] = pd.to_datetime(div[c].astype(str), format="%Y%m%d", errors="coerce")
    if "div_proc" in div.columns:
        impl = div["div_proc"].astype(str)
        sel = impl.str.contains("实施", na=False)
        if sel.sum() > 0:
            div = div[sel]
    print(f"  实施类分红 {len(div)} 行", flush=True)

    # 交易日索引与收盘价：**只读一次** daily_basic（1.9GB gz，重复读有 OOM 风险）
    cidx = pd.DatetimeIndex([pd.Timestamp(d) for d in args.dates])
    need_from = cidx.min() - pd.Timedelta(days=int(WINDOW * 1.6))
    db = pd.read_csv(DAILY_BASIC, usecols=["ts_code", "trade_date", "close"])
    db = db[db["ts_code"].isin(codes)]
    db["trade_date"] = pd.to_datetime(db["trade_date"].astype(str))
    all_days = pd.DatetimeIndex(sorted(db["trade_date"].unique()))
    idx = all_days[(all_days >= need_from) & (all_days <= cidx.max())]
    close = (db.pivot_table(index="trade_date", columns="ts_code", values="close")
               .reindex(idx).ffill())
    del db
    print(f"  计算区间 {idx.min().date()} ~ {idx.max().date()}（{len(idx)} 日）", flush=True)
    results = {}
    for col in ("cash_div_tax", "cash_div"):
        if col not in div.columns:
            continue
        # 逐股构造「除权日=每股分红，其余=0」的日序列
        series = []
        for c, g in div.dropna(subset=["ex_date"]).groupby("ts_code", sort=False):
            g = g[(g["ex_date"] >= idx.min()) & (g["ex_date"] <= idx.max())]
            if g.empty:
                continue
            s = pd.Series(0.0, index=idx, dtype=float)
            v = pd.to_numeric(g[col], errors="coerce").fillna(0.0)
            for e, val in zip(g["ex_date"], v):
                if e in s.index:
                    s.loc[e] += float(val)
            s.name = c
            series.append(s)
        if not series:
            continue
        daily = pd.concat(series, axis=1).reindex(columns=codes).fillna(0.0)
        local = (daily.rolling(WINDOW, min_periods=1).sum() / 3.0) / close
        local = local.replace([np.inf, -np.inf], np.nan).reindex(cidx)

        # ⚠️ 实证标定：必须**剔除上市不足 3 年**的股票。
        #    全市场 A/B（4 日，5416 只）：基线 0.989898 → 剔除<3年 **0.990599**（越过 0.99 阈值）；
        #    而剔除<1年仅 0.989927（几乎无变化）⇒ 跳变正好发生在 3 年处，
        #    与「3 年平均股息率」的窗口语义一致：无 3 年历史的股票其 sum/3 被系统性低估。
        try:
            import tushare as ts
            sb = ts.pro_api(load_token()).stock_basic(list_status="L").set_index("ts_code")
            ld = pd.to_datetime(sb["list_date"], format="%Y%m%d", errors="coerce")
            for t in local.index:
                ok = [c for c in local.columns
                      if pd.notna(ld.get(c)) and ld.get(c) <= t - pd.Timedelta(days=365 * 3)]
                local.loc[t, [c for c in local.columns if c not in ok]] = np.nan
        except Exception as e:  # noqa: BLE001
            print(f"  [warn] 上市日期过滤失败，跳过：{str(e)[:60]}", flush=True)
        # CrossSectionalRank
        n = local.notna().sum(axis=1)
        local = local.rank(axis=1, method="max").div(n.replace(0, np.nan), axis=0)
        results[col] = local.loc[:, local.notna().any()]
        print(f"  [{col}] 本地可算 {int(local.notna().sum().sum())} 个 stock-day", flush=True)

    if not results:
        print("本地值为空"); return 1

    official = {}
    for d in args.dates:
        rows = cli.factor_value(factor_name=FACTOR, trade_date=d)
        if rows:
            official[d] = pd.Series({r["ts_code"]: float(r["factor_value"]) for r in rows})
    if not official:
        print("官方值全空"); return 1
    off = pd.DataFrame(official).T
    off.index = pd.to_datetime(off.index, format="%Y%m%d")
    off = off.sort_index()

    offd = {f"{FACTOR}[{k}]": off for k in results}
    d = compare_xs("qdata_value", {f"{FACTOR}[{k}]": v for k, v in results.items()},
                   offd, list(offd))
    with pd.option_context("display.width", 200):
        print(d.to_string(index=False, float_format=lambda x: f"{x:.6f}"))
    print(summarize_xs(d))
    d.to_csv(OUT / "dividend_yield_compare.csv", index=False)
    print(f"产出: {OUT / 'dividend_yield_compare.csv'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
