# 五因子 + 超买过滤 + T5 剔除双层叠加回测协议 v16

## 1. 状态与授权

状态：`frozen_awaiting_run`（2026-08-18）
前置链：
- `a_share_value_growth_five_factor_strategy_closure_v2.md`（五因子
  复合 regime_robust_improved，采纳为 v16 候选基线）
- v11 revfilter（单层 adopted）、v12 T5（单层 adopted）、v14 vt+t5
  （四因子基线上双层 adopted）、v15 三层（四因子基线上拒绝，
  holdout 侵蚀 -1.18pp + MDD -33%）

**与 v15 的关系**：v15 在**四因子基线**上测三层（vt+t5+revf）被拒。
本协议在**五因子基线**上测两层（t5+revf，不含 vt）--基线换了、
少一层 vt，是不同的实验。两层 revfilter+t5 在四因子基线上**从未
独立测过**（v14 是 vt+t5、v15 是三层），属于未测组合。

**不违反 v15 收口**：v15 §4 "不再叠加新层"针对的是四因子基线的
过滤层组合；五因子是新基线，g2 改变了候选池结构，有独立验证
必要。

## 2. 基线与对照（冻结）

- **基线**：五因子 v2（ep+bm+div+accruals+g2，≥4/5 门槛），即
  `a_share_value_growth_five_factor_strategy_v2` 结果
- **对照臂**（单变量）：
  1. baseline = 五因子无过滤（= v2）
  2. t5 = 五因子 + T5 剔除（mask composite）
  3. **t5+revf = 五因子 + T5 + 超买过滤**（本协议主臂）
- TOP_K=15、ACCOUNT=1e8、SH000852、T+1 开盘、涨跌停 9.5%、
  base/stress 成本，全部照抄 v8/v2

## 3. 两层过滤的层序（冻结，与 v15 一致）

1. composite5（五因子 ≥4 门槛）
2. ST/退市过滤（mask composite5）
3. 容量过滤 5% 参与率（mask composite5）
4. **T5 剔除**：调仓日前 20 交易日有跌幅上榜事件 -> mask composite5
   （在 neutral_composite 之前，因为 T5 是外部静态集合）
5. 行业+log_size OLS 中性化 -> neutral_composite5
6. **超买过滤**：top-(K+SLACK=20) 候选中，过去 20 日收益 > +20%
   -> mask neutral_composite5（在中性化之后，因为要取候选排名）
7. 选 top-15 等权

T5 数据：`a_share_events_daily_v1/raw/*top_list.csv.gz`，
reason 含"跌幅|负向"，2022-01 起。
超买参数：SLACK=5、RET_WINDOW=20、OVERBOUGHT_THRESHOLD=0.20
（全部冻结自 v11，不调参）。

## 4. 预设判定（冻结，双门槛，与 v14/v15 同口径）

主判定（防 holdout 侵蚀）：
- holdout delta ≥ -0.5pp（t5+revf 的 holdout net ≥ baseline 的
  -0.5pp 容差内）且
- new_coverage delta ≥ +5pp（t5+revf 的 new_coverage net 比
  baseline 改善至少 5pp）
-> `dual_filter_adopted`

附加对照（不设门槛只记录）：
- t5+revf 的 holdout MDD vs baseline（v15 在四因子上 MDD 恶化
  -27.6%->-33.0%，五因子基线上观察是否重演）
- t5+revf vs t5 单层的 new_coverage 增量（revfilter 在 T5 之上的
  独立增量，v15 在四因子上是 +13.6pp）

出口：
- 双门槛都过 -> adopted 为最终实盘形态候选
- holdout 侵蚀超 -0.5pp -> `holdout_erosion_closed`（与 v15 同
  机制，记录但不采纳）
- new_coverage 增量 < +5pp -> `no_increment_closed`

## 5. 产物

`output/analysis_fundamental/a_share_value_growth_five_factor_strategy_v16_t5_revf/`

## 6. 风险预告（预注册的怀疑）

v15 的机制警示：revfilter 在已有过滤层之上会把候选挤向"低波动但
非最优"的替补，顺风期（holdout）代价集中。五因子基线的 g2 让
候选池在成长股方向更宽，可能缓解这个挤压；但如果 T5 先剔除了
部分高增速候选（成长股波动大、易上跌幅榜），revfilter 的替补池
质量可能比四因子基线更差。**这是本实验真正要测的**。
