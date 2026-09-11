# Quality 59 因子假设检验协议 v1（干净微盘域 + 全市场对照）

## 1. 状态与授权

状态：`frozen_awaiting_run`（2026-09-09）

前置链：
- tushare 因子族扫描进度：Alpha101(31)→Growth(15)→Liquidity(35)→
  Momentum(20) 全部完成（见 `market_survivors_progress_snapshot_v1.md`
  与各 closure），Quality(59) 是第五族；
- 主线资产：五因子（ep/bm/div/accruals/g2）中 accruals、g2 与质量/成长
  轴同源；本族的增量问题是"质量维度是否有 g2/accruals 之外的域内增量"；
- 数据基础（本日核查）：
  `balancesheet_v1/normalized/batch_*/`（54 批 × 160 列，含 inventories、
  fix_assets、defer_tax_assets、total_cur_assets/liab、accounts_receiv、
  adv_receipts 等）+ `fina_indicator`（116 列，含 roe/roa/eps/gross_margin/
  netprofit_margin/current_ratio/quick_ratio/cash_ratio/debt_to_assets/
  profit_to_op/ebit/ebitda/fixed_assets）+ income 全列（oper_cost、
  sell_exp、admin_exp、fin_exp、operate_profit、total_profit、total_revenue）。

## 2. 因子集与映射（冻结）

59 个因子按原料归并为 8 组。映射到本项目数据的实现：

| 组 | 数量 | 因子 | 原料来源 |
|---|---|---|---|
| Q1 盈利水平 | 12 | roe_ttm/roe_y、roa_ttm/roa_y/roa_q、eps_ttm/eps_q/eps_y、npm_q/y/ttm、opm_y/ttm、gpm_q/y/ttm、opt_tpro | fina_indicator（roe/roa/eps/gross_margin/netprofit_margin）+ income（operate_profit/total_profit） |
| Q2 盈利质量/现金 | 4 | cash_profit_ratio、quality_composite、cfcr、icr | income+cashflow+fin_exp（icr 需利息支出：fin_exp 代理） |
| Q3 偿债/流动性 | 6 | debt_asset_ratio、de、market_value_leverage、quick_ratio、cash_ratio、current_ratio | fina_indicator + balancesheet |
| Q4 营运效率 | 6 | asset_turnover、fixed_asset_turnover、equity_turnover、inventory_turnover、receivable_turnover、opt_tpro | income（total_revenue/oper_cost）+ balancesheet |
| Q5 同比变化 delta_* | 11 | delta_{current_ratio,de,gpm,npm,opm,roe,roa,asset_turnover,quick_ratio,cash_ratio,inventory_turnover} | 上述各项 TTM 同比差 |
| Q6 单位产出同比 | 6 | income_tax_yoy、np_to_inventory_yoy、np_to_total_expenses_yoy、np_to_deferred_tax_yoy、np_to_salary_yoy、lra_yoy、expenses_to_equity_yoy | income+balancesheet（np_to_salary_yoy：staff 数据缺失→用 admin_exp 代理并标注） |
| Q7 变化率 qoq | 3 | gpm_qoq、npm_q_qoq、npm_ttm_qoq | fina_indicator 环比 |
| Q8 其他 | 1 | npm_tsh（平均权益口径净利率） | income+balancesheet |

**明确放弃（数据不可得，预注册 3 个）**：staff_behalf_paid（现金流量表
未含该列）→ np_to_salary_yoy 用 admin_exp 代理降级；其余 58 个可全量
实现。icr 的 interest_expense 用 fin_exp 代理（含手续费，偏差已标注）。

## 3. 双臂与口径（冻结）

与前四族完全一致：臂B=干净微盘域（月末重建）、臂A=全市场（剔ST），
月度持有、月末-月末收益（费前），2022-01~2026-08。全部因子 PIT
（available_date ≤ 观察日）。

## 4. 预注册判定（冻结）

与 growth15/liquidity35/momentum20 同门槛：
- 域内月度 |RankIC 中位| ≥ 0.02 且 (Q4−Q1 或 Q5−Q1) |t| ≥ 2 且分年
  同号 ≥4/5 → `quality_domain_candidate`（负 IC 标 reversal_dir）；
- 冗余归并：与 g2 |corr|≥0.60 → `g2_duplicate`（主线已有）；与 Z1
  |corr|≥0.60 → `z1_duplicate`；组内 |corr|>0.90 只留 |IC| 最高者；
- **Q1 盈利水平组与主线 ep/bm 的关系单列**：ep/bm 是"价格调整后"
  的盈利（盈利/市值），Q1 是"未调价"的盈利能力——两者高相关但
  不同轴，判定以与 g2/accruals 的相关为准，与 ep 的相关只记录。

出口：
- 候选 = 0 → `quality_no_domain_value`：质量轴域内无独立增量，主线
  accruals/g2 已覆盖，本族关闭；
- 有候选 → 并入 enhance 融合候选池（现 5 源）。

## 5. 产物

`output/analysis_static/quality59_dual_arm_v1/`：
`ic_summary.csv`、`quintile_shape.csv`、`g2_z1_correlation.csv`、
`corr_matrix.csv`、`decision_table.csv`、`decision.json`。

## 6. 风险预告（预注册的怀疑）

1. **59 个因子的高冗余**：npm_q/y/ttm/tsh、gpm_q/y/ttm、roe/roa 多
   口径等是同一指标的换肤，预计归并后独立信号 ≤8 个；
2. 微盘域内"质量溢价"存疑：质量因子在 A 股整体有效但集中于中大盘
   （机构定价），微盘散户对 ROE/毛利率的截面差异定价不足——预期
   域内 IC 弱于全市场（与 pa 的域内增强相反）；
3. delta_* 组（11 个）是"质量改善方向"，与 pa（盈利加速度）同族，
   预计与 pa 相关 0.3~0.5，融合时可能与 pa 二选一；
4. icr/cfcr 的利息支出代理（fin_exp）在零杠杆微盘股上分母趋 0 会
   产生极端值，rank 化前需按分位截尾（预注册：±3 MAD 截尾）；
5. quality_composite（AQR 6 项合成）公式中两个分母含现金流项，
   现金流量表仅有 n_cashflow_act，投资现金流（InvCashInflow）缺失
   → 该因子按"可用 4 项合成"降级实现并标注。
