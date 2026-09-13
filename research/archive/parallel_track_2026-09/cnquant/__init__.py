"""Standalone CN daily-frequency quant research library.

Deliberately independent of qlib: the prior experiments in this workspace used
qlib's community dataset and default cost/portfolio assumptions, and one of the
working hypotheses is that those two choices — not the modelling method — are
what made every strategy look unprofitable.
"""

from __future__ import annotations

__all__ = ["config", "data", "universe"]
