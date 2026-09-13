# 价值陷阱识别单因子验证协议 v1

## 1. 状态、问题与授权边界

状态：`design_frozen_before_first_label_read`

承接 `research/decisions/a_share_value_trap_identification_proposal_v1.md`。主线
价值策略（四因子复合）全部为**水平因子**（E/P、BM、股息率、应计质量），无法区分
"便宜且稳定"与"便宜且正在恶化"。本协议检验：

```text
在主线的"便宜"子集（composite 中性化残差前 50%）内，财务恶化信号
（净利/营收/经营现金流同比为负）标识的股票，未来 20/40/60 日是否
显著跑输"同样便宜但财务稳定"的股票？
```

若成立 → 恶化信号可作为主线的**质量过滤层**（剔除价值陷阱），再走组合层回测验证；
若不成立 → 关闭归档，结论"价值陷阱在主线域内不存在或已定价"。

本协议只授权**单因子信息含量检验 + 一次过滤层组合对比回测**，不授权模型训练、
阈值搜索或实盘。4 个恶化信号定义在读取任何标签前冻结；跑完不因结果调整信号或门槛。

## 2. 与既有研究的关系

| 项 | 说明 |
|---|---|
| 已关闭命题（盈利现金质量、营运资本质量） | 关注"同比改善"作**正向选股**信号，失败。本协议关注"恶化"作**负向过滤**，方向相反、用途不同 |
| PEAD（已关闭） | 检验公告**事件窗口**内漂移（利空出尽）。本协议检验报告期**状态截面**的未来持有期收益，机制链不同 |
| 主线四因子 | 全部水平因子。本协议补充"恶化状态"维度，正交 |
| 恶化信号列 | `fina_indicator` 归一化文件自带 `netprofit_yoy` / `or_yoy` / `ocf_yoy` / `dt_netprofit_yoy`（非空率 93-95%），可用 `available_date` PIT 对齐，零新增下载 |

## 3. 信号定义（冻结，不做搜索）

对每月快照（`available_date <= rebalance_date` 的最新可得报告期版本）：

| 信号 | 定义 | 方向 |
|---|---|---|
| `deter_ni` | 1 if `netprofit_yoy < 0`（净利同比为负） | 负向 |
| `deter_or` | 1 if `or_yoy < 0`（营收同比为负） | 负向 |
| `deter_ocf` | 1 if `ocf_yoy < 0`（经营现金流同比为负） | 负向 |
| `deter_any2` | 1 if 以上 3 个中 **≥2 个**为 1（复合恶化，主信号） | 负向 |

补充约束：
- YoY 列缺失（新上市/数据缺失）时该子信号记 NaN，不填 0；
- `deter_any2` 需至少 2 个子信号非缺失才能判定（即至少有 2 个可观察维度）；
- `deter_ni` 附加扣非对照：`dt_netprofit_yoy < 0` 仅作观察口径（`deter_ni_dedt`），不计入门槛；
- 分报告期（Q1/Q2/Q3/Q4）报告，标注基数效应与季节性（尤其 Q1）。

## 4. 检验框架（与主线单因子验证同构）

- **母池**：沪深普通 A 股（非金融），口径同主线；
- **域（关键）**：`composite_score`（≥3 因子门槛）→ 行业 OLS + log_size 中性化
  （`ols_residual`）残差前 50%（横截面分位数），即主线日频策略的选股域定义；
- **信号快照**：月末 `available_date <= rebalance_date` 最新版本（复用
  `load_financials_extended` + `build_daily_grid`，网格与 v6/v8 完全一致）；
- **标签**：`r_H(t) = open(t+H)/open(t) − 1`，H ∈ {20, 40, 60}；
- **时间切分**：development 2016-2019 / confirmation 2020-2022 / holdout 2023-2025-06 /
  new_coverage 2025-07~2026-06（与 v8 的 STAGES 一致，含 new_coverage 以观察 2026 逆风）；
- **中性化**：对标签再做行业 + log_size OLS 残差（`ols_residual`）后比较组均值，
  与主线"中性 RankIC"口径一致。

### 4.1 主检验（域内恶化组 vs 稳定组）

- 每月：域内按 `deter_any2` 分组（恶化组 = 1，稳定组 = 0）；
- 比较两组 40 日中性化收益均值差（恶化 − 稳定），该差**显著为负**（时序 t 检验：
  以每月差值构成时间序列，t 参照从紧口径 > 2 为显著）；
- 分阶段（dev/conf/holdout/new_coverage）与分年度报告方向与量级；
- 规模层：按 `size_control` 五等分报告，确认效应不集中于最小市值层。

### 4.2 次要观察

- `deter_ni` / `deter_or` / `deter_ocf` 单信号各自的分组差（诊断哪个维度主导）；
- 恶化组在全市场（非域内）的表现对照——区分"域内过滤价值"与"全市场负向信号"；
- new_coverage（2026）重点标注：若过滤层对 2026 逆风有改善，直接支持"价值陷阱成分"
  假说。

## 5. 验收（两条同时满足才采纳过滤层）

1. **IC 层**：域内 `deter_any2` 恶化组 vs 稳定组 40 日中性化收益差**显著为负**
   （时序 t < −2），且分阶段方向一致（dev/conf/holdout 三个阶段中至少 2 个为负）；
2. **组合层**：v8 top15 基线 + 剔除 `deter_any2` 过滤层 vs v8 基线，
   holdout（2023-2025）压力费后年化超额 **不降**（容忍 ≥ −0.5pp），
   且 new_coverage（2025-07~2026-06）年化超额**改善 ≥ +5pp**。

任一不满足 → `value_trap_filter_not_adopted`，关闭归档，不追加搜索、不调阈值。

## 6. 产物、目录与审计

```text
output/analysis_fundamental/a_share_value_trap_identification_v1/
  monthly_signal_label_panel.csv.gz   # 域内逐月 panel：信号 + 中性化收益 + 分组
  group_mean_diff_summary.csv         # 主检验：分阶段/分年度组均值差 + t
  signal_single_summary.csv           # 次要观察：单信号分组差
  size_layer_summary.csv              # 规模层
  decision.json
  methodology.json
  validation_report.txt
```

`decision.json` 对主信号 `deter_any2` 独立给出各阶段判定（negative/neutral/positive），
含时序 t 与方向一致性。组合层对比回测产物在
`output/analysis_fundamental/a_share_value_quality_monthly_strategy_v13_value_trap_filter/`
（基线为既有 v8 产物，不做重跑）。

## 7. 结论边界

若 IC 层通过而组合层不通过 → 记录"信号存在但不足以支撑过滤层"，关闭组合用法；
若 IC 层不通过 → 不再启动组合层回测。无论结果，本协议只跑一次，不因结果调整
信号定义、域分位数、持有期或判定门槛。

## 8. 可复现证据

- 提案：`research/decisions/a_share_value_trap_identification_proposal_v1.md`
- 冻结决策（不再构成门槛，仅方法论参考）：
  `research/decisions/a_share_fundamental_research_freeze_v1.md`
- 复用函数：`scripts/load_financials_extended_v1.py`、
  `scripts/analyze_a_share_value_quality_level_factors_extension_v1.py`
  （build_snapshot / composite_score / ols_residual）、
  `scripts/backtest_a_share_value_quality_monthly_dailygrid_v6.py`（build_daily_grid）、
  `scripts/backtest_a_share_value_quality_monthly_top15_v8.py`（组合层基线）
