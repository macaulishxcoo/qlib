#!/usr/bin/env python3
"""Build the label-free PIT working-capital-quality event panel.

Only financial statements, listing metadata, industry history, and the Qlib
trading calendar are read.  Prices, returns, labels, ICs, models, and backtests
are deliberately outside this program's scope.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import numpy as np
import pandas as pd


PERIOD_SUFFIXES = {"0331", "0630", "0930", "1231"}
FINANCIAL_L1_CODES = {"801780.SI", "801790.SI"}
KEY = ["ts_code", "end_date", "report_type", "available_date"]
BALANCE_CORE = ["accounts_receiv", "inventories", "total_assets", "total_liab"]


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


def load_endpoint(root: Path, dataset: str, endpoint: str, fields: list[str]) -> pd.DataFrame:
    if dataset == "income":
        base = root / "data/external/tushare/a_share_financial_pit_v1/full/normalized"
    else:
        base = root / "data/external/tushare/a_share_financial_pit_v1/balancesheet_v1/normalized"
    frames = []
    for number in range(1, 55):
        path = base / f"batch_{number:04d}" / f"{endpoint}.csv.gz"
        if not path.is_file():
            raise SystemExit(f"missing normalized input: {path}")
        frames.append(pd.read_csv(path, compression="gzip", usecols=lambda name: name in fields, dtype=str))
    data = pd.concat(frames, ignore_index=True)
    data["end_date"] = data["end_date"].str.replace("-", "", regex=False)
    data["available_date"] = pd.to_datetime(data["available_date"], errors="coerce")
    return data.loc[data["report_type"].eq("1") & data["end_date"].str[-4:].isin(PERIOD_SUFFIXES) & data["available_date"].notna()].copy()


def collapse_same_day(data: pd.DataFrame, endpoint: str, value_fields: list[str]) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """Choose identical versions deterministically and quarantine value conflicts."""
    groups = data.groupby(KEY, dropna=False, sort=False)
    counts = groups.size().rename("source_rows").reset_index()
    flags = pd.DataFrame({field: groups[field].nunique(dropna=False).gt(1) for field in value_fields}).reset_index()
    all_groups = counts.merge(flags, on=KEY, how="left")
    conflict_mask = all_groups[value_fields].any(axis=1)
    conflicts = all_groups.loc[conflict_mask].copy()
    conflicts["endpoint"] = endpoint
    conflicts["conflicting_fields"] = conflicts[value_fields].apply(lambda row: ",".join(field for field in value_fields if row[field]), axis=1)
    conflicts = conflicts[["endpoint", *KEY, "source_rows", "conflicting_fields"]]
    usable = data.merge(conflicts[KEY], on=KEY, how="left", indicator=True)
    usable = usable.loc[usable["_merge"].eq("left_only")].drop(columns="_merge")
    usable["_update"] = pd.to_numeric(usable.get("update_flag"), errors="coerce").fillna(-1)
    usable = usable.sort_values([*KEY, "_update", "source_file"], ascending=[True, True, True, True, False, True], kind="mergesort")
    usable["_rank"] = usable.groupby(KEY, dropna=False).cumcount()
    chosen = usable.loc[usable["_rank"].eq(0)].drop(columns=["_rank", "_update"])
    discarded = usable.loc[usable["_rank"].gt(0)].copy()
    chosen_meta = usable.loc[usable["_rank"].eq(0), [*KEY, "source_file", "update_flag"]].rename(columns={"source_file": "chosen_source_file", "update_flag": "chosen_update_flag"})
    duplicates = discarded.merge(chosen_meta, on=KEY, how="left").rename(columns={"source_file": "discarded_source_file", "update_flag": "discarded_update_flag"})
    duplicates["endpoint"] = endpoint
    duplicates["reason"] = "same_day_core_values_identical"
    duplicates = duplicates[["endpoint", *KEY, "chosen_source_file", "discarded_source_file", "chosen_update_flag", "discarded_update_flag", "reason"]]
    return chosen, duplicates, conflicts


def map_industry(events: pd.DataFrame, industry: pd.DataFrame) -> pd.DataFrame:
    """Attach only the uniquely effective level-1 industry on available_date."""
    left = events.reset_index(drop=True).copy()
    left["_row"] = np.arange(len(left))
    intervals = industry.copy()
    intervals["in_date"] = pd.to_datetime(intervals["in_date"], errors="coerce")
    intervals["out_date"] = pd.to_datetime(intervals["out_date"], errors="coerce")
    matched = left[["_row", "ts_code", "available_date"]].merge(intervals[["ts_code", "l1_code", "l1_name", "in_date", "out_date"]], on="ts_code", how="left")
    matched = matched.loc[matched["in_date"].le(matched["available_date"]) & (matched["out_date"].isna() | matched["out_date"].ge(matched["available_date"]))]
    counts = matched.groupby("_row").size()
    valid_rows = counts[counts.eq(1)].index
    valid = matched.loc[matched["_row"].isin(valid_rows), ["_row", "l1_code", "l1_name"]]
    left = left.merge(valid, on="_row", how="left")
    left["industry_status"] = "industry_missing"
    left.loc[left["_row"].isin(counts[counts.gt(1)].index), "industry_status"] = "industry_ambiguous"
    left.loc[left["_row"].isin(valid_rows), "industry_status"] = "valid"
    return left.drop(columns="_row")


def next_trading_days(dates: pd.Series, calendar: pd.DatetimeIndex) -> pd.Series:
    positions = calendar.searchsorted(pd.DatetimeIndex(dates), side="right")
    return pd.Series([calendar[pos] if pos < len(calendar) else pd.NaT for pos in positions], index=dates.index)


def pair_prior_year(events: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Use the latest prior-year version public by each current event date."""
    prior = events[["ts_code", "end_date_dt", "report_type", "available_date", "receivable_intensity", "inventory_intensity"]].copy()
    prior["target_end_date"] = prior["end_date_dt"] + pd.DateOffset(years=1)
    paired = events.merge(prior, left_on=["ts_code", "end_date_dt", "report_type"], right_on=["ts_code", "target_end_date", "report_type"], how="left", suffixes=("", "_prior"))
    paired = paired.loc[paired["available_date_prior"].le(paired["available_date"])].copy()
    paired = paired.sort_values(["ts_code", "end_date", "available_date", "available_date_prior"], kind="mergesort").drop_duplicates(KEY, keep="last")
    all_keys = events[KEY].drop_duplicates()
    audit = all_keys.merge(paired[KEY], on=KEY, how="left", indicator=True)
    audit["pairing_status"] = np.where(audit["_merge"].eq("both"), "paired", "prior_not_available_or_missing")
    return paired, audit.drop(columns="_merge")


def main() -> None:
    root = Path(__file__).resolve().parents[2]
    derived = root / "data/derived/a_share_working_capital_quality_event_v1"
    audit = root / "output/data_audits/a_share_working_capital_quality_event_v1"
    income = load_endpoint(root, "income", "income", [*KEY, "total_revenue", "update_flag", "source_file"])
    balance = load_endpoint(root, "balancesheet", "balancesheet", [*KEY, *BALANCE_CORE, "update_flag", "source_file"])
    print(f"loaded income={len(income)} balancesheet={len(balance)}", flush=True)
    income_clean, income_dupes, income_conflicts = collapse_same_day(income, "income", ["total_revenue"])
    balance_clean, balance_dupes, balance_conflicts = collapse_same_day(balance, "balancesheet", BALANCE_CORE)
    duplicates = pd.concat([income_dupes, balance_dupes], ignore_index=True)
    conflicts = pd.concat([income_conflicts, balance_conflicts], ignore_index=True)
    aligned = balance_clean.merge(income_clean[KEY + ["total_revenue", "source_file"]], on=KEY, how="left", suffixes=("_balance", "_income"), indicator=True)
    alignment_audit = aligned.loc[aligned["_merge"].ne("both"), KEY + ["_merge"]].rename(columns={"_merge": "alignment_status"})
    events = aligned.loc[aligned["_merge"].eq("both")].drop(columns="_merge").copy()
    for field in [*BALANCE_CORE, "total_revenue"]:
        events[field] = pd.to_numeric(events[field], errors="coerce")
    events["end_date_dt"] = pd.to_datetime(events["end_date"], format="%Y%m%d", errors="coerce")
    events["event_year"] = events["end_date_dt"].dt.year
    events["period_suffix"] = events["end_date"].str[-4:]
    snapshot = pd.read_csv(root / "data/external/tushare/a_share_financial_pit_v1/full/raw/batch_0001/stock_basic_snapshot.csv.gz", compression="gzip", dtype=str)
    snapshot["list_date"] = pd.to_datetime(snapshot["list_date"], errors="coerce")
    snapshot["delist_date"] = pd.to_datetime(snapshot["delist_date"], errors="coerce")
    events = events.merge(snapshot[["ts_code", "list_date", "delist_date"]], on="ts_code", how="left")
    listed = events["list_date"].le(events["available_date"]) & (events["delist_date"].isna() | events["delist_date"].gt(events["available_date"]))
    events["listing_status"] = np.where(listed, "valid", "not_listed_or_delisted")
    industry = pd.read_csv(root / "data/external/tushare/a_share_style_pit_v1/normalized/industry_l1_effective_intervals.csv.gz", compression="gzip", dtype=str)
    events = map_industry(events, industry)
    events["nonfinancial_status"] = np.where(events["industry_status"].eq("valid") & ~events["l1_code"].isin(FINANCIAL_L1_CODES), "valid", np.where(events["l1_code"].isin(FINANCIAL_L1_CODES), "financial_excluded", events["industry_status"]))
    # Ratio validity is an accounting-data gate, not a label-based exclusion.
    invalid = pd.Series("valid", index=events.index, dtype=object)
    invalid.loc[events["total_revenue"].isna()] = "revenue_missing"
    invalid.loc[events["total_revenue"].le(0)] = "revenue_nonpositive"
    invalid.loc[events["accounts_receiv"].isna()] = "accounts_receiv_missing"
    invalid.loc[events["accounts_receiv"].lt(0)] = "accounts_receiv_negative"
    invalid.loc[events["inventories"].isna()] = "inventories_missing"
    invalid.loc[events["inventories"].lt(0)] = "inventories_negative"
    events["ratio_validity"] = invalid
    candidates = events.loc[events["listing_status"].eq("valid") & events["nonfinancial_status"].eq("valid") & events["ratio_validity"].eq("valid")].copy()
    candidates["receivable_intensity"] = np.log1p(candidates["accounts_receiv"] / candidates["total_revenue"])
    candidates["inventory_intensity"] = np.log1p(candidates["inventories"] / candidates["total_revenue"])
    finite = np.isfinite(candidates["receivable_intensity"]) & np.isfinite(candidates["inventory_intensity"])
    candidates = candidates.loc[finite].copy()
    print(f"aligned={len(events)} eligible_ratio_candidates={len(candidates)} conflicts={len(conflicts)}", flush=True)
    paired, pairing_audit = pair_prior_year(candidates)
    paired["receivable_deterioration"] = paired["receivable_intensity"] - paired["receivable_intensity_prior"]
    paired["inventory_deterioration"] = paired["inventory_intensity"] - paired["inventory_intensity_prior"]
    paired["working_capital_deterioration"] = (paired["receivable_deterioration"] + paired["inventory_deterioration"]) / 2.0
    calendar_path = Path.home() / ".qlib/qlib_data/cn_data_2026/calendars/day.txt"
    if not calendar_path.is_file():
        raise SystemExit(f"missing Qlib CN calendar: {calendar_path}")
    calendar = pd.DatetimeIndex(pd.to_datetime(pd.read_csv(calendar_path, header=None)[0], errors="coerce").dropna().sort_values())
    paired["effective_date"] = next_trading_days(paired["available_date"], calendar).values
    paired = paired.loc[paired["effective_date"].notna()].copy()
    # Friday and weekend disclosures can share Monday's first tradable date.
    # At that Monday open only the latest already-public version is actionable.
    paired = paired.sort_values(["ts_code", "effective_date", "available_date", "end_date"], kind="mergesort").drop_duplicates(["ts_code", "effective_date"], keep="last")
    paired = paired.sort_values(["ts_code", "effective_date", "available_date"], kind="mergesort")
    paired["next_effective_date"] = paired.groupby("ts_code")["effective_date"].shift(-1)
    paired["expiry_date"] = paired["next_effective_date"] - pd.Timedelta(days=1)
    paired.loc[paired["expiry_date"].isna(), "expiry_date"] = calendar[-1]
    paired["event_id"] = paired.apply(lambda row: f"{row.ts_code}|{row.end_date}|{row.available_date.strftime('%Y-%m-%d')}", axis=1)
    keep = ["event_id", "ts_code", "end_date", "event_year", "period_suffix", "report_type", "available_date", "effective_date", "expiry_date", "l1_code", "l1_name", "accounts_receiv", "inventories", "total_revenue", "receivable_intensity", "inventory_intensity", "receivable_intensity_prior", "inventory_intensity_prior", "receivable_deterioration", "inventory_deterioration", "working_capital_deterioration"]
    panel = paired[keep].sort_values(["effective_date", "ts_code"], kind="mergesort").reset_index(drop=True)
    atomic_csv(panel, derived / "event_panel.csv.gz")
    atomic_csv(duplicates, audit / "same_day_duplicate_audit.csv.gz")
    atomic_csv(conflicts, audit / "same_day_value_conflict.csv.gz")
    atomic_csv(alignment_audit, audit / "statement_alignment_audit.csv.gz")
    atomic_csv(pairing_audit, audit / "prior_year_pairing_audit.csv.gz")
    ratio_audit = events.groupby(["event_year", "period_suffix", "ratio_validity"], dropna=False).agg(events=("ts_code", "size"), companies=("ts_code", "nunique")).reset_index()
    atomic_csv(ratio_audit, audit / "ratio_validity_audit.csv.gz")
    coverage = panel.groupby(["event_year", "period_suffix"], dropna=False).agg(events=("event_id", "size"), companies=("ts_code", "nunique")).reset_index()
    atomic_csv(coverage, audit / "coverage_by_event_year_and_period.csv")
    distribution_columns = ["receivable_intensity", "inventory_intensity", "receivable_deterioration", "inventory_deterioration", "working_capital_deterioration"]
    rows = []
    for (year, period), group in panel.groupby(["event_year", "period_suffix"], dropna=False):
        row = {"event_year": year, "period_suffix": period, "events": len(group)}
        for field in distribution_columns:
            row[f"{field}_p01"] = group[field].quantile(0.01)
            row[f"{field}_p50"] = group[field].median()
            row[f"{field}_p99"] = group[field].quantile(0.99)
        rows.append(row)
    atomic_csv(pd.DataFrame(rows), audit / "variable_distribution_by_event_year_and_period.csv")
    replacements = paired.loc[paired["next_effective_date"].notna(), ["event_id", "ts_code", "effective_date", "next_effective_date", "expiry_date"]].copy()
    replacements["replacement_type"] = "later_valid_financial_event"
    atomic_csv(replacements, audit / "event_replacement_audit.csv.gz")
    pairing_missing = int(pairing_audit["pairing_status"].ne("paired").sum())
    methodology = {"version": "v1", "label_access": False, "main_score": "equal-weight mean of receivable and inventory intensity year-over-year deterioration", "ratio": "log(1 + ending balance / same-period cumulative revenue)", "prior_pairing": "latest same-period prior-year version public no later than current event", "same_day_conflict_policy": "exclude event", "financial_l1_exclusions": sorted(FINANCIAL_L1_CODES), "calendar_source": str(calendar_path), "event_replacement": "next valid financial event effective date"}
    atomic_json(methodology, audit / "methodology.json")
    report = (
        "沪深非金融 A 股营运资本质量事件面板无标签审计 v1\n"
        "status: working_capital_event_panel_ready\n"
        f"aligned_income_balancesheet_events: {len(events)}\n"
        f"valid_nonfinancial_ratio_events_before_prior_pairing: {len(candidates)}\n"
        f"event_panel_rows: {len(panel)}; companies: {panel['ts_code'].nunique()}\n"
        f"same_day_identical_duplicates: {len(duplicates)}\n"
        f"same_day_value_conflicts_excluded: {len(conflicts)}\n"
        f"statement_alignment_missing: {len(alignment_audit)}\n"
        f"prior_year_not_available_or_missing: {pairing_missing}\n"
        "未读取价格或收益；未构建标签；未计算 IC；未训练模型；未回测。\n"
    )
    (audit / "event_panel_audit_report.txt").write_text(report, encoding="utf-8")
    print(report, end="")


if __name__ == "__main__":
    main()
