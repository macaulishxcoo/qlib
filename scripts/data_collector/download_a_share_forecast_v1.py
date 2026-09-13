#!/usr/bin/env python3
"""A 股业绩预告（forecast）下载 v1 —— 负面事件分类型研究的经营类事件源。

选题评审：research/decisions/a_share_negative_event_subtype_proposal_v1.md（T1 经营类）
权限探测：2026-08-13 实测 tushare `forecast` 接口个人权限可用（按 ann_date 逐日拉取）。
范围：2022-01-01 ~ 最新交易日（默认 2026-08-07），逐日拉取，断点续跑。

事件定义（冻结于协议）：
  T1 经营类-预亏/预减 = forecast.type ∈ {预亏, 首亏, 续亏, 预减, 略减}
  （type 枚举含：预增/预减/扭亏/首亏/续亏/续盈/略增/略减/减亏/增亏/不确定）

用法：
  python scripts/data_collector/download_a_share_forecast_v1.py
  python scripts/data_collector/download_a_share_forecast_v1.py \
      --end-date 2026-08-07 --sleep-seconds 0.4
"""

from __future__ import annotations

import argparse
import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
import tushare as ts

TOKEN_PATH = Path.home() / ".config/tushare/token"
DEFAULT_RAW_DIR = Path("data/external/tushare/a_share_forecast_v1")
QLIB_CALENDAR = Path("~/.qlib/qlib_data/cn_data_2026/calendars/day.txt").expanduser()
START_DATE = "2022-01-01"
DEFAULT_END = "2026-08-07"
RETRY = 5

FIELDS = [
    "ts_code", "ann_date", "end_date", "type",
    "p_change_min", "p_change_max", "net_profit_min", "net_profit_max",
]


def get_token() -> str:
    token = os.environ.get("TUSHARE_TOKEN")
    if token:
        return token.strip()
    if TOKEN_PATH.is_file():
        return TOKEN_PATH.read_text(encoding="utf-8").strip()
    raise RuntimeError("TUSHARE_TOKEN env var or token file required")


def trade_days(start: str, end: str) -> list[str]:
    """返回 YYYYMMDD 格式的交易日列表。"""
    days = pd.read_csv(QLIB_CALENDAR, header=None)[0].astype(str).str.replace("-", "")
    s, e = start.replace("-", ""), end.replace("-", "")
    return [d for d in days if s <= d <= e]


def fetch_with_retry(pro, api: str, **kwargs) -> pd.DataFrame:
    last = None
    for _ in range(RETRY):
        try:
            return getattr(pro, api)(**kwargs)
        except Exception as exc:  # noqa: BLE001
            last = exc
            time.sleep(1.0)
    raise last


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--raw-dir", type=Path, default=DEFAULT_RAW_DIR)
    parser.add_argument("--start-date", default=START_DATE)
    parser.add_argument("--end-date", default=DEFAULT_END)
    parser.add_argument("--sleep-seconds", type=float, default=0.4)
    args = parser.parse_args()

    raw = args.raw_dir / "raw"
    aux = args.raw_dir / "aux"
    raw.mkdir(parents=True, exist_ok=True)
    aux.mkdir(parents=True, exist_ok=True)
    completed_path = aux / "completed_dates.csv"
    completed = set()
    if completed_path.is_file():
        completed = set(pd.read_csv(completed_path, header=None)[0].astype(str))

    pro = ts.pro_api(get_token())
    days = trade_days(args.start_date, args.end_date)
    pending = [d for d in days if d not in completed]
    print(f"trade days: {len(days)}, already completed: {len(completed)}, pending: {len(pending)}", flush=True)

    failed: list[str] = []
    done = 0
    for i, day in enumerate(pending):
        try:
            df = fetch_with_retry(pro, "forecast", ann_date=day, fields=",".join(FIELDS))
            if not df.empty:
                df.to_csv(raw / f"{day}_forecast.csv.gz", index=False, compression="gzip")
            done += 1
        except Exception as exc:  # noqa: BLE001
            print(f"  FAIL {day}: {exc}", flush=True)
            failed.append(day)
        # 限频：即使失败也写 completed？—— 不，失败不写，下次重试
        if not failed or failed[-1] != day:
            with open(completed_path, "a", encoding="utf-8") as fh:
                fh.write(f"{day}\n")
        if i % 50 == 0:
            print(f"  progress {i}/{len(pending)} (done={done}, failed={len(failed)})", flush=True)
        time.sleep(args.sleep_seconds)

    print(f"done={done}, failed={len(failed)}", flush=True)
    if failed:
        print(f"failed dates: {failed[:20]}", flush=True)

    # manifest
    files = sorted(raw.glob("*_forecast.csv.gz"))
    total_rows = 0
    for f in files:
        try:
            total_rows += len(pd.read_csv(f, usecols=["ts_code"]))
        except Exception:  # noqa: BLE001
            pass
    manifest = {
        "dataset": "a_share_forecast_v1",
        "purpose": "A 股业绩预告（负面事件分类型研究 T1 经营类事件源）",
        "start_date": args.start_date,
        "end_date": args.end_date,
        "completed_dates": len(completed) + done,
        "pending_dates": len(failed),
        "file_count": len(files),
        "total_rows": int(total_rows),
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
    }
    (args.raw_dir / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(manifest, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
