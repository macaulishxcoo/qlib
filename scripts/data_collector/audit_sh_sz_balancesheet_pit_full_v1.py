#!/usr/bin/env python3
"""Run a read-only aggregate audit for balance-sheet PIT download batches."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pandas as pd


ANNOUNCEMENT_START = pd.Timestamp("2010-01-01")
ANNOUNCEMENT_END = pd.Timestamp("2025-06-30")
REPORT_START = pd.Timestamp("2009-12-31")
REPORT_END = pd.Timestamp("2024-12-31")
ENDPOINT = "balancesheet"
CORE_FIELDS = ("accounts_receiv", "inventories", "total_assets", "total_liab", "total_cur_assets")
KEYS = ("ts_code", "end_date", "report_type", "available_date")


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


def atomic_json(value: object, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


def final_logs(logs: pd.DataFrame) -> pd.DataFrame:
    if logs.empty or "ts_code" not in logs:
        return logs.copy()
    out = logs.copy()
    out["_sequence"] = range(len(out))
    return out.sort_values("_sequence", kind="mergesort").drop_duplicates("ts_code", keep="last").drop(columns="_sequence")


def main() -> None:
    root = Path(__file__).resolve().parents[2]
    data_root = root / "data/external/tushare/a_share_financial_pit_v1/balancesheet_v1"
    base_root = root / "data/external/tushare/a_share_financial_pit_v1/full"
    audit_root = root / "output/data_audits/a_share_financial_pit_v1/balancesheet_v1"
    output = audit_root / "full_audit_v1"
    batch_rows, field_rows, alignment_rows, integrity_rows, failures = [], [], [], [], []
    universe_parts = []
    total_final_requests = 0
    total_final_successes = 0
    normalized_totals = 0

    for number in range(1, 55):
        batch_id = f"batch_{number:04d}"
        raw_dir = data_root / "raw" / batch_id
        normalized_path = data_root / "normalized" / batch_id / "balancesheet.csv.gz"
        audit_dir = audit_root / batch_id
        report_path = audit_dir / "batch_audit_report.txt"
        manifest_path = data_root / "manifests" / f"{batch_id}.json"
        report = report_path.read_text(encoding="utf-8") if report_path.is_file() else ""
        ready = "status: batch_data_ready" in report
        if not ready:
            failures.append({"batch_id": batch_id, "check": "batch_status", "detail": "missing_or_invalid"})
        universe_path = raw_dir / "universe_slice.csv.gz"
        if universe_path.is_file():
            universe = pd.read_csv(universe_path, compression="gzip", dtype=str)
            universe_parts.append(universe)
        else:
            universe = pd.DataFrame()
            failures.append({"batch_id": batch_id, "check": "universe_slice", "detail": "missing"})
        log_path = raw_dir / "request_log.csv"
        if log_path.is_file():
            logs = final_logs(pd.read_csv(log_path, dtype=str))
        else:
            logs = pd.DataFrame()
            failures.append({"batch_id": batch_id, "check": "request_log", "detail": "missing"})
        successful = int(logs.get("status", pd.Series(dtype=str)).isin(["success", "no_data"]).sum())
        total_final_requests += len(logs)
        total_final_successes += successful
        if len(logs) != len(universe) or successful != len(logs):
            failures.append({"batch_id": batch_id, "check": "final_request_completeness", "detail": f"final={len(logs)} success={successful} expected={len(universe)}"})

        manifest_ok, manifest_files = False, 0
        if manifest_path.is_file():
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            listed = manifest.get("files", {})
            manifest_files = len(listed)
            mismatches = []
            for relative, expected in listed.items():
                candidate = data_root / relative
                if not candidate.is_file():
                    mismatches.append(f"missing:{relative}")
                elif candidate.stat().st_size != expected.get("bytes") or sha256_file(candidate) != expected.get("sha256"):
                    mismatches.append(f"hash_or_size:{relative}")
            manifest_ok = not mismatches
            if mismatches:
                failures.append({"batch_id": batch_id, "check": "manifest_integrity", "detail": ";".join(mismatches[:5])})
        else:
            failures.append({"batch_id": batch_id, "check": "manifest", "detail": "missing"})
        integrity_rows.append({"batch_id": batch_id, "manifest_files": manifest_files, "manifest_integrity_ok": manifest_ok})

        if not normalized_path.is_file():
            balance = pd.DataFrame()
            failures.append({"batch_id": batch_id, "check": "normalized_balancesheet", "detail": "missing"})
        else:
            balance = pd.read_csv(normalized_path, compression="gzip", dtype=str)
            normalized_totals += len(balance)
            available = pd.to_datetime(balance.get("available_date"), errors="coerce")
            report_end = pd.to_datetime(balance.get("end_date"), errors="coerce")
            dates_ok = bool(available.between(ANNOUNCEMENT_START, ANNOUNCEMENT_END, inclusive="both").all() and report_end.between(REPORT_START, REPORT_END, inclusive="both").all())
            if not dates_ok:
                failures.append({"batch_id": batch_id, "check": "pit_dates", "detail": "out_of_scope_or_unparseable"})
            record = {"batch_id": batch_id, "normalized_rows": len(balance), "pit_dates_valid": dates_ok}
            for field in CORE_FIELDS:
                record[f"{field}_coverage"] = float(balance[field].notna().mean()) if field in balance and len(balance) else 0.0
            field_rows.append(record)

        alignment_path = audit_dir / "income_alignment_summary.csv"
        if alignment_path.is_file():
            summary = pd.read_csv(alignment_path, dtype=str)
            if len(summary):
                item = summary.iloc[0].to_dict()
                item["batch_id"] = batch_id
                alignment_rows.append(item)
        else:
            failures.append({"batch_id": batch_id, "check": "income_alignment_summary", "detail": "missing"})
        batch_rows.append({"batch_id": batch_id, "status": "batch_data_ready" if ready else "missing_or_invalid", "companies": len(universe), "final_requests": len(logs), "final_successful_or_no_data": successful})

    universe_all = pd.concat(universe_parts, ignore_index=True) if universe_parts else pd.DataFrame()
    base_universe_path = base_root / "raw/batch_0001/stock_basic_snapshot.csv.gz"
    order = pd.to_numeric(universe_all.get("universe_order"), errors="coerce")
    universe_ok = len(universe_all) == 5385 and universe_all.get("ts_code", pd.Series(dtype=str)).nunique() == 5385 and order.notna().all() and sorted(order.astype(int).tolist()) == list(range(1, 5386))
    if not universe_ok:
        failures.append({"batch_id": "all", "check": "frozen_universe_coverage_and_order", "detail": f"rows={len(universe_all)} unique={universe_all.get('ts_code', pd.Series(dtype=str)).nunique()}"})
    if base_universe_path.is_file():
        frozen_codes = pd.read_csv(base_universe_path, compression="gzip", dtype=str)
        expected = set(frozen_codes.loc[frozen_codes.get("ts_code", pd.Series(dtype=str)).isin(universe_all.get("ts_code", pd.Series(dtype=str))), "ts_code"])
        if set(universe_all.get("ts_code", pd.Series(dtype=str))) != expected:
            failures.append({"batch_id": "all", "check": "base_universe_match", "detail": "balancesheet universe differs from frozen base snapshot"})

    batches = pd.DataFrame(batch_rows)
    fields = pd.DataFrame(field_rows)
    alignment = pd.DataFrame(alignment_rows)
    integrity = pd.DataFrame(integrity_rows)
    failure_frame = pd.DataFrame(failures, columns=["batch_id", "check", "detail"])
    atomic_csv(batches, output / "batch_summary.csv")
    atomic_csv(fields, output / "field_coverage_summary.csv")
    atomic_csv(alignment, output / "income_alignment_summary.csv")
    atomic_csv(integrity, output / "manifest_integrity_summary.csv")
    atomic_csv(failure_frame, output / "audit_failures.csv")
    atomic_csv(universe_all, output / "frozen_universe_index.csv.gz")
    complete = len(batches) == 54 and (batches["status"] == "batch_data_ready").all() and total_final_requests == 5385 and total_final_successes == 5385 and universe_ok and integrity["manifest_integrity_ok"].all() and failure_frame.empty
    summary = {"audit_version": "v1", "scope": "read-only aggregation audit; no factors, labels, prices, or returns were read", "batches": int(len(batches)), "companies": int(len(universe_all)), "final_requests": int(total_final_requests), "final_successful_or_no_data": int(total_final_successes), "normalized_rows": int(normalized_totals), "frozen_universe_coverage_and_order_ok": bool(universe_ok), "manifest_integrity_ok": bool(integrity["manifest_integrity_ok"].all()) if len(integrity) else False, "status": "balancesheet_data_ready" if complete else "full_audit_blocked"}
    atomic_json(summary, output / "full_audit_summary.json")
    (output / "full_audit_report.txt").write_text(
        "沪深普通 A 股资产负债表 PIT 全量合并审计 v1\n"
        f"status: {summary['status']}\nbatches: {summary['batches']}/54; companies: {summary['companies']}/5385\n"
        f"final_requests: {summary['final_requests']}; final_successful_or_no_data: {summary['final_successful_or_no_data']}\n"
        f"normalized_rows: {summary['normalized_rows']}\nfrozen_universe_coverage_and_order_ok: {summary['frozen_universe_coverage_and_order_ok']}\nmanifest_integrity_ok: {summary['manifest_integrity_ok']}\n"
        "未读取价格或收益；未计算因子；未训练模型；未回测。\n",
        encoding="utf-8",
    )
    print(json.dumps(summary, ensure_ascii=False))
    if not complete:
        raise SystemExit("full audit blocked; inspect audit_failures.csv")


if __name__ == "__main__":
    main()
