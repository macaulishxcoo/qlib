# 日频策略探索开发日志

> 创建日期：2026-08-14  
> 方向定位：**独立方向 = 寻找可交易的日频策略**（区别于月度价值策略线的保持/优化）。
> 月度策略线（价值/质量四因子月频换手 + 20% 仓位模拟盘）保持现状并持续优化，**属后续工作，
> 不在本日志范围内推进**。本日志只记录日频方向的探索、发现与候选。
> 用户指示（2026-08-14）："月度策略我会保持和优化……但是现在想找到一个日频的策略，
> 现在做的不是在之前的基础上再优化"——本方向与月度线解耦。

---

## 1. 方向现状（一句话）

**A 股日频 alpha 在"横截面因子"形态下已测尽（`a_share_daily_alpha_exhaustion_manifest_v1.md`），
本方向换视角重开：从"为什么涨"转向"为什么跌"（反向视角），并换策略形态（事件窗口、
日频事件驱动），首条已验证的子线是"负面事件分类型研究"（T5 跌幅上榜信号）。

## 2. 已闭环子线：负面事件分类型研究（2026-08-13 ~ 08-14）

### 2.1 结论速览

- 事件层（2022-01 ~ 2026-07，市场调整超额 h=20）：**类型间行为显著不同**
  （ANOVA F=99.9, p<0.0001）——"利空出尽"不是普遍规律：
  | 类型 | 含义 | h=20 超额 | t | 判定 |
  |---|---|---|---|---|
  | T1 经营类（预亏/预减） | 经营下行 | **+0.47%** | +3.21 | 利空出尽 |
  | T2 制度类（ST 戴帽） | 制度风险 | **−4.53%** | −3.07 | 负漂移 |
  | T3 资金类（减持） | 主力撤离 | +0.53% | +5.23 | 利空出尽 |
  | T4 资金类（解禁） | 供给冲击 | +1.07% | +7.55 | 动量代理 |
  | **T5 交易类（跌幅上榜）** | 恐慌/放量下跌 | **−1.87%** | −13.09 | **负漂移** |
- 组合层（月度 v8 top15 基线 + T5 剔除层）：holdout +0.74pp、**new_coverage +20.33pp**
  → T5 剔除层 adopted。**但这是月度线视角的验证**；T5 的日频潜力见 §3。
- 证据：`research/decisions/a_share_negative_event_subtype_{proposal,closure}_v1.md`、
  `research/protocols/a_share_negative_event_subtype_protocol_v1.md`、
  `output/analysis_static/a_share_negative_event_subtype_v1/`、
  `output/analysis_fundamental/a_share_value_quality_monthly_strategy_v12_negative_event_filter/`。

### 2.2 关键资产（勿弃）

- **T5 跌幅上榜事件源**：`top_list.reason` 含"跌幅/负向"（2022-2026，约 3.2 万事件，
  数据 `a_share_events_daily_v1/`，日更可用）；
- **业绩预告**：`a_share_forecast_v1/`（2022-2026，21,142 条，tushare `forecast`
  个人权限✅，下载脚本 `scripts/data_collector/download_a_share_forecast_v1.py`）；
- **事件分析管线**：`scripts/analyze_a_share_negative_event_subtype_v1.py`
  （正确 open-to-open 标签 + 动量正交化 + 组间检验，可复用为日频事件研究的骨架）。

### 2.3 重要技术纠错（影响既有结论，待复核）

本线发现并修正了既有事件脚本的**标签方向 bug**：
- 错误公式 `FWD_h = open[t+1]/close[t+h+1]−1` ≈ 1/(1+r)−1 ≈ **−r**（与正确收益
  corr=−0.93）——事件后超额的方向结论完全反转；
- 影响面：`analyze_a_share_events_daily_v1.py`（事件流）、
  `analyze_a_share_trend_persistence_v1.py`（TS_UP60 标签）及继承者；
- 本线采用正确口径 `open[t+1+h]/open[t+1]−1`；
- **复核清单**：见 §6。已关闭实验（事件流 not_supported、趋势 T1 显著等）的方向性
  结论可能因此需要重估——但因其余结论（动量代理、正交性）基于同一批数据内部比较，
  部分仍成立，逐条复核后再定。

---

## 3. T5 的日频策略潜力（本方向下一步的核心候选）

T5（跌幅上榜）是**日频事件源**，事件层负漂移显著（−1.87%/20d, t=−13.09），
但个股做空不可行 → 不能直接做空。日频可交易形态的候选：

| 候选形态 | 机制 | 状态 |
|---|---|---|
| **A. 超跌组反转（T5 ∩ 前期跌透）** | 动量正交化显示 T5 Q1（前 20 日最弱）20 日 **+5.47%**，Q2-Q5 继续跌——"跌透的上榜股反弹，相对强的上榜股续跌" | 待立项（事件窗口内部分组，日频入场） |
| **B. 日频回避/风控层** | T5 负漂移股作为日频组合的剔除层（对日频多头组合而非月频名单） | 待立项（需先有日频多头组合） |
| **C. 恐慌买入（全市场恐慌期）** | 市场宽度/恐慌识别后，T5 类超跌股批量反弹 | 与方向 C 择时耦合，从紧立项 |
| **D. 涨停板/连板行为（制度摩擦）** | top_list reason 已有"涨幅偏离/连板"类（非跌幅），T+1 开盘行为 | 未立项（reason 文本已有，零下载） |

**注意**：候选 A 的本质是反转，与已关闭的"日频反转 S1"（负 IC）和"换手率/偏度
日频回测 dead"同族——立项时必须直接过"扣成本真实调仓回测"这一关（`metrics_judgment_standard.md`），
不能只看 IC。T5 的边际价值在于**事件条件**（放量大跌上榜 = 情绪极端），
可能比裸反转因子更聚焦。

---

## 4. 与月度策略线的关系（明确解耦）

| 项 | 月度策略线（后续工作） | 日频探索线（当前） |
|---|---|---|
| 目标 | 保持 + 优化（价值/质量四因子、20% 仓位模拟盘） | **找到可交易的日频策略** |
| 策略形态 | 月频调仓、top15、低换手 | 日频事件驱动（待定型） |
| 共享资产 | 数据（cn_data_2026、财务 PIT、事件、forecast） | 同左 |
| 治理 | v11/T5 剔除层是否并入实盘名单 = **月度线决策**，不阻塞日频线 | 独立立项、独立验收 |

**T5 剔除层并入月度名单**（v12 adopted）属月度线决策，用户可随时决定；本日志
不把它当作日频线的任务。

---

## 4.1 已闭环：正面事件分类型研究（2026-08-17）

镜像负面事件分类型（T 系列）的**正半边**检验："利好兑现（见光死）是否 A 股全市场
成立"（来源：智谱 HK2513 发布 GLM-5.3 利好股价连跌的单票观察）。**裁剪版**执行：
事件层只做 P1/P2（P3 引用 labelfix），组合层做"利好兑现剔除层"。

| 类型 | 事件层 | 组合层 |
|---|---|---|
| P1 经营类-正面预告（预增/略增/扭亏/续盈） | h=20 无效应（not_supported）；**h=40 +1.02% t=5.72 延迟正漂移观察** | 未合格（审计臂 +1.27pp 中性） |
| P2 资金类-增持（IN） | h=20 +0.76% t=4.50 显著正，但**动量严格单调（Q1 弱股 +2.55% → Q5 +0.14%）= 弱股反转代理** | 未合格（审计臂 new_coverage +8.17pp 观察——池内样本为"护盘式增持"下跌股） |
| P3 交易类-涨幅上榜（引用 labelfix） | 龙虎榜全部 −2.85%/20d（注意力反转） | **holdout +1.14pp 通过，但 new_coverage −11.79pp 恶化 → 不采纳** |

**核心结论**：`positive_event_subtype_not_adopted`。① 公告类正面事件（预告/增持）
无"利好兑现"负漂移——智谱式下跌不是 A 股制度性规律，更可能是**估值高位+供给
压力（解禁/配售）+预期透支**的个股特例；② 交易类上榜的注意力反转（事件层成立）
在 2026 弱市组合层被"强者恒强"覆盖（剔除逆势强势股反而更差）——**事件层负漂移
≠ 组合层剔除有效**（T5 教训的镜像）；③ 记录两项观察候选：P1 h=40 预告延迟漂移、
P2 组合层审计臂。证据：`research/decisions/a_share_positive_event_subtype_{proposal,
closure}_v1.md`、`research/protocols/a_share_positive_event_subtype_protocol_v1.md`、
`scripts/analyze_a_share_positive_event_subtype_v1.py`、
`scripts/backtest_a_share_value_quality_monthly_positive_event_filter_v16.py`、
`output/analysis_static/a_share_positive_event_subtype_v1/`、
`output/analysis_fundamental/a_share_value_quality_monthly_strategy_v16_positive_event_filter/`。

---

## 5. 日频方向的下一步候选（均未立项，走三问门槛 + 五项评审）

1. **T5 事件日频策略立项**：§3 候选 A/B 的最小实验设计（事件条件反转 vs 裸反转的
   扣成本对比）；
2. **指数调整效应**（`research/decisions/a_share_index_adjustment_effect_proposal_v1.md`，
   pending，数据已入库从未研究，规则化资金流事件）；
3. **融券余量信号**（`margin_pit_v1` 的 rqye/rqyl/rqmcl，已入库从未消费，
   "空头在定价坏消息"的直接度量）；
4. ~~市场宽度/恐慌识别~~（**已测并关闭**：方向 C 三个候选全部不达标，见
   `research/decisions/direction_c_closure_v1.md`——breadth IC≈0、margin_chg IC=−0.018、
   北向资金 IC 正负翻转；结论"风控不靠择时"。**不再立项**）
5. **行业内相对恶化/行业轮动**（财务 + 申万行业已有，状态型/轮动型两种形态）。

---

## 6. 复核清单（标签 bug 影响面）

| 脚本 | 影响 | 复核动作 |
|---|---|---|
| `analyze_a_share_events_daily_v1.py` | 事件后超额方向反转 | 用正确标签重跑，重判 not_supported |
| `analyze_a_share_trend_persistence_v1.py` | TS_UP60 标签方向反转 | 重跑 T1-T4，重判系统性暴露结论 |
| `analyze_a_share_pead_v1.py` | 已用 open_wide 正确口径（entry/exit open），**无 bug** | 免复核 |
| 其他继承 FWD 公式的脚本 | 逐 grep `shift(-(h+1))` 排查 | 见下 |

```bash
# 排查命令（工作目录 /home/xiaocong/worksapces/qlib）
grep -rn "shift(-(h + 1))\|shift(-(h+1))" scripts/ --include="*.py"
```

---

## 7. 变更记录

| 日期 | 变更 |
|---|---|
| 2026-08-14 | 创建：日频策略探索方向日志（与月度线解耦）；记录负面事件分类型研究闭环（T5 负漂移 + 超跌组反转异质性）、forecast 数据资产、标签 bug 复核清单、日频候选 A-D |
| 2026-08-14 | 更新：标签 bug 复核完成（事件流方向反转：龙虎榜负漂移注意力反转；趋势持续性 supported→not_supported，见 `event_label_bug_recheck_closure_v1.md`）；**候选 A（T5 事件日频策略）一轮最小实验执行完毕 → `t5_daily_not_adopted`**（事件层 Q1 +4%/20d t=9.07 但 2/4 年同向；组合层 Q1 −8.6%/yr 优于裸反转 −18.9%/yr 但均不可交易，见 `a_share_t5_daily_strategy_closure_v1.md`）。日频线候选 A 收口，下一候选：指数调整 / 融券余量 / 涨幅类上榜 |
| 2026-08-14 | 更新：**指数调整效应一轮实验完成 → `index_adjustment_effect_not_supported`**（纳入组 H=40 −1.14% t=−4.42 显著为负，方向与"被动买压"假设相反；剔除组 +0.92% 利空出尽；4 指数全负、1/3 时间段同向，见 `a_share_index_adjustment_closure_v1.md`）。机制：快照滞后生效日、买盘已透支 + 纳入=追高 → 均值回归。**日频线累计结论：反转市特征贯穿所有事件形态**（龙虎榜、T5、指数纳入、趋势状态）。下一候选：融券余量信号（margin_pit_v1 未消费）/ 市场宽度恐慌 / 涨幅类上榜 |
| 2026-08-17 | 更新：**正面事件分类型研究闭环 → `positive_event_subtype_not_adopted`**（见 §4.1）；DEV_LOG §5 候选"市场宽度/恐慌识别"标记为已测（direction_c 已闭环，不再立项） |
