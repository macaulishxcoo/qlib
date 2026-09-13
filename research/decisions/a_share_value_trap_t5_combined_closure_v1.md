# 价值陷阱 + T5 负面事件双过滤叠加验证结论 v1

> **文档定位**：研究结论文档。记录两条探索线（价值陷阱过滤层、T5 负面事件剔除层）
> 的**叠加验证**结果，回答"两个已验证过滤层能否叠加、叠加增量多少"。供后续会话
> 直接引用，避免重复研究。
> **性质**：只读结论。脚本与产物：
> `scripts/backtest_a_share_value_quality_monthly_value_trap_t5_filter_v14.py`、
> `output/analysis_fundamental/a_share_value_quality_monthly_strategy_v14_value_trap_t5_filter/`。
> 上游：`research/decisions/a_share_value_trap_identification_closure_v1.md`（v13）、
> `research/decisions/a_share_negative_event_subtype_closure_v1.md`（v12）。

---

## 1. 背景

两线分别验证了两个过滤层：
- **价值陷阱（v13）**：剔除财务恶化股（`deter_any2`，净利/营收/经营现金流 YoY 中
  ≥2 个为负）→ new_coverage +8.67pp；
- **T5 跌幅上榜（v12）**：剔除调仓日前 20 交易日内有跌幅上榜事件的股票 → new_coverage
  **+20.33pp**。

两线均判定 adopted，且机制互补（财务恶化**状态** vs 近期**交易行为**）。本线检验叠加：
**双过滤同时启用是否比单一过滤更好，还是被更强的 T5 吸收？**

## 2. 实验设计（四臂同环境对比）

| 臂 | 规则 |
|---|---|
| baseline | v8 top15 同构（无过滤） |
| vt | baseline + 剔除 deter_any2（价值陷阱） |
| t5 | baseline + 剔除跌幅上榜 20 日窗口 |
| **vt+t5** | baseline + 双过滤 |

同脚本同数据环境；验收双门槛（holdout ≥−0.5pp、new_coverage ≥+5pp，与 v12/v13 一致），
另算叠加 vs T5 单层增量。

## 3. 结果（压力费后净超额，相对 SH000852）

| 臂 | holdout net | holdout IR | holdout MDD | new_coverage net | new_coverage IR |
|---|---|---|---|---|---|
| baseline | +10.16% | 0.92 | −16.6% | −35.01% | −1.84 |
| vt | +12.14% | 0.97 | **−30.7%** | −26.34% | −1.84 |
| t5 | +10.89% | 1.05 | **−15.5%** | −14.68% | −0.57 |
| **vt+t5** | **+12.09%** | **0.99** | −27.6% | **−9.95%** | **−0.58** |

**双门槛：holdout delta +1.93pp ✅、new_coverage delta +25.06pp ✅ → `combined_filter_adopted`。**

**叠加 vs T5 单层（new_coverage 增量）：+4.73pp** —— 价值陷阱在 T5 之上仍有实质增量，
未被吸收。机制互补确认：T5（近期放量大跌上榜=被抛售）与价值陷阱（财务恶化状态）
是两个正交的风险维度。

## 4. 关键发现

### 4.1 2026 逆风最强修复：−35.0% → −9.95%（+25.06pp）

双过滤把 2026 价值逆风净超额的**约 2/3** 修复掉，只剩 −9.95%。对比单层：
T5 单层 −14.68%、价值陷阱单层 −26.34%。叠加的修复接近三者相加（+8.67+20.33=+29pp
的理论简单和，实测 +25.06pp，略低于简单和——部分重叠，但增量仍显著）。

### 4.2 MDD 折中：叠加 −27.6% 介于两单层之间

- T5 单层 holdout MDD 最优（−15.5%，比基线还改善）；
- 价值陷阱单层 holdout MDD 最差（−30.7%）；
- 叠加 −27.6%：T5 部分补偿了价值陷阱的 MDD 恶化，但仍明显深于基线（−16.6%）与
  T5 单层。**对个人实盘（MDD 敏感）这是必须权衡的点**。

### 4.3 确认期（2020-2022）仍是双过滤的软肋

confirmation 段 vt 臂转负（−0.04%）、vt+t5 臂 −0.54%——与 v13 的"dev/conf 组合层
削弱"一致。**过滤层的代价集中在顺风/中性期，收益集中在逆风期（new_coverage）**。
这不是 bug，是"用部分顺风期收益换逆风期保护"的权衡。

### 4.4 三过滤层的全景（2026 逆风修复能力排序）

| 过滤层 | new_coverage delta | holdout delta | holdout MDD 影响 |
|---|---|---|---|
| revfilter（+20% 涨幅剔除） | 约 +2pp | −1.11pp | 改善（−16.6→−13.9） |
| 价值陷阱（财务恶化） | +8.67pp | +1.98pp | 恶化（→−30.7） |
| T5（跌幅上榜） | +20.33pp | +0.74pp | 改善（→−15.5） |
| **双叠加（T5+价值陷阱）** | **+25.06pp** | **+1.93pp** | 折中（→−27.6） |

## 5. 结论与建议

1. **双过滤叠加 adopted**：T5 + 价值陷阱机制互补、增量显著（+4.73pp vs T5 单层），
   是当前已验证的 2026 逆风最强修复（+25.06pp，holdout 反升 +1.93pp）；
2. **实盘配置建议（用户决策）**：
   - T5 单层：new_coverage +20.33pp、holdout MDD 最优（−15.5%）——**MDD 敏感型
     首选**；
   - 双叠加：new_coverage +25.06pp、holdout MDD −27.6%——**逆风保护最大化**，但
     需接受更深回撤（个人 100K 仓位下 −27.6K 最坏亏损）；
   - 若选双叠加，可与 revfilter（MDD 改善）再叠一层验证（revfilter+双叠加是否
     进一步收窄 MDD，属另一立项）；
3. **2026 逆风对策的最终状态**：逆风 = 纯风格暴露（约 1/3，仍 −9.95%）+ 可过滤
   成分（约 2/3，已验证修复 +25.06pp）。剩余部分仍需 20% 仓位 + 30% 硬止损钝化
   （部署协议 v1），但"可修复部分"已大幅实证。
4. **不再重复**：三个过滤层均已闭环验证，不需要再搜索阈值/窗口/组合。

## 6. 诚实标注

- development/confirmation 期事件数据不覆盖（2022 起），vt 臂在这两期等价基线
  （无恶化剔除）——但 vt+t5 臂在 confirmation 仍转负（−0.54%），说明负贡献来自
  vt 过滤而非事件缺失；
- new_coverage 为观察区（2025-07~2026-06，11 个月），+25.06pp 依赖这一窗口的
  逆风环境，顺风环境下过滤层可能纯拖累（如 confirmation 显示）——**regime 依赖
  未消除，需在实盘以模拟盘持续观察**；
- 叠加 arm 的 MDD（−27.6%）未列入验收门槛（协议只查 net 超额与 IR），如实记录；
- 未做参数搜索（窗口/阈值/组合方式冻结），不因结果调参。

## 7. 可复现证据

- 脚本：`scripts/backtest_a_share_value_quality_monthly_value_trap_t5_filter_v14.py`
- 产物：`output/analysis_fundamental/a_share_value_quality_monthly_strategy_v14_value_trap_t5_filter/`
  （backtest_summary.csv / decision.json / methodology.json / strategy_report.txt）
- 上游：v13 `..._v13_value_trap_filter/`、v12 `..._v12_negative_event_filter/`
- 标签口径：本线与 v13/v12 一致（T+1 开盘入场，与主线历史口径一致）

## 8. 变更记录

| 日期 | 变更 |
|---|---|
| 2026-08-14 | 创建：价值陷阱 + T5 双过滤叠加验证——new_coverage +25.06pp（−35.0%→−9.95%）、holdout +1.93pp、叠加 vs T5 增量 +4.73pp → `combined_filter_adopted`；MDD 折中 −27.6% 如实标注；2026 逆风对策更新（约 2/3 可过滤、1/3 纯风格暴露） |
