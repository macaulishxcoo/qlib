#!/usr/bin/env python3
"""Rolling-window retraining diagnosis for the Core13 Alpha158 residuals (2021 onward).

Answers the frozen protocol question: under rolling retraining with market-cap and
industry as explicit model features, how much predictive power do the 13 residual
price-volume factors retain over 2021-2026?

Design (frozen by research/protocols/csi1000_core13_rolling_window_protocol_v1.md):
- Universe: Qlib CSI1000 point-in-time historical constituents (delisted kept).
- Label: Ref($close,-2)/Ref($close,-1)-1.
- Features V1: 13 fixed Core13 factors only.
- Features V2: 13 factors + log(free-float market cap) + SW L1 industry dummies.
- Rolling: every 63 trading days retrain; train = prior 504 sessions,
  valid = 252 sessions before node (early stopping), predict = next 63 sessions.
- Model: qlib LGBModel hyper-parameters identical to frozen B_core13.
- No future leakage: market cap monthly PIT aligned to its rebalance_date
  (first trading day the month-end value is usable) and forward-filled daily.

Outputs are written only under:
    output/analysis_static/csi1000_core13_rolling_2021onward_v1/
"""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

import lightgbm as lgb
import numpy as np
import pandas as pd

import qlib
from qlib.config import REG_CN
from qlib.data import D
from qlib.contrib.evaluate import backtest_daily, risk_analysis
from qlib.contrib.strategy import TopkDropoutStrategy

CORE13_FIELDS = [
    "Std($close, 5)/$close",
    "($high-$low)/$open",
    "Std($close, 10)/$close",
    "Std($close, 60)/$close",
    "Std($close, 20)/$close",
    "Min($low, 60)/$close",
    "$high/$close",
    "Corr($close/Ref($close,1), Log($volume/Ref($volume, 1)+1), 20)",
    "Corr($close, Log($volume+1), 10)",
    "Max($high, 5)/$close",
    "($high-Greater($open, $close))/$open",
    "Corr($close, Log($volume+1), 20)",
    "Corr($close/Ref($close,1), Log($volume/Ref($volume, 1)+1), 10)",
]
CORE13_NAMES = ["STD5", "KLEN", "STD10", "STD60", "STD20", "MIN60", "HIGH0", "CORD20", "CORR10", "MAX5", "KUP", "CORR20", "CORD10"]
LABEL_FIELD = "Ref($close, -2)/Ref($close, -1) - 1"

LGB_PARAMS = {
    "objective": "regression",
    "metric": "l2",
    "learning_rate": 0.1,
    "colsample_bytree": 0.9,
    "subsample": 0.9,
    "lambda_l1": 205.6999,
    "lambda_l2": 580.9768,
    "max_depth": 8,
    "num_leaves": 250,
    "num_threads": 20,
    "verbosity": -1,
    "seed": 0,
}

TRAIN_DAYS = 504   # ~2 years
VALID_DAYS = 252   # ~1 year
NODE_STEP = 63     # ~1 quarter
TOP_K = 50
N_DROP = 5
ACCOUNT = 100_000_000
BENCHMARK = "SH000852"
EVAL_START = pd.Timestamp("2021-01-01")
DATA_START = pd.Timestamp("2017-11-01")  # covers warmup + earliest train window
DATA_END = pd.Timestamp("2026-07-23")
ANNUALIZATION_DAYS = 238
COST_SCENARIOS = {
    "base": {"open_cost": 0.0005, "close_cost": 0.0015},
    "stress": {"open_cost": 0.0010, "close_cost": 0.0030},
}

STYLE_SIZE = Path("data/external/tushare/a_share_style_pit_v1/normalized/monthly_free_float_size.csv.gz")
STYLE_INDUSTRY = Path("data/external/tushare/a_share_style_pit_v1/normalized/industry_l1_effective_intervals.csv.gz")
NEUTRAL_2025 = Path("data/external/tushare/csi1000_neutralization_2025-01-01_2026-07-23")


def ext_to_qlib(code: str) -> str:
    """'600519.SH' -> 'SH600519'"""
    number, suffix = code.split(".")
    return f"{suffix}{number}"


def load_market_cap(dates: pd.DatetimeIndex) -> pd.DataFrame:
    """Load free-float market cap as (datetime, qlib_code) wide log frame.

    Monthly PIT records are aligned to their rebalance_date (the first trading
    day the month-end value becomes usable), then forward-filled to daily
    frequency. 2025-06 onward is appended from the daily csi1000_neutralization
    data. Wide frame index=dates, columns=qlib codes.
    """
    monthly = pd.read_csv(
        STYLE_SIZE,
        compression="gzip",
        usecols=["ts_code", "rebalance_date", "free_float_market_value"],
        dtype={"ts_code": str, "rebalance_date": str},
    )
    monthly = monthly.dropna(subset=["free_float_market_value", "rebalance_date"]).copy()
    monthly["asof"] = pd.to_datetime(monthly["rebalance_date"], errors="coerce")
    monthly = monthly.dropna(subset=["asof"]).drop(columns=["rebalance_date"])
    monthly["code"] = monthly["ts_code"].map(ext_to_qlib)
    monthly["log_mktcap"] = np.log(monthly["free_float_market_value"])
    wide = monthly.pivot_table(index="asof", columns="code", values="log_mktcap", aggfunc="last").sort_index()

    daily_file = NEUTRAL_2025 / "daily_basic_csi1000.csv.gz"
    if not daily_file.exists():
        daily_file = NEUTRAL_2025 / "daily_basic.csv.gz"
    daily = pd.read_csv(
        daily_file,
        compression="gzip",
        usecols=["ts_code", "trade_date", "close", "free_share"],
        dtype={"ts_code": str, "trade_date": str},
    )
    daily["asof"] = pd.to_datetime(daily["trade_date"])
    daily["log_mktcap"] = np.log(
        pd.to_numeric(daily["close"], errors="coerce") * pd.to_numeric(daily["free_share"], errors="coerce")
    )
    daily = daily.replace([np.inf, -np.inf], np.nan).dropna(subset=["log_mktcap"])
    daily["code"] = daily["ts_code"].map(ext_to_qlib)
    daily_wide = daily.pivot_table(index="asof", columns="code", values="log_mktcap", aggfunc="last").sort_index()

    combined = pd.concat([wide, daily_wide]).sort_index()
    # Ensure no duplicate asof columns conflict; dedupe by index then ffill on trading days
    combined = combined[~combined.index.duplicated(keep="last")]
    return combined.reindex(dates).ffill().reindex(columns=sorted(combined.columns))


def load_industry(dates: pd.DatetimeIndex) -> pd.DataFrame:
    """Load SW L1 industry PIT effective intervals as long (datetime, code, ind_code).

    Deduplicates overlapping intervals per (datetime, code): the last record
    wins, which matches the Tushare index_member_all revision semantics.
    """
    ind = pd.read_csv(
        STYLE_INDUSTRY,
        compression="gzip",
        usecols=["l1_code", "ts_code", "in_date", "out_date"],
        dtype=str,
    )
    ind["in_date"] = pd.to_datetime(ind["in_date"], errors="coerce")
    ind["out_date"] = pd.to_datetime(ind["out_date"], errors="coerce")
    ind["code"] = ind["ts_code"].map(ext_to_qlib)
    ind = ind[["code", "l1_code", "in_date", "out_date"]].dropna(subset=["in_date"])

    for sub in ("industry_member_history_csi1000.csv.gz", "industry_member_history.csv.gz"):
        path = NEUTRAL_2025 / sub
        if path.exists():
            extra = pd.read_csv(
                path,
                compression="gzip",
                usecols=["ts_code", "l1_code", "in_date", "out_date"],
                dtype=str,
            )
            extra["in_date"] = pd.to_datetime(extra["in_date"], errors="coerce")
            extra["out_date"] = pd.to_datetime(extra["out_date"], errors="coerce")
            extra["code"] = extra["ts_code"].map(ext_to_qlib)
            extra = extra[["code", "l1_code", "in_date", "out_date"]].dropna(subset=["in_date"])
            ind = pd.concat([ind, extra], ignore_index=True)
            break

    end_default = dates.max() + pd.Timedelta(days=1)
    blocks = []
    for _, row in ind.iterrows():
        end = row["out_date"] if pd.notna(row["out_date"]) else end_default
        active = dates[(dates >= row["in_date"]) & (dates < end)]
        if len(active):
            blocks.append(
                pd.DataFrame({"datetime": active, "code": row["code"], "ind_code": row["l1_code"]})
            )
    long = pd.concat(blocks, ignore_index=True) if blocks else pd.DataFrame(
        columns=["datetime", "code", "ind_code"]
    )
    return long.drop_duplicates(subset=["datetime", "code"], keep="last")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--qlib-data-dir", type=Path, default=Path("~/.qlib/qlib_data/cn_data_2026").expanduser())
    parser.add_argument("--output-dir", type=Path, default=Path("output/analysis_static/csi1000_core13_rolling_2021onward_v1"))
    parser.add_argument("--no-backtest", action="store_true", help="skip portfolio backtest (IC-only mode)")
    args = parser.parse_args()

    if args.output_dir.exists() and any(args.output_dir.iterdir()):
        raise FileExistsError(f"Refusing to overwrite existing experiment output: {args.output_dir}")
    args.output_dir.mkdir(parents=True, exist_ok=True)

    qlib.init(provider_uri=str(args.qlib_data_dir), region=REG_CN)
    calendar = pd.to_datetime(pd.read_csv(args.qlib_data_dir / "calendars" / "day.txt", header=None)[0])

    # ---- 1. Features & label ---------------------------------------------------
    print("[1/6] Loading features/label from qlib ...", flush=True)
    raw = D.features(
        D.instruments("csi1000"),
        CORE13_FIELDS + [LABEL_FIELD],
        start_time=DATA_START,
        end_time=DATA_END,
        freq="day",
    )
    raw.columns = CORE13_NAMES + ["label"]
    raw = raw.sort_index()
    raw = raw.reset_index()
    raw.columns = ["instrument", "datetime"] + list(raw.columns[2:])
    print(f"      raw rows={len(raw)}", flush=True)

    # ---- 2. PIT market-cap & industry ------------------------------------------
    print("[2/6] Loading PIT market cap & industry ...", flush=True)
    dates = pd.DatetimeIndex(sorted(raw["datetime"].unique()))
    mkt_wide = load_market_cap(dates)
    ind_long = load_industry(dates)
    print(f"      mktcap wide={mkt_wide.shape}, industry long={ind_long.shape}", flush=True)

    mkt_long = mkt_wide.stack().rename("log_mktcap").reset_index()
    mkt_long.columns = ["datetime", "code", "log_mktcap"]
    mkt_long = mkt_long.drop_duplicates(subset=["datetime", "code"], keep="last")

    raw = raw.merge(mkt_long, left_on=["datetime", "instrument"], right_on=["datetime", "code"], how="left").drop(columns=["code"])
    raw = raw.merge(ind_long, left_on=["datetime", "instrument"], right_on=["datetime", "code"], how="left").drop(columns=["code"])

    # One-hot SW L1 industry once, for the whole frame
    ind_dummies = pd.get_dummies(raw["ind_code"].astype(str), prefix="ind", dtype=np.float32)
    raw = pd.concat([raw, ind_dummies], axis=1)
    raw = raw.set_index(["datetime", "instrument"]).sort_index()
    industry_cols = list(ind_dummies.columns)
    print(f"      industry dummies: {len(industry_cols)}", flush=True)

    # ---- 3. Rolling node schedule -----------------------------------------------
    print("[3/6] Building rolling node schedule ...", flush=True)
    start_idx = calendar.searchsorted(EVAL_START)
    nodes = []
    idx = start_idx
    while idx + NODE_STEP - 1 < len(calendar):
        nodes.append(calendar[idx])
        idx += NODE_STEP
    print(f"      {len(nodes)} nodes: {nodes[0].date()} .. {nodes[-1].date()}", flush=True)

    feature_v1 = CORE13_NAMES
    feature_v2 = CORE13_NAMES + ["log_mktcap"] + industry_cols

    def slice_window(d0: pd.Timestamp, d1: pd.Timestamp) -> pd.DataFrame:
        return raw.loc[pd.Timestamp(d0): pd.Timestamp(d1)]

    preds: dict[str, pd.Series] = {}
    node_models: dict[tuple[str, str], lgb.Booster] = {}

    for version, use_style in [("V1_core13_plain", False), ("V2_core13_size_ind", True)]:
        print(f"[4/6] Rolling retrain {version} ...", flush=True)
        feats = feature_v2 if use_style else feature_v1
        seg_preds = []
        for node in nodes:
            node_pos = calendar.searchsorted(node)
            if node_pos - VALID_DAYS - TRAIN_DAYS < 0:
                continue
            train_d0 = calendar[node_pos - TRAIN_DAYS - VALID_DAYS]
            valid_d0 = calendar[node_pos - VALID_DAYS]
            pred_d0 = calendar[node_pos]
            pred_d1 = calendar[min(node_pos + NODE_STEP - 1, len(calendar) - 1)]

            tr = slice_window(train_d0, calendar[node_pos - VALID_DAYS - 1])
            va = slice_window(valid_d0, calendar[node_pos - 1])
            pr = slice_window(pred_d0, pred_d1)

            X_tr, y_tr = tr[feats].astype(np.float32), tr["label"]
            X_va, y_va = va[feats].astype(np.float32), va["label"]
            X_pr = pr[feats].astype(np.float32)

            def clean(X, y=None):
                mask = X.notna().all(axis=1)
                if y is not None:
                    mask = mask & y.notna()
                X = X[mask]
                y = y[mask] if y is not None else None
                return X, y

            X_tr, y_tr = clean(X_tr, y_tr)
            X_va, y_va = clean(X_va, y_va)
            X_pr, _ = clean(X_pr)

            if len(X_tr) < 10_000 or len(X_va) < 1_000 or len(X_pr) < 100:
                print(f"      node {node.date()}: insufficient samples "
                      f"(train={len(X_tr)}, valid={len(X_va)}, pred={len(X_pr)}), skip", flush=True)
                continue

            # CSZScoreNorm on the label, statistics fitted on the train window
            # only (no future leakage). This matches the frozen B_core13 handler
            # and keeps the large lambda_l1/l2 regularization on the same scale.
            y_mu, y_sigma = float(y_tr.mean()), float(y_tr.std())
            if not np.isfinite(y_sigma) or y_sigma < 1e-12:
                print(f"      node {node.date()}: degenerate train label sigma, skip", flush=True)
                continue
            y_tr_n = (y_tr - y_mu) / y_sigma
            y_va_n = (y_va - y_mu) / y_sigma

            dtr = lgb.Dataset(X_tr, label=y_tr_n)
            dva = lgb.Dataset(X_va, label=y_va_n, reference=dtr)
            booster = lgb.train(
                LGB_PARAMS,
                dtr,
                num_boost_round=3000,
                valid_sets=[dva],
                callbacks=[lgb.early_stopping(50, verbose=False)],
            )
            node_models[(version, node.date().isoformat())] = booster

            score = pd.Series(
                booster.predict(X_pr, num_iteration=booster.best_iteration),
                index=X_pr.index,
                name="score",
            )
            seg_preds.append(score)
            print(f"      node {node.date()} -> pred {pred_d0.date()}..{pred_d1.date()} "
                  f"best_iter={booster.best_iteration} n={len(score)}", flush=True)
        if seg_preds:
            preds[version] = pd.concat(seg_preds).sort_index()
            print(f"      {version}: total pred rows={len(preds[version])}", flush=True)

    # ---- 5. Persist predictions & models ----------------------------------------
    print("[5/6] Saving predictions & models ...", flush=True)
    for version, series in preds.items():
        series.to_frame("score").to_pickle(args.output_dir / f"predictions_{version}.pkl")
    models_dir = args.output_dir / "models"
    models_dir.mkdir(exist_ok=True)
    for (version, node_str), booster in node_models.items():
        booster.save_model(models_dir / f"{version}__{node_str}.txt")
    print(f"      saved {len(node_models)} node models to {models_dir}", flush=True)

    # ---- 6. Evaluation ------------------------------------------------------------
    print("[6/6] Evaluating IC & backtest ...", flush=True)
    label_series = raw["label"]
    rows = []
    for version, series in preds.items():
        if not len(series):
            continue
        merged = pd.DataFrame({"score": series, "label": label_series.reindex(series.index)}).dropna()
        merged = merged[merged.index.get_level_values("datetime") >= EVAL_START]
        daily_ic = merged.groupby(level="datetime").apply(
            lambda x: pd.Series({
                "ic": x["score"].corr(x["label"]),
                "rank_ic": x["score"].corr(x["label"], method="spearman"),
                "count": len(x),
            })
        )
        daily_ic = daily_ic[daily_ic["count"] >= 50]
        daily_ic.to_csv(args.output_dir / f"daily_ic_{version}.csv.gz", compression="gzip")

        yearly = pd.DataFrame([
            {
                "version": version, "year": int(year), "days": int(len(g)),
                "ic_mean": float(g["ic"].mean()),
                "icir": float(g["ic"].mean() / g["ic"].std()) if g["ic"].std() > 0 else np.nan,
                "rank_ic_mean": float(g["rank_ic"].mean()),
                "rank_icir": float(g["rank_ic"].mean() / g["rank_ic"].std()) if g["rank_ic"].std() > 0 else np.nan,
                "ic_positive_ratio": float((g["ic"] > 0).mean()),
            }
            for year, g in daily_ic.groupby(daily_ic.index.year)
        ])
        yearly.to_csv(args.output_dir / f"yearly_ic_{version}.csv", index=False)
        ic_sum = pd.DataFrame({
            "version": [version],
            "ic_mean": [daily_ic["ic"].mean()],
            "icir": [daily_ic["ic"].mean() / daily_ic["ic"].std()],
            "rank_ic_mean": [daily_ic["rank_ic"].mean()],
            "rank_icir": [daily_ic["rank_ic"].mean() / daily_ic["rank_ic"].std()],
            "ic_positive_ratio": [(daily_ic["ic"] > 0).mean()],
            "days": [len(daily_ic)],
        })
        ic_sum.to_csv(args.output_dir / f"ic_summary_{version}.csv", index=False)
        rows.append((version, daily_ic, yearly))

    backtest_df = pd.DataFrame()
    if not args.no_backtest:
        bt_rows = []
        for version, series in preds.items():
            if not len(series):
                continue
            pred_win = series[series.index.get_level_values("datetime") >= EVAL_START]
            for scenario, costs in COST_SCENARIOS.items():
                strategy = TopkDropoutStrategy(signal=pred_win, topk=TOP_K, n_drop=N_DROP)
                report, _ = backtest_daily(
                    start_time=EVAL_START, end_time=DATA_END, strategy=strategy,
                    account=ACCOUNT, benchmark=BENCHMARK,
                    exchange_kwargs={
                        "limit_threshold": 0.095, "deal_price": "close",
                        "open_cost": costs["open_cost"], "close_cost": costs["close_cost"],
                        "min_cost": 5,
                    },
                )
                excess_wo = report["return"] - report["bench"]
                excess_w = report["return"] - report["bench"] - report["cost"]
                res_wo = risk_analysis(excess_wo, freq="day")["risk"]
                res_w = risk_analysis(excess_w, freq="day")["risk"]
                bt_rows.append({
                    "version": version, "cost_scenario": scenario,
                    "start_date": str(report.index.min().date()), "end_date": str(report.index.max().date()),
                    "trading_days": int(len(report)),
                    "gross_excess_annualized_return": float(res_wo["annualized_return"]),
                    "gross_excess_ir": float(res_wo["information_ratio"]),
                    "gross_excess_max_drawdown": float(res_wo["max_drawdown"]),
                    "net_excess_annualized_return": float(res_w["annualized_return"]),
                    "net_excess_ir": float(res_w["information_ratio"]),
                    "net_excess_max_drawdown": float(res_w["max_drawdown"]),
                    "average_daily_turnover_rate": float(report["turnover"].mean()),
                    "annualized_cost_drag": float(report["cost"].mean() * ANNUALIZATION_DAYS),
                    "benchmark_annualized_return": float(risk_analysis(report["bench"], freq="day")["risk"]["annualized_return"]),
                })
                print(f"      backtest {version} [{scenario}] done", flush=True)
        backtest_df = pd.DataFrame(bt_rows)
        backtest_df.to_csv(args.output_dir / "backtest_summary.csv", index=False)

    metadata = {
        "purpose": "Rolling-window retraining diagnosis of Core13 Alpha158 residuals with style features",
        "protocol": "research/protocols/csi1000_core13_rolling_window_protocol_v1.md",
        "universe": "Qlib CSI1000 historical daily constituents (PIT, delisted kept)",
        "label": LABEL_FIELD,
        "eval_window": [str(EVAL_START.date()), str(DATA_END.date())],
        "node_step_days": NODE_STEP,
        "train_days": TRAIN_DAYS,
        "valid_days": VALID_DAYS,
        "lgb_params": LGB_PARAMS,
        "feature_versions": {"V1_core13_plain": feature_v1, "V2_core13_size_ind": feature_v2},
        "node_count": len(nodes),
        "node_model_files": len(node_models),
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
    }
    (args.output_dir / "metadata.json").write_text(json.dumps(metadata, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    # ---- Report -----------------------------------------------------------------
    lines = [
        "CSI1000 Core13 滚动窗口重训诊断 v1（2021-2026）",
        "=" * 64,
        "",
        "目的：量化滚动重训 + 市值/行业显式特征下，Alpha158 残余 13 因子的真实预测力。",
        "标签：Ref($close,-2)/Ref($close,-1)-1；股票池：Qlib CSI1000 历史 PIT 成分（含退市）。",
        "滚动规则：每 63 交易日重训；训练=节点前 504 日，验证=节点前 252 日（早停），预测=节点后 63 日。",
        "模型：LGBModel，超参与冻结 B_core13 完全一致。V1=13 因子；V2=13 因子+log(自由流通市值)+申万一级行业哑变量。",
        "",
        "一、全期日频 IC：",
        "=" * 64,
    ]
    for version, daily_ic, yearly in rows:
        m = {
            "IC均值": daily_ic["ic"].mean(), "ICIR": daily_ic["ic"].mean() / daily_ic["ic"].std(),
            "RankIC均值": daily_ic["rank_ic"].mean(), "RankICIR": daily_ic["rank_ic"].mean() / daily_ic["rank_ic"].std(),
            "IC>0占比": (daily_ic["ic"] > 0).mean(), "有效天数": len(daily_ic),
        }
        lines.append(f"  {version}: " + " | ".join(f"{k}={v:.4f}" for k, v in m.items()))
    lines += ["", "二、分年 IC：", "=" * 64]
    for version, daily_ic, yearly in rows:
        lines.append(f"  {version}:")
        for _, r in yearly.iterrows():
            lines.append(
                f"    {int(r['year'])}: days={int(r['days'])} IC={r['ic_mean']:.4f} ICIR={r['icir']:.4f} "
                f"RankIC={r['rank_ic_mean']:.4f} pos={(r['ic_positive_ratio']*100):.1f}%"
            )
    if len(backtest_df):
        lines += ["", "三、回测（TopkDropout topk=50, n_drop=5；基准 SH000852）：", "=" * 64]
        for _, r in backtest_df.iterrows():
            lines.append(
                f"  {r['version']} [{r['cost_scenario']}]: 费前超额 {r['gross_excess_annualized_return']*100:.2f}%/yr "
                f"IR={r['gross_excess_ir']:.3f} | 费后超额 {r['net_excess_annualized_return']*100:.2f}%/yr "
                f"IR={r['net_excess_ir']:.3f} 回撤={r['net_excess_max_drawdown']*100:.2f}% "
                f"换手={r['average_daily_turnover_rate']*100:.1f}% 成本损耗={r['annualized_cost_drag']*100:.2f}%/yr"
            )
    lines += ["", "结论边界：本实验是诊断，不授权部署；运行后停止，等待用户审查。"]
    (args.output_dir / "rolling_report.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("\n".join(lines))


if __name__ == "__main__":
    main()
