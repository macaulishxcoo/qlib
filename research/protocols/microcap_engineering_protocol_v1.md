# 微盘引擎风险工程协议 v1（MDD 控制 + 可执行性截断）

## 1. 状态与授权

状态：`frozen_awaiting_run`（2026-09-12）

前置链：
- `clean_microcap_fusion_closure_v1.md`：融合 enhance 费后 +24.1%/
  IR 0.89/MDD −30.3%，被用户以"信号超额占比低 + MDD 过深"否决；
- `market_survivors_closure_v1.md`：全市场路线判
  scale_beta_disguised 后，研究重心回归微盘引擎的**工程化交付**；
- 用户已确认方向：把 2~5pp 纯 α 定位为叠加项，先修复引擎的两个
  工程缺陷（回撤、可执行性）。

**本协议的两个实验**：
- 实验一（风险工程）：机械状态变量触发减仓，目标 MDD ≤ −20% 且
  年化保留 ≥ 18%（费后 0.8% microcap 成本档）；
- 实验二（可执行性）：enhance 权重截断到 top-N（N=100/150），
  目标保留信号超额 ≥ 70%（对照全池 enhance 的超额 vs pool_ew）。

## 2. 状态变量（冻结，只许用域外可观测数据，防内生性）

用微盘池自身价格会引入内生性（池子跌 = 持仓跌，减仓永远滞后），
状态变量只用**全市场/指数层**：

| 变量 | 定义 | 危机机制 |
|---|---|---|
| V1 drawdown | 基准等权微盘指数（域等权日收益累计）20 日回撤 | 流动性危机的自我强化段 |
| V2 amount_ratio | 域内总成交额 20 日 MA ÷ 250 日 MA | 流动性枯竭先兆（雪球/两融敲入连锁） |
| V3 style_gap | 主板末20%域等权 ÷ 微盘域等权，20 日收益差 | 风格切换观测（资金逃离微盘去了主板低价） |

**先验声明**：2024-01/02 的机制是雪球敲入 + 两融平仓 + 量化 DMA
去杠杆的连锁——V2（成交额萎缩）应先行，V1（回撤）确认，V3 提供风格
切换目的地。预期 V2 最及时。**不预设哪个变量能过门槛**。

减仓规则（机械，无参数搜索）：状态触发日收盘判断 → T+1 开盘执行
→ 权重 = 0.5×enhance + 0.5×cash（半仓）；状态解除连续 5 个交易日后
恢复全仓。**单一变量独立触发，不叠加**（每个变量一个臂）。

## 3. 实验一臂（冻结）

| 臂 | 规则 |
|---|---|
| base_enhance | 无减仓（基准，复现 fusion closure 数字） |
| v1_dd_half | V1 < −8%（20 日回撤破 −8%）触发半仓 |
| v2_amt_half | V2 < 0.7 触发半仓 |
| v3_style_half | V3 > +3%（主板末20% 20 日跑赢微盘 3pp）触发半仓 |
| combo_or | 任一变量触发即半仓（三变量并集，仍是预注册规则非拟合） |

成本：0.8% microcap 单边（最悲观档，与融合 closure 同口径）。

**判定（预注册）**：费后（0.8% 档）MDD ≤ −20% 且 CAGR ≥ 18% →
`risk_engineering_passed`；MDD 改善 ≥5pp 但 CAGR 掉到 <18% →
`risk_mdd_fixed_cost_high`；MDD 无改善 → `state_variable_dead`。
触发次数、最长触发天数、2024-01/02 段收益单独报告。

## 4. 实验二臂（冻结）

| 臂 | 构造 |
|---|---|
| enhance_full | 1+0.5×(rank−0.5) 全池（基准） |
| enhance_top150 | enhance 权重排序取前 150 重归一 |
| enhance_top100 | 同上取前 100 |
| enhance_top50 | 同上取前 50（渐近 top-N 的对照） |
| top30_ew | 等权 top30（已知死亡形态，作形状对照） |

成本 0.8% 档。**判定**：信号超额（vs pool_ew）≥ 全池 enhance 超额的
70% 且 MDD 不深于全池 enhance 2pp 以上 → 该 N `executable`；报告
每臂实际持仓票数分布。

## 5. 输出与判定文件

`output/analysis_fundamental/microcap_risk_engineering_v1/`（实验一）、
`output/analysis_fundamental/microcap_topn_exec_v1/`（实验二）；脚本
`scripts/backtest_microcap_risk_engineering_v1.py`（两实验共用数据层）；
closure `research/decisions/microcap_engineering_closure_v1.md`。

## 6. 变更记录

| 日期 | 变更 |
|---|---|
| 2026-09-12 | 创建：3 状态变量 × 减仓规则 + enhance 截断 5 臂，双判定门槛预注册 |
