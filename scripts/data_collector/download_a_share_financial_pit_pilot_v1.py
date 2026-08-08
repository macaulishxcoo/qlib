#!/usr/bin/env python3
"""Download and audit the frozen 50-company financial PIT pilot.

This script deliberately stops at data lineage. It does not read returns, build
labels, calculate factors, train models, or run backtests.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import time
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
import tushare as ts


SEED = "a_share_earnings_quality_pit_pilot_v1"
SPOT_SEED = "a_share_earnings_quality_pit_spot_check_v1"
START_DATE = "20150101"
END_DATE = "20250630"
REPORT_START = pd.Timestamp("2014-12-31")
REPORT_END = pd.Timestamp("2024-12-31")
REFERENCE_CODES = ("600519.SH", "000858.SZ")
FINANCIAL_KEYWORDS = ("银行", "证券", "保险", "多元金融", "信托", "期货", "金融控股")
ENDPOINTS = ("income", "cashflow", "fina_indicator")


def digest(seed: str, key: str) -> str:
    return hashlib.sha256(f"{seed}|{key}".encode("utf-8")).hexdigest()


def atomic_csv(frame: pd.DataFrame, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    frame.to_csv(tmp, index=False, compression="gzip" if path.suffix == ".gz" else None)
    os.replace(tmp, path)


def atomic_json(value: object, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    tmp.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(tmp, path)


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def read_token() -> str:
    token = os.environ.get("TUSHARE_TOKEN", "").strip()
    if not token:
        token_path = Path("/root/.config/tushare/token")
        if token_path.is_file():
            token = token_path.read_text(encoding="utf-8").strip()
    if not token:
        raise SystemExit("TUSHARE_TOKEN is not configured and /root/.config/tushare/token is absent")
    return token


def fetch_all_stock_basic(pro) -> pd.DataFrame:
    parts = []
    for status in ("L", "D"):
        frame = pro.stock_basic(
            list_status=status,
            fields=(
                "ts_code,symbol,name,area,industry,market,list_date,delist_date,"
                "list_status,exchange,is_hs"
            ),
        )
        frame = frame.copy()
        frame["requested_list_status"] = status
        parts.append(frame)
    return pd.concat(parts, ignore_index=True).drop_duplicates().reset_index(drop=True)


def is_common_a(row: pd.Series) -> bool:
    code = str(row.get("ts_code", ""))
    exchange = str(row.get("exchange", ""))
    return bool(re.fullmatch(r"\d{6}\.(SH|SZ|BJ)", code)) and exchange in {"SSE", "SZSE", "BSE"}


def is_non_financial(row: pd.Series) -> bool:
    industry = str(row.get("industry", "")).strip()
    if not industry or industry.lower() == "nan":
        return False
    return not any(keyword in industry for keyword in FINANCIAL_KEYWORDS)


def ranked(frame: pd.DataFrame, seed: str = SEED) -> pd.DataFrame:
    out = frame.copy()
    out["_hash"] = out["ts_code"].map(lambda value: digest(seed, str(value)))
    return out.sort_values(["_hash", "ts_code"], kind="mergesort").reset_index(drop=True)


def choose_sample(stock_basic: pd.DataFrame) -> pd.DataFrame:
    current = stock_basic[stock_basic["list_status"].eq("L")].copy()
    current = current[current.apply(is_common_a, axis=1)]
    current["list_date_dt"] = pd.to_datetime(current["list_date"], errors="coerce")
    current = current[current["list_date_dt"].notna()]
    current_non_fin = current[current.apply(is_non_financial, axis=1)].copy()
    selected: list[dict[str, str]] = []

    def add_rows(pool: pd.DataFrame, count: int, sample_type: str) -> None:
        for _, row in ranked(pool).head(count).iterrows():
            selected.append({"ts_code": row.ts_code, "sample_type": sample_type})

    cohorts = [
        ("pre_2010", current_non_fin["list_date_dt"] < "2010-01-01", 6),
        ("2010_2019", (current_non_fin["list_date_dt"] >= "2010-01-01") & (current_non_fin["list_date_dt"] < "2020-01-01"), 6),
        ("post_2020", current_non_fin["list_date_dt"] >= "2020-01-01", 4),
    ]
    for exchange, label in (("SSE", "shanghai_current_non_financial"), ("SZSE", "shenzhen_current_non_financial")):
        exchange_pool = current_non_fin[current_non_fin["exchange"].eq(exchange)]
        for cohort_name, _, count in cohorts:
            if cohort_name == "pre_2010":
                cohort_mask = exchange_pool["list_date_dt"] < "2010-01-01"
            elif cohort_name == "2010_2019":
                cohort_mask = (exchange_pool["list_date_dt"] >= "2010-01-01") & (exchange_pool["list_date_dt"] < "2020-01-01")
            else:
                cohort_mask = exchange_pool["list_date_dt"] >= "2020-01-01"
            add_rows(exchange_pool[cohort_mask], count, f"{label}_{cohort_name}")

    bj = current_non_fin[current_non_fin["exchange"].eq("BSE")].sort_values(["list_date_dt", "ts_code"])
    midpoint = len(bj) // 2
    add_rows(bj.iloc[:midpoint], 4, "beijing_current_non_financial_early")
    add_rows(bj.iloc[midpoint:], 4, "beijing_current_non_financial_late")

    delisted = stock_basic[stock_basic["list_status"].eq("D")].copy()
    delisted = delisted[delisted.apply(is_common_a, axis=1)]
    delisted["delist_date_dt"] = pd.to_datetime(delisted["delist_date"], errors="coerce")
    delisted = delisted[delisted["delist_date_dt"] >= pd.Timestamp("2015-01-01")]
    for exchange, label in (("SSE", "shanghai_delisted"), ("SZSE", "shenzhen_delisted")):
        add_rows(delisted[delisted["exchange"].eq(exchange)], 4, label)

    # Add two distinct reference slots. If a reference is already in the 48-company
    # coverage sample, add the next deterministic company as its separate reference slot.
    selected_codes = {item["ts_code"] for item in selected}
    for ref in REFERENCE_CODES:
        if ref in selected_codes:
            row = current[current["ts_code"].eq(ref)]
            if row.empty:
                continue
            exchange = row.iloc[0]["exchange"]
            cohort = "pre_2010" if row.iloc[0]["list_date_dt"] < pd.Timestamp("2010-01-01") else (
                "2010_2019" if row.iloc[0]["list_date_dt"] < pd.Timestamp("2020-01-01") else "post_2020"
            )
            if cohort == "pre_2010":
                cohort_mask = current_non_fin["list_date_dt"] < "2010-01-01"
            elif cohort == "2010_2019":
                cohort_mask = (current_non_fin["list_date_dt"] >= "2010-01-01") & (current_non_fin["list_date_dt"] < "2020-01-01")
            else:
                cohort_mask = current_non_fin["list_date_dt"] >= "2020-01-01"
            pool = ranked(current_non_fin[(current_non_fin["exchange"] == exchange) & cohort_mask])
            replacement = pool[~pool["ts_code"].isin(selected_codes)].iloc[0]
            selected.append({"ts_code": replacement.ts_code, "sample_type": "reference_replacement"})
            selected_codes.add(replacement.ts_code)
        else:
            selected.append({"ts_code": ref, "sample_type": "reference_company"})
            selected_codes.add(ref)

    sample = pd.DataFrame(selected).drop_duplicates("ts_code", keep="first")
    if len(sample) != 50:
        raise RuntimeError(f"sample construction produced {len(sample)} companies, expected 50")
    return sample


def call_endpoint(pro, endpoint: str, ts_code: str, attempts: int, sleep_seconds: float):
    # Tushare's start_date/end_date parameters are report-period filters. They
    # are not announcement-date range parameters, so the PIT scope is applied
    # locally after requesting the stock's available history.
    kwargs = {"ts_code": ts_code}
    last_error = ""
    for attempt in range(1, attempts + 1):
        started = datetime.now(timezone.utc).isoformat()
        try:
            frame = getattr(pro, endpoint)(**kwargs)
            return frame, {"started_at_utc": started, "attempt": attempt, "status": "success", "error": ""}
        except Exception as exc:  # Tushare raises several request-specific exception classes.
            last_error = f"{type(exc).__name__}: {exc}"
            if attempt < attempts:
                time.sleep(sleep_seconds * attempt)
    return None, {"started_at_utc": started, "attempt": attempts, "status": "error", "error": last_error}


def filter_pit_scope(frame: pd.DataFrame) -> pd.DataFrame:
    """Keep only the frozen announcement/report-period scope."""
    if frame is None or frame.empty:
        return frame
    out = frame.copy()
    announcement = pd.Series(pd.NaT, index=out.index, dtype="datetime64[ns]")
    if "f_ann_date" in out:
        announcement = pd.to_datetime(out["f_ann_date"], errors="coerce")
    if "ann_date" in out:
        fallback = pd.to_datetime(out["ann_date"], errors="coerce")
        announcement = announcement.where(announcement.notna(), fallback)
    report_end = pd.to_datetime(out["end_date"], errors="coerce") if "end_date" in out else pd.Series(pd.NaT, index=out.index)
    announcement_ok = announcement.between(pd.Timestamp("2015-01-01"), pd.Timestamp("2025-06-30"), inclusive="both")
    report_ok = report_end.between(REPORT_START, REPORT_END, inclusive="both")
    # Keep missing-date rows for the audit to flag; never silently repair them.
    keep = (announcement_ok | announcement.isna()) & (report_ok | report_end.isna())
    return out.loc[keep].reset_index(drop=True)


def normalize_endpoint(raw_dir: Path, endpoint: str, normalized_dir: Path) -> dict:
    files = sorted((raw_dir / endpoint).glob("*.csv.gz"))
    parts = []
    for path in files:
        frame = pd.read_csv(path, compression="gzip", dtype=str)
        if not frame.empty:
            frame["source_file"] = path.name
            parts.append(frame)
    if not parts:
        output = pd.DataFrame()
    else:
        output = pd.concat(parts, ignore_index=True)
        for col in ("ann_date", "f_ann_date", "end_date"):
            if col in output:
                output[f"_{col}_dt"] = pd.to_datetime(output[col], errors="coerce")
        if "end_date" in output:
            output["report_end"] = output["_end_date_dt"]
        output["available_date"] = output.get("_f_ann_date_dt", pd.Series(pd.NaT, index=output.index))
        if "_ann_date_dt" in output:
            output["available_date"] = output["available_date"].where(output["available_date"].notna(), output["_ann_date_dt"])
        output["available_date_valid"] = output["available_date"].notna()
        if "report_end" in output:
            output["available_date_valid"] &= output["available_date"] >= output["report_end"]
            output["report_period_in_scope"] = output["report_end"].between(REPORT_START, REPORT_END, inclusive="both")
        output = output.drop(columns=[c for c in output.columns if c.startswith("_")])
    path = normalized_dir / f"{endpoint}.csv.gz"
    atomic_csv(output, path)
    return {"rows": int(len(output)), "files": len(files), "path": str(path)}


def make_spot_check_template(normalized_dir: Path, audit_dir: Path, sample: pd.DataFrame) -> pd.DataFrame:
    """Freeze 24 unique keys with the protocol's report/update/delist coverage."""
    parts = []
    update_keys = []
    for endpoint in ENDPOINTS:
        path = normalized_dir / f"{endpoint}.csv.gz"
        if path.is_file():
            frame = pd.read_csv(path, compression="gzip", dtype=str)
            if not frame.empty and "ts_code" in frame and "end_date" in frame:
                parts.append(frame[["ts_code", "end_date"]].drop_duplicates())
                if "update_flag" in frame:
                    changed = frame[frame["update_flag"].astype(str).eq("1")]
                    update_keys.append(changed[["ts_code", "end_date"]].drop_duplicates())
    candidates = pd.concat(parts, ignore_index=True).drop_duplicates() if parts else pd.DataFrame(columns=["ts_code", "end_date"])
    candidates["_hash"] = candidates.apply(lambda row: digest(SPOT_SEED, f"{row.ts_code}|{row.end_date}"), axis=1)
    candidates = candidates.sort_values(["_hash", "ts_code", "end_date"]).drop(columns="_hash")
    retired_codes = set(sample.loc[sample["sample_type"].str.contains("delisted", na=False), "ts_code"])
    changed_keys = pd.concat(update_keys, ignore_index=True).drop_duplicates() if update_keys else pd.DataFrame(columns=["ts_code", "end_date"])
    changed = candidates.merge(changed_keys, on=["ts_code", "end_date"], how="inner")
    retired = candidates[candidates["ts_code"].isin(retired_codes)]
    period_suffixes = {"Q1": "0331", "H1": "0630", "Q3": "0930", "FY": "1231"}
    chosen_parts = []
    selected = set()

    def take(pool: pd.DataFrame, count: int, group: str) -> None:
        available = pool[~pool.apply(lambda row: (row.ts_code, row.end_date) in selected, axis=1)].head(count)
        if len(available) < count:
            raise RuntimeError(f"spot-check group {group} has {len(available)} candidates, expected {count}")
        for _, row in available.iterrows():
            selected.add((row.ts_code, row.end_date))
        tagged = available.copy()
        tagged["selection_group"] = group
        chosen_parts.append(tagged)

    take(changed, 4, "update_or_duplicate")
    take(retired, 4, "delisted")
    for label, suffix in period_suffixes.items():
        take(candidates[candidates["end_date"].str.endswith(suffix)], 4, label)
    chosen = pd.concat(chosen_parts, ignore_index=True)
    if len(chosen) != 24 or chosen.duplicated(["ts_code", "end_date"]).any():
        raise RuntimeError("spot-check selection is not 24 unique company/report-period keys")
    chosen["official_source_url"] = ""
    chosen["checked_at_utc"] = ""
    chosen["date_match"] = "pending"
    chosen["amount_match"] = "pending"
    chosen["revision_checked"] = "pending"
    chosen["notes"] = "Fill from exchange/CNInfo official announcement; no automatic pass allowed."
    atomic_csv(chosen, audit_dir / "official_spot_check.csv")
    return chosen


def build_audit(sample: pd.DataFrame, stock_basic: pd.DataFrame, logs: pd.DataFrame, normalized_dir: Path, audit_dir: Path) -> str:
    summaries = []
    schema = {}
    anomalies = []
    for endpoint in ENDPOINTS:
        path = normalized_dir / f"{endpoint}.csv.gz"
        frame = pd.read_csv(path, compression="gzip", dtype=str) if path.is_file() else pd.DataFrame()
        schema[endpoint] = {"columns": frame.columns.tolist(), "rows": len(frame)}
        core = {"income": ["total_revenue", "n_income"], "cashflow": ["n_cashflow_act"], "fina_indicator": []}[endpoint]
        coverage = {field: float(frame[field].notna().mean()) if field in frame and len(frame) else 0.0 for field in core}
        for field in core:
            if field in frame:
                missing = frame[field].isna() | frame[field].eq("")
                if missing.any():
                    anomalies.append({"endpoint": endpoint, "reason": "missing_core_field", "field": field, "count": int(missing.sum())})
        if "available_date_valid" in frame:
            invalid = ~frame["available_date_valid"].astype(str).eq("True")
            if invalid.any():
                anomalies.append({"endpoint": endpoint, "reason": "invalid_available_date", "field": "available_date", "count": int(invalid.sum())})
        summaries.append({"endpoint": endpoint, "rows": len(frame), **coverage})
    pd.DataFrame(summaries).to_csv(audit_dir / "field_coverage_summary.csv", index=False)
    atomic_json(schema, audit_dir / "schema_inventory.json")
    date_rows = []
    for endpoint in ENDPOINTS:
        path = normalized_dir / f"{endpoint}.csv.gz"
        frame = pd.read_csv(path, compression="gzip", dtype=str) if path.is_file() else pd.DataFrame()
        valid = frame["available_date_valid"].astype(str).eq("True") if "available_date_valid" in frame else pd.Series(dtype=bool)
        date_rows.append({"endpoint": endpoint, "rows": len(frame), "valid_available_date": int(valid.sum()), "valid_ratio": float(valid.mean()) if len(valid) else 0.0})
    pd.DataFrame(date_rows).to_csv(audit_dir / "date_quality_summary.csv", index=False)
    version_parts = []
    for endpoint in ENDPOINTS:
        path = normalized_dir / f"{endpoint}.csv.gz"
        frame = pd.read_csv(path, compression="gzip", dtype=str) if path.is_file() else pd.DataFrame()
        keys = [c for c in ["ts_code", "end_date", "report_type"] if c in frame]
        if keys and len(frame):
            counts = frame.groupby(keys, dropna=False).size()
            version_parts.append({"endpoint": endpoint, "keys": len(counts), "duplicate_key_groups": int((counts > 1).sum()), "max_versions": int(counts.max())})
        else:
            version_parts.append({"endpoint": endpoint, "keys": 0, "duplicate_key_groups": 0, "max_versions": 0})
    pd.DataFrame(version_parts).to_csv(audit_dir / "version_quality_summary.csv", index=False)
    aligned = []
    income_path, cash_path = normalized_dir / "income.csv.gz", normalized_dir / "cashflow.csv.gz"
    if income_path.is_file() and cash_path.is_file():
        inc = pd.read_csv(income_path, compression="gzip", dtype=str)
        cf = pd.read_csv(cash_path, compression="gzip", dtype=str)
        keys = [c for c in ["ts_code", "end_date", "report_type", "available_date"] if c in inc and c in cf]
        left = inc[keys].drop_duplicates() if keys else pd.DataFrame()
        right = cf[keys].drop_duplicates() if keys else pd.DataFrame()
        if keys:
            both = left.merge(right, on=keys, how="inner")
            aligned.append({"income_keys": len(left), "cashflow_keys": len(right), "aligned_keys": len(both), "alignment_ratio_income": len(both) / len(left) if len(left) else 0.0})
    pd.DataFrame(aligned or [{"income_keys": 0, "cashflow_keys": 0, "aligned_keys": 0, "alignment_ratio_income": 0.0}]).to_csv(audit_dir / "three_statement_alignment_summary.csv", index=False)
    spot = make_spot_check_template(normalized_dir, audit_dir, sample)
    anomaly_frame = pd.DataFrame(anomalies, columns=["endpoint", "reason", "field", "count"])
    atomic_csv(anomaly_frame, audit_dir / "anomaly_records.csv.gz")
    official_complete = len(spot) >= 24 and spot[["date_match", "amount_match", "revision_checked"]].apply(lambda col: col.eq("yes")).all(axis=None)
    successful = logs[logs["status"].eq("success")] if not logs.empty else logs
    pass_flag = len(sample) == 50 and len(logs) == 150 and len(successful) == 150 and official_complete
    status = "pilot_pass" if pass_flag else "pilot_blocked"
    report = [
        "A 股财务 PIT 小样本下载与审计报告 v1",
        f"status: {status}",
        f"sample_companies: {len(sample)}",
        f"requests: {len(logs)}; successful: {len(successful)}; expected: 150",
        f"official_spot_checks: {len(spot)}; complete: {official_complete}",
        "审计范围仅包括财务数据血缘；未读取未来收益，未计算因子，未训练模型，未回测。",
        "官方公告核验模板必须由交易所或巨潮资讯结果填写；未完成时不得判定 pilot_pass。",
    ]
    (audit_dir / "pilot_audit_report.txt").write_text("\n".join(report) + "\n", encoding="utf-8")
    audit_metadata = {
        "status": status,
        "sample_count": len(sample),
        "request_count": len(logs),
        "successful_request_count": len(successful),
        "official_spot_check_count": len(spot),
        "official_spot_check_complete": bool(official_complete),
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "scope": {"announcement_start": "2015-01-01", "announcement_end": "2025-06-30", "report_start": str(REPORT_START.date()), "report_end": str(REPORT_END.date())},
        "files": {},
    }
    for path in sorted(audit_dir.rglob("*")):
        if path.is_file() and path.name != "metadata.json":
            audit_metadata["files"][str(path.relative_to(audit_dir))] = {"bytes": path.stat().st_size, "sha256": sha256_file(path)}
    atomic_json(audit_metadata, audit_dir / "metadata.json")
    return status


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[2])
    parser.add_argument("--sleep-seconds", type=float, default=0.25)
    parser.add_argument("--attempts", type=int, default=3)
    parser.add_argument("--refresh", action="store_true", help="Re-request all three endpoints for the frozen pilot sample.")
    args = parser.parse_args()
    root = args.root.resolve()
    raw_dir = root / "data/external/tushare/a_share_financial_pit_v1/pilot/raw"
    normalized_dir = root / "data/external/tushare/a_share_financial_pit_v1/pilot/normalized"
    audit_dir = root / "output/data_audits/a_share_financial_pit_v1/pilot"
    token = read_token()
    pro = ts.pro_api(token)
    stock_basic = fetch_all_stock_basic(pro)
    atomic_csv(stock_basic, raw_dir / "stock_basic_snapshot.csv.gz")
    sample = choose_sample(stock_basic)
    sample = sample.merge(stock_basic.drop_duplicates("ts_code"), on="ts_code", how="left", suffixes=("", "_source"))
    atomic_csv(sample, audit_dir / "sample_universe.csv")
    logs_path = audit_dir / "request_log.csv"
    logs = pd.DataFrame() if args.refresh else (pd.read_csv(logs_path, dtype=str) if logs_path.is_file() else pd.DataFrame())
    rows = []
    for _, company in sample.iterrows():
        code = company.ts_code
        for endpoint in ENDPOINTS:
            target = raw_dir / endpoint / f"{code}.csv.gz"
            done = logs[(logs.get("ts_code", pd.Series(dtype=str)) == code) & (logs.get("endpoint", pd.Series(dtype=str)) == endpoint) & (logs.get("status", pd.Series(dtype=str)) == "success")]
            if target.is_file() and not done.empty and not args.refresh:
                continue
            frame, meta = call_endpoint(pro, endpoint, code, args.attempts, args.sleep_seconds)
            if frame is not None:
                frame = filter_pit_scope(frame)
                frame["requested_ts_code"] = code
                frame["request_started_at_utc"] = meta["started_at_utc"]
                atomic_csv(frame, target)
            rows.append({"ts_code": code, "endpoint": endpoint, "request_params": "ts_code only; local PIT scope 2015-01-01..2025-06-30; report_end 2014-12-31..2024-12-31", "status": meta["status"], "rows": 0 if frame is None else len(frame), "error": meta["error"], "request_started_at_utc": meta["started_at_utc"], "attempt": meta["attempt"]})
            print(f"{code} {endpoint}: {meta['status']} rows={0 if frame is None else len(frame)}")
            time.sleep(args.sleep_seconds)
    if rows:
        logs = pd.concat([logs, pd.DataFrame(rows)], ignore_index=True) if not logs.empty else pd.DataFrame(rows)
    atomic_csv(logs, logs_path)
    for endpoint in ENDPOINTS:
        normalize_endpoint(raw_dir, endpoint, normalized_dir)
    status = build_audit(sample, stock_basic, logs, normalized_dir, audit_dir)
    manifest_files = {}
    for path in sorted((root / "data/external/tushare/a_share_financial_pit_v1/pilot").rglob("*")):
        if path.is_file() and path.name != "manifest.json":
            relative = path.relative_to(root / "data/external/tushare/a_share_financial_pit_v1/pilot")
            manifest_files[str(relative)] = {"bytes": path.stat().st_size, "sha256": sha256_file(path)}
    atomic_json({"status": status, "sample_count": len(sample), "endpoints": ENDPOINTS, "start_date": START_DATE, "end_date": END_DATE, "report_period_start": str(REPORT_START.date()), "report_period_end": str(REPORT_END.date()), "request_scope": "Tushare stock history request; local f_ann_date/ann_date and end_date filtering", "files": manifest_files}, root / "data/external/tushare/a_share_financial_pit_v1/pilot/manifest.json")
    print(f"completed: status={status}; audit={audit_dir}")


if __name__ == "__main__":
    main()
