#!/usr/bin/env python3
"""Port hardcoded Linux paths so the repo runs on this machine.

The original environment was ``/home/xiaocong/worksapces/qlib`` with the conda
env and qlib store under ``/root``. Here the repo lives at
``/mnt/d/workspaces/qlib`` and the store under ``$HOME``. Only 20 literal paths
across 19 files need changing; everything else already uses ``Path.home()`` or
repo-relative paths.

Edits are exact-string replacements, reported per file. Run without ``--apply``
to preview. A git safety snapshot should exist first (see
``git log``: "snapshot: research docs + scripts before machine-migration porting").
"""

from __future__ import annotations

import argparse
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
SCRIPTS = REPO / "scripts"

_RAW_OLD = 'Path("/home/xiaocong/worksapces/qlib/data/external/tushare/market_daily_v1")'

# (relative glob, old literal, new literal, human note)
# NOTE the parents[N] depth differs per directory: __file__ is scripts/x.py in
# one case and scripts/data_collector/x.py in the other.
RULES: list[tuple[str, str, str, str]] = [
    (
        "scripts/*.py",
        'Path("/root/.config/tushare/token")',
        'Path.home() / ".config/tushare/token"',
        "tushare token path -> $HOME",
    ),
    (
        "scripts/*/*.py",
        'Path("/root/.config/tushare/token")',
        'Path.home() / ".config/tushare/token"',
        "tushare token path -> $HOME",
    ),
    (
        "scripts/*.py",
        'qlib_dir = "/root/.qlib/qlib_data/cn_data_2026"',
        'qlib_dir = str(Path.home() / ".qlib/qlib_data/cn_data_2026")',
        "qlib store path -> $HOME",
    ),
    (
        "scripts/*.py",
        f"DEFAULT_RAW_DIR = {_RAW_OLD}",
        'DEFAULT_RAW_DIR = Path(__file__).resolve().parents[1] / "data/external/tushare/market_daily_v1"',
        "raw market dir -> repo-relative (scripts/)",
    ),
    (
        "scripts/data_collector/*.py",
        f"DEFAULT_RAW_DIR = {_RAW_OLD}",
        'DEFAULT_RAW_DIR = Path(__file__).resolve().parents[2] / "data/external/tushare/market_daily_v1"',
        "raw market dir -> repo-relative (scripts/data_collector/)",
    ),
    (
        "scripts/validate_a_share_margin_signal_v1.py",
        'PROBE_DIR = Path("/tmp/margin_probe")',
        'PROBE_DIR = Path(__file__).resolve().parents[1] / "data/external/tushare/margin_pit_v1/raw"',
        "margin probe dir -> the real margin_pit_v1 dataset (fixes the stale /tmp path "
        "flagged in PROJECT_SYNC section 5 item 4)",
    ),
    # --- second pass: literal forms the first rules missed -------------------
    (
        "scripts/*/*.py",
        'pd.read_csv("/root/.qlib/qlib_data/cn_data_2026/calendars/day.txt"',
        'pd.read_csv(str(Path.home() / ".qlib/qlib_data/cn_data_2026/calendars/day.txt")',
        "calendar path read -> $HOME",
    ),
    (
        "scripts/*/*.py",
        'calendar_path = Path("/root/.qlib/qlib_data/cn_data_2026/calendars/day.txt")',
        'calendar_path = Path.home() / ".qlib/qlib_data/cn_data_2026/calendars/day.txt"',
        "calendar path -> $HOME",
    ),
    (
        "scripts/*/*.py",
        'default=Path("/root/.qlib/qlib_data/cn_data_2026")',
        'default=Path.home() / ".qlib/qlib_data/cn_data_2026"',
        "argparse default qlib dir -> $HOME",
    ),
    (
        "scripts/*/*.py",
        "/root/.config/tushare/token is absent",
        "~/.config/tushare/token is absent",
        "error message token path (cosmetic)",
    ),
    (
        "scripts/*/*.py",
        "TUSHARE_TOKEN or /root/.config/tushare/token",
        "TUSHARE_TOKEN or ~/.config/tushare/token",
        "error message token path (cosmetic)",
    ),
]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--apply", action="store_true", help="write the changes (default: preview)")
    args = parser.parse_args()

    changed: list[tuple[Path, str, int, str]] = []
    warnings: list[str] = []

    for pattern, old, new, note in RULES:
        if old == new:
            continue
        for path in sorted(REPO.glob(pattern)):
            if not path.is_file():
                continue
            # scripts/migration holds this script's own rule data; rewriting it
            # would corrupt the rules themselves.
            if "migration" in path.parts:
                continue
            text = path.read_text(encoding="utf-8", errors="surrogateescape")
            count = text.count(old)
            if count == 0:
                continue
            changed.append((path, note, count, old))
            if args.apply:
                path.write_text(text.replace(old, new), encoding="utf-8",
                                errors="surrogateescape")
                # Any rewrite that references Path must have it in scope.
                if ("Path.home()" in new or "Path(__file__)" in new) and "import Path" not in text:
                    warnings.append(f"{path.name}: rewritten to use Path but never imports it")

    print("=" * 88)
    print(f" path porting ({'APPLIED' if args.apply else 'PREVIEW'})")
    print("=" * 88)
    if not changed:
        print("  nothing to change (already ported?)")
    total = 0
    for path, note, count, _ in changed:
        total += count
        print(f"  {path.relative_to(REPO)}")
        print(f"      {count} x  {note}")
    print()
    print(f"  {len(changed)} files, {total} replacements")
    for warning in warnings:
        print(f"  WARNING: {warning}")

    print()
    remaining = 0
    for path in sorted(SCRIPTS.rglob("*.py")):
        # scripts/migration holds this script's own rule data, not real usage.
        if "migration" in path.parts:
            continue
        text = path.read_text(encoding="utf-8", errors="surrogateescape")
        for needle in ("/root/", "/home/xiaocong"):
            if needle in text:
                # Crontab examples inside docstrings on the old machine are
                # harmless documentation; flag them separately.
                kind = "docstring-only" if "crontab" in text.lower() else "NEEDS FIXING"
                remaining += 1
                print(f"  [{kind}] {path.relative_to(REPO)} contains {needle!r}")
    print(f"  residual literal hits: {remaining}")
    print("=" * 88)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
