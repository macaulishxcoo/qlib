#!/usr/bin/env python3
"""Build the label-free PIT earnings and cash-quality event panel.

The implementation follows the frozen event-panel specification.  It reads
financial and control data only; no prices beyond pre-downloaded size controls,
returns, labels, ICs, models, or backtests are accessed.
"""

from __future__ import annotations

import json
import math
import os
from pathlib import Path

import numpy as np
import pandas as pd


PERIOD_SUFFIXES = {"0331", "0630", "0930", "1231"}
FINANCIAL_L1_CODES = {"801780.SI", "801790.SI"}
KEY = ["ts_code", "end_date", "report_type", "available_date"]


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


def load_financial(root: Path, endpoint: str, fields: list[str]) -> pd.DataFrame:
    base = root / "data/external/tushare/a_share_financial_pit_v1/full/normalized"
    frames = []
    for number in range(1, 55):
        path = base / f"batch_{number:04d}" / f"{endpoint}.csv.gz"
        frames.append(pd.read_csv(path, compression="gzip", usecols=lambda name: name in fields, dtype=str))
    data = pd.concat(frames, ignore_index=True)
    data["end_date"] = data["end_date"].str.replace("-", "", regex=False)
    data["available_date"] = pd.to_datetime(data["available_date"], errors="coerce")
    data = data[
        data["report_type"].eq("1")
        & data["end_date"].str[-4:].isin(PERIOD_SUFFIXES)
        & data["available_date"].notna()
    ].copy()
    return data


def collapse_same_day(data: pd.DataFrame, endpoint: str, value_fields: list[str]) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """Keep deterministic identical duplicates; quarantine same-day value conflicts."""
    working = data.copy()
    grouped = working.groupby(KEY, dropna=False, sort=False)
    counts = grouped.size().rename("source_rows").reset_index()
    conflict_flags = pd.DataFrame({field: grouped[field].nunique(dropna=False) > 1 for field in value_fields})
    conflicts = counts.merge(conflict_flags.reset_index(), on=KEY, how="left")
    conflict_mask = conflicts[value_fields].any(axis=1)
    conflicts = conflicts.loc[conflict_mask].copy()
    conflicts["endpoint"] = endpoint
    conflicts["conflicting_fields"] = conflicts[value_fields].apply(lambda row: ",".join(field for field in value_fields if row[field]), axis=1)
    conflicts = conflicts[["endpoint", *KEY, "source_rows", "conflicting_fields"]]
    usable = working.merge(conflicts[KEY], on=KEY, how="left", indicator=True)
    usable = usable.loc[usable["_merge"].eq("left_only")].drop(columns="_merge")
    usable["_update"] = pd.to_numeric(usable.get("update_flag"), errors="coerce").fillna(-1)
    usable = usable.sort_values([*KEY, "_update", "source_file"], ascending=[True, True, True, True, False, True], kind="mergesort")
    usable["_rank"] = usable.groupby(KEY, dropna=False).cumcount()
    chosen = usable.loc[usable["_rank"].eq(0)].drop(columns=["_rank", "_update"])
    duplicate_rows = usable.loc[usable["_rank"].gt(0)].copy()
    chosen_meta = usable.loc[usable["_rank"].eq(0), [*KEY, "source_file", "update_flag"]].rename(columns={"source_file": "chosen_source_file", "update_flag": "chosen_update_flag"})
    duplicates = duplicate_rows.merge(chosen_meta, on=KEY, how="left").rename(columns={"source_file": "discarded_source_file", "update_flag": "discarded_update_flag"})
    duplicates["endpoint"] = endpoint
    duplicates["reason"] = "same_day_core_values_identical"
    duplicates = duplicates[["endpoint", *KEY, "chosen_source_file", "discarded_source_file", "chosen_update_flag", "discarded_update_flag", "reason"]]
    return chosen, duplicates, conflicts


def map_industry(events: pd.DataFrame, industry: pd.DataFrame, date_column: str) -> pd.DataFrame:
    """Attach the only industry record effective on each event date; retain status."""
    industry = industry.copy()
    industry["in_date"] = pd.to_datetime(industry["in_date"], errors="coerce")
    industry["out_date"] = pd.to_datetime(industry["out_date"], errors="coerce")
    left = events.reset_index(drop=True).copy()
    left["_event_row"] = np.arange(len(left))
    matches = left[["_event_row", "ts_code", date_column]].merge(industry[["ts_code", "l1_code", "l1_name", "in_date", "out_date"]], on="ts_code", how="left")
    matches = matches[matches["in_date"].le(matches[date_column]) & (matches["out_date"].isna() | matches["out_date"].ge(matches[date_column]))]
    match_count = matches.groupby("_event_row").size()
    valid = matches.loc[matches["_event_row"].isin(match_count[match_count.eq(1)].index), ["_event_row", "l1_code", "l1_name"]]
    left = left.merge(valid, on="_event_row", how="left")
    left["industry_status"] = "industry_missing"
    left.loc[left["_event_row"].isin(match_count[match_count.gt(1)].index), "industry_status"] = "industry_ambiguous"
    left.loc[left["_event_row"].isin(valid["_event_row"]), "industry_status"] = "valid"
    return left.drop(columns="_event_row")


def next_trading_days(dates: pd.Series, calendar: pd.DatetimeIndex) -> pd.Series:
    positions = calendar.searchsorted(pd.DatetimeIndex(dates), side="right")
    values = [calendar[position] if position < len(calendar) else pd.NaT for position in positions]
    return pd.Series(values, index=dates.index)


def state_to_months(events: pd.DataFrame, grid: pd.DataFrame, industry: pd.DataFrame, size: pd.DataFrame) -> pd.DataFrame:
    """Create label-free monthly qualification coverage from active events only."""
    size = size.copy()
    size["asof_date"] = pd.to_datetime(size["asof_date"], errors="coerce")
    size["size_control"] = pd.to_numeric(size["size_control"], errors="coerce")
    grid = grid.copy()
    grid["rebalance_date"] = pd.to_datetime(grid["rebalance_date"], errors="coerce")
    grid["asof_date"] = pd.to_datetime(grid["asof_date"], errors="coerce")
    rows = []
    # Pre-sort so choosing the newest available event is deterministic.
    events = events.sort_values(["ts_code", "effective_date", "available_date"], kind="mergesort")
    for _, month in grid.iterrows():
        current = events[events["effective_date"].le(month.rebalance_date) & events["expiry_date"].ge(month.rebalance_date)].copy()
        current = current.sort_values(["ts_code", "effective_date", "available_date"], kind="mergesort").drop_duplicates("ts_code", keep="last")
        if current.empty:
            rows.append({"rebalance_date": month.rebalance_date.strftime("%Y-%m-%d"), "asof_date": month.asof_date.strftime("%Y-%m-%d"), "active_events": 0, "complete_events": 0, "qualified_events": 0, "qualification_coverage": np.nan})
            continue
        # Re-evaluate industry on the monthly control-data date, not announcement date.
        current = current.drop(columns=[column for column in ("l1_code", "l1_name", "industry_status") if column in current])
        current["asof_date"] = month.asof_date
        current = map_industry(current, industry, "asof_date")
        current = current[current["industry_status"].eq("valid") & ~current["l1_code"].isin(FINANCIAL_L1_CODES)].copy()
        current = current.merge(size[size["asof_date"].eq(month.asof_date)][["ts_code", "size_control"]], on="ts_code", how="left")
        complete = current[current["size_control"].notna() & current["profit_yoy_clipped"].notna() & current["revenue_yoy_clipped"].notna() & current["cash_support_flag"].notna()].copy()
        if len(complete) >= 100:
            complete["profit_quintile"] = pd.qcut(complete["profit_yoy_clipped"].rank(method="first"), 5, labels=False) + 1
            complete["revenue_quintile"] = pd.qcut(complete["revenue_yoy_clipped"].rank(method="first"), 5, labels=False) + 1
            qualified = complete[complete["profit_quintile"].ge(4) & complete["revenue_quintile"].ge(4) & complete["cash_support_flag"].eq(True)]
            qualified_count = len(qualified)
        else:
            qualified_count = 0
        rows.append({"rebalance_date": month.rebalance_date.strftime("%Y-%m-%d"), "asof_date": month.asof_date.strftime("%Y-%m-%d"), "active_events": len(current), "complete_events": len(complete), "qualified_events": qualified_count, "qualification_coverage": qualified_count / len(complete) if len(complete) else np.nan})
    return pd.DataFrame(rows)


def main() -> None:
    root = Path(__file__).resolve().parents[2]
    derived = root / "data/derived/a_share_earnings_cash_quality_event_v1"
    audit = root / "output/data_audits/a_share_earnings_cash_quality_event_v1"
    income = load_financial(root, "income", [*KEY, "total_revenue", "n_income", "update_flag", "source_file"])
    cashflow = load_financial(root, "cashflow", [*KEY, "n_cashflow_act", "update_flag", "source_file"])
    print(f"loaded income={len(income)} cashflow={len(cashflow)}", flush=True)
    income_clean, income_dupes, income_conflicts = collapse_same_day(income, "income", ["total_revenue", "n_income"])
    cash_clean, cash_dupes, cash_conflicts = collapse_same_day(cashflow, "cashflow", ["n_cashflow_act"])
    print(f"collapsed income={len(income_clean)} cashflow={len(cash_clean)} conflicts={len(income_conflicts) + len(cash_conflicts)}", flush=True)
    duplicate_audit = pd.concat([income_dupes, cash_dupes], ignore_index=True)
    conflict_audit = pd.concat([income_conflicts, cash_conflicts], ignore_index=True)
    aligned = income_clean.merge(cash_clean[KEY + ["n_cashflow_act", "source_file"]], on=KEY, how="left", suffixes=("_income", "_cashflow"), indicator=True)
    alignment_audit = aligned.loc[aligned["_merge"].ne("both"), KEY + ["_merge"]].rename(columns={"_merge": "alignment_status"})
    events = aligned[aligned["_merge"].eq("both")].drop(columns="_merge").copy()
    for field in ["total_revenue", "n_income", "n_cashflow_act"]:
        events[field] = pd.to_numeric(events[field], errors="coerce")
    events["end_date_dt"] = pd.to_datetime(events["end_date"], format="%Y%m%d", errors="coerce")
    events["period_suffix"] = events["end_date"].str[-4:]
    events["event_year"] = events["end_date_dt"].dt.year
    snapshot = pd.read_csv(root / "data/external/tushare/a_share_financial_pit_v1/full/raw/batch_0001/stock_basic_snapshot.csv.gz", compression="gzip", dtype=str)
    universe = pd.read_csv(root / "output/data_audits/a_share_financial_pit_v1/full/full_audit_v1/frozen_universe_index.csv.gz", compression="gzip", dtype=str)
    snapshot = snapshot[snapshot["ts_code"].isin(set(universe["ts_code"]))][["ts_code", "list_date", "delist_date"]].copy()
    snapshot["list_date"] = pd.to_datetime(snapshot["list_date"], errors="coerce")
    snapshot["delist_date"] = pd.to_datetime(snapshot["delist_date"], errors="coerce")
    events = events.merge(snapshot, on="ts_code", how="left")
    listed = events["list_date"].le(events["available_date"]) & (events["delist_date"].isna() | events["delist_date"].gt(events["available_date"]))
    events["listing_status"] = np.where(listed, "valid", "not_listed_or_delisted")
    industry = pd.read_csv(root / "data/external/tushare/a_share_style_pit_v1/normalized/industry_l1_effective_intervals.csv.gz", compression="gzip", dtype=str)
    events = map_industry(events, industry, "available_date")
    print(f"aligned={len(events)} industry_valid={(events['industry_status'].eq('valid')).sum()}", flush=True)
    events["nonfinancial_status"] = np.where(events["industry_status"].eq("valid") & ~events["l1_code"].isin(FINANCIAL_L1_CODES), "valid", np.where(events["l1_code"].isin(FINANCIAL_L1_CODES), "financial_excluded", events["industry_status"]))
    candidates = events[events["listing_status"].eq("valid") & events["nonfinancial_status"].eq("valid")].copy()
    # Choose the latest eligible prior-year version that was public by the current event.
    prior = candidates[["ts_code", "end_date_dt", "available_date", "n_income", "total_revenue"]].copy()
    prior["target_end_date"] = prior["end_date_dt"] + pd.DateOffset(years=1)
    current = candidates.merge(prior[["ts_code", "target_end_date", "available_date", "n_income", "total_revenue"]], left_on=["ts_code", "end_date_dt"], right_on=["ts_code", "target_end_date"], how="left", suffixes=("", "_prior"))
    current = current[current["available_date_prior"].le(current["available_date"])].copy()
    current = current.sort_values(["ts_code", "end_date", "available_date", "available_date_prior"], kind="mergesort").drop_duplicates(KEY, keep="last")
    print(f"nonfinancial_candidates={len(candidates)} prior_pairs={len(current)}", flush=True)
    all_candidate_keys = candidates[KEY].drop_duplicates()
    pairing_audit = all_candidate_keys.merge(current[KEY], on=KEY, how="left", indicator=True)
    pairing_audit["pairing_status"] = np.where(pairing_audit["_merge"].eq("both"), "paired", "prior_not_available_or_missing")
    pairing_audit = pairing_audit.drop(columns="_merge")
    panel = current.copy()
    panel["profit_median_positive_abs"] = panel.groupby(["event_year", "period_suffix"])["n_income"].transform(lambda value: value[value.gt(0)].abs().median())
    panel["revenue_median_positive_abs"] = panel.groupby(["event_year", "period_suffix"])["total_revenue"].transform(lambda value: value[value.gt(0)].abs().median())
    profit_denom = np.maximum(panel["n_income_prior"].abs(), 0.01 * panel["profit_median_positive_abs"])
    revenue_denom = np.maximum(panel["total_revenue_prior"].abs(), 0.01 * panel["revenue_median_positive_abs"])
    panel["profit_yoy_raw"] = (panel["n_income"] - panel["n_income_prior"]) / profit_denom
    panel["revenue_yoy_raw"] = (panel["total_revenue"] - panel["total_revenue_prior"]) / revenue_denom
    panel.loc[panel["total_revenue"].le(0) | panel["total_revenue_prior"].le(0), "revenue_yoy_raw"] = np.nan
    panel["profit_yoy_clipped"] = panel["profit_yoy_raw"].clip(-5, 5)
    panel["revenue_yoy_clipped"] = panel["revenue_yoy_raw"].clip(-5, 5)
    panel["cash_support_flag"] = panel["n_cashflow_act"].gt(0)
    cash_denom = np.maximum(panel["n_income"].abs(), 0.01 * panel["profit_median_positive_abs"])
    panel["cash_profit_ratio_raw"] = panel["n_cashflow_act"] / cash_denom
    panel["cash_profit_ratio_clipped"] = panel["cash_profit_ratio_raw"].clip(-5, 5)
    panel["profit_state"] = np.select(
        [panel["n_income"].gt(0) & panel["n_income_prior"].gt(0), panel["n_income"].gt(0) & panel["n_income_prior"].le(0), panel["n_income"].le(0) & panel["n_income_prior"].gt(0)],
        ["profit_positive_to_positive", "profit_turnaround", "profit_deterioration"],
        default="profit_loss_to_loss",
    )
    calendar = pd.DatetimeIndex(pd.to_datetime(pd.read_csv(str(Path.home() / ".qlib/qlib_data/cn_data_2026/calendars/day.txt"), header=None)[0], errors="coerce").dropna().sort_values())
    panel["effective_date"] = next_trading_days(panel["available_date"], calendar).values
    effective_positions = calendar.searchsorted(pd.DatetimeIndex(panel["effective_date"]), side="left")
    panel["expiry_date"] = [calendar[position + 119] if not pd.isna(panel["effective_date"].iloc[index]) and position + 119 < len(calendar) else pd.NaT for index, position in enumerate(effective_positions)]
    panel = panel[panel["effective_date"].notna() & panel["expiry_date"].notna()].copy()
    print(f"panel_before_monthly_coverage={len(panel)}", flush=True)
    # Stable event identifiers make later joins auditable without using labels.
    panel["event_id"] = panel.apply(lambda row: f"{row.ts_code}|{row.end_date}|{row.available_date.strftime('%Y-%m-%d')}", axis=1)
    keep = ["event_id", "ts_code", "end_date", "event_year", "period_suffix", "report_type", "available_date", "effective_date", "expiry_date", "l1_code", "l1_name", "total_revenue", "n_income", "n_cashflow_act", "total_revenue_prior", "n_income_prior", "profit_yoy_raw", "profit_yoy_clipped", "revenue_yoy_raw", "revenue_yoy_clipped", "cash_support_flag", "cash_profit_ratio_raw", "cash_profit_ratio_clipped", "profit_state", "profit_median_positive_abs", "revenue_median_positive_abs"]
    panel = panel[keep].sort_values(["effective_date", "ts_code"], kind="mergesort").reset_index(drop=True)
    atomic_csv(panel, derived / "event_panel.csv.gz")
    atomic_csv(duplicate_audit, audit / "same_day_duplicate_audit.csv.gz")
    atomic_csv(conflict_audit, audit / "same_day_value_conflict.csv.gz")
    atomic_csv(alignment_audit, audit / "statement_alignment_audit.csv.gz")
    atomic_csv(pairing_audit, audit / "prior_year_pairing_audit.csv.gz")
    coverage = panel.groupby(["event_year", "period_suffix"], dropna=False).agg(events=("event_id", "size"), companies=("ts_code", "nunique"), cash_support_rate=("cash_support_flag", "mean")).reset_index()
    atomic_csv(coverage, audit / "coverage_by_event_year_and_period.csv")
    distributions = panel.groupby(["event_year", "period_suffix"], dropna=False).agg(profit_yoy_p01=("profit_yoy_raw", lambda value: value.quantile(.01)), profit_yoy_p50=("profit_yoy_raw", "median"), profit_yoy_p99=("profit_yoy_raw", lambda value: value.quantile(.99)), revenue_yoy_p01=("revenue_yoy_raw", lambda value: value.quantile(.01)), revenue_yoy_p50=("revenue_yoy_raw", "median"), revenue_yoy_p99=("revenue_yoy_raw", lambda value: value.quantile(.99)), cash_ratio_p01=("cash_profit_ratio_raw", lambda value: value.quantile(.01)), cash_ratio_p50=("cash_profit_ratio_raw", "median"), cash_ratio_p99=("cash_profit_ratio_raw", lambda value: value.quantile(.99))).reset_index()
    atomic_csv(distributions, audit / "variable_distribution_by_event_year_and_period.csv")
    grid = pd.read_csv(root / "data/external/tushare/a_share_style_pit_v1/normalized/monthly_rebalance_grid.csv.gz", compression="gzip", dtype=str)
    size = pd.read_csv(root / "data/external/tushare/a_share_style_pit_v1/normalized/monthly_free_float_size.csv.gz", compression="gzip", dtype=str)
    qualification = state_to_months(panel, grid, industry, size)
    print(f"monthly_qualification_rows={len(qualification)}", flush=True)
    atomic_csv(qualification, audit / "qualification_coverage_by_rebalance_month.csv")
    methodology = {"version": "v1", "label_access": False, "same_day_conflict_policy": "exclude_event", "prior_pairing": "latest prior-year same-period version public no later than current event", "yoy_floor": "1 percent of same event-year and report-period positive-value median", "yoy_clip": [-5.0, 5.0], "cash_support": "n_cashflow_act > 0", "holding_window": "120 Qlib CN trading days", "financial_l1_exclusions": sorted(FINANCIAL_L1_CODES)}
    atomic_json(methodology, audit / "methodology.json")
    report = (
        "沪深非金融 A 股盈利改善与现金流质量事件面板无标签审计 v1\n"
        "status: event_panel_ready_for_label_protocol_review\n"
        f"eligible_aligned_events_before_prior_pairing: {len(candidates)}\n"
        f"event_panel_rows: {len(panel)}; companies: {panel['ts_code'].nunique()}\n"
        f"same_day_identical_duplicates: {len(duplicate_audit)}\n"
        f"same_day_value_conflicts_excluded: {len(conflict_audit)}\n"
        f"statement_alignment_missing: {len(alignment_audit)}\n"
        f"prior_year_not_available_or_missing: {int(pairing_audit['pairing_status'].ne('paired').sum())}\n"
        f"minimum_monthly_complete_events: {int(qualification['complete_events'].min())}\n"
        "未读取收益、未构建标签、未计算 IC、未训练模型、未回测。\n"
    )
    (audit / "event_panel_audit_report.txt").write_text(report, encoding="utf-8")
    print(report, end="")


if __name__ == "__main__":
    main()
