# 存活价量因子与主线正交性检验协议 v1

状态：`executed_orthogonal_neutral`（2026-08-12 执行；TURNOVER_LEVEL5/SKEW60 与
主线相关中位数 +0.011/-0.080，正交性极好；h=5 口径合并无增益 → 两候选均
`orthogonal_neutral`；互补性保留 h=40 口径补测资格，结论归档见
`research/decisions/a_share_price_volume_factor_orthogonality_closure_v1.md`）

## 1. 状态、问题与授权边界

**承接**：`a_share_price_volume_factor_neutralization_closure_v1.md` 判定
TURNOVER_LEVEL5 / SKEW60 中性化后 `alpha_confirmed`，获"候选主线正交信号源"
资格。本协议检验第二步：**候选因子与主线（价值质量四因子 composite）是否正交**。

主线信号（冻结）：四因子（E/P、BM、股息率、应计质量）→ composite（rank 均值，
≥3 因子门槛）→ 行业+log_size OLS 残差（`analyze_a_share_value_quality_level
_factors_extension_v1.py` 的 `composite_score` + `ols_residual`）。

**回答**：调仓日横截面上，候选因子（MVI 残差）与主线中性化 composite 的相关性
多高？等权合并后是否产生 IC 增量（互补性）？若正交 → 确认可作主线之外的正交
信号源；若高相关 → 候选与主线同信息，降级为冗余。

**授权边界**：只测 2 候选 × 主线 composite 在月度调仓日的相关性 + 互补性；
不调参、不搜索替代定义、不改变 v1/v2 口径。候选因子用 MVI 残差（市值+波动+
行业），主线用其自有中性化口径（行业+log_size，total_mv）——两轴市值口径不同
（circ_mv vs total_mv），如实报告。

**已知覆盖限制**：财务 PIT 可用到 2025-06-28（`a_share_financial_pit_v1`），
正交性检验窗口 = 2022-01-04 ~ 2025-06-03（42 个调仓日）。2025-06 之后待财务
更新后补测，不伪造。

## 2. 假设（冻结）

- H1：候选 MVI 残差与主线中性化 composite 横截面相关 |corr| < 0.5 → 正交，
  可作主线之外信号源。
- H2：等权 z-score 合并（候选 + 主线）的 RankIC 高于任一分量 → 互补性成立。

## 3. 信号构造（冻结）

| 信号 | 定义 | 口径 |
|---|---|---|
| `composite_neutral` | 主线 composite（≥3 因子门槛）经 行业+log_size OLS 残差 | 主线自有口径（total_mv） |
| `TURNOVER_LEVEL5_MVI` | 换手率水平 5 日均值，MVI 残差（log circ_mv + std20 + 申万L1） | 与 neutralization v1 一致 |
| `SKEW60_MVI` | 60 日偏度，MVI 残差 | 同上 |

标签：T+1 开盘成交 h=5（`Ref($open,-1)/Ref($close,-6)-1`），与候选 v1 验证一致。

## 4. 检验设计（冻结）

在 42 个调仓日逐日执行：

- **O1 正交性**：截面 Spearman，配对：`candidate_MVI vs composite_neutral`、
  `candidate_raw vs composite_raw`（对照组）。报告全期 + 分年度中位数/均值。
- **O2 互补性**：调仓日截面 RankIC（vs h=5 标签）三个信号：
  `composite_neutral`、`candidate_MVI`、`0.5*z(composite_neutral) + 0.5*z(candidate_MVI)`
  合并信号。若合并 ICIR/正占比高于分量 → 互补成立。
- 样本量要求：截面 ≥ 300（调仓日覆盖全市场，ST/停牌/涨停过滤后仍充足）。

## 5. 预设判定

| 条件 | 判定 |
|---|---|
| O1 中位数 \|corr\| < 0.5 **且** O2 合并 ICIR > 任一分量 | `orthogonal_positive` → 候选确认主线正交信号源，建议并入主线组合（另行立项） |
| O1 \|corr\| < 0.5 但 O2 合并无增益 | `orthogonal_neutral` → 正交但不增量，暂不投入 |
| O1 \|corr\| ∈ [0.5, 0.7) | `partially_overlapping` → 需先在主线轴上正交化再评 |
| O1 \|corr\| ≥ 0.7 | `redundant` → 与主线同信息，判死归档 |

## 6. 产物与目录

```text
output/analysis_static/a_share_price_volume_factor_orthogonality_v1/
  orthogonality_daily.csv     每调仓日 相关性（O1）
  orthogonality_summary.csv   O1 全期 + 分年度中位数/均值
  complementarity_daily.csv   每调仓日 三信号 RankIC（O2）
  complementarity_summary.csv O2 全期 IC/ICIR/IC>0
  decision.json               预设判定（每候选）
  methodology.json            口径快照
  validation_report.txt       中文报告
```

脚本：`scripts/analyze_a_share_price_volume_factor_orthogonality_v1.py`
（复用主线 `composite_score`/`ols_residual` + 中性化 `neutralize_day`）。

## 7. 结论边界

本检验只回答"候选与主线是否正交、是否互补"，不改变主线决策。`orthogonal_positive`
仅确认候选具备并入主线的资格，实际并入（权重/门槛/回测）另行立项。2025-06 后
覆盖受限，如实标注。

## 8. 变更记录

| 日期 | 变更 |
|---|---|
| 2026-08-12 | 创建：冻结 O1 正交性 + O2 互补性检验；窗口 2022-01~2025-06（财务上限） |
| 2026-08-12 | 执行：两候选 |corr|<0.11 正交性极好；h=5 口径合并无增益 → orthogonal_neutral；结论归档 `a_share_price_volume_factor_orthogonality_closure_v1.md` |
| 2026-08-12 | h=40 补测（`a_share_price_volume_factor_orthogonality_h40_protocol_v1.md`）：主线本职口径下主线 IC +0.0973/0.85 四年全正，候选 IC 四年全负 → 时间尺度错配，候选是短周期信号不能并入月频主线；并入路径正式关闭，归档 `a_share_price_volume_factor_orthogonality_h40_closure_v1.md` |
