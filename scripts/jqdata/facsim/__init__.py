"""聚宽因子本地复现与自动比对体系。

模块分工：
    conventions  口径约定（唯一来源，含实测标定证据）
    ops          算子库（宽表，复用 factorlib.ops）
    data         数据层（面板 / 官方因子值 / 缓存 / 额度记账）
    families/*   各族因子实现
    registry     族注册表与实施顺序
    compare      比对引擎与精度判定
"""
from __future__ import annotations

from . import compare, conventions, data, ops, registry  # noqa: F401

__all__ = ["compare", "conventions", "data", "ops", "registry"]
