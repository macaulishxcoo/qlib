#!/usr/bin/env python3
"""存活价量因子中性化复验 v1。

协议：research/protocols/a_share_price_volume_factor_neutralization_protocol_v1.md

研究问题
--------
battery v1 判定 TURNOVER_LEVEL5（换手率水平）与 SKEW60（60 日偏度）存活，但两者
方向均与文献相反且疑似风险暴露（高换手 ≈ 小市值/高波动补偿；偏度 ≈ 波动代理）。
本脚本用三档横截面残差中性化（M / MV / MVI = 市值 / 市值+波动 / 市值+波动+行业）
复验这两个因子的 RankIC 是否在中性化后仍存活，并用市值×波动 5×5 分层抓
"只在一层有效"的风险暴露。

口径（与 battery v1 完全一致）
------------------------------
- 主池：沪深普通 A 股母池 5544 只（all.txt 历史在市，剔除 BJ/指数/B 股）
- 辅助层：csi1000 历史成分（只跑 MVI 档）
- 数据：cn_data_2026（后复权）+ daily_basic_pit_v1（换手率+市值）
  + a_share_style_pit_v1（申万 L1 行业，PIT 区间）
- 过滤：ST/*ST/退市整理（PIT）+ 停牌 + 涨停信号日
- 窗口：2022-01-01 ~ 2026-07-31（预热自 2020-01-01）
- label：T+1 开盘成交 Ref($open,-1)/Ref($close,-6)-1（h=5），Spearman RankIC

输出（拒绝覆盖非空目录）
------------------------
output/analysis_static/a_share_price_volume_factor_neutralization_v1/
  neutralized_daily_ic.csv.gz   每因子 × 三档 每日 RankIC（long）
  neutralized_summary.csv       每因子 × 档 IC/ICIR/IC>0/22-25同向/2026 IC
  neutralized_yearly.csv        每因子 × 档 分年度 IC
  neutralized_sizevol_grid.csv  市值×波动 5×5 组内 RankIC（原始因子，全期）
  decision.json                 预设判定（每因子）
  methodology.json              口径快照
  validation_report.txt         中文报告
"""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

import qlib
from qlib.config import REG_CN
from qlib.data import D

QLIB_DIR = Path("~/.qlib/qlib_data/cn_data_2026").expanduser()
ALL_FILE = QLIB_DIR / "instruments" / "all.txt"
DATA_START = "2020-01-01"
DATA_END = "2026-07-31"
EVAL_START = "2022-01-01"
ANNUALIZATION_DAYS = 238

ST_INTERVALS = Path("data/external/tushare/a_share_st_status_pit_v1/normalized/st_status_intervals.csv.gz")
DAILY_BASIC = Path("data/external/tushare/a_share_daily_basic_pit_v1/normalized/daily_basic.csv.gz")
INDUSTRY_FILE = Path("data/external/tushare/a_share_style_pit_v1/normalized/industry_l1_effective_intervals.csv.gz")
LIMIT_MAIN = 0.095
LIMIT_GEM = 0.195
EXCLUDE_PREFIXES = ("BJ",)
EXCLUDE_PATTERNS = [("SH", "000"), ("SZ", "399"), ("SH", "900"), ("SZ", "200")]

ICIR_ALIVE = 0.3
YEARLY_STRICT = 3
IC_DECAY_RATIO = 0.5    # 中性化后 IC 衰减 > 50% 视为风险暴露
N_GRID = 5

FACTORS = ["TURNOVER_LEVEL5", "SKEW60"]
SCHEMES = ["raw", "M", "MV", "MVI"]


def qlib_to_ts(code: str) -> str:
    return f"{code[2:]}.{code[:2]}"


def ts_to_qlib(ts: str) -> str:
    return f"{ts[-2:].upper()}{ts[:6]}"


def is_gem(code: str) -> bool:
    num = code[2:]
    return num.startswith("30") or num.startswith("688")


def build_universe() -> list[str]:
    lines = [ln for ln in ALL_FILE.read_text().strip().splitlines() if ln.strip()]
    codes, excluded = [], []
    for ln in lines:
        code = ln.split()[0]
        if code.startswith(EXCLUDE_PREFIXES):
            excluded.append(code)
            continue
        ex, num = code[:2], code[2:]
        if (ex, num[:3]) in EXCLUDE_PATTERNS:
            excluded.append(code)
            continue
        codes.append(code)
    return codes, excluded


def load_daily_basic() -> pd.DataFrame:
    """换手率 + 自由流通市值（code, trade_date -> 行），对齐 df.index 顺序。"""
    db = pd.read_csv(DAILY_BASIC, compression="gzip",
                     usecols=["ts_code", "trade_date", "turnover_rate_f", "circ_mv"])
    db["trade_date"] = pd.to_datetime(db["trade_date"].astype(str), format="%Y%m%d")
    db["code"] = db["ts_code"].map(ts_to_qlib)
    db = db.rename(columns={"turnover_rate_f": "trf"})
    db = db.set_index(["trade_date", "code"])[["trf", "circ_mv"]]
    return db


def load_industry_l1(idx: pd.MultiIndex) -> pd.Series:
    """申万 L1 行业（PIT 区间逐日 asof），返回与 idx 对齐的 Series（object）。"""
    ind = pd.read_csv(INDUSTRY_FILE, compression="gzip",
                      usecols=["ts_code", "in_date", "out_date", "l1_name"])
    ind["start"] = pd.to_datetime(ind["in_date"].astype(str), format="%Y%m%d", errors="coerce")
    ind["end"] = pd.to_datetime(ind["out_date"].astype(str), format="%Y%m%d", errors="coerce")
    ind["end"] = ind["end"].fillna(pd.Timestamp.max)
    ind = ind.dropna(subset=["start", "l1_name"])
    ind = ind[ind["l1_name"].notna()]

    codes = idx.get_level_values("instrument").to_numpy()
    dts = idx.get_level_values("datetime").to_numpy(dtype="datetime64[ns]")
    out = np.full(len(idx), np.nan, dtype=object)
    uniq = pd.unique(codes)
    ind_by_code = {c: g.sort_values("start") for c, g in ind.groupby("ts_code")}
    for code in uniq:
        grp = ind_by_code.get(qlib_to_ts(code))   # qlib code -> ts_code
        if grp is None or len(grp) == 0:
            continue
        sel = np.where(codes == code)[0]
        dates = dts[sel]
        starts = grp["start"].values.astype("datetime64[ns]")
        ends = grp["end"].values.astype("datetime64[ns]")
        l1s = grp["l1_name"].values
        pos = np.searchsorted(starts, dates, side="right") - 1
        valid = pos >= 0
        pos_c = np.clip(pos, 0, len(starts) - 1)
        valid &= dates <= ends[pos_c]
        if valid.any():
            out[sel[valid]] = l1s[pos_c[valid]]
    return pd.Series(out, index=idx)


def roll_series(s: pd.Series, w: int, fn: str) -> pd.Series:
    out = s.groupby(level="instrument").transform(lambda x: getattr(x.rolling(w, min_periods=w // 2), fn)())
    return pd.Series(out.to_numpy(), index=s.index)


def load_market(codes) -> pd.DataFrame:
    """行情 + TURNOVER_LEVEL5/SKEW60 + std20 + 市值 + 行业 + 标签。"""
    raw = ["$close", "$open", "$volume", "$change"]
    df = D.features(codes, raw, start_time=DATA_START, end_time=DATA_END, freq="day")
    df.columns = ["close", "open", "volume", "change"]
    df = df.reset_index().set_index(["datetime", "instrument"]).sort_index()

    g = df.groupby(level="instrument")
    close = df["close"]

    # 换手率 + 市值
    db = load_daily_basic()
    df["trf"] = db["trf"].reindex(df.index).to_numpy()
    df["circ_mv"] = db["circ_mv"].reindex(df.index).to_numpy()

    # 因子（与 battery v1 定义一致）
    tr_mean5 = roll_series(df["trf"], 5, "mean")
    df["TURNOVER_LEVEL5"] = tr_mean5
    ret = g["close"].pct_change(fill_method=None)
    df["SKEW60"] = roll_series(ret, 60, "skew")

    # 波动率（与 Alpha158 STD20 同口径）+ 市值对数
    std20 = roll_series(close, 20, "std") / close
    df["std20"] = std20
    df["log_mv"] = np.log(df["circ_mv"])

    # 行业
    df["l1_name"] = load_industry_l1(df.index)
    df["l1_name"] = df["l1_name"].fillna("UNKNOWN")

    # 标签
    for h in [5]:
        df[f"FWD_{h}_open"] = g["open"].shift(-1) / g["close"].shift(-(h + 1)) - 1
    return df


def build_filter_mask(df: pd.DataFrame) -> np.ndarray:
    mask = df["close"].notna() & df["volume"].notna() & (df["volume"] > 0)
    codes = df.index.get_level_values("instrument")
    gem = codes.map(is_gem)
    limit_thresh = np.where(gem, LIMIT_GEM, LIMIT_MAIN)
    mask &= ~(df["change"] >= limit_thresh)

    st = pd.read_csv(ST_INTERVALS, compression="gzip", parse_dates=["start_date", "end_date"])
    st_active = st.loc[st["is_st"] | st["is_delist_phase"], ["ts_code", "start_date", "end_date"]]
    st_set_by_date: dict[pd.Timestamp, set[str]] = {}
    dates = df.index.get_level_values("datetime").unique()
    for d in dates:
        active = st_active[(st_active["start_date"] <= d) & (st_active["end_date"] >= d)]
        st_set_by_date[d] = set(active["ts_code"])
    ts = df.index.get_level_values("instrument").map(qlib_to_ts)
    dts = df.index.get_level_values("datetime")
    st_flag = np.array([c in st_set_by_date.get(d, set()) for d, c in zip(dts, ts)])
    mask &= ~st_flag
    return mask.to_numpy()


def neutralize_day(g: pd.DataFrame, factor: str, scheme: str) -> np.ndarray:
    """单日横截面残差中性化，返回残差（原始方向，NaN 保留）。"""
    y = g[factor].to_numpy(dtype=float)
    X_parts = []
    if scheme in ("M", "MV", "MVI"):
        X_parts.append(np.log(g["circ_mv"].to_numpy(dtype=float)))
    if scheme in ("MV", "MVI"):
        X_parts.append(g["std20"].to_numpy(dtype=float))
    if scheme == "MVI":
        l1 = g["l1_name"].to_numpy()
        for ind_name in sorted(pd.unique(l1)):
            X_parts.append((l1 == ind_name).astype(float))
    X = np.column_stack([np.ones(len(g))] + X_parts) if X_parts else np.ones((len(g), 1))

    mask = np.isfinite(y) & np.all(np.isfinite(X), axis=1)
    if mask.sum() < 100:
        return np.full(len(g), np.nan)
    beta, *_ = np.linalg.lstsq(X[mask], y[mask], rcond=None)
    resid = y - X @ beta
    return resid


def daily_ic(g: pd.DataFrame, factor: str, label: str) -> float:
    s = g[[factor, label]].dropna()
    if len(s) < 30:
        return np.nan
    return s[factor].corr(s[label], method="spearman")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--output-dir", type=Path,
                        default=Path("output/analysis_static/a_share_price_volume_factor_neutralization_v1"))
    args = parser.parse_args()
    out = args.output_dir
    if out.exists() and any(out.iterdir()):
        raise FileExistsError(f"Refusing to overwrite existing experiment output: {out}")
    out.mkdir(parents=True, exist_ok=True)

    qlib.init(provider_uri=str(QLIB_DIR), region=REG_CN)
    label = "FWD_5_open"

    # ---- 主池 ----
    print("[1/5] Building SH/SZ ordinary A-share universe ...", flush=True)
    codes, excluded = build_universe()
    print(f"      universe={len(codes)}, excluded={len(excluded)}", flush=True)

    print("[2/5] Loading market + factors + industry ...", flush=True)
    mkt = load_market(codes)
    mask = build_filter_mask(mkt)
    print(f"      rows={len(mkt)}, instruments={mkt.index.get_level_values('instrument').nunique()}, "
          f"keep={mask.mean():.1%}", flush=True)
    eval_all = mkt.loc[pd.Timestamp(EVAL_START): pd.Timestamp(DATA_END)]
    mask_full = pd.Series(mask, index=mkt.index)
    eval_keep = eval_all.loc[mask_full.loc[eval_all.index].to_numpy()]
    # 行业覆盖检查
    ind_cov = eval_keep["l1_name"].notna().mean()
    print(f"      industry coverage (eval): {ind_cov:.1%}", flush=True)

    # ---- 逐日中性化 + RankIC ----
    print("[3/5] Running daily neutralization (raw/M/MV/MVI) ...", flush=True)
    ic_rows = []
    for d, g in eval_keep.groupby(level="datetime", sort=True):
        for f in FACTORS:
            ic_rows.append((d, f, "raw", daily_ic(g, f, label)))
            for scheme in ["M", "MV", "MVI"]:
                resid = neutralize_day(g, f, scheme)
                g2 = g.copy()
                g2[f"{f}_resid"] = pd.Series(resid, index=g.index)
                ic_rows.append((d, f, scheme, daily_ic(g2, f"{f}_resid", label)))
    ic_df = pd.DataFrame(ic_rows, columns=["datetime", "factor", "scheme", "ic"])

    # ---- 市值×波动分层（原始因子）----
    print("[4/5] Building size×vol grid (raw factor, daily 5×5) ...", flush=True)
    grid_rows = []
    for d, g in eval_keep.groupby(level="datetime", sort=True):
        g = g.dropna(subset=["log_mv", "std20", label])
        if len(g) < N_GRID * N_GRID * 5:
            continue
        try:
            mvq = pd.qcut(g["log_mv"], N_GRID, labels=False, duplicates="drop")
            volq = pd.qcut(g["std20"], N_GRID, labels=False, duplicates="drop")
            tmp = g.assign(mvq=mvq, volq=volq)
            for mv in range(N_GRID):
                for vol in range(N_GRID):
                    sub = tmp[(tmp["mvq"] == mv) & (tmp["volq"] == vol)]
                    for f in FACTORS:
                        s = sub[[f, label]].dropna()
                        if len(s) >= 20:
                            grid_rows.append((d, f, mv, vol, s[f].corr(s[label], method="spearman")))
        except Exception:
            continue
    grid_df = pd.DataFrame(grid_rows, columns=["datetime", "factor", "mvq", "volq", "ic"])

    # ---- 汇总 ----
    print("[5/5] Summarizing + writing ...", flush=True)
    summary_rows = []
    for f in FACTORS:
        for scheme in SCHEMES:
            s = ic_df[(ic_df["factor"] == f) & (ic_df["scheme"] == scheme)].set_index("datetime")["ic"].dropna()
            yearly = s.groupby(s.index.year).mean()
            pos_2225 = int((yearly.loc[[y for y in range(2022, 2026) if y in yearly.index]] > 0).sum())
            raw = ic_df[(ic_df["factor"] == f) & (ic_df["scheme"] == "raw")].set_index("datetime")["ic"].dropna()
            decay = 1 - s.mean() / (raw.mean() + 1e-12) if scheme != "raw" else np.nan
            summary_rows.append({
                "factor": f, "scheme": scheme,
                "ic_mean": s.mean(), "icir": s.mean() / (s.std() + 1e-12),
                "ic_pos_ratio": (s > 0).mean(), "days": len(s),
                "yearly_same_sign_2022_2025": pos_2225, "ic_2026": yearly.get(2026, np.nan),
                "ic_decay_vs_raw": decay,
            })
    summary = pd.DataFrame(summary_rows)

    yearly_all = ic_df.pivot_table(
        index=ic_df["datetime"].dt.year, columns=["factor", "scheme"], values="ic", aggfunc="mean")

    grid_means = grid_df.groupby(["factor", "mvq", "volq"])["ic"].mean().reset_index()

    # 判定（协议 §5）
    decisions = {}
    for f in FACTORS:
        raw = summary[(summary["factor"] == f) & (summary["scheme"] == "raw")].iloc[0]
        mvi = summary[(summary["factor"] == f) & (summary["scheme"] == "MVI")].iloc[0]
        if mvi["icir"] >= ICIR_ALIVE and mvi["yearly_same_sign_2022_2025"] >= YEARLY_STRICT:
            decisions[f] = "alpha_confirmed"
        elif mvi["ic_decay_vs_raw"] > IC_DECAY_RATIO or mvi["icir"] < 0.2:
            decisions[f] = "risk_exposure"
        else:
            decisions[f] = "partially_neutralized"

    # ---- 写产物 ----
    ic_df.to_csv(out / "neutralized_daily_ic.csv.gz", index=False, compression="gzip")
    summary.to_csv(out / "neutralized_summary.csv", index=False)
    yearly_all.to_csv(out / "neutralized_yearly.csv")
    grid_means.to_csv(out / "neutralized_sizevol_grid.csv", index=False)
    (out / "decision.json").write_text(json.dumps(decisions, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    # ---- 报告 ----
    lines = []
    lines.append(f"# 存活价量因子中性化复验报告 v1\n")
    lines.append(f"- 主池: 沪深普通 A 股 {len(codes)} 只（剔除 BJ/指数/B 股 {len(excluded)} 只），行业覆盖 {ind_cov:.1%}")
    lines.append(f"- 数据: {QLIB_DIR}（后复权）+ daily_basic_pit_v1 + style_pit_v1(申万L1)")
    lines.append(f"- 窗口: {EVAL_START} ~ {DATA_END}（预热自 {DATA_START}），过滤保留率 {mask.mean():.1%}")
    lines.append(f"- label: T+1 开盘成交 h=5；中性化: 每交易日 OLS 残差（M=市值, MV=市值+波动, MVI=市值+波动+行业）\n")

    lines.append("### 汇总（每因子 × 档）")
    lines.append("| 因子 | 档 | IC | ICIR | IC>0 | 22-25同向 | 2026 IC | IC衰减vs原始 | 判定 |")
    lines.append("|---|---|---|---|---|---|---|---|---|")
    for _, r in summary.iterrows():
        decay_txt = "—" if pd.isna(r["ic_decay_vs_raw"]) else f"{r['ic_decay_vs_raw']:.0%}"
        decision_txt = decisions[r["factor"]] if r["scheme"] == "MVI" else ""
        lines.append(
            f"| {r['factor']} | {r['scheme']} | {r['ic_mean']:+.4f} | {r['icir']:.2f} | {r['ic_pos_ratio']:.0%} | "
            f"{r['yearly_same_sign_2022_2025']}/4 | {r['ic_2026']:+.4f} | "
            f"{decay_txt} | {decision_txt} |"
        )

    lines.append("\n### 分年度 IC（每因子 × 档）")
    lines.append("| 因子 | 档 | 2022 | 2023 | 2024 | 2025 | 2026 |")
    lines.append("|---|---|---|---|---|---|---|")
    for f in FACTORS:
        for scheme in SCHEMES:
            yr = yearly_all[(f, scheme)] if (f, scheme) in yearly_all.columns else None
            if yr is None:
                continue
            cells = " | ".join(f"{yr.get(y, np.nan):+.4f}" for y in range(2022, 2027))
            lines.append(f"| {f} | {scheme} | {cells} |")

    lines.append("\n### 市值×波动 5×5 组内 RankIC（原始因子，全期；mvq=小→大市值, volq=低→高波动）")
    lines.append("| 因子 | mvq | volq | 组内 IC |")
    lines.append("|---|---|---|---|")
    for _, r in grid_means.iterrows():
        lines.append(f"| {r['factor']} | {r['mvq']} | {r['volq']} | {r['ic']:+.4f} |")

    lines.append("\n### 判定解读（协议 §5）")
    lines.append("- alpha_confirmed: MVI 后 ICIR≥0.3 且 2022-2025 同向≥3 → 真增量，候选主线正交信号源")
    lines.append("- risk_exposure: MVI 后 IC 衰减>50% 或 ICIR<0.2 → 风险暴露（市值/波动/行业），判死")
    lines.append("- partially_neutralized: 其余 → 弱存活，需并入主线组合后再评")
    for f in FACTORS:
        lines.append(f"- **{f}: {decisions[f]}**")

    (out / "validation_report.txt").write_text("\n".join(lines), encoding="utf-8")

    meta = {
        "purpose": "存活价量因子（换手率水平/偏度）的三档残差中性化复验：区分真 alpha 与风险暴露",
        "protocol": "research/protocols/a_share_price_volume_factor_neutralization_protocol_v1.md",
        "universe": f"沪深普通 A 股 {len(codes)} 只（剔除 {len(excluded)} 只）",
        "data_dir": str(QLIB_DIR),
        "eval_window": [EVAL_START, DATA_END],
        "horizon": 5,
        "label": "Ref($open,-1)/Ref($close,-6)-1",
        "factors": FACTORS,
        "schemes": SCHEMES,
        "neutralization": "OLS residual per day: M=log(circ_mv), MV=+std20, MVI=+SW-L1 industry dummies",
        "filters": "ST/*ST/退市整理(PIT) + 停牌 + 涨停信号日",
        "thresholds": {"icir_alive": ICIR_ALIVE, "yearly_strict": YEARLY_STRICT, "ic_decay_ratio": IC_DECAY_RATIO},
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
    }
    (out / "methodology.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"      report -> {out / 'validation_report.txt'}", flush=True)
    print(f"      decisions = {decisions}", flush=True)
    print("DONE", flush=True)


if __name__ == "__main__":
    main()
