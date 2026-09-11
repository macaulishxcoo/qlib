# Reversal 3 因子假设检验协议 v1（干净微盘域 + 全市场对照）

## 1. 状态与授权

状态：`frozen_awaiting_run`（2026-09-09）

前置链与先验（本族是九族里先验最重的一族）：
- tushare Reversal 族仅 3 个：small_cap_reversal_21d（小盘 21 日反转）、
  rsi（14 日 RSI）、price_dist（价格距整数关口距离）；
- **small_cap_reversal_21d 与本项目已验证内容几乎完全重合**：干净微盘域
  本身就是"市值最小的股票"（末10%），该因子 = 域内 21 日收益反转 =
  本轮 Momentum 轮 return_21d（IC -0.024，未过线）的域内限定版 + 
  enhance 已用的"反转哲学"。预期它就是 return_21d 的换肤，按协议跑但
  预标注 `likely_duplicate`；
- rsi：与 Momentum 轮 return 族、主升浪轮 TIGHTNESS/ROC 族同轴，短期
  反转口径；battery 轮"偏度/换手"已覆盖相邻信息；
- price_dist：股价距下一个整数价位的距离——**日内微观结构/散户挂单
  心理**（整数关口支撑/阻力），这个机制在本项目从未测过，是三因子中
  唯一真正的新信息候选；
- 九族扫描统一框架与前四族 closure（momentum20 最新）。

## 2. 因子集与复现（冻结）

| 因子 | 公式 | 实现 |
|---|---|---|
| small_cap_reversal_21d | Rank(-21日累计收益)（市值最小股票内的反转） | 域内即为小盘，实现为域内 -21 日收益的截面 rank（等价于文档"选市值最小+取收益反转"的域内版） |
| rsi | 14 日 RSI（Wilder 平滑） | 逐股 Wilder EMA |
| price_dist | 股价距下一整数（或 10 元）关口的归一化距离 | 文档公式：dist = (Close - floor(Close)) 归一；未复权价（整数关口效应只存在于名义价格上！）——**用未复权 close = qlib close/factor** |

**口径关键点**：price_dist 必须用**未复权价格**——散户看到的挂单价位
是名义价，后复权价（如 2.13）会破坏整数关口语义。这是本因子实现的
核心口径决定。

## 3. 双臂与判定（冻结，与前五族同框架）

- 臂B=干净微盘域（月末重建）、臂A=全市场（剔ST），月度持有、费前，
  2022-01~2026-08；
- 候选门槛：|IC 中位| ≥ 0.02 且价差 |t| ≥ 2 且分年 ≥4/5 →
  `reversal_domain_candidate`；符号不限（反转族预期负 IC：RSI 高=
  超买=跑输）；
- 冗余：与 Z1 |corr|≥0.60 → `z1_duplicate`；与 Momentum 轮 return_21d
  的关系单独对照（同一基础量）。

出口：
- 候选 = 0 → `reversal_no_domain_value`：反转轴已被 Momentum 轮覆盖，
  本族关闭（记录与 return 族的对照）；
- 有候选（尤其 price_dist）→ 新微观结构信息立项候选，并入 enhance
  池。

## 4. 产物

`output/analysis_static/reversal3_dual_arm_v1/`：全套与各族一致。

## 5. 风险预告（预注册的怀疑）

1. small_cap_reversal_21d ≈ return_21d 换肤（域内口径下二者构造几乎
   同一），预期 IC 差 <0.005；
2. rsi 与 return_21d 相关预计 >0.7（同为短期反转代理），大概率
   not_qualified 或 duplicate；
3. price_dist 是唯一的新机制，但其效应量在学术文献里偏小（散户挂单
   心理在月度尺度可能被稀释），预期 IC <0.02——若过线将是九族扫描
   里机制最新颖的发现；
4. 3 个因子结论外推性弱（样本=族内全部），报告以"轴闭合"为主。
