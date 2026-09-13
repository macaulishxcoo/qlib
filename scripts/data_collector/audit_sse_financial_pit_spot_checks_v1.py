#!/usr/bin/env python3
"""Collect official SSE announcement metadata for frozen financial PIT checks."""

from __future__ import annotations

import json
from datetime import datetime, timedelta
from pathlib import Path

import pandas as pd
import requests


SSE_QUERY = "https://query.sse.com.cn/security/stock/queryCompanyBulletin.do"
SSE_PDF = "https://www.sse.com.cn"
HEADERS = {"User-Agent": "Mozilla/5.0", "Referer": "https://www.sse.com.cn/"}


def date_window(end_date: str) -> tuple[str, str]:
    report_end = pd.Timestamp(end_date)
    # Formal reports are ordinarily due no later than four months after period end.
    return (report_end.strftime("%Y-%m-%d"), (report_end + pd.Timedelta(days=160)).strftime("%Y-%m-%d"))


def expected_title_fragment(end_date: str) -> str:
    value = pd.Timestamp(end_date)
    suffix = {3: "第一季度报告", 6: "半年度报告", 9: "第三季度报告", 12: "年度报告"}[value.month]
    return f"{value.year}年{suffix}"


def main() -> None:
    root = Path(__file__).resolve().parents[2]
    audit_dir = root / "output/data_audits/a_share_financial_pit_v1/pilot"
    checks = pd.read_csv(audit_dir / "official_spot_check.csv", dtype=str)
    rows = []
    session = requests.Session()
    for _, check in checks[checks["ts_code"].str.endswith(".SH")].iterrows():
        start, end = date_window(check.end_date)
        params = {
            "isPagination": "true", "productId": check.ts_code[:6], "securityType": "0101",
            "reportType2": "DQGG", "beginDate": start, "endDate": end,
            "pageHelp.pageSize": "500", "pageHelp.pageNo": "1", "pageHelp.beginPage": "1", "pageHelp.cacheSize": "1",
        }
        response = session.get(SSE_QUERY, params=params, headers=HEADERS, timeout=30)
        response.raise_for_status()
        payload = response.json()
        for item in payload.get("pageHelp", {}).get("data", []):
            title = item.get("TITLE", "")
            expected = expected_title_fragment(check.end_date)
            # Exact period title only: do not mistake an abstract, a correction
            # to another period, or the following quarter for the target report.
            if expected in title and "摘要" not in title:
                rows.append({
                    "ts_code": check.ts_code,
                    "end_date": check.end_date,
                    "selection_group": check.selection_group,
                    "official_date": item.get("SSEDATE", ""),
                    "official_title": title,
                    "official_pdf_url": SSE_PDF + item.get("URL", ""),
                    "official_payload": json.dumps(item, ensure_ascii=False),
                })
    result = pd.DataFrame(rows)
    result.to_csv(audit_dir / "sse_official_announcement_candidates.csv", index=False)
    print(f"saved {len(result)} candidates")


if __name__ == "__main__":
    main()
