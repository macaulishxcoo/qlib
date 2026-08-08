# 沪深非金融 A 股财务事件面板无标签计算规范 v1

## 1. 目的、状态与禁止事项

状态：`design_frozen_before_label_access`

本规范把已审计的财务 PIT 原始记录转换为后续研究唯一允许使用的“财报事件面板”。
它解决的不是预测收益，而是三个数据解释问题：同一报告期的版本应何时生效、同比在
亏损/低基数时如何可比较、经营现金流如何表达“盈利质量”。

本规范只允许读取财务 PIT 数据与行业/市值控制数据的字段分布；**不允许**读取任何
未来收益、价格标签、IC、分组收益、模型结果或回测结果。生成事件面板后也必须停止，
由单独协议授权有效性检验。

## 2. 无标签审计依据

本规范在不读取收益的前提下检查了全量 `a_share_financial_pit_v1` 标准化数据：

- 利润表 301,927 行，现金流量表 298,480 行；
- `total_revenue` 非空 301,542 行，其中正值 301,390 行；
- `n_income` 同时有正值 254,946 行和负值 46,013 行；
- `n_cashflow_act` 同时有正值 191,653 行和负值 106,816 行；
- 同一“公司、报告期、报告类型、可得日”通常是金额相同的重复版本，但利润表仍有
  5 个收入金额冲突组、2 个净利润金额冲突组，现金流有 4 个经营现金流金额冲突组。

所以：亏损和负现金流是正常经济状态而非缺失；同日冲突不能靠任意排序“选一个”；
同比比例必须防止前年同期金额接近零时被无限放大。

## 3. 输入、时间与研究范围

### 3.1 输入与输出位置

唯一输入是：

```text
data/external/tushare/a_share_financial_pit_v1/full/normalized/batch_*/
data/external/tushare/a_share_style_pit_v1/normalized/
output/data_audits/a_share_financial_pit_v1/full/full_audit_v1/
```

未来输出必须独立写入：

```text
data/derived/a_share_earnings_cash_quality_event_v1/
output/data_audits/a_share_earnings_cash_quality_event_v1/
```

不得修改 `data/external/`，不得写入 `mlruns*`、Qlib 行情目录或旧 Alpha158 输出目录。

### 3.2 纳入记录

仅纳入满足以下条件的利润表与现金流量表记录：

1. `report_type = 1`；
2. `end_date` 月日为 `03-31`、`06-30`、`09-30` 或 `12-31`；
3. `available_date` 合法，且属于冻结财务 PIT 数据范围；
4. 该公司在 `available_date` 已上市且未退市；
5. 信号日有唯一有效的申万一级行业，且不是 `801780.SI`（银行）或
   `801790.SI`（非银金融）；
6. 本期和前年同报告期记录均满足本规范的版本与金额规则。

不因 ST、停牌、流动性或收益表现删除记录；这些是以后可交易性层的规则。

### 3.3 生效日

事件日是 `available_date`，生效日为其后第一个 Qlib CN 交易日。事件保留为离散
记录；本规范不把它扩展为每日持有信号，也不计算任何收益。

## 4. 版本去重与冲突处理

### 4.1 先按可得日，再按报告期

版本主键是：

```text
ts_code, end_date, report_type, available_date
```

对每张表、每个主键，比较核心金额：利润表比较 `total_revenue` 与 `n_income`；现金流
比较 `n_cashflow_act`。

- 核心金额都相等（包括都缺失）的重复行：保留其中 `update_flag=1` 优先、再按
  `source_file` 字典序最小的一行作为该日版本；其余行写入重复审计表；
- 核心金额存在任何冲突：该键写入 `same_day_value_conflict` 审计表，**整个事件不进入
  首轮面板**；不按 `update_flag`、文件顺序或今天看到的最终值猜测哪一行正确；
- 不同 `available_date` 的版本均保留为不同历史事件。后续某日使用哪一版本时，只有
  该日及之前已披露的版本可见；修订版本绝不回填首发版本的过去日期。

### 4.2 三表对齐

首轮只要求利润表和现金流量表按以下键精确对齐：

```text
ts_code, end_date, report_type, available_date
```

不同公告日的利润表和现金流记录不允许“最近邻配对”，以免把一张更晚修订的报表提前
用于另一张表的首发日。无法精确对齐即标记 `statement_alignment_missing` 并排除，数量
必须按年、报告期类型报告。

`fina_indicator` 仅保留为后续对账来源，不进入首个事件公式，也不用于填补三表缺失。

## 5. 同比与会计状态编码

### 5.1 前年同期配对

本期 `end_date` 为 YYYY-MM-DD 时，只匹配 YYYY-1 年相同月日；季度累计口径只与相同
累计口径同比，禁止环比或把一季报与年报混合。候选前年记录必须在本期事件日之前已经
可得；若出现异常的“前年同期更晚披露”，事件标记 `prior_not_available` 并排除。

### 5.2 金额尺度与同比值

令 `prior_abs = abs(prior_value)`。不同公司数量级差异很大，因此不以固定金额判断。
对利润和收入分别定义：

```text
denominator = max(prior_abs, 1% * median_positive_abs_same_period)
yoy_raw = (current_value - prior_value) / denominator
yoy_clipped = clip(yoy_raw, -5.0, 5.0)
```

其中 `median_positive_abs_same_period` 在每个“事件年 + 报告期月日”横截面只用财务
金额计算，并在本次面板构建时保存。`1%` 下限与 `[-5, 5]` 截尾是为处理低基数，按
无标签分布预先固定；以后不得因任何标签或回测结果调整。

`profit_yoy` 使用 `n_income`，`revenue_yoy` 使用 `total_revenue`。收入值若非正，或
任一参与同比的金额缺失，相关同比记缺失而不填零。

### 5.3 盈利状态

除连续 `profit_yoy` 外，保留以下固定分类，供覆盖与经济解释使用：

| 本期净利润 | 前年同期净利润 | `profit_state` |
|---|---|---|
| 正 | 正 | `profit_positive_to_positive` |
| 正 | 非正 | `profit_turnaround` |
| 非正 | 正 | `profit_deterioration` |
| 非正 | 非正 | `profit_loss_to_loss` |

四类均保留。首轮排名不将 `profit_turnaround` 自动视为最大改善，也不将亏损公司自动
剔除；它们与连续同比共同进入后续预先声明的描述性报告。

## 6. 现金流质量编码

现金流质量只使用同一已对齐版本的 `n_cashflow_act` 与 `n_income`：

```text
cash_support_flag = (n_cashflow_act > 0)
cash_profit_ratio = n_cashflow_act / max(abs(n_income), 1% * median_positive_abs_profit_same_period)
cash_profit_ratio_clipped = clip(cash_profit_ratio, -5.0, 5.0)
```

`cash_support_flag` 是首轮主质量条件；`cash_profit_ratio_clipped` 是辅助连续诊断，不
能在首次检验后被事后升级或替换为主条件。净利润为零时仍按固定分母下限计算比例，
不将其无声删除。现金流缺失则两项质量变量缺失。

## 7. 首轮主组合资格的无标签定义

本规范只定义资格，不计算它是否赚钱。每个 `rebalance_date`，在该日之前已生效、且未
被后一财报事件替代的公司事件中：

1. `profit_yoy_clipped`、`revenue_yoy_clipped`、`cash_support_flag` 均非缺失；
2. 仅在同一有效行业/市值完整样本内，分别计算盈利同比与收入同比的截面五分位；
3. `profit_yoy` 和 `revenue_yoy` 均位于最高两组（第 4 或第 5 五分位）；
4. `cash_support_flag = true`。

该交集命名为 `earnings_revenue_cash_quality_2of5`。它不使用任何收益、价格标签或
模型输出决定门槛。若某月有效完整样本少于 100 家，所有五分位资格记缺失，并在审计
中报告。

## 8. 必须输出的无标签审计

面板构建后必须输出以下文件，随后停止：

```text
event_panel.csv.gz
same_day_duplicate_audit.csv.gz
same_day_value_conflict.csv.gz
statement_alignment_audit.csv.gz
prior_year_pairing_audit.csv.gz
coverage_by_event_year_and_period.csv
variable_distribution_by_event_year_and_period.csv
qualification_coverage_by_rebalance_month.csv
methodology.json
event_panel_audit_report.txt
```

审计报告必须列出每年事件数、非金融覆盖数、三表对齐缺失、同日金额冲突、前年同期
缺失、各盈利状态、截尾前后分布，以及月度资格覆盖。任何冲突都必须保留在审计文件，
不得静默改值或删除其血缘。

## 9. 下一步授权边界

只有面板构建和上述无标签审计完成后，下一步才可以审查一份“单因子有效性检验协议”。
那份协议才会明确如何读取 20/40/60 日标签、计算行业/市值中性化 Rank IC 和分组单调
性。本规范不授权执行这些动作。
