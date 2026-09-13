# 沪深普通 A 股日频估值轮动 + 质量/拥挤过滤检验协议 v1（S1）

状态：`executed_signal_weak`（2026-08-12 执行；结果见
`output/analysis_static/a_share_daily_valuation_s1/`）

## 1. 状态、问题与授权边界

背景：价值质量月频策略已完成但月频换手不符个人资金/频率要求；纯价量日频因子
已被证据证伪（Alpha158 衰减、横截面形态死、趋势状态为系统性暴露）。本协议检验
"日频信号 + 低频/事件触发执行"架构的信号层，回答：

```text
日频估值轮动（EP/PB/股息率）作为日频选股信号是否有效：
其 alpha 是否独立于价格反转（不是反转换皮）？
叠加 PIT 质量过滤与两融拥挤风控后是否提升？
```

**定位**：S1 只检验**信号层**是否存在 alpha（RankIC/分层/正交性），**不做组合回测**。
组合回测（top10-20 集中持仓、事件触发调仓）留待 S2/S3。S3（事件驱动/公告漂移）
触碰基本面冻结边界，走完整解冻评估，不在本协议范围。

**授权边界**：只检验本协议冻结的信号、过滤与四项检验；不授权搜索 pe_ttm/pb 的
更优变换、不因结果调整过滤阈值、不做完整组合回测。

## 2. 信号构造（冻结）

全部按日计算，`t` 日信号已知 → `t+1` 开盘成交口径检验。

### 2.1 日频估值信号（daily_basic，市场口径，每日变动）

| 信号 | 定义 | 数据 |
|---|---|---|
| `EP_ttm` | 1 / pe_ttm（pe_ttm>0 有效，否则 NaN） | `a_share_daily_basic_pit_v1` |
| `PB_inv` | 1 / pb（pb>0 有效，否则 NaN） | 同上 |
| `DV_ttm` | dv_ttm（股息率，越高越好） | 同上 |

### 2.2 PIT 质量慢变量（财务口径，按 available_date 广播到日频）

复用价值质量线已验证因子与公式（`analyze_a_share_value_quality_level_factors_extension_v1.py`）：

| 因子 | 公式 | 说明 |
|---|---|---|
| `ep` | profit_dedt TTM / total_mv（元） | 分母用 daily_basic 日频 total_mv（万元×1e4），替代原月频网格 |
| `bm` | bps × total_share(×1e4) / total_mv | 同上 |
| `accruals` | -(NI_ttm − CFO_ttm) / total_assets | |

对每个交易日 `t`：取每只股票 `available_date <= t` 的最新一期（end_date, available_date
去重保末），TTM 按 `ttm_value` 公式；日频市值取 daily_basic 当日。质量分 = 三者
百分位秩均值（ep/bm/accruals 均"越高越好"）。

### 2.3 两融拥挤信号（margin，日频）

| 信号 | 定义 |
|---|---|
| `rzye_zscore` | rzye 250 日时序 z-score（min 120 期），已验证 IC -0.043 / ICIR -5.86 |

## 3. 股票池与可交易过滤（冻结）

| 项 | 冻结值 |
|---|---|
| 研究母池 | 沪深普通 A 股（all.txt 剔北交所，同趋势持续性协议，约 5542 只，含退市） |
| 数据 | `~/.qlib/qlib_data/cn_data_2026`（后复权）+ 三个外部数据源 |
| ST/*ST/退市整理 | `a_share_st_status_pit_v1` PIT 区间逐日 asof 剔除 |
| 停牌/涨停 | 无有效价量剔除；`$change >= 阈值`（主板 0.095/创业板科创 0.195）剔除 |
| 检验窗口 | 2022-01-01 ~ 2026-07-31（与趋势持续性、主升浪复验一致，可对比） |
| 数据预热 | 2020-01-01 起（覆盖 250 日 z-score 与 TTM 需回溯） |

## 4. 标签与执行口径（冻结）

- 未来收益：T+1 开盘成交 `Ref($open,-1)/(Ref($close,-(h+1))-1)`，h = 5/10/20；
  主检验 h=5（与既有复验一致）。
- 日频估值信号 `EP_ttm`/`PB_inv`/`DV_ttm` 在 `t` 日收盘后已知（daily_basic 为当日快照）。

## 5. 检验设计与报告

四项检验，全部按日截面执行、分年度（2022-2026）报告：

- **T1 单信号 RankIC**：`EP_ttm`、`PB_inv`、`DV_ttm` 各自的日频 RankIC 均值/ICIR/
  IC>0 占比/五分位价差。
- **T2 正交性（核心，反转换皮检验）**：控制当日 20 日价格反转秩后，`EP_ttm` 的
  残差 RankIC 与增量。判定：衰减 < 30% = 真估值信号；30-50% = 部分；> 50% =
  `reversal_artifact`（判死）。
- **T3 质量过滤增量**：全样本 vs 剔除质量分后 20% 后的 `EP_ttm`/组合 IC 对比。
- **T4 两融拥挤剔除增量**：全样本 vs 剔除 rzye_zscore > 2（敏感性附 z > 1.5）后的
  IC/ICIR 对比。
- **T5 组合信号**：`EP_ttm + PB_inv + DV_ttm` 等权百分位秩均值（组合 0），
  组合 1 = 组合 0 + 质量过滤，组合 2 = 组合 1 + 两融剔除；报告三者 IC/ICIR/分年度。

报告同时输出：样本量、过滤保留率、市值分层（S1-S5 按 total_mv，报告
`EP_ttm` 各层 IC——检验信号是否只在特定市值段有效）、2025-07 后压力段单独报告
（价值质量线 v6 在该段为负）。

## 6. 预设判定

对齐 `metrics_judgment_standard.md`（ICIR 0.3~0.5 = 中、0.5~1.0 = 好）：

| 条件 | 判定 |
|---|---|
| T2 非反转换皮（衰减 < 50%）**且** 组合 2 ICIR ≥ 0.3 | `signal_viable` → 进入 S2（叠加两融风控回测） |
| T2 判定 `reversal_artifact` | `reversal_artifact` → 日频估值是价格反转换皮，收口并归档 |
| 组合 2 ICIR < 0.3 | `signal_weak` → 如实报告，不强行进入组合回测 |
| 任何路径：2025-07 后压力段如实报告，不因全期好看而忽略 | — |

## 7. 产物与目录

```text
output/analysis_static/a_share_daily_valuation_s1/
  t1_signal_ic.csv            T1 单信号 IC/ICIR/分年度/分层价差
  t2_orthogonality.csv        T2 控制反转后残差 IC
  t3_quality_filter.csv       T3 质量过滤增量
  t4_margin_filter.csv        T4 两融剔除增量
  t5_composite.csv            组合 0/1/2 IC/ICIR/分年度
  ts_size_layers.csv          市值分层 IC（S1-S5）
  daily_ic.csv.gz             组合 2 日频 IC 序列
  decision.json               预设判定结果
  methodology.json            口径快照
  validation_report.txt       中文报告
```

脚本：`scripts/analyze_a_share_daily_valuation_s1_v1.py`（复用趋势持续性/主升浪复验的
过滤与分层框架，质量 TTM 公式复用价值质量线冻结实现）。

## 8. 结论边界

本检验回答"日频估值信号层是否有独立于反转的 alpha"。它不改变主线（价值质量月频）的
任何决策；若 `signal_viable`，S2 将做 top10-20 集中持仓 + 事件触发调仓的组合回测
（需另行协议）。2025-07 后压力段结论如实归档。

## 9. 变更记录

| 日期 | 变更 |
|---|---|
| 2026-08-11 | 创建：冻结信号/过滤/检验/验收；状态 design_frozen_before_backtest；S3 事件驱动走完整解冻评估另行立项 |
