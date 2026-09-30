#!/usr/bin/env python
"""全市场 Tushare 面板（Alpha101 横截面复现的输入层）。

为什么需要它
------------
Alpha101 族大量使用**横截面**算子（``Rank`` / ``Scale`` / ``IndNeutralize``），
其取值取决于参与排名的**股票全集**。用 6 只样本股复现 ``Rank`` 与官方
（基于全市场约 5500 只）必然不同。因此必须建全市场面板。

设计要点
--------
1. **按交易日整日取数**：Tushare ``daily`` / ``adj_factor`` / ``daily_basic``
   都支持 ``trade_date=YYYYMMDD`` 一次返回全市场（≈5540 行，0.3~1.2 s/日），
   远快于按股票循环（5500 次调用）。
2. **按日落盘缓存** 到 ``output/qdata_factor_repro/cache/market/<YYYYMMDD>.pkl``，
   重复运行零联网。断点续取：已有缓存的日期直接跳过。
3. **代码格式** 统一 ``600519.SH``（与 qdata 一致），列 = ts_code，行 = 交易日。
4. **价格口径**：与 ``ts_env.load_panel`` 一致 —— ``C = close × adj_factor``（后复权，G1）。
   同时保留不复权列（``C_RAW`` 等）与换手率/市值，便于逐项标定口径。

单位说明（Tushare 原生）
------------------------
- ``vol``   单位「手」(100 股)
- ``amount`` 单位「千元」
- ⇒ 真实成交均价 = ``amount × 1000 / (vol × 100) = amount × 10 / vol``
  （:func:`TSPanel.vwap_raw` 与 :func:`TSPanel.vwap_hfq`）

Token
-----
复用 ``ts_env.pro()``（``TUSHARE_TOKEN`` → ``/root/.config/tushare/token``）。
**不使用 ``ts.set_token``**（会写 ``/root/tk.csv``，沙箱只读）。
"""
from __future__ import annotations

import sys
import time
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import pandas as pd

_SCRIPTS = Path(__file__).resolve().parents[1]
for _p in (str(_SCRIPTS), str(_SCRIPTS / "qdata")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from ts_env import load_token, to_ts_code  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parents[2]
MARKET_CACHE = REPO_ROOT / "output" / "qdata_factor_repro" / "cache" / "market"
MARKET_CACHE.mkdir(parents=True, exist_ok=True)

SCHEMA = 2                      # 缓存结构版本
_SLEEP = 0.12                   # 顺序取数，留速率余量

_PRO = None


def pro():
    """惰性初始化的 Tushare pro 接口（直接传 token，不落盘）。"""
    global _PRO
    if _PRO is None:
        import tushare as ts
        _PRO = ts.pro_api(load_token())
    return _PRO


# ============================================================ 交易日历 ==========
def trade_dates(start: str, end: str, use_cache: bool = True) -> list[str]:
    """区间内 SSE 开市日（``YYYYMMDD`` 升序）。"""
    s, e = start.replace("-", ""), end.replace("-", "")
    cname = MARKET_CACHE / f"cal_{s}_{e}.pkl"
    if use_cache and cname.is_file():
        return pd.read_pickle(cname)
    cal = pro().trade_cal(exchange="SSE", start_date=s, end_date=e,
                          fields="cal_date,is_open")
    days = sorted(cal.loc[cal["is_open"] == 1, "cal_date"].astype(str).tolist())
    if use_cache:
        pd.to_pickle(days, cname)
    return days


# ============================================================ 单日取数 ==========
_DAILY_COLS = ["ts_code", "trade_date", "open", "high", "low", "close",
               "pre_close", "pct_chg", "vol", "amount"]
_BASIC_COLS = ["ts_code", "trade_date", "turnover_rate", "turnover_rate_f",
               "total_share", "float_share", "free_share", "total_mv", "circ_mv"]


def day_cache_path(d: str) -> Path:
    return MARKET_CACHE / f"d{SCHEMA}_{d}.pkl"


def fetch_day(d: str, retries: int = 4) -> dict | None:
    """取单个交易日的全市场 ``daily`` + ``adj_factor`` + ``daily_basic``。"""
    p = day_cache_path(d)
    if p.is_file():
        return pd.read_pickle(p)
    pr = pro()
    payload: dict[str, pd.DataFrame] = {}
    specs = [("daily", "daily", _DAILY_COLS),
             ("adj", "adj_factor", ["ts_code", "trade_date", "adj_factor"]),
             ("basic", "daily_basic", _BASIC_COLS)]
    for key, api, cols in specs:
        last = None
        for att in range(retries):
            try:
                df = getattr(pr, api)(trade_date=d)
                last = None
                break
            except Exception as exc:               # noqa: BLE001  (限流/网络)
                last = exc
                time.sleep(1.5 ** att)
        if last is not None:
            raise RuntimeError(f"{api} {d} 取数失败: {last}")
        if df is None or df.empty:
            df = pd.DataFrame(columns=cols)
        else:
            df = df[[c for c in cols if c in df.columns]]
        payload[key] = df.set_index("ts_code") if "ts_code" in df.columns else df
        time.sleep(_SLEEP)
    if payload["daily"].empty:
        return None
    payload["date"] = d
    pd.to_pickle(payload, p)
    return payload


# ============================================================ 面板 ==============
@dataclass
class TSPanel:
    """全市场宽表：index=DatetimeIndex, columns=ts_code。"""

    codes: list[str]
    fields: dict[str, pd.DataFrame] = field(default_factory=dict)

    def __getattr__(self, item: str) -> pd.DataFrame:
        f = self.__dict__.get("fields", {})
        if item in f:
            return f[item]
        raise AttributeError(item)

    @property
    def dates(self) -> pd.DatetimeIndex:
        return next(iter(self.fields.values())).index

    # ---- 派生成交均价 --------------------------------------------------------
    def vwap_raw(self) -> pd.DataFrame:
        """真实成交均价（元/股，不复权）= amount×10 / vol。"""
        return self.AMOUNT * 10.0 / self.V.replace(0, np.nan)

    def vwap_hfq(self) -> pd.DataFrame:
        """与后复权价可比 = vwap_raw × adj_factor。"""
        return self.vwap_raw() * self.ADJ

    # ---- 价格口径（Alpha101 实测：不复权 + 停牌日「走平」）------------------
    def prices(self, mode: str = "raw", flat: bool = True) -> dict[str, pd.DataFrame]:
        """按口径返回价量宽表。

        ``mode``：
            ``"raw"`` 不复权（**qdata Alpha101 族实测口径**）
            ``"hfq"`` 后复权 ``价×adj_factor``（qdata Momentum/Risk 族口径）
            ``"fq"``  归一化复权 ``价×adj/adj_last``（≈前复权）
        ``flat``：
            **停牌日「走平」约定**（实测标定，2026-09-17）：
            无成交日 ``O = H = L = C = 前一交易日收盘``；``V``/``AMOUNT`` 保持 NaN。
            证据：``alpha101_101`` 要求 ``(C−O)/(H−L+0.001)``，官方对 600984.SH /
            603221.SH（当日 Tushare 无行情）返回 **0**，且官方当日 ``Rank`` 的并列块
            恰好比本地多 3 只 ⇒ 官方把这 3 只停牌股的价格走平纳入横截面。
        """
        adj = self.ADJ
        if mode == "hfq":
            mult: pd.DataFrame | None = adj
        elif mode == "fq":
            last = adj.ffill().iloc[-1].replace(0, np.nan)
            mult = adj.div(last, axis=1)
        else:
            mult = None

        def sc(df: pd.DataFrame) -> pd.DataFrame:
            return df if mult is None else df.mul(mult)

        O, H, L, C = sc(self.O_RAW), sc(self.H_RAW), sc(self.L_RAW), sc(self.C_RAW)
        traded = self.C_RAW.notna()
        if flat:
            Cf = C.ffill()
            O, H, L = (O.where(traded, Cf), H.where(traded, Cf), L.where(traded, Cf))
            C = Cf
        VW = self.vwap_raw()
        if mult is not None:
            VW = VW.mul(mult)
        return {"O": O, "H": H, "L": L, "C": C, "V": self.V,
                "AMOUNT": self.AMOUNT, "VWAP": VW, "ADJ": adj}


_SUM_FIELDS = ["open", "high", "low", "close", "pre_close", "pct_chg", "vol", "amount"]
_BASIC_MAP = {"turnover_rate": "TURNOVER", "turnover_rate_f": "TURNOVER_F",
              "total_share": "TOTAL_SHARE", "float_share": "FLOAT_SHARE",
              "free_share": "FREE_SHARE", "total_mv": "TOTAL_MV", "circ_mv": "CIRC_MV"}


def load_market(start: str, end: str, *, fields: str = "all",
                use_cache: bool = True, verbose: bool = True) -> TSPanel:
    """全市场面板。

    ``fields="all"`` 返回 ``O/H/L/C/V/AMOUNT/ADJ/C_RAW/O_RAW/H_RAW/L_RAW/``
    ``PCT_CHG/TOTAL_MV/CIRC_MV/TURNOVER/TOTAL_SHARE/FLOAT_SHARE/FREE_SHARE``
    以及 ``VWAP_RAW`` / ``VWAP_HFQ``。
    ``fields="core"`` 只返回 Alpha101 必需列（省内存）。
    """
    s, e = start.replace("-", ""), end.replace("-", "")
    days = trade_dates(s, e, use_cache=use_cache)
    want = set(days)
    have = [d for d in days if day_cache_path(d).is_file()]
    miss = [d for d in days if d not in set(have)]
    if verbose:
        print(f"  [mkt] {len(days)} 个交易日，缓存命中 {len(have)}，待取 {len(miss)}")
    for i, d in enumerate(miss):
        try:
            fetch_day(d)
        except Exception as exc:                    # noqa: BLE001
            print(f"    !! {d} 取数失败：{exc}")
            continue
        if verbose and (i + 1) % 25 == 0:
            print(f"    …已取 {i+1}/{len(miss)}（{d}）")

    # ---- 逐字段组装宽表 -------------------------------------------------------
    per_field: dict[str, dict[str, pd.Series]] = {}
    for d in days:
        p = day_cache_path(d)
        if not p.is_file() or d not in want:
            continue
        pl = pd.read_pickle(p)
        dly = pl["daily"]
        adj = pl["adj"]
        bas = pl["basic"]
        a = adj["adj_factor"] if "adj_factor" in adj.columns else pd.Series(dtype=float)
        row_adj = a.reindex(dly.index).ffill() if len(a) else pd.Series(1.0, index=dly.index)
        for c in _SUM_FIELDS:
            if c in dly.columns:
                per_field.setdefault(c, {})[d] = dly[c]
        per_field.setdefault("adj_factor", {})[d] = a
        for c in _BASIC_MAP:
            if c in bas.columns:
                per_field.setdefault(c, {})[d] = bas[c]

    def wide(name: str) -> pd.DataFrame | None:
        dd = per_field.get(name)
        if not dd:
            return None
        df = pd.DataFrame(dd)            # index=ts_code, columns=date
        df = df.T.sort_index()           # index=date, columns=ts_code
        df.index = pd.to_datetime(df.index, format="%Y%m%d")
        return df

    out: dict[str, pd.DataFrame] = {}
    raw = {c: wide(c) for c in _SUM_FIELDS}
    adj = wide("adj_factor")
    # 复权因子对齐到行情列，再沿日期前向填充（停牌日无 adj_factor 行）
    if adj is not None:
        adj = adj.reindex(columns=raw["close"].columns).sort_index().ffill().bfill()
    out["C_RAW"] = raw["close"]
    out["O_RAW"] = raw["open"]
    out["H_RAW"] = raw["high"]
    out["L_RAW"] = raw["low"]
    out["ADJ"] = adj if adj is not None else pd.DataFrame(
        1.0, index=raw["close"].index, columns=raw["close"].columns)
    out["V"] = raw["vol"]
    out["AMOUNT"] = raw["amount"]
    out["PCT_CHG"] = raw["pct_chg"]
    for src, dst in [("open", "O"), ("high", "H"), ("low", "L"), ("close", "C")]:
        out[dst] = raw[src] * out["ADJ"]
    for c, name in _BASIC_MAP.items():
        f = wide(c)
        if f is not None:
            out[name] = f

    p = TSPanel(codes=list(out["C"].columns), fields=out)
    p.fields["VWAP_RAW"] = p.vwap_raw()
    p.fields["VWAP_HFQ"] = p.vwap_hfq()
    if fields == "core":
        keep = ["O", "H", "L", "C", "V", "AMOUNT", "ADJ",
                "O_RAW", "H_RAW", "L_RAW", "C_RAW",
                "VWAP_RAW", "VWAP_HFQ", "TOTAL_MV", "TURNOVER"]
        p.fields = {k: v for k, v in p.fields.items() if k in keep}
    if verbose:
        print(f"  [mkt] 面板就绪：{len(p.codes)} 只 × {len(p.dates)} 日 "
              f"({p.dates[0].date()} ~ {p.dates[-1].date()})")
    return p


# ============================================================ 股票池 / 行业 ====
def stock_basic(use_cache: bool = True) -> pd.DataFrame:
    """全部 A 股基础信息（含 ``industry`` / ``list_date`` / ``delist_date``）。"""
    cname = MARKET_CACHE / f"stock_basic_v{SCHEMA}.pkl"
    if use_cache and cname.is_file():
        return pd.read_pickle(cname)
    pr = pro()
    frames = []
    for st in ("L", "D", "P"):
        try:
            df = pr.stock_basic(exchange="", list_status=st,
                                fields="ts_code,name,industry,market,list_date,delist_date")
        except Exception:                            # noqa: BLE001
            continue
        if df is not None and not df.empty:
            df = df.copy()
            df["list_status"] = st
            frames.append(df)
        time.sleep(_SLEEP)
    out = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()
    if use_cache and not out.empty:
        pd.to_pickle(out, cname)
    return out


def industry_map(use_cache: bool = True) -> pd.Series:
    """``ts_code -> industry``（Tushare 口径，非申万/中信）。"""
    sb = stock_basic(use_cache=use_cache)
    if sb.empty:
        return pd.Series(dtype=object)
    return sb.drop_duplicates("ts_code").set_index("ts_code")["industry"]


def listed_universe(dates: pd.DatetimeIndex, sb: pd.DataFrame | None = None) -> pd.DataFrame:
    """布尔矩阵：某日该股是否「已上市且未退市」（按 ``list_date``/``delist_date``）。"""
    sb = stock_basic() if sb is None else sb
    d8 = dates.strftime("%Y%m%d")
    codes = sb["ts_code"].tolist()
    lst = pd.to_datetime(sb.set_index("ts_code")["list_date"], format="%Y%m%d", errors="coerce")
    dls = pd.to_datetime(sb.set_index("ts_code")["delist_date"], format="%Y%m%d", errors="coerce")
    l = lst.reindex(codes)
    d = dls.reindex(codes)
    m = pd.DataFrame(False, index=dates, columns=codes)
    for i, dt in enumerate(dates):
        ok = (l <= dt) & (d.isna() | (d > dt))
        m.iloc[i] = ok.reindex(codes).fillna(False).values
    return m


def alive_mask(dates: pd.DatetimeIndex, codes, use_cache: bool = True) -> pd.DataFrame:
    """``(date × code)`` 布尔矩阵：上市中（不早于 list_date，且未退市）。

    用途：**停牌走平**约定会给退市股无限前向填充，若不做退市过滤，它们会一直
    留在横截面 ``Rank`` 里污染名次。
    """
    sb = stock_basic(use_cache=use_cache)
    codes = pd.Index(codes)
    if sb.empty:
        return pd.DataFrame(True, index=dates, columns=codes)
    lst = pd.to_datetime(sb.drop_duplicates("ts_code").set_index("ts_code")["list_date"],
                         format="%Y%m%d", errors="coerce").reindex(codes)
    dls = pd.to_datetime(sb.drop_duplicates("ts_code").set_index("ts_code")["delist_date"],
                         format="%Y%m%d", errors="coerce").reindex(codes)
    # 用「距起点的天数」做二维广播比较
    d0 = dates[0]
    dd = ((dates - d0).days.values[:, None]).astype(float)
    ll = (lst - d0).dt.days.values.astype(float)
    dl = (dls - d0).dt.days.values.astype(float)
    with np.errstate(invalid="ignore"):
        m = (ll[None, :] <= dd) & (np.isnan(dl)[None, :] | (dl[None, :] > dd))
    m &= np.isfinite(ll)[None, :]
    m |= np.isnan(ll)[None, :]        # 无 list_date 信息的代码不因上市状态被剔除
    return pd.DataFrame(m, index=dates, columns=codes)


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser(description="全市场 Tushare 面板取数/缓存")
    ap.add_argument("--start", default="2025-04-01")
    ap.add_argument("--end", default="2026-09-10")
    ap.add_argument("--prefetch", action="store_true", help="只补缓存，不组装面板")
    a = ap.parse_args()
    if a.prefetch:
        ds = trade_dates(a.start, a.end)
        miss = [d for d in ds if not day_cache_path(d).is_file()]
        print(f"{len(ds)} 日，待取 {len(miss)}")
        for i, d in enumerate(miss):
            fetch_day(d)
            if (i + 1) % 25 == 0:
                print(f"  …{i+1}/{len(miss)}")
        print("完成")
    else:
        p = load_market(a.start, a.end)
        print(sorted(p.fields))
        print(p.C.tail(2).iloc[:, :3])
