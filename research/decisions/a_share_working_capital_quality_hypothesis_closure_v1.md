# “营运资本质量”命题关闭复盘 v1

## 1. 决策

状态：`hypothesis_not_supported_closed`

“应收账款与存货相对收入的同比恶化越少，未来收益越高”这一**特定等权组合命题**不进入
LightGBM、策略回测或交易设计。2023-01 至 2025-06 的封存期价格未被读取；不得修改应收/
存货的权重、分母、同比定义、持有期、行业范围或市值层来重新测试本命题。

该决定不代表资产负债表、营运资本的所有单项、基本面信息或 Tushare PIT 数据整体失效；它只
关闭下列已经预先冻结的一个组合：

```text
working_capital_quality =
  - (receivable_deterioration + inventory_deterioration) / 2
```

## 2. 证据与失败位置

每月第一个交易日使用当时已经生效的财报事件和前一交易日的行业/自由流通市值，标签为同一
复权口径的开盘到开盘 20/40/60 日收益。每个完整样本中均移除了申万一级行业和对数自由流通
市值暴露。

| 阶段 | 月数 | 40 日中性化 Rank IC | ICIR | 正 IC 月占比 | 40 日中性化 Q5-Q1 | 结论 |
|---|---:|---:|---:|---:|---:|---|
| 开发期 2014--2019 | 72 | 0.0214 | 0.611 | 70.8% | +0.83% | 通过开发门槛 |
| 确认期 2020--2022 | 36 | 0.00225 | 0.050 | 52.8% | +0.26% | 未通过 |

确认期失败不是覆盖不足：36 个月均有效，每月完整样本约 3,300--3,600 家。失败原因是预设的
预测关系衰减：40 日中性化 IC 低于 `0.01`，60 日中性化 IC 为 -0.00084，且去除最小市值层
S1 后，40 日中性化 IC 为 -0.00357。

确认期五个规模层的 40 日中性化 Rank IC 为：

| S1 最小 | S2 | S3 | S4 | S5 最大 |
|---:|---:|---:|---:|---:|
| 0.0283 | 0.0034 | 0.0005 | -0.0044 | -0.0137 |

这表明剩余的开发期样式主要集中在最小市值层；它没有作为跨规模稳定的财务选股信息存活。
基于已冻结的规则，不把 S1 事后改成新的“有效股票池”。

## 3. 这次研究确认了什么

1. 资产负债表 PIT、收入 PIT、历史行业与自由流通市值可以以公告可得时点无未来函数地连通；
2. 155,725 条无标签事件及其月初快照支持全市场低频基本面研究；
3. 开发期有统计关联，说明研究并非因数据接入错误而失败；
4. 该等权组合在确认期失去跨规模稳定性，因此不应由模型训练或回测“挽救”；
5. 未读取封存期，避免封存结果被用于继续筛选公式。

## 4. 未确认、不能宣称的事项

1. 不能宣称所有资产负债表质量信号无效：本次没有独立测试单独应收、单独存货、应付、杠杆、
   现金持有或资本配置命题；
2. 不能宣称 S1、小盘、CSI1000 或任何指数是这条信号的可交易范围；
3. 不能宣称基本面信息整体无效，也不能从开发期表现推出未来收益；
4. 不能把 2023--2025 封存期用于寻找新的阈值、子市场或权重。

## 5. 可复现证据

- 研究协议：`research/protocols/a_share_working_capital_quality_single_factor_validation_protocol_v1.md`；
- 开发期判定：`output/analysis_fundamental/a_share_working_capital_quality_single_factor_v1/decision.json`；
- 开发期汇总：`output/analysis_fundamental/a_share_working_capital_quality_single_factor_v1/development_rank_ic_summary.csv`；
- 确认期汇总：`output/analysis_fundamental/a_share_working_capital_quality_single_factor_v1/confirmation_rank_ic_summary.csv`；
- 确认期规模层：`output/analysis_fundamental/a_share_working_capital_quality_single_factor_v1/confirmation_size_layer_summary.csv`。
