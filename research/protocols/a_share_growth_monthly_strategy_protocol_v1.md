# 成长复合策略月度 top-15 回测协议 v1

## 1. 状态与授权

状态：`frozen_awaiting_run`（2026-08-15）
前置：`research/decisions/a_share_growth_factor_family_closure_v1.md`
（g1/g2/g3 单因子三段全过；g1×g3 截面相关 0.848 高冗余）。
本协议冻结组合层实验参数，单一变量原则：与 v8 唯一差异是**选股信号
从价值四因子 composite 换成成长双因子复合**，其余全部照抄 v8。

## 2. 信号定义（冻结）

- 复合分：`growth_composite = rank_pct(g2_dedt_np_yoy) 与
  rank_pct(g3_q_rev_yoy) 的等权均值`，≥2 因子非缺失才有效
  （两因子都缺 -> NaN）
  - g1（or_yoy）与 g3 冗余 0.848，取更灵敏的单季口径 g3；
    g2 是盈利轴、g3 是营收轴，两者相关 0.442 中度，复合有意义
- 数据：fina_indicator PIT（available_date <= rebalance_date，
  同 (ts_code,end_date) 取最新）
- 窗口：2016-01 ~ 2026-06（v8 同窗口；dev 段有效月从 2016-02 起，
  与单因子轮一致）

## 3. 管道（与 v8 逐项一致）

1. growth_composite -> ST/退市整理过滤（composite 置 NaN）
2. 容量过滤：单票 notional(ACCOUNT/TOP_K) ÷ 20 日均成交额 ≤ 5%
3. 中性化：行业 L1 哑变量 + log(total_mv) OLS 残差 -> neutral_growth
4. top-15 等权，月度换仓
5. 执行：T+1 开盘、涨跌停 9.5% 剔除、base/stress 两档成本、min_cost 5
6. TOP_K=15、ACCOUNT=1e8、基准 SH000852（中证1000）

## 4. 预设判定（冻结，与 v8 同门槛）

- 封存期（2023-01~2025-06）stress 费后年化超额 > 0 且 IR > 0
  -> `growth_top15_viable`
- 附加对照（不设门槛只记录）：
  - 新覆盖段（2025-07~2026-06）vs v8 同段（预期互补：v8 -35%/yr，
    成长策略 2026 成长牛应有正超额）
  - 成长 vs v8 日收益相关（预期低/负相关 -> 双策略组合有分散价值）
  - 全期分年度超额 vs v8 分年度超额（风格互补性验证）
- 不授权调优：不试 TOP_K 其他值、不加过滤层、不试加权方式

## 5. 产物

`output/analysis_fundamental/a_share_growth_monthly_strategy_v1/`：
`backtest_summary.csv`、`yearly_summary.csv`、
`monthly_composite_top15.csv.gz`、`decision.json`、`methodology.json`

## 6. 判定出口

- 通过 -> 立项"双策略并行模拟盘"提案（成长腿 + 价值腿各自独立
  模拟，不合并净值；仓位分配另议）
- 不通过 -> 成长因子保留为"单因子层有效、组合层不可交易"结论，
  与量价偏度因子同性质归档
