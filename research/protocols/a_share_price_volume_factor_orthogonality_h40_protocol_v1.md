# 存活价量因子与主线互补性补测协议 v1（h=40 口径）

状态：`executed_orthogonal_neutral`（2026-08-12 执行；h=40 主线本职口径下
主线 IC +0.0973/0.85 四年全正，两候选 IC 四年全负（-0.039/-0.029）→ 时间
尺度错配是根因，候选为短周期信号、不能并入月频主线；两候选均
`orthogonal_neutral`，并入主线路径正式关闭，结论归档见
`research/decisions/a_share_price_volume_factor_orthogonality_h40_closure_v1.md`）

## 1. 承接与动机

`a_share_price_volume_factor_orthogonality_protocol_v1.md` 执行判定
`orthogonal_neutral`：TURNOVER_LEVEL5 / SKEW60 与主线 composite 相关中位数
+0.011/-0.080（|corr|<0.11，正交性极好），但 O2 互补性在 **h=5 标签**下
"合并无增益"。归档（`a_share_price_volume_factor_orthogonality_closure_v1.md`）
明确标注口径局限：**主线是月频策略（本职验证口径 h=40，open-to-open），
h=5 标签下主线本身 IC 即为负（-0.0432），"无增量"不能当作否定结论**，
并保留 h=40 口径补测资格。

本协议执行该补测：在主线本职口径下重跑 O2 互补性，直接回答
"候选能否并入主线增厚"。

## 2. 口径变更（唯一改动）

| 项 | v1（已执行） | 本次补测 |
|---|---|---|
| O2 标签 | `Ref($open,-1)/Ref($close,-6)-1`（h=5，T+1 开盘成交） | **open-to-open H=40：`open(t+40)/open(t)-1`**（主线本职口径，与 `analyze_a_share_value_quality_level_factors_extension_v1.py` 的 `fetch_labels` H=40 一致） |
| 其余一切 | — | 与 v1 完全一致（主池/主线 composite/候选 MVI/窗口/判定阈值） |

O1 正交性不依赖标签，本次重算仅作一致性核对（预期与 v1 相同）。

## 3. 信号与标签（冻结）

- 主线：`composite_neutral`（≥3 因子 → 行业+log_size 残差，total_mv 口径）
- 候选：`TURNOVER_LEVEL5_MVI` / `SKEW60_MVI`（log circ_mv + std20 + 申万L1 残差）
- 标签：open-to-open H=40（调仓日 open 入场，40 交易日 open 出场）
- 窗口：42 个调仓日 2022-01-04 ~ 2025-06-03（财务 PIT 上限 2025-06-28）

## 4. 检验设计（冻结）

逐调仓日执行 O2：调仓日截面 RankIC（vs h=40 标签）三个信号：
`composite_neutral`、`candidate_MVI`、`0.5*z(composite_neutral)+0.5*z(candidate_MVI)`。
若合并 IC 均值/ICIR/正占比高于任一分量 → 互补成立。截面 ≥ 300。

## 5. 预设判定（与 v1 §5 一致）

| 条件 | 判定 |
|---|---|
| O1 \|corr\| < 0.5 **且** O2 合并 IC > 任一分量 | `orthogonal_positive` → 候选确认主线正交信号源，建议并入主线组合（另行立项） |
| O1 \|corr\| < 0.5 但 O2 合并无增益 | `orthogonal_neutral` → 正交不增量，暂不投入 |
| O1 \|corr\| ∈ [0.5, 0.7) | `partially_overlapping` |
| O1 \|corr\| ≥ 0.7 | `redundant` |

## 6. 产物与目录

```text
output/analysis_static/a_share_price_volume_factor_orthogonality_h40_v1/
  orthogonality_daily.csv     每调仓日 相关性（O1，一致性核对）
  orthogonality_summary.csv   O1 全期 + 分年度中位数/均值
  complementarity_daily.csv   每调仓日 三信号 RankIC（O2，h=40）
  complementarity_summary.csv O2 全期 IC/ICIR/IC>0
  decision.json               预设判定（每候选）
  methodology.json            口径快照
  validation_report.txt       中文报告（含 v1 h=5 vs h=40 对比）
```

脚本：`scripts/analyze_a_share_price_volume_factor_orthogonality_h40_v1.py`

## 7. 结论边界

本补测只回答"主线本职口径下，候选能否并入主线增厚"。`orthogonal_positive`
仅确认并入资格，实际并入（权重/门槛/回测）另行立项。2025-06 后覆盖受限，
如实标注。

## 8. 变更记录

| 日期 | 变更 |
|---|---|
| 2026-08-12 | 创建：冻结 h=40 口径 O2 补测（主线本职口径，唯一改动为标签） |
