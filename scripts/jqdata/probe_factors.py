#!/usr/bin/env python
"""JQData 因子可及性实测（只读）。

    bash scripts/jqdata/run.sh scripts/jqdata/probe_factors.py

用途：一次跑清「这个账号到底能拿哪些因子」，避免把**本地计算模块**误当成**账号权限**。

背景（为什么需要这个脚本）：``jqdatasdk.alpha101`` / ``alpha191`` 是**客户端模块**，
而 ``get_factor_values`` / ``get_fundamentals`` 是**服务端 API**；两者的"可用"
含义不同。本脚本把三类都探一遍并打印证据。

输出结论（2026-09-15 实测，账号区间 2025-06-07 ~ 2026-06-14）：
- Alpha101：本地可算 82/101（19 个 SDK 标注"该因子未实现"）；**无需鉴权**即
  可运行（已实测清空鉴权状态后仍可算）→ 是"本地实现"，**不是账号权益**，且不耗额度。
- Alpha191：0/191，**任何日期**都返回账号区间受限 → 服务端模块，受试用权益限制。
- 风险模型风格因子：``get_factor_values`` 支持 **10 个**（size/beta/momentum/
  residual_volatility/non_linear_size/book_to_price_ratio/liquidity/earnings_yield/growth/leverage）
  ＋ market_cap/circulating_market_cap；``get_factor_cov`` 另暴露 30 个申万一级行业因子。
- 技术指标 ``technical_analysis``：**付费模块**，未授权。
- 财务/估值因子：走 ``get_fundamentals`` 字段（valuation / indicator 表），可用。
"""

from __future__ import annotations

import sys
import warnings
from pathlib import Path

warnings.filterwarnings("ignore")
sys.path.insert(0, str(Path(__file__).resolve().parent))
from _env import auth, ensure_env  # noqa: E402

ensure_env()
DAY = "2026-03-02"
SECS = ["000001.XSHE", "600519.XSHG"]

RISK_FACTORS = [
    "size", "beta", "momentum", "residual_volatility", "non_linear_size",
    "book_to_price_ratio", "liquidity", "earnings_yield", "growth", "leverage",
]


def probe_alpha_modules() -> None:
    from jqdatasdk import alpha101, alpha191

    print("=== A) Alpha 模块（客户端计算）===")
    for label, mod, n in (("Alpha101", alpha101, 101), ("Alpha191", alpha191, 191)):
        ok, unimplemented, blocked = 0, 0, 0
        reason = ""
        for i in range(1, n + 1):
            try:
                r = getattr(mod, f"alpha_{i:03d}")(DAY)
                if r is not None and not getattr(r, "empty", False):
                    ok += 1
            except Exception as exc:  # noqa: BLE001
                msg = str(exc)
                if "未实现" in msg:
                    unimplemented += 1
                else:
                    blocked += 1
                    reason = reason or msg[:80]
        print(f"  {label:9s} 可算 {ok:3d}/{n}  未实现 {unimplemented:3d}  受限 {blocked:3d}")
        if reason:
            print(f"            受限原因: {reason}")


def probe_factor_values() -> None:
    from jqdatasdk import get_factor_values

    print("\n=== B) 风险模型风格因子（get_factor_values，服务端 API）===")
    r = get_factor_values(securities=SECS, factors=RISK_FACTORS, start_date=DAY, end_date=DAY)
    print(f"  可用 {len(r)}/{len(RISK_FACTORS)}: {sorted(r)}")
    try:
        get_factor_values(securities=SECS, factors=["alpha_001"], start_date=DAY, end_date=DAY)
        print("  alpha_001: 可用")
    except Exception as exc:  # noqa: BLE001
        print(f"  alpha_001: 不可用 -> {str(exc)[:90]}")


def probe_industry_factors() -> None:
    from jqdatasdk import get_factor_cov

    print("\n=== C) 行业因子（get_factor_cov 默认列表）===")
    cov = get_factor_cov(start_date=DAY, end_date=DAY)
    cols = list(cov.columns)
    inds = [c for c in cols if c.startswith("80")]
    print(f"  风格因子: {[c for c in cols if not c.startswith('80')]}")
    print(f"  申万一级行业因子: {len(inds)} 个")


def probe_technical() -> None:
    print("\n=== D) 技术指标模块（technical_analysis）===")
    import jqdatasdk as jq

    try:
        jq.technical_analysis.MACD(SECS[0], DAY)
        print("  MACD: 可用")
    except Exception as exc:  # noqa: BLE001
        print(f"  MACD: 不可用 -> {str(exc)[:110]}")


def probe_fundamentals() -> None:
    from jqdatasdk import get_fundamentals, indicator, query, valuation

    print("\n=== E) 财务/估值因子（get_fundamentals 字段）===")
    q = query(
        valuation.code, valuation.pe_ratio, valuation.pb_ratio, valuation.ps_ratio,
        valuation.market_cap, valuation.circulating_market_cap, valuation.turnover_ratio,
        valuation.dividend_ratio,
        indicator.roe, indicator.roa, indicator.eps, indicator.net_profit_margin,
        indicator.inc_revenue_year_on_year, indicator.inc_net_profit_year_on_year,
    ).filter(valuation.code.in_(SECS))
    df = get_fundamentals(q, date=DAY)
    print(f"  取数成功 shape={df.shape}")
    print(f"  字段: {list(df.columns)}")


def main() -> int:
    auth()
    probe_alpha_modules()
    probe_factor_values()
    probe_industry_factors()
    probe_technical()
    probe_fundamentals()
    print("\n[probe] 完成")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
