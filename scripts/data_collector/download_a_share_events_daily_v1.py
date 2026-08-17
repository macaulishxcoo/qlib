#!/usr/bin/env python3
"""每日结构化事件数据下载 v1（股东增减持 / 限售解禁 / 龙虎榜）。

选题评审：research/decisions/a_share_events_daily_stream_proposal_v1.md
范围：2022-01-01 ~ 最新交易日（默认 2026-08-07），逐日拉取，断点续跑。

主事件（按日期批量，已实测可用）：
  - stk_holdertrade(ann_date=YYYYMMDD)  股东增减持
  - share_float(ann_date=YYYYMMDD)      限售解禁公告（事件日取 float_date，见协议）
  - top_list(trade_date=YYYYMMDD)       龙虎榜（当日收盘后披露）

附录事件 stk_rewards（股权激励）需逐 ts_code 查询、事件稀疏（600519 2022 后为 0），
暂缓下载；若后续确需再立项。

用法：
  python scripts/data_collector/download_a_share_events_daily_v1.py
  python scripts/data_collector/download_a_share_events_daily_v1.py \
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

TOKEN_PATH = Path("/root/.config/tushare/token")
DEFAULT_RAW_DIR = Path("data/external/tushare/a_share_events_daily_v1")
QLIB_CALENDAR = Path("~/.qlib/qlib_data/cn_data_2026/calendars/day.txt").expanduser()
START_DATE = "2022-01-01"
DEFAULT_END = "2026-08-07"
# 接口名 -> 逐日查询参数名
ENDPOINTS = {
    "stk_holdertrade": "ann_date",
    "share_float": "ann_date",
    "top_list": "trade_date",
}
RETRY = 5


def get_token() -> str:
    token = os.environ.get("TUSHARE_TOKEN")
    if token:
        return token.strip()
    if TOKEN_PATH.is_file():
        return TOKEN_PATH.read_text(encoding="utf-8").strip()
    raise RuntimeError("TUSHARE_TOKEN env var or token file required")


def trade_days(start: str, end: str) -> list[str]:
    """返回 YYYYMMDD 格式的交易日列表（qlib 日历为 YYYY-MM-DD，接口查询需无横线）。"""
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
    parser.add_argument("--sleep-seconds", type=float, default=0.4,
                        help="每次接口调用间隔（限频保护）")
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

    failed: list[tuple[str, str, str]] = []
    done = 0
    for i, day in enumerate(pending):
        ok = True
        for endpoint, param in ENDPOINTS.items():
            try:
                frame = fetch_with_retry(pro, endpoint, **{param: day})
            except Exception as exc:  # noqa: BLE001
                ok = False
                failed.append((day, endpoint, str(exc)[:120]))
                print(f"      FAIL {day} {endpoint}: {str(exc)[:80]}", flush=True)
                continue
            if frame is None:
                frame = pd.DataFrame()
            # 空事件日也写表头文件，区分"无事件"与"数据缺失"
            frame.to_csv(raw / f"{day}_{endpoint}.csv.gz", index=False, compression="gzip")
        if ok:
            with open(completed_path, "a", encoding="utf-8") as fh:
                fh.write(day + "\n")
            done += 1
            if done % 50 == 0:
                print(f"      {done}/{len(pending)} ({day})", flush=True)
        time.sleep(args.sleep_seconds)

    # manifest
    files = sorted(raw.glob("*.csv.gz"))
    by_endpoint: dict[str, int] = {}
    total_rows = 0
    date_range = [None, None]
    for f in files:
        endpoint = f.name.split(".")[0][9:]  # 去掉 YYYYMMDD_ 前缀（9 字符）与扩展名
        by_endpoint[endpoint] = by_endpoint.get(endpoint, 0) + 1
        day = f.name[:8]
        date_range[0] = day if date_range[0] is None else min(date_range[0], day)
        date_range[1] = day if date_range[1] is None else max(date_range[1], day)
        df = pd.read_csv(f, compression="gzip")
        total_rows += len(df)

    manifest = {
        "dataset": "a_share_events_daily_v1",
        "purpose": "每日结构化事件流：股东增减持/限售解禁/龙虎榜",
        "start_date": args.start_date,
        "end_date": args.end_date,
        "completed_dates": len(completed) + done,
        "pending_dates": len(pending) - done,
        "file_count": len(files),
        "total_rows": int(total_rows),
        "files_by_endpoint": by_endpoint,
        "raw_date_range": date_range,
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
    }
    (args.raw_dir / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")

    print(json.dumps(manifest, ensure_ascii=False, indent=2), flush=True)
    if failed:
        print(f"FAILED {len(failed)} records (first 10):", flush=True)
        for row in failed[:10]:
            print(f"  {row}", flush=True)
        raise SystemExit(1)
    print("DONE", flush=True)


if __name__ == "__main__":
    main()
