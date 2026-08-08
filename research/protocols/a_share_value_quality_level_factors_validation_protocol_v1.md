# 沪深非金融 A 股价值与盈利质量水平因子单因子验证协议 v1

## 1. 状态、问题与授权边界

状态：`design_frozen_before_first_label_read`

本协议承接选题评审 `a_share_value_quality_level_factors_proposal_v1.md`，
首次授权读取价格来回答一个可证伪的问题：

```text
月末已知的（a）扣非盈利收益率 E/P、（b）经营现金流对净利润的覆盖 CFO/NI，
是否能预测其后 20、40、60 个交易日的横截面收益；并且这种关系在去除申万
一级行业与自由流通市值暴露后仍存在？
```

它只授权**单因子信息含量检验**，不授权模型训练、LightGBM、因子搜索、组合
回测、交易成本估计、实盘选股或交易。若检验不通过，结论是该预先定义的
水平因子命题不受支持，不是继续改阈值、换指数或追加公式。

本协议是一轮最小实验，与已关闭的"盈利/收入同比改善"命题在信息维度上
正交（水平 vs 变化）。

## 2. 固定输入与研究日期

### 2.1 输入

| 输入 | 作用 | 不可改动范围 |
|---|---|---|
| `a_share_financial_pit_v1/full/normalized/*/fina_indicator.csv.gz` | 扣非净利润 `profit_dedt`、ROE `roe`、资产负债率 `debt_to_assets`（PIT 多版本，按 `available_date`） | 40 万条已审计记录 |
| `*/cashflow.csv.gz` | 经营现金流净额 `n_cashflow_act` | 同上 |
| `*/income.csv.gz` | 归母净利润 `n_income` | 同上 |
| `monthly_rebalance_grid.csv.gz` | 月末调仓日与前一交易日控制日期 | `a_share_style_pit_v1`，2014-01 至 2025-06 |
| `monthly_free_float_size.csv.gz` | 总市值 `total_mv`、自由流通市值、规模层 | 2013-12 至 2025-05 |
| 行业有效区间 | 申万一级行业、非金融筛选 | `a_share_style_pit_v1` |
| Qlib `cn_data_2026` 日历与 `open` | 后续价格标签 | 只读取本协议所需交易日与普通 A 股代码 |

当前研究母池仍是沪深普通 A 股历史在市证券，排除银行和非银金融（与既有
事件面板一致）；不把 CSI300/500/1000 或任何事后表现较好的指数当成默认池。

### 2.2 时间切分

按月末 `rebalance_date` 切分，不允许让 60 日收益窗口所属年份重新划分样本：

| 阶段 | 月末信号日期 | 用途 |
|---|---|---|
| 开发期 | 2014-01 至 2019-12 | 运行一次完整诊断；不改公式 |
| 确认期 | 2020-01 至 2022-12 | 判断命题是否跨阶段存活 |
| 封存测试期 | 2023-01 至 2025-05 | 在确认结论固定后运行一次最终复现 |

2025-05 月末信号若没有完整 60 个后续交易日开盘价，必须只从该期限标签中
排除并报告，不得缩短持有期或用后续日期替代。

## 3. 月末信号快照与 TTM 构建

在每个 `rebalance_date = t`：

1. 只使用 `available_date <= t` 的财务记录（PIT）；
2. 同一 `(ts_code, end_date)` 存在多个版本时，取 `available_date` 最新者；
   并列时取 `ann_date` 最新者；
3. TTM 化（扣非净利润、经营现金流、归母净利润均为累计值）：
   ```text
   TTM(最新报告期) = 最新报告期累计值
                   - 去年同期报告期累计值
                   + 去年全年报告期累计值
   ```
   其中"去年同期报告期"与"去年全年报告期"也取 `available_date <= t`
   可得版本；无法找到任一构成项时，该月该变量缺失；
4. 使用 `asof_date`（= rebalance 前一交易日）的总市值、自由流通市值与行业；
5. 行业缺失/歧义、市值缺失或非正、变量缺失的股票从该变量的当月完整样本
   排除；原始和中性化结果使用**完全相同的完整样本**；
6. 单月完整样本少于 100 家时，该月该变量的所有结果为无效并单独报告。

这一步是将低频财报水平因子转换为月末可交易前就能确定的横截面快照，不能
在同一个月内根据随后公告、股价或标签再调整。

## 4. 唯一允许检验的变量

不增加 Alpha158、业绩预告或其他财务字段；也不在结果出来后把辅助变量升级
为主信号。

| 名称 | 值 | 方向 | 角色 |
|---|---|---|---|
| `ep` | 扣非净利润 TTM / 总市值 | 越高越好 | **主命题 M1** |
| `cfo_ni` | 经营现金流净额 TTM / 归母净利润 TTM | 越高越好 | **主命题 M2** |
| `lev` | 资产负债率 `debt_to_assets` | 越高越差（负向） | 诊断组件，不充当主命题 |

主信号的五分位仅在该月同一完整样本内按 `rank(method="first")` 后等频划分；
样本少于 100 家时为缺失。诊断组件只用于解释主命题的经济来源，不从中选择
"表现最好"的项替代主命题。

## 5. 前瞻标签与 PIT 执行时点

使用 Qlib 同一复权口径的 `open` 价格与交易日历。月末信号在 `t` 开盘前
已经由此前披露的财务数据和 `asof_date` 控制变量确定，固定标签为：

```text
r_H(t) = open(t + H) / open(t) - 1,  H ∈ {20, 40, 60}
```

`t + H` 是日历中 `t` 后第 H 个交易日。若 `open(t)`、`open(t+H)` 缺失、非正
或不在该股票的历史在市区间，标签缺失；不得用收盘价、下一天价格、复权外部
价格或横截面均值补值。

这不是最终成交模拟：停牌、涨跌停、ST、冲击成本和容量只在之后的策略层处理。

## 6. 原始与中性化检验

### 6.1 原始结果

每月、每个变量、每个 H，在完整样本上计算 Spearman Rank IC。报告月度序列、
均值、标准差、ICIR、正 IC 月份占比，以及按日历年/阶段的汇总。

### 6.2 中性化结果

对每月同一个完整样本，对每个变量做横截面 OLS：

```text
variable = intercept
         + beta_size * log(自由流通市值)
         + Shenwan level-1 industry dummy coefficients
         + residual_variable
```

一个行业虚拟变量与截距共同省略。对 `residual_variable` 与**同一批股票、
同一标签**再计算 Rank IC 和分组结果。不得将"原始 IC 与残差 IC 的差"拆成
单独的行业贡献或市值贡献。

## 7. 分组、分层与统计报告

1. 连续变量：每月五分组，报告各组平均标签、`Q5-Q1`、五组单调性（相邻组
   不降比例）；
2. 规模层：以当月完整样本 `size_control` 等频五分位 `S1`–`S5`，重复主命题
   的原始和中性化 40 日 Rank IC；
3. 行业内：对当月样本数至少 10 家的一级行业，报告主命题 40 日原始 Rank IC
   的分布，不以最好的行业作为主结论；
4. 20/40/60 日都必须报告。40 日是主期限，不能因 20 或 60 日更好而改主结论。

所有均值使用"每月先计算统计量，再对月份等权平均"的口径。

## 8. 预设判定门槛

### 8.1 开发期

主命题成为 `development_candidate` 必须同时满足：

1. 40 日中性化平均 Rank IC 为正且至少 `0.01`；
2. 20、40、60 日中性化平均 Rank IC 均为正；
3. 40 日中性化 `Q5-Q1` 不为负；
4. 40 日中性化 ICIR 不低于 `0.20`。

若不满足，记 `hypothesis_not_supported_in_development`，停止该主命题，不
进入确认或封存期结果解读，且不修改变量规则。

### 8.2 确认期

若开发期通过，确认期成为 `confirmed_candidate` 必须同时满足：

1. 40 日中性化平均 Rank IC 为正且至少 `0.01`，方向与开发期相同；
2. 20、40、60 日方向均不反转；
3. 40 日中性化五组收益差不为负；
4. 至少 3 个预定义规模层的 40 日中性化 Rank IC 为正；
5. 不只由 `S1`（最小市值层）贡献：去除 S1 后，40 日中性化 Rank IC 仍为正。

若任一条件失败，主结论为 `hypothesis_not_supported`。

### 8.3 封存测试

只在 `confirmed_candidate` 时读取并报告。若封存期 40 日中性化 Rank IC 为正、
20/60 日不同时反向、且分组差不为负，标记 `replicated_for_strategy_design`；
否则为 `not_replicated`。无论哪种结果，都不能在封存期后改信号或重新运行
封存期。

## 9. 产物、目录和审计

首次运行只能写入：

```text
output/analysis_fundamental/a_share_value_quality_level_factors_v1/
  monthly_signal_label_panel.csv.gz
  monthly_rank_ic.csv.gz
  rank_ic_summary.csv
  group_return_summary.csv
  size_layer_summary.csv
  industry_distribution_summary.csv
  sample_coverage_summary.csv
  decision.json
  methodology.json
  validation_report.txt
```

`methodology.json` 必须记录 Qlib 数据目录、标签交易日映射、TTM 构建规则、
完整样本数、无效月数、所有时间切片与本协议 SHA256。`validation_report.txt`
必须先报告覆盖和无效月，再报告各阶段的原始/中性化结果和预设结论。

## 10. 本协议后的决策

- `hypothesis_not_supported*` 或 `not_replicated`：停止该财务命题，回到冻结
  状态；不训练 LightGBM 试图挽救它。
- `replicated_for_strategy_design`：下一步仅定义个人可执行的月度策略可交易
  池、停牌/ST/涨跌停、流动性与保守成本模型，再进行策略回测。

本协议不授权直接进入模型训练或自动因子挖掘。
