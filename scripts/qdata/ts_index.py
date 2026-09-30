#!/usr/bin/env python
"""指数行情数据层（Liquidity / Risk 族的基准输入）。

用途
----
`Liquidity` 族的 ``volume_alpha_300d_{000001,000300}`` 与 `Risk` 族的
``beta_*d_{000300,000001}`` / ``sigma_1320d_*`` / ``volume_beta_120d_000300`` /
``beta_consistency_1320d_000300`` 都需要**指数行情**作为基准：

    ==================  ==========================================
    qdata 后缀           Tushare ts_code
    ==================  ==========================================
    ``_000300``         ``000300.SH``  沪深300
    ``_000001``         ``000001.SH``  上证指数（**注意不是** 000001.SZ 平安银行）
    ==================  ==========================================

口径
----
1. 指数**不需要复权**（``index_daily`` 无 adj_factor，指数本身是连续序列）。
   因此 :class:`IndexPanel.C` 即原始收盘价。
2. ``index_daily`` 的 ``vol`` 单位「手」，``amount`` 单位「千元」，与 ``daily`` 一致。
3. 本模块**只读** ``ts_env.load_token``，不使用 ``ts.set_token``
   （后者会写 ``/root/tk.csv``，沙箱下只读失败）。

缓存
----
``output/qdata_factor_repro/cache/index_<code>_<start>_<end>.pkl``。
"""
from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

_SCRIPTS = Path(__file__).resolve().parents[1]
for _p in (str(_SCRIPTS), str(_SCRIPTS / "qdata")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from ts_env import load_token  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parents[2]
CACHE_DIR = REPO_ROOT / "output" / "qdata_factor_repro" / "cache"
CACHE_DIR.mkdir(parents=True, exist_ok=True)

#: qdata 因子名后缀 → Tushare 指数代码
INDEX_CODES = {
    "000300": "000300.SH",   # 沪深300
    "000001": "000001.SH",   # 上证指数
}

_PRO = None


def pro():
    global _PRO
    if _PRO is None:
        import tushare as ts
        _PRO = ts.pro_api(load_token())
    return _PRO


def load_index(index_code: str, start: str, end: str,
               use_cache: bool = True) -> pd.DataFrame:
    """取单只指数日线（不复权），返回 index=交易日 的 DataFrame。

    列：``O/H/L/C/V/AMOUNT/PCT_CHG``（``V`` 单位手，``AMOUNT`` 单位千元）。
    """
    code = INDEX_CODES.get(index_code, index_code)
    s, e = start.replace("-", ""), end.replace("-", "")
    cname = CACHE_DIR / f"index_{code.replace('.', '_')}_{s}_{e}.pkl"
    if use_cache and cname.is_file():
        return pd.read_pickle(cname)
    pr = pro()
    df = pr.index_daily(ts_code=code, start_date=s, end_date=e)
    if df is None or df.empty:
        raise RuntimeError(f"index_daily 返回空: {code} {s}~{e}")
    df = df.copy()
    df["trade_date"] = pd.to_datetime(df["trade_date"])
    df = df.sort_values("trade_date").set_index("trade_date")
    out = pd.DataFrame({
        "O": df["open"], "H": df["high"], "L": df["low"], "C": df["close"],
        "V": df["vol"], "AMOUNT": df["amount"], "PCT_CHG": df["pct_chg"],
    })
    if use_cache:
        pd.to_pickle(out, cname)
    return out


def load_indices(index_codes, start: str, end: str,
                 use_cache: bool = True) -> dict[str, pd.DataFrame]:
    """批量取指数，返回 ``{qdata 后缀: DataFrame}``。"""
    return {c: load_index(c, start, end, use_cache=use_cache) for c in index_codes}


if __name__ == "__main__":
    for k, v in load_indices(["000300", "000001"], "2020-01-01", "2026-09-10").items():
        print(f"{k}: {len(v)} 行  {v.index[0].date()} ~ {v.index[-1].date()}")
        print(v.tail(2).round(3))
