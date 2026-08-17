# 沪深非金融 A 股价值/质量多因子月度策略 margin 过滤层对照协议 v5

## 1. 状态、问题与授权边界

状态：`design_frozen_before_backtest`

承接 v3（ST 过滤后 alpha 真实，封存期 +9.8%）与 margin 正交性检验
（`margin_signal_orthogonality_protocol_v1.md`：`rzye_zscore` 发布滞后对齐
正确、与换手率/量比/动量/波动率截面相关最大仅 0.235，正交成立）。本协议
回答：

```text
在 v3 管线（中性化 + ST 过滤 + 容量过滤）基础上叠加"融资余额历史高位
（z>2）剔除"过滤层，是否提升策略的稳健性（封存期与全期超额、回撤）？
```

本协议只授权一次对照回测（v3 基线 vs v5 加 margin 过滤），不授权调优
z 阈值、topk、加权或因子定义。

## 2. margin 过滤层（冻结）

| 项 | 固定值 |
|---|---|
| 数据 | `data/external/tushare/margin_pit_v1/raw/*.csv.gz`（2016-2026，`rzye`） |
| 信号 | 每只股票 `rzye` 的 250 日滚动 z-score（至少 60 个有效值），在调仓日 `asof_date` 取值 |
| 对齐 | `rzye` 为 T 日盘后值，`asof_date` = 调仓日前一交易日，天然满足 T-1 可见性 |
| 剔除规则 | `z > 2` 的股票当月剔除（composite 置 NaN） |
| 敏感性 | 顺带报告 `z > 1.5` 一档，仅作敏感性展示，不参与判定 |

## 3. 唯一对比

| 版本 | 管线 | 角色 |
|---|---|---|
| v3 | 中性化 + ST/退市过滤 + 容量过滤 | 基线（已有结果） |
| **v5** | v3 + margin z>2 剔除 | **本协议唯一检验** |

回测设置与 v3 完全一致（topk=50、月度换手、t+1 开盘价、涨跌停 9.5%、
min_cost 5、基准 SH000852、区间 2014-01-01 至 2025-06-30、压力成本与
基准成本两套）。

## 4. 报告指标

- v5 全期 + 开发/确认/封存三阶段 + 分自然年，费前/费后（两套成本）年化
  超额、IR、最大超额回撤、日均换手率；
- **v5 与 v3 逐项对比**（重点：封存期超额与全期回撤是否改善）；
- 每月 margin 剔除的股票数量与占比（`margin_filter_summary.csv`）。

## 5. 预设判定

- 若 v5 封存期压力成本后年化超额 > 0 且 IR ≥ v3（或回撤明显改善）→
  margin 过滤层有效，进入阶段 2 信号管道；
- 若 v5 与 v3 无显著差异或更差 → margin 过滤层对当前策略无增量，
  如实记录，不调优。

## 6. 产物与目录

```text
output/analysis_fundamental/a_share_value_quality_monthly_strategy_v5_margin_filtered/
  monthly_margin_filtered_signal.csv.gz
  margin_filter_summary.csv
  backtest_summary.csv
  yearly_summary.csv
  decision.json
  methodology.json
  strategy_report.txt
```

## 7. 结论边界

margin 剔除为 T-1 可见的保守对齐；z 阈值 2.0 为预先冻结。滑点仍为参数化
假设；结果用于判断过滤层的增量价值，不构成实盘保证。
