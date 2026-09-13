#!/usr/bin/env python
"""Verify the research environment and the live A-share data sources.

Run with the research virtual environment interpreter, e.g.::

    D:\\workspaces\\qlib\\research\\.venv\\Scripts\\python.exe research\\scripts\\verify_env.py

The script never raises for an individual probe: every check reports PASS / FAIL /
WARN and the process exit code is 0 only when no required check FAILED.
"""

from __future__ import annotations

import importlib
import os
import platform
import shutil
import sys
import traceback
from pathlib import Path

MIN_PYTHON = (3, 10)
RECOMMENDED_PYTHON = (3, 11)

REQUIRED_PACKAGES = [
    "pandas",
    "numpy",
    "pyarrow",
    "scipy",
    "statsmodels",
    "lightgbm",
    "matplotlib",
    "plotly",
    "tqdm",
    "yaml",
    "akshare",
    "baostock",
    "tushare",
]

RESEARCH_ROOT = Path(__file__).resolve().parent.parent

_results: list[tuple[str, str, str]] = []


def record(status: str, name: str, detail: str = "") -> None:
    _results.append((status, name, detail))
    line = f"[{status:4}] {name}"
    if detail:
        line += f" -- {detail}"
    print(line)


def check(name: str, fn) -> None:
    """Run one probe, converting an exception into a FAIL record."""
    try:
        status, detail = fn()
    except Exception as exc:  # noqa: BLE001 - a probe failure must not abort the run
        record("FAIL", name, f"{type(exc).__name__}: {exc}")
        return
    record(status, name, detail)


# --------------------------------------------------------------------------- #
# interpreter and filesystem
# --------------------------------------------------------------------------- #


def probe_interpreter() -> tuple[str, str]:
    version = sys.version_info
    detail = f"{platform.python_implementation()} {version.major}.{version.minor}.{version.micro} on {platform.platform()}"
    if (version.major, version.minor) < MIN_PYTHON:
        return "FAIL", detail + " -- need Python >= 3.10"
    if (version.major, version.minor) == RECOMMENDED_PYTHON:
        return "PASS", detail
    return "WARN", detail + f" -- {RECOMMENDED_PYTHON[0]}.{RECOMMENDED_PYTHON[1]} recommended"


def probe_executable() -> tuple[str, str]:
    return "PASS", sys.executable


def probe_venv() -> tuple[str, str]:
    in_venv = sys.prefix != getattr(sys, "base_prefix", sys.prefix)
    if in_venv:
        return "PASS", sys.prefix
    return "WARN", "not running inside a virtual environment"


def probe_disk() -> tuple[str, str]:
    usage = shutil.disk_usage(str(RESEARCH_ROOT))
    free_gb = usage.free / (1024**3)
    detail = f"{free_gb:.1f} GiB free at {RESEARCH_ROOT}"
    if free_gb < 5:
        return "FAIL", detail + " -- need >= 5 GiB for the daily panel"
    return "PASS", detail


def probe_write() -> tuple[str, str]:
    RESEARCH_ROOT.mkdir(parents=True, exist_ok=True)
    target = RESEARCH_ROOT / ".write_probe"
    target.write_text("ok", encoding="utf-8")
    target.unlink()
    return "PASS", str(RESEARCH_ROOT)


def probe_data_dirs() -> tuple[str, str]:
    created = []
    for name in ("data", "reports", "notebooks"):
        path = RESEARCH_ROOT / name
        path.mkdir(parents=True, exist_ok=True)
        created.append(name)
    return "PASS", ", ".join(created)


# --------------------------------------------------------------------------- #
# packages
# --------------------------------------------------------------------------- #


def probe_packages() -> tuple[str, str]:
    missing: list[str] = []
    versions: list[str] = []
    for name in REQUIRED_PACKAGES:
        try:
            module = importlib.import_module(name)
        except Exception as exc:  # noqa: BLE001
            missing.append(f"{name} ({type(exc).__name__})")
            continue
        versions.append(f"{name}=={getattr(module, '__version__', '?')}")
    if missing:
        return "FAIL", "missing: " + ", ".join(missing)
    print("       " + "  ".join(versions))
    return "PASS", f"{len(REQUIRED_PACKAGES)} packages importable"


# --------------------------------------------------------------------------- #
# baostock
# --------------------------------------------------------------------------- #

BAOSTOCK_FIELDS = "date,code,open,high,low,close,volume,amount,turn,pctChg,isST"


def probe_baostock() -> tuple[str, str]:
    import baostock as bs

    login = bs.login()
    if login.error_code != "0":
        return "FAIL", f"login error {login.error_code}: {login.error_msg}"
    try:
        result = bs.query_history_k_data_plus(
            "sh.600000",
            BAOSTOCK_FIELDS,
            start_date="2024-01-02",
            end_date="2024-01-31",
            frequency="d",
            adjustflag="2",
        )
        if result.error_code != "0":
            return "FAIL", f"query error {result.error_code}: {result.error_msg}"
        rows = []
        while result.next():
            rows.append(result.get_row_data())
        if not rows:
            return "FAIL", "query returned no rows"
        first, last = rows[0], rows[-1]
        return "PASS", f"{len(rows)} rows, {first[0]} close={first[5]} .. {last[0]} close={last[5]}"
    finally:
        bs.logout()


# --------------------------------------------------------------------------- #
# akshare
# --------------------------------------------------------------------------- #


def probe_akshare_history() -> tuple[str, str]:
    import akshare as ak

    frame = ak.stock_zh_a_hist(
        symbol="600000",
        period="daily",
        start_date="20240102",
        end_date="20240131",
        adjust="hfq",
    )
    if frame is None or frame.empty:
        return "FAIL", "empty frame"
    return "PASS", f"{len(frame)} rows, columns={list(frame.columns)[:6]}"


def probe_akshare_delisted() -> tuple[str, str]:
    import akshare as ak

    frames = []
    for name in ("stock_info_sh_delist", "stock_info_sz_delist"):
        fn = getattr(ak, name, None)
        if fn is None:
            continue
        try:
            frame = fn()
        except Exception as exc:  # noqa: BLE001
            print(f"       {name}: {type(exc).__name__}: {exc}")
            continue
        if frame is not None and not frame.empty:
            frames.append((name, len(frame)))
    if not frames:
        return "WARN", "no delisted-stock list retrieved -- survivorship bias cannot be checked yet"
    detail = ", ".join(f"{name}={count}" for name, count in frames)
    return "PASS", detail


# --------------------------------------------------------------------------- #
# qlib community data (optional cross-check)
# --------------------------------------------------------------------------- #


def probe_qlib_data() -> tuple[str, str]:
    candidates = [
        Path.home() / ".qlib" / "qlib_data" / "cn_data",
        RESEARCH_ROOT.parent / "data" / "cn_data",
    ]
    for candidate in candidates:
        if candidate.is_dir():
            instruments = list(candidate.glob("instruments/*.txt"))
            return "PASS", f"{candidate} ({len(instruments)} instrument lists)"
    return "WARN", "no qlib cn_data directory found -- cross-check dataset unavailable"


# --------------------------------------------------------------------------- #

CHECKS = [
    ("python interpreter", probe_interpreter),
    ("python executable", probe_executable),
    ("virtual environment", probe_venv),
    ("disk space", probe_disk),
    ("research root writable", probe_write),
    ("data directories", probe_data_dirs),
    ("required packages", probe_packages),
    ("baostock daily history", probe_baostock),
    ("akshare daily history", probe_akshare_history),
    ("akshare delisted lists", probe_akshare_delisted),
    ("qlib cn_data (cross-check)", probe_qlib_data),
]


def main() -> int:
    print("=" * 72)
    print(" CN daily-frequency quant research - environment verification")
    print("=" * 72)
    print(f"research root: {RESEARCH_ROOT}")
    print(f"cwd          : {os.getcwd()}")
    print()

    for name, fn in CHECKS:
        check(name, fn)

    failures = [row for row in _results if row[0] == "FAIL"]
    warnings = [row for row in _results if row[0] == "WARN"]

    print()
    print("-" * 72)
    print(f"summary: {len(_results) - len(failures) - len(warnings)} pass, "
          f"{len(warnings)} warn, {len(failures)} fail")
    for status, name, detail in failures:
        print(f"  FAIL {name}: {detail}")
    print("-" * 72)

    return 1 if failures else 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except SystemExit:
        raise
    except Exception:  # noqa: BLE001
        traceback.print_exc()
        raise SystemExit(2)
