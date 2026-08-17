# 三过滤叠加验证结论 v1（价值陷阱 + T5 + 超买剔除）

> **文档定位**：研究结论文档。记录三过滤叠加（v15）结果——revfilter 在双过滤之上
> 是否收窄 MDD 且保住逆风增量。**性质**：只读结论。脚本与产物：
> `scripts/backtest_a_share_value_quality_monthly_combined_triple_filter_v15.py`、
> `output/analysis_fundamental/a_share_value_quality_monthly_strategy_v15_triple_filter/`。

---

## 1. 背景

v14 双过滤（价值陷阱 + T5）new_coverage +25.06pp、holdout +1.93pp 已采用，但 holdout MDD
−27.6% 偏深。revfilter（超买剔除）单独验证时改善 MDD（−16.6→−13.9%）。本线检验：
**revfilter 叠加在双过滤之上，能否收窄 MDD 且保住 new_coverage 增量？**

## 2. 结果（压力费后净超额，相对 SH000852）

| 臂 | holdout net | holdout IR | holdout MDD | new_coverage net | new_coverage IR |
|---|---|---|---|---|---|
| baseline | +10.16% | 0.92 | −16.6% | −35.01% | −1.84 |
| vt+t5（v14 采用） | +12.09% | 0.99 | −27.6% | −9.95% | −0.58 |
| **vt+t5+revf（三层）** | **+8.98%** | **0.72** | **−33.0%** | **−0.96%** | **−0.07** |

**双门槛：holdout delta −1.18pp（≥−0.5 不通过 ❌）、new_coverage delta +33.64pp（≥+5 通过 ✅）**
→ 判定 **`triple_filter_holdout_erosion`**。

## 3. 关键发现（超出预期的两个事实）

### 3.1 revfilter 把 2026 逆风几乎完全修复（−35.0% → −0.96%，+33.64pp）

三过滤叠加下 new_coverage 净超额从基线的 −35% 修复到 **−0.96%**——2026 逆风基本被消灭。
三个过滤层（T5 恐慌抛售 + 价值陷阱财务恶化 + 超买剔除）合起来覆盖了逆风期的几乎全部
风险维度。这是当前仓库已验证的**最强逆风修复**。

### 3.2 但 holdout 侵蚀 −1.18pp、MDD 反而更深（−27.6% → −33.0%）

与单层 revfilter 改善 MDD 的结论**相反**：在双过滤之上再叠超买剔除，holdout 从 +12.09%
降到 +8.98%（−1.18pp，超硬门槛 −0.5pp），MDD 反而加深到 −33.0%。

**机制推测**：revfilter 的替换逻辑（top K+SLACK 候选内剔除超买、用替补顶上）在双过滤
已经缩小候选池之后，进一步把候选挤向"低波动但非最优"的替补——双过滤本就剔除了部分
top 候选（缩小了 nlargest 池），叠加 revfilter 后替补池质量下降，holdout 期（价值顺风）
这些替补跑输；而 new_coverage 期（2026 逆风）"超买股"恰是逆风重灾区，剔除它们反而大赚
——**revfilter 的收益集中在逆风期、代价集中在顺风期，且代价（holdout 侵蚀 + MDD 加深）
超过收益**。

## 4. 结论与建议

1. **三层不采用**（`triple_filter_holdout_erosion`）：holdout 侵蚀超硬门槛，MDD 恶化。
   **v14 双过滤（价值陷阱 + T5）保持为过滤层最终形态**；
2. **revfilter 的定位修正**：单层时改善 MDD 可作独立选项（v11 已 adopted）；在双过滤
   之上叠加会恶化——**三过滤组合不可行，不再组合**；
3. **2026 逆风对策最终版**：双过滤（+25.06pp）+ 20% 仓位 + 30% 止损；
   revfilter 作为独立可选项（若实盘优先 MDD）或弃用（若优先超额）；
4. **过滤层形态收口**：v11（revfilter）/ v13（价值陷阱）/ v12（T5）/ v14（T5+价值陷阱）
   / v15（三层，拒绝）全部闭环。**不再叠加新层、不再搜索阈值**（遵循不调参美化纪律）。

## 5. 诚实标注

- revfilter 在双过滤之上的逆周期收益/顺周期代价（§3.2）为机制推测，未逐月拆解验证；
- new_coverage 观察区（2025-07~2026-06）三层近乎完美（−0.96%）依赖 2026 逆风环境，
  顺风环境下三层预计更差（holdout 侵蚀已显示）；
- 三层 arm 与 revfilter 单层 arm 的排除集合不同（revfilter 单层作用于全 top20 候选，
  三层作用于双过滤后的候选），不可直接对比排除数量；
- 未做参数搜索（超买阈值/窗口/替补池冻结），不因结果调参。

## 6. 可复现证据

- 脚本：`scripts/backtest_a_share_value_quality_monthly_combined_triple_filter_v15.py`
- 产物：`output/analysis_fundamental/a_share_value_quality_monthly_strategy_v15_triple_filter/`
  （backtest_summary.csv / decision.json / methodology.json / strategy_report.txt /
  overbought_exclusion_log.csv）
- 上游：v14 `..._v14_value_trap_t5_filter/`、v11 `..._v11_revfilter/`

## 7. 变更记录

| 日期 | 变更 |
|---|---|
| 2026-08-14 | 创建：三过滤叠加验证——new_coverage +33.64pp（−35%→−0.96%，逆风近全修复）但 holdout −1.18pp 超门槛、MDD −33.0% 恶化 → `triple_filter_holdout_erosion`；v14 双过滤保持最终形态，过滤层形态收口 |
