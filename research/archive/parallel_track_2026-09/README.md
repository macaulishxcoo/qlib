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
