#!/usr/bin/env bash
# Move the parallel research track written while the shell was broken into an
# archive directory, so it cannot be mistaken for part of the project's
# governed research lines (research/{charters,protocols,decisions,specifications}).
set -euo pipefail
REPO=/mnt/d/workspaces/qlib
cd "${REPO}"

ARCH="research/archive/parallel_track_2026-09"
mkdir -p "${ARCH}"

move_if_exists() {
  if [ -e "$1" ]; then
    mv "$1" "${ARCH}/"
    echo "  moved $1"
  fi
}

move_if_exists research/cnquant
move_if_exists research/scripts
move_if_exists research/README.md
move_if_exists research/docs/RESEARCH_PLAN.md
move_if_exists research/docs/RESUME.md
move_if_exists research/docs/ENVIRONMENT.md

cat > "${ARCH}/README.md" <<'EOF'
# Archived: parallel research track (2026-09)

These files were written during a period when the harness's shell tooling could
not spawn any child process, so the pre-existing state of this repository was
invisible to the authoring agent. The agent therefore built a standalone
factor/backtest stack from scratch.

That was a mistake in framing: this repository already had 150+ research
documents, 85 scripts, a landed five-factor strategy and a documented
"daily alpha exhausted" conclusion. **The authoritative entry point is
`PROJECT_SYNC.md` at the repo root, and the governed research lines live in
`research/{charters,protocols,decisions,specifications}`.**

Nothing here is on the mainline. Kept only because a few ideas in it may still
be worth mining:

* `cnquant/backtest.py` -- an explicit A-share execution model: T+1 lock,
  limit-up/limit-down fill blocking, and the **¥5 minimum commission floor**
  (which is a first-order cost at a ¥500k book and is not modelled by qlib's
  default backtester).
* `cnquant/universe.py` -- exchange-style half-up rounding of limit prices
  (naive `np.floor(x*100+0.5)/100` mis-rounds decimal ties such as 11.055).
* `cnquant/altdata.py` -- strict point-in-time `asof_align` for quarterly/event
  data, with a test proving the naive `stat_date` alignment leaks the future.
* `scripts/selftest_*.py` -- offline self-tests for the above.

Do not extend this tree. If a piece is wanted, port it into `scripts/` under the
project's protocol-first convention.
EOF

echo "archive written: ${ARCH}"
ls -1 "${ARCH}"
