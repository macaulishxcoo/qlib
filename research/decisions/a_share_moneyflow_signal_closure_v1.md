# 个股资金流向（moneyflow）信号验证关闭记录 v1

## 1. 决策

状态：`moneyflow_not_supported_closed`

**修复 lookahead bias 后，moneyflow 信号 IC 过弱（ICIR 0.27 < 0.3 门槛），
不构成独立 alpha 来源。方向 B 首轮关闭。**

## 2. 实验设计（协议 v1）

- 数据：Tushare `moneyflow`，2022-01-04 ~ 2026-08-12，5733 只股票，560 万行
- 3 个信号：`net_mf_5d`（5 日净资金流入/市值）、`net_mf_20d`、`elg_net_5d`（超大单）
- 验证：RankIC（h=5/10/20）+ 与价值因子和动量的正交性 + 分组单调性

## 3. 关键发现：lookahead bias

### 修复前（有未来函数）

信号用交易日 T 的全天 moneyflow，入场用 T 日开盘价。moneyflow 是 T 日
开盘到收盘的累计资金流，在 T 日开盘时不可知。这导致 IC 被严重高估：

| 信号 (h=10) | IC（修复前） | ICIR（修复前） |
|---|---|---|
| net_mf_5d | 0.1032 | 0.935 |

IC=0.103 在 A 股截面信号中异常偏高（对比价值因子 IC 0.04-0.08），是 lookahead
的典型症状。

### 修复后（T-1 信号，无未来函数）

信号移位 1 天：用 T-1 日的 moneyflow，入场用 T 日开盘价。IC 暴跌 70%：

| 信号 (h=10) | IC（修复后） | ICIR（修复后） | IC>0 占比 |
|---|---|---|---|
| net_mf_5d | 0.0305 | 0.271 | 62.1% |
| net_mf_20d | 0.0304 | 0.257 | 65.0% |
| elg_net_5d | -0.0052 | -0.088 | 44.4% |

ICIR 0.271 < 0.3 门槛 -> `moneyflow_not_supported`。

## 4. 正交性结果

| 信号 | vs neutral_composite | vs momentum_20d |
|---|---|---|
| net_mf_5d | -0.018（正交 ✅） | 0.128（<0.3 ✅） |
| net_mf_20d | -0.016（正交 ✅） | 0.252（<0.3 ✅ 但偏高） |

资金流向与价值因子和动量都正交，**数据源本身是独立的**。但独立不等于有效 --
信号太弱，ICIR 不达标。

## 5. 经验教训

1. **lookahead bias 是信号验证的头号陷阱**：修复前 IC=0.103 看起来是"发现
   了金矿"，修复后只有 0.030。任何用日内全量数据预测从开盘起的收益，都
   必须移位到 T-1。
2. **资金流向的日频截面预测力很弱**：A 股散户占比高，大单/超大单的净流入
   更多反映当日已发生的价格变动（与动量部分重叠），对次日收益的预测力弱。
3. **IC>0.05 且 ICIR>0.5 在 A 股日频截面是极高标准**：你的价值因子
   （IC 0.04-0.08）是月频信号，日频信号很难达到同样水平。

## 6. 结论

moneyflow 信号方向 B 首轮关闭。数据源与价值因子正交但信号太弱。

方向 B 的其他候选（stk_holdernumber 股东户数、stk_managers 高管增减持）
仍可作为后续低频事件驱动信号测试，但优先级降低。

## 7. 可复现证据

- 协议：`research/protocols/a_share_moneyflow_signal_protocol_v1.md`
- 脚本：`scripts/analyze_a_share_moneyflow_signal_v1.py`
- 数据：`data/external/tushare/moneyflow_pit_v1/`
- 产物：`output/analysis_static/a_share_moneyflow_signal_v1/`
