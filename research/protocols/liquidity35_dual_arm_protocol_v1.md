# Liquidity 35 因子假设检验协议 v1（干净微盘域 + 全市场对照）

## 1. 状态与授权

状态：`frozen_awaiting_run`（2026-09-05）

前置链：
- `a_share_price_volume_factor_battery_closure_v1.md`：换手率**水平**
  IC +0.064 但 top50 组合年化 -0.49（"IC 正 ≠ 可交易"首例）；
- `a_share_price_volume_factor_neutralization_closure_v1.md`：换手率
  水平/偏度 MVI 后 ICIR 反升、25 格全正——真 alpha 非 risk 暴露；
- `a_share_price_volume_factor_orthogonality_closure_v1.md`：与主线正交
  （|corr|<0.11）但**短周期信号**（h=40 反转），不能并入月频主线；
- `growth15_dual_arm_closure_v1.md`：Growth 族检验完成，pa 唯一存活。

**先验声明（预注册的强怀疑）**：Liquidity 族 35 个因子里约 33 个是
**换手率的函数**（MA/STD/BIAS/短长比值），与已闭环的"换手率水平"
信号是同族变体。本实验的增量问题只有一个：**换手率族在"干净微盘域 +
月度持有"口径下是否有独立信息**——此前检验是全市场 + 日频/短持有期
口径。已知证据（水平因子组合层 dead、h=40 反转）倾向于否定，但域内
+月度口径从未测过，按协议补齐这一格。

## 2. 因子集与复现（冻结）

35 个因子全部复现，按结构分 4 组：

| 组 | 数量 | 因子 | 原料 |
|---|---|---|---|
| L1 换手率水平 MA | 8 | avg_turnover_{5,10,20,21,42,63,126,252}d | volume/总股本（daily_basic total_share 月末 + qlib volume） |
| L2 换手率波动 STD | 7 | std_turnover_{21,42,63,126,252}d | 同上 |
| L3 乖离 BIAS | 16 | bias_{turn,std_turn}_{21,42,63,126}d_{252,504}d | 同上 |
| L4 其他 | 4 | amount_ma_20d、sum_abs_rtn_amount_20d、turnover_ma_20d(±long)、volume_alpha_300d_{000001,000300} | 成交额（校准口径 (close/factor)×vol×100）、指数 volume（sh000300/sz399300 近似） |

实现口径：
- DailyTurnoverRate = 当日成交量(手×100) / 总股本(万股×1e4)——用月末
  total_share 近似（月内股本变动忽略，误差 <1%）；
- turnover_ma 系列用流通市值口径（float_share），float 数据用月末
  float_share（daily_basic）；
- amount 用校准成交额（q4 轮已验证 (close/factor)×vol×100，与 tushare
  误差 <3%）；
- volume_alpha：个股 5 日量和对上证指数 5 日量动量 300 日滚动 OLS 的
  alpha（指数用 sz399300/ sh000300 可得者）。

**去重声明**：L1/L2/L3 的 31 个因子是同一基础序列（换手率）的窗口
变换，预计互相关极高。检验照跑（尊重"全部复现"的指示），但结论按
**结构组**归并解读，避免把同族重复当作多个证据。

## 3. 双臂与口径（冻结）

- 臂B（主）：干净微盘域（月末重建，与前几轮完全一致），**月度**调仓
  口径分组 + 月末截面 RankIC；
- 臂A（对照）：全市场（沪深三板块剔 ST/退市），同频率；
- 样本窗：2022-01 ~ 2026-08，预热自 2024-08（504 日 BIAS 需要更长
  预热，实际从 2024-08 起对 504 类报告、2022-01 起对其余）；
- 标签：月末到月末收益（费前），与 growth15 轮一致。

## 4. 预注册判定（冻结）

主判定（域内月度口径）：
- |IC 中位| ≥ 0.02 且 (Q4−Q1 或 Q5−Q1) 价差 t ≥ 2 且分年同号 ≥4/5
  → `liquidity_domain_candidate`（与 growth15 同门槛）；
- 已知换手率水平方向的**符号预期**：A 股"高换手 → 低收益"（负 IC），
  候选判定不限符号但报告符号，负 IC 的候选标注 `reversal_direction`。

附加判定（仅对候选）：
- 与 Z1 相关 <0.60 → `incremental_over_z1`（量价主线增量）；
- 冗余归并：组内 |corr|>0.90 的因子视为同一信号，只保留 IC 最高者
  进入候选清单（防同族重复计数）。

出口：
- 候选数 = 0 → `liquidity_no_domain_value`：换手率族在微盘域月度口径
  无增量——与 battery/orthogonality 轮结论合并成完整闭环（三种口径
  全灭），量价-换手轴彻底关闭；
- 有候选且 incremental → 进入 Z1+候选的 enhance 融合实验（与 pa 同批）。

## 5. 产物

`output/analysis_static/liquidity35_dual_arm_v1/`：
`ic_summary.csv`、`corr_matrix.csv`、`quintile_shape.csv`、
`z1_correlation.csv`、`decision_table.csv`、`decision.json`。

## 6. 风险预告（预注册的怀疑）

1. **同族重复**：31/35 是换手率变换，通过门槛的若 >1 个大概率同源，
   归并后真实候选数预计 0~2；
2. 换手率水平在微盘域的既有证据是"IC 正但组合 dead"（battery 轮）——
   本轮月度持有 + 分组价差口径若依然过线，需警惕与 battery 轮口径差
   （日频 top50 vs 月度等权分组）带来的表面分歧，结论表述必须带口径；
3. BIAS 类（短长比值）数学上是换手率的"动量"，可能与 Z1（量价协方差）
   相关中等（0.4~0.6），增量判定用 0.60 阈值；
4. 504 日窗口在 2022 起点样本下只有 ~2.5 年可用样本，该组结论天然
   降级。
