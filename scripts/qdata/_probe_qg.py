#!/usr/bin/env python
"""一次性探针：观察 Quality/Growth 官方因子值形态（rank 还是原始值）。"""
from __future__ import annotations

import sys
import time
from pathlib import Path

import pandas as pd

_SCRIPTS = Path(__file__).resolve().parents[1]
for p in (str(_SCRIPTS), str(_SCRIPTS / "jqdata"), str(_SCRIPTS / "qdata")):
    if p not in sys.path:
        sys.path.insert(0, p)

from qdata_env import QDataClient  # noqa: E402

CODES = ["600519.SH", "000001.SZ", "000002.SZ", "600036.SH", "002415.SZ", "000651.SZ"]
FACTORS = ["roe_ttm", "roa_y", "eps_ttm", "npm_q", "asset_growth_qoq",
           "fixed_asset_turnover", "debt_asset_ratio", "quality_composite",
           "yoy_net_profit", "peg_252d", "roe_ttm_lag63d", "current_ratio"]


def main() -> int:
    cli = QDataClient()
    rows = []
    for f in FACTORS:
        for c in CODES:
            r = cli.factor_value(factor_name=f, ts_code=c,
                                 start_date="20260801", end_date="20260811")
            time.sleep(0.05)
            if not r:
                rows.append({"factor": f, "code": c, "n": 0})
                continue
            d = pd.DataFrame(r).drop_duplicates(subset=["trade_date"])
            d["trade_date"] = pd.to_datetime(d["trade_date"])
            s = d.set_index("trade_date")["factor_value"].astype(float)
            rows.append({"factor": f, "code": c, "n": len(s),
                         "first": s.iloc[0], "last": s.iloc[-1],
                         "min": s.min(), "max": s.max()})
        print(f"  … {f} done")
    df = pd.DataFrame(rows)
    with pd.option_context("display.width", 220):
        print(df.to_string(index=False))
    df.to_csv("output/qdata_factor_repro/_probe_qg.csv", index=False)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
