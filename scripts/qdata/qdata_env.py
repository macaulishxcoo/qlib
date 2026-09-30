#!/usr/bin/env python
"""qdata.cc（Tushare 兼容）API 客户端。

数据源
------
- 主地址 ``http://api.qdata.cc``，备用 ``https://quantdata.olingma.com``
  （境外/开 VPN 时主地址可能连不上）
- 调用：``GET /tushare/pro/{api}``，请求头 ``X-API-Key``

Key 读取优先级（**不硬编码进版本控制文件**）
--------------------------------------------
1. 环境变量 ``QDATA_KEY``
2. 仓库内 ``.jqdata/qdata_key``（已 gitignore）
3. 均无 → 抛 ``RuntimeError`` 并给出设置方法

本 Key 的权限边界（2026-09-17 实测）
------------------------------------
**仅开通因子库**：``factor_list`` / ``factor_value`` 可用；
``daily`` / ``daily_basic`` / ``stock_basic`` / ``trade_cal`` / ``adj_factor``
等 246 个接口一律 ``403 subscription_required``。
⇒ 复现所需的**输入数据必须来自本地**（见 ``data/external/tushare/``）。

限流与翻页
----------
- QPS 30 / QPM 200（本模块默认压到 ``qps=20`` 留余量）
- 单次 ``limit`` 上限 **6000 行，超出静默截断**；翻页须固定 ``limit=6000``，
  以「返回行数 < 6000」判末页（不能用「行数 < 请求 limit」，否则 limit>6000 时提前终止丢数据）
"""
from __future__ import annotations

import os
import time
from dataclasses import dataclass
from pathlib import Path

import requests

REPO_ROOT = Path(__file__).resolve().parents[2]
KEY_FILE = REPO_ROOT / ".jqdata" / "qdata_key"
KEY_FILE_ALT = REPO_ROOT / "tushare_factor" / "probe" / "probe.py"

BASE_PRIMARY = "http://api.qdata.cc"
BASE_BACKUP = "https://quantdata.olingma.com"

PAGE_LIMIT = 6000          # 服务端硬上限，超出静默截断
DEFAULT_QPS = 20           # 官方 30，压到 20 留余量


def load_key() -> str:
    """按优先级读取 API Key。"""
    k = os.environ.get("QDATA_KEY", "").strip()
    if k:
        return k
    if KEY_FILE.is_file():
        k = KEY_FILE.read_text(encoding="utf-8").strip()
        if k:
            return k
    if KEY_FILE_ALT.is_file():                    # 兜底：从既有 probe 脚本解析
        import re
        m = re.search(r'KEY\s*=\s*["\']([^"\']+)["\']',
                      KEY_FILE_ALT.read_text(encoding="utf-8"))
        if m:
            return m.group(1)
    raise RuntimeError(
        "未找到 qdata API Key。请任选其一：\n"
        "  A) export QDATA_KEY=<你的key>\n"
        f"  B) 写入 {KEY_FILE}（建议 chmod 600）"
    )


@dataclass
class QDataError(RuntimeError):
    api: str
    status: int
    message: str

    def __str__(self) -> str:
        return f"[{self.api}] HTTP {self.status}: {self.message}"


class QDataClient:
    """带限流与重试的极简客户端。所有返回统一转成 ``list[dict]``。"""

    def __init__(self, key: str | None = None, base: str = BASE_PRIMARY,
                 qps: int = DEFAULT_QPS, timeout: int = 30, retries: int = 3):
        self.key = key or load_key()
        self.base = base.rstrip("/")
        self.min_interval = 1.0 / max(qps, 1)
        self.timeout = timeout
        self.retries = retries
        self._last = 0.0
        self.session = requests.Session()
        self.session.headers.update({"X-API-Key": self.key})

    # ---- 底层 ----------------------------------------------------------------
    def _throttle(self) -> None:
        wait = self.min_interval - (time.monotonic() - self._last)
        if wait > 0:
            time.sleep(wait)
        self._last = time.monotonic()

    def call_raw(self, api: str, **params) -> dict:
        """单次调用，返回服务端原始 JSON（``{code,msg,data:{fields,items}}``）。"""
        last_err = None
        for attempt in range(self.retries):
            self._throttle()
            try:
                r = self.session.get(f"{self.base}/tushare/pro/{api}",
                                     params=params, timeout=self.timeout)
            except requests.RequestException as exc:
                last_err = QDataError(api, -1, str(exc))
                time.sleep(1.5 ** attempt)
                continue
            if r.status_code == 429:                       # 限流
                time.sleep(2.0 * (attempt + 1))
                last_err = QDataError(api, 429, "触发限流")
                continue
            if r.status_code == 403:
                raise QDataError(api, 403, r.text[:200])
            if r.status_code != 200:
                last_err = QDataError(api, r.status_code, r.text[:200])
                time.sleep(1.5 ** attempt)
                continue
            j = r.json()
            if j.get("code") != 0:
                raise QDataError(api, r.status_code,
                                 f"code={j.get('code')} msg={j.get('msg')}")
            return j
        raise last_err or QDataError(api, -1, "未知错误")

    def call(self, api: str, *, page: int | None = None, **params) -> list[dict]:
        """单页调用，返回 ``list[dict]``。

        ``page`` 为 None 时用服务端默认（通常 10 行）；要取全量请传 ``page=PAGE_LIMIT``
        或直接用 :meth:`paginate`。
        """
        p = dict(params)
        if page is not None:
            p["limit"] = page
        j = self.call_raw(api, **p)
        d = j.get("data") or {}
        fields = d.get("fields") or []
        return [dict(zip(fields, row)) for row in (d.get("items") or [])]

    def paginate(self, api: str, **params) -> list[dict]:
        """按 ``offset`` 翻页取全量。

        固定 ``limit=PAGE_LIMIT``，以「返回行数 < PAGE_LIMIT」判末页。
        """
        out: list[dict] = []
        offset = 0
        while True:
            rows = self.call(api, page=PAGE_LIMIT, offset=offset, **params)
            out.extend(rows)
            if len(rows) < PAGE_LIMIT:
                break
            offset += PAGE_LIMIT
        return out

    # ---- 便捷方法 ------------------------------------------------------------
    def factor_list(self, **params) -> list[dict]:
        """因子元数据（含 ``factor_desc`` 里的数学表达式），单次可取全部。"""
        return self.call("factor_list", page=PAGE_LIMIT, **params)

    def factor_value(self, factor_name: str | None = None,
                     ts_code: str | None = None,
                     trade_date: str | None = None,
                     start_date: str | None = None,
                     end_date: str | None = None) -> list[dict]:
        """因子数值（长表 ``factor_name / ts_code / trade_date / factor_value``）。

        ⚠ 单次 6000 行上限。1 只股票 1 个交易日 ≈ 219 行 → 约 27 个 stock-day/次。
        取多日多因子时请自行分批。
        """
        p = {k: v for k, v in dict(factor_name=factor_name, ts_code=ts_code,
                                   trade_date=trade_date, start_date=start_date,
                                   end_date=end_date).items() if v}
        return self.paginate("factor_value", **p)


if __name__ == "__main__":
    c = QDataClient()
    print(f"base={c.base}  key={c.key[:8]}…{c.key[-4:]}")
    rows = c.factor_list(limit=3)
    for r in rows[:3]:
        print(f"  {r['factor_name']:22s} {r['factor_type']:10s} {r['factor_desc'][:40]!r}")
