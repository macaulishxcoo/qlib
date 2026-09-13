# 沪深非金融 A 股营运资本质量：资产负债表 PIT 最小数据规范 v1

## 1. 目的、状态与边界

状态：`design_frozen_before_download_and_label_access`

本规范只定义下一条研究命题所需的资产负债表 PIT 数据，服务于以下尚未检验的问题：

```text
在正式财报披露后，应收账款或存货相对收入的同比异常恶化，
是否预示未来 20--60 个交易日较低的横截面收益？
```

它先冻结最小字段、可得时点、报表对齐和审计规则，避免在看到收益结果后选择有利的会计
口径。它不授权下载数据、读取收益、计算因子、训练、回测或交易；完成后必须等待审查。

## 2. 范围和已有输入

新增数据覆盖沪深普通 A 股，排除北交所、新三板、B 股、基金、指数、债券等。原始层保留
金融业；派生研究层才按历史申万一级行业排除银行（`801780.SI`）和非银金融（`801790.SI`）。
公告可得日范围为 2010-01-01 至 2025-06-30，报告期范围为 2009-12-31 至 2024-12-31。

下载证券清单、历史上市/退市状态和原始层规则沿用
`research/protocols/sh_sz_financial_pit_full_download_protocol_v1.md`。已完成的收入 PIT 是唯一
收入分母来源：

```text
data/external/tushare/a_share_financial_pit_v1/full/normalized/batch_*/income.csv.gz
```

收入只用 `income.total_revenue`，不得以最终修订值回填过去，也不得以价格或其他字段反推。

## 3. 新增来源与最小字段

新增源为 Tushare Pro `balancesheet`。原始响应必须保存全部字段；未来标准化、审计和首轮
命题必需字段如下：

| 类别 | 字段 | 用途 | 规则 |
|---|---|---|---|
| 身份与版本 | `ts_code`、`ann_date`、`f_ann_date`、`end_date`、`report_type`、`update_flag` | 公司、报告期、版本与可得时点 | 原样保留并建立标准化日期列 |
| 应收 | `accounts_receiv` | 期末应收账款余额 | 首轮必需；不以应收票据或其他应收款替代 |
| 存货 | `inventories` | 期末存货余额 | 首轮必需；不以预付款或其他流动资产替代 |
| 收入分母 | `income.total_revenue` | 对应累计报告期营业收入 | 与资产负债表精确对齐，见第 5 节 |
| 一致性检查 | `total_assets`、`total_liab`、`total_cur_assets` | 检查单位、符号和异常 | 不进入首轮因子公式 |

若实际 schema 缺少上述字段或字段名不同，下载作业必须停止并审计差异；不得猜测列名或静默
使用相似字段。

## 4. PIT 可得时点与版本

每条记录按以下规则生成日期：

```text
available_date = 合法 f_ann_date；否则使用合法 ann_date
effective_date = available_date 之后的第一个 Qlib CN 交易日
```

报告期末不是市场可得日。信号日只能使用当日及之前可得的版本，后来修订只从其自身生效日
起有效，绝不回填历史。

版本主键为 `ts_code, end_date, report_type, available_date`。对同一主键比较
`accounts_receiv`、`inventories`、`total_assets`、`total_liab`：金额完全相同（包括共同缺失）
的重复项优先保留 `update_flag=1`，再按源文件名排序；任一金额冲突则记录
`same_day_value_conflict`，整个主键不进入首轮面板；不同 `available_date` 的修订版本均保留。

## 5. 会计口径和精确对齐

`accounts_receiv`、`inventories` 是期末余额；`total_revenue` 是累计期间金额。首轮可使用
“期末营运资本余额 / 同报告期累计收入”的描述性比率，但同比只能匹配同月日：

```text
03-31 对 03-31；06-30 对 06-30；09-30 对 09-30；12-31 对 12-31
```

禁止混合不同累计口径，禁止事后根据收益决定改单季收入或其他分母。

资产负债表与收入只允许按以下键精确连接：

```text
ts_code, end_date, report_type, available_date
```

不允许最近公告或同月公告的近邻配对。例如资产负债表在 8 月 28 日披露、收入在 8 月 30 日
修订披露，二者不能构成 8 月 28 日信号；无法精确对齐则标记
`statement_alignment_missing` 并排除。前年同比版本也必须在本期 `available_date` 前已可得，
否则标记 `prior_not_available`，不得用今天可见的终版补齐。

本规范不冻结具体因子公式、截尾或好坏方向；这些只能在无标签事件面板完成后、读取收益前，
由独立验证协议冻结。

## 6. 存储与血缘

新增数据必须独立存放，不能覆盖既有三表快照：

```text
data/external/tushare/a_share_financial_pit_v1/balancesheet_v1/
  raw/batch_XXXX/balancesheet/
  normalized/batch_XXXX/balancesheet.csv.gz
  manifests/batch_XXXX.json

output/data_audits/a_share_financial_pit_v1/balancesheet_v1/
  batch_XXXX/
```

原始层保留服务端全字段、请求证券、时间、接口、批次和源文件名。标准化层保留原字段，新增
`available_date`、`available_date_valid`、`report_period_in_scope`、`source_file`。

## 7. 必须完成的无标签审计

审计不读取价格、收益、IC 或策略结果，且必须输出异常明细和血缘：

1. 请求完整性：证券数、请求数、成功/无数据/失败数及原始文件 hash；
2. schema：必需字段、类型和接口版本差异；
3. 日期：`ann_date`、`f_ann_date`、`available_date`、`end_date` 合法率及异常；
4. 版本：同日重复、同日金额冲突、不同可得日的修订数；
5. 核心字段：按事件年和报告期统计应收、存货、资产、负债的缺失、零值、负值和数量级异常；
6. 会计一致性：报告资产、负债正值覆盖和单位疑点，不用恒等式补造字段；
7. 收入对齐：按事件年和报告期报告与已有 `income` 的精确对齐率、缺失原因和冲突数；
8. 母池覆盖：合并历史上市状态和行业后报告非金融候选覆盖率；不得按 ST、停牌、流动性或
   收益表现剔除。

## 8. 数据就绪门槛和后续边界

只有满足以下条件才可标记 `balancesheet_data_ready`：所有请求有可解释最终状态且未解释失败
为零；必需字段存在；没有用报告期末替代公告日；同日冲突均保留且排除；收入精确对齐结果已
报告；原始、标准化、审计和 manifest 可追溯且不覆盖既有快照。

即使数据就绪，也不得直接训练模型。下一步只能制定“营运资本异常无标签事件面板规范”，
冻结比率、同比变化、极端值处理、事件替代和覆盖规则，之后才可审查收益验证协议。
