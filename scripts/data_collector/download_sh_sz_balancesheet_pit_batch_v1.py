#!/usr/bin/env python3
"""Download one auditable batch of historical Tushare balance-sheet PIT data.

This collector only stores and audits source financial statements.  It never
opens market prices, constructs a factor, or calculates a return label.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
import tushare as ts


ANNOUNCEMENT_START = pd.Timestamp("2010-01-01")
ANNOUNCEMENT_END = pd.Timestamp("2025-06-30")
REPORT_START = pd.Timestamp("2009-12-31")
REPORT_END = pd.Timestamp("2024-12-31")
ENDPOINT = "balancesheet"
CORE_FIELDS = ("accounts_receiv", "inventories", "total_assets", "total_liab", "total_cur_assets")
ALIGNMENT_KEYS = ("ts_code", "end_date", "report_type", "available_date")


def atomic_csv(frame: pd.DataFrame, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    frame.to_csv(temporary, index=False, compression="gzip" if path.suffix == ".gz" else None)
    os.replace(temporary, path)


def atomic_json(value: object, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(temporary, path)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def load_token() -> str:
    token = os.environ.get("TUSHARE_TOKEN", "").strip()
    if not token:
        token_path = Path("/root/.config/tushare/token")
        if token_path.is_file():
            token = token_path.read_text(encoding="utf-8").strip()
    if not token:
        raise SystemExit("TUSHARE_TOKEN is not configured")
    return token


def frozen_batch(root: Path, batch_number: int) -> pd.DataFrame:
    path = root / "data/external/tushare/a_share_financial_pit_v1/full/raw" / f"batch_{batch_number:04d}" / "universe_slice.csv.gz"
    if not path.is_file():
        raise SystemExit(f"missing frozen universe slice: {path}")
    batch = pd.read_csv(path, compression="gzip", dtype=str)
    if batch.empty or "ts_code" not in batch:
        raise SystemExit(f"invalid frozen universe slice: {path}")
    return batch


def normalize(raw: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    if raw.empty:
        return raw.copy(), pd.DataFrame(columns=["source_file", "source_row", "reason"])
    data = raw.copy()
    report = pd.to_datetime(data.get("end_date"), errors="coerce")
    available = pd.Series(pd.NaT, index=data.index, dtype="datetime64[ns]")
    if "f_ann_date" in data:
        final_ann = pd.to_datetime(data["f_ann_date"], errors="coerce")
        available = final_ann.where(final_ann.notna() & (final_ann >= report))
    if "ann_date" in data:
        announced = pd.to_datetime(data["ann_date"], errors="coerce")
        fallback = announced.where(announced.notna() & (announced >= report))
        available = available.where(available.notna(), fallback)
    announcement_ok = available.between(ANNOUNCEMENT_START, ANNOUNCEMENT_END, inclusive="both")
    report_ok = report.between(REPORT_START, REPORT_END, inclusive="both")
    keep = announcement_ok & report_ok
    details = data.loc[~keep, [col for col in ("source_file", "ts_code", "ann_date", "f_ann_date", "end_date") if col in data]].copy()
    details.insert(1, "source_row", details.index)
    reasons = []
    for index in details.index:
        if pd.isna(available.loc[index]):
            reasons.append("unparseable_or_pre_report_announcement_date")
        elif pd.isna(report.loc[index]):
            reasons.append("unparseable_report_end")
        elif not bool(announcement_ok.loc[index]):
            reasons.append("announcement_date_out_of_scope")
        else:
            reasons.append("report_end_out_of_scope")
    details["reason"] = reasons
    output = data.loc[keep].copy()
    output["available_date"] = available.loc[keep].dt.strftime("%Y-%m-%d")
    output["available_date_valid"] = True
    output["report_period_in_scope"] = True
    return output, details.reset_index(drop=True)


def call_endpoint(pro, ts_code: str, attempts: int, sleep_seconds: float) -> tuple[pd.DataFrame | None, dict[str, object]]:
    error = ""
    started = ""
    for attempt in range(1, attempts + 1):
        started = datetime.now(timezone.utc).isoformat()
        try:
            frame = pro.balancesheet(ts_code=ts_code)
            return frame, {"status": "no_data" if frame.empty else "success", "attempt": attempt, "request_started_at_utc": started, "error": ""}
        except Exception as exc:  # Tushare exception classes vary across releases.
            error = f"{type(exc).__name__}: {exc}"
            if attempt < attempts:
                time.sleep(sleep_seconds * attempt)
    return None, {"status": "error", "attempt": attempts, "request_started_at_utc": started, "error": error}


def recover_completed(raw_dir: Path, logs: pd.DataFrame) -> pd.DataFrame:
    recorded: set[str] = set()
    if not logs.empty and {"ts_code", "status"}.issubset(logs.columns):
        recorded = set(logs.loc[logs["status"].isin(["success", "no_data"]), "ts_code"].astype(str))
    recovered = []
    for path in sorted((raw_dir / ENDPOINT).glob("*.csv.gz")):
        code = path.name.removesuffix(".csv.gz")
        if code in recorded:
            continue
        frame = pd.read_csv(path, compression="gzip", dtype=str)
        request_time = str(frame["request_started_at_utc"].iloc[0]) if len(frame) and "request_started_at_utc" in frame else ""
        recovered.append({"ts_code": code, "endpoint": ENDPOINT, "status": "success", "attempt": "recovered", "request_started_at_utc": request_time, "error": "", "rows": len(frame), "raw_sha256": sha256_file(path)})
    return pd.concat([logs, pd.DataFrame(recovered)], ignore_index=True) if recovered else logs


def completed_codes(logs: pd.DataFrame) -> set[str]:
    """A later success resolves an earlier transient error for the same code."""
    if logs.empty or not {"ts_code", "status"}.issubset(logs.columns):
        return set()
    return set(logs.loc[logs["status"].isin(["success", "no_data"]), "ts_code"].astype(str))


def latest_request_statuses(logs: pd.DataFrame) -> pd.DataFrame:
    """Keep the final attempt per security for completion accounting."""
    if logs.empty or "ts_code" not in logs:
        return logs.copy()
    ordered = logs.copy()
    ordered["_sequence"] = range(len(ordered))
    return ordered.sort_values("_sequence", kind="mergesort").drop_duplicates("ts_code", keep="last").drop(columns="_sequence")


def same_day_conflicts(data: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    if data.empty:
        empty = pd.DataFrame(columns=[*ALIGNMENT_KEYS, "status"])
        return empty, empty
    keys = [key for key in ALIGNMENT_KEYS if key in data]
    duplicates = []
    conflicts = []
    for key, group in data.groupby(keys, dropna=False, sort=False):
        if len(group) < 2:
            continue
        values = group[[field for field in CORE_FIELDS if field in group]].fillna("<NA>").drop_duplicates()
        record = dict(zip(keys, key if isinstance(key, tuple) else (key,)))
        record["rows"] = len(group)
        if len(values) == 1:
            record["status"] = "same_day_exact_duplicate"
            duplicates.append(record)
        else:
            record["status"] = "same_day_value_conflict"
            conflicts.append(record)
    return pd.DataFrame(duplicates), pd.DataFrame(conflicts)


def income_alignment(root: Path, batch_id: str, balance: pd.DataFrame) -> pd.DataFrame:
    path = root / "data/external/tushare/a_share_financial_pit_v1/full/normalized" / batch_id / "income.csv.gz"
    if not path.is_file():
        return pd.DataFrame([{"balancesheet_keys": 0, "income_keys": 0, "aligned_keys": 0, "alignment_ratio_balancesheet": 0.0, "status": "income_file_missing"}])
    income = pd.read_csv(path, compression="gzip", dtype=str)
    keys = list(ALIGNMENT_KEYS)
    if not set(keys).issubset(balance.columns) or not set(keys).issubset(income.columns):
        return pd.DataFrame([{"balancesheet_keys": 0, "income_keys": 0, "aligned_keys": 0, "alignment_ratio_balancesheet": 0.0, "status": "alignment_keys_missing"}])
    left = balance[keys].drop_duplicates()
    right = income[keys].drop_duplicates()
    matched = left.merge(right, on=keys, how="inner")
    return pd.DataFrame([{"balancesheet_keys": len(left), "income_keys": len(right), "aligned_keys": len(matched), "alignment_ratio_balancesheet": len(matched) / len(left) if len(left) else 0.0, "status": "ok"}])


def write_batch_audit(root: Path, batch: pd.DataFrame, raw_dir: Path, normalized_dir: Path, audit_dir: Path, logs: pd.DataFrame) -> None:
    audit_dir.mkdir(parents=True, exist_ok=True)
    files = sorted((raw_dir / ENDPOINT).glob("*.csv.gz"))
    frames = []
    for path in files:
        frame = pd.read_csv(path, compression="gzip", dtype=str)
        frame["source_file"] = path.name
        frames.append(frame)
    raw = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()
    balance, anomalies = normalize(raw)
    atomic_csv(balance, normalized_dir / "balancesheet.csv.gz")
    atomic_csv(batch, audit_dir / "sample_or_universe_slice.csv")
    atomic_csv(logs, audit_dir / "request_log.csv")
    atomic_csv(anomalies, audit_dir / "anomaly_records.csv.gz")
    schema = {"endpoint": ENDPOINT, "raw_rows": len(raw), "normalized_rows": len(balance), "columns": raw.columns.tolist(), "required_fields": list(CORE_FIELDS)}
    atomic_json(schema, audit_dir / "schema_inventory.json")
    coverage = {"endpoint": ENDPOINT, "raw_rows": len(raw), "normalized_rows": len(balance)}
    for field in CORE_FIELDS:
        numeric = pd.to_numeric(balance[field], errors="coerce") if field in balance else pd.Series(dtype=float)
        coverage[f"{field}_present"] = field in balance
        coverage[f"{field}_coverage"] = float(numeric.notna().mean()) if len(balance) else 0.0
        coverage[f"{field}_zero_count"] = int(numeric.eq(0).sum())
        coverage[f"{field}_negative_count"] = int(numeric.lt(0).sum())
    atomic_csv(pd.DataFrame([coverage]), audit_dir / "field_coverage_summary.csv")
    available = pd.to_datetime(balance.get("available_date"), errors="coerce")
    report = pd.to_datetime(balance.get("end_date"), errors="coerce")
    atomic_csv(pd.DataFrame([{"normalized_rows": len(balance), "valid_available_dates": int(available.between(ANNOUNCEMENT_START, ANNOUNCEMENT_END, inclusive="both").sum()), "valid_report_ends": int(report.between(REPORT_START, REPORT_END, inclusive="both").sum()), "available_before_report_end": int(available.lt(report).sum())}]), audit_dir / "date_quality_summary.csv")
    duplicates, conflicts = same_day_conflicts(balance)
    atomic_csv(duplicates, audit_dir / "same_day_duplicate_audit.csv.gz")
    atomic_csv(conflicts, audit_dir / "same_day_value_conflict.csv.gz")
    atomic_csv(pd.DataFrame([{"duplicate_groups": len(duplicates), "conflict_groups": len(conflicts)}]), audit_dir / "version_quality_summary.csv")
    atomic_csv(income_alignment(root, raw_dir.name, balance), audit_dir / "income_alignment_summary.csv")
    final_logs = latest_request_statuses(logs)
    completed = len(final_logs) == len(batch) and final_logs.get("status", pd.Series(dtype=str)).isin(["success", "no_data"]).all()
    required_present = all(field in raw.columns for field in ("ts_code", "ann_date", "end_date", *CORE_FIELDS))
    status = "batch_data_ready" if completed and required_present else "batch_blocked"
    (audit_dir / "batch_audit_report.txt").write_text(
        "沪深普通 A 股资产负债表 PIT 批次审计 v1\n"
        f"status: {status}\ncompanies: {len(batch)}\nrequest_attempts: {len(logs)}; final_successful_or_no_data: {int(final_logs.get('status', pd.Series(dtype=str)).isin(['success', 'no_data']).sum())}\n"
        f"required_fields_present: {required_present}\nsame_day_value_conflicts: {len(conflicts)}\n"
        "未读取收益、未计算因子、未训练模型、未回测。\n",
        encoding="utf-8",
    )
    if status != "batch_data_ready":
        raise SystemExit(f"batch audit blocked: {audit_dir}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[2])
    parser.add_argument("--batch-number", type=int, default=1)
    parser.add_argument("--sleep-seconds", type=float, default=0.3)
    parser.add_argument("--attempts", type=int, default=3)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    if not 1 <= args.batch_number <= 54 or args.attempts < 1 or args.sleep_seconds < 0:
        raise SystemExit("invalid batch or request settings")
    root = args.root.resolve()
    batch = frozen_batch(root, args.batch_number)
    print(f"batch={args.batch_number:04d} companies={len(batch)} first={batch['ts_code'].iloc[0]} last={batch['ts_code'].iloc[-1]}")
    if args.dry_run:
        return
    batch_id = f"batch_{args.batch_number:04d}"
    data_root = root / "data/external/tushare/a_share_financial_pit_v1/balancesheet_v1"
    raw_dir = data_root / "raw" / batch_id
    normalized_dir = data_root / "normalized" / batch_id
    audit_dir = root / "output/data_audits/a_share_financial_pit_v1/balancesheet_v1" / batch_id
    log_path = raw_dir / "request_log.csv"
    logs = pd.read_csv(log_path, dtype=str) if log_path.is_file() else pd.DataFrame()
    if not (raw_dir / "universe_slice.csv.gz").exists():
        atomic_csv(batch, raw_dir / "universe_slice.csv.gz")
    logs = recover_completed(raw_dir, logs)
    atomic_csv(logs, log_path)
    pro = ts.pro_api(load_token())
    new_logs = []
    for code in batch["ts_code"].astype(str):
        done = code in completed_codes(logs)
        target = raw_dir / ENDPOINT / f"{code}.csv.gz"
        if target.exists() and done:
            continue
        frame, meta = call_endpoint(pro, code, args.attempts, args.sleep_seconds)
        if frame is None:
            new_logs.append({"ts_code": code, "endpoint": ENDPOINT, **meta, "rows": 0})
            atomic_csv(pd.concat([logs, pd.DataFrame(new_logs)], ignore_index=True), log_path)
            raise SystemExit(f"blocked at {code}: {meta['error']}")
        frame = frame.copy()
        frame["requested_ts_code"] = code
        frame["request_started_at_utc"] = meta["request_started_at_utc"]
        frame["source_endpoint"] = ENDPOINT
        frame["batch_id"] = batch_id
        atomic_csv(frame, target)
        new_logs.append({"ts_code": code, "endpoint": ENDPOINT, **meta, "rows": len(frame), "raw_sha256": sha256_file(target)})
        print(f"{code}: {meta['status']} rows={len(frame)}", flush=True)
        time.sleep(args.sleep_seconds)
    logs = pd.concat([logs, pd.DataFrame(new_logs)], ignore_index=True) if new_logs else logs
    atomic_csv(logs, log_path)
    write_batch_audit(root, batch, raw_dir, normalized_dir, audit_dir, logs)
    files = {str(path.relative_to(data_root)): {"bytes": path.stat().st_size, "sha256": sha256_file(path)} for path in sorted(raw_dir.rglob("*")) if path.is_file()}
    atomic_json({"batch_id": batch_id, "endpoint": ENDPOINT, "companies": len(batch), "files": files}, data_root / "manifests" / f"{batch_id}.json")
    print(f"completed {batch_id}; audit={audit_dir}")


if __name__ == "__main__":
    main()
