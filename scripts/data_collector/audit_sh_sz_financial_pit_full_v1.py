#!/usr/bin/env python3
"""Create a read-only, aggregate audit for all financial PIT download batches.

The script never combines, changes, or derives financial values.  It verifies
the downloaded batch artifacts and writes only audit summaries.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pandas as pd


ENDPOINTS = ("income", "cashflow", "fina_indicator")
ANNOUNCEMENT_START = pd.Timestamp("2010-01-01")
ANNOUNCEMENT_END = pd.Timestamp("2025-06-30")
REPORT_START = pd.Timestamp("2009-12-31")
REPORT_END = pd.Timestamp("2024-12-31")


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


def main() -> None:
    root = Path(__file__).resolve().parents[2]
    full_root = root / "data/external/tushare/a_share_financial_pit_v1/full"
    raw_root = full_root / "raw"
    normalized_root = full_root / "normalized"
    manifests_root = full_root / "manifests"
    audit_root = root / "output/data_audits/a_share_financial_pit_v1/full"
    output = audit_root / "full_audit_v1"

    universe_frames = []
    batch_rows = []
    endpoint_rows = []
    integrity_rows = []
    errors = []
    anomaly_totals: dict[str, int] = {}
    total_requested = 0
    total_success = 0

    for number in range(1, 55):
        batch_id = f"batch_{number:04d}"
        raw_dir = raw_root / batch_id
        normalized_dir = normalized_root / batch_id
        batch_audit = audit_root / batch_id
        report_path = batch_audit / "batch_audit_report.txt"
        manifest_path = manifests_root / f"{batch_id}.json"
        report = report_path.read_text(encoding="utf-8") if report_path.is_file() else ""
        status = "batch_data_ready" if "status: batch_data_ready" in report else "missing_or_invalid"
        if status != "batch_data_ready":
            errors.append({"batch_id": batch_id, "check": "batch_status", "detail": status})

        universe_path = raw_dir / "universe_slice.csv.gz"
        if not universe_path.is_file():
            errors.append({"batch_id": batch_id, "check": "universe_slice", "detail": "missing"})
            universe = pd.DataFrame()
        else:
            universe = pd.read_csv(universe_path, compression="gzip", dtype=str)
            universe_frames.append(universe)

        request_path = raw_dir / "request_log.csv"
        if not request_path.is_file():
            logs = pd.DataFrame()
            errors.append({"batch_id": batch_id, "check": "request_log", "detail": "missing"})
        else:
            logs = pd.read_csv(request_path, dtype=str)
            total_requested += len(logs)
            successes = int(logs["status"].isin(["success", "no_data"]).sum()) if "status" in logs else 0
            total_success += successes
            if len(logs) != len(universe) * len(ENDPOINTS) or successes != len(logs):
                errors.append({"batch_id": batch_id, "check": "request_completeness", "detail": f"rows={len(logs)} success={successes} expected={len(universe) * len(ENDPOINTS)}"})

        manifest_ok = False
        manifest_files = 0
        if not manifest_path.is_file():
            errors.append({"batch_id": batch_id, "check": "manifest", "detail": "missing"})
        else:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            listed = manifest.get("files", {})
            manifest_files = len(listed)
            mismatches = []
            for relative, expected in listed.items():
                file_path = full_root / relative
                if not file_path.is_file():
                    mismatches.append(f"missing:{relative}")
                elif file_path.stat().st_size != expected.get("bytes") or sha256_file(file_path) != expected.get("sha256"):
                    mismatches.append(f"hash_or_size:{relative}")
            manifest_ok = not mismatches
            if mismatches:
                errors.append({"batch_id": batch_id, "check": "manifest_integrity", "detail": ";".join(mismatches[:5])})
        integrity_rows.append({"batch_id": batch_id, "manifest_files": manifest_files, "manifest_integrity_ok": manifest_ok})

        batch_rows.append({"batch_id": batch_id, "status": status, "companies": len(universe), "requests": len(logs), "successful_or_no_data": int(logs["status"].isin(["success", "no_data"]).sum()) if "status" in logs else 0})
        for endpoint in ENDPOINTS:
            path = normalized_dir / f"{endpoint}.csv.gz"
            if not path.is_file():
                errors.append({"batch_id": batch_id, "check": f"normalized_{endpoint}", "detail": "missing"})
                continue
            frame = pd.read_csv(path, compression="gzip", dtype=str)
            available = pd.to_datetime(frame.get("available_date"), errors="coerce")
            report_end = pd.to_datetime(frame.get("end_date"), errors="coerce")
            dates_ok = bool(available.between(ANNOUNCEMENT_START, ANNOUNCEMENT_END, inclusive="both").all() and report_end.between(REPORT_START, REPORT_END, inclusive="both").all())
            if not dates_ok:
                errors.append({"batch_id": batch_id, "check": f"pit_dates_{endpoint}", "detail": "out_of_scope_or_unparseable"})
            row = {"batch_id": batch_id, "endpoint": endpoint, "normalized_rows": len(frame), "pit_dates_valid": dates_ok}
            for field in {"income": ("total_revenue", "n_income"), "cashflow": ("n_cashflow_act",), "fina_indicator": ()}[endpoint]:
                row[f"{field}_coverage"] = float(frame[field].notna().mean()) if field in frame and len(frame) else 0.0
            endpoint_rows.append(row)

        anomaly_path = batch_audit / "anomaly_records.csv.gz"
        if anomaly_path.is_file():
            anomalies = pd.read_csv(anomaly_path, compression="gzip", dtype=str)
            for reason, count in anomalies.get("reason", pd.Series(dtype=str)).value_counts().items():
                anomaly_totals[str(reason)] = anomaly_totals.get(str(reason), 0) + int(count)

    universe_all = pd.concat(universe_frames, ignore_index=True) if universe_frames else pd.DataFrame()
    order = pd.to_numeric(universe_all.get("universe_order"), errors="coerce")
    universe_ok = len(universe_all) == 5385 and universe_all.get("ts_code", pd.Series(dtype=str)).nunique() == 5385 and order.notna().all() and sorted(order.astype(int).tolist()) == list(range(1, 5386))
    if not universe_ok:
        errors.append({"batch_id": "all", "check": "universe_coverage_and_order", "detail": f"rows={len(universe_all)} unique_codes={universe_all.get('ts_code', pd.Series(dtype=str)).nunique()}"})

    batches = pd.DataFrame(batch_rows)
    endpoints = pd.DataFrame(endpoint_rows)
    integrity = pd.DataFrame(integrity_rows)
    failures = pd.DataFrame(errors, columns=["batch_id", "check", "detail"])
    atomic_csv(batches, output / "batch_summary.csv")
    atomic_csv(endpoints, output / "endpoint_summary.csv")
    atomic_csv(integrity, output / "manifest_integrity_summary.csv")
    atomic_csv(failures, output / "audit_failures.csv")
    atomic_csv(universe_all, output / "frozen_universe_index.csv.gz")

    complete = len(batches) == 54 and (batches["status"] == "batch_data_ready").all() and total_requested == 5385 * 3 and total_success == total_requested and universe_ok and integrity["manifest_integrity_ok"].all() and failures.empty
    summary = {
        "audit_version": "v1",
        "scope": "read-only aggregation audit; no financial values were changed or derived",
        "batches": int(len(batches)),
        "companies": int(len(universe_all)),
        "requests": int(total_requested),
        "successful_or_no_data": int(total_success),
        "universe_coverage_and_order_ok": bool(universe_ok),
        "manifest_integrity_ok": bool(integrity["manifest_integrity_ok"].all()) if len(integrity) else False,
        "normalized_rows_by_endpoint": {endpoint: int(endpoints.loc[endpoints["endpoint"].eq(endpoint), "normalized_rows"].sum()) for endpoint in ENDPOINTS},
        "anomaly_rows_by_reason": anomaly_totals,
        "status": "full_data_ready" if complete else "full_audit_blocked",
    }
    atomic_json(summary, output / "full_audit_summary.json")
    (output / "full_audit_report.txt").write_text(
        "沪深普通 A 股财务 PIT 全量合并审计 v1\n"
        f"status: {summary['status']}\n"
        f"batches: {summary['batches']}/54; companies: {summary['companies']}/5385\n"
        f"requests: {summary['requests']}; successful_or_no_data: {summary['successful_or_no_data']}\n"
        f"frozen_universe_coverage_and_order_ok: {summary['universe_coverage_and_order_ok']}\n"
        f"manifest_integrity_ok: {summary['manifest_integrity_ok']}\n"
        "未合并或修改财务数据；未读取收益、未计算因子、未训练模型、未回测。\n",
        encoding="utf-8",
    )
    print(json.dumps(summary, ensure_ascii=False))
    if not complete:
        raise SystemExit("full audit blocked; inspect audit_failures.csv")


if __name__ == "__main__":
    main()
