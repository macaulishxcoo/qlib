#!/usr/bin/env python
"""因子族注册表。新增族时在此登记：``FAMILIES[族名] = 模块``。

族名与 ``factor_library_formulas.json`` 中的 ``category`` 字段一致，
便于按族批量取官方因子值、按族产出报告。
"""
from __future__ import annotations

from .families import (basics, emotion, growth, momentum, pershare, quality,
                       risk, style, technical)

# 族名 -> 模块（模块需暴露 FAMILY 常量与 build(panel) -> dict[code, DataFrame]）
FAMILIES: dict[str, object] = {
    "technical": technical,
    "risk": risk,
    "momentum": momentum,
    "emotion": emotion,
    "basics": basics,
    "quality": quality,
    "style": style,
    "pershare": pershare,
    "growth": growth,
}

# 实施顺序（按预期复现难度从低到高，先技术/财务，后风格）
PLANNED_ORDER = [
    "technical",   # 16  纯价量，公式最规整
    "risk",        # 12  收益矩，只差年化常数
    "momentum",    # 34  价量 + 回归
    "emotion",     # 36  价量 + 换手率
    "pershare",    # 15  财务
    "basics",      # 37  财务
    "growth",      # 9   财务
    "quality",     # 71  财务，含衍生比率
    "style",       # 30  预处理链，仅近似
    "style_pro",   # 16  仅简介，无公式
]
