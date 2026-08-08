# 基本面研究线冻结决策 v1

## 1. 决策

状态：`frozen_archived`

**停止全部 A 股基本面单因子研究轨道**（财务 PIT 下载、数据审计、事件面板构建、
单因子验证、研究协议与规格文档的扩写）。此前的两个命题（盈利现金质量、营运资本
质量）已分别关闭，本决策将**整个基本面信息源研究轨道**一并冻结，不再开展新的
基本面命题验证。

冻结对象（不删除、不再修改、不再追加下载）：

| 类别 | 内容 |
|---|---|
| 数据 | `data/external/tushare/a_share_financial_pit_v1`（623M）、`a_share_style_pit_v1`（73M）、`data/derived/` 两个事件面板（31M） |
| 脚本 | `scripts/data_collector/` 下 13 个 `*v1*` 下载/审计/建面板脚本，`scripts/` 下 3 个 `analyze_a_share_*` 脚本 |
| 文档 | `research/protocols/` 6 份、`research/specifications/` 5 份、`research/decisions/` 4 份基本面相关文档（`earnings_cash_quality_hypothesis_closure`、`working_capital_quality_hypothesis_closure`、`next_fundamental_research_direction_comparison`、`shenzhen_shanghai_tushare_pit_acceptance`，含本决策） |
| 产物 | `output/analysis_fundamental/`、`output/data_audits/` 下基本面相关目录 |

## 2. 冻结原因

目标重锚：本项目的目标是**沪深主板日频选股量化交易系统**，不是基本面因子研究。

| 事实 | 结论 |
|---|---|
| 2021 年后价量 alpha 衰减（DEV_LOG 根因诊断） | 主线真问题是信号失效，不是数据缺失 |
| 已做两次基本面命题验证均未通过确认期 | 现有研究投入产出比已为负 |
| 624M 财务数据 + 13 个数据工程脚本 + 15 份文档 | 精力从"把系统跑起来"转移到"把数据做完美" |
| 决策已出（8-5/8-7 命题关闭）但动作未停（8-7 仍下载资产负债表） | 必须用显式决策文档切断惯性 |

日频交易系统对基本面的需求是**慢变量过滤**（当前季度质量分层），不是逐条
PIT 审计。PIT 严谨性是因子研究论文的要求，不是日频系统的要求。

## 3. 基本面接入的最小版本（解除冻结时唯一允许的接入方式）

若主线系统跑稳后确需基本面增强，只允许使用以下最小路径：

1. tushare `fina_indicator` 直接拉取**每只股票最新一期** ROE / 营收增速 /
   经营现金流指标；
2. 构造简单质量分，作为**过滤层**（剔除质量分后 20%）叠加在价量信号之上；
3. 不做事件面板、不做公告日对齐、不做 PIT 历史重建。

验收标准：一个下午能跑通；否则说明接入方式又偏离了"过滤层"定位。

## 4. 解除冻结的条件

只有同时满足以下三条才允许回到基本面轨道：

1. 主线日频系统已连续运行且产生实际选股名单；
2. 价量信号的 IC 或回测已确认不足以支撑策略；
3. 重新立项时必须先写一页纸选题评审（经济机制、可得时点、周期匹配、
   容量风险、可证伪性），且只做一轮最小实验。

## 5. 新工作启动三问门槛（适用于一切后续工作）

任何新任务开工前必须通过：

1. **它服务哪个决策？** 不做会怎样？——回答不出就直接不做。
2. **最小成本版本是什么？** 能用 tushare 接口直接拉就不建面板，能拉最新一期
   就不重建历史。
3. **验收标准是什么？** 不达标就停，不扩建。

> 保留对象（不属于冻结范围）：`research/charters/a_share_research_universe_charter_v1.md`
> 定义的沪深普通 A 股研究母池与分层报告章程，对未来主线阶段 5/6 的股票池过滤
> 仍有效，继续作为母池定义使用。

## 6. 可复现证据

- 盈利现金质量命题关闭：`research/decisions/a_share_earnings_cash_quality_hypothesis_closure_v1.md`
- 营运资本质量命题关闭：`research/decisions/a_share_working_capital_quality_hypothesis_closure_v1.md`
- 数据源验收：`research/decisions/shenzhen_shanghai_tushare_pit_acceptance_v1.md`
- 方向比较备忘录（冻结前的最后一份选题文档）：
  `research/decisions/a_share_next_fundamental_research_direction_comparison_v1.md`
- 主线路线图：`research/ROADMAP.md`
