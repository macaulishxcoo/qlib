#!/usr/bin/env python3
"""Collect one auditable batch of Shanghai/Shenzhen financial PIT data.

The collector stores complete Tushare responses in the raw layer.  It neither
reads market returns nor calculates factors, labels, models, or backtests.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import time
from datetime import datetime, timezone
from itertools import zip_longest
from pathlib import Path

import pandas as pd
import tushare as ts


ENDPOINTS = ("income", "cashflow", "fina_indicator")
ANNOUNCEMENT_START = pd.Timestamp("2010-01-01")
ANNOUNCEMENT_END = pd.Timestamp("2025-06-30")
REPORT_START = pd.Timestamp("2009-12-31")
REPORT_END = pd.Timestamp("2024-12-31")
SPOT_SEED = "sh_sz_financial_pit_full_spot_check_v1"
PREFIXES = {
    "SSE": ("600", "601", "603", "605", "688"),
    "SZSE": ("000", "001", "002", "003", "300", "301"),
}


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
        path = Path("/root/.config/tushare/token")
        if path.is_file():
            token = path.read_text(encoding="utf-8").strip()
    if not token:
        raise SystemExit("TUSHARE_TOKEN is not configured")
    return token


def fetch_stock_basic(pro) -> pd.DataFrame:
    parts = []
    fields = "ts_code,symbol,name,area,industry,market,list_date,delist_date,list_status,exchange,is_hs"
    for status in ("L", "D"):
        frame = pro.stock_basic(list_status=status, fields=fields).copy()
        frame["requested_list_status"] = status
        parts.append(frame)
    return pd.concat(parts, ignore_index=True).drop_duplicates().reset_index(drop=True)


def classify_universe(stock_basic: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    rows = []
    excluded = []
    for _, row in stock_basic.iterrows():
        code = str(row.get("ts_code", ""))
        exchange = str(row.get("exchange", ""))
        status = str(row.get("list_status", ""))
        reason = ""
        if status not in {"L", "D"}:
            reason = "unsupported_list_status"
        elif exchange not in PREFIXES:
            reason = "outside_sh_sz_exchange"
        elif not re.fullmatch(r"\d{6}\.(SH|SZ)", code):
            reason = "not_sh_sz_six_digit_code"
        elif not code.startswith(PREFIXES[exchange]):
            reason = "outside_common_a_code_prefix"
        elif (exchange == "SSE" and not code.endswith(".SH")) or (exchange == "SZSE" and not code.endswith(".SZ")):
            reason = "exchange_code_suffix_mismatch"
        else:
            list_date = pd.to_datetime(row.get("list_date"), errors="coerce")
            delist_date = pd.to_datetime(row.get("delist_date"), errors="coerce")
            if pd.isna(list_date) or list_date > ANNOUNCEMENT_END:
                reason = "outside_announcement_window_by_list_date"
            elif status == "D" and (pd.isna(delist_date) or delist_date < ANNOUNCEMENT_START):
                reason = "outside_announcement_window_by_delist_date"
        if reason:
            item = row.to_dict()
            item["exclusion_reason"] = reason
            excluded.append(item)
        else:
            rows.append(row.to_dict())
    selected = pd.DataFrame(rows)
    excluded_frame = pd.DataFrame(excluded)
    return selected, excluded_frame


def interleaved_order(universe: pd.DataFrame) -> pd.DataFrame:
    groups = {
        exchange: universe[universe["exchange"].eq(exchange)].sort_values("ts_code", kind="mergesort").to_dict("records")
        for exchange in ("SSE", "SZSE")
    }
    ordered = []
    for sh_row, sz_row in zip_longest(groups["SSE"], groups["SZSE"]):
        if sh_row is not None:
            ordered.append(sh_row)
        if sz_row is not None:
            ordered.append(sz_row)
    output = pd.DataFrame(ordered)
    output.insert(0, "universe_order", range(1, len(output) + 1))
    return output


def batch_slice(ordered: pd.DataFrame, batch_number: int, batch_size: int) -> pd.DataFrame:
    start = (batch_number - 1) * batch_size
    batch = ordered.iloc[start : start + batch_size].copy()
    batch.insert(1, "batch_number", batch_number)
    if batch.empty:
        raise SystemExit(f"batch {batch_number} is outside the selected universe")
    return batch


def filter_for_normalized(raw: pd.DataFrame, endpoint: str) -> tuple[pd.DataFrame, pd.DataFrame]:
    if raw.empty:
        return raw, pd.DataFrame(columns=["endpoint", "source_file", "source_row", "reason"])
    data = raw.copy()
    ann = pd.Series(pd.NaT, index=data.index, dtype="datetime64[ns]")
    report = pd.to_datetime(data.get("end_date"), errors="coerce")
    if "f_ann_date" in data:
        f_ann = pd.to_datetime(data["f_ann_date"], errors="coerce")
        ann = f_ann.where(f_ann.notna() & (f_ann >= report))
    if "ann_date" in data:
        fallback = pd.to_datetime(data["ann_date"], errors="coerce")
        ann = ann.where(ann.notna(), fallback.where(fallback.notna() & (fallback >= report)))
    ann_ok = ann.between(ANNOUNCEMENT_START, ANNOUNCEMENT_END, inclusive="both")
    report_ok = report.between(REPORT_START, REPORT_END, inclusive="both")
    keep = ann_ok & report_ok
    anomalies = data.loc[~keep, [c for c in ["source_file", "ts_code", "ann_date", "f_ann_date", "end_date"] if c in data]].copy()
    anomalies.insert(0, "endpoint", endpoint)
    anomalies.insert(2, "source_row", anomalies.index)
    reasons = []
    for index in anomalies.index:
        source_index = index
        if pd.isna(ann.loc[source_index]):
            reasons.append("unparseable_announcement_date")
        elif pd.isna(report.loc[source_index]):
            reasons.append("unparseable_report_end")
        elif not ann_ok.loc[source_index]:
            reasons.append("announcement_date_out_of_scope")
        else:
            reasons.append("report_end_out_of_scope")
    anomalies["reason"] = reasons
    normalized = data.loc[keep].copy()
    normalized["available_date"] = ann.loc[keep].dt.strftime("%Y-%m-%d")
    normalized["available_date_valid"] = True
    normalized["report_period_in_scope"] = True
    return normalized, anomalies


def call_endpoint(pro, endpoint: str, ts_code: str, attempts: int, sleep_seconds: float) -> tuple[pd.DataFrame | None, dict]:
    error = ""
    for attempt in range(1, attempts + 1):
        started = datetime.now(timezone.utc).isoformat()
        try:
            frame = getattr(pro, endpoint)(ts_code=ts_code)
            status = "no_data" if frame.empty else "success"
            return frame, {"status": status, "attempt": attempt, "request_started_at_utc": started, "error": ""}
        except Exception as exc:  # API-specific exception types are not stable across tushare releases.
            error = f"{type(exc).__name__}: {exc}"
            if attempt < attempts:
                time.sleep(sleep_seconds * attempt)
    return None, {"status": "error", "attempt": attempts, "request_started_at_utc": started, "error": error}


def recover_completed_raw_files(raw_dir: Path, logs: pd.DataFrame) -> pd.DataFrame:
    """Rebuild missing request-log entries after an interrupted process.

    Raw files are atomically written, so an existing file is a completed response
    even if the process stopped before its batched log flush.  Recovery avoids
    re-requesting or overwriting that immutable response on restart.
    """
    recorded = set()
    if not logs.empty and {"ts_code", "endpoint", "status"}.issubset(logs.columns):
        recorded = set(
            zip(
                logs.loc[logs["status"].isin(["success", "no_data"]), "ts_code"],
                logs.loc[logs["status"].isin(["success", "no_data"]), "endpoint"],
            )
        )
    recovered = []
    for endpoint in ENDPOINTS:
        for file_path in sorted((raw_dir / endpoint).glob("*.csv.gz")):
            ts_code = file_path.name.removesuffix(".csv.gz")
            if (ts_code, endpoint) in recorded:
                continue
            frame = pd.read_csv(file_path, compression="gzip", dtype=str)
            request_time = ""
            if "request_started_at_utc" in frame and not frame.empty:
                request_time = str(frame["request_started_at_utc"].iloc[0])
            recovered.append(
                {
                    "ts_code": ts_code,
                    "endpoint": endpoint,
                    "status": "success",
                    "attempt": "recovered",
                    "request_started_at_utc": request_time,
                    "error": "",
                    "rows": len(frame),
                    "raw_sha256": sha256_file(file_path),
                }
            )
    if not recovered:
        return logs
    return pd.concat([logs, pd.DataFrame(recovered)], ignore_index=True)


def write_batch_audit(batch: pd.DataFrame, raw_dir: Path, normalized_dir: Path, audit_dir: Path, logs: pd.DataFrame) -> None:
    audit_dir.mkdir(parents=True, exist_ok=True)
    atomic_csv(batch, audit_dir / "sample_or_universe_slice.csv")
    atomic_csv(logs, audit_dir / "request_log.csv")
    summaries = []
    versions = []
    anomalies = []
    schema = {}
    normalized = {}
    for endpoint in ENDPOINTS:
        frames = []
        for file_path in sorted((raw_dir / endpoint).glob("*.csv.gz")):
            frame = pd.read_csv(file_path, compression="gzip", dtype=str)
            frame["source_file"] = file_path.name
            frames.append(frame)
        raw = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()
        output, endpoint_anomalies = filter_for_normalized(raw, endpoint)
        atomic_csv(output, normalized_dir / f"{endpoint}.csv.gz")
        normalized[endpoint] = output
        anomalies.append(endpoint_anomalies)
        schema[endpoint] = {"raw_rows": len(raw), "normalized_rows": len(output), "columns": raw.columns.tolist()}
        core = {"income": ("total_revenue", "n_income"), "cashflow": ("n_cashflow_act",), "fina_indicator": ()}[endpoint]
        record = {"endpoint": endpoint, "raw_rows": len(raw), "normalized_rows": len(output)}
        for field in core:
            record[f"{field}_coverage"] = float(output[field].notna().mean()) if field in output and len(output) else 0.0
        summaries.append(record)
        keys = [field for field in ("ts_code", "end_date", "report_type") if field in output]
        counts = output.groupby(keys, dropna=False).size() if keys and len(output) else pd.Series(dtype=int)
        versions.append({"endpoint": endpoint, "key_groups": len(counts), "duplicate_key_groups": int((counts > 1).sum()) if len(counts) else 0, "max_versions": int(counts.max()) if len(counts) else 0})
    atomic_json(schema, audit_dir / "schema_inventory.json")
    atomic_csv(pd.DataFrame(summaries), audit_dir / "field_coverage_summary.csv")
    atomic_csv(pd.DataFrame(versions), audit_dir / "version_quality_summary.csv")
    anomaly_frame = pd.concat(anomalies, ignore_index=True) if anomalies else pd.DataFrame()
    atomic_csv(anomaly_frame, audit_dir / "anomaly_records.csv.gz")
    date_rows = []
    for endpoint, frame in normalized.items():
        date_rows.append({"endpoint": endpoint, "normalized_rows": len(frame), "valid_available_dates": int(frame.get("available_date_valid", pd.Series(dtype=bool)).sum())})
    atomic_csv(pd.DataFrame(date_rows), audit_dir / "date_quality_summary.csv")
    inc, cf = normalized["income"], normalized["cashflow"]
    keys = [field for field in ("ts_code", "end_date", "report_type", "available_date") if field in inc and field in cf]
    left = inc[keys].drop_duplicates() if keys else pd.DataFrame()
    right = cf[keys].drop_duplicates() if keys else pd.DataFrame()
    aligned = left.merge(right, on=keys, how="inner") if keys else pd.DataFrame()
    atomic_csv(pd.DataFrame([{"income_keys": len(left), "cashflow_keys": len(right), "aligned_keys": len(aligned), "alignment_ratio_income": len(aligned) / len(left) if len(left) else 0.0}]), audit_dir / "three_statement_alignment_summary.csv")
    candidates = pd.concat([frame[["ts_code", "end_date"]] for frame in normalized.values() if {"ts_code", "end_date"}.issubset(frame.columns)], ignore_index=True).drop_duplicates()
    if len(candidates):
        candidates["_hash"] = candidates.apply(lambda row: hashlib.sha256(f"{SPOT_SEED}|{row.ts_code}|{row.end_date}".encode()).hexdigest(), axis=1)
        checks = candidates.sort_values(["_hash", "ts_code", "end_date"]).head(8).drop(columns="_hash")
    else:
        checks = pd.DataFrame(columns=["ts_code", "end_date"])
    for column in ("official_source_url", "checked_at_utc"):
        checks[column] = ""
    for column in ("date_match", "amount_match", "revision_checked"):
        checks[column] = "not_required"
    checks["notes"] = "Retained for targeted investigation if a concrete data discrepancy is found."
    atomic_csv(checks, audit_dir / "official_spot_check.csv")
    successful = logs["status"].isin(["success", "no_data"]).all() if len(logs) else False
    status = "batch_data_ready" if successful else "batch_blocked"
    (audit_dir / "batch_audit_report.txt").write_text(
        "沪深普通 A 股财务 PIT 批次审计 v1\n"
        f"status: {status}\n"
        f"companies: {len(batch)}\n"
        f"requests: {len(logs)}; successful_or_no_data: {int(logs['status'].isin(['success', 'no_data']).sum()) if len(logs) else 0}\n"
        "未读取收益、未计算因子、未训练模型、未回测。\n"
        "Tushare 已获用户接受；保留抽样清单仅用于后续具体疑点追溯。\n",
        encoding="utf-8",
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[2])
    parser.add_argument("--batch-number", type=int, default=1)
    parser.add_argument("--batch-size", type=int, default=100)
    parser.add_argument("--sleep-seconds", type=float, default=0.3)
    parser.add_argument("--attempts", type=int, default=3)
    parser.add_argument("--dry-run", action="store_true", help="Use a saved stock_basic snapshot and do not write or request data.")
    parser.add_argument("--stock-basic-snapshot", type=Path, help="Required with --dry-run; a saved stock_basic CSV/GZIP snapshot.")
    args = parser.parse_args()
    if args.batch_number < 1 or args.batch_size < 1:
        raise SystemExit("batch-number and batch-size must be positive")
    if args.dry_run and not args.stock_basic_snapshot:
        raise SystemExit("--dry-run requires --stock-basic-snapshot")
    root = args.root.resolve()
    frozen_snapshot = root / "data/external/tushare/a_share_financial_pit_v1/full/raw/batch_0001/stock_basic_snapshot.csv.gz"
    if args.dry_run:
        stock_basic = pd.read_csv(args.stock_basic_snapshot, compression="infer", dtype=str)
    elif frozen_snapshot.is_file():
        # All subsequent batches use the first-run snapshot so their membership
        # and ordering cannot change as securities list or delist during a run.
        stock_basic = pd.read_csv(frozen_snapshot, compression="gzip", dtype=str)
    else:
        stock_basic = fetch_stock_basic(ts.pro_api(load_token()))
    universe, excluded = classify_universe(stock_basic)
    ordered = interleaved_order(universe)
    batch = batch_slice(ordered, args.batch_number, args.batch_size)
    print(f"eligible={len(universe)} excluded={len(excluded)} batch={args.batch_number} companies={len(batch)}")
    print(batch.groupby(["exchange", "list_status"]).size().to_string())
    print(batch[["universe_order", "ts_code", "exchange", "list_status", "list_date", "delist_date"]].head(12).to_string(index=False))
    if args.dry_run:
        return
    batch_id = f"batch_{args.batch_number:04d}"
    full_root = root / "data/external/tushare/a_share_financial_pit_v1/full"
    raw_dir = full_root / "raw" / batch_id
    normalized_dir = full_root / "normalized" / batch_id
    audit_dir = root / "output/data_audits/a_share_financial_pit_v1/full" / batch_id
    if (raw_dir / "request_log.csv").exists():
        logs = pd.read_csv(raw_dir / "request_log.csv", dtype=str)
    else:
        logs = pd.DataFrame()
        atomic_csv(stock_basic, raw_dir / "stock_basic_snapshot.csv.gz")
        atomic_csv(excluded, raw_dir / "excluded_securities.csv.gz")
        atomic_csv(batch, raw_dir / "universe_slice.csv.gz")
    # Persist recovered entries before making any new network request.
    logs = recover_completed_raw_files(raw_dir, logs)
    atomic_csv(logs, raw_dir / "request_log.csv")
    pro = ts.pro_api(load_token())
    new_logs = []
    for _, company in batch.iterrows():
        for endpoint in ENDPOINTS:
            done = logs[(logs.get("ts_code", pd.Series(dtype=str)) == company.ts_code) & (logs.get("endpoint", pd.Series(dtype=str)) == endpoint) & (logs.get("status", pd.Series(dtype=str)).isin(["success", "no_data"]))]
            target = raw_dir / endpoint / f"{company.ts_code}.csv.gz"
            if target.exists() and not done.empty:
                continue
            frame, meta = call_endpoint(pro, endpoint, company.ts_code, args.attempts, args.sleep_seconds)
            if frame is None:
                new_logs.append({"ts_code": company.ts_code, "endpoint": endpoint, **meta, "rows": 0})
                atomic_csv(pd.concat([logs, pd.DataFrame(new_logs)], ignore_index=True), raw_dir / "request_log.csv")
                raise SystemExit(f"blocked at {company.ts_code} {endpoint}: {meta['error']}")
            frame = frame.copy()
            frame["requested_ts_code"] = company.ts_code
            frame["request_started_at_utc"] = meta["request_started_at_utc"]
            frame["source_endpoint"] = endpoint
            frame["batch_id"] = batch_id
            atomic_csv(frame, target)
            new_logs.append({"ts_code": company.ts_code, "endpoint": endpoint, **meta, "rows": len(frame), "raw_sha256": sha256_file(target)})
            print(f"{company.ts_code} {endpoint}: {meta['status']} rows={len(frame)}")
            time.sleep(args.sleep_seconds)
    logs = pd.concat([logs, pd.DataFrame(new_logs)], ignore_index=True) if new_logs else logs
    atomic_csv(logs, raw_dir / "request_log.csv")
    write_batch_audit(batch, raw_dir, normalized_dir, audit_dir, logs)
    files = {str(path.relative_to(full_root)): {"bytes": path.stat().st_size, "sha256": sha256_file(path)} for path in sorted(raw_dir.rglob("*")) if path.is_file()}
    atomic_json({"batch_id": batch_id, "scope": {"announcement_start": str(ANNOUNCEMENT_START.date()), "announcement_end": str(ANNOUNCEMENT_END.date()), "report_start": str(REPORT_START.date()), "report_end": str(REPORT_END.date())}, "companies": len(batch), "files": files}, full_root / "manifests" / f"{batch_id}.json")
    print(f"completed {batch_id}; review {audit_dir} before running the next batch")


if __name__ == "__main__":
    main()
