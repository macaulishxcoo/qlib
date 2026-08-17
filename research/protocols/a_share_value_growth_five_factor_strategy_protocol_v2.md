# 价值/质量 + 成长五因子复合策略回测协议 v2

## 1. 状态与授权

状态：`frozen_awaiting_run`（2026-08-15）
前置链：
- `a_share_growth_factor_family_closure_v1.md`（g2/g3 单因子三段全过，
  与价值轴截面相关 -0.078）
- `a_share_growth_monthly_strategy_closure_v1.md` §5.3（独立成长策略
  不采纳，"g2 并入价值复合"为指定未测方向）

单一变量原则：与 v8 的唯一差异是 **composite_score 从四因子
（ep/bm/div_yield/accruals）扩为五因子（+g2_dedt_np_yoy）**，门槛
从 ≥3 改为 ≥4（等比例收紧，5 因子中至少 4 个非缺失）。其余全部
照抄 v8（ST/容量/中性化/top15/成本/执行）。

## 2. 信号定义（冻结）

- g2 = `dt_netprofit_yoy`（扣非净利同比，fina_indicator PIT，
  available_date <= rebalance_date，同 (ts_code,end_date) 取最新）
- `composite5 = mean(rank_pct(ep), rank_pct(bm), rank_pct(div_yield),
  rank_pct(accruals), rank_pct(g2))`，非缺失因子数 ≥ 4 才有效
- 门槛比例保持 4/5 = 80%，与 v8 的 3/4 = 75% 近似（不重调）
- g2 不做额外清洗（fina_indicator 原生 YoY，极端值由 rank 化吸收）

## 3. 管道（与 v8 逐项一致）

v8 全套：build_snapshot 四因子 + g2 合并 -> composite5（≥4 门槛）->
ST/退市过滤 -> 容量过滤（5% 参与率）-> 行业+log_size 中性化 ->
top-15 等权月度换仓 -> T+1 开盘、涨跌停 9.5%、base/stress 成本。

## 4. 预设判定（冻结）

主判定（与 v8 同门槛）：
- 封存期（2023-01~2025-06）stress 费后超额 > 0 且 IR > 0
  -> `five_factor_viable`

采纳判定（比 viable 更严，防"换皮"）：
- 封存期 IR > v8 的 0.92 -> `improved`
- 或全期 net IR > v8 的 0.61 且新覆盖段超额 > v8 的 -35.0%
  -> `regime_robust_improved`

对照出口：
- 两条件都不满足 -> `no_improvement_closed`，成长并入路线关闭，
  v8 四因子维持实盘基线
- 不授权调优：不试 g3 并入、不试权重（等权固定）、不试门槛其他值

## 5. 产物

`output/analysis_fundamental/a_share_value_growth_five_factor_strategy_v2/`：
`backtest_summary.csv`、`yearly_summary.csv`、
`monthly_composite_top15.csv.gz`、`decision.json`、`methodology.json`

## 6. 风险预告（预注册的怀疑）

g2 与四因子截面相关 -0.078，加入后复合分被"稀释"价值轴纯度。
若 2023-2025 价值顺风期复合分变弱（IR 下降），恰说明 g2 的贡献
主要在成长牛段；本实验真正要测的是"全期稳健性提升"而非封存期
单段提升。
