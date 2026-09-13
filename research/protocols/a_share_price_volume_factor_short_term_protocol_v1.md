# 存活价量因子短周期可行性检验协议 v1

状态：`executed_short_term_viable`（2026-08-12 执行；两因子最优持有期 h=10
（非日频）、ICIR 0.83/0.51、2022-2026 五年全正、2026 未衰减，Top20% 组合
粗算扣成本年化净超额 +24.8%/+2.5%（上限估计，未含冲击成本）→ 两候选均
`short_term_viable`，结论归档见
`research/decisions/a_share_price_volume_factor_short_term_closure_v1.md`）

## 1. 承接与动机

`a_share_price_volume_factor_orthogonality_h40_closure_v1.md` 判定：
TURNOVER_LEVEL5 / SKEW60 是**短周期信号**——h=5 有效（battery v1 /
neutralization v1 已证），h=40 反转（IC 四年全负），不能并入月频主线。
归档 §6 给出的合理归宿：**独立短周期策略**（日频/周频调仓）或主线持仓内
日频轮动。

本协议检验第一步：**两因子能否支撑独立短周期策略**——即回答三个问题：
1. 信号的最优持有期在哪（decay 轮廓）？
2. 最优持有期下信号是否稳定（分年度 IC/ICIR/正占比）？
3. 扣交易成本后是否还有利润空间（换手率敏感性）？

## 2. 信号与标签（冻结）

- 候选（MVI 残差 + raw 对照）：`TURNOVER_LEVEL5` / `SKEW60`
  （口径与 neutralization v1 完全一致）
- 标签：T+1 开盘成交，`Ref($open,-1)/Ref($close,-(h+1))-1`，h ∈ {1, 3, 5, 10}
  （h=5 与 battery v1 口径一致，其余 h 同式外推）
- 主池：沪深普通 A 股母池（与 v1 一致，ST/停牌/涨停过滤）
- 窗口：2022-01-01 ~ 2026-07-31（预热自 2020-01-01，与 neutralization v1 一致）
- 年度：2022-2025 同向判定 + 2026 IC 单独列出（"2026 衰减杀"口径）

## 3. 检验设计（冻结）

### C1 衰减轮廓（decay profile）
对每因子 × 每 h ∈ {1,3,5,10}：全期 RankIC/ICIR/IC>0 占比（MVI 残差口径），
找 ICIR 最高的 h 为"最优持有期"。

### C2 稳定性（最优 h 上）
- 分年度 IC（2022~2026），2022-2025 同向数 ≥ 3 判定稳定；
- 2026 IC 单独报告（是否被"2026 衰减"杀死）；
- raw vs MVI 对照（中性化是否仍然必要）。

### C3 单调性（最优 h 上）
五分位组内平均收益，检查 Q1→Q5 单调性 + Q5-Q1 价差。
（battery v1 已知 TURNOVER_LEVEL5 在 h=5 是 U 型——IC 主要来自高换手极端组，
 本检验看最优 h 下是否仍是 U 型。）

### C4 换手率与成本敏感性（最优 h 上）
取每调仓日 MVI 残差 Top 20% 等权组合：
- 组合平均前向收益（h 日）与全市场均值之差 = 单期毛超额；
- 相邻调仓日组合重叠率 → 单期换手率 → 年化换手次数 × 换手率；
- 交易成本：双边 0.20%（买 0.05% + 卖 0.15%，与 metrics_judgment_standard.md
  及 csi300 滑点扫描一致）；
- 年化净超额 = 年化毛超额 − 年化成本。

## 4. 预设判定

| 条件 | 判定 |
|---|---|
| 最优 h 上 ICIR ≥ 0.5 且 2022-2025 同向 ≥ 3 且 2026 IC > 0 且 C4 扣成本后净超额 > 0 | `short_term_viable` → 建议立项独立短周期策略（另行立项） |
| 最优 h 上 ICIR ∈ [0.3, 0.5) 且 C4 扣成本净超额 > 0 | `short_term_marginal` → 只能做主线持仓内轮动层，不单飞 |
| 最优 h 上 ICIR < 0.3 或 C4 扣成本净超额 ≤ 0 | `short_term_not_viable` → 关闭短周期路径 |

参考阈值（`metrics_judgment_standard.md`）：IC ≥ 0.05 好 / ICIR ≥ 0.5 好 /
IC>0 ≥ 60% 好；换手率 0.15-0.30 适中、> 0.50 过度交易成本吃掉收益。

## 5. 产物与目录

```text
output/analysis_static/a_share_price_volume_factor_short_term_v1/
  decay_profile.csv        每因子 × h：IC/ICIR/IC>0（C1）
  stability_yearly.csv     每因子 × h：分年度 IC（C2）
  quintile_returns.csv     最优 h 五分位（C3）
  turnover_cost.csv        最优 h Top20% 组合换手与成本（C4）
  decision.json            预设判定（每因子）
  methodology.json         口径快照
  validation_report.txt    中文报告
```

脚本：`scripts/analyze_a_share_price_volume_factor_short_term_v1.py`
（复用 neutralization v1 的 universe/过滤/MVI，扩展多 h 标签与组合模拟）

## 6. 结论边界

本检验只回答"能否支撑独立短周期策略"的统计可行性（IC/稳定性/扣成本净超额），
**不做完整回测**（无基准对冲、无滑点逐笔、无资金容量模型）。`short_term_viable`
仅确认值得进入组合构建阶段，实际策略（基准/权重/容量/滑点）另行立项。

## 7. 变更记录

| 日期 | 变更 |
|---|---|
| 2026-08-12 | 创建：冻结短周期可行性检验（decay + 稳定性 + 单调性 + 换手成本） |
