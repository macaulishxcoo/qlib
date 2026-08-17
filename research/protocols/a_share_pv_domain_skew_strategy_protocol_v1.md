# 域内偏度日频策略协议 v1

状态：`executed_domain_revived`（2026-08-13 执行；域内偏度 net +0.061/IR 0.60，
2024 失效（-0.127）被域过滤消除（-0.001）→ 按协议判定 `domain_revived`；但
域内偏度 < 域内 composite（+0.122/IR 1.34），偏度增量有限，域内基本面日频化
为更优产出；结论归档见 `research/decisions/a_share_pv_domain_skew_strategy_closure_v1.md`）

## 1. 三问门槛

| 问 | 答 |
|---|---|
| 服务哪个决策 | 偏度因子（SKEW60）在全市场 top50 组合层不可交易（`a_share_pv_daily_strategy_closure_v1.md`：net +0.032/IR 0.25，2024 年 -0.127）。本验证回答：**在基本面域内（过滤题材/炒作股后）偏度是否恢复为稳定超额**——偏度因子是否可救活 |
| 最小版本 | 基本面域（主线四因子 composite 中性化前 50%）内按 SKEW60 MVI 残差排序 → TopkDropout topk50 日频 → SH000852，base 费率；三个版本对比（域内偏度 / 域内 composite / 全市场偏度），窗口 2022-01~2025-06（财务 PIT 上限） |
| 验收标准 | 域内偏度 net 超额 > 0 且 net IR ≥ 0.5，**且 > 同窗口全市场偏度** → `domain_revived`（偏度域内救活，成日频策略候选信号）；若仅 > 域内 composite 贡献有限 → `domain_contrib_only`；否则 `dead` |

**对比基准（关键）**：域过滤本身（基本面 alpha，主线 IR 1.3+）会贡献大部分
收益——必须用"域内 composite"对照隔离"域功劳"与"偏度增量"。

## 2. 假设与信号（冻结）

- 假设：偏度因子失效的根因是**选股池污染**（信号集中在小市值高波动题材股，
  全市场 top50 集中持有后吃均值回归）；基本面域过滤掉亏损/高估/炒作股后，
  域内正偏度 = "基本面健康 + 偶发利好日"，含义从"彩票炒作"转为"有支撑的上行
  信号"，可交易。
- 信号：
  - `SKEW_MVI` = SKEW60 的 MVI 残差（log circ_mv + std20 + 申万 L1，**全市场
    截面计算，与 v1/v2 完全一致**，域内仅作选股池变量——保持单变量可归因）；
  - `COMP_NEUTRAL` = 主线四因子 composite（≥3 因子门槛）→ 行业+log_size OLS
    残差（月频更新，调仓日固定）；
  - 域 = 每月调仓日 `COMP_NEUTRAL` 截面前 50%（月内固定，月频更新）。
- 三版本：
  - **domain_skew（主候选）**：域内按 `SKEW_MVI` 排序，日频 top50；
  - **domain_comp（对照1：域功劳）**：域内按 `COMP_NEUTRAL` 排序，日频 top50
    （分数月内不变，等价月频持仓的日频化）；
  - **skew_full（对照2：全市场偏度，同窗口复现）**：全市场按 `SKEW_MVI` 排序，
    日频 top50。

## 3. 口径（冻结）

| 项 | 冻结值 |
|---|---|
| 主池 | 沪深普通 A 股母池（all.txt 历史在市，剔除 BJ/指数/B 股） |
| 数据 | `cn_data_2026`（后复权）+ `daily_basic_pit_v1`（换手率/市值）+ `style_pit_v1`（行业）+ `a_share_financial_pit_v1`（基本面域，PIT） |
| 过滤 | ST/*ST/退市（PIT）+ 停牌 + 涨停信号日 |
| 回测窗口 | **2022-01-01 ~ 2025-06-30**（财务 PIT 上限 2025-06-28；2025-06 后待财务更新，如实标注） |
| 域更新 | 月度调仓日（`monthly_rebalance_grid`，42 个月），域月内固定 |
| 策略 | TopkDropout topk=50 n_drop=5 日频，T+1 开盘成交，`limit_threshold=0.095`，`min_cost=5` |
| 基准 | SH000852 |
| 费率 | base: open 0.0005 / close 0.0015（主）；stress: open 0.0010 / close 0.0030（附录） |

## 4. 检验与报告

- 三版本 × base（+附录 stress）全期 net/gross 超额、IR、最大回撤、日均换手、
  年化成本拖累、2024 年（偏度失效年）net 超额、分年度 net。
- **关键对照**：
  - domain_skew vs skew_full（同窗口）：域过滤是否救活偏度；
  - domain_skew vs domain_comp：偏度在域内是否贡献增量（还是纯域功劳）。
- 域规模统计：域内股票数、偏度因子在域内的覆盖率。

## 5. 预设判定

| 条件 | 判定 |
|---|---|
| domain_skew net 超额 > 0 且 net IR ≥ 0.5，且 net 超额 > skew_full（同窗口） | `domain_revived` → 偏度域内救活，候选日频信号，可进组合版 |
| domain_skew net 超额 > 0 且 IR ≥ 0.5，但不显著优于 skew_full | `domain_contrib_only` → 主要靠域功劳，偏度增量不足，偏度因子收口（域/组合价值另评） |
| 其余 | `dead` → 偏度因子正式收口 |

2024 年表现与 stress 如实报告，不改变判定路径。

## 6. 产物与目录

```text
output/analysis_static/a_share_pv_domain_skew_strategy_v1/
  backtest_summary.csv       版本×费率 全期指标
  yearly_summary_*.csv       各版本分年度 net 超额（base）
  domain_stats.csv           域规模/覆盖率统计
  decision.json              预设判定
  methodology.json           口径快照
  validation_report.txt      中文报告
```

脚本：`scripts/backtest_a_share_pv_domain_skew_strategy_v1.py`
（复用 `neut` 数据/中性化 + `mq` 基本面域 + qlib 回测框架）。

## 7. 结论边界

本验证只回答"偏度是否在基本面域内救活"。`domain_revived` 仅确认偏度可作为
日频策略候选信号；完整日频策略（多信号合成/组合版）另行立项。2025-06 后受
财务 PIT 上限限制，如实标注。

## 8. 变更记录

| 日期 | 变更 |
|---|---|
| 2026-08-13 | 创建：冻结域内偏度三版本对照（域内偏度/域内composite/全市场偏度）；域=composite中性化前50%月频更新 |
