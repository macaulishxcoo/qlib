"""各族因子实现。模块暴露 FAMILY 与 build(panel[, fund|tables]) -> dict[code, DataFrame]。"""
from __future__ import annotations

from . import (basics, emotion, growth, momentum, pershare, quality, risk,  # noqa: F401
               style, technical)

__all__ = ["basics", "emotion", "growth", "momentum", "pershare", "quality",
           "risk", "style", "technical"]
