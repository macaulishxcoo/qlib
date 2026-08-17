# 阶段 2 信号生产管道协议 v1：价值/质量月度策略落地

## 1. 目的与授权边界

状态：`design_frozen_before_implementation`

ROADMAP 阶段 2 要求把已验证策略落地为"收盘后自动产出明日选股名单 + 台账"。
本协议把 v4 策略（基本面四因子 → 中性化 → ST/退市过滤 → 容量过滤 → top50
月度换手）实现为**可对任意交易日 T 运行的信号管道**，回答：

```text
给定交易日 T，用 T 时点可得的数据（无未来函数），当日应持有哪 50 只股票，
并如何逐日记录 IC/持仓/组合台账？
```

本协议授权：
- 实现管道脚本（单日模式 + 历史重演模式）；
- 用历史重演验证管道输出与 v4 回测一致（一致性校验）；
- 产出三张台账。

不授权：修改 v4 策略规则、调优参数、新增信号源。

## 2. 数据边界（冻结）

| 数据 | 来源 | 用途 | 最新覆盖（2026-08-11 核查） |
|---|---|---|---|
| 行情 | `~/.qlib/qlib_data/cn_data_2026` | 标签、容量、复权 | 2026-08-07 |
| 财务 PIT | `a_share_financial_pit_v1` | 四因子分子 | 2025-06-28 |
| 月度市值 PIT | `a_share_style_pit_v1` | 因子分母、中性化、容量 | 2025-05-30 |
| ST 状态 | `a_share_st_status_pit_v1` | 风险过滤 | 2026 年（namechange 到最新） |

**已知缺口（如实标注）**：财务与月度市值数据未更新到当前，因此管道目前只能
对 `T <= 2025-06-30` 产出完整名单；对更晚的 T，脚本必须报"数据不足"而非
用旧数据伪造名单。财务/市值更新链路是阶段 2 的后续前置任务。

## 3. 管道输出（冻结）

对任意交易日 T，管道产出/追加：

| 台账 | 内容 | 更新频率 |
|---|---|---|
| `signal_ledger.csv` | 调仓日全市场四因子原始分数 + 中性化残差 + ST/容量过滤标记 | 每月调仓日 |
| `holding_ledger.csv` | 每日持仓：排名、代码、分数、权重、调仓日标记 | 每日 |
| `portfolio_ledger.csv` | 每日组合收益、基准收益、超额、换手、成本、账户值 | 每日 |

文件位置：`output/signal_ledger/`。

## 4. 单日名单生成逻辑（冻结，与 v4 完全一致）

对交易日 T：
1. 若 T 为调仓日（`monthly_rebalance_grid` 中的 `rebalance_date`）：
   - 用 `available_date <= T` 的财务 PIT 算四因子（TTM，复用
     `analyze_a_share_value_quality_level_factors_extension_v1.py`）；
   - 用 `asof_date`（= T 前一交易日）市值做分母 + 中性化 + 容量过滤；
   - ST/退市整理过滤（`namechange` 区间）；
   - 中性化残差取 top50 等权 → 生成持仓；
   - 记录 `signal_ledger` 与调仓日 `holding_ledger`。
2. 若 T 非调仓日：持仓沿用最近调仓日的 top50（月度换手），仅追加
   `holding_ledger`（持仓不变）与 `portfolio_ledger`（当日收益）。

过滤规则顺序与 v4 相同：ST/退市 → 容量（单票 200 万 / 20 日均额，参与率
上限 5%）→ 中性化残差选 top50。

## 5. 历史重演模式（验证一致性）

`--replay --from 2024-01-01 --to 2025-06-30`：按调仓日逐步重演，产出完整
台账；一致性校验：每个调仓日的 top50 与 v4 回测同期持仓**重合率 ≥ 95%**
（信号生成逻辑完全一致时应当如此）。不一致则判定管道 bug，禁止进入前瞻。

## 6. 产物与目录

```text
output/signal_ledger/
  signal_ledger.csv
  holding_ledger.csv
  portfolio_ledger.csv
  pipeline_meta.json        （每次运行追加运行记录）
scripts/run_daily_signal_pipeline_v1.py
research/protocols/signal_production_pipeline_protocol_v1.md（本文件）
```

## 7. 结论边界与后续

- 管道用 v4 冻结规则，不在此调参；
- 财务/市值数据更新链路（拉最新 PIT + 追加）为阶段 2 后续前置任务，未在本
  协议范围内；
- 台账运行一段时间后，才允许基于台账做前瞻期分析（阶段 5）。
