#!/usr/bin/env python3
"""Download frozen official SSE report PDFs and extract text for PIT audit."""

from __future__ import annotations

import hashlib
from pathlib import Path

import pandas as pd
import requests
from pypdf import PdfReader


HEADERS = {"User-Agent": "Mozilla/5.0", "Referer": "https://www.sse.com.cn/"}


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def main() -> None:
    root = Path(__file__).resolve().parents[2]
    audit_dir = root / "output/data_audits/a_share_financial_pit_v1/pilot"
    candidates = pd.read_csv(audit_dir / "sse_official_announcement_candidates.csv", dtype=str)
    source_dir = audit_dir / "official_sources/sse"
    source_dir.mkdir(parents=True, exist_ok=True)
    rows = []
    session = requests.Session()
    for _, item in candidates.iterrows():
        stem = f"{item.ts_code}_{item.end_date}"
        pdf_path = source_dir / f"{stem}.pdf"
        text_path = source_dir / f"{stem}.txt"
        response = session.get(item.official_pdf_url, headers=HEADERS, timeout=60)
        response.raise_for_status()
        content = response.content
        if not content.startswith(b"%PDF"):
            raise RuntimeError(f"official source is not a PDF: {item.official_pdf_url}")
        pdf_path.write_bytes(content)
        reader = PdfReader(pdf_path)
        text = "\n".join(page.extract_text() or "" for page in reader.pages)
        text_path.write_text(text, encoding="utf-8")
        rows.append({
            "ts_code": item.ts_code,
            "end_date": item.end_date,
            "official_date": item.official_date,
            "official_title": item.official_title,
            "official_pdf_url": item.official_pdf_url,
            "pdf_path": str(pdf_path.relative_to(audit_dir)),
            "text_path": str(text_path.relative_to(audit_dir)),
            "pdf_sha256": sha256_bytes(content),
            "pdf_bytes": len(content),
            "pages": len(reader.pages),
            "text_characters": len(text),
        })
    pd.DataFrame(rows).to_csv(audit_dir / "sse_official_pdf_manifest.csv", index=False)
    print(f"downloaded {len(rows)} official PDFs")


if __name__ == "__main__":
    main()
