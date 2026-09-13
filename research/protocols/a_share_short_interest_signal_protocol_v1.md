# 融券（空头）信号独立信息检验协议 v1

## 1. 状态、问题与授权边界

状态：`design_frozen_before_data`

**承接**：`PROJECT_SYNC.md` §8「下一步候选（研究）」第 2 条 ——
「**融券余量信号**（rqye/rqyl/rqmcl）："空头在定价坏消息"的直接度量，**已入库从未消费**」。
以及 `a_share_data_assets_and_mainline_status_sync_v1.md` §1.3 记录的
「仅 rzye（融资余额）测过：IC -0.043，作过滤层无增量；**rqye/rqyl/rqmcl（融券）未测**」。

**本协议只回答三个问题：**

```text
Q1. 融券类信号是否按"发布滞后"正确对齐（T 日盘后公布 -> T+1 才可见）？
Q2. 融券类信号是否携带独立于价量因子的截面方向性信息（RankIC / ICIR）？
Q3. 融券类信号与融资余额（rzye，已测）以及价量因子是否正交？
```

**不做**：不训练模型、不构造复合策略、不做参数搜索、不回测组合层。
本协议只做单因子层面的检验；是否进入策略层由结论按预冻结规则决定。

**为什么值得测（与已关闭路线的关系）**：本项目已关闭的 13 条线全部基于
价量 / 估值 / 事件 / PEAD / 两融**融资**侧 / 趋势 / 市场宽度。**融券（空头）侧从未测过**，
其经济机制（知情卖空者定价坏消息）与前 13 条线不同源，因此不属于"重复已关闭方向"。

## 2. 信息边界与数据（冻结）

| 项 | 固定值 |
|---|---|
| margin 数据 | `data/external/tushare/margin_pit_v1/normalized/margin_detail.csv.gz`，2016-01-04 ~ 2026-08-07 |
| 融券字段 | `rqye`（融券余额，元）、`rqyl`（融券余量，股）、`rqmcl`（融券卖出量）、`rqchl`（融券偿还量） |
| 流通市值 | `a_share_daily_basic_pit_v1` 的 `circ_mv`（万元 -> 元） |
| 价格 | Qlib store `cn_data_2026`：`$open`（标签）、`$close`/`$volume`（价量因子） |
| 股票池 | 沪深普通 A 股：排除 `30*`（创业板）、`688*`（科创板）、`BJ/8*/4*`（北交所）、B 股、指数 |
| 样本期 | **2018-01-01 ~ 2026-06-30**（2016-2017 用于时序窗口预热） |

## 3. 冻结的信号定义（不得事后增删）

所有信号在 t 日决策时只使用 **t-1 及更早**的数据。

| 信号 | 定义 | 方向先验 |
|---|---|---|
| `short_ratio` | `rqye(t-1) / circ_mv(t-1)`，融券余额占流通市值比 | 越高越空 |
| `short_z` | `short_ratio` 的 250 日时序 z-score（至少 60 日历史） | 越高越空 |
| `short_chg20` | `rqyl(t-1) / rqyl(t-21) - 1`，融券余量 20 日变化 | 越高越空 |
| `short_flow` | `(rqmcl(t-1) - rqchl(t-1)) / rqyl(t-2)`，净融券卖出占存量比 | 越高越空 |

有效性判定**取绝对值**（方向由数据决定，先验只用于解读），避免因符号猜测错误而误杀。

## 4. 冻结的标签口径

遵守 `PROJECT_SYNC.md` §7 纪律 3「标签必须用 open-to-open 口径」：

```text
label_h(t) = open(t+1+h) / open(t+1) - 1      h ∈ {1, 5, 10, 20}
```

即 t 日盘后出信号、t+1 开盘建仓、持有 h 个交易日后开盘平仓。**不使用**
`open(t+1)/close(t+h+1)-1` 的旧式口径。

## 5. 冻结的判定阈值（预先确定，事后不得调整）

依据 `metrics_judgment_standard.md`（IC ≥ 0.05 / ICIR ≥ 0.5 才算有效）：

| 判定 | 条件 |
|---|---|
| `lag_ok` | `aligned` 与 `misaligned` 的 \|IC\| 差异 < 30%（即未依赖未来函数） |
| `orthogonal` | 与全部价量因子、以及 rzye 的 \|均值截面 Spearman 相关\| < 0.4 |
| `effective` | 主口径 h=5 满足 \|RankIC\| ≥ 0.05 **且** \|ICIR\| ≥ 0.5，且 h=1/10/20 中至少 2 个同号且 \|IC\| ≥ 0.03 |
| `supported` | `lag_ok` **且** `orthogonal` **且** `effective`，三者同时成立 |
| `not_supported` | 否则 |

主口径固定为 **h = 5**（对应目标中的"5 日"），**不事后挑最好的 horizon**。

## 6. 产物与目录

```text
output/analysis_fundamental/a_share_short_interest_signal_v1/
  ic_by_date.csv.gz           # 每信号 x 每 horizon 的每日 RankIC
  ic_summary.csv              # 均值/ICIR/t 值/正比例 汇总
  lag_alignment_check.csv     # Q1
  cross_section_correlation.csv.gz   # Q3 每日截面相关
  correlation_summary.csv     # Q3 汇总
  decision.json
  methodology.json
  short_interest_report.txt
```

## 7. 预设结论与后续

| 结论 | 后续动作 |
|---|---|
| `supported` | 进入下一轮：作为**过滤层**在五因子 top30_cap3 上做增量检验（另立协议） |
| `not_supported` | 记录原因并关闭该信息源；**不追加公式、不换窗口、不换阈值** |

## 8. 结论边界

- 本协议不模拟交易成本，不做组合构建；「IC 正 ≠ 可交易」是本项目已写死的教训
  （`PROJECT_SYNC.md` §5 教训 1），因此 `effective` 不等于"可部署"。
- 融券标的本身是交易所指定名单，存在**样本选择性**；结论只在该名单内成立，
  不外推到全市场。
- 2016-2017 仅用于时序窗口预热，不计入统计。
