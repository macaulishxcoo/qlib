# 事件/趋势脚本标签 bug 复核结论 v1

> **文档定位**：技术复核记录。2026-08-14 在"负面事件分类型研究"中发现既有事件脚本
> 的 FWD 标签公式方向反转（≈ −r），对已关闭实验（事件流、趋势持续性）进行修正
> 标签重跑，记录新旧结论对照与处置。**本文档不改变任何实验协议，只更正结论口径。**

---

## 1. Bug 描述

既有脚本（`analyze_a_share_events_daily_v1.py`、
`analyze_a_share_trend_persistence_v1.py`、
`analyze_a_share_daily_valuation_s1_v1.py`、
`analyze_a_share_price_volume_factor_neutralization_v1.py`、
`analyze_kdj_macd_crossover_compare_v1.py`、
`analyze_a_share_price_volume_factor_short_term_v1.py`）使用：

```python
FWD_h = open.shift(-1) / close.shift(-(h+1)) - 1   # = open[t+1]/close[t+h+1] - 1
```

该式 ≈ `1/(1+r) − 1 ≈ −r`（r = 正确持有期收益），实测与正确 open-to-open
`open[t+1+h]/open[t+1] − 1` 的 **corr = −0.93**——事件/信号后超额的方向结论反转。

**根因**：分子用 `open[t+1]`（入场日开盘）、分母用 `close[t+h+1]`（出场日收盘），
两值时间顺序颠倒（出场日应在入场日之后），得到的是"入场相对出场的折价"≈ 负收益。

## 2. 复核重跑（正确标签，v2-labelfix）

| 脚本 | 原结论 | 修正后结论 | 变化 |
|---|---|---|---|
| `analyze_a_share_events_daily_v2_labelfix.py` | 事件流 `not_supported`（龙虎榜=动量代理） | **`event_stream_viable`（方向反转）** | 见 §3 |
| `analyze_a_share_trend_persistence_v2_labelfix.py` | `supported`（TS_UP60 趋势确认层） | **`not_supported`（状态反转）** | 见 §4 |

## 3. 事件流复核结果（2022-01 ~ 2026-07，市场调整超额）

| 事件 | h=5 超额 | t | h=20 超额 | t | 修正后解读 |
|---|---|---|---|---|---|
| 增持 | +0.42% | +4.64 | +0.75% | +4.44 | **正超额**（原标签下显示为负） |
| 减持 | +0.16% | +3.19 | +0.55% | +5.40 | 正超额 |
| 解禁 | +0.52% | +7.00 | +1.06% | +7.54 | 正超额 |
| **龙虎榜（全部）** | **−1.22%** | **−17.57** | **−2.85%** | **−25.36** | **显著负漂移，五年全负** |

**关键更正**：原结论"龙虎榜上榜=动量代理、事件无方向信息"**不成立**。正确标签下
龙虎榜上榜后 5/10/20 日均显著**负漂移**（−1.2%/−1.9%/−2.9%），2022-2026 五年方向
一致——这是**注意力反转**（上榜=短期过热 → 回落），不是动量延续。E2 显示净买
（−1.29%）与净卖（−1.18%）均负、无单调区分 → 负漂移来自"上榜"本身（关注度峰值），
与买卖方向无关。

**与本线 T5 的关系**：负面事件分类型研究中的 T5（跌幅上榜）负漂移（−1.87%/20d）
与本次复核的"龙虎榜全部负漂移"（−2.85%/20d）一致且更强（全上榜 vs 仅跌幅类）。
T5 的"跌透组反转"异质性（Q1 +5.47%）是日频策略线（`a_share_t5_daily_strategy_proposal_v1.md`）
的立项基础。

## 4. 趋势持续性复核结果（2022-01 ~ 2026-07，h=5）

| 统计 | 原结论 | 修正后 | 解读 |
|---|---|---|---|
| T1 状态价差（年化） | +0.166（显著） | **−0.075（t=−2.65）** | 方向反转 |
| T1 2022-2025 同向年数 | — | **0/4** | 无稳定性 |
| T2 vol-scaled 价差 | — | −0.158（t=−3.86） | 方向反转 |
| T3 控制动量后增量 | — | −0.016（t=−1.39） | 不显著 |
| T4 日频 IC/ICIR | — | −0.032/−0.26 | 弱负 |

**关键更正**：原结论"TS_UP60 趋势持续性 = 系统性暴露/趋势确认层（supported）"**不成立**。
正确标签下为**状态反转**：过去 60 日上涨的股票未来 5 日跑输（年化 −7.5%），
2022-2025 无一年同向。修正后判定 `not_supported`，"趋势确认层候选"作废，
价量线收口结论不变（甚至更强——连趋势状态都反转）。

## 5. 其他受影响脚本（grep 确认，逐项待复核）

```bash
grep -rn "shift(-(h + 1))\|shift(-(h+1))" scripts/ --include="*.py"
```

| 脚本 | 影响 | 状态 |
|---|---|---|
| `analyze_a_share_daily_valuation_s1_v1.py` | 日频估值 FWD 标签方向 | 待复核（原结论"负 IC、无 alpha"——修正后方向翻转，但"无 alpha"的绝对值结论可能不变） |
| `analyze_a_share_price_volume_factor_neutralization_v1.py` | 换手率/偏度中性化标签 | 待复核（存活因子 h=5 IC 为正——修正后为负？需重跑确认） |
| `analyze_kdj_macd_crossover_compare_v1.py` | KDJ/MACD 交叉标签 | 待复核 |
| `analyze_a_share_price_volume_factor_short_term_v1.py` | 短周期标签 | 待复核（"h=5 有效 h=40 反转"的结论可能完全反转） |
| `analyze_a_share_pead_v1.py` | 已用 open_wide 正确口径（entry/exit open） | **免复核** |
| `analyze_a_share_negative_event_subtype_v1.py` | 本线新脚本，正确口径 | 无影响 |

**注意**：这些脚本的**相对比较结论**（如 A vs B 的差异、分年度方向、单调性）基于
同一批数据的内部比较，反转标签对所有组一视同仁，**部分结论（单调性、组间差异、
正交性）仍成立**；只有**绝对方向结论**（"正超额/负超额""正 IC/负 IC"）需重估。
复核原则：逐脚本重跑（输出 v2-labelfix 目录），只更新方向性表述，不重开实验。

## 6. 处置

1. **事件流结论更正**：`a_share_events_daily_stream_assessment_v1.md` 的
   `not_supported`（动量代理）改为"**龙虎榜上榜后显著负漂移（注意力反转）**，
   事件有方向信息但为反向"；`a_share_daily_alpha_exhaustion_manifest_v1.md` §2 第 5 行
   同步更正；
2. **趋势持续性结论更正**：`a_share_trend_persistence_protocol_v1.md` 的
   `executed_supported` 改为"**修正标签后 not_supported（状态反转）**"；
3. **价量短周期结论更正**（待重跑）：若 h=5 正 IC 翻转为负，"换手率/偏度存活"的
   结论需重估——这与本线 T5 事件层（跌幅上榜负漂移）方向一致，可互相印证；
4. 所有更正文档标注"2026-08-14 标签 bug 复核"来源，保留原产物（不删除，可审计）。

## 7. 可复现证据

- 复核脚本：`scripts/analyze_a_share_events_daily_labelfix_v2.py`、
  `scripts/analyze_a_share_trend_persistence_labelfix_v2.py`
- 产物：`output/analysis_static/a_share_events_daily_v2_labelfix/`、
  `output/analysis_static/a_share_trend_persistence_v2_labelfix/`
- 原始产物（保留）：`output/analysis_static/a_share_events_daily_v1/`、
  `output/analysis_static/a_share_trend_persistence_v1/`
- 发现记录：`DEV_LOG_DailyStrategyExploration.md` §2.3/§6

## 8. 变更记录

| 日期 | 变更 |
|---|---|
| 2026-08-14 | 创建：标签 bug 复核结论——事件流方向反转（龙虎榜负漂移注意力反转）、趋势持续性 supported→not_supported；列出其余 4 个受影响脚本待复核 |
