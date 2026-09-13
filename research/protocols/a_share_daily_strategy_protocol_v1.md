# 日频策略协议 v1（基本面域 + 量价增强）

状态：`executed_main_baseline`（2026-08-13 执行；main=域内基本面日频 net
+0.164/IR 1.68 四年全正、换手 4.8%、stress 下 IR 1.58 → 日频基线确立；
enhanced=0.7comp+0.3skew net +0.100/IR 1.08、2025H1 转负、换手×3 → 偏度
增强不采纳；结论归档见 `research/decisions/a_share_daily_strategy_closure_v1.md`）

## 1. 三问门槛

| 问 | 答 |
|---|---|
| 服务哪个决策 | 日频策略的正式基线——确认"基本面域 + 日频调仓"（domain_comp）为日频策略主力，并回答偏度增强是否贡献增量 |
| 最小版本 | 三版本对照：main=domain_comp（基本面域内 composite 排序，日频 top50）、enhanced=域内 0.7·comp + 0.3·skew（偏度低权重增强）、对照=domain_skew（已测，引用）；TopkDropout topk50 n_drop5 日频、SH000852、base/stress、2022-01~2025-06 |
| 验收标准 | enhanced net IR≥0.5 且 net 超额 > main → 偏度增强采纳（`enhanced_adopted`）；否则增强不采纳（`main_baseline`）；无论增强是否采纳，main net IR≥0.5 → 日频基线成立 |

## 2. 假设与信号（冻结）

- 假设：基本面域（composite 中性化前 50%，月频）内日频调仓是有效基线
  （上轮 domain_comp net +0.122/IR 1.34）；域内偏度（上轮 IR 0.60）与基本面
  正交（|corr|<0.11），低权重叠加可小幅增厚。
- 信号（逐日域内横截面）：
  - `comp_rank` = 域内 composite_neutral 的 rank pct（月频更新，月内固定）；
  - `skew_rank` = 域内 SKEW60 MVI 残差的 rank pct（逐日）；
  - `score_main` = `comp_rank`；
  - `score_enhanced` = `0.7*comp_rank + 0.3*skew_rank`（低权重增强，防量价污染）。
- 域 = composite_neutral（四因子≥3 门槛 → 行业+log_size 残差）前 50%，42 个月度调仓日、月内固定。

## 3. 口径（冻结）

| 项 | 冻结值 |
|---|---|
| 主池 | 沪深普通 A 股母池（all.txt 历史在市，剔除 BJ/指数/B 股） |
| 数据 | `cn_data_2026` + `daily_basic_pit_v1` + `style_pit_v1` + `a_share_financial_pit_v1` |
| 过滤 | ST/*ST/退市（PIT）+ 停牌 + 涨停信号日 |
| 回测窗口 | 2022-01-01 ~ 2025-06-30（财务 PIT 上限；2025-06 后待财务更新，如实标注） |
| 策略 | TopkDropout topk=50 n_drop=5 日频，T+1 开盘成交，`limit_threshold=0.095`，`min_cost=5` |
| 基准 | SH000852 |
| 费率 | base: open 0.0005 / close 0.0015（主）；stress: open 0.0010 / close 0.0030（附录） |

## 4. 检验与报告

- 三版本 × base/stress：net/gross 超额、IR、最大回撤、日均换手、年化成本拖累、
  2024 net、分年度 net。
- 关键对照：enhanced vs main（偏度增强增量）、main vs domain_skew（基线 vs 纯量价）。
- 2025H1 单独列示（半年样本，如实标注）。

## 5. 预设判定

| 条件 | 判定 |
|---|---|
| main net IR ≥ 0.5 且 enhanced net IR ≥ 0.5 且 enhanced net 超额 > main | `enhanced_adopted` → 偏度增强采纳，日频基线 = enhanced |
| main net IR ≥ 0.5（增强不达标） | `main_baseline` → 日频基线 = main（纯基本面域），增强不采纳 |
| main net IR < 0.5 | `not_viable` → 日频基线不成立，收口 |

stress 与 2025H1 如实报告，不改变判定路径。

## 6. 产物与目录

```text
output/analysis_static/a_share_daily_strategy_v1/
  backtest_summary.csv       版本×费率 全期指标
  yearly_summary_*.csv       各版本分年度 net（base）
  daily_report_main_base.csv.gz  主版本 base 日度 report
  decision.json              预设判定
  methodology.json           口径快照
  validation_report.txt      中文报告
```

脚本：`scripts/backtest_a_share_daily_strategy_v1.py`（复用 domain_skew 骨架）。

## 7. 结论边界

本验证只确立日频策略基线（main/enhanced 选型）。实盘化（容量/流动性/滑点实测、
风控、cron 生产管道）属 ROADMAP 阶段 3+，另行立项。2025-06 后受财务 PIT 上限，
如实标注。

## 8. 变更记录

| 日期 | 变更 |
|---|---|
| 2026-08-13 | 创建：冻结 main/enhanced/对照 三版本 + 0.7/0.3 增强权重 + 三档判定 |
