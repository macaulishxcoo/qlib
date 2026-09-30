#!/usr/bin/env python
"""qdata 因子复现 —— 全批次汇总。

扫描 ``output/qdata_factor_repro/`` 下所有 ``*_compare_settled.csv``（判定口径报告），
合并去重后与 ``factor_formulas.json`` 的 242 个当前因子做覆盖率对照，
产出 ``SUMMARY.csv`` 与 ``SUMMARY.md``。

用法::

    python scripts/qdata/run_factor_summary.py
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "output" / "qdata_factor_repro"
FORMULAS = OUT / "factor_formulas.json"

VERDICTS = ["EXACT", "GOOD", "APPROX", "FAIL", "NO_DATA"]
OK = {"EXACT", "GOOD"}


def _sp_to_verdict(sp) -> str:
    """横截面 Spearman → 档位（与 ``xs_compare._verdict`` 的阈值保持一致）。"""
    try:
        s = float(sp)
    except (TypeError, ValueError):
        return "NO_DATA"
    if not np.isfinite(s):
        return "NO_DATA"
    if s >= 0.9999:
        return "EXACT"
    if s >= 0.999:
        return "GOOD"
    if s >= 0.99:
        return "APPROX"
    return "FAIL"

#: 结构性不可复现 / 已知原因的归档（人工维护，随批次推进补充）
#: 章节号对应 `CONVENTIONS.md`。
KNOWN_ISSUES: dict[str, str] = {
    # §G2 —— qdata 尾部未沉淀窗口（暂定值事后被回填修正）
    "dif": "§G2 未沉淀窗口；截断后精确",
    "dea": "§G2 未沉淀窗口；截断后精确",
    "MACD": "§G2 未沉淀窗口；截断后精确",

    # §5.10 —— 供方内部分组规则未披露（大并列块，公开数据不可反推）
    "yoy_ocf": "§5.10 供方分组规则未披露（并列块 1767 只；本地 yoy 分布与非并列组无法区分）",
    "eaa": "§5.10 疑同因：大并列块 1167 只（供方分组规则未披露）",
    "alpha101_29": "§5.10 疑同因：大并列块 1084 只（供方分组规则未披露）",
    "pa": "§5.10 疑同因：大并列块 850 只（供方分组规则未披露）",
    "sa": "§5.10 疑同因：大并列块 564 只（供方分组规则未披露）",
    "alpha101_25": "§5.10 疑同因：大并列块 227 只（供方分组规则未披露）",
    "alpha101_52": "§5.10 疑同因：大并列块 118 只（供方分组规则未披露）",

    # §5.2 / §5.6 —— IndNeutralize 行业标准未披露（中信/同花顺接口无权限）
    "alpha101_48": "§5.11 行业标准未披露（申万L1/L2/L3 + Tushare 四种最佳仅 0.9255）",
    "alpha101_58": "§5.11 行业标准未披露（四种最佳 0.7404）；分档一致率 0.62 亦不达标",
    "alpha101_59": "§5.11 行业标准未披露（四种最佳 0.7497）；分档一致率 0.56 亦不达标",
    "alpha101_63": "§5.11 行业标准未披露（四种最佳 0.8776）",
    "alpha101_67": "§5.11 行业标准未披露（四种最佳 0.7577）",
    "alpha101_69": "§5.11 行业标准未披露（四种最佳 0.8729）",
    "alpha101_70": "§5.11 行业标准未披露（四种最佳 0.8935）",

    # §5.6 —— 官方每日股票池规则未标定（官方 N 比 Tushare daily 少约 100~120 只）
    "alpha101_8": "§5.6 官方股票池规则未标定（长窗口 + 历史横截面池差异）",
    "alpha101_32": "§5.6 官方股票池规则未标定（250 日窗口，官方 N≈4930）",
    "alpha101_45": "§5.6 官方股票池规则未标定",
    "alpha101_56": "§5.6 官方股票池规则未标定",
    "alpha101_61": "§5.6 离散输出（±1）；分档一致率 0.96 接近",
    "alpha101_62": "§5.6 离散输出（±1）；分档一致率 0.98 接近",
    "alpha101_65": "§5.6 离散输出（±1）；分档一致率 0.87 仍不达标",
    "alpha101_68": "§5.6 离散输出（±1）；分档一致率 0.90 仍不达标",
    "alpha101_64": "§5.6 公式含厂商私有字段 Delta_Mix（未定义）⇒ 不可实现",

    # ⚠️ 样本量不足 —— 结论本身不可靠
    "cfcr": "⚠️ 官方截面仅 N=172 ⇒ 样本量不足、Spearman 不可靠；InterestExpense 字段未标定",
    "icr": "⚠️ 官方截面仅 N=106 ⇒ 样本量不足、Spearman 不可靠；InterestExpense 字段未标定",

    # Quality/Growth 字段或口径未标定
    "lra_yoy": "LongtermReceivableAccount 字段未标定（Tushare lt_rec 仅覆盖 1693 只）",
    "quality_composite": "OpCashInflow/InvCashInflow 字段 + filter=True 语义未标定",
    "cash_profit_ratio": "分子口径未标定 (OCF−NI)/NI",
    "gpm_q": "✅ 已解决（§5.15）：q 口径是**累计(YTD)**，非单季差分 —— 修正后 Spearman 0.99998",
    "eap": "EPS_Q 口径 + Close 分母待定",
    "yoy_net_profit": "§5.10 疑同因：原始比值型，长尾由分母穿越 0 主导（med_rel 0.0066 但 corr 0.12）",
    "np_to_fixed_assets_yoy": "比率分母穿越 0 ⇒ 极端值主导；疑 qdata 有裁剪（filter=True）",
    "np_to_inventory_yoy": "比率分母穿越 0 ⇒ 极端值主导",
    "np_to_deferred_tax_yoy": "比率分母穿越 0 ⇒ 极端值主导",
    "np_to_salary_yoy": "比率分母穿越 0 ⇒ 极端值主导",
    "np_to_total_expenses_yoy": "比率分母穿越 0 ⇒ 极端值主导",
    "expenses_to_equity_yoy": "比率分母穿越 0 ⇒ 极端值主导",
    "income_tax_yoy": "比率分母穿越 0 ⇒ 极端值主导",
    "tax_surcharge_yoy": "比率分母穿越 0 ⇒ 极端值主导",
    "delta_npm": "比率分母穿越 0 ⇒ 极端值主导（Spearman 0.9843）",
    "delta_opm": "比率分母穿越 0 ⇒ 极端值主导（Spearman 0.9850）",
    "delta_roa": "比率分母穿越 0 ⇒ 极端值主导（Spearman 0.9864）",
    "yoy_roa": "§5.7 已排除报告期偏移；§5.9 f_ann_date 仅 +0.0014 ⇒ 成因未定",
    "yoy_roe": "§5.7 已排除报告期偏移；§5.9 f_ann_date 仅 +0.0033 ⇒ 成因未定",
    "np_ttm_qoq": "比率分母穿越 0；并列仅 22 只，影响小",

    # ---- §5.14 Value 族（2026-09-21 全市场标定，5381 只 × 2024 窗口 4 日）----
    "ebitda_to_market": "§5.14 口径未定：EBITDA_TTM/mv 0.910（年报口径 0.973、EBIT+营业成本 0.599 均更差）",
    "etp5": "§5.14 窗口口径未定：mean(归母年报,1260)/mean(mv,1260) 0.984；名次偏差中位 7.86%",
    "pegh5": "§5.14 口径未定：-Close/(g5·EPS_TTM) 0.941；g5 用 EPS 年报 5 年复合增速",
    "ocf_to_market": "§5.14 少数金融股错位主导：名次偏差中位仅 1.46% 但 p90 19.5%；最大偏差 8 只全为银行/券商（存款同业现金流科目差异）；分子取绝对值已否证",
    "ncf_to_market": "§5.14 口径未定：(OCF+ICF+筹资净额)_TTM/mv 0.713；最大偏差集中在银行；OCF+ICF 0.184、单季 0.202 均更差",
    "fcf_to_market": "§5.14 内层公式正确（中位相对误差 1e-10）⇒ maxerr 由分母穿越 0 的长尾主导；Tushare free_cashflow 口径 0.242 已否证",

    # ---- 以下 9 条为 APPROX「差一点点」型：形状已对，差口径细节或长尾 ----
    "ar_ap_to_revenue": "APPROX 0.9739：(预收−预付)/营收，科目口径待定",
    "asset_growth_qoq": "APPROX 0.9948：环比用 prev_report（上一披露期），报告期选择待定",
    "delta_asset_turnover": "APPROX：Delta = 本期 − t-252；长尾由分母接近 0 主导",
    "delta_gpm": "APPROX：Delta = 本期 − t-252；长尾由分母接近 0 主导",
    "delta_inventory_turnover": "APPROX：Delta = 本期 − t-252；长尾由分母接近 0 主导",
    "delta_roe": "APPROX：Delta = 本期 − t-252；长尾由分母接近 0 主导",
    "gpm_qoq": "APPROX 0.9955：TTM 毛利率环比，分母穿越 0 影响长尾；并列 23 只",
    "gross_margin_qoq": "APPROX 0.9955：同 gpm_qoq（二者实现相同）",
    "npm_ttm_qoq": "APPROX：TTM 净利率环比，分母穿越 0 影响长尾；并列 22 只",
}


def load_reports() -> pd.DataFrame:
    """合并所有批次报告。

    支持两类判据（见 CONVENTIONS §3.4）：

    * ``*_compare_settled.csv``（``facsim.compare``）—— 绝对误差判据，列 ``verdict_med``，
      指标 ``max_abs_err`` / ``med_rel_err``；
    * ``*_xs*.csv``（``xs_compare``）—— 横截面 Spearman 判据，列 ``verdict_xs``，
      指标 ``spearman_med`` / ``spearman_min``。

    同一因子出现多次时保留样本量最大的一条；两套判据都有时**优先采信横截面判据**
    （横截面因子的绝对误差判据会系统性误判，见 §3.4）。
    """
    frames = []
    # 绝对误差口径报告：``*_compare_settled.csv``（已沉淀窗口）+ ``*_compare.csv``
    # （全窗口/未截断，如 Alpha101 族的报告 —— 实测该族无 G2 尾部效应，故只有一份）。
    # ``_settled`` 让"已沉淀"报告在其它条件相同时优先（0 优于 1）。
    seen: set[str] = set()
    for f in sorted(list(OUT.glob("*_compare_settled.csv")) + list(OUT.glob("*_compare.csv"))):
        # ⚠️ 排除中间产物：
        #   * ``variant`` / ``skipped`` —— 口径变体与跳过清单，不是结论
        #   * ``smallsample`` —— 已被降级为 sanity check 的"6 只样本股"表。
        #     它以 ``_compare_settled.csv`` 结尾，会被本 glob 命中；且它对
        #     rank 型因子给出 59 EXACT（本地 {1/6..1} 对官方 {1/N..1}，不可能成立），
        #     在"结论更好的胜"的去重规则下会**击穿**正确的全市场结果。
        if (f.name in seen or "variant" in f.name or "skipped" in f.name
                or "smallsample" in f.name):
            continue
        seen.add(f.name)
        d = pd.read_csv(f)
        if "verdict_med" not in d.columns:
            continue
        # 若该报告同时给出了横截面判据列（如 Alpha101 族的 alpha101_compare.csv
        # 带 verdict_xs / spearman_med），则**优先采用横截面判据** ——
        # 该族因子由 Rank 派生，maxerr 判据系统性不适合（见 CONVENTIONS §3.4）。
        if "verdict_xs" in d.columns and "spearman_med" in d.columns:
            d["verdict_med"] = d["verdict_xs"].fillna(d["verdict_med"])
            d["corr"] = d["spearman_med"].fillna(d.get("corr"))
            d["med_rel_err"] = d["spearman_med"].fillna(d.get("med_rel_err"))
            d["判据"] = "横截面Spearman"
            d["_prio"] = 0
        else:
            d["判据"] = "绝对误差"
            d["_prio"] = 1
        d["_settled"] = 0 if f.name.endswith("_compare_settled.csv") else 1
        d["_src"] = f.name
        d["_mtime"] = f.stat().st_mtime
        frames.append(d)
    for f in sorted(OUT.glob("*_xs*.csv")):
        d = pd.read_csv(f)
        if "verdict_xs" in d.columns:
            # ⚠️ 必须先取 spearman_med 作为 corr，再重命名：
            #    重命名后 verdict_med 是档位字符串，若在之后取 .get("verdict_med")
            #    会让 corr 变成 str，最终在 f"{corr:.6f}" 处崩溃。
            if "corr" not in d.columns:
                d["corr"] = d.get("spearman_med", np.nan)
            d = d.rename(columns={"verdict_xs": "verdict_med",
                                  "spearman_med": "med_rel_err",
                                  "spearman_min": "max_abs_err"})
            if "n_overlap" not in d.columns:
                d["n_overlap"] = d.get("n_days", 0)
            crit = "横截面Spearman"
        elif "sp" in d.columns:
            # phaseA 全市场验证格式：factor,universe,n,n_off,max_abs,med_abs,mean_abs,sp
            # 同一因子可能在多个 universe 下各有一行 —— 取 sp 最高的一行，
            # 但"官方"与"Tushare"两种股票池的结论实测一致，故不影响判定。
            d = (d.sort_values("sp", ascending=False)
                   .drop_duplicates("factor", keep="first"))
            d["corr"] = d["sp"]
            d["n_overlap"] = d["n"]
            d["max_abs_err"] = d["max_abs"]
            d["med_rel_err"] = d["med_abs"]
            d["verdict_med"] = d["sp"].map(_sp_to_verdict)
            crit = "横截面Spearman"
        else:
            continue
        d["判据"] = crit
        d["_prio"] = 0  # 判据更合适
        d["_settled"] = 0
        d["_src"] = f.name
        d["_mtime"] = f.stat().st_mtime
        if "coverage" not in d.columns:
            d["coverage"] = np.nan
        if "corr" not in d.columns:
            d["corr"] = d.get("verdict_med", np.nan)
        if "verdict" not in d.columns:
            d["verdict"] = d["verdict_med"]
        frames.append(d)
    # ---- 离散输出型因子的「分档一致率 / Spearman 取较优」判据 -----------------
    # 见 `check_discrete.py`：对并列型输出两个指标各有假阴性
    #   * `alpha101_1/21/27/7`：Spearman 低估（档位跳变）→ 一致率才对
    #   * `alpha101_43/46`：一致率假阴性（块边界微差使逐值全不等）→ Spearman 才对
    # 故取较优者，并用 `判据` 列记录来源。
    for f in sorted(OUT.glob("*discrete_agreement.csv")):
        d = pd.read_csv(f)
        if "verdict_best" not in d.columns:
            continue
        d = d.rename(columns={"verdict_best": "verdict_med",
                              "spearman_med": "corr"})
        d["判据"] = "分档一致率/Spearman取较优"
        d["n_overlap"] = d.get("n_days", 0)
        d["coverage"] = np.nan
        d["verdict"] = d["verdict_med"]
        d["_prio"] = 0
        d["_settled"] = 0
        d["_src"] = f.name
        d["_mtime"] = f.stat().st_mtime
        frames.append(d)

    # ---- 横截面因子的「数值差多少」判据（用户标准：差不太多就算公式正确）----------
    # 见 `check_xs_median_error.py`：横截面因子原本只用 Spearman（排序一致度）判定，
    # 从未测过数值差多少。但对 `rank/N` 型因子两者可能严重不一致：
    #   `yoy_roa` Spearman 0.9837（判 FAIL）但**中位相对误差仅 0.575%**（用户标准 = APPROX）。
    # 这里按「两套判据取较优」纳入，与离散因子的处理一致。
    for f in sorted(OUT.glob("xs_median_error.csv")):
        d = pd.read_csv(f)
        if "中位误差判" not in d.columns:
            continue
        d = d.rename(columns={"中位误差判": "verdict_med"})
        d["判据"] = "中位相对误差(用户标准)"
        d["corr"] = d.get("spearman_med", np.nan)
        d["n_overlap"] = d.get("n_days", 0)
        d["coverage"] = np.nan
        d["verdict"] = d["verdict_med"]
        d["_prio"] = 0
        d["_settled"] = 0
        d["_src"] = f.name
        d["_mtime"] = f.stat().st_mtime
        frames.append(d)

    if not frames:
        raise SystemExit(f"未找到任何批次报告 CSV（{OUT}），先跑各批 repro 脚本。")
    df = pd.concat(frames, ignore_index=True, sort=False)
    # 去重优先级（依次）：
    #   1. **结论更好的胜**（EXACT > GOOD > APPROX > FAIL > NO_DATA）—— 同一因子可能被多个
    #      批次测过，应报告"已知能达到的最好复现程度"。
    #      反例：`book_to_market` 先在批次二判 FAIL，后被 `repro_value.py` 修正为 EXACT。
    #   2. 判据更合适的胜：横截面判据(0) > 绝对误差(1)。
    #   3. 样本量大的胜；4. 文件更新的胜（后跑的会修正先前的）。
    #
    #   ⚠️ 早期版本把 `_prio`（判据）放在**第一位**，导致「横截面报告里判 NO_DATA」的行
    #   盖住「绝对误差报告里判 EXACT」的行 —— 某批 27 个 Quality 因子就这样被虚报为 NO_DATA。
    #   正确做法是先比结论好坏：只要有一份报告给出了明确结论，就不该被 NO_DATA 掩盖。
    #   判据是否用错由下方的「判据差异」告警负责提示（A 类 = 用绝对误差判横截面因子）。
    _vrank = {v: i for i, v in enumerate(VERDICTS)}
    df["_vrank"] = df["verdict_med"].map(_vrank).fillna(len(VERDICTS))
    if "_settled" not in df.columns:
        df["_settled"] = 1
    df["_settled"] = df["_settled"].fillna(1)
    df = (df.sort_values(["_vrank", "_prio", "_settled", "n_overlap", "_mtime"],
                         ascending=[True, True, True, False, False])
            .drop_duplicates("factor", keep="first"))
    return df.reset_index(drop=True)


def main() -> int:
    df = load_reports()
    meta = json.load(open(FORMULAS, encoding="utf-8"))
    cur = {k: v for k, v in meta.items() if "_old_" not in k}
    fam_of = {k: v.get("factor_type", "?") for k, v in cur.items()}
    params_of = {k: v.get("params") or {} for k, v in cur.items()}

    # 逐因子状态登记表（由 audit_formulas.py 生成），提供"应有判据"与归档原因
    status: dict[str, dict] = {}
    st_path = OUT / "FACTOR_STATUS.json"
    if st_path.is_file():
        status = json.load(open(st_path, encoding="utf-8"))
    crit_of = {k: v.get("criterion", "") for k, v in status.items()}

    # 用**实证**判别覆盖公式文本的启发式（见 classify_factors.py）：
    # 实测证明公式文本不可全信 —— `de` 文本含 CrossSectionalRank 但官方值是原始比值；
    # 反过来 `roe_ttm` 等 passthrough 因子文本省略了排名包装但官方值确是 rank/N。
    cls_path = OUT / "FACTOR_CLASSIFICATION.json"
    cls = json.load(open(cls_path, encoding="utf-8")) if cls_path.is_file() else {}
    n_emp = 0
    for k, v in cls.items():
        if v.get("kind", "").startswith("rank"):
            crit_of[k] = "横截面Spearman"   # 纯 rank/N 型：绝对误差判据在样本股上必然失真
            n_emp += 1
    if cls:
        print(f"  [classify] 实证判定 {n_emp} 个因子为纯 rank/N 型（强制横截面判据）")
    archived = {k: v.get("archived_reason", "") for k, v in status.items()
                if v.get("archived_reason")}

    df["factor_type"] = df["factor"].map(fam_of).fillna("(未知)")
    # 各批脚本对"未实现/无数据"的表示不统一（NaN / 空串 / NO_DATA），统一归一到 NO_DATA，
    # 否则 EXACT+GOOD+APPROX+FAIL+NO_DATA 之和对不上"已比对"。
    df["verdict_med"] = df["verdict_med"].fillna("NO_DATA")
    df.loc[df["verdict_med"].astype(str).str.strip() == "", "verdict_med"] = "NO_DATA"
    df["verdict"] = df.get("verdict", pd.Series("NO_DATA", index=df.index)).fillna("NO_DATA")
    # 数值列强制转型：各批脚本写出的 CSV 里这些列偶尔是字符串（如占位文件的空值）
    for _c in ("corr", "max_abs_err", "p99_abs_err", "med_rel_err", "n_overlap"):
        if _c in df.columns:
            df[_c] = pd.to_numeric(df[_c], errors="coerce")
    df["is_pass"] = df["verdict_med"].isin(OK)
    # 「已判定」= 有明确结论的（EXACT/GOOD/APPROX/FAIL）；
    # NO_DATA 表示未实现或无重叠样本，不应计入"已比对"，否则会虚高覆盖率。
    df["is_judged"] = df["verdict_med"].isin([v for v in VERDICTS if v != "NO_DATA"])
    if "判据" not in df.columns:
        df["判据"] = ""
    df["应有判据"] = df["factor"].map(crit_of).fillna("")
    # 判据差异。方向决定谁错了（见 CONVENTIONS §3.4）：
    #   A) 实际=绝对误差 & 应有=横截面Spearman → **实际判据错**，横截面因子用 maxerr 判会系统性误判；
    #   B) 实际=横截面Spearman & 应有=绝对误差 → **登记表可能不完整**：qdata 的公式文本有时
    #      省略了外层的 CrossSectionalRank（尤其 passthrough / 复合因子，如 roe_ttm、
    #      quality_composite、nl_size）。实测用横截面判据往往才是对的，应在登记表中标注，
    #      而不是推翻实际结果。
    # 「分档一致率/Spearman取较优」是对**并列型输出**因子的正当判据（见 check_discrete.py），
    # 不能算作"判据不符"—— 否则 13 个离散因子会被误报。
    # 「中位相对误差(用户标准)」同样是对横截面因子的正当判据（见 check_xs_median_error.py），
    # 不能算作"判据不符"。
    _ok_crit = {"分档一致率/Spearman取较优", "中位相对误差(用户标准)"}
    df["判据不符"] = ((df["应有判据"] != "") & (df["应有判据"] != df["判据"])
                  & (~df["判据"].isin(_ok_crit)))

    # 归档原因：把 KNOWN_ISSUES（人工维护，见 CONVENTIONS 章节）与各批报告自带的
    # `note`/`attribution` 合并成 DataFrame 的 `note` 列，**CSV 与 Markdown 共用**。
    # ⚠️ `np.nan` 是 truthy，必须显式判空，否则 `x or fallback` 会取到 NaN。
    def _note(r):
        for key in ("note", "attribution"):
            v = r.get(key)
            if isinstance(v, str) and v.strip():
                return v.strip()
        return KNOWN_ISSUES.get(r["factor"], "")

    df["note"] = [_note(r) for _, r in df.iterrows()]
    # 未通过但无任何归档说明的，显式标出，便于后续补录
    _bad = ~df["verdict_med"].isin(OK)
    df.loc[_bad & (df["note"] == ""), "note"] = "⚠️ 未归档：原因待补录"
    df["差异方向"] = np.where(
        ~df["判据不符"], "",
        np.where(df["判据"] == "横截面Spearman",
                 "B:登记表待补（实际用横截面判据，通常正确）",
                 "A:实际判据错误（须用 xs_compare 重跑）"))

    # ---------- 按族汇总 ----------
    rows = []
    for fam, g in df.groupby("factor_type"):
        vc = g["verdict_med"].value_counts().to_dict()
        total_in_lib = sum(1 for k, v in fam_of.items() if v == fam)
        n_judged = int(g["is_judged"].sum())
        n_pass = int(g["is_pass"].sum())
        rows.append({
            "factor_type": fam,
            "库内因子数": total_in_lib,
            "已判定": n_judged,
            "覆盖率": round(n_judged / total_in_lib, 4) if total_in_lib else 0.0,
            **{v: vc.get(v, 0) for v in VERDICTS},
            "通过数": n_pass,
            # 通过率以「已判定」为分母 —— NO_DATA（未实现/无重叠）不该拉低通过率
            "通过率": round(n_pass / n_judged, 4) if n_judged else 0.0,
        })
    fam_df = pd.DataFrame(rows).sort_values("库内因子数", ascending=False)

    # ---------- 总账 ----------
    vc = df["verdict_med"].value_counts().to_dict()
    n_pass = int(df["is_pass"].sum())
    n_judged = int(df["is_judged"].sum())
    n_lib = len(cur)

    # ---------- 未覆盖清单 ----------
    missing = sorted(set(cur) - set(df["factor"]))
    miss_arch = [k for k in missing if k in archived]   # 已归档（结构性不可复现）
    miss_todo = [k for k in missing if k not in archived]
    miss_by_fam: dict[str, list[str]] = {}
    for k in miss_todo:
        miss_by_fam.setdefault(fam_of[k], []).append(k)

    # ---------- 判据不符 ----------
    wrong_crit = df[df["判据不符"]]

    # ---------- 未通过清单 ----------
    failed = df[~df["is_pass"]].sort_values(["factor_type", "verdict_med"])

    # ---------- 写 CSV ----------
    cols = ["factor", "factor_type", "判据", "应有判据", "判据不符", "verdict_med", "verdict",
            "n_overlap", "coverage", "max_abs_err", "p99_abs_err", "med_rel_err", "corr", "note"]
    cols = [c for c in cols if c in df.columns]
    df[cols].to_csv(OUT / "SUMMARY.csv", index=False)
    fam_df.to_csv(OUT / "SUMMARY_BY_FAMILY.csv", index=False)

    # ---------- 写 Markdown ----------
    L: list[str] = []
    L.append("# qdata.cc 因子本地复现 —— 总汇总\n")
    L.append(f"> 判定口径：**已沉淀窗口**（`--settle-days 30`），见 `CONVENTIONS.md` §G2。")
    rate = f"{n_pass / n_judged * 100:.1f}%" if n_judged else "—"
    L.append(f"> 库内当前因子 **{n_lib}** 个；**已判定 {n_judged}** 个（有明确结论）；"
             f"**通过 {n_pass} 个（占已判定 {rate}，占库内 {n_pass / n_lib * 100:.1f}%）**。")
    L.append(f"> 另有 {len(df) - n_judged} 个已跑但 NO_DATA（未实现 / 无重叠样本），"
             f"未覆盖 {n_lib - len(df)} 个。\n")
    if len(wrong_crit):
        nA = int((wrong_crit["差异方向"].str.startswith("A")).sum())
        n_pass_a = int((wrong_crit["差异方向"].str.startswith("A") & wrong_crit["is_pass"]).sum())
        L.append(f"> ⚠️ **判据存疑**：{nA} 条因子的结果由**不合适的判据**得出（其中 {n_pass_a} 条当前记为"
                 f"「通过」）。实测已确认这类因子的官方值是 `rank/N`（如 `roa_y` N=5545、"
                 f"`asset_turnover` N=5430，min=1/N、max=1.0、全互异），"
                 f"**在 6 只样本股上不可能复现**。")
        L.append(f"> ⇒ **保守通过数 = {n_pass - n_pass_a}**（剔除判据存疑项）。"
                 f"这些因子必须用 `xs_compare.py` 在全市场重跑才能定论。\n")

    L.append("## 1. 总账\n")
    L.append("| 指标 | 值 |")
    L.append("|---|---|")
    L.append(f"| 库内因子总数 | {n_lib} |")
    L.append(f"| 已判定（有明确结论） | {n_judged} |")
    L.append(f"| 已跑但 NO_DATA | {len(df) - n_judged} |")
    L.append(f"| 未覆盖 | {len(missing)} |")
    for v in VERDICTS:
        L.append(f"| {v} | {vc.get(v, 0)} |")
    L.append(f"| **通过（EXACT+GOOD）** | **{n_pass}** |\n")

    L.append("## 2. 按族汇总\n")
    L.append("| 族 | 库内 | 已判定 | 覆盖率 | EXACT | GOOD | APPROX | FAIL | NO_DATA | 通过率 |")
    L.append("|---|---|---|---|---|---|---|---|---|---|")
    for _, r in fam_df.iterrows():
        L.append(f"| {r['factor_type']} | {r['库内因子数']} | {r['已判定']} | "
                 f"{r['覆盖率']:.0%} | {r['EXACT']} | {r['GOOD']} | {r['APPROX']} | "
                 f"{r['FAIL']} | {r['NO_DATA']} | {r['通过率']:.0%} |")
    L.append("")

    if len(failed):
        L.append("## 3. 未通过因子\n")
        L.append("| 因子 | 族 | verdict_med | n_overlap | max_abs_err | med_rel_err | corr | note |")
        L.append("|---|---|---|---|---|---|---|---|")
        for _, r in failed.iterrows():
            note = str(r.get("note") or "")[:70]
            L.append(f"| `{r['factor']}` | {r['factor_type']} | {r['verdict_med']} | "
                     f"{r['n_overlap']} | {r['max_abs_err']:.4g} | {r['med_rel_err']:.4g} | "
                     f"{r['corr']:.6f} | {note} |")
        L.append("")

    if missing:
        L.append("## 4. 未覆盖清单\n")
        L.append(f"待做 **{len(miss_todo)}** 条；直通候选 **{len(miss_arch)}** 条"
                 f"（文档给了公式但 qdata 实际取预计算字段，需实测确认）。\n")
        for fam in sorted(miss_by_fam, key=lambda x: -len(miss_by_fam[x])):
            ks = miss_by_fam[fam]
            L.append(f"- **{fam}**（{len(ks)}）：" + "、".join(f"`{k}`" for k in ks))
        L.append("")
        if miss_arch:
            L.append("### 直通候选（`passthrough=true`，需实测确认）\n")
            L.append("| 因子 | 族 | 文档公式 | 说明 |")
            L.append("|---|---|---|---|")
            for k in miss_arch:
                fml = (status.get(k, {}).get("formula") or "").replace("\n", " ")[:60]
                L.append(f"| `{k}` | {fam_of.get(k,'?')} | {fml} | {archived[k]} |")
            L.append("")

    if len(wrong_crit):
        nA = int((wrong_crit["差异方向"].str.startswith("A")).sum())
        nB = int((wrong_crit["差异方向"].str.startswith("B")).sum())
        L.append("## 5. 判据差异（需人工确认）\n")
        L.append(f"共 {len(wrong_crit)} 条：**A 类（实际判据错误，结果不可信）{nA} 条**；"
                 f"**B 类（登记表待补，实际结果通常正确）{nB} 条**。\n")
        if nA:
            L.append("### A 类 —— 必须用 `xs_compare` 重跑\n")
            L.append("这些因子含横截面算子，却用了**绝对误差**判据。横截面因子的值是 `rank/N`，"
                     "名次差 10 位只值 0.0018，绝对误差判据会把「99% 名次都对」错报成 FAIL。\n")
        if nB:
            L.append("### B 类 —— `FACTOR_STATUS.json` 的判据列待补\n")
            L.append("这些因子在 `FACTOR_STATUS.json` 里按**公式文本**被标为「绝对误差」"
                     "（公式未出现 `CrossSectionalRank`），但实测实际用的是**横截面**判据。"
                     "常见于 `passthrough` 因子与复合因子（qdata 的公式文本省略了外层排名包装，"
                     "如 `roe_ttm` / `quality_composite` / `nl_size`）。**实际结果通常是对的**，"
                     "应在登记表中补标「含横截面（公式文本未体现）」。\n")
        L.append("| 因子 | 族 | 实际判据 | 应有判据 | 差异方向 | 当前结论 |")
        L.append("|---|---|---|---|---|---|")
        for _, r in wrong_crit.iterrows():
            L.append(f"| `{r['factor']}` | {r['factor_type']} | {r['判据']} | "
                     f"{r['应有判据']} | {r['差异方向']} | {r['verdict_med']} |")
        L.append("")

    L.append("## 6. 已标定的全局口径\n")
    L.append("见 `CONVENTIONS.md`：§G1 后复权价、§G2 尾部未沉淀窗口（含完整证据链）、"
             "§G3 滚动窗口含当日、§G4 简单收益、§G5 样本标准差、"
             "§G6 日期上限、§G7 取数纪律、§3.1 横截面依赖扫描（126/242）、"
             "§3.2 全市场面板可行路径、§3.4 `CrossSectionalRank = rank/N` 标定与"
             "横截面 Spearman 判据、§3.3 跨体系交叉验证、§3.5 Tushare 数据可得性。\n")
    L.append("> `scripts/qdata/FORMULA_AUDIT.md` 为公式静态审计（横截面扫描 / 参数清单 / "
             "直通因子 / 跨体系对照）。\n")

    (OUT / "SUMMARY.md").write_text("\n".join(L), encoding="utf-8")

    print(f"库内 {n_lib} | 已比对 {len(df)} | 通过 {n_pass} | 未覆盖 {len(missing)}")
    print(fam_df.to_string(index=False))
    print(f"\n产出: {OUT / 'SUMMARY.md'}\n      {OUT / 'SUMMARY.csv'}\n      {OUT / 'SUMMARY_BY_FAMILY.csv'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
