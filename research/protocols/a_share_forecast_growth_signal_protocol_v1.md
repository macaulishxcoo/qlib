# 业绩预告增速（g2 领先版）增量信息检验协议 v1

## 1. 状态、问题与授权边界

状态：`design_frozen_before_data`

**承接**：`PROJECT_SYNC.md` §8「下一步候选（研究）」第 1 条 ——
「**业绩预告增速**（`a_share_forecast_v1`，2022 起）：成长因子高频领先版本，独立事件族实验」。

**与已关闭路线的边界（重要，避免重复）**：`a_share_positive_event_subtype_closure_v1.md`
（P1）已测过**业绩预告的分类标签**（type ∈ {预增,略增,扭亏,续盈}）作为**事件**，
在 h=10/20 无效应（h=20 −0.06%, t=−0.41）→ `not_supported`；并记录了一个
**未立项的观察**：h=40 正漂移 +1.02%（t=5.72）。

本协议做的是**不同的事**：
- P1 = 把预告当作**事件**（有没有发预告、属于哪一类），测事件后超额；
- 本协议 = 把预告的**量级**（`p_change_min/max`，净利润同比变动区间）当作**连续因子**，
  测它能否**在现有五因子之外**提供增量信息。

**唯一要回答的问题**：

```text
Q. 业绩预告的增速量级，在扣除现有五因子（ep/bm/div_yield/accruals/g2 + 行业 + 规模）
   之后，是否仍携带对未来 1/5/10/20 日收益的截面信息？
```

**不做**：不训练模型、不构造组合、不做参数搜索、不回测交易成本。
**不重复**：不重测预告分类标签（P1 已闭环）。

## 2. 信息边界与数据（冻结）

| 项 | 固定值 |
|---|---|
| 预告数据 | `data/external/tushare/a_share_forecast_v1/raw/YYYYMMDD_forecast.csv.gz`（888 个日文件，2022-01-04 起） |
| 预告字段 | `ts_code, ann_date, end_date, type, p_change_min, p_change_max, net_profit_min, net_profit_max` |
| 控制因子 | **复用项目冻结构造**：`analyze_a_share_value_quality_level_factors_extension_v1.build_snapshot`（ep/bm/div_yield/accruals + log_size + l1_code，含经济域约束与金融股剔除） |
| 成长控制 | `g2 = dt_netprofit_yoy`，PIT 键 `available_date`（复用 `run_daily_signal_pipeline_v1.load_g2_series / g2_at`） |
| 价格/标签 | Qlib store `cn_data_2026`，`$open` |
| 网格 | `a_share_style_pit_v1/normalized/monthly_rebalance_grid.csv.gz`（月末调仓日） |
| 池 | 沪深普通 A 股（`build_snapshot` 输出，已剔金融、剔无行业） |
| 样本期 | grid 中 `rebalance_date ≥ 2022-01-01` 且 `≤ 2026-06-30` 的全部调仓日 |

## 3. 冻结的信号定义

预告在 `ann_date` 盘后公布，**t 日只能使用 `ann_date ≤ t` 的记录**。

| 信号 | 定义 |
|---|---|
| `fg_mid`（主） | `(p_change_min + p_change_max) / 2`，取「`end_date` 最新、且 `ann_date ≤ asof_date`」的一条 |
| `fg_min`（次） | `p_change_min`（保守口径），同上取法 |
| `fg_rank` | `fg_mid` 在当日截面内的百分位秩（仅用于稳健性展示） |

**陈旧度约束（冻结）**：距 `ann_date` 超过 **180 个自然日** 的预告视为失效，置 NaN。
**去重规则（冻结）**：同一 `ts_code` 同一 `end_date` 多次公告取 `ann_date` 最新一条；
同一 `ts_code` 多个 `end_date` 取 `end_date` 最新一条。

## 4. 冻结的标签口径

遵守 `PROJECT_SYNC.md` §7 纪律 3：

```text
label_h(t) = open(t+1+h) / open(t+1) - 1      h ∈ {1, 5, 10, 20}
```

其中 t 为 rebalance_date。**不使用** `open(t+1)/close(t+h+1)-1` 的旧式口径。

## 5. 冻结的判定方法

### 5.1 两个 endpoint

| endpoint | 定义 |
|---|---|
| **主：增量 RankIC（h=5）** | 先对 `fg_mid` 在当日截面上回归 `{ep, bm, div_yield, accruals, g2, log_size, 行业哑变量}` 取残差（复用 `ols_residual` 的 OLS 口径），再计算残差与 `label_5` 的 Spearman RankIC；跨调仓日汇总 |
| 次：原始 RankIC | `fg_mid` / `fg_min` 与 `label_h`（h=1/5/10/20）的 RankIC，仅作描述 |

**主 endpoint 选择理由**：本实验的价值主张是"**增量**"，不是"又一个有 IC 的因子"。
原始 IC 会被它与价值/成长因子的相关性污染，无法回答"是否值得加入现有模型"。

### 5.2 冻结阈值

| 判定 | 条件 |
|---|---|
| `incremental_supported` | 主 endpoint \|RankIC\| ≥ **0.02** 且 \|ICIR\| ≥ **0.30**，且符号在 **≥3/4 个年度块**中一致 |
| `not_supported` | 否则 |

阈值来源：现有四因子在项目记录中的中性 RankIC 为 0.044~0.083（`PROJECT_SYNC` §2.2）。
一个**增量**因子取 0.02（约为现有因子强度的 1/3）+ ICIR 0.30，是**有意从紧**的下限——
低于此值不值得在一个已经达标（全期 stress 净超额 +10.5%）的策略上增加复杂度与换手。

**事后不得**调整阈值、horizon、陈旧度窗口、去重规则或控制变量集合。

## 6. 产物与目录

```text
output/analysis_fundamental/a_share_forecast_growth_signal_v1/
  snapshot_panel.csv.gz        # 每个调仓日 x 每股：fg_mid/fg_min + 控制因子 + 标签
  ic_by_date.csv.gz            # 主/次 endpoint 的逐调仓日序列
  ic_summary.csv               # 汇总（含分年度块）
  residual_diagnostics.csv     # 残差化前后相关、控制变量共线性诊断
  decision.json
  methodology.json
  forecast_growth_report.txt
```

## 7. 预设结论与后续

| 结论 | 后续动作 |
|---|---|
| `incremental_supported` | 另立协议：把 `fg_mid` 作为**第五条之外的第六条腿**加入五因子 composite，测双门槛（holdout 侵蚀 ≤ −0.5pp、new_coverage 改善 ≥ +5pp） |
| `not_supported` | 关闭该方向，记录原因；**不追加公式、不换窗口、不换阈值** |

## 8. 结论边界（诚实标注）

1. **无一致预期数据**：`fg_mid` 是"公司自述的同比区间中值"，**不是"超预期"**。
   预告本身是管理层自愿/强制披露，存在**选择性披露偏差**——业绩好的公司更愿意预告。
   因此本实验测的是"预告量级的截面预测力"，不是"盈余惊喜"。
2. **样本期短**：预告数据 2022 起，仅约 4.5 年、54 个调仓日；**统计功效有限**，
   `not_supported` 只能说明"在本样本内不足以支持"，不等于"该因子全期无效"。
3. **数据源覆盖**：`a_share_forecast_v1` 为按日拉取，2022 年前的预告不在库内。
4. 本协议不做成本模拟；即便 `incremental_supported`，进入组合层仍需过
   "扣成本真实调仓回测"（`PROJECT_SYNC.md` §5 教训 1）。
