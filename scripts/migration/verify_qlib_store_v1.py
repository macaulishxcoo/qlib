#!/usr/bin/env python3
"""Verify the rebuilt qlib store actually serves the fields the strategies read.

Read-only. Exits non-zero when a required field cannot be loaded.
"""

from __future__ import annotations

import sys
from pathlib import Path

STORE = Path.home() / ".qlib/qlib_data/cn_data_2026"
BENCHMARK = "SH000852"


def main() -> int:
    print("=" * 80)
    print(f" qlib store verification: {STORE}")
    print("=" * 80)

    failures: list[str] = []

    # ---- on-disk layout ------------------------------------------------- #
    for sub in ("calendars", "features", "instruments"):
        path = STORE / sub
        if not path.exists():
            failures.append(f"missing directory: {sub}")
            print(f"  [FAIL] {sub}: missing")
            continue
        n = sum(1 for _ in path.rglob("*") if _.is_file())
        size = sum(f.stat().st_size for f in path.rglob("*") if f.is_file())
        print(f"  [ ok ] {sub:<12} {n:>7} files  {size / 1e6:>8.1f} MB")

    calendar = STORE / "calendars" / "day.txt"
    if calendar.exists():
        days = calendar.read_text(encoding="utf-8").split()
        print(f"  [ ok ] calendar      {len(days)} days  {days[0]} .. {days[-1]}")
    else:
        failures.append("calendars/day.txt missing")
        print("  [FAIL] calendars/day.txt missing")

    all_txt = STORE / "instruments" / "all.txt"
    if all_txt.exists():
        rows = [line for line in all_txt.read_text(encoding="utf-8").splitlines() if line.strip()]
        print(f"  [ ok ] all.txt       {len(rows)} instruments")
        print(f"         first: {rows[0] if rows else '-'}")
    else:
        failures.append("instruments/all.txt missing")
        print("  [FAIL] instruments/all.txt missing")

    # ---- qlib can read it ----------------------------------------------- #
    import qlib
    from qlib.config import REG_CN
    from qlib.data import D

    print()
    print(f"  qlib module: {qlib.__file__}")
    qlib.init(provider_uri=str(STORE), region=REG_CN)

    cal = D.calendar(start_time="2000-01-01", end_time="2100-01-01", freq="day")
    print(f"  [ ok ] D.calendar    {len(cal)} days  {cal.min().date()} .. {cal.max().date()}")

    fields = ["$open", "$high", "$low", "$close", "$volume", "$factor", "$vwap", "$adjclose"]
    instruments = D.instruments(market="all")
    codes = D.list_instruments(instruments=instruments,
                               start_time=str(cal.min().date()), end_time=str(cal.max().date()),
                               as_list=True)
    print(f"  [ ok ] D.list_instruments: {len(codes)} codes")
    if not codes:
        failures.append("D.list_instruments returned nothing")
        return report(failures)

    sample = codes[:3] + [BENCHMARK]
    frame = D.features(sample, fields, start_time=str(cal.min().date()),
                       end_time=str(cal.max().date()), freq="day")
    print(f"  [ ok ] D.features    shape={frame.shape} columns={list(frame.columns)}")
    for field in fields:
        if field not in frame.columns:
            failures.append(f"field {field} missing from D.features")
            continue
        coverage = float(frame[field].notna().mean())
        flag = "ok" if coverage > 0 else "FAIL"
        if coverage == 0:
            failures.append(f"field {field} is entirely NaN")
        print(f"         {field:<10} coverage {coverage:6.1%}  [{flag}]")

    print()
    print("  sample rows (last 3 dates, first instrument):")
    head = frame.xs(sample[0], level="instrument").tail(3) if not frame.empty else frame
    print(head.to_string())

    print()
    print("  benchmark check:")
    if BENCHMARK in frame.index.get_level_values("instrument"):
        bench = frame.xs(BENCHMARK, level="instrument")
        print(f"         {BENCHMARK}: {len(bench)} rows, "
              f"close {bench['$close'].min():.2f} .. {bench['$close'].max():.2f}")
    else:
        failures.append(f"benchmark {BENCHMARK} not loadable")
        print(f"  [FAIL] benchmark {BENCHMARK} not present")

    return report(failures)


def report(failures: list[str]) -> int:
    print()
    print("-" * 80)
    if failures:
        print(f"{len(failures)} FAILURE(S):")
        for item in failures:
            print(f"  - {item}")
        print("-" * 80)
        return 1
    print("store verification passed")
    print("-" * 80)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
