# 纯量价日频策略回测归档 v1

## 1. 决策

状态：`not_viable_closed`（main 判定 `dead`）

**纯量价日频策略（换手率水平 + 偏度，MVI 中性化，TopkDropout topk50 日频）在
2022-2026 扣成本后不成立。** 但失败原因是分裂的、极有诊断价值：
- **换手率水平因子在组合层面彻底反转**（turnonly gross 超额 -0.49，年化负），
  IC 正但组合亏——**"IC 有效 ≠ 可交易"的教科书案例**；
- **偏度因子弱正**（skewonly gross +0.068/IR 0.54，net +0.032/IR 0.25），
  未达 viable 门槛，2024 年大负、2025 年归零，不稳定。

## 2. 协议与产物

- 协议：`research/protocols/a_share_pv_daily_strategy_protocol_v1.md`
  （状态 `executed_not_viable`）
- 脚本：`scripts/backtest_a_share_pv_daily_strategy_v1.py`
- 产物：`output/analysis_static/a_share_pv_daily_strategy_v1/`
  （backtest_summary.csv / yearly_summary_{main,turnonly,skewonly}.csv /
  daily_report_main_base.csv.gz / decision.json / validation_report.txt）

口径：母池 5544 只，2022-01 ~ 2026-07，TopkDropout topk=50 n_drop=5 日频、
T+1 开盘成交、SH000852 基准、base/stress 两套费率；信号 = 逐日 MVI 残差
（log circ_mv + std20 + 申万 L1）合成 0.5·rank(TURN)+0.5·rank(SKEW)。

## 3. 主结果（全期）

| 版本 | 费率 | gross超额 | gross IR | net超额 | net IR | 日均换手 | 年化成本拖累 |
|---|---|---|---|---|---|---|---|
| main | base | -0.281 | -1.55 | -0.329 | -1.82 | 17.2% | 4.8% |
| turnonly | base | -0.488 | -2.41 | -0.557 | -2.75 | 14.5% | 6.8% |
| skewonly | base | **+0.068** | **0.54** | **+0.032** | **0.25** | 15.4% | 3.7% |
| skewonly | stress | +0.072 | 0.56 | -0.001 | -0.01 | 15.4% | 7.3% |

skewonly 分年度 net 超额：2022 +0.153 / 2023 +0.086 / 2024 **-0.127** /
2025 +0.010 / 2026 +0.040（3/5 年正，2024 大负）。

## 4. 关键发现：IC 正 ≠ 可交易（本回测的核心教训）

**battery v1 中 TURNOVER_LEVEL5 的 IC +0.064（正）、MVI 中性化后 alpha_confirmed，
但回测 turnonly gross 超额 -0.488（年化负）**。两个层面的信号完全相反，根因：

1. **IC 是全市场截面秩相关，top50 是极值组合**：换手率水平的 IC 由高换手极端
   组（Q5）驱动（中性化复验五分组 Q5 跳升），但 Q5 极端高换手股 = 题材/炒作股，
   在 top50 集中持有后系统性回落（均值回归），**组合收益与截面秩相关脱钩**。
2. **方向本就与文献相反**（battery v1 已标注）：高换手→高收益违背"高换手=高关注
   =负 alpha"，组合层证实该方向在实盘不可交易。
3. 偏度因子弱正（skewonly IR 0.25 < 0.5 门槛），且 2024 年 -0.127 大负——排序
   能力（battery ICIR 0.37）不足以转化为稳定的组合超额。

**诊断结论**：单靠 RankIC/ICIR 判定因子"有效"是不够的——必须过真实调仓回测
（扣成本）才算数。这两个因子是"IC 有效、组合无效"的典型。

## 5. 判定与建议

1. **纯量价日频（本两因子）关闭**：换手率水平不可交易（方向反转）、偏度弱且
   不稳（IR 0.25）。不再投入本口径。
2. **组合版（基本面域 + 量价快信号）前提未满足**：协议 §1 约定 `viable` 才立项
   组合版；本验证 `dead`，组合版**不自动启动**。
3. **可选讨论项（不自动执行）**：基本面域（价值质量池）过滤掉题材/高换手股后，
   偏度因子**在域内**是否恢复稳定超额——这是对"偏度弱正"的挽救尝试，但属新
   立项，需用户决策。换手率水平因子建议放弃（方向在组合层反转，域内大概率
   仍受题材污染）。

## 6. 诚实标注

- 2026-07-24 SH000852 复权断层已修复（`sh000852_factor_break_repair_v1.md`），
  回测窗口完整到 2026-07-31，无污染。
- gross 为负排除了"成本吃光 alpha"的解释——是**因子本身在组合层无 alpha**。
- 未做参数搜索（topk/n_drop 冻结为仓库结论值）；调参美化路径违反项目纪律。

## 7. 可复现证据

- 协议/脚本/产物见 §2。判定阈值：net 超额>0 且 net IR≥0.5 → viable；
  0<IR<0.5 → weak；≤0 → dead（`metrics_judgment_standard.md`）。

## 8. 变更记录

| 日期 | 变更 |
|---|---|
| 2026-08-13 | 创建：纯量价日频回测 dead；换手率组合层方向反转（IC 正≠可交易）、偏度弱正不稳；组合版不自动启动，保留域内偏度讨论项 |
