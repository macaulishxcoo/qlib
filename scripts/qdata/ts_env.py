#!/usr/bin/env python
"""Tushare 官方数据层（qdata 因子复现的**输入**来源）。

用途
----
qdata 的 Key **只开通因子库**，取不到行情/财务；而项目里已配置 Tushare 官方 TOKEN，
可实时取 ``daily`` / ``daily_basic`` / ``adj_factor`` / ``fina_indicator`` / ``income`` 等。
本模块把这些接口封装成**宽表面板**（index=date, columns=ts_code），供因子复现使用。

Token 读取优先级
----------------
1. 环境变量 ``TUSHARE_TOKEN``
2. ``/root/.config/tushare/token``（项目既有位置）
3. ``~/.tushare/token``
**不硬编码进版本控制文件。**

代码格式
--------
统一用 qdata/Tushare 的 ``600519.SH`` / ``000001.SZ`` 形式。转换工具见 :func:`to_ts_code` /
:func:`from_qlib_code`（本地 qlib 用 ``SH600519``）。

缓存
----
面板按 (codes, start, end, fq) 落盘到 ``output/qdata_factor_repro/cache/``，
重复运行不联网。Tushare 有积分限流，**务必先读缓存**。
"""
from __future__ import annotations

import os
import pickle
import sys
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[2]
CACHE_DIR = REPO_ROOT / "output" / "qdata_factor_repro" / "cache"
CACHE_DIR.mkdir(parents=True, exist_ok=True)

TOKEN_PATHS = [Path("/root/.config/tushare/token"), Path.home() / ".tushare" / "token"]


def load_token() -> str:
    """按优先级读取 Tushare token。"""
    t = os.environ.get("TUSHARE_TOKEN", "").strip()
    if t:
        return t
    for p in TOKEN_PATHS:
        if p.is_file():
            t = p.read_text(encoding="utf-8").strip()
            if t:
                return t
    raise RuntimeError(
        "未找到 Tushare token。请任选其一：\n"
        "  A) export TUSHARE_TOKEN=<你的token>\n"
        "  B) 写入 /root/.config/tushare/token"
    )


_PRO = None


def pro():
    """惰性初始化的 Tushare pro 接口。"""
    global _PRO
    if _PRO is None:
        import tushare as ts
        _PRO = ts.pro_api(load_token())
    return _PRO


# ---- 代码格式 ----------------------------------------------------------------
def to_ts_code(code: str) -> str:
    """``SH600519`` / ``sh600519`` → ``600519.SH``；已是 ``600519.SH`` 则原样返回。"""
    c = code.strip().upper()
    if "." in c:
        return c
    if c[:2] in ("SH", "SZ", "BJ"):
        return f"{c[2:]}.{c[:2]}"
    raise ValueError(f"无法识别的代码格式: {code}")


def from_qlib_code(code: str) -> str:
    """qlib 风格 ``SH600519`` → Tushare ``600519.SH``。"""
    return to_ts_code(code)


def to_qlib_code(ts_code: str) -> str:
    """Tushare ``600519.SH`` → qlib ``SH600519``。"""
    num, ex = ts_code.split(".")
    return f"{ex}{num}"


# ---- 面板 --------------------------------------------------------------------
@dataclass
class TSPanel:
    """宽表面板：index=DatetimeIndex, columns=Tushare 代码（如 600519.SH）。"""

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


def _key(*parts) -> str:
    import hashlib
    import json
    h = hashlib.sha1(json.dumps(parts, default=str, sort_keys=True).encode()).hexdigest()[:16]
    return h


def _cache(name: str, obj=None):
    p = CACHE_DIR / name
    if obj is None:
        if p.is_file():
            with p.open("rb") as f:
                return pickle.load(f)
        return None
    with p.open("wb") as f:
        pickle.dump(obj, f)
    return obj


PAGE = 6000          # Tushare 单次上限
SCHEMA = 1


def load_panel(codes: list[str], start: str, end: str, adj: str = "post",
               use_cache: bool = True) -> TSPanel:
    """取行情面板 + 复权因子 + 每日指标，全部转成宽表。

    ``adj``：``"post"`` 后复权 / ``"pre"`` 前复权 / ``"none"`` 不复权。
    后复权价 = ``close × adj_factor``（再按最后一日归一，便于跨期比较）。

    额外字段：
        ``O/H/L/C/V/AMOUNT/PCT_CHG``（按 ``adj`` 复权）
        ``C_RAW``（不复权收盘）、``ADJ``（复权因子）
        ``TURNOVER``（换手率 %）、``TURNOVER_F``、``VOLUME_RATIO``、
        ``PE_TTM``、``PB``、``PS_TTM``、``DV_TTM``、
        ``TOTAL_SHARE``、``FLOAT_SHARE``、``FREE_SHARE``、``TOTAL_MV``、``CIRC_MV``
    """
    codes = [to_ts_code(c) for c in codes]
    codes = sorted(dict.fromkeys(codes))
    cname = f"ts_panel_v{SCHEMA}_{adj}_{_key(codes, start, end)}.pkl"
    if use_cache:
        got = _cache(cname)
        if got is not None:
            print(f"  [ts] 面板缓存命中（{len(got.codes)} 只 × {len(got.dates)} 日）")
            return got

    pr = pro()
    basic_fields = ["turnover_rate", "turnover_rate_f", "volume_ratio", "pe_ttm",
                    "pb", "ps_ttm", "dv_ttm", "total_share", "float_share",
                    "free_share", "total_mv", "circ_mv"]
    px_frames, af_frames, db_frames = [], [], []
    for i, c in enumerate(codes):
        d = pr.daily(ts_code=c, start_date=start.replace("-", ""),
                     end_date=end.replace("-", ""))
        if d is not None and not d.empty:
            px_frames.append(d)
        a = pr.adj_factor(ts_code=c, start_date=start.replace("-", ""),
                          end_date=end.replace("-", ""))
        if a is not None and not a.empty:
            af_frames.append(a)
        b = pr.daily_basic(ts_code=c, start_date=start.replace("-", ""),
                           end_date=end.replace("-", ""), fields="ts_code,trade_date," +
                           ",".join(basic_fields))
        if b is not None and not b.empty:
            db_frames.append(b)
        if (i + 1) % 50 == 0:
            print(f"    …已取 {i+1}/{len(codes)}")

    def widen(frames, cols):
        if not frames:
            return {}
        df = pd.concat(frames, ignore_index=True)
        df["trade_date"] = pd.to_datetime(df["trade_date"])
        return {c: df.pivot(index="trade_date", columns="ts_code", values=c).sort_index()
                for c in cols if c in df.columns}

    out: dict[str, pd.DataFrame] = {}
    raw = widen(px_frames, ["open", "high", "low", "close", "vol", "amount", "pct_chg"])
    af = widen(af_frames, ["adj_factor"]).get("adj_factor")
    out["C_RAW"] = raw["close"]
    out["ADJ"] = af.reindex(raw["close"].index).ffill() if af is not None else 1.0
    factor = out["ADJ"]
    if adj == "none":
        factor = pd.DataFrame(1.0, index=factor.index, columns=factor.columns)
    for src, dst in [("open", "O"), ("high", "H"), ("low", "L"),
                     ("close", "C"), ("vol", "V"), ("amount", "AMOUNT")]:
        out[dst] = raw[src] * factor
    out["PCT_CHG"] = raw["pct_chg"]
    out.update({k.upper(): v for k, v in widen(db_frames, basic_fields).items()})

    panel = TSPanel(codes=list(out["C"].columns), fields=out)
    if use_cache:
        _cache(cname, panel)
    print(f"  [ts] 面板已取回并缓存（{len(panel.codes)} 只 × {len(panel.dates)} 日）")
    return panel


if __name__ == "__main__":
    p = load_panel(["600519.SH", "000001.SZ"], "2025-01-01", "2026-09-10")
    print("字段:", sorted(p.fields))
    print("样例:\n", p.C.tail(3).round(2))
