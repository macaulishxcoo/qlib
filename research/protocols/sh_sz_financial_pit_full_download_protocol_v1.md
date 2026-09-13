# 沪深普通 A 股财务 PIT 全量下载协议 v1

## 1. 状态、目的与执行边界

本协议承接：

- `research/decisions/shenzhen_shanghai_tushare_pit_acceptance_v1.md`；
- `research/specifications/a_share_earnings_quality_pit_minimum_data_spec_v1.md`。

它只回答：如何可复现地收集沪深普通 A 股的历史正式财报，并保留公告可得时点和
版本线索，供后续“盈利改善与现金流质量”研究使用。

**本文件只冻结全量下载方案，尚不授权执行下载。** 它不定义财务因子公式，不读
未来收益，不生成标签，不训练模型，不回测，也不构成交易范围或选股结论。

## 2. 研究范围与证券口径

### 2.1 原始下载范围

原始层包括沪深交易所的当前上市与历史退市普通 A 股，以避免只下载今天仍上市
公司造成幸存者偏差。纳入条件必须同时满足：

1. `stock_basic.exchange` 为 `SSE` 或 `SZSE`；
2. `ts_code` 是六位代码加 `.SH` 或 `.SZ`；
3. 代码前缀属于沪深普通 A 股：上交所 `600/601/603/605/688`，深交所
   `000/001/002/003/300/301`；
4. `list_status` 为当前上市 `L` 或已退市 `D`。
5. 证券在冻结公告窗口内可能有正式报告：`list_date <= 2025-06-30`，且已退市
   证券须满足 `delist_date >= 2010-01-01`。不满足者属于时间范围外，而非
   Tushare “无数据”。

北交所（`.BJ`）、原全国股转系统、B 股（如 `900/200`）、ETF、指数、债券、
CDR 及无法由上述规则确认的证券必须写入排除清单，不请求三张财务表。

金融行业不在下载层排除。它们保留在原始和标准化数据中；第一个“非金融盈利
质量”研究问题才以单独、可审计的行业规则排除金融股。

### 2.2 历史在市口径

每只证券必须保存 `list_date`、`delist_date`、`list_status` 和本次元数据快照。
后续任一信号日 `t` 的研究母池只能在：

```text
list_date <= t < delist_date（未退市时视为无上界）
```

内使用该证券；本协议不允许以今天的上市状态替代历史状态。

## 3. 冻结的时间范围与接口

第一版全量数据集范围为：

```text
接口：income、cashflow、fina_indicator
公告日期：2010-01-01 至 2025-06-30
保留报告期：2009-12-31 至 2024-12-31
```

2010 年公告窗口内的 2009 年报为早期同比基线；研究期起点、开发期和封存测试期
以后单独冻结，不能在本协议中由收益表现决定。

Tushare 的接口日期参数按报告期工作，并非公告日期筛选。因此每次请求只传入
`ts_code`，将服务端完整响应不改动地写入原始层；标准化层再按：

```text
available_date = 合法 f_ann_date，否则合法 ann_date
2010-01-01 <= available_date <= 2025-06-30
2009-12-31 <= end_date <= 2024-12-31
```

过滤。公告日或报告期无法解析、或不在冻结范围的记录不能因标准化过滤而静默
消失：必须在异常表记录原始文件、行标识、原始值和排除原因。

## 4. 下载执行设计

### 4.1 请求规模与节奏

预期沪深普通 A 股约数千只，主体请求数为：

```text
证券数 × 3 个接口（income、cashflow、fina_indicator）
```

全量作业采用固定、可复现的市场交替顺序：沪市和深市分别按 `ts_code` 升序排列，
每次交替取一只；任一市场耗尽后才继续另一个市场。第 1 批保存的 `stock_basic`
快照冻结整个下载作业的证券范围和排序，后续批次不得重新取当天证券清单。按每批
100 家（通常沪深各50家，约300次请求）串行执行；每批结束后生成独立审计摘要，
若状态为 `batch_data_ready` 则自动继续下一批。不得通过并发、多个 Token、拆分
权限或无界重试绕过 Tushare 限速。

遇到权限、频率、服务端错误或响应结构变化时，记录错误并停止当前批；最多重试
3 次，退避间隔为 0.3、0.6、0.9 秒。失败不允许标成“无数据”。

### 4.2 断点与幂等性

一个“接口 + `ts_code`”只有在同时满足下列条件时才视为完成：

1. 原始响应文件存在且 SHA256 已记录；
2. 请求日志状态为 `success` 或 `no_data`；
3. 响应字段结构已记录。

重启时只继续未完成项；除非显式运行更新模式，否则不覆盖历史原始文件。后续
更新必须写入新的批次目录，不得覆盖 v1 历史快照。

## 5. 文件布局与版本不可变性

全量文件只允许写入以下目录：

```text
data/external/tushare/a_share_financial_pit_v1/full/
  raw/batch_0001/{income,cashflow,fina_indicator}/
  raw/batch_0001/stock_basic_snapshot.csv.gz
  raw/batch_0001/request_log.csv
  normalized/batch_0001/{income,cashflow,fina_indicator}.csv.gz
  manifests/batch_0001.json

output/data_audits/a_share_financial_pit_v1/full/
  batch_0001/
```

原始响应保留服务端返回的全部行和字段，并添加 `requested_ts_code`、请求 UTC
时间、接口名、批次号和源文件名。原始层禁止去重、按日期范围过滤、改列名、填
公告日期、换单位或覆盖旧版本。

标准化层保留原字段，并新增 `available_date`、`available_date_valid`、
`report_period_in_scope`、`source_file`。同公司、同报告期、同报告类型的重复或
更新记录必须保留，分类为完全重复、更新标志重复或金额变化；不得只留下最终值。

结果不得写入 `mlruns*`、`examples/`、Qlib 行情目录或既有 `pilot/` 目录。

## 6. 每批强制审计与阻断条件

每个批次生成以下产物：

```text
batch_audit_report.txt
sample_or_universe_slice.csv
request_log.csv
schema_inventory.json
date_quality_summary.csv
version_quality_summary.csv
three_statement_alignment_summary.csv
field_coverage_summary.csv
anomaly_records.csv.gz
official_spot_check.csv
metadata.json
```

批次可标记 `batch_data_ready` 必须同时满足：

1. 全部请求均为成功、明确 `no_data` 或有解释的失败；
2. 任何有财报记录的公司不得将报告期末静默填作公告日；
3. `income`、`cashflow` 的核心字段、日期合法率和可解释对齐率分别报告；
4. 重复/更新记录保留在版本审计表；
5. 文件哈希、请求参数、代码版本和证券元数据快照完整；
6. 生成固定抽样清单 `official_spot_check.csv` 作为发生数据疑点时的追溯入口，
   但不要求每批人工核对交易所公告。Tushare 已按个人研究标准被用户接受为主
   结构化来源；当前批次由程序审计通过后即可标记 `batch_data_ready`。

若发现公告日期、金额、单位或更正/修订版本的具体疑点，才必须核验报告期、公告
日期、营业收入、净利润、经营现金流和更正/修订，并将结论写入该清单。无法解释的
不一致使受影响批次为 `batch_blocked`。

下列情况使批次为 `batch_blocked`：系统性日期错误、关键金额单位不明、发现官方
更正但无法保留其可得时点、未解释请求失败、或针对具体疑点的核验发现日期/金额
不一致。
阻断后只能定位数据问题、修正收集器或更换数据源；不得降低门槛或直接进入因子
研究。

## 7. 全量完成判定

所有批次完成并各自达到 `batch_data_ready` 后，才可生成一次全量合并审计。合并
审计只检查数据血缘、覆盖、日期、版本和文件完整性；仍不读取收益或计算因子。

合并审计结束后停止，等待用户审查。下一阶段应另行定义“盈利改善与现金流质量”
变量的分母、极端值处理和事件持有规则，之后才允许读取收益标签。

## 8. 本协议不授权的事项

本协议不授权：执行全量下载、补造缺失财报、从其他表推导缺失金额、财务因子
公式搜索、收益标签读取、IC 检验、模型训练、回测、交易或把数据混入 Alpha158。
