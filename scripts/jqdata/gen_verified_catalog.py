#!/usr/bin/env python
"""生成「已验证因子清单」——逐个记录**实测确认的公式**与注意事项。

    bash scripts/jqdata/run.sh scripts/jqdata/gen_verified_catalog.py

产物：output/jqdata_factor_repro/VERIFIED_FACTORS.md

为什么需要：官方文档的公式有多处与实现不符（如 ``equity_turnover_rate`` 公式写反、
``eps_ttm`` 分子口径不同、``Price1M`` 的均值不含当日）。本清单记录的是
**经变体对照实测确认的公式**，并标注每个因子的口径陷阱。
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(Path(__file__).resolve().parent))

from facsim.registry import PLANNED_ORDER  # noqa: E402

SUMMARY = REPO_ROOT / "output/jqdata_factor_repro/SUMMARY.csv"
FORMULAS = REPO_ROOT / ".jqdata/docs/factor_library_formulas.json"
OUT = REPO_ROOT / "output/jqdata_factor_repro/VERIFIED_FACTORS.md"

# ---------------------------------------------------------------- 族说明
FAMILY_DESC = {
    "technical": "纯价量技术指标（均线/布林/MACD/资金流）",
    "risk": "收益矩类风险指标（方差/偏度/峰度/夏普）",
    "momentum": "动量与超买超卖指标（ROC/BIAS/CCI/TRIX/CR/Aroon/PLRC…）",
    "emotion": "情绪与量能指标（换手率/成交量/成交额/ATR/PSY/WVAD…）",
    "pershare": "每股指标（科目 / 总股本）",
    "basics": "财务基础科目（TTM 求和、单期科目、市值）",
    "growth": "增长率指标",
    "quality": "财务质量比率（偿债/周转/盈利/现金流）",
    "style": "风险模型风格因子（CNE5 描述因子）",
}

# ------------------------------------------------- 文档与实现不符之处（实测确认）
# 只有经变体对照确认、且与文档不同的条目才登记在此。
FORMULA_OVERRIDE: dict[str, tuple[str, str]] = {
    # ---- risk 族：文档只给一句中文描述，实际口径全部靠实测标定 ----
    "Variance20": ("pct_change().rolling(20).var(ddof=1) × 250",
                   "**250 不是 252**（252 版误差 2.25e-03、244 版 6.75e-03）；"
                   "简单收益率（对数版 1.17e-02 ❌）；**样本方差** ddof=1"),
    "Variance60": ("pct_change().rolling(60).var(ddof=1) × 250", "同 Variance20"),
    "Variance120": ("pct_change().rolling(120).var(ddof=1) × 250", "同 Variance20"),
    "Skewness20": ("pct_change().rolling(20).skew()",
                   "pandas `.skew()` = **校正 Fisher-Pearson**；未校正的 g1 误差 2.52e-01 ❌"),
    "Skewness60": ("pct_change().rolling(60).skew()", "同 Skewness20"),
    "Skewness120": ("pct_change().rolling(120).skew()", "同 Skewness20"),
    "Kurtosis20": ("pct_change().rolling(20).kurt()",
                   "pandas `.kurt()` 返回**超额峰度**（Fisher）；+3 的 Pearson 峰度误差 3.00e+00 ❌"),
    "Kurtosis60": ("pct_change().rolling(60).kurt()", "同 Kurtosis20"),
    "Kurtosis120": ("pct_change().rolling(120).kurt()", "同 Kurtosis20"),
    "sharpe_ratio_20": ("(Rp − 0.04) / (std(ddof=1) × √250)，Rp = expm1(Σln(1+r)·250/20)",
                        "Rp 是**几何年化收益率**（算术均值×250 版误差 7.69 ❌）；"
                        "std 用 ddof=1（ddof=0 版 2.94e-01 ❌）；√250 不是 √252"),
    "sharpe_ratio_60": ("(Rp − 0.04) / (std(ddof=1) × √250)，Rp = expm1(Σln(1+r)·250/60)", "同 sharpe_ratio_20"),
    "sharpe_ratio_120": ("(Rp − 0.04) / (std(ddof=1) × √250)，Rp = expm1(Σln(1+r)·250/120)", "同 sharpe_ratio_20"),
    # ---- technical 族补充 ----
    "EMA5": ("EMA(C, 5) / C", "`ewm(span=5, adjust=False)`；EMA 无界记忆，span 越大越吃预热"),
    "EMAC10": ("EMA(C, 10) / C", "同 EMA5"),
    "EMAC12": ("EMA(C, 12) / C", "同 EMA5"),
    "EMAC20": ("EMA(C, 20) / C", "同 EMA5"),
    "EMAC26": ("EMA(C, 26) / C", "同 EMA5"),
    "EMAC120": ("EMA(C, 120) / C", "⚠ span=120 需约 600 日预热，窗口不足时误差大（属数据窗口限制）"),
    "MAC5": ("MA(C, 5) / C", "**含当日**（已实测：shift(1) 版误差放大 3 个数量级）"),
    "MAC10": ("MA(C, 10) / C", "含当日"),
    "MAC20": ("MA(C, 20) / C", "含当日"),
    "MAC60": ("MA(C, 60) / C", "含当日"),
    "MAC120": ("MA(C, 120) / C", "含当日"),
    "boll_up": ("(MA(C,20) + 2×STD(C,20)) / C", "**STD 是样本标准差 ddof=1**（ddof=0 版误差 1.28e-03）；含当日"),
    "boll_down": ("(MA(C,20) − 2×STD(C,20)) / C", "同 boll_up"),
    "MFI14": ("100 − 100/(1 + ΣMF⁺/ΣMF⁻)，TYP=(H+L+C)/3，MF=TYP×成交量，按 TYP 涨跌分正负，窗口 14",
              "5/6 标的精确到 2e-4；单只标的异常会使 maxerr 偏大"),
    # ---- pershare：文档用循环描述，必须给出实际科目 ----
    "retained_profit_per_share": ("balance.retained_profit / 总股本", "总股本 = capitalization × 1e4（万股→股）"),
    "retained_earnings_per_share": ("(盈余公积金 + 未分配利润) / 总股本", "留存收益 = surplus_reserve_fund + retained_profit"),
    "surplus_reserve_fund_per_share": ("balance.surplus_reserve_fund / 总股本", ""),
    "capital_reserve_fund_per_share": ("balance.capital_reserve_fund / 总股本", ""),
    "operating_revenue_per_share": ("单季 income.operating_revenue / 总股本", "**单期**口径"),
    "total_operating_revenue_per_share": ("单季 income.total_operating_revenue / 总股本", "**单期**口径"),
    "operating_profit_per_share": ("单季 income.operating_profit / 总股本", "**单期**口径"),
    "operating_profit_per_share_ttm": ("TTM(income.operating_profit) / 总股本", "TTM = 最新 4 个单季之和"),
    "operating_revenue_per_share_ttm": ("TTM(income.operating_revenue) / 总股本", "TTM = 最新 4 个单季之和"),
    "total_operating_revenue_per_share_ttm": ("TTM(income.total_operating_revenue) / 总股本", "TTM = 最新 4 个单季之和"),
    # ---- growth ----
    "total_asset_growth_rate": ("总资产(当季) / 总资产(4 个季度前) − 1",
                                "⚠ 文档写「总资产_4」，实测为 **4 个季度前**（平均相对误差 0.0004%）"),
    "net_asset_growth_rate": ("**总权益**(当季) / **总权益**(4 个季度前) − 1",
                              "⚠ 文档写「三季度前」且未说口径，实测是 **4 个季度前**、且用**总权益**"
                              "而非归母（归母版平均误差 11.0%）"),
    # ---- quality：金融类标的的覆盖率陷阱 ----
    "current_ratio": ("流动资产合计 / 流动负债合计",
                      "**含当日最新一期**报表。⚠ 金融类（银行/保险/券商）报表无「流动/非流动」划分，"
                      "官方对其直接返回 nan（实测覆盖率 67%）"),
    "quick_ratio": ("(流动资产合计 − 存货) / 流动负债合计", "同 current_ratio 的覆盖率说明"),
    "debt_to_asset_ratio": ("负债合计 / 总资产", "期末口径（AvgQ 版更差，corr 0.995）"),
    "debt_to_equity_ratio": ("负债合计 / 归属母公司所有者权益合计", ""),
    # ---- 与文档不同的公式 ----
    "MACDC": ("2 × (DIF − DEA) / C，其中 DIF = EMA(C,12) − EMA(C,26)，DEA = EMA(DIF, 9)",
              "**文档未提 ×2**。四变体对照：(DIF−DEA)/C 误差 2.1e-02、DIF/C 6.8e-02、"
              "DEA/C 7.3e-02，**2×(DIF−DEA)/C 为 1.1e-05**"),
    "equity_turnover_rate": ("股东权益 / 营业总收入(TTM)",
                             "⚠ **文档公式写反**：文档写「营业收入(TTM)/股东权益」，"
                             "但官方发布的是**倒数**（该写法 corr 为 −0.96；倒数版误差 1.4e-07）"),
    "eps_ttm": ("net_profit(TTM) / 总股本",
                "⚠ 文档写「归母净利润(TTM)/总股本」，实测分子是 **net_profit**"
                "（归母版 maxerr 2.379 ❌）"),
    "EBIT": ("单季(净利润 + 所得税 + 财务费用)",
             "⚠ **单期口径，非 TTM**（文档未写）。TTM 版 maxerr 7.7e+10 ❌"),
    "net_operate_cash_flow_to_operate_income": (
        "TTM(经营现金流) / (营业总收入(TTM) − 营业总成本(TTM))",
        "分母必须用「营业**总**收入 − 营业**总**成本」；误用营业收入时 maxerr 2.6e-02"),
    "cash_to_current_liability": (
        "cash_flow.cash_and_equivalents_at_end / AvgQ(流动负债, 4)",
        "⚠ 分子取 **cash_flow 表的期末现金及现金等价物**，**不是** balance.cash_equivalents"
        "（货币资金）；分母用 AvgQ 而非期末"),
    "net_operate_cash_flow_to_total_current_liability": (
        "TTM(经营现金流) / AvgQ(流动负债, 4)",
        "分母用 **AvgQ**：TTM/AvgQ 误差 5.0e-07 ✅ ｜ TTM/期末 0.193 ｜ 单季/AvgQ 1.24"),
    "cashflow_per_share_ttm": (
        "TTM(经营 + 投资 + 筹资三项现金流净额) / 总股本",
        "「现金流量净额」是**三项之和**，不是现金流表里现成的 cash_equivalent_increase 字段"
        "（后者 maxerr 0.172 ❌）"),
    "roe_ttm": ("TTM(归母净利润) / 归母股东权益",
                "⚠ 文档写「净利润/期末股东权益」，实测**分子分母都要用归母口径**"
                "（误差 4.4e-07；用净利润/总权益为 0.397 ❌）"),
    "price_no_fq": ("不复权收盘价（fq='none'）", "定义即不复权，是**唯一不使用后复权**的价格类因子"),
    "single_day_VPT": ("后复权收益率 × 不复权成交量 ÷ 100",
                       "⚠ 文档写「基于当日前复权」。实测：后复权收益率 × 不复权量/100 误差 4.9e+01；"
                       "改用**不复权收益率**在除权日错（3.8e+04）；成交量单位是**手**（÷100）"),
    "money_flow_20": ("Σ₂₀( (H+L+C)/3 × 成交量 )",
                      "⚠ **正文只写「当日资金流量」，实际是 20 日求和**"
                      "（单日版 maxerr 2.0e+11 ❌）"),
    "VROC6": ("(V − REF(V, 5)) / REF(V, 5) × 100", "⚠ **滞后是 n−1 不是 n**（官方 off-by-one）"),
    "VROC12": ("(V − REF(V, 11)) / REF(V, 11) × 100", "⚠ 同上，滞后 n−1"),
    "VR": ("(AVS + ½CVS) / (BVS + ½CVS)，窗口 **24** 日",
           "⚠ **窗口 24，不是 TDX 惯例的 26**（26 版 maxerr 4.4e-01 ❌）；文档未给 N"),
    "BR": ("Σ₂₆(H − 昨收) / Σ₂₆(昨收 − L) × 100，**不 clip 负值**",
           "⚠ **BR 不 clip 负值**，而同族的 AR 需要 clip（口径不一致）；clip 版 maxerr 5.4e+01 ❌"),
    "AR": ("Σ₂₆(H − 今开) / Σ₂₆(今开 − L) × 100，**clip 负值为 0**", "n=26，文档明写"),
    "arron_down_25": ("**[HIGH]** 序列的 argmin 位置 → (idx+1)/25 × 100",
                      "⚠⚠ **用 HIGH 序列，不是 LOW**（与 Aroon 通行定义相反）。"
                      "宽池 160 只：HIGH 版 3/160 超标、LOW 版 **156/160** ❌"),
    "arron_up_25": ("HIGH 序列的 argmax 位置 → (idx+1)/25 × 100",
                    "并列极值取**末次**（取首次 maxerr 4.4e+01 ❌）；宽池 9/160 超标"),
    "MASS": ("Σ₂₅( SMA(H−L, 9) / SMA(SMA(H−L,9), 9) )",
             "⚠ 文档只写「MASS(N1=9,N2=25,M=6)」无公式。实测用 **SMA 而非 EMA**"
             "（EMA 版 corr 0.972 ❌）"),
    "PLRC6": ("回归斜率(C, 6) / MA(C, 6)", "文档：(close/mean(close)) = β·t + α；逐日滚动均值归一化版误差 2.6e-02 ❌"),
    "PLRC12": ("回归斜率(C, 12) / MA(C, 12)", "同上"),
    "PLRC24": ("回归斜率(C, 24) / MA(C, 24)", "同上"),
    "turnover_volatility": ("std(换手率, 20, ddof=1) ÷ 100",
                            "⚠ 文档说「取 20 日换手率标准差」，官方返回的是**小数**而非百分数"
                            "（off/loc 恒为 0.010000）"),
    "share_turnover_monthly": ("ln( Σ₂₁(换手率 ÷ 100) )",
                               "⚠ 官方先把换手率换算成**小数**再取对数；"
                               "未换算时 maxerr 恒为 ln(100)=4.605171"),
    "average_share_turnover_quarterly": ("ln( Σ₆₃(换手率 ÷ 100) ÷ 3 )",
                                          "⚠「过去 3 个月平均」= **3 个月度和的均值**，不是 63 日均值"
                                          "（后者恰差 ln(21)=3.0445）"),
    "market_cap": ("valuation.market_cap × 1e8",
                   "⚠ valuation 单位是**亿元**，因子单位是**元**"),
    "circulating_market_cap": ("valuation.circulating_market_cap × 1e8", "同上，×1e8"),
    "net_operate_cash_flow_per_share": ("**单季**经营现金流 / 总股本",
                                         "⚠ 名字含「12 个月」但实测是**单期**（单季版 4.97e-07 ✅，TTM 版 42.2 ❌）"),
    "net_asset_per_share": ("(归母权益 − 其他权益工具) / 总股本", "总股本 = valuation.capitalization × 1e4（单位万股）"),
    "cash_and_equivalents_per_share": ("cash_flow.cash_and_equivalents_at_end / 总股本",
                                        "⚠ 不能用 balance.cash_equivalents（货币资金），corr 仅 0.80"),
    "Price1M": ("当日收盘价 / MA(C, 20).shift(1) − 1",
                "⚠⚠ 均值窗口是**不含当日的过去 20 日**。文档写「(21天)」是**跨度**"
                "（20 历史日 + 当日），但均值不含当日。MA(21) 版 3.7e-02 ❌"),
    "Price3M": ("当日收盘价 / MA(C, 60).shift(1) − 1", "⚠ 同上，不含当日的过去 60 日"),
}

# ---------------------------------------------------------------- 全局约定
GLOBAL_NOTES = """
### G1. 复权

- **统一用后复权**（`fq='post'`），全项目唯一来源 `conventions.FQ`。
- 前复权与后复权对**比值/均值类因子结果完全相同**（两者只差一个全局常数，
  比值把它约掉）——实测 ROC6/Price1M 的前后复权 maxerr 逐位相同。
- **不复权**只用于 `price_no_fq` 一个因子；VPT 用到不复权**成交量**。

### G2. ⚠ 必须使用 2 位小数价格（`round=True`）

官方因子是基于 **2 位小数**的原始价计算的。实测把 `get_price(..., round=False)`
（全精度）接进来，**结果反而变差**（全局 150 → 132 通过，risk 族 12/12 GOOD 全退化为 APPROX）。
复现的定义是**对齐官方口径**，不是追求更高精度。

### G3. 算子口径

| 项 | 口径 |
|---|---|
| `MA(X,N)` | `rolling(N).mean()`，**含当日**（唯一例外：`Price1M/Price3M`） |
| `STD(X,N)` | **样本标准差** `rolling(N).std(ddof=1)`（ddof=0 误差放大 450 倍） |
| `EMA(X,N)` | `ewm(span=N, adjust=False).mean()` |
| 年化交易日数 | **250**（不是 252，也不是 244） |
| 夏普分子 | **几何年化收益率** `expm1(Σln(1+r)·250/w)` |
| 峰度 | pandas `.kurt()` = **超额峰度**（Fisher），不是 Pearson(+3) |
| 偏度 | pandas `.skew()` = 校正 Fisher-Pearson |

### G4. 财务数据口径

- 用**最新一期单季度**数据；TTM = **截至比对日已披露的最新 4 个单季之和**。
  ⚠ 必须取「最新 4 季」而非固定某一年——这是早期误判「TTM 不可复现」的根因。
- `AvgQ(X,4)` = 最新 4 个单季的**均值**（用于资产负债表时点科目）。
- 单位陷阱：`valuation.market_cap` 是**亿元**（×1e8）；
  `valuation.capitalization` 是**万股**（×1e4）。
- **「货币资金」≠「现金及现金等价物」**：前者 `balance.cash_equivalents`，
  后者 `cash_flow.cash_and_equivalents_at_end`。

### G5. 精度判定的三个口径

| 判定 | 统计量 | 用途 |
|---|---|---|
| `verdict` | maxerr / mean(｜官方值｜) | 「能否逐位复现对方流水线」——对尾部极值最敏感 |
| `verdict_robust` | p99 误差 | 中间口径 |
| **`verdict_med`** | **中位误差** | **「这个因子实际能不能用」——推荐作为可用性主判据** |

⚠ `maxerr` 会被极少数观测（如某只低价股某天）完全支配。例如 `arron_up_25`
在 94.4% 的标的上误差是 **7e-15**（精确），却因 9/160 只离群而 maxerr 达 84。

### G6. ⚠ 价格类因子的精度上限（结构性，不可修复）

`后复权价 = 不复权价(2位小数) × 复权因子`，故相对分辨率 ≈ `0.005 / 原始股价`。
对 ×100 或做差放大型因子：

```
err ≈ A × 0.005 / 原始股价      （实测 log-log 斜率 −1.08，理论 −1）
```

**A 股中位价约 15.9 元，因此下列因子在典型价位上不可能达到 GOOD 档**：

| 因子 | 达到 GOOD 需原始价 ≥ |
|---|---|
| `ROC6` | 378.83 元 |
| `BIAS10` | 310.80 元 |
| `single_day_VPT` | 246.98 元 |
| `CCI20` | 146.84 元 |

实用含义：这些因子**数值有偏差，但排序几乎完全一致**（corr ≥ 0.99999），
**横截面排序/分组用法有效**，精确数值比较无效。
"""


def main() -> int:
    d = pd.read_csv(SUMMARY)
    info = json.loads(FORMULAS.read_text(encoding="utf-8"))
    d["passing"] = d["verdict_med"].isin(["EXACT", "GOOD"])

    L: list[str] = []
    L.append("# 聚宽因子复现 —— 已验证因子清单\n")
    L.append("本清单记录**经变体对照实测确认**的因子公式与口径注意事项。")
    L.append("与官方文档不同之处均已标出——文档有若干处与实现不符。\n")
    tot = int(d["passing"].sum())
    L.append(f"- 通过因子数（中位口径）：**{tot}** / {len(d)}")
    L.append("- 验证区间：`2026-05-06` ~ `2026-06-16`（6 只标的）")
    L.append("- 判定：`verdict_med`（中位误差 / 官方值量级）")
    L.append("- 生成脚本：`scripts/jqdata/gen_verified_catalog.py`\n")
    L.append("---\n")
    L.append("## 通用口径约定\n")
    L.append(GLOBAL_NOTES)
    L.append("\n---\n")
    L.append("## 逐族清单\n")
    L.append("「已验证公式」列是与文档核对后的实际口径；⚠ 标记表示**文档会误导你**。\n")
    L.append("> 说明：若「已验证公式」单元格只是中文名称的重复（如「每股未分配利润」），"
             "表示**官方文档未给可执行公式**，该因子的口径由因子名 + 变体对照实测标定得出，"
             "具体实现见 `scripts/jqdata/facsim/families/*.py`。\n")

    for fam in PLANNED_ORDER:
        sub = d[(d.family == fam) & d["passing"]]
        if sub.empty:
            continue
        L.append(f"### {fam}（{len(sub)} 个通过）—— {FAMILY_DESC.get(fam, '')}\n")
        L.append("| 因子 | 中文名 | 已验证公式 | 精度 | 注意事项 |")
        L.append("|---|---|---|---|---|")
        for r in sub.sort_values("med_rel_err").itertuples():
            v = info.get(r.factor, {})
            nm = v.get("name", "")
            doc = (v.get("formula") or v.get("description") or "").replace("\n", " ")
            if r.factor in FORMULA_OVERRIDE:
                fo, note = FORMULA_OVERRIDE[r.factor]
            else:
                fo, note = doc[:70], ""
            pr = f"{r.verdict_med} {r.med_rel_err:.1e}"
            L.append(f"| `{r.factor}` | {nm} | {fo} | {pr} | {note} |")
        L.append("")

    L.append("\n---\n")
    L.append("## 附：未通过因子\n")
    bad = d[~d["passing"] & d["implemented"]]
    L.append(f"共 {len(bad)} 个（中位口径）。失败原因见 `SUMMARY.md` §四点五。\n")
    L.append("| 因子 | 族 | 中位相对误差 |")
    L.append("|---|---|---|")
    for r in bad.sort_values("med_rel_err", ascending=False).itertuples():
        L.append(f"| `{r.factor}` | {r.family} | {r.med_rel_err:.3g} |")

    OUT.write_text("\n".join(L), encoding="utf-8")
    print(f"✅ 已生成 {OUT}")
    print(f"   通过 {tot} 个 / 未通过 {len(bad)} 个")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
