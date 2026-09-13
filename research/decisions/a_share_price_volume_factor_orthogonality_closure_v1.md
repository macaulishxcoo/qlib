# 存活价量因子与主线正交性检验归档 v1

## 1. 决策

状态：`orthogonality_confirmed_complementarity_open`（两候选均 `orthogonal_neutral`）

**正交性极好，互补性在本检验口径下未确认**：
- **正交**：TURNOVER_LEVEL5 / SKEW60（MVI 残差）与主线（价值质量 composite 中性化）
  调仓日截面相关中位数 **+0.011 / -0.080**（|corr| 全 < 0.11）——两因子与主线
  **几乎零重叠信息**；
- **互补**：等权合并 h=5 IC 无增益（-0.027~-0.034），按协议判定 `orthogonal_neutral`
  = "正交但不增量，暂不投入"。**但此结论受 h=5 口径局限（见 §4.2）**。

## 2. 协议与产物

- 协议：`research/protocols/a_share_price_volume_factor_orthogonality_protocol_v1.md`
  （状态 `executed_orthogonal_neutral`）
- 脚本：`scripts/analyze_a_share_price_volume_factor_orthogonality_v1.py`
- 产物：`output/analysis_static/a_share_price_volume_factor_orthogonality_v1/`

窗口：42 个调仓日 2022-01-04 ~ 2025-06-03（财务 PIT 上限 2025-06-28）。
候选 = MVI 残差（log circ_mv + std20 + 申万L1）；主线 = composite（≥3 因子）+
行业+log_size OLS 残差（total_mv 口径）。

## 3. 主结果

### O1 正交性（候选 MVI vs 主线 composite_neutral，调仓日截面 Spearman）

| 因子 | corr 中位数 | corr 均值 | raw_raw 中位数 | 分年度\|corr\|范围 |
|---|---|---|---|---|
| TURNOVER_LEVEL5 | **+0.011** | +0.000 | -0.293 | 0.027~0.069 |
| SKEW60 | **-0.080** | -0.092 | -0.132 | 0.073~0.106 |

### O2 互补性（调仓日 RankIC，h=5 标签）

| 因子 | 主线 IC/ICIR | 候选 IC/ICIR | 合并 IC/ICIR | 合并增益 |
|---|---|---|---|---|
| TURNOVER_LEVEL5 | -0.0432/-0.37 | -0.0040/-0.05 | -0.0309/-0.26 | -0.027 |
| SKEW60 | -0.0432/-0.37 | +0.0128/0.19 | -0.0215/-0.32 | -0.034 |

## 4. 关键解读与诚实标注

### 4.1 正交性结论稳健
两因子与主线相关性几乎为零（TURNOVER_LEVEL5 中位数 +0.011，SKEW60 -0.080），
分年度稳定（|corr| 均 < 0.11）。**换手率水平与偏度确实是主线（基本面价值质量）
之外的独立信息轴**——这与理论一致（价值因子换手慢、量价因子快）。

### 4.2 互补性"无增量"受 h=5 口径局限（必须如实标注）
- **主线是月频策略**：验证与回测口径为 h=40 日（`a_share_value_quality_level
  _factors_extension_protocol_v1.md`），其 h=5 单因子 IC 在开发期就弱。
- 本协议冻结 h=5 标签（承接候选 v1 验证口径），导致**主线在非本职口径下测试**
  （IC -0.043），合并自然无增益。
- 因此 O2 的"无增量"**不能作为否定结论**；等权 0.5/0.5 合并也非最优组合方式。
- **正确补测（另行立项）**：在 h=40（主线本职）口径下，检验候选 MVI 残差与
  主线 composite 的互补性；以及主线持仓 top50 上候选因子的分层表现。

### 4.3 其他标注
- 两轴市值口径不同（候选 circ_mv vs 主线 total_mv），相关性低估了重叠，但
  |corr|<0.11 的余量足够大，不影响正交结论。
- 2025-06 后未测（财务 PIT 上限），待财务更新补测。
- 候选 MVI 的 h=5 IC 在调仓日样本上偏弱（TURNOVER_LEVEL5 -0.004、SKEW60 +0.013），
  与 battery v1 全市场逐日口径（+0.037/+0.020）有差异——调仓日 subset 小、且
  月度截面 IC 波动大。

## 5. 结论与建议

1. **两候选与主线高度正交**（|corr|<0.1）——确认是主线之外的真实独立信息轴，
   "候选主线正交信号源"资格成立。
2. **互补性未在当前口径确认**，不判死：按协议 `orthogonal_neutral` 归档
   （暂不投入），但保留补测机会：
   - 在 h=40（主线本职）口径下重测互补性（另行立项）；
   - 财务更新后补测 2025-06 之后。
3. **不追加**：本协议冻结口径下结论已出；组合方式（权重/门槛/并入回测）另行立项。

## 6. 可复现证据

- 协议：`research/protocols/a_share_price_volume_factor_orthogonality_protocol_v1.md`
- 脚本：`scripts/analyze_a_share_price_volume_factor_orthogonality_v1.py`
- 产物：`output/analysis_static/a_share_price_volume_factor_orthogonality_v1/`
  （orthogonality_daily/summary.csv、complementarity_daily/summary.csv、
  decision.json、validation_report.txt）

## 7. 变更记录

| 日期 | 变更 |
|---|---|
| 2026-08-12 | 创建：两候选与主线正交性极好（\|corr\|<0.11）；互补性受 h=5 口径局限未确认，orthogonal_neutral 归档，保留 h=40 补测资格 |
| 2026-08-12 | h=40 补测已执行（`a_share_price_volume_factor_orthogonality_h40_closure_v1.md`）：主线本职口径下主线 IC +0.097/0.85 四年全正、候选四年全负 → 时间尺度错配，候选为短周期信号不能并入月频主线，并入路径关闭；本归档补测资格已结清 |
