#!/usr/bin/env python3
"""qdata.cc 官方因子库客户端（tushare 兼容代理，Key 仅开通因子库）。

- 限速：QPS 30 / QPM 200（内置节流）
- 单次返回上限 6000 行（静默截断，必须分片）
- 两种取数路线：
  A) 因子×日期：一次返回全市场约 5500 只
  B) 股票×区间：一次返回该股约 219 个因子 × 约 27 个交易日

Key 读取顺序：环境变量 QDATA_KEY > .jqdata/qdata_key（已 gitignore）
"""
from __future__ import annotations

import json
import os
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

import pandas as pd

ROOT = Path('/home/xiaocong/worksapces/qlib')
BASE = 'http://api.qdata.cc/tushare/pro'
KEY_FILE = ROOT / '.jqdata/qdata_key'
ROWS_MAX = 6000

_CALLS: list[float] = []


def get_key() -> str:
    k = os.environ.get('QDATA_KEY')
    if k:
        return k.strip()
    if KEY_FILE.exists():
        return KEY_FILE.read_text().strip()
    raise RuntimeError('未找到 QDATA_KEY（env 或 .jqdata/qdata_key）')


class Throttle:
    """线程安全节流：同时满足 QPS<=qps 与 QPM<=qpm。"""

    def __init__(self, qps: float | None = None, qpm: float | None = None):
        self.qps = qps if qps is not None else float(os.environ.get('QDATA_QPS', 25))
        self.qpm = qpm if qpm is not None else float(os.environ.get('QDATA_QPM', 190))
        self._t: list[float] = []
        self._lock = threading.Lock()

    def wait(self) -> None:
        while True:
            with self._lock:
                now = time.time()
                self._t = [t for t in self._t if now - t < 60]
                if len(self._t) >= self.qpm:
                    sleep = 60 - (now - self._t[0]) + 0.05
                elif self._t and now - self._t[-1] < 1.0 / self.qps:
                    sleep = 1.0 / self.qps - (now - self._t[-1])
                else:
                    self._t.append(time.time())
                    return
            time.sleep(max(sleep, 0.005))


TH = Throttle()


def api(path: str, params: dict, retries: int = 8, timeout: int = 40) -> pd.DataFrame:
    """带自适应退避的调用：429 触发长退避（令牌桶式限流），而非失败。"""
    q = urllib.parse.urlencode({k: v for k, v in params.items() if v is not None})
    url = f'{BASE}/{path}?{q}' if q else f'{BASE}/{path}'
    last = None
    for i in range(retries):
        TH.wait()
        try:
            req = urllib.request.Request(url, headers={'X-API-Key': get_key()})
            with urllib.request.urlopen(req, timeout=timeout) as r:
                d = json.loads(r.read().decode())
            if d.get('code') != 0:
                raise RuntimeError(f"code={d.get('code')} msg={d.get('msg')}")
            data = d['data']
            return pd.DataFrame(data['items'], columns=data['fields'])
        except urllib.error.HTTPError as e:      # noqa: PERF203
            last = e
            if e.code in (429, 403):
                time.sleep(min(4 + 4 * i, 25))       # 短退避：快速适配令牌桶
            else:
                time.sleep(1.5 * (i + 1))
        except Exception as e:      # noqa: BLE001
            last = e
            time.sleep(1.5 * (i + 1))
    raise RuntimeError(f'api {path} 失败: {last}')


def factor_value(factor_name: str | None = None, ts_code: str | None = None,
                 trade_date: str | None = None, start_date: str | None = None,
                 end_date: str | None = None) -> pd.DataFrame:
    return api('factor_value', dict(factor_name=factor_name, ts_code=ts_code,
                                    trade_date=trade_date, start_date=start_date,
                                    end_date=end_date))


def factor_list() -> pd.DataFrame:
    return api('factor_list', {})
