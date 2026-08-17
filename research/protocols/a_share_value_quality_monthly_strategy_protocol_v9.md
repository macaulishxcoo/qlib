# 价值/质量多因子月度策略 同轴 HML 风控协议 v9

## 1. 状态、问题与授权边界

状态：`design_frozen_before_backtest`

v7 HML 风控失败，根因是"风格代理（单 BM）与策略实际暴露（四因子复合）不同轴"。
本协议回答：

```text
把 HML 信号的组合形成变量从单 BM 改为策略自身的四因子中性化残差
（neutral_composite），使风格信号与策略暴露同轴，能否改善 2026 等逆风年
的表现，同时保留封存期收益？

通过后，管道接入该风控层；不通过则风格择时路线彻底关闭，不再追加实验。
```

本协议只授权一次对照回测（v8 满仓基线 vs v9 同轴 HML 降仓），不授权调优
HML 窗口/分位/降仓档位/阈值。

## 2. 与 v7 的唯一差异（冻结）

| 项 | v7 | v9 |
|---|---|---|
| HML 组合形成变量 | `bm`（单因子） | **`neutral_composite`**（四因子中性化残差） |
| 基线（满仓） | v6 top-50 | **v8 top-15** |
| RISK_CUT_KEEP | 15（30% of 50） | **5**（30% of 15） |

其余与 v7 完全一致：

| 项 | 固定值 |
|---|---|
| HML 分位 | top/bottom 15% by neutral_composite |
| HML(t) | 价值组合（top 15%）未来 20 交易日等权收益 − 成长组合（bottom 15%）等权收益 |
| 风格状态 S(t) | HML 过去 6 个月（含当月）均值 |
| 降仓规则 | S(t) < 0 -> 降仓至 5 只（30% of 15），其余现金；否则满仓 15 只 |
| HML_HORIZON | 20 交易日 |
| HML_WINDOW | 6 个月 |

**同轴的具体含义**：HML 信号直接度量"策略选股信号偏好的股票"（neutral_composite
top 15%）vs"策略回避的股票"（bottom 15%）的收益差。这与策略实际持有的 top-15
在同一根轴上。

**为什么用 neutral_composite 而非 raw composite**：`neutral_composite` 是中性化
后的残差，策略实际选股用的就是它（top-15 by neutral_composite）。用它形成 HML
= 度量策略选股信号的相对表现，是最严格的同轴定义。

## 3. 唯一对比

| 版本 | 风控 | 角色 |
|---|---|---|
| v8 | 无（满仓 top-15） | 基线（已有结果） |
| **v9** | 同轴 HML<0 降仓至 5 只 | **本协议唯一检验** |

股票池、因子、中性化、ST/容量过滤、成本、执行与 v8 完全一致，仅叠加第 2 节
的风控规则。回测使用 v7 的费前等权 close-to-close 近似（方向性风控检验，
非完整成本回测）。

## 4. 时间切分与回测设置

与 v8 一致：2016-01 至 2026-06，日频月末网格；SH000852 基准；报告全期 + 分阶段
+ 分年。

## 5. 预设判定（冻结）

- 若 v9 在 **2026H1 超额明显优于 v8**（年化超额改善 > 5 个百分点，或 IR 转正），
  且 **2023-2025 封存期超额/IR 未明显恶化**（IR 降幅 < 0.3）->
  `coaxial_hml_effective`，管道接入；
- 否则 -> `coaxial_hml_not_effective`，**风格择时路线彻底关闭，不再追加实验**。

## 6. 产物与目录

```text
output/analysis_fundamental/a_share_value_quality_monthly_strategy_v9_coaxial_hml/
  hml_signal_series.csv        (同轴 HML 月度信号 + S 值)
  backtest_summary.csv
  yearly_summary.csv
  decision.json
  methodology.json
  strategy_report.txt
```

## 7. 结论边界

即使同轴了，v7 失败的第二个原因（6 月均值 + 20 日已实现收益 = 信号滞后）仍在。
这个实验的价值是**干净地关闭风格择时这条路**（同轴了还不行 -> 这条路到此为止），
而不是"找到救星"。真正的风控兜底是部署协议中的小仓位设计（20% 资金分配）。

## 8. 不做的事

- 不调优 HML 窗口（6 月）、分位（15%）、降仓档位（30%）、阈值（S<0）
- 不尝试其他风格代理（如 EP、DP 等单因子）
- 不尝试预测性（而非已实现）的风格信号
- v9 是风格择时路线的**最后一次实验**
