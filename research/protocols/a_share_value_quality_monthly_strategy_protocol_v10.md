# 价值/质量多因子月度策略 逆波动率加权协议 v10

## 1. 状态与授权

状态：`design_frozen_before_backtest`

v1-v9 全程等权（`weight = 1.0 / len(top)`）。本协议测试**逆波动率加权**：
权重 ∝ 1/过去 60 日日收益率波动率。这是组合构造层的首次实验，唯一变量是
权重分配方式。因子选股、中性化、过滤、调仓频率、执行方式全部不变。

## 2. 研究问题

```text
把 top-15 的权重从等权改为逆波动率加权（低波动股权重大），
能否在保持超额收益的同时降低组合波动率和最大回撤？
```

## 3. 唯一变动（冻结）

| 项 | v8（等权基线） | v10（逆波动率） |
|---|---|---|
| 权重分配 | `1/15 = 6.67%` 每只 | `w_i ∝ 1/σ_i`，归一化到 sum=1 |
| 策略类 | `TopkDropoutStrategy` | `InverseVolWeightStrategy`（继承 `WeightStrategyBase`） |

### 波动率计算（冻结）

| 项 | 固定值 |
|---|---|
| 数据源 | qlib `$close`（后复权），与回测同源 |
| 窗口 | 调仓日前 60 个交易日 |
| 最小数据量 | 至少 40 个非 NaN 日收益率，否则 σ=NaN -> 权重 0（跳过） |
| 权重公式 | `w_i = (1/σ_i) / Σ(1/σ_j)`，对 top-15 中有效 σ 的股票归一化 |
| 时点 | 波动率在调仓日 T 计算完成，T+1 开盘执行（无未来函数） |

### 技术约束

`TopkDropoutStrategy` 强制等权（`signal_strategy.py:266`），无法做加权。
v10 使用 `WeightStrategyBase`（`signal_strategy.py:298`），重写
`generate_target_weight_position()` 返回 `{stock_id: weight}` 字典。
`backtest_daily()` 的成本模型、涨跌停、T+1 执行全部保留，与 v8 可比。

## 4. 与 v8 完全一致的部分

四因子（ep/bm/div_yield/accruals）≥3 因子门槛 -> 中性化（行业 OLS + log size）
-> ST/退市过滤 -> 容量过滤（参与率 5%）-> top-15 选股 -> 月度换手 -> T+1 开盘
执行 -> 涨跌停 9.5% -> 基准/压力两套成本 -> SH000852 基准。

## 5. 时间切分

与 v8 一致：

| 阶段 | 区间 |
|---|---|
| development | 2016-01 ~ 2019-12 |
| confirmation | 2020-01 ~ 2022-12 |
| holdout（封存期） | 2023-01 ~ 2025-06 |
| new_coverage（观察） | 2025-07 ~ 2026-06 |

## 6. 预设判定（冻结）

| 条件 | 判定 |
|---|---|
| 封存期压力费后超额 > 0 且 IR > 0 | `invvol_viable` |
| 且封存期 IR > v8 等权 IR（0.92） | `invvol_improved` |
| 且封存期 \|MDD\| < v8 等权 \|MDD\|（16.6%） | `invvol_lower_risk` |
| 三条件全满足 | 逆波动率加权有效，更新信号管道默认权重 |
| IR 改善但 MDD 没改善（或反过来） | 记录，需人工判断 |
| 两者都没改善 | `invvol_not_effective`，等权确认最优，关闭组合构造优化路线 |

**不授权调优**：不试 30/90/120 日窗口、不试信号倾斜/最小方差/混合加权。

## 7. 产物

```text
output/analysis_fundamental/a_share_value_quality_monthly_strategy_v10_invvol/
  backtest_summary.csv
  yearly_summary.csv
  decision.json
  methodology.json
  strategy_report.txt
  monthly_composite_invvol.csv.gz    (含 weight 列)
```

## 8. 结论边界

逆波动率加权是最低过拟合风险的加权方案（不依赖因子分值、不依赖协方差矩阵
估计）。如果有效，是"免费"的 IR/风险改善；如果无效，确认等权就是最优，
组合构造优化路线关闭。
