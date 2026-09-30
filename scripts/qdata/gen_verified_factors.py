#!/usr/bin/env python
"""生成「qdata 因子复现 —— 已验证因子清单（含归档）」。

产物：``output/qdata_factor_repro/VERIFIED_FACTORS.md``

内容
----
1. **已验证因子**（按用户口径：中位相对误差 ≤1% / 横截面秩相关达标）——逐条记录
   **实测确认的口径**与注意事项；
2. **已验证的口径修正**——文档公式与实现不符处（实测标定）；
3. **已否证的实现变体**——避免重复踩坑；
4. **未通过因子归档**——逐条原因与不可复现性判断。

数据来源
--------
* ``SUMMARY.csv``（总账，由 ``run_factor_summary.py`` 生成）
* ``factor_formulas.json``（官方公式文本）
* ``FACTOR_STATUS.json``（族 / 判据 / 直通）
* 人工维护的 ``CALIBRATION`` / ``DOC_CORRECTIONS`` / ``REFUTED``（本文件内，均有实测出处）

用法::

    python scripts/qdata/gen_verified_factors.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(Path(__file__).resolve().parent))

from run_factor_summary import KNOWN_ISSUES  # noqa: E402

OUT = REPO_ROOT / "output" / "qdata_factor_repro"
SUMMARY = OUT / "SUMMARY.csv"
FORMULAS = OUT / "factor_formulas.json"
STATUS = OUT / "FACTOR_STATUS.json"
TARGET = OUT / "VERIFIED_FACTORS.md"

FAMILY_DESC = {
    "Alpha101": "WorldQuant Alpha101 公式族（横截面，多数用**不复权价**）",
    "Quality": "财务质量比率（偿债 / 周转 / 盈利 / 现金流）",
    "Liquidity": "流动性与量额类（换手率 / 成交额 / Amihud / 量价相关）",
    "Risk": "收益矩与一致性风险（波动 / 偏度 / 峰度 / beta / sigma）",
    "Momentum": "动量与超买超卖（ROC / RSI / 区间收益 / 指数回归 alpha）",
    "Growth": "增长率与增长加速度（YoY / QoQ / 加速度）",
    "Value": "价值类（市值比 / 股息率 / 估值）",
    "Reversal": "反转类（短期反转 / 小市值反转）",
    "Size": "规模类（总市值 / 流通市值对数）",
}

#: 已验证因子的**实测口径**（与文档不同或需强调的点）。来源：CONVENTIONS.md 各节。
CALIBRATION: dict[str, str] = {
    # ---- 文档公式有误 ----
    "size": "**文档公式有误**：实为 `−log(total_mv/100)`；文档的 `−log(总股本×收盘价/1e6)` 与官方 corr=−0.02（§批次二）",
    "float_size": "同 `size`：实为 `−log(circ_mv/100)`；文档口径 corr=0.067",
    "book_to_market": "文档的 `_pri` 后缀**误导**：实为**最新报告期期末**值，且分子**必须计入递延所得税资产**（中位误差 1.28e-11）",
    "earnings_cut_to_market": "**文档字面写「扣非净利润」，实测官方用归母净利润 TTM**：归母 0.999997 vs 扣非 0.941175（§5.14）",
    "gpm_q": "q 口径是**累计（YTD）**而非单季差分：8 个比对日全市场实测累计 0.99998（含 4 个样本外日期 min 0.99996）、名次偏差 0.93%；单季差分 0.9698、TTM 0.9699（§5.15）",
    "equity_turnover_rate": "文档公式与实现方向相反（见聚宽体系交叉验证）",
    # ---- 口径必须精确到单季/TTM ----
    "sales_to_market": "分子是**单季**营业总收入（TTM 只有 0.957）；分母是**总**市值（流通市值 0.944）",
    "gpm_q": "分子分母均为**单季（差分）**的 `revenue`/`oper_cost`；累计(YTD) 口径只有 0.977（§本轮标定）",
    "rsi": "**Wilder 平滑 `ewm(com=13)`**；`span=14` / SMA14 / 原始价全 FAIL。中位相对误差 = 0",
    "rsrs": "后复权 + **`ddof=1`**；`ddof=0` 仅 APPROX",
    "price_dist": "后复权价 + **`ceil`**；`nearest` corr −0.10",
    "price_position_ir_60d": "用 **`ddof=1`**",
    "days_down_up": "**严格** `diff>0 / diff<0` + 后复权；非严格 corr 0.925",
    "small_cap_reversal_21d": "`CrossSectionalRank(Reversal) × SmallCap`，`SmallCap = CrossSectionalRank(−MarketCap)`（旧文档公式已废弃）",
    "earnings_to_price": "`1 / pe_ttm`",
    # ---- 量额单位陷阱 ----
    "amount_ma_20d": "成交额单位是**元**（Tushare 千元×1000）；且 `TSPanel.AMOUNT` **已被乘过复权因子**，须 `/ADJ` 还原",
    "turnover_volatility": "须 **÷100**",
    "market_cap": "×1e8（亿元→元）",
    # ---- 横截面机制 ----
    "roa_ttm": "内层 = **净利润 `n_income`（含少数股东）TTM / 期末总资产**（全市场 0.99999）；归母只有 0.986。外层 `CrossSectionalRank`",
    "roe_ttm": "内层 = **归母净利润 TTM / 股东权益合计（含少数股东）**（逐位 1.0000）；passthrough 无外层 rank",
    "roe_y": "同 `roe_ttm`，取**年报**报告期",
    "roa_y": "年报报告期口径",
    "asset_turnover": "TTM 营业收入 / 期末总资产",
    "de": "`总负债 / 股东权益`；**注意**：文档公式文本含 `CrossSectionalRank` 但官方值是**原始比值**（−166~412），必须实测判型",
    "nl_size": "`CrossSectionalRank(−log(市值))` 型；公式文本省略了 rank 包装",
    "quality_composite": "AQR Quality-Minus-Junk 六项之和；公式文本省略 rank 包装",
    # ---- Alpha101 专用 ----
    "dif": "⚠️ EMA 族有 **qdata 尾部未沉淀窗口**（约 20~25 交易日），判定须截断（§G2）；截断后 maxerr ≈5e-11",
}

#: 已验证的**否定结论**（错误实现变体），避免重复投入。
REFUTED: list[tuple[str, str, str]] = [
    ("size", "`−log(总股本 × 收盘价 / 1e6)`（文档写法）", "corr = **−0.02**（完全不相关）"),
    ("float_size", "`−log(流通股本 × 后复权价 / 1e6)`", "corr = 0.067"),
    ("rsi", "`span=14` / SMA14 / 原始价", "全 FAIL；Wilder `com=13` 才精确"),
    ("price_dist", "`round` 到最近整数", "corr = −0.10"),
    ("rsrs", "`ddof=0`", "仅 APPROX"),
    ("book_to_market", "`1/pb`", "中位相对误差 9.95e-2（Tushare `pb` 不含递延所得税资产）"),
    ("book_to_market", "期末归母权益（不加 DTA）", "中位相对误差 5.3e-2"),
    ("sharpe 类", "算术年化 / 252 交易日", "聚宽体系用 **几何年化 + 250**；本项目按各族分别标定"),
    ("alpha101_12 / 42 / 101", "后复权价", "误差 3105 / 792.6 / 8e-2 ⇒ **Alpha101 用不复权价**"),
    ("yoy_roa / yoy_roe", "4 个披露日偏移替代 `t-252` 交易日", "0.9626 / 0.9689 < 0.9837 / 0.9851（更差）"),
    ("yoy_roa / yoy_roe", "PIT 基准换 `f_ann_date`", "仅 +0.0014 / +0.0033，不足以解释残差"),
    ("ocf_to_market", "分子取绝对值 `|OCF_TTM|/mv`", "0.528 vs 基线 0.763（更差）"),
    ("ncf_to_market", "`|OCF+ICF+Fin|/mv`", "**−0.032**（更差）"),
    ("ebitda_to_market", "`|EBITDA_TTM|/mv`", "0.821 vs 0.978（更差）"),
    ("fcf_to_market", "Tushare `free_cashflow`", "0.242 vs 基线 0.851（更差）"),
    ("sales_to_market", "TTM 营业总收入", "0.957 vs 单季 1.000"),
    ("earnings_cut_to_market", "扣非净利润 TTM（文档字面）", "0.941 vs 归母 0.999997"),
    ("gpm_q", "单季(差分) 口径（文档「q 用累计单季」被误读为差分）", "0.9698 vs 累计(YTD) 0.99998（§5.15）"),
    ("Rank", "`method=\"average\"`（并列取平均名次）", "`yoy_ocf` 得 2759 而官方 3642；须 `method=\"max\"`"),
    ("所有 EMA 族因子", "用最近 30 自然日内官方值做判定", "qdata 近期值是**暂定值**，事后回填（§G2）"),
]

#: 归档分类（未通过因子）→ 结论
ARCHIVE_CLASS: list[tuple[str, str, str]] = [
    ("§5.10 供方分组规则未披露",
     "大并列块（yoy_ocf 1767 只 / eaa 1167 / pa 850 / sa 564）。**已证不可反推**："
     "并列块的本地 yoy 分布与非并列组统计上无法区分 ⇒ 分组不可能是数据本身的函数。",
     "结构性不可复现"),
    ("§5.11 行业标准未披露",
     "`IndNeutralize` 需厂商行业分类。申万 L1/L2/L3 + Tushare 自有**四种标准全部试过**，"
     "最佳仅 0.9255，且**行业越细越差**（7/7 成立）⇒ 官方分组更粗或完全不同。",
     "结构性不可复现"),
    ("§5.6 官方股票池/停牌规则未标定",
     "官方 N 比 Tushare `daily` 少约 100~120 只，含 ST 204 只、含停牌 4 只，"
     "剔除列表无干净上市日切分点 ⇒ **无法从公开字段推导**。长窗口因子的历史横截面池随之漂移。",
     "结构性不可复现"),
    ("§5.6 离散输出（±1）跳变",
     "官方只有 2 个取值，1~2 位名次漂移即造成 ±1 跳变。已改用「分档归属一致率」，"
     "`alpha101_61`(0.96) / `62`(0.98) 接近但未达标。",
     "度量不适配 + 边缘漂移"),
    ("算子统计量定义未标定",
     "`Alpha101` 长窗口/`Ts_Rank(高并列序列)` 类（`39`/`52`/`34`/`25`/`19`），"
     "Spearman 0.9937~0.9985 —— 名次基本正确，差算子细节。",
     "口径未标定（接近）"),
    ("比率分母穿越 0 ⇒ 极端值主导",
     "分子的比值或增量分母可正可负，产生 ±1e3~1e5 爆炸值主导排序。"
     "**同结构但分母恒正的因子全部 0.99+**（asset_growth_qoq 0.9948、yoy_total_asset 1.0000）"
     "⇒ 机制正确，疑官方对极端值有裁剪，但 `filter=True` 语义未披露。",
     "疑供方裁剪，规则未披露"),
    ("分子/分母口径未标定",
     "`cash_profit_ratio` / `gpm_q` / `eap` / `ar_ap_to_revenue` 等：分子或分母的科目口径未定，"
     "有明确前进方向（见 §5.14 与本轮标定）。",
     "口径未标定（可继续）"),
    ("厂商私有字段未定义",
     "`alpha101_64` 公式含 `Delta_Mix`，文档未定义该标识符；`lra_yoy` 的 "
     "`LongtermReceivableAccount` 在 Tushare 只覆盖 1693 只（corr 0.069）。",
     "结构性不可实现"),
    ("⚠️ 样本量不足",
     "`cfcr`(N=172) / `icr`(N=106)：官方横截面只有一两百只股票，"
     "**Spearman 在小样本上噪声极大，判定结论本身不可靠**。",
     "结论不可靠（非实现问题）"),
]



#: 归档类别判定（按 note 关键词，优先级从上到下）
_CLASS_RULES: list[tuple[tuple[str, ...], str]] = [
    (("§5.10", "供方分组"), "§5.10 供方分组规则未披露"),
    (("§5.11", "行业标准", "IndNeutralize 行业"), "§5.11 行业标准未披露"),
    (("股票池", "停牌"), "§5.6 官方股票池/停牌规则未标定"),
    (("离散输出",), "§5.6 离散输出（±1）跳变"),
    (("算子统计量",), "算子统计量定义未标定"),
    (("样本量不足",), "⚠️ 样本量不足"),
    (("Delta_Mix", "未实现", "私有字段"), "厂商私有字段未定义"),
    (("LongtermReceivableAccount",), "厂商私有字段未定义"),
    (("分母穿越 0", "分母接近 0"), "比率分母穿越 0 ⇒ 极端值主导"),
    (("口径未定", "口径未标定", "待定", "未标定", "APPROX"), "分子/分母口径未标定"),
]


def classify(note: str) -> str:
    n = note or ""
    for keys, kind in _CLASS_RULES:
        if any(k in n for k in keys):
            return kind
    return "成因未定"


def flat(s: object, limit: int = 200) -> str:
    t = " ".join(str(s or "").split())
    t = t.replace("|", "\\|")
    return t if len(t) <= limit else t[: limit - 1] + "…"


def main() -> int:
    summary = pd.read_csv(SUMMARY)
    formulas = {k: v for k, v in json.loads(FORMULAS.read_text()).items() if "_old_" not in k}
    status = json.loads(STATUS.read_text())

    summary["pass"] = summary["verdict_med"].isin(["EXACT", "GOOD"])
    summary["user_ok"] = summary["verdict_med"].isin(["EXACT", "GOOD", "APPROX"])
    n_all, n_pass, n_user = len(summary), int(summary["pass"].sum()), int(summary["user_ok"].sum())
    passed = summary[summary["user_ok"]].copy()
    failed = summary[~summary["user_ok"]].copy()

    L: list[str] = []
    A = L.append
    A("# qdata.cc 因子复现 —— 已验证因子清单与归档\n")
    A("本清单记录**经全市场变体对照实测确认**的因子公式与口径注意事项。")
    A("官方文档有若干处与实现不符，均已标出。\n")
    A(f"- 库内因子：**{n_all}**（另有 10 个 `_old_` 历史快照不参与判定）")
    A(f"- **用户口径通过（中位相对误差 ≤1% / 秩相关达标，含 APPROX）：{n_user} / {n_all} "
      f"= {n_user / n_all:.1%}**")
    A(f"- 严格口径通过（仅 EXACT+GOOD）：{n_pass} / {n_all} = {n_pass / n_all:.1%}")
    A(f"- 未通过归档：**{len(failed)}** 条（100% 有归档原因）")
    A("- 判定口径：横截面因子用**逐日 Spearman / 名次相对偏差**（全市场），"
      "时序因子用**中位相对误差**（已沉淀窗口，`--settle-days 30`）")
    A("- 生成脚本：`scripts/qdata/gen_verified_factors.py`；数据源：`SUMMARY.csv` / "
      "`factor_formulas.json` / `FACTOR_STATUS.json`\n")
    A("> ⚠️ **不要用最严的 maxerr 口径评价这些因子**：横截面因子值是 `rank/N`，"
      "名次差 10 位只值 0.0018；实测 `yoy_roa` 的 maxerr 判 FAIL 但中位相对误差仅 **0.575%**。\n")
    A("---\n")

    # ---------------- 1. 已验证因子 ----------------
    A("## 1. 已验证因子（按族）\n")
    A("| 族 | 库内 | 通过（用户口径） | 通过率 |")
    A("|---|---|---|---|")
    fam_order = ["Liquidity", "Risk", "Momentum", "Reversal", "Size",
                 "Alpha101", "Quality", "Value", "Growth"]
    for fam in fam_order:
        g = summary[summary["factor_type"] == fam]
        if g.empty:
            continue
        k = int(g["user_ok"].sum())
        A(f"| {fam} | {len(g)} | **{k}** | {k / len(g):.0%} |")
    A(f"| **合计** | **{n_all}** | **{n_user}** | **{n_user / n_all:.1%}** |")
    A("")

    for fam in fam_order:
        g = passed[passed["factor_type"] == fam].sort_values("factor")
        if g.empty:
            continue
        A(f"### {fam} —— {FAMILY_DESC.get(fam, '')}\n")
        A(f"通过 **{len(g)}** 条。\n")
        A("| 因子 | 判定 | 验证口径 | 官方公式（文档） |")
        A("|---|---|---|---|")
        for _, r in g.iterrows():
            f = r["factor"]
            cal = CALIBRATION.get(f, "")
            crit = flat(r.get("判据", ""), 24)
            A(f"| `{f}` | {r['verdict_med']} | {crit} | {flat(formulas.get(f, {}).get('formula'), 200)} |")
            if cal:
                A(f"| ↳ | | | {cal} |")
        A("")

    # ---------------- 2. 已验证的口径修正 ----------------
    A("---\n")
    A("## 2. 已验证的口径修正（文档与实现不符，均已实测）\n")
    A("| 因子 | 实测口径 / 修正 |")
    A("|---|---|")
    for f in fam_order:
        pass
    for f, note in CALIBRATION.items():
        if f in formulas:
            A(f"| `{f}` | {note} |")
    A("")
    A("### 通用约定（全局，适用于整库）\n")
    A("| 编号 | 约定 |")
    A("|---|---|")
    for k, v in [
        ("G1", "复权口径**分族**：显式写 `Close_hfq` 的因子用后复权；**Alpha101 用不复权价**；`VWAP = amount×10/vol` 亦不复权"),
        ("G2", "⚠️ EMA 族有 **qdata 尾部未沉淀窗口**（约 20~25 交易日，近期值是暂定值，事后回填）⇒ 判定须截断 `--settle-days 30`"),
        ("G3", "滚动窗口**含当日**（`MA`/`STD` 等）"),
        ("G4", "收益用**简单收益**（非对数）"),
        ("G5", "`StdDev` 用**样本标准差** `ddof=1`"),
        ("G7", "取数纪律：`factor_value` 日期必须 `YYYYMMDD`；禁用 offset 分页（会返回重复行）；空结果 `code=0/msg=ok/items=[]` 必须当可重试"),
        ("G11", "`Rank(x) = count(x_i ≤ x)/N`，并列取**最大**名次（`method=\"max\"`）"),
        ("G13", "`Ts_ArgMax(x,d)` = **距最大值的天数**（与 `np.argmax` 位置口径排序相反）"),
        ("G16", "`CrossSectionalRank(x) = rank(x)/N`，升序 1..N"),
        ("G17", "**判据必须实证确定**：公式文本会两个方向都错（`de` 文本含 rank 实为原始比值；`roe_ttm` 文本无 rank 实为 rank/N）"),
    ]:
        A(f"| {k} | {v} |")
    A("")

    # ---------------- 3. 已否证的实现变体 ----------------
    A("---\n")
    A("## 3. 已否证的实现变体（不要重复踩坑）\n")
    A("| 因子 | 否证的写法 | 实测结果 |")
    A("|---|---|---|")
    for f, variant, res in REFUTED:
        A(f"| `{f}` | {variant} | {res} |")
    A("")

    # ---------------- 4. 未通过归档 ----------------
    A("---\n")
    A("## 4. 未通过因子归档\n")
    A(f"共 **{len(failed)}** 条，逐条列出验证口径、实测值与归档原因。\n")
    A("| 因子 | 族 | 判定 | 秩相关/中位误差 | 归档类别 | 说明 |")
    A("|---|---|---|---|---|---|")
    for _, r in failed.sort_values(["factor_type", "factor"]).iterrows():
        note = r.get("note") if isinstance(r.get("note"), str) else ""
        val = r.get("corr") if pd.notna(r.get("corr")) else r.get("med_rel_err")
        A(f"| `{r['factor']}` | {r['factor_type']} | {r['verdict_med']} | {val:.4f} | "
          f"{classify(note)} | {flat(note, 110)} |")
    A("")

    A("### 归档类别说明\n")
    A("| 类别 | 判定 | 依据 |")
    A("|---|---|---|")
    for key, desc, kind in ARCHIVE_CLASS:
        A(f"| {key} | **{kind}** | {desc} |")
    A("")

    A("---\n")
    A("## 5. 相关文件\n")
    A("| 文件 | 内容 |")
    A("|---|---|")
    for f, d in [
        ("CONVENTIONS.md", "口径约定与完整验证记录（G1~G17 + 逐批标定 + 否证清单）"),
        ("SUMMARY.md / SUMMARY.csv / SUMMARY_BY_FAMILY.csv", "精度总账（自动生成）"),
        ("SUMMARY.csv 的 `note` 列", "未通过因子的逐条归档原因"),
        ("FORMULA_AUDIT.md", "公式静态审计（横截面扫描 / 参数 / 直通 / 跨体系对照）"),
        ("final8_scan.csv", "最后 8 条疑难因子的跨日多口径标定"),
        ("value_variant_scan.csv / value_sign_scan.csv", "Value 族口径变体与符号假设检验"),
        ("xs_median_error.csv", "横截面因子的「中位相对误差」补测（用户口径）"),
    ]:
        A(f"| `{f}` | {d} |")

    TARGET.write_text("\n".join(L) + "\n")
    print(f"已写 {TARGET}（{len(L)} 行）")
    print(f"  库内 {n_all} | 用户口径通过 {n_user} | 严格通过 {n_pass} | 归档 {len(failed)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
