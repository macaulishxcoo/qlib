# A 股成长因子族 staged 验证协议 v1

## 1. 状态与授权

状态：`frozen_awaiting_run`（2026-08-15）
选题：`research/decisions/a_share_growth_factor_family_proposal_v1.md`
（8 候选 + 1 对照，门槛预注册）。本协议冻结实验参数，跑完即出判定，
不做参数扫描、不做窗口调优。

## 2. 数据

- `fina_indicator`（顶层合并 + full batches 去重）：`or_yoy`、
  `dt_netprofit_yoy`、`q_sales_yoy`，PIT 按 `available_date <= rebalance_date`
  对齐，同 `(ts_code, end_date)` 取最新 available
- `income`（full batches）：`rd_exp`、`revenue` -> 研发强度
  （2025Q1 后缺失，按可得样本评估，样本 < 100/月记 invalid）
- `monthly_stock_classification_v2`：申万 L1、`total_mv`（log_size）、
  `free_float_mv_percentile`（size_control）、`turnover_rate_percentile`、
  `risk_status`（剔 ST/退市整理）
- 标签：open-to-open，H ∈ {20, 40, 60}，qlib `$open`

## 3. 因子定义（与 proposal 一致）

| 名 | 构造 |
|---|---|
| g0_tech_dummy | L1 ∈ {801080 电子, 801750 计算机, 801770 通信}，只算 raw IC（对照） |
| g1_rev_yoy | or_yoy |
| g2_dedt_np_yoy | dt_netprofit_yoy |
| g3_q_rev_yoy | q_sales_yoy |
| g4_rd_intensity | rd_exp/revenue，截断 (0,1] |
| g5_np_accel | dt_netprofit_yoy(最新) − dt_netprofit_yoy(上一报告期) |
| g6_rev_stability | −std(or_yoy, 近 8 报告期, ≥6 非空) |
| g7_rev_x_turnover | or_yoy 截面 pct-rank × turnover_rate_percentile |
| g8_tech_growth | 科技域内 or_yoy pct-rank（域外 NaN，域内样本 ≥100 才有效） |

中性化：log_size + 申万 L1 哑变量（与 v8 同轴）。
g8 在域内截面上做完整中性化（域内行业细分后哑变量可能退化，按实际
秩取残差）。g0 不做中性化。

## 4. 阶段与门槛（预注册）

| 阶段 | 窗口 | 通过条件（40 日中性 RankIC） |
|---|---|---|
| development | 2014-01 ~ 2019-12 | IC > 0.01 且 ICIR ≥ 0.20 且 20d/60d IC 同号为正 |
| confirmation | 2020-01 ~ 2022-12 | IC > 0.01 |
| holdout | 2023-01 ~ 2025-05 | IC > 0 |

- 月度样本 < 100 只记 invalid，不进 IC
- 剔除申万 L1 银行(801780)/非银(801790)、risk_status ∈ {st, delist_phase}

## 5. 产物

`output/analysis_fundamental/a_share_growth_factor_family_v1/`：
`monthly_signal_label_panel.csv.gz`、`monthly_rank_ic.csv.gz`、
`rank_ic_summary.csv`、`group_return_summary.csv`、
`sample_coverage_summary.csv`、`decision.json`、`methodology.json`、
`validation_report.txt`

## 6. 判定出口

- 任一因子三段全通过 -> 进入第二轮：与 v8 composite 的月度截面
  Spearman 相关（|ρ|>0.5 淘汰；0.3~0.5 组合层验证；<0.3 独立候选）
- A/B 组全灭且 g8 也灭 -> 成长族关闭，业绩预告增速转事件族立项
- g0 显著为正而 g8 不显著 -> "科技行业效应存在但域内成长选股无效"，
  科技暴露归行业配置问题，不属于因子研究范畴
