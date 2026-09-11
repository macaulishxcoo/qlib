# 沪深主板末20% enhance 构造组合回测协议 v1

## 1. 状态与授权

状态：`frozen_awaiting_run`（2026-09-08）

前置链：
- `mainboard_bottom20_dual_arm_closure_v1.md`：Z1 倒U形状在主板末20%清洁域
  完全转移且更强（Q4−Q1 月均 +1.55%，t=4.11，5/5 年为正）；纯新增子集
  B_new 同向等强（排除旧样本复用）；pa 同呈倒U（Q4−Q1 +0.92%，t=3.62）；
  `bias_std_turn_21d_252d` 单调下行（Q5−Q1 −0.97%，t=−2.53，5/5 年）；
- `clean_microcap_q4_closure_v2.md`：旧微盘域同款构造——enhance +2.0pp
  （marginal）、q4 分位臂被微盘摩擦吃掉（base +6.4pp → microcap −0.4pp）；
- 三信号域内互相关 ≤0.22（Z1/pa/BIAS），正交。

**本实验测的唯一问题**：把旧微盘域的 enhance 构造搬到更宽、更流动、
纯 ±10% 限的主板末 20% 域，并融合三源正交信号，能否把分层层的价差
在**费后**转化为 ≥+3pp 的年化净超额（旧域只做到 +2.0pp）。

## 2. 信号（冻结）

域内月末截面 rank 后等权融合（三源正交，各 1/3）：
- Z1 合成（6 族等权 rank 均值，与分层检验同构造）；
- pa（ROA 同比变化，growth15 面板，取最新报告期）；
- bias_std_turn_21d_252d（换手波动短长比，reversal 方向，取负号后融合）。

融合信号 `FUSE = (rank(Z1) + rank(pa) + rank(-bias)) / 3`。

## 3. 臂设计（冻结，单变量原则）

| 臂 | 规则 | 检验点 |
|---|---|---|
| **enhance_fuse** | 全池持有，权重 = 等权 × (1 + 0.5×(rank_pct(FUSE) − 0.5))，归一 | 主臂：三源增强 |
| **enhance_z1** | 同上但仅 Z1 | 旧域构造的直接搬移（对照） |
| **q4_fuse** | FUSE 分数 60~80 分位带全部股票 | 形状直接指定（分层结论） |
| **pool_ew** | 全池等权（对照） | 基线 |

## 4. 执行与成本（冻结）

- T 月末收盘分组 → T+1 开盘等权成交，持有至下月末；
- 成本三档：base 0.15% / stress 0.40% / microcap 0.80% 单边（沿 q4 协议）；
- 窗口 2022-01 ~ 2026-08；崩盘段 2024-01~02 单列。

## 5. 预注册判定（冻结）

主判定（microcap 成本，vs pool_ew）：
- 任一 enhance/q4 臂年化净超额 ≥ +3pp 且 IR ≥ 0.5 → `mainboard20_construction_works`
  （采纳，进入模拟盘评估）；
- 超额在 (0, +3pp) → `mainboard20_marginal`（薄增量，保留观察）；
- 全部 ≤ 0 → `mainboard20_construction_dead`（新域构造关闭）。

附加观察（不设门槛）：enhance_fuse vs enhance_z1 的融合增量；q4_fuse vs
enhance 的构造优劣；换手率；崩盘段回撤。

## 6. 产物

`output/analysis_fundamental/mainboard20_enhance_v1/`：
`backtest_summary.csv`、`nav_*.csv`、`crash_2024.csv`、`decision_excess.csv`、`decision.json`。

## 7. 风险预告（预注册的怀疑）

1. **Q1 端驱动**：分层价差主要来自 Q1 更弱（新域 Q1 0.88% vs 旧域 1.61%），
   只做多头的 enhance 权重下行（超配高分、低配低分）可能只能兑现部分价差
   ——若费后 <+3pp，是"空头端不可交易"的真实体现，不是运气；
2. **融合稀释**：三源等权可能被较弱源（pa IC 仅 0.023）稀释 Z1 的强度，
   enhance_fuse 可能不优于 enhance_z1——这是融合增量的一次性对照；
3. **新域更流动**：中位市值 23.9 亿、换手 2%，微盘摩擦小于旧域，理论上
   q4_fuse 的生存概率高于旧域 q4_band（旧域 microcap 口径归零）；
4. 月度调仓形态，月内信号不更新（与前几轮一致）。

## 8. 变更记录

| 日期 | 变更 |
|---|---|
| 2026-09-08 | 创建并冻结：三源融合 enhance 在主板末20%域，4 臂×3 成本，判定沿 q4 协议 |
