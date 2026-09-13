# 价值/质量多因子月度策略 短期收益反转过滤协议 v11

## 1. 状态与授权

状态：`design_frozen_before_backtest`

模拟盘数据显示：6 月暴涨的股票 7 月回落，6 月暴跌的 7 月反弹。当前策略纯排序
选股，不考虑持仓股近期涨跌状态。本协议测试：在 top-15 选股后排除近期涨幅
极端的股票（用下一排名替补），能否改善回撤而不损害收益。

## 2. 唯一变动（冻结）

在 v8 的 `neutral_composite` 计算后、`nlargest(TOP_K)` 选股前，插入一步过滤：

1. 先取 `nlargest(TOP_K + SLACK, "neutral_composite")`（多取 5 只作为替补池）
2. 对这 20 只候选，查表获取过去 20 交易日收益率
3. 排除 `past_20d_ret > OVERBOUGHT_THRESHOLD` 的股票
4. 从剩余候选中取 top-15

| 参数 | 固定值 | 说明 |
|---|---|---|
| RET_WINDOW | 20 交易日 | 过去收益计算窗口 |
| SLACK | 5 | 替补池大小（top-15+5=20 候选） |
| OVERBOUGHT_THRESHOLD | +20% | 涨幅超过此值的候选被排除 |

**不排除暴跌股**：暴跌后反弹是正面现象（价值因子选的便宜股暴跌后仍有价值），
只过滤暴涨。

其余与 v8 完全一致：四因子、中性化、ST/容量过滤、等权 top-15、月度换手、
T+1 开盘执行、两套成本、SH000852 基准。

## 3. 实现方式

基于 v8 脚本，新增 `compute_short_term_return_lookup(snapshots, cal)` 函数
（复用 v10 的 `compute_vol_lookup` 模式），在 snapshot 循环中插入过滤逻辑。
信号构建和 TopkDropoutStrategy 完全不变 -- 被排除的股票 neutral_composite
设为 NaN，自然不进入 top-15。

## 4. 预设判定（冻结）

- 封存期超额 > 0 且 IR > 0 -> `rev_filter_viable`
- 且 IR > v8（0.92）-> `rev_filter_improved`
- 且 |MDD| < v8（16.6%）-> `rev_filter_lower_risk`
- 三条件全满足 -> 过滤有效
- 部分满足 -> 记录，人工判断
- 都没改善 -> `rev_filter_not_effective`，不过滤最优

**不授权调优**：不试其他窗口/阈值、不排除暴跌、不降权。

## 5. 产物

```
output/analysis_fundamental/a_share_value_quality_monthly_strategy_v11_revfilter/
  backtest_summary.csv / yearly_summary.csv / decision.json
  methodology.json / strategy_report.txt / monthly_composite_revfilter.csv.gz
```
