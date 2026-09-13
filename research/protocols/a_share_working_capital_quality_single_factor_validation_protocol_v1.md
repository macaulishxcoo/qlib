# 沪深非金融 A 股营运资本质量单因子有效性检验协议 v1

## 1. 状态、问题与授权边界

状态：`design_frozen_before_first_label_read`

本协议承接已完成无标签审计的 `working_capital_event_panel_v1`，首次定义如何检验以下唯一的
经济命题：

```text
正式财报披露后，应收账款和存货相对收入的同比恶化越少（营运资本质量越高）的公司，
是否在后续 20、40、60 个交易日有更高的横截面收益；该关联在移除行业和自由流通市值
暴露后是否仍然存在？
```

它只授权**单因子信息含量检验**，不授权 LightGBM、因子搜索、策略回测、成本估计、选股或
实盘交易。若命题未通过，不能改分母、改权重、改持有期、改股票池或只留下表现较好的应收/
存货单项来挽救它。

## 2. 固定输入与研究母池

| 输入 | 作用 | 冻结范围 |
|---|---|---|
| `event_panel.csv.gz` | 已 PIT 对齐的营运资本事件与主分数 | 155,725 条无标签事件，5,129 家非金融历史公司 |
| 月初网格、行业、自由流通市值 | 月初信号快照、中性化、规模分层 | `a_share_style_pit_v1`，2014-01 至 2025-06 的 138 个月 |
| Qlib `cn_data_2026` 日历与 `open` | 前瞻价格标签 | 仅在本协议允许的阶段、股票和日期读取 |

研究母池为历史在市的沪深普通 A 股，不把 CSI300、CSI500、CSI1000 或任何事后收益较高的
指数作为默认范围。事件面板已按事件日排除银行与非银金融；月初快照仍须使用 `asof_date`
有效行业并使用相同规则确认。

## 3. 唯一分数与方向

无标签面板已冻结：

```text
working_capital_deterioration =
  (receivable_deterioration + inventory_deterioration) / 2
```

为使“高分 = 预期较高收益”的统计方向统一，验证时唯一主分数固定为：

```text
working_capital_quality = -working_capital_deterioration
```

这只是符号翻转，不改变应收/存货的等权组成、同比口径或事件样本。`receivable_deterioration`
和 `inventory_deterioration` 只作预先声明的诊断组件：报告其结果以帮助解释主结果，但不能从
中挑选一个替代主命题，也不能据其结果修改主分数。

## 4. 时间切分与顺序门控

按月初 `rebalance_date` 切分；收益窗口跨年不改变所属阶段：

| 阶段 | 信号月初日期 | 目的 | 可读取条件 |
|---|---|---|---|
| 开发期 | 2014-01-01 至 2019-12-31 | 检验一次已冻结命题的数据与方向 | 本协议批准后首次且唯一一次读取 |
| 确认期 | 2020-01-01 至 2022-12-31 | 独立确认跨阶段稳定性 | 仅开发期通过第 8.1 节全部门槛后 |
| 封存期 | 2023-01-01 至 2025-06-30 | 不参与任何选择的最终复现 | 仅确认期通过第 8.2 节全部门槛后 |

程序必须按阶段顺序执行并在每道门后停止。若某阶段不通过，后续价格不得读取，已封存阶段
也不得以任何形式用于解释、筛选或重新设计本命题。

## 5. 月初 PIT 信号快照

每个固定 `rebalance_date = t`：

1. 使用 `effective_date <= t <= expiry_date` 的事件；同一股票若仍有多个事件，取
   `effective_date` 最新的一条；
2. 只使用 `asof_date` 有效的申万一级行业和在该日已知的自由流通市值；
3. 对主分数、行业、`size_control` 或标签缺失/非有限的公司，均从该月完整样本排除；
   原始与中性化统计必须使用**同一完整样本**；
4. 完整样本少于 100 家时，该月该期限全部记为无效并报告，不能用其他月份、指数成分或
   横截面均值填补；
5. 不按 ST、停牌、流动性、涨跌停或以后收益过滤。这是信息含量检验，不是可成交组合。

## 6. 前瞻标签与执行时点

使用 Qlib 同一复权口径的 `open` 和交易日历。因为月初信号在 `t` 开盘前由已经生效的财报
事件与前一交易日 `asof_date` 控制变量决定，固定标签为：

```text
r_H(t) = open(t + H) / open(t) - 1,  H ∈ {20, 40, 60}
```

`t + H` 表示交易日历中 `t` 后第 H 个交易日。任一端 `open` 缺失、非正、或证券不在其历史
在市区间，则该股票该期限标签为缺失，不得使用收盘价、后一天价格、外部价格或横截面填补。

这不是成交模拟。真实停牌、涨跌停、ST、成本与容量只在一个因子通过信息检验后才另行定义。

## 7. 固定统计方法与报告

### 7.1 原始结果

在每月每个期限的完整样本中，计算 `working_capital_quality` 与 `r_H` 的 Spearman Rank IC。
报告月度序列、均值、标准差、ICIR、正 IC 月占比及按阶段/日历年汇总。

同时按分数等频五分组（用 `rank(method="first")` 后分组）报告平均标签、`Q5-Q1` 和五组
相邻不降比例。诊断组件按同样方式报告，但没有独立的通过资格。

### 7.2 行业/市值中性化结果

在每月相同完整样本中对主分数进行横截面 OLS：

```text
working_capital_quality = intercept
                        + beta_size * size_control
                        + Shenwan level-1 industry dummy coefficients
                        + residual_quality
```

`size_control = log(free_float_market_value)`，行业为 `asof_date` 有效申万一级行业；与截距
共同省略一个行业虚拟变量。用 `residual_quality` 和同一批 `r_H` 再计算 Rank IC 与五分组结果。
中性化只识别去除二者合并暴露后的剩余关联，不能把原始与残差差异解释为单独的行业或市值贡献。

### 7.3 预定义稳健性报告

- 固定主期限是 40 日；20/60 日是衰减诊断，不能因更好看而替代主期限；
- 按当月完整样本的 `size_control` 等频分为 S1--S5，报告主分数 40 日原始和中性化 Rank IC；
- 对月内样本至少 10 家的一级行业，报告 40 日原始 Rank IC 分布，不将最佳行业升级为结论；
- 所有阶段汇总采用“先每月统计、再对月份等权平均”，避免样本更多的月份支配结论。

## 8. 预设通过与关闭门槛

门槛只判断是否有资格进入未来策略设计，不承诺可交易收益。

### 8.1 开发期门槛

主命题成为 `development_candidate` 必须同时满足：

1. 40 日中性化平均 Rank IC `>= 0.01`；
2. 20、40、60 日中性化平均 Rank IC 均为正；
3. 40 日中性化 `Q5-Q1 >= 0`；
4. 40 日中性化 ICIR `>= 0.20`。

任一失败即为 `hypothesis_not_supported_in_development`：停止该命题，不读确认/封存价格，不改
公式或阈值。

### 8.2 确认期门槛

仅开发期通过时运行。成为 `confirmed_candidate` 必须同时满足：

1. 40 日中性化平均 Rank IC `>= 0.01` 且为正；
2. 20、40、60 日中性化方向均不反转；
3. 40 日中性化 `Q5-Q1 >= 0`；
4. 至少 3 个预定义规模层的 40 日中性化 Rank IC 为正；
5. 去除最小市值 S1 后，40 日中性化 Rank IC 仍为正。

任一失败即为 `hypothesis_not_supported`，封存期不得读取。

### 8.3 封存期门槛

仅确认期通过时运行一次。若 40 日中性化 Rank IC 为正、20/60 日不同时反向、且 40 日中性化
`Q5-Q1 >= 0`，标记 `replicated_for_strategy_design`；否则 `not_replicated`。无论结果如何，
封存期之后不得修改该命题并重跑。

## 9. 产物与审计

首次开发期运行只能写入：

```text
output/analysis_fundamental/a_share_working_capital_quality_single_factor_v1/
  development_monthly_signal_label_panel.csv.gz
  development_monthly_rank_ic.csv.gz
  development_rank_ic_summary.csv
  development_group_return_summary.csv
  development_size_layer_summary.csv
  development_industry_distribution_summary.csv
  development_sample_coverage_summary.csv
  decision.json
  methodology.json
  validation_report.txt
```

确认/封存只有在前一门通过后才可追加对应前缀文件。`methodology.json` 必须记录输入路径和
hash、变量版本、标签交易日映射、每月完整样本与无效月、阶段门控状态及本协议 SHA256。
报告先写覆盖和无效月，再写原始/中性化结果和预设结论。

## 10. 本协议后的决策

- `hypothesis_not_supported*` 或 `not_replicated`：关闭这一具体营运资本组合命题；不进入
  LightGBM 或回测，也不宣称基本面整体失效；
- `replicated_for_strategy_design`：下一步只制定个人可执行的月度策略规则（ST/停牌/涨跌停、
  流动性、容量和保守成本），随后才可回测。

本协议不授权自动因子挖掘、修改 Alpha158 或把本分数加入模型训练。
