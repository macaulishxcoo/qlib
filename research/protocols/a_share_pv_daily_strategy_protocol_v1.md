# 纯量价日频策略协议 v1

状态：`executed_not_viable`（2026-08-13 执行；main/turnonly 扣成本后大负
gross 即负、skewonly 弱正 IR 0.25 未过 0.5 门槛 → 判定 `dead`；关键教训：
IC 正 ≠ 可交易，换手率组合层方向反转；结论归档见
`research/decisions/a_share_pv_daily_strategy_closure_v1.md`）

## 1. 三问门槛

| 问 | 答 |
|---|---|
| 服务哪个决策 | 纯量价日频策略**是否值得继续投入**（组合版"基本面域+量价快信号"的前置验证）——回答"换手率水平+偏度在真实日频调仓、扣成本后能否活" |
| 最小版本 | 两因子（TURNOVER_LEVEL5 + SKEW60）MVI 残差合成信号 → TopkDropout topk=50 n_drop=5 日频调仓 → SH000852 基准，base/stress 两套费率，2022-01-01 ~ 2026-07-31 |
| 验收标准 | 扣成本后 net 超额年化 > 0 且 net IR ≥ 0.5 → `viable`（值得进组合版本）；0 < IR < 0.5 → `weak`（需组合/择时增强）；net 超额 ≤ 0 → `dead` |

**后续项（本协议不执行，另行立项）**：组合版（基本面月频域 + 量价日频快信号）——
待本验证 `viable` 后立项，路径已由
`a_share_price_volume_factor_orthogonality_h40_closure_v1.md` 指出（候选因子是
短周期信号，恰为日频策略所需；基本面四因子作月频更新选股域）。

## 2. 假设与信号（冻结）

- 假设：换手率水平 + 收益偏度（MVI 中性化后，battery/neutralization v1 已证
  alpha_confirmed、h=5 日频口径有效）在**真实日频调仓 + 扣成本**后仍为正超额。
- 信号：逐日全市场横截面计算：
  - `TURN_MVI` = TURNOVER_LEVEL5（自由流通换手率 5 日均值）的 MVI 残差
    （log circ_mv + std20 + 申万 L1，复用 `neutralize_day`）；
  - `SKEW_MVI` = SKEW60（60 日日收益偏度）的 MVI 残差（同法）；
  - `score` = `0.5 * rank_pct(TURN_MVI) + 0.5 * rank_pct(SKEW_MVI)`（逐日截面）。
- 主版本 = 合成 score；对照版本 = 单因子（TURN 单独 / SKEW 单独）——识别贡献源。

## 3. 口径（冻结，与 v1/v2 一致）

| 项 | 冻结值 |
|---|---|
| 主池 | 沪深普通 A 股母池（all.txt 历史在市，剔除 BJ/指数/B 股） |
| 数据 | `cn_data_2026`（后复权）+ `daily_basic_pit_v1`（换手率/市值）+ `style_pit_v1`（行业） |
| 过滤 | ST/*ST/退市（PIT）+ 停牌 + 涨停信号日（同 v1），信号日剔除 |
| 回测窗口 | 2022-01-01 ~ 2026-07-31（预热自 2020-01-01；SH000852 已修复无断层） |
| 策略 | TopkDropout topk=50, n_drop=5（日频低换手，ROADMAP csi300 滑点扫描结论） |
| 成交 | `deal_price="open"`（T+1 开盘成交），`limit_threshold=0.095`，`min_cost=5` |
| 基准 | SH000852（中证 1000） |
| 费率 | base: open 0.0005 / close 0.0015；stress: open 0.0010 / close 0.0030（仓库惯例） |

## 4. 检验与报告

- 版本：main（合成）、turnonly（TURN 单独）、skewonly（SKEW 单独）；每版本 × base/stress。
- 指标（对齐 `metrics_judgment_standard.md`）：扣成本 net 超额年化/IR/最大回撤、
  gross 超额年化/IR、日均换手率、年化成本拖累、2025-07 后（近期）net 超额。
- 分年度 net 超额（base）。
- 报告合成 vs 单因子对照，识别贡献源与拥挤（两因子高度同向则合并增益有限）。

## 5. 预设判定（对合成 main/base）

| 条件 | 判定 |
|---|---|
| net 超额年化 > 0 且 net IR ≥ 0.5 | `viable` → 值得进组合版（另行立项） |
| net 超额年化 > 0 且 0 < net IR < 0.5 | `weak` → 需组合/择时增强，暂不立项 |
| net 超额年化 ≤ 0 | `dead` → 纯量价日频收口，不再投入 |

stress 场景与 2025-07 后表现如实报告，不改变判定路径。

## 6. 产物与目录

```text
output/analysis_static/a_share_pv_daily_strategy_v1/
  backtest_summary.csv       版本×费率 全期指标
  yearly_summary_main.csv    主版本分年度 net 超额（base）
  daily_report_main_base.csv.gz  主版本 base 日度 report（return/bench/cost/turnover）
  decision.json              预设判定
  methodology.json           口径快照
  validation_report.txt      中文报告
```

脚本：`scripts/backtest_a_share_pv_daily_strategy_v1.py`
（复用 `neutralization_v1.load_market/neutralize_day/build_filter_mask` +
qlib `TopkDropoutStrategy/backtest_daily/risk_analysis`）。

## 7. 结论边界

本验证只回答"纯量价日频是否值得继续投入"。`viable` 不直接进实盘；组合版
（基本面域+量价快信号）另行立项。所有结论在仓库口径（后复权、历史成分、真实
费率）下成立。

## 8. 变更记录

| 日期 | 变更 |
|---|---|
| 2026-08-13 | 创建：冻结两因子合成信号 + TopkDropout 日频回测 + 三档判定；组合版列为后续项 |
