# 沪深 A 股行业与自由流通市值 PIT 最小数据规范 v1

## 1. 目的与状态

状态：`design_frozen_before_download`

本规范为 [盈利改善与现金流质量研究协议](../protocols/a_share_nonfinancial_earnings_cash_quality_research_protocol_v1.md)
补齐两项**控制变量**：信号日可得的申万一级行业与自由流通市值。它们不增加任何
预测信息，也不定义新的因子。

目的有两个：

1. 以历史行业分类排除金融业，并识别财务信号是否只是集中在少数行业；
2. 以历史自由流通市值剔除规模暴露，避免把“小市值股票在某段时间表现较好”误判为
   财务信息的选股能力。

预期结果是一份覆盖月度信号评估日期的、可审计的 PIT 控制数据集。只有该数据集通过
审计，才允许构建无收益标签的财务事件面板；本规范不授权计算信号、读取收益、IC、
训练、回测或交易。

## 2. 为什么不沿用已有 CSI1000 数据

项目中已有 CSI1000 的行业与 `daily_basic` 文件，但其证券范围仅为 CSI1000 成分股，
日期仅覆盖此前 Alpha158 实验的局部窗口。新研究的母池是沪深普通 A 股历史在市证券，
不能把一个指数成分池的覆盖情况外推到全市场，也不能因 CSI1000 曾相对较好而把它
再次默认为交易范围。

旧文件保留原处，不修改、不合并。新数据集必须独立保存。

## 3. 时间网格、母池与 PIT 时点

### 3.1 固定评估日期

首个财务命题使用月度调仓，因此只收集每月第一个交易日的前一交易日控制变量，而非
下载全市场每一个交易日数据。这样既满足中性化需要，又避免把个人研究资源耗在不会
参与首次月度检验的日度横截面上。

固定网格为：

```text
评估月：2014-01 至 2025-06（138 个月）
rebalance_date：每月第一个 Qlib CN 交易日
asof_date：rebalance_date 的前一个 Qlib CN 交易日
```

在 `asof_date` 收盘后获得的自由流通市值只可用于下一交易日 `rebalance_date` 的
研究组合；不能使用 `rebalance_date` 收盘后才知道的市值去解释或构造当日开盘交易。
这与财报信号“公告日后下一交易日才生效”的规则一致。

### 3.2 历史证券范围

证券范围严格使用 `a_share_financial_pit_v1` 第 1 批保存的 `stock_basic` 快照，再用
全量审计的 `frozen_universe_index.csv.gz` 确认其属于 5,385 家沪深普通 A 股。对任一
`asof_date`，只保留：

```text
list_date <= asof_date < delist_date
```

未退市证券的 `delist_date` 视为无上界。不得用当前成分股、当前上市状态或今天的
股票列表替代历史在市区间。

## 4. 数据来源与字段

### 4.1 申万一级行业历史

主源为 Tushare Pro `index_member_all` 的申万行业成员历史，读取 `is_new=Y` 与
`is_new=N` 的完整分页响应。保留的原始字段至少包括：

```text
ts_code, l1_code, l1_name, l2_code, l2_name, l3_code, l3_name,
in_date, out_date, is_new, name
```

对每个 `asof_date`，只采用满足 `in_date <= asof_date` 且 `out_date` 为空或
`out_date >= asof_date` 的申万一级记录。不能用 `in_date` 晚于该日的后续行业归属
回填历史。若多个记录同时有效或没有有效记录，标记 `industry_ambiguous` 或
`industry_missing`，不猜测、不用今日 `stock_basic.industry` 填补。

非金融样本的固定排除规则为有效申万一级代码 `801780.SI`（银行）与
`801790.SI`（非银金融）。若数据源在历史记录中使用不同的一级代码或名称，必须先
在**不读取收益**的字段审计中记录映射，再由协议修订决定，不能临时按回测结果改动。

### 4.2 自由流通市值

主源为 Tushare Pro `daily_basic(trade_date=YYYYMMDD)` 的全市场横截面响应。每个
`asof_date` 请求一次完整响应，再按当日历史在市的 5,385 家研究母池截取；不逐股票
请求，也不使用日后截面补值。

保留完整原始响应，并至少保留：

```text
ts_code, trade_date, close, free_share, float_share, circ_mv,
total_share, total_mv
```

首选控制变量定义为：

```text
free_float_market_value = close * free_share
size_control = log(free_float_market_value)
```

`daily_basic` 的股本单位随 Tushare 字段定义保留；对数回归不受固定单位倍率影响。
`free_share` 必须为正且 `close` 必须为正。若任一字段缺失、非正或无法解析，
`size_control` 缺失；不得用 `circ_mv`、总市值、后一天的值或横截面均值替代。
`circ_mv` 仅保留作字段合理性审计，因为“流通市值”和“自由流通市值”不是同一概念。

## 5. 标准化数据结构与文件布局

所有新增文件独立放在以下位置：

```text
data/external/tushare/a_share_style_pit_v1/
  raw/industry_member_all/{is_new_Y,is_new_N}.csv.gz
  raw/daily_basic/YYYYMMDD.csv.gz
  raw/stock_basic_snapshot_reference.json
  normalized/industry_l1_effective_intervals.csv.gz
  normalized/monthly_free_float_size.csv.gz
  manifests/manifest.json

output/data_audits/a_share_style_pit_v1/
  data_audit_report.txt
  request_log.csv
  industry_coverage_by_month.csv
  size_coverage_by_month.csv
  industry_overlap_or_gap.csv.gz
  size_field_quality.csv
  universe_join_coverage.csv
  anomaly_records.csv.gz
```

原始层只追加下载元数据（请求 UTC 时间、端点、参数、文件 SHA256），不得去重、改
字段、前向填充或重写历史响应。标准化层保留原字段，并新增 `asof_date`、
`rebalance_date`、`industry_status`、`size_status` 与来源文件名。

## 6. 预先冻结的中性化规则

后续首次财务信号检验，在每个 `rebalance_date` 的完整样本上采用同一横截面 OLS：

```text
signal = intercept
       + beta_size * log(free_float_market_value)
       + Shenwan level-1 industry dummy coefficients
       + residual_signal
```

其中行业为 `asof_date` 有效行业，市值为 `asof_date` 自由流通市值；一个行业虚拟变量
与截距共同省略以避免完全共线。原始信号和残差信号必须在**同一个完整样本**上计算
Rank IC 与分组结果，才可将差异解释为去除了行业/市值暴露，而不是样本变了。

单月完整样本少于 100 家时，该月中性化结果无效并单独报告。行业样本数不足 10 家
时仍进入整体哑变量回归，但不单列行业内 IC。此处的 100/10 是统计可行性下限，不是
根据收益优化的阈值。

## 7. 数据审计与阻断条件

下载完成后，只做数据审计。数据可标记 `style_data_ready` 必须同时满足：

1. 138 个 `asof_date` 全部有成功的 `daily_basic` 请求与原始文件哈希；
2. 每月历史在市母池、行业、自由流通市值三者的连接覆盖率均已报告；
3. 每月行业有效记录不存在无法解释的重叠；缺失和歧义记录均在异常表中保留；
4. 每月 `free_share > 0`、`close > 0` 的比例与 `free_float_market_value` 的数量级
   分布已报告；
5. 行业与市值字段不会由未来日期填充；
6. 原始、标准化、请求与字段/文件清单完整，且所有异常可追溯。

以下情况为 `style_data_blocked`：任一月缺少原始市值截面、行业历史无法提供有效日期、
主要历史在市样本的连接覆盖率未解释地骤降、自由流通市值单位或字段语义不明、或发现
使用未来分类/市值的路径。

## 8. 本规范后的唯一动作

若本规范获认可，下一步是实现并运行数据下载与审计器，且只下载本规范中的行业历史
和 138 个 `daily_basic` 月度截面。审计通过后停止，审查数据覆盖与异常，再单独定义
无标签财务事件面板的计算细节。
