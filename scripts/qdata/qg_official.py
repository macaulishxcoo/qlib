#!/usr/bin/env python
"""Quality/Growth 官方因子值取数（可断点续取，供 repro_quality.py 复用）。

取数纪律（见 CONVENTIONS.md G7）：
- **逐 ``(factor, ts_code)`` 单取**，避免 ``offset`` 分页的重复行问题；
- 日期用 ``YYYYMMDD``；
- 顺序调用 + 退避重试（与其它子代理共享 QPS/QPM）。

缓存：``output/qdata_factor_repro/cache/qg_official/<factor>__<code>.pkl``（按 (factor, code) 落盘，
单只单因子最多约 73 行，天然远低于 6000 上限）。
"""
from __future__ import annotations

import pickle
import sys
import time
from pathlib import Path

import pandas as pd

_SCRIPTS = Path(__file__).resolve().parents[1]
for p in (str(_SCRIPTS), str(_SCRIPTS / "jqdata"), str(_SCRIPTS / "qdata")):
    if p not in sys.path:
        sys.path.insert(0, p)

from qdata_env import QDataClient, QDataError  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parents[2]
CACHE = REPO_ROOT / "output" / "qdata_factor_repro" / "cache" / "qg_official"
CACHE.mkdir(parents=True, exist_ok=True)

CODES = ["600519.SH", "000001.SZ", "000002.SZ", "600036.SH", "002415.SZ", "000651.SZ"]


def _path(factor: str, code: str, start: str, end: str) -> Path:
    return CACHE / f"{factor}__{code}__{start}_{end}.pkl"


def fetch_one(cli: QDataClient, factor: str, code: str, start: str, end: str,
              use_cache: bool = True) -> pd.Series | None:
    p = _path(factor, code, start, end)
    if use_cache and p.is_file():
        with p.open("rb") as f:
            return pickle.load(f)
    for att in range(5):
        try:
            rows = cli.factor_value(factor_name=factor, ts_code=code,
                                    start_date=start, end_date=end)
            # ⚠ 限流时接口可能返回 code=0/msg=ok 但 items=[] → 必须当可重试，否则静默丢数据
            if not rows:
                time.sleep(1.5 * (att + 1))
                continue
            break
        except (QDataError, Exception) as exc:      # noqa: BLE001
            wait = 2.0 * (att + 1)
            print(f"    !! {factor} {code} 失败({exc}) → 退避 {wait:.0f}s")
            time.sleep(wait)
    else:
        return None
    if not rows:
        s = pd.Series(dtype=float)
    else:
        d = pd.DataFrame(rows).drop_duplicates(subset=["trade_date"])
        d["trade_date"] = pd.to_datetime(d["trade_date"], format="%Y%m%d")
        s = d.set_index("trade_date")["factor_value"].astype(float).sort_index()
    with p.open("wb") as f:
        pickle.dump(s, f)
    return s


def load_official(factors: list[str], codes: list[str], start: str, end: str,
                  verbose: bool = True) -> dict[str, pd.DataFrame]:
    """返回 ``dict[factor -> DataFrame(index=date, columns=code)]``。"""
    cli = QDataClient()
    out: dict[str, dict[str, pd.Series]] = {}
    n = 0
    t0 = time.time()
    total = len(factors) * len(codes)
    for c in codes:
        for f in factors:
            s = fetch_one(cli, f, c, start, end)
            n += 1
            if s is not None and len(s):
                out.setdefault(f, {})[c] = s
            if verbose and n % 25 == 0:
                el = time.time() - t0
                print(f"    …{n}/{total} 调用，{el:.0f}s，剩余约 {el / n * (total - n):.0f}s")
    return {f: pd.DataFrame(v).sort_index() for f, v in out.items()}


if __name__ == "__main__":
    import argparse
    import json

    ap = argparse.ArgumentParser()
    ap.add_argument("--start", default="20260601")
    ap.add_argument("--end", default="20260910")
    ap.add_argument("--codes", nargs="*", default=CODES)
    a = ap.parse_args()
    meta = json.loads((REPO_ROOT / "output/qdata_factor_repro/factor_formulas.json")
                      .read_text(encoding="utf-8"))
    facs = [k for k, v in meta.items()
            if v.get("factor_type") in ("Quality", "Growth") and "_old_" not in k]
    print(f"{len(facs)} 因子 × {len(a.codes)} 股票 = {len(facs)*len(a.codes)} 次调用")
    load_official(facs, a.codes, a.start, a.end)
    print("完成")
