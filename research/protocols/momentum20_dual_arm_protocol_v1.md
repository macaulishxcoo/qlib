# Momentum 20 因子假设检验协议 v1（干净微盘域 + 全市场对照）

## 1. 状态与授权

状态：`frozen_awaiting_run`（2026-09-08）

前置链（本族的重先验，全部已归档）：
- `a_share_zsl_main_wave_factor_line_assessment_v1.md`：主升浪复验——
  动量/趋势类 ABOVE_MA60/MOM_20_5/SMOOTH_MOM 等 IC +0.03~0.04，但
  与 Alpha158 判 duplicate（|corr|>0.95）；TIGHTNESS 负 IC；2026 年
  趋势类全面衰减；
- `a_share_daily_alpha_exhaustion_manifest_v1.md` #2/#3：动量/趋势
  轴测尽，"唯一真差异化"的 UP_FROM_LOW_250 也已不再单独深验；
- 本项目多轮证据：A 股反转强于动量（事件线反复验证），月度持有下
  动量符号预期为**负**（与 Liquidity 轮换手率同向推理）；
- `market_survivors_progress_snapshot_v1.md`：进度快照（本实验纳入
  同一双臂框架）。

**先验声明**：Momentum 族 20 个因子里，return_{5,21,42,63,126,252}d
（6 个）与主升浪复验的 ROC/动量族同源；MACD/dif/dea（3 个）是趋势
指标的经典形态（Alpha158 的 MA 族的近亲）；alpha_*（7 个）是相对
指数的滚动回归截距（CAPM alpha，长窗口 125~1320 天）；rsrs（1 个）
是支撑阻力相对强度（斜率 z-score）；price_position_ir_60d（1 个）
是日内位置 IR；days_down_up（1 个）是连续涨跌天数。**预期：短窗口
动量（return_5d/21d）在月度口径下呈反转（负 IC，与 battery/liquidity
轮的持有期符号翻转一致）；长窗口（252d+）是真正未测区域**。

## 2. 因子集与复现（冻结）

20 个全部复现：

| 组 | 因子 | 实现 |
|---|---|---|
| M1 区间收益 | return_{5,21,42,63,126,252}d | (1+RET).rolling(w).prod()-1 |
| M2 趋势指标 | ma_20d（价格）、MACD、dif、dea | EMA 链，close 后复权 |
| M3 CAPM alpha | alpha_{125,250,500,1000}d_000300、alpha_{528,792,1320}d_000001 | 滚动 OLS 截距，对 sh000300/sz399300（可得的指数），日频收益 |
| M4 形态/位置 | price_position_ir_60d、rsrs、days_down_up | 按文档公式 |

- ma_20d 按文档是**价格本身**（非偏离率），rank 后等价于价格水平
  排名（高 价=高价股），预期与规模/价格水平混杂——照跑，解读时
  标注；
- rsrs：18 日 Low~High 回归斜率，200 日 z-score；斜率为正且大=
  支撑强于阻力；
- days_down_up：|连续涨天数-连续跌天数-1|，连续方向持续性强
  → 值大；
- 长窗口（alpha_1000d/1320d、return_252d）需 ≥4 年预热，实际样本
  从 2025 年起——**样本天然不足，单独标注降级**。

## 3. 双臂与口径（冻结）

与前几轮完全一致：臂B=干净微盘域（月末重建）、臂A=全市场（剔ST），
月度持有（月末-月末收益，费前），2022-01~2026-08（长窗口因子按
可用样本单独报告）。

## 4. 预注册判定（冻结）

与 growth15/liquidity35 同门槛：
- 域内月度 |RankIC 中位| ≥ 0.02 且 (Q4−Q1 或 Q5−Q1) 价差 |t| ≥ 2
  且分年同号 ≥4/5 → `momentum_domain_candidate`；
- **符号不限**（A 股月度口径预期反转/负 IC，负 IC 候选标注
  `reversal_dir`，与 liquidity 轮同处理）；
- 冗余归并：与 Z1 |corr|≥0.60 → 标 `z1_duplicate`（不作为独立
  增量）；组内 |corr|>0.90 只留 |IC| 最高者。

出口：
- 候选 = 0 → `momentum_no_domain_value`：动量轴在微盘域月度口径
  关闭（与主升浪线合并成完整闭环）；
- 有候选 → 与 Z1/pa/BIAS 一起进入三源（或 N 源）enhance 融合实验
  的候选池。

## 5. 产物

`output/analysis_static/momentum20_dual_arm_v1/`：
`ic_summary.csv`、`quintile_shape.csv`、`z1_correlation.csv`、
`corr_matrix.csv`、`decision_table.csv`、`decision.json`。

## 6. 风险预告（预注册的怀疑）

1. 短窗口 return 族月度口径大概率负 IC（反转），且与 Z1 的负相关
   可能达 -0.4~-0.6（Z1 本身含价格动量负向成分）——若 so，它们是
   Z1 的影子而非增量；
2. MACD/dif/dea 三者互相关预期 >0.95（同一指标的三个部件），归并后
   至多 1 个有效；
3. 长窗口 alpha 族（≥500d）样本 <2 年，结论只能"记录不判定"；
4. rsrs 在微盘域的涨跌停扭曲下（18 日 Low~High 回归被一字板压扁）
   可能失真，异常率需报告；
5. 全市场臂（日频/月度）继续只算 IC——补齐价差/组合回测仍在全局
   缺口清单（进度快照 §3），本轮不重复建设。
