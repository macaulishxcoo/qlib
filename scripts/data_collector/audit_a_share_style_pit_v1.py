#!/usr/bin/env python3
"""Audit monthly PIT industry and free-float-size control data without signals."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pandas as pd


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def atomic_csv(frame: pd.DataFrame, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp")
    frame.to_csv(temporary, index=False, compression="gzip" if path.suffix == ".gz" else None)
    temporary.replace(path)


def main() -> None:
    root = Path(__file__).resolve().parents[2]
    data_root = root / "data/external/tushare/a_share_style_pit_v1"
    normalized = data_root / "normalized"
    raw_daily = data_root / "raw/daily_basic"
    audit = root / "output/data_audits/a_share_style_pit_v1"
    grid = pd.read_csv(normalized / "monthly_rebalance_grid.csv.gz", compression="gzip", dtype=str)
    size = pd.read_csv(normalized / "monthly_free_float_size.csv.gz", compression="gzip", dtype=str)
    industry = pd.read_csv(normalized / "industry_l1_effective_intervals.csv.gz", compression="gzip", dtype=str)
    universe = pd.read_csv(root / "output/data_audits/a_share_financial_pit_v1/full/full_audit_v1/frozen_universe_index.csv.gz", compression="gzip", dtype=str)
    snapshot = pd.read_csv(root / "data/external/tushare/a_share_financial_pit_v1/full/raw/batch_0001/stock_basic_snapshot.csv.gz", compression="gzip", dtype=str)
    snapshot = snapshot[snapshot["ts_code"].isin(set(universe["ts_code"]))].copy()
    snapshot["list_date"] = pd.to_datetime(snapshot["list_date"], errors="coerce")
    snapshot["delist_date"] = pd.to_datetime(snapshot["delist_date"], errors="coerce")
    industry["in_date"] = pd.to_datetime(industry.get("in_date"), errors="coerce")
    industry["out_date"] = pd.to_datetime(industry.get("out_date"), errors="coerce")
    size["asof_date"] = pd.to_datetime(size["asof_date"], errors="coerce")
    size["close_num"] = pd.to_numeric(size.get("close"), errors="coerce")
    size["free_share_num"] = pd.to_numeric(size.get("free_share"), errors="coerce")
    size["free_float_market_value_num"] = pd.to_numeric(size.get("free_float_market_value"), errors="coerce")
    errors = []
    industry_rows, size_rows, join_rows, anomalies = [], [], [], []
    for _, date_row in grid.iterrows():
        asof = pd.Timestamp(date_row.asof_date)
        active = snapshot[snapshot["list_date"].le(asof) & (snapshot["delist_date"].isna() | snapshot["delist_date"].gt(asof))]
        codes = set(active["ts_code"])
        month_size = size[size["asof_date"].eq(asof) & size["ts_code"].isin(codes)]
        valid_size = month_size[month_size["close_num"].gt(0) & month_size["free_share_num"].gt(0) & month_size["free_float_market_value_num"].gt(0)]
        effective = industry[industry["ts_code"].isin(codes) & industry["in_date"].le(asof) & (industry["out_date"].isna() | industry["out_date"].ge(asof))]
        counts = effective.groupby("ts_code").size()
        valid_industry = set(counts[counts.eq(1)].index)
        overlap = set(counts[counts.gt(1)].index)
        missing = codes - set(counts.index)
        industry_rows.append({"asof_date": date_row.asof_date, "active_companies": len(codes), "valid_industry": len(valid_industry), "industry_coverage": len(valid_industry) / len(codes) if codes else 0.0, "industry_ambiguous": len(overlap), "industry_missing": len(missing)})
        size_rows.append({"asof_date": date_row.asof_date, "active_companies": len(codes), "daily_basic_rows": len(month_size), "valid_free_float_size": len(valid_size), "size_coverage": len(valid_size) / len(codes) if codes else 0.0, "close_positive": int(month_size["close_num"].gt(0).sum()), "free_share_positive": int(month_size["free_share_num"].gt(0).sum()), "free_float_market_value_p01": valid_size["free_float_market_value_num"].quantile(.01) if len(valid_size) else None, "free_float_market_value_p50": valid_size["free_float_market_value_num"].quantile(.50) if len(valid_size) else None, "free_float_market_value_p99": valid_size["free_float_market_value_num"].quantile(.99) if len(valid_size) else None})
        complete = valid_industry & set(valid_size["ts_code"])
        join_rows.append({"asof_date": date_row.asof_date, "active_companies": len(codes), "complete_industry_and_size": len(complete), "complete_case_coverage": len(complete) / len(codes) if codes else 0.0})
        for code in sorted(overlap): anomalies.append({"asof_date": date_row.asof_date, "ts_code": code, "reason": "industry_ambiguous"})
        for code in sorted(missing): anomalies.append({"asof_date": date_row.asof_date, "ts_code": code, "reason": "industry_missing"})
        for code in sorted(codes - set(valid_size["ts_code"])): anomalies.append({"asof_date": date_row.asof_date, "ts_code": code, "reason": "free_float_size_missing_or_nonpositive"})
    industry_summary, size_summary, join_summary = pd.DataFrame(industry_rows), pd.DataFrame(size_rows), pd.DataFrame(join_rows)
    if len(grid) != 138: errors.append({"check": "grid", "detail": f"months={len(grid)} expected=138"})
    raw_missing = [date for date in grid["asof_date"] if not (raw_daily / f"{date}.csv.gz").is_file()]
    if raw_missing: errors.append({"check": "raw_daily", "detail": f"missing={len(raw_missing)}"})
    if (industry_summary["industry_ambiguous"] > 0).any(): errors.append({"check": "industry_overlap", "detail": f"months={(industry_summary['industry_ambiguous'] > 0).sum()}"})
    manifest_path = data_root / "manifests/manifest.json"
    manifest_ok = manifest_path.is_file()
    if manifest_ok:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        for relative, expected in manifest.get("files", {}).items():
            path = data_root / relative
            if not path.is_file() or path.stat().st_size != expected["bytes"] or sha256_file(path) != expected["sha256"]:
                manifest_ok = False
                break
    if not manifest_ok: errors.append({"check": "manifest", "detail": "missing_or_hash_mismatch"})
    atomic_csv(industry_summary, audit / "industry_coverage_by_month.csv")
    atomic_csv(size_summary, audit / "size_coverage_by_month.csv")
    atomic_csv(join_summary, audit / "universe_join_coverage.csv")
    atomic_csv(size_summary[["asof_date", "close_positive", "free_share_positive", "free_float_market_value_p01", "free_float_market_value_p50", "free_float_market_value_p99"]], audit / "size_field_quality.csv")
    atomic_csv(pd.DataFrame(anomalies, columns=["asof_date", "ts_code", "reason"]), audit / "industry_overlap_or_gap.csv.gz")
    atomic_csv(pd.DataFrame(errors, columns=["check", "detail"]), audit / "anomaly_records.csv.gz")
    status = "style_data_ready" if not errors else "style_data_blocked"
    (audit / "data_audit_report.txt").write_text(
        "沪深 A 股行业与自由流通市值 PIT 数据审计 v1\n"
        f"status: {status}\n"
        f"months: {len(grid)}/138; raw_daily_files: {138 - len(raw_missing)}/138\n"
        f"industry_rows: {len(industry)}; monthly_size_rows: {len(size)}\n"
        f"minimum_complete_case_coverage: {join_summary['complete_case_coverage'].min():.4f}\n"
        "未计算财务信号、未读取收益、未训练模型、未回测。\n",
        encoding="utf-8",
    )
    print((audit / "data_audit_report.txt").read_text(encoding="utf-8"), end="")
    if errors: raise SystemExit("style data audit blocked; inspect anomaly_records.csv.gz")


if __name__ == "__main__":
    main()
