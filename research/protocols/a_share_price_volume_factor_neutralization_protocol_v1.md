# 存活价量因子中性化复验协议 v1

状态：`executed_alpha_confirmed`（2026-08-12 执行；TURNOVER_LEVEL5 与 SKEW60
MVI 中性化后均存活，ICIR 不降反升，判定 `alpha_confirmed`；结论归档见
`research/decisions/a_share_price_volume_factor_neutralization_closure_v1.md`）

## 1. 状态、问题与授权边界

**承接**：`a_share_price_volume_factor_battery_closure_v1.md` 判定 7 个非 Alpha158
量价因子中 2 个存活——TURNOVER_LEVEL5（自由流通换手率水平，IC +0.064、ICIR 0.35、
2026 全表最强）与 SKEW60（60 日收益偏度，ICIR 0.37）。但归档明确标注了两个
"存活但存疑"：
- TURNOVER_LEVEL5 方向与文献相反（高换手 → 高收益），五分组 U 型（IC 主要来自
  高换手极端组），**疑似高波动/题材/小市值的风险暴露而非行为 alpha**（与 STD20
  相关 0.55）；
- SKEW60 方向也与彩票偏好理论相反，需排除波动率代理。

**本协议回答**：这两个因子的 RankIC 在控制市值、波动率、行业之后是否仍存活？
即：中性化后仍有增量 alpha，还是纯风险暴露？

**授权边界**：只对 TURNOVER_LEVEL5、SKEW60 两个存活因子做中性化复验；不搜索
替代因子定义、不扩展窗口搜索、不改变 v1 的过滤/标签口径。中性化采用冻结的
三档横截面残差法 + 冻结的市值×波动分层法。

## 2. 假设（冻结）

- H1：TURNOVER_LEVEL5 的正 IC 在控制市值与波动后消失 → 风险暴露（高换手 =
  小市值/高波动补偿）；仍存活 → 存在换手率独有的行为信息。
- H2：SKEW60 的正 IC 在控制波动率（std20）后消失 → 波动率代理；仍存活 → 偏度
  有独立于波动的高阶矩信息。

## 3. 中性化设计（冻结）

### 3.1 三档横截面残差中性化

每交易日，对因子值做 OLS 回归并取残差：

| 档 | 回归 | 含义 |
|---|---|---|
| 原始 | 无 | v1 基准 |
| M | `factor ~ 1 + log(circ_mv)` | 控制市值 |
| MV | `factor ~ 1 + log(circ_mv) + std20` | 控制市值 + 波动 |
| MVI | `factor ~ 1 + log(circ_mv) + std20 + 行业L1哑变量` | 全控制 |

- `circ_mv`：自由流通市值（`a_share_daily_basic_pit_v1`），取对数压缩右偏；
- `std20`：`close` 20 日滚动标准差 / close（与 Alpha158 STD20 同口径，逐股计算）；
- 行业：申万 L1（`a_share_style_pit_v1/normalized/industry_l1_effective_intervals.csv.gz`，
  PIT 区间逐日 asof）；
- OLS 用 `np.linalg.lstsq`（最小范数解，容忍行业哑变量共线）；
- 对中性化后因子（残差）重算逐日 RankIC / ICIR / 分年度，方向保持原始方向。

### 3.2 市值 × 波动分层（辅助，抓"只在一层有效"的风险暴露）

- 每交易日按 log(circ_mv) 与 std20 各 5 分位，25 格组内计算**原始因子** RankIC；
- 报告全期组内 IC 均值矩阵：若因子只在某层（如小市值/高波动格）有效，判定风险暴露。

## 4. 口径（冻结，与 v1 完全一致）

- 主池：沪深普通 A 股母池 5544 只（all.txt 历史在市，剔除 BJ/指数/B 股）；
- 辅助层：csi1000 历史成分（只跑 MVI 档对照）；
- 数据：`~/.qlib/qlib_data/cn_data_2026`（后复权）+ `daily_basic_pit_v1`（换手率
  与市值）+ `a_share_style_pit_v1`（行业）；
- 过滤：ST/*ST/退市整理（PIT）+ 停牌 + 涨停信号日；
- 窗口：2022-01-01 ~ 2026-07-31（预热自 2020-01-01）；
- label：T+1 开盘成交 `Ref($open,-1)/Ref($close,-6)-1`（h=5），Spearman RankIC；
- 年化：日均 × 238/5。

## 5. 预设判定（每个因子独立）

| 条件 | 判定 |
|---|---|
| MVI 中性化后 ICIR ≥ 0.3 **且** 2022-2025 同向 ≥ 3 年 | `alpha_confirmed` → 真增量，候选主线正交信号源（另行立项验证与主线正交性） |
| MVI 后 IC 均值相对原始衰减 > 50% 或 ICIR < 0.2 | `risk_exposure` → 风险暴露，判死归档 |
| 其余 | `partially_neutralized` → 弱存活，需并入主线组合后再评 |

分层辅助：若因子 IC 高度集中在某一市值/波动层（该层贡献 IC 显著高于其他层），
即使全截面存活也按 `risk_exposure` 从严处理。

## 6. 产物与目录

```text
output/analysis_static/a_share_price_volume_factor_neutralization_v1/
  neutralized_daily_ic.csv.gz   每因子 × 三档 每日 RankIC（long 格式）
  neutralized_summary.csv       每因子 × 档 IC/ICIR/IC>0/2022-2025同向/2026 IC
  neutralized_yearly.csv        每因子 × 档 分年度 IC
  neutralized_sizevol_grid.csv  市值×波动 5×5 组内 RankIC（原始因子，全期）
  decision.json                 预设判定（每因子）
  methodology.json              口径快照
  validation_report.txt         中文报告
```

脚本：`scripts/analyze_a_share_price_volume_factor_neutralization_v1.py`。

## 7. 结论边界

本复验只回答"存活因子的增量是否中性化后仍在"，不改变主线决策。`alpha_confirmed`
仅获"候选信号源"资格，是否接入主线另行立项。所有结论在仓库口径下成立。

## 8. 变更记录

| 日期 | 变更 |
|---|---|
| 2026-08-12 | 创建：冻结三档残差中性化 + 市值×波动分层；对 TURNOVER_LEVEL5/SKEW60 复验 |
| 2026-08-12 | 执行：两因子 MVI 后均 alpha_confirmed（ICIR 0.52/0.42，分层 25/25 格全正）；结论归档 `a_share_price_volume_factor_neutralization_closure_v1.md` |
