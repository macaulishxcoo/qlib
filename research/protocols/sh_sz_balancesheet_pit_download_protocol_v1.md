# 沪深普通 A 股资产负债表 PIT 下载协议 v1

## 1. 状态、目的与执行边界

状态：`download_design_frozen_not_authorized_to_run`

本协议落实
`research/specifications/a_share_working_capital_balance_sheet_pit_minimum_data_spec_v1.md`，只规定
如何可复现地下载、保存和审计 Tushare `balancesheet` 历史 PIT 数据。目标是补齐营运资本研究
所缺的“应收账款、存货等期末余额”，而不是开始研究收益。

本文件不定义营运资本因子公式，不读取价格或收益，不生成标签，不做 IC、模型、回测或交易。
它本身也不授权执行下载；执行需要用户审查后明确授权。

## 2. 固定证券范围与数据范围

### 2.1 冻结证券清单

本次不得重新请求、重新筛选或按今天状态重建证券清单。唯一下载对象为既有三表 PIT 全量
快照中已经冻结并通过审计的 5,385 家沪深普通 A 股，及其固定顺序：

```text
data/external/tushare/a_share_financial_pit_v1/full/raw/batch_0001/stock_basic_snapshot.csv.gz
data/external/tushare/a_share_financial_pit_v1/full/raw/batch_XXXX/universe_slice.csv.gz
```

这样做是为了使资产负债表和已有收入表面对完全相同的历史证券范围，避免今天新上市、退市
或 Tushare 元数据变动造成隐蔽的样本差异。证券清单包含沪深主板、创业板和科创板普通 A 股
的当前上市与历史退市证券；不包含北交所、原新三板、B 股、基金、指数、债券等。

原始下载层不排除金融业。未来“营运资本质量”派生面板才以历史申万行业排除银行和非银金融，
以保留原始数据的完整性和可追溯性。

### 2.2 冻结接口和日期范围

```text
Tushare Pro 接口：balancesheet
公告可得日：2010-01-01 至 2025-06-30
报告期末：2009-12-31 至 2024-12-31
```

接口请求仅传 `ts_code`，保留服务端完整响应；因为接口日期参数按报告期而不是公告日期工作。
标准化阶段才按 `f_ann_date` 优先、`ann_date` 回退得到 `available_date`，并按上述公告/报告期
范围筛选。原始行即使超范围或日期异常也必须保留并在异常表说明，不能静默丢弃。

## 3. 请求规模、批次与限速

每家证券恰好一个 `balancesheet(ts_code=...)` 请求，因此预期为：

```text
5,385 家证券 x 1 个接口 = 5,385 次主体请求
```

沿用既有 `full/` 的 100 家证券批次边界和顺序，共 54 批（前 53 批各 100 家，最后一批 85 家）。
批次编号与已有 `batch_0001` 至 `batch_0054` 一一对应，但资产负债表单独位于
`balancesheet_v1`，绝不向已有三表批次添加或覆盖文件。

请求串行执行，每次请求间隔 0.3 秒；单次失败最多重试 3 次，退避为 0.3、0.6、0.9 秒。不得
通过并发、多个 Token、拆分账号或无界重试绕过数据源限速。网络、权限、频率或 schema 错误
必须记录，并阻断当前批次；失败绝不可记为 `no_data`。

## 4. 不可变存储布局

所有新文件只允许写入以下位置：

```text
data/external/tushare/a_share_financial_pit_v1/balancesheet_v1/
  raw/batch_0001/balancesheet/{ts_code}.csv.gz
  raw/batch_0001/request_log.csv
  raw/batch_0001/universe_slice.csv.gz
  normalized/batch_0001/balancesheet.csv.gz
  manifests/batch_0001.json

output/data_audits/a_share_financial_pit_v1/balancesheet_v1/
  batch_0001/
```

原始响应必须保留 Tushare 返回的全部字段，并附加 `requested_ts_code`、请求 UTC 时间、接口名、
批次号和源文件名。原始层禁止去重、改列、按研究日期过滤、填补公告日、换单位或覆盖旧文件。

标准化层保留原字段，另加 `available_date`、`available_date_valid`、
`report_period_in_scope`、`source_file`。它是分析便利层，不替代原始证据。

## 5. 断点、幂等与 Token 安全

一个证券请求只有在原始响应文件存在、SHA256 已记录且请求日志状态为 `success` 或 `no_data`
时才完成。进程中断后只恢复未完成项目；原始文件采用原子写入，已完成的文件不得重复请求或
覆盖。后续增量更新必须创建新版本目录，不能改写 `balancesheet_v1` 历史快照。

Token 只能从 `TUSHARE_TOKEN` 环境变量或本机已配置的受限 token 文件读取；不得写入脚本、
协议、命令行参数、CSV、JSON、日志或研究报告。

## 6. 每批审计与阻断条件

每批必须生成：

```text
batch_audit_report.txt
sample_or_universe_slice.csv
request_log.csv
schema_inventory.json
date_quality_summary.csv
version_quality_summary.csv
field_coverage_summary.csv
income_alignment_summary.csv
anomaly_records.csv.gz
metadata.json
```

审计至少报告：请求状态与 hash；实际 schema；日期合法率；`accounts_receiv`、`inventories`、
`total_assets`、`total_liab`、`total_cur_assets` 的覆盖、零值、负值和数量级；同日重复和金额
冲突；以及与已冻结 `income` 的精确键
`ts_code, end_date, report_type, available_date` 对齐情况。

一个批次仅当所有请求有可解释最终状态、必需字段存在、公告日未由报告期末伪造、冲突记录被
保留、原始及标准化文件可追溯时，才能标记 `batch_data_ready`。以下任一情况标记
`batch_blocked`：未解释请求失败、关键字段缺失或 schema 改变、系统性日期错误、单位无法解释、
或无法保留修订的可得时点。阻断后只允许定位/修复数据链，不得降低门槛或跳到因子研究。

## 7. 全量完成判定

54 批全部达到 `batch_data_ready` 后，才运行一次全量无标签审计。它只合并检查：证券范围是否
与既有 5,385 家快照一致、文件哈希和清单是否完整、日期/版本/字段覆盖是否合格、与 `income`
的精确对齐覆盖及异常原因。审计报告必须独立保存在：

```text
output/data_audits/a_share_financial_pit_v1/balancesheet_v1/full_audit_v1/
```

全量审计完成后停止并等待审查。只有数据链被接受，下一步才可制定“营运资本异常无标签事件
面板规范”；仍不得读取收益或开始模型实验。

## 8. 明确不做的事项

本协议不授权：补造缺失字段、用其他表填补应收或存货、以最终版本回填历史、按收益筛选证券、
更改已有三表数据、计算营运资本因子、读取价格标签、IC 检验、模型训练、回测或实盘交易。
