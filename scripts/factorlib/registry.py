#!/usr/bin/env python3
"""因子族注册表。新增族时在此登记。"""
from __future__ import annotations

from . import (fam_alpha101, fam_growth, fam_liquidity, fam_momentum, fam_quality,
               fam_reversal, fam_risk, fam_size, fam_value)

FAMILIES = {
    'Reversal': fam_reversal,
    'Risk': fam_risk,
    'Liquidity': fam_liquidity,
    'Momentum': fam_momentum,
    'Size': fam_size,
    'Value': fam_value,
    'Growth': fam_growth,
    'Alpha101': fam_alpha101,
    'Quality': fam_quality,
}
