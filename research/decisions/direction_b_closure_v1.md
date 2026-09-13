# 方向 B（第二个 alpha 来源）整体关闭记录 v1

## 1. 决策

状态：`direction_b_closed`

**方向 B 全部候选数据源测完，未找到独立的第二个 alpha 来源。方向 B 关闭。**

## 2. 实验汇总

| 数据源 | 频率 | 信号 | 最佳 IC | 最佳 ICIR | 正交性 | 判定 |
|---|---|---|---|---|---|---|
| moneyflow（个股资金流向） | 日频 | net_mf_5d | 0.030 | 0.271 | ✅ (0.063) | not_supported |
| holdernumber（股东户数） | 季度 | holder_change_neg | 0.041 | 0.265 | ✅ (0.039) | not_supported |
| stk_holdertrade（增减持） | 事件 | 已在事件流评估中证伪 | - | - | - | not_supported (动量暴露) |
| hsgt_top10（北向十大） | 日频 | 个股明细停更 | - | - | - | 不可用 |
| fund_portfolio（基金持仓） | - | 无 API 权限 | - | - | - | 不可用 |
| ana_review（分析师评级） | - | 无 API 权限 | - | - | - | 不可用 |

## 3. 关键发现

### 3a. moneyflow 的 lookahead 教训

首轮 IC=0.103（异常高），修复 T-1 移位后暴跌到 0.030。这验证了一个重要原则：
**任何用日内全量数据预测从当日开盘起的收益，都必须移位到 T-1**。

### 3b. 股东户数方向正确但太弱

IC=0.041（方向正确，筹码集中度逻辑成立），与价值因子正交（corr=0.039），
但 ICIR=0.265 不达标。季度频率 + 弱信号 = 即使进组合也贡献不了多少 alpha。

### 3c. 可用数据源已穷尽

Tushare 个人权限下，能提供截面选股 alpha 的数据源已全部测完：
- 基本面（价值/质量）：✅ 唯一有效（v1-v8 已验证）
- 价量（Alpha158）：✅ 2021 后衰减
- 事件流（龙虎榜/增减持/限售）：✅ 动量暴露
- PEAD：✅ 方向不符
- moneyflow：✅ IC 太弱
- holdernumber：✅ ICIR 不达标
- 分析师预期/基金持仓：❌ 无权限

## 4. 结论

**A 股截面选股 alpha 对个人可及的数据源已全部穷尽。** 唯一有效的仍然是
价值/质量四因子复合（月频）。方向 B 关闭。

后续研究方向转向：
- **方向 C（市场择时/仓位管理）**：不找选股 alpha，在市场层面择时。
  候选：北向资金整体净流入（日频可用）、市场宽度、市场波动率。
- **模拟盘继续运行**：验证 v8 策略在 live 条件下的表现。

## 5. 可复现证据

- moneyflow：`scripts/analyze_a_share_moneyflow_signal_v1.py` + `research/decisions/a_share_moneyflow_signal_closure_v1.md`
- holdernumber：`scripts/analyze_a_share_holdernumber_signal_v1.py` + `output/analysis_static/a_share_holdernumber_signal_v1/`
- 事件流（增减持）：`research/decisions/a_share_events_daily_stream_assessment_v1.md`
