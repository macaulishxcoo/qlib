# 沪深非金融 A 股营运资本质量无标签事件面板规范 v1

## 1. 目的、状态与禁止事项

状态：`design_frozen_before_label_access`

本规范将已审计的利润表与资产负债表 PIT 记录转换为后续研究唯一可用的营运资本质量事件
面板，并冻结一条可证伪的主命题：

```text
在正式财报披露后，应收账款和存货相对收入的同比恶化越严重，
非金融公司的后续 20--60 个交易日横截面收益预期越低。
```

它解决的核心问题是：资产负债表数据是期末余额、收入是累计期间金额，且两者有公告日和
修订版本。先固定合并方式、同比方式和异常处理，才能避免日后根据 IC 或回测结果更换比率、
分母、单项或组合。

本规范只允许读取财务 PIT、历史上市状态、行业/市值控制数据的字段与分布；**禁止**读取
任何价格、未来收益、标签、IC、分组收益、模型、回测或旧因子结果。面板和无标签审计生成
后必须停止，等待单独的有效性检验协议。

## 2. 输入、范围和输出

### 2.1 唯一输入

```text
data/external/tushare/a_share_financial_pit_v1/full/normalized/batch_*/income.csv.gz
data/external/tushare/a_share_financial_pit_v1/balancesheet_v1/normalized/batch_*/balancesheet.csv.gz
data/external/tushare/a_share_style_pit_v1/normalized/
data/external/tushare/a_share_financial_pit_v1/full/raw/batch_*/universe_slice.csv.gz
```

其中 `balancesheet_v1` 已完成 54 批全量审计：5,385 家证券、343,058 条标准化记录，与收入
表的精确键匹配率为 98.5%。这些数字只说明数据链可用，不表示本命题有效。

### 2.2 研究范围

仅纳入满足下列条件的记录：

1. 沪深普通 A 股，且在 `available_date` 已上市、未退市；
2. `report_type = 1`，`end_date` 是 `03-31`、`06-30`、`09-30` 或 `12-31`；
3. `available_date` 合法并属于冻结 PIT 时间范围；
4. 有唯一有效的历史申万一级行业，且非银行（`801780.SI`）和非银金融（`801790.SI`）；
5. 本期、前年同报告期均符合本规范的版本、精确对齐和金额规则。

不因 ST、停牌、成交额、价格表现或以后收益删除记录。这些是未来策略可交易性层的独立规则，
不能在信息含量研究中静默混入。

### 2.3 输出边界

未来产物只能写入：

```text
data/derived/a_share_working_capital_quality_event_v1/
output/data_audits/a_share_working_capital_quality_event_v1/
```

不得修改 `data/external/`，不得写入 Qlib 行情目录、`mlruns*` 或已有 Alpha158、财务命题
结果目录。

## 3. PIT 事件与版本处理

### 3.1 时间规则

每个有效的“公司、报告期、报告类型、可得日”是一个财报事件：

```text
event_date = available_date
effective_date = event_date 后第一个 Qlib CN 交易日
```

事件是离散 PIT 记录；后续月初快照仅可使用当日已经生效的记录。信号持续到同一公司下一条
有效事件的 `effective_date` 前一日；修订报告只从自身生效日替代旧版本，绝不回填过去。

### 3.2 同日重复与金额冲突

资产负债表版本主键为：

```text
ts_code, end_date, report_type, available_date
```

对同一主键比较 `accounts_receiv`、`inventories`、`total_assets`、`total_liab`。金额完全相同
（含共同缺失）的重复记录，保留 `update_flag=1` 优先、再按 `source_file` 字典序最小的一条；
其余写入重复审计。任一核心金额不同则写入 `same_day_value_conflict`，整个主键不进入本面板。

收入表同日版本沿用既有财务事件面板规则：比较 `total_revenue`，冲突主键不进入本面板。
不得通过文件顺序、最终修订值或字段非空数量猜测应保留哪一版本。

### 3.3 资产负债表和收入精确对齐

本期资产负债表和收入仅可按下列四键精确连接：

```text
ts_code, end_date, report_type, available_date
```

不允许最近邻、同月或同报告期的近邻连接。无法精确连接时，标记
`statement_alignment_missing` 并排除，审计必须按事件年和报告期报告。

## 4. 固定会计口径与唯一主分数

### 4.1 期末余额 / 累计收入

应收账款和存货是期末余额；收入是同一报告期的累计金额。对每个精确对齐的本期事件，定义：

```text
receivable_intensity = log(1 + accounts_receiv / total_revenue)
inventory_intensity  = log(1 + inventories / total_revenue)
```

纳入计算必须同时满足：`total_revenue > 0`、`accounts_receiv >= 0`、`inventories >= 0`，且三者
均非缺失。收入非正、应收/存货为负、缺失或无穷值记为 `invalid_economic_ratio`；保留在审计中，
不以零、行业均值或其他科目填补。

使用 `log(1+x)` 仅为压缩极端的正比率、保留非负顺序；不做事后 winsorize、不按收益选择截尾
比例，也不将应收票据、其他应收款、预付款或其他流动资产加入首轮口径。

### 4.2 前年同期变化

本期只配对前年相同月日和相同 `report_type` 的有效事件：

```text
03-31 对 03-31；06-30 对 06-30；09-30 对 09-30；12-31 对 12-31
```

候选前年版本必须在本期 `available_date` 前已披露。若同一前年报告期在本期日前存在多个
PIT 版本，选择其中 `available_date` 最晚、但不晚于本期事件日的版本；这是当时市场能见的
最新版本，而不是今天的最终版本。若不存在，标记 `prior_not_available` 并排除。

固定计算：

```text
receivable_deterioration = receivable_intensity_current - receivable_intensity_prior
inventory_deterioration  = inventory_intensity_current - inventory_intensity_prior
working_capital_deterioration =
    (receivable_deterioration + inventory_deterioration) / 2
```

`working_capital_deterioration` 是**唯一主分数**。数值越大表示应收和存货相对收入同时更差，
预先声明的收益方向是“越大，未来收益越低”。两个单项只作经济诊断，不能在看到标签后替换
主分数、改为只保留表现较好的单项，或改变等权重。

需要同时拥有应收和存货有效同比变化才计算主分数；不以单项填补另一项。这样牺牲部分覆盖，
换取主分数的经济含义在全样本一致。日后研究单独的应收或存货命题，必须新建协议和独立确认。

## 5. 行业、市值与月初快照准备

面板保留事件生效日可得的历史申万一级行业；月初快照时再按照已冻结的 `asof_date` 连接自由
流通市值。面板构建不读取价格，也不依赖 CSI300、CSI500、CSI1000 成分。

未来每个月初只允许保留 `effective_date <= rebalance_date <= expiry_date` 的最新有效事件。行业、
市值或主分数缺失的公司将在后续“同一完整样本”中排除；不得用行业或市值结果决定是否保留
特定公司的会计记录。

## 6. 必须输出的无标签审计

面板构建后必须生成以下文件，然后停止：

```text
event_panel.csv.gz
same_day_duplicate_audit.csv.gz
same_day_value_conflict.csv.gz
statement_alignment_audit.csv.gz
prior_year_pairing_audit.csv.gz
ratio_validity_audit.csv.gz
coverage_by_event_year_and_period.csv
variable_distribution_by_event_year_and_period.csv
event_replacement_audit.csv.gz
methodology.json
event_panel_audit_report.txt
```

审计报告至少列出：每年/报告期事件与公司数；非金融覆盖；收入对齐缺失；同日冲突；前年配对
缺失；无效经济比率原因；`receivable_intensity`、`inventory_intensity` 及三项变化分数的分布；
每家公司修订/新报告替代事件的数量；以及行业缺失情况。所有剔除必须有原因和源文件血缘，
不得静默删除或改值。

## 7. 数据就绪门槛与后续边界

事件面板可标为 `working_capital_event_panel_ready` 的条件是：版本/冲突审计完整；本期三表精确
对齐、前年配对和无效比率均有可追溯数量；主分数定义固定且未读取收益；输出目录完整。

达到门槛后，下一步只能审查一份单因子有效性检验协议。该协议才可定义 20/40/60 日收益标签、
行业/市值中性化、开发/确认/封存期与通过门槛。本规范不授权读取这些数据、训练模型、回测或
实盘交易。
