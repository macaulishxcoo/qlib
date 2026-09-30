#!/usr/bin/env python
"""JQData 数据层：宽表面板加载 + 官方因子值取数 + 本地缓存 + 额度记账。

设计要点
--------
1. **所有网络取数都走 :func:`_quota` 记账**，避免重蹈「探测因子权限烧掉 88 万条」的覆辙
   （见 scripts/jqdata/quota.py 顶部说明）。``get_query_count``/``get_account_info`` 免费。
2. **强缓存**：面板与官方因子值按 (codes, start, end) 哈希落盘到
   ``.jqdata_cache/facsim/``，重复运行不耗额度。缓存命中时不登录、不联网。
3. 面板统一为**宽表** ``index=date, columns=code``（与 factorlib 一致）。
"""
from __future__ import annotations

import hashlib
import json
import pickle
import sys
import warnings
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import pandas as pd

from . import conventions as KV

warnings.filterwarnings("ignore")

REPO_ROOT = Path(__file__).resolve().parents[3]
JQ_DIR = REPO_ROOT / "scripts" / "jqdata"
CACHE_DIR = REPO_ROOT / ".jqdata_cache" / "facsim"
CACHE_DIR.mkdir(parents=True, exist_ok=True)

if str(JQ_DIR) not in sys.path:
    sys.path.insert(0, str(JQ_DIR))

_AUTHED = False


def _ensure_auth() -> None:
    global _AUTHED
    if _AUTHED:
        return
    from _env import auth

    auth(verbose=False)
    _AUTHED = True


class _quota:
    """最简额度记账：进入/退出时读 get_query_count（免费），打印实际消耗。"""

    def __init__(self, label: str):
        self.label = label
        self.start = None

    def __enter__(self):
        from jqdatasdk import get_query_count

        self.start = get_query_count()["spare"]
        return self

    def __exit__(self, *exc):
        from jqdatasdk import get_query_count

        used = self.start - get_query_count()["spare"]
        print(f"  [quota] {self.label}: 消耗 {used:,} 条")
        return False


def _key(*parts) -> str:
    h = hashlib.sha1(json.dumps(parts, default=str, sort_keys=True).encode()).hexdigest()[:16]
    return h


def _cache_get(name: str):
    p = CACHE_DIR / name
    if p.is_file():
        with p.open("rb") as f:
            return pickle.load(f)
    return None


def _cache_put(name: str, obj) -> None:
    with (CACHE_DIR / name).open("wb") as f:
        pickle.dump(obj, f)


# ---- 面板 --------------------------------------------------------------------
@dataclass
class Panel:
    """宽表面板：index=DatetimeIndex, columns=code（JQData 原生格式，如 000001.XSHE）。"""

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

    @property
    def ret(self) -> pd.DataFrame:
        if "RET" not in self.fields:
            self.fields["RET"] = self.fields["C"].pct_change()
        return self.fields["RET"]


def _to_wide(long_df: pd.DataFrame, field_names: list[str]) -> dict[str, pd.DataFrame]:
    out: dict[str, pd.DataFrame] = {}
    if long_df.empty:
        return {f: pd.DataFrame() for f in field_names}
    long_df = long_df.copy()
    long_df["time"] = pd.to_datetime(long_df["time"])
    for f in field_names:
        out[f] = long_df.pivot(index="time", columns="code", values=f).sort_index()
    return out


PANEL_FIELDS = ["open", "high", "low", "close", "pre_close", "volume", "money"]

# 面板字段集变更时必须递增，否则会命中旧结构缓存（曾因此踩坑：V_PRE 缺失）
PANEL_SCHEMA_VERSION = 5


def account_window() -> tuple[pd.Timestamp, pd.Timestamp]:
    """试用账号可及区间（免费调用，不耗额度）。"""
    _ensure_auth()
    from jqdatasdk import get_account_info

    info = get_account_info()
    return (pd.Timestamp(info["date_range_start"]),
            pd.Timestamp(info["date_range_end"]))


def load_panel(codes: list[str], start: str, end: str, lookback_days: int = 400,
               use_cache: bool = True) -> Panel:
    """加载后复权面板（OHLCV+money+pre_close）与不复权收盘价。

    ``lookback_days`` 为**自然日**回溯量，用于覆盖最长窗口（EMAC120/TRIX/VOL240…）。
    **回溯起点会被夹到账号可及区间的左边界**——否则 get_price 会因越界直接报错。
    夹取导致窗口不足时，早期因子值为 NaN，属预期行为（比对报告会体现为覆盖率不足）。
    """
    codes = sorted(dict.fromkeys(codes))
    w_start, _ = account_window()
    want = pd.Timestamp(start) - pd.Timedelta(days=lookback_days)
    fetch_start = max(want, w_start).strftime("%Y-%m-%d")
    if want < w_start:
        print(f"  [data] 回溯起点 {want.date()} 早于账号区间 {w_start.date()}，已夹取")
    cname = f"panel_v{PANEL_SCHEMA_VERSION}_{_key(codes, fetch_start, end)}.pkl"

    if use_cache:
        cached = _cache_get(cname)
        if cached is not None:
            print(f"  [data] 面板缓存命中 {cname}（{len(cached.codes)} 只 × {len(cached.dates)} 日）")
            return cached

    _ensure_auth()
    from jqdatasdk import get_price

    with _quota(f"panel {len(codes)}只 {fetch_start}~{end}"):
        # ⚠ **必须用默认 round=True（2 位小数）**：实测官方因子就是基于 2 位小数的
        #   后复权价计算的 —— 改用 round=False 全精度反而使 risk 族 12/12 GOOD 全数
        #   退化为 APPROX（总数 150→132）。见 conventions.py G1/G5。
        post = get_price(codes, start_date=fetch_start, end_date=end, frequency="daily",
                         fields=PANEL_FIELDS, fq=KV.FQ, panel=False)
        raw = get_price(codes, start_date=fetch_start, end_date=end, frequency="daily",
                        fields=["close", "volume"], fq="none", panel=False)
        # single_day_VPT 文档要求「当日前复权」，其成交量与后复权口径相差一个
        # 每股常数因子（实测 official/local = 1.4636 恒定）→ 需单独取前复权量价
        pre = get_price(codes, start_date=fetch_start, end_date=end, frequency="daily",
                        fields=["close", "volume"], fq="pre", panel=False)

    fields = _to_wide(post, PANEL_FIELDS)
    fields = {f: v for f, v in zip(
        ["O", "H", "L", "C", "PRE_CLOSE", "V", "MONEY"],
        [fields[k] for k in PANEL_FIELDS])}
    raw_w = _to_wide(raw, ["close", "volume"])
    fields["C_RAW"], fields["V_RAW"] = raw_w["close"], raw_w["volume"]
    pre_w = _to_wide(pre, ["close", "volume"])
    fields["C_PRE"], fields["V_PRE"] = pre_w["close"], pre_w["volume"]
    fields["VWAP"] = fields["MONEY"] / fields["V"].replace(0, np.nan)

    panel = Panel(codes=codes, fields=fields)
    if use_cache:
        _cache_put(cname, panel)
    print(f"  [data] 面板已加载并缓存 {cname}（{len(codes)} 只 × {len(panel.dates)} 日）")
    return panel


# ---- 财务/估值面板 -----------------------------------------------------------
# 换手率、市值等逐日字段走 get_fundamentals_continuously（valuation 表）。
# 注意必须用 .filter(valuation.code.in_(codes))，否则会取回全市场（每次 2.7 万行）。
FUND_FIELDS = ["turnover_ratio", "circulating_market_cap", "market_cap"]


def load_fundamentals_panel(codes: list[str], end: str, count: int,
                            fields: list[str] | None = None,
                            use_cache: bool = True) -> dict[str, pd.DataFrame]:
    """取 valuation 表的逐日宽表面板（index=date, columns=code）。

    ``count`` 为**交易日个数**（含 end 当日），需与价格面板长度一致以对齐日期。
    """
    codes = sorted(dict.fromkeys(codes))
    fields = list(fields or FUND_FIELDS)
    cname = f"fund_{_key(codes, fields, end, count)}.pkl"

    if use_cache:
        cached = _cache_get(cname)
        if cached is not None:
            print(f"  [data] 财务面板缓存命中 {cname}（{len(cached)} 字段）")
            return cached

    _ensure_auth()
    import jqdatasdk as jq
    from jqdatasdk import get_fundamentals_continuously, query

    val = jq.valuation
    q = query(val.code, *[getattr(val, f) for f in fields]).filter(val.code.in_(codes))
    with _quota(f"fundamentals {len(codes)}只×{count}日×{len(fields)}字段"):
        df = get_fundamentals_continuously(q, end_date=end, count=count)

    df = df.copy()
    df["day"] = pd.to_datetime(df["day"])
    out: dict[str, pd.DataFrame] = {}
    for f in fields:
        out[f] = df.pivot_table(index="day", columns="code", values=f, aggfunc="last").sort_index()
    if use_cache:
        _cache_put(cname, out)
    print(f"  [data] 财务面板已取回并缓存 {cname}（{len(out)} 字段 × {len(next(iter(out.values())))} 日）")
    return out


def load_table_panel(codes: list[str], end: str, count: int, table: str,
                     fields: list[str], use_cache: bool = True) -> dict[str, pd.DataFrame]:
    """按**任意财务表**（balance/income/cash_flow/indicator/valuation）取逐日宽表面板。

    与 :func:`load_fundamentals_panel` 的区别是表可选、字段以字符串给出，供财务族
    按需取报表科目。**必须 filter code.in_(codes)**，否则取回全市场。
    """
    codes = sorted(dict.fromkeys(codes))
    cname = f"tbl_{table}_{_key(codes, fields, end, count)}.pkl"
    if use_cache:
        cached = _cache_get(cname)
        if cached is not None:
            print(f"  [data] {table} 面板缓存命中 {cname}（{len(cached)} 字段）")
            return cached

    _ensure_auth()
    import jqdatasdk as jq
    from jqdatasdk import get_fundamentals_continuously, query

    t = getattr(jq, table)
    q = query(t.code, *[getattr(t, f) for f in fields]).filter(t.code.in_(codes))
    with _quota(f"{table} {len(codes)}只×{count}日×{len(fields)}字段"):
        df = get_fundamentals_continuously(q, end_date=end, count=count)

    df = df.copy()
    df["day"] = pd.to_datetime(df["day"])
    out = {f: df.pivot_table(index="day", columns="code", values=f,
                             aggfunc="last").sort_index() for f in fields}
    if use_cache:
        _cache_put(cname, out)
    print(f"  [data] {table} 面板已取回并缓存 {cname}（{len(out)} 字段）")
    return out


# ---- 全市场截面面板（截面因子用） -------------------------------------------
MARKET_SCHEMA_VERSION = 1


def load_market_close(end: str, count: int, types: tuple[str, ...] = ("stock",),
                      fields: tuple[str, ...] = ("close",), batch: int = 1000,
                      use_cache: bool = True) -> dict[str, pd.DataFrame]:
    """取**全市场**宽表面板（index=date, columns=code），供截面因子使用。

    截面因子（如 ``Rank1M``）的分母是「全市场股票总数」，用小子集无法复现 —
    必须取全市场。实测：5190 只 × 25 日 ≈ 13 万行，约占当日额度 13%。

    ``types`` 传 ``("stock",)`` 得 5190 只；``("stock","bjse")`` 含北交所共 5485 只
    （官方用哪个口径需实测确定，见 momentum.Rank1M 的标定记录）。
    """
    cname = f"mkt_v{MARKET_SCHEMA_VERSION}_{_key(end, count, types, fields)}.pkl"
    if use_cache:
        cached = _cache_get(cname)
        if cached is not None:
            print(f"  [data] 全市场面板缓存命中 {cname}")
            return cached

    _ensure_auth()
    from jqdatasdk import get_all_securities, get_price

    codes = list(get_all_securities(list(types), date=end).index)
    frames = []
    with _quota(f"全市场 {len(codes)}只×{count}日"):
        for i in range(0, len(codes), batch):
            chunk = codes[i:i + batch]
            df = get_price(chunk, end_date=end, count=count, frequency="daily",
                           fields=list(fields), fq=KV.FQ, panel=False)
            if df is not None and not df.empty:
                frames.append(df)
    long_df = pd.concat(frames, ignore_index=True)
    out = _to_wide(long_df, list(fields))
    if use_cache:
        _cache_put(cname, out)
    print(f"  [data] 全市场面板已缓存 {cname}（{len(codes)} 只 × {len(next(iter(out.values())))} 日）")
    return out


# ---- TTM 面板（过去 4 个单季之和） -------------------------------------------
TTM_SCHEMA_VERSION = 2


def load_ttm_panel(codes: list[str], stat_date: str, table: str, fields: list[str],
                   index: pd.DatetimeIndex, agg: str = "sum", count: int = 4,
                   nan_as_zero: bool = False,
                   use_cache: bool = True) -> dict[str, pd.DataFrame]:
    """取 **TTM / AvgQ**（截至 ``stat_date`` 的最新 4 个单季）并广播到 ``index``。

    ``agg="sum"``   → TTM（过去 ``count`` 季之和，用于利润表/现金流量表科目）
    ``agg="mean"``  → AvgQ（过去 ``count`` 季均值，用于资产负债表时点科目，官方记法 ``AvgQ(X,4,0)``）
    ``agg="first"`` → ``count`` 季**最早一季**的值（同比基期，如「4 季度前」）
    ``agg="last"``  → ``count`` 季**最新一季**的值（当季）

    ``nan_as_zero=True`` → 求和时把缺失季度视为 0（**仅用于官方如此处理的科目**，
    如 ``asset_impairment_loss``：实测 2025q1 常为 NaN 但官方按 0 计入）。

    配方（实测逐位一致，见 conventions.py F1）：
        get_history_fundamentals(code, fields, stat_date=最新可得季, interval="1q", count=4)
    再对 4 个单季求和。TTM 在同一报告期内是常量，故广播到给定日期索引。

    ⚠ ``stat_date`` 必须传**截至比对日已披露的最新季**（如 2026-05 比对用 ``2026q1``），
    传错会整段偏差（这正是早前误判 TTM 不可复现的原因）。
    """
    codes = sorted(dict.fromkeys(codes))
    fields = list(fields)
    cname = (f"ttm_v{TTM_SCHEMA_VERSION}_{table}_{agg}{count}"
             f"{'z' if nan_as_zero else ''}_"
             f"{_key(codes, stat_date, fields)}.pkl")
    if use_cache:
        cached = _cache_get(cname)
        if cached is not None:
            print(f"  [data] TTM({table}@{stat_date}) 缓存命中 {cname}")
            # 缓存存的是「每字段一行」的 Series（避免把日期索引也存进去导致 reindex 全 NaN）
            return {f: pd.DataFrame([v.values] * len(index), index=index,
                                    columns=list(v.index)) for f, v in cached.items()}

    _ensure_auth()
    import jqdatasdk as jq
    from jqdatasdk import get_history_fundamentals

    t = getattr(jq, table)
    cols = [getattr(t, f) for f in fields]
    with _quota(f"TTM {table}@{stat_date} {len(codes)}只×{len(fields)}字段×4季"):
        raw = {c: get_history_fundamentals(c, cols, stat_date=stat_date,
                                           interval="1q", count=count) for c in codes}

    wide: dict[str, pd.DataFrame] = {}
    for f, jqcol in zip(fields, [getattr(t, f) for f in fields]):
        ser = {}
        for c, df in raw.items():
            if df is None or df.empty or jqcol.name not in df.columns:
                ser[c] = np.nan
                continue
            # 必须满 4 季才有效（不足则为 nan，避免半截和）
            vals = df[jqcol.name]
            if vals.notna().sum() < count and not nan_as_zero:
                ser[c] = np.nan
            elif nan_as_zero and vals.notna().sum() == 0:
                ser[c] = np.nan
            elif agg == "sum":
                ser[c] = float(vals.fillna(0).sum() if nan_as_zero else vals.sum())
                ser[c] = float(vals.sum())
            elif agg == "mean":
                ser[c] = float(vals.mean())
            else:
                ser[c] = float(vals.iloc[0] if agg == "first" else vals.iloc[-1])
        row = pd.Series(ser)
        wide[f] = pd.DataFrame([row.values] * len(index), index=index,
                               columns=list(row.index))
    if use_cache:
        # 只缓存「每字段 × 各标的」的一维值（TTM 在报告期内为常量），
        # 不缓存日期索引 —— 否则 cache 回读时 reindex 会整段变 NaN（曾因此静默出错）
        _cache_put(cname, {f: v.iloc[0] for f, v in wide.items()})
    print(f"  [data] TTM({table}@{stat_date}) 已取回并广播（{len(codes)} 只 × {len(fields)} 字段）")
    return wide


# ---- 官方因子值 --------------------------------------------------------------
def load_official(codes: list[str], factor_codes: list[str], start: str, end: str,
                  use_cache: bool = True) -> dict[str, pd.DataFrame]:
    """取官方因子值（ground truth），按 (codes, factors, start, end) 缓存。"""
    codes = sorted(dict.fromkeys(codes))
    factor_codes = sorted(dict.fromkeys(factor_codes))
    cname = f"official_{_key(codes, factor_codes, start, end)}.pkl"

    if use_cache:
        cached = _cache_get(cname)
        if cached is not None:
            print(f"  [data] 官方因子缓存命中 {cname}（{len(factor_codes)} 因子）")
            return cached

    _ensure_auth()
    from jqdatasdk import get_factor_values

    n_cells = len(codes) * len(factor_codes)
    with _quota(f"official {len(factor_codes)}因子×{len(codes)}只×(日期数)"):
        got = get_factor_values(codes, factor_codes, start_date=start, end_date=end)

    if use_cache:
        _cache_put(cname, got)
    print(f"  [data] 官方因子已取回并缓存 {cname}（{len(got)}/{len(factor_codes)} 因子，"
          f"约 {n_cells} 列×日）")
    return got
