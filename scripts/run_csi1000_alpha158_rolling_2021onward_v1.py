#!/usr/bin/env python3
"""Rolling-window retraining diagnosis for ALL 158 Alpha158 factors (2021 onward).

Answers the frozen protocol question: under rolling retraining, how much
predictive power do the FULL 158 Alpha158 price-volume factors retain over
2021-2026? This is the signal-source evidence for ROADMAP stage 2.

Design (frozen by research/protocols/csi1000_alpha158_rolling_window_protocol_v1.md):
- Universe: Qlib CSI1000 point-in-time historical constituents (delisted kept).
- Label: Ref($close,-2)/Ref($close,-1)-1, CSZScoreNorm fitted on train window only.
- Features: all 158 Alpha158 expressions (Alpha158DL default kbar/price/rolling).
- Rolling: every 63 trading days retrain; train = prior 504 sessions,
  valid = 252 sessions before node (early stopping), predict = next 63 sessions.
- Model: qlib LGBModel hyper-parameters identical to frozen B_core13.
- Single version (no market-cap/industry features, proven non-additive for Core13).

Outputs are written only under:
    output/analysis_static/csi1000_alpha158_rolling_2021onward_v1/
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
from qlib.contrib.data.loader import Alpha158DL
from qlib.contrib.evaluate import backtest_daily, risk_analysis
from qlib.contrib.strategy import TopkDropoutStrategy

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
DATA_START = pd.Timestamp("2017-11-01")
DATA_END = pd.Timestamp("2026-07-23")
ANNUALIZATION_DAYS = 238
COST_SCENARIOS = {
    "base": {"open_cost": 0.0005, "close_cost": 0.0015},
    "stress": {"open_cost": 0.0010, "close_cost": 0.0030},
}


def alpha158_definitions() -> tuple[list[str], list[str]]:
    """Get all 158 raw expressions and their canonical Alpha158 names."""
    return Alpha158DL.get_feature_config(
        {
            "kbar": {},
            "price": {"windows": [0], "feature": ["OPEN", "HIGH", "LOW", "VWAP"]},
            "rolling": {},
        }
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--qlib-data-dir", type=Path, default=Path("~/.qlib/qlib_data/cn_data_2026").expanduser())
    parser.add_argument("--output-dir", type=Path, default=Path("output/analysis_static/csi1000_alpha158_rolling_2021onward_v1"))
    parser.add_argument("--no-backtest", action="store_true", help="skip portfolio backtest (IC-only mode)")
    args = parser.parse_args()

    if args.output_dir.exists() and any(args.output_dir.iterdir()):
        raise FileExistsError(f"Refusing to overwrite existing experiment output: {args.output_dir}")
    args.output_dir.mkdir(parents=True, exist_ok=True)

    fields, names = alpha158_definitions()
    if len(fields) != 158 or len(set(names)) != 158:
        raise RuntimeError("Alpha158 definition does not contain 158 unique factors")

    qlib.init(provider_uri=str(args.qlib_data_dir), region=REG_CN)
    calendar = pd.to_datetime(pd.read_csv(args.qlib_data_dir / "calendars" / "day.txt", header=None)[0])

    # ---- 1. Features & label ---------------------------------------------------
    print("[1/5] Loading 158 features/label from qlib ...", flush=True)
    raw = D.features(
        D.instruments("csi1000"),
        fields + [LABEL_FIELD],
        start_time=DATA_START,
        end_time=DATA_END,
        freq="day",
    )
    raw.columns = names + ["label"]
    raw = raw.sort_index().reset_index()
    raw.columns = ["instrument", "datetime"] + list(raw.columns[2:])
    raw = raw.set_index(["datetime", "instrument"]).sort_index()
    print(f"      raw rows={len(raw)}, features={len(names)}", flush=True)

    # ---- 2. Rolling node schedule ----------------------------------------------
    print("[2/5] Building rolling node schedule ...", flush=True)
    start_idx = calendar.searchsorted(EVAL_START)
    nodes = []
    idx = start_idx
    while idx + NODE_STEP - 1 < len(calendar):
        nodes.append(calendar[idx])
        idx += NODE_STEP
    print(f"      {len(nodes)} nodes: {nodes[0].date()} .. {nodes[-1].date()}", flush=True)

    def slice_window(d0: pd.Timestamp, d1: pd.Timestamp) -> pd.DataFrame:
        return raw.loc[pd.Timestamp(d0): pd.Timestamp(d1)]

    # ---- 3. Rolling retrain -----------------------------------------------------
    print("[3/5] Rolling retrain (158 features) ...", flush=True)
    seg_preds = []
    node_models: dict[str, lgb.Booster] = {}
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

        X_tr, y_tr = tr[names].astype(np.float32), tr["label"]
        X_va, y_va = va[names].astype(np.float32), va["label"]
        X_pr = pr[names].astype(np.float32)

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

        # CSZScoreNorm on label, statistics fitted on train window only.
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
        node_models[node.date().isoformat()] = booster

        score = pd.Series(
            booster.predict(X_pr, num_iteration=booster.best_iteration),
            index=X_pr.index,
            name="score",
        )
        seg_preds.append(score)
        print(f"      node {node.date()} -> pred {pred_d0.date()}..{pred_d1.date()} "
              f"best_iter={booster.best_iteration} n={len(score)}", flush=True)

    predictions = pd.concat(seg_preds).sort_index()
    print(f"      total pred rows={len(predictions)}", flush=True)

    # ---- 4. Persist predictions & models ----------------------------------------
    print("[4/5] Saving predictions & models ...", flush=True)
    predictions.to_frame("score").to_pickle(args.output_dir / "predictions.pkl")
    models_dir = args.output_dir / "models"
    models_dir.mkdir(exist_ok=True)
    for node_str, booster in node_models.items():
        booster.save_model(models_dir / f"{node_str}.txt")
    print(f"      saved {len(node_models)} node models to {models_dir}", flush=True)

    # ---- 5. Evaluation ------------------------------------------------------------
    print("[5/5] Evaluating IC & backtest ...", flush=True)
    label_series = raw["label"]
    merged = pd.DataFrame({"score": predictions, "label": label_series.reindex(predictions.index)}).dropna()
    merged = merged[merged.index.get_level_values("datetime") >= EVAL_START]
    daily_ic = merged.groupby(level="datetime").apply(
        lambda x: pd.Series({
            "ic": x["score"].corr(x["label"]),
            "rank_ic": x["score"].corr(x["label"], method="spearman"),
            "count": len(x),
        })
    )
    daily_ic = daily_ic[daily_ic["count"] >= 50]
    daily_ic.to_csv(args.output_dir / "daily_ic.csv.gz", compression="gzip")

    yearly = pd.DataFrame([
        {
            "year": int(year), "days": int(len(g)),
            "ic_mean": float(g["ic"].mean()),
            "icir": float(g["ic"].mean() / g["ic"].std()) if g["ic"].std() > 0 else np.nan,
            "rank_ic_mean": float(g["rank_ic"].mean()),
            "rank_icir": float(g["rank_ic"].mean() / g["rank_ic"].std()) if g["rank_ic"].std() > 0 else np.nan,
            "ic_positive_ratio": float((g["ic"] > 0).mean()),
        }
        for year, g in daily_ic.groupby(daily_ic.index.year)
    ])
    yearly.to_csv(args.output_dir / "yearly_ic.csv", index=False)

    ic_sum = pd.DataFrame({
        "ic_mean": [daily_ic["ic"].mean()],
        "icir": [daily_ic["ic"].mean() / daily_ic["ic"].std()],
        "rank_ic_mean": [daily_ic["rank_ic"].mean()],
        "rank_icir": [daily_ic["rank_ic"].mean() / daily_ic["rank_ic"].std()],
        "ic_positive_ratio": [(daily_ic["ic"] > 0).mean()],
        "days": [len(daily_ic)],
    })
    ic_sum.to_csv(args.output_dir / "ic_summary.csv", index=False)

    backtest_df = pd.DataFrame()
    if not args.no_backtest:
        bt_rows = []
        pred_win = predictions[predictions.index.get_level_values("datetime") >= EVAL_START]
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
                "cost_scenario": scenario,
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
            print(f"      backtest [{scenario}] done", flush=True)
        backtest_df = pd.DataFrame(bt_rows)
        backtest_df.to_csv(args.output_dir / "backtest_summary.csv", index=False)

    metadata = {
        "purpose": "Rolling-window retraining diagnosis of ALL 158 Alpha158 factors (stage-2 signal source evidence)",
        "protocol": "research/protocols/csi1000_alpha158_rolling_window_protocol_v1.md",
        "universe": "Qlib CSI1000 historical daily constituents (PIT, delisted kept)",
        "label": LABEL_FIELD,
        "label_preprocessing": "CSZScoreNorm fitted on train window only",
        "feature_count": len(names),
        "eval_window": [str(EVAL_START.date()), str(DATA_END.date())],
        "node_step_days": NODE_STEP,
        "train_days": TRAIN_DAYS,
        "valid_days": VALID_DAYS,
        "lgb_params": LGB_PARAMS,
        "node_count": len(nodes),
        "node_model_files": len(node_models),
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
    }
    (args.output_dir / "metadata.json").write_text(json.dumps(metadata, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    # ---- Report -----------------------------------------------------------------
    lines = [
        "CSI1000 全量 Alpha158 滚动窗口重训诊断 v1（2021-2026）",
        "=" * 64,
        "",
        "目的：评估全量 158 因子在滚动重训下的真实预测力，作为阶段 2 信号源选择的证据。",
        "标签：Ref($close,-2)/Ref($close,-1)-1（训练窗 CSZScoreNorm）；股票池：Qlib CSI1000 历史 PIT 成分（含退市）。",
        "滚动规则：每 63 交易日重训；训练=节点前 504 日，验证=节点前 252 日（早停），预测=节点后 63 日。",
        "模型：LGBModel，超参与冻结 B_core13 完全一致；单版本（不加市值/行业，前序已证无增益）。",
        "",
        "一、全期日频 IC：",
        "=" * 64,
        f"  V_full158: IC均值={daily_ic['ic'].mean():.4f} | ICIR={daily_ic['ic'].mean() / daily_ic['ic'].std():.4f} | "
        f"RankIC均值={daily_ic['rank_ic'].mean():.4f} | RankICIR={daily_ic['rank_ic'].mean() / daily_ic['rank_ic'].std():.4f} | "
        f"IC>0占比={(daily_ic['ic'] > 0).mean():.4f} | 有效天数={len(daily_ic)}",
        "",
        "二、分年 IC：",
        "=" * 64,
    ]
    for _, r in yearly.iterrows():
        lines.append(
            f"  {int(r['year'])}: days={int(r['days'])} IC={r['ic_mean']:.4f} ICIR={r['icir']:.4f} "
            f"RankIC={r['rank_ic_mean']:.4f} pos={(r['ic_positive_ratio']*100):.1f}%"
        )
    if len(backtest_df):
        lines += ["", "三、回测（TopkDropout topk=50, n_drop=5；基准 SH000852）：", "=" * 64]
        for _, r in backtest_df.iterrows():
            lines.append(
                f"  [{r['cost_scenario']}]: 费前超额 {r['gross_excess_annualized_return']*100:.2f}%/yr "
                f"IR={r['gross_excess_ir']:.3f} | 费后超额 {r['net_excess_annualized_return']*100:.2f}%/yr "
                f"IR={r['net_excess_ir']:.3f} 回撤={r['net_excess_max_drawdown']*100:.2f}% "
                f"换手={r['average_daily_turnover_rate']*100:.1f}% 成本损耗={r['annualized_cost_drag']*100:.2f}%/yr"
            )
    lines += [
        "",
        "与 Core13 滚动诊断（13 因子）对比：",
        "- Core13: IC=0.0084, ICIR=0.095, 费后基准成本超额 -5.57%/yr",
        "- 全量 158: 见上表",
        "",
        "结论边界：本实验是阶段 2 信号源选择证据，不授权部署；运行后停止，等待用户审查。",
    ]
    (args.output_dir / "rolling_report.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("\n".join(lines))


if __name__ == "__main__":
    main()
