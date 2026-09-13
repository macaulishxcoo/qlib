# 沪深非金融 A 股价值/质量水平因子同族扩展验证协议 v1

## 1. 状态、问题与授权边界

状态：`design_frozen_before_first_label_read`

承接 `a_share_value_quality_level_factors_validation_protocol_v1.md`：E/P
（扣非盈利收益率）已在开发/确认/封存三阶段全部通过预设门槛，标记为
`replicated_for_strategy_design`。本协议扩展同族验证，回答：

```text
与 E/P 同属"价值/质量水平因子"族、但经济机制不同的另外 4 个候选
（BM、ROE 稳定性、应计质量、股息率），是否同样具备跨阶段预测力？
```

本协议只授权**单因子信息含量检验**，不授权模型训练、组合回测或实盘。
新增 4 个变量在读取任何标签前冻结；跑完不因结果调整变量或门槛。

## 2. 与第一轮的关系

| 项 | 第一轮 | 本轮扩展 |
|---|---|---|
| 已冻结变量 | `ep`、`cfo_ni`、`lev` | 新增 `bm`、`roe_stability`、`accruals`、`div_yield` |
| E/P 角色 | 主命题 | **对照基准**（同框架复现，确认扩展脚本与原结果一致） |
| `cfo_ni`、`lev` | 已判定失败 | **不重跑**（失败即止，纪律不变） |
| 验证框架 | 月度截面 + 20/40/60 日 + 中性化 + 规模层 | **完全相同** |

## 3. 新增变量定义（冻结）

| 名称 | 公式 | 方向 | 经济机制 |
|---|---|---|---|
| `bm` | 每股净资产 `bps`（最新期，PIT）× 总股本 `total_share` / 总市值 `total_mv` | 越高越好 | 账面价值相对市价低估，价值因子第二代表 |
| `roe_stability` | `-std(roe, 最近8个报告期)`（PIT 可得版本） | 越高越好（即 ROE 波动越小） | 高质量盈利公司的低波动性 |
| `accruals` | `-(净利润TTM - 经营现金流TTM) / 总资产(最新期)` | 越高越好（即应计越低） | 利润与现金流差异越小，利润越真实 |
| `div_yield` | `dv_ttm`（月末 PIT 市值表自带） | 越高越好 | 现金分红回报，防御型价值 |

补充约束：
- `bm`：仅对最新期 `bps > 0` 的股票有效；
- `roe_stability`：最近 8 个报告期必须有至少 6 期 `roe` 非空，否则该月缺失；
- `accruals`：仅对净利润 TTM > 0 的股票有效（分母约束与 `cfo_ni` 一致）；
- `div_yield`：`dv_ttm` 缺失（不分红公司）时为缺失，不填 0。

## 4. 验证框架（与第一轮完全一致）

- 时间切分：开发期 2014-01~2019-12、确认期 2020-01~2022-12、
  封存测试 2023-01~2025-05；
- 月末信号快照：`available_date <= rebalance_date` 的 PIT 记录；
- 标签：`r_H(t) = open(t+H)/open(t) - 1`，H ∈ {20, 40, 60}；
- 中性化：横截面 OLS 去除申万一级行业 + log(自由流通市值)；
- 规模层：当月完整样本 `size_control` 五等分 S1~S5，主期限 40 日；
- 判定门槛：与第一轮 §8 完全相同（开发期 40 日中性 RankIC ≥ 0.01 且
  20/40/60 均为正、ICIR ≥ 0.20 → 确认期 → 封存测试）。

## 5. 产物、目录与审计

```text
output/analysis_fundamental/a_share_value_quality_level_factors_v1_extension/
  monthly_signal_label_panel.csv.gz
  monthly_rank_ic.csv.gz
  rank_ic_summary.csv
  group_return_summary.csv
  size_layer_summary.csv
  sample_coverage_summary.csv
  decision.json
  methodology.json
  validation_report.txt
```

`decision.json` 对每个新增变量独立给出
`development/confirmation/holdout` 判定；`ep` 作为对照复现，其结果必须与
第一轮一致（中性 RankIC 偏差 < 0.01），否则视为脚本回归。

## 6. 结论边界

若 `bm`、`roe_stability`、`accruals`、`div_yield` 中任一通过封存测试，
与 E/P 构成多因子候选池，下一步计算存活因子两两 Spearman 相关以决定
组合互补性。若全部失败，则基本面水平因子族仅 E/P 存活，按第一轮协议
§10 进入 E/P 月度策略可交易池设计。

本协议不授权模型训练、自动因子挖掘或直接实盘。
