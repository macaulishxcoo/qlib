# 滚动训练优化开发日志

> 创建日期：2026-07-29  
> 问题背景：2008~2020 静态训练效果尚可，数据更新至 2026 年后滚动训练模型完全失效。  
> 排查结论：**核心原因是 2021 年后市场概念漂移（concept drift）导致 alpha 衰减，流程与数据基本无重大 bug。**

---

## 1. 环境信息

| 项目 | 值 |
|---|---|
| 工作目录 | `/home/xiaocong/worksapces/qlib` |
| Python 环境 | `conda activate qlib`（`/home/xiaocong/anaconda3/envs/qlib`） |
| Qlib 版本 | `pyqlib 0.1.dev2065` |
| 旧数据 | `~/.qlib/qlib_data/cn_data` |
| 新数据 | `~/.qlib/qlib_data/cn_data_2026` |

---

## 2. 数据排查结果

### 2.1 两套数据集对比

| 维度 | `cn_data`（旧） | `cn_data_2026`（新） |
|---|---|---|
| 时间范围 | 1999-11-10 ~ **2020-09-25** | 2000-01-04 ~ **2026-07-23** |
| 交易日数 | 4943 | 6434 |
| 成份股文件 | csi100 / csi300 / csi500 / all | csi300 / csi500 / **csi1000** / **csi800** / **csiall** |
| `csi100` | 有 | **缺失** |
| csi300 2020 年有数据股票数 | 180 | 243 |
| csi300 2020 年特征缺失率 | **16.8%** | **0.17%** |

**结论**：新数据质量反而更好，排除“数据缺失导致失效”。  
**注意**：若原策略使用 `csi100`，切到 `cn_data_2026` 会报错或 universe 不一致。

### 2.2 标签分布漂移（核心证据）

标签定义：`Ref($close, -20) / Ref($close, -1) - 1`

| 年份 | 标签均值 | 标签标准差 | 市场特征 |
|---|---|---|---|
| 2020 | +2.17% | 0.124 | 疫情后反弹，波动大 |
| 2021 | -0.23% | 0.112 | 结构性行情，波动收敛 |
| 2022 | -0.75% | 0.104 | 熊市，波动继续收敛 |
| 2023 | -1.31% | 0.088 | 持续低迷 |
| 2024 | +1.43% | 0.122 | 9·24 政策反转 |
| 2025 | +2.02% | 0.098 | 反弹后震荡 |
| 2026 | -0.84% | 0.126 | 波动重新放大 |

**结论**：2021 年后标签均值趋近于 0、标准差显著下降，说明趋势性 alpha 衰减、市场进入低波动/震荡市。

### 2.3 流程排查结论

- 滚动训练切分无时间穿越。
- `fit_start_time` / `fit_end_time` 与训练 segment 对齐。
- Processor 仅在训练集 fit，再 transform 到验证/测试集。
- 无显著 look-ahead bias。

---

## 3. 模型性能退化实验

使用 `cn_data_2026` + `LGBModel` + `Alpha158` + `csi300` 做的三组对照：

| 实验 | 训练集 | 测试集 | 日均 IC | ICIR | IC > 0 比例 |
|---|---|---|---|---|---|
| A | 2017-2019 | 2020 下半年 | **0.0333** | **0.287** | **63.5%** |
| B | 2018-2020 | 2021-2022 | **0.0191** | **0.155** | **55.3%** |
| C | 2021-2023 | 2024-2025 | **0.0147** | **0.106** | **55.3%** |

**结论**：即使训练窗口已经推到最近（实验 C），IC 仍不到 2020 年的一半，说明 alpha 本身在衰减。

---

## 4. 根因分析

1. **市场 regime 变化**：2021 年后 A 股趋势性减弱、波动收敛，传统价量 alpha 失效。
2. **概念漂移（concept drift）**：历史特征-标签关系在新环境中不稳定。
3. **数据 universe 变化**：`cn_data_2026` 缺少 `csi100`，成份股定义存在差异。

---

## 5. 优化方向（按优先级）

### 优先级 1：缩短训练窗口 + 增加近期样本权重

- 避免使用 2008~2020 这种超长窗口。
- 推荐窗口：训练 3~5 年，验证 6~12 个月，测试 6~12 个月。
- 在 LightGBM 训练时传入 `weight`，给近期样本更高权重。

参考配置思路：

```yaml
dataset:
  class: DatasetH
  module_path: qlib.data.dataset
  kwargs:
    handler:
      class: Alpha158
      module_path: qlib.contrib.data.handler
      kwargs:
        start_time: 2021-01-01
        end_time: 2026-07-23
        fit_start_time: 2021-01-01
        fit_end_time: 2024-12-31
        instruments: csi300
    segments:
      train: [2021-01-01, 2024-12-31]
      valid: [2025-01-01, 2025-06-30]
      test:  [2025-07-01, 2026-07-23]
```

---

### 优先级 2：引入 DDG-DA（动态数据选择）

Qlib 内置了解决概念漂移的方案：

- 示例入口：[`examples/benchmarks_dynamic/DDG-DA/workflow.py`](file:///home/xiaocong/worksapces/qlib/examples/benchmarks_dynamic/DDG-DA/workflow.py)
- 核心实现：[`qlib/contrib/rolling/ddgda.py`](file:///home/xiaocong/worksapces/qlib/qlib/contrib/rolling/ddgda.py)

DDG-DA 会根据当前测试分布，自动从历史中挑选“最相似”的样本训练，比固定滚动窗口更适应 regime 切换。

建议作为第二阶段的优化重点。

---

### 优先级 3：更换对分布漂移更鲁棒的模型

在 [`qlib/contrib/model/`](file:///home/xiaocong/worksapces/qlib/qlib/contrib/model) 中优先尝试：

| 模型 | 文件 | 适用场景 |
|---|---|---|
| **ADARNN** | [`pytorch_adarnn.py`](file:///home/xiaocong/worksapces/qlib/qlib/contrib/model/pytorch_adarnn.py) | 显式建模时间序列分布迁移 |
| **HIST** | [`pytorch_hist.py`](file:///home/xiaocong/worksapces/qlib/qlib/contrib/model/pytorch_hist.py) | 引入概念信息，降低对单一价量特征依赖 |
| **DoubleEnsemble** | [`double_ensemble.py`](file:///home/xiaocong/worksapces/qlib/qlib/contrib/model/double_ensemble.py) | 通过样本/特征选择抑制噪声 |
| **TRA** | [`pytorch_tra.py`](file:///home/xiaocong/worksapces/qlib/qlib/contrib/model/pytorch_tra.py) | 针对市场动态性建模 |

---

### 优先级 4：优化标签与回测策略

- 把 20 日收益率标签替换为**方向性标签**或**夏普类标签**。
- 回测中加入**止盈止损**或**波动率缩放**。
- 使用 `TopkDropoutStrategy` 时，适当减小 `n_drop`，降低换手和交易成本。
- 检查 `deal_price` 与模型标签价格字段是否一致。

---

## 6. 推荐执行顺序

1. 先做 **优先级 1**（缩短窗口 + 权重），验证是否恢复部分 IC。
2. 如果效果仍差，上 **优先级 2**（DDG-DA）。
3. 同时并行尝试 **优先级 3** 中的 ADARNN 或 HIST。
4. 最后做 **优先级 4** 的策略层优化。

---

## 7. 相关文件与参考

- 滚动训练基类：[`qlib/contrib/rolling/base.py`](file:///home/xiaocong/worksapces/qlib/qlib/contrib/rolling/base.py)
- DDG-DA 实现：[`qlib/contrib/rolling/ddgda.py`](file:///home/xiaocong/worksapces/qlib/qlib/contrib/rolling/ddgda.py)
- 任务生成器：[`qlib/workflow/task/gen.py`](file:///home/xiaocong/worksapces/qlib/qlib/workflow/task/gen.py)
- 基准配置：[`examples/benchmarks_dynamic/baseline/workflow_config_lightgbm_Alpha158.yaml`](file:///home/xiaocong/worksapces/qlib/examples/benchmarks_dynamic/baseline/workflow_config_lightgbm_Alpha158.yaml)
- DDG-DA 示例：[`examples/benchmarks_dynamic/DDG-DA/workflow.py`](file:///home/xiaocong/worksapces/qlib/examples/benchmarks_dynamic/DDG-DA/workflow.py)
- 训练器核心：[`qlib/model/trainer.py`](file:///home/xiaocong/worksapces/qlib/qlib/model/trainer.py)

---

## 9. 优先级 1 实验结果（2026-07-29）

### 9.1 实验设计

为验证“缩短训练窗口 + 样本权重”的效果，跑了 3 组对照实验：

| 实验 | 训练窗口 | 验证窗口 | 测试窗口 | 权重策略 |
|---|---|---|---|---|
| `baseline` | 2021-01-01 ~ 2024-12-31 | 2025-01-01 ~ 2025-06-30 | 2025-07-01 ~ 2026-07-23 | 无 |
| `timedecay_252` | 2021-01-01 ~ 2024-12-31 | 2025-01-01 ~ 2025-06-30 | 2025-07-01 ~ 2026-07-23 | 指数衰减，半衰期 252 日 |
| `timedecay_126` | 2022-01-01 ~ 2024-12-31 | 2025-01-01 ~ 2025-06-30 | 2025-07-01 ~ 2026-07-23 | 指数衰减，半衰期 126 日 |

所有实验共享：
- 数据：`~/.qlib/qlib_data/cn_data_2026`
- 模型：`LGBModel` + `Alpha158`
- 股票池：`csi300`
- 标签：`Ref($close, -20) / Ref($close, -1) - 1`
- LightGBM 超参数一致

### 9.2 实验文件

- 权重实现：[`research/reweighters/time_decay_reweighter.py`](research/reweighters/time_decay_reweighter.py)
- 配置文件：[`research/configs/exp_baseline.yaml`](research/configs/exp_baseline.yaml)、[`exp_timedecay_252.yaml`](research/configs/exp_timedecay_252.yaml)、[`exp_timedecay_126.yaml`](research/configs/exp_timedecay_126.yaml)
- 运行脚本：[`research/run_rolling_comparison.py`](research/run_rolling_comparison.py)
- 结果 CSV：[`research/rolling_comparison_results.csv`](research/rolling_comparison_results.csv)

### 9.3 实验结果

| 实验 | n_samples | daily_ic_mean | daily_ic_std | icir | ic_positive_ratio | rank_ic_mean | rank_icir |
|---|---:|---:|---:|---:|---:|---:|---:|
| `baseline` | 76881 | **-0.0059** | 0.1771 | **-0.0333** | **48.64%** | **0.0209** | **0.1146** |
| `timedecay_252` | 76881 | -0.0129 | 0.1679 | -0.0769 | 42.41% | 0.0152 | 0.0803 |
| `timedecay_126` | 76881 | -0.0189 | 0.1858 | -0.1016 | 43.58% | 0.0137 | 0.0673 |

### 9.4 结论

- **Daily IC 全部接近 0 或为负**，说明 2025-07 至 2026-07 这个测试段对 Alpha158 + LightGBM 极其困难。
- **缩短窗口 + 时间衰减权重没有改善效果，反而让 Daily IC 更差。**
- Rank IC 仍为正值，但也在衰减（0.0209 → 0.0137）。

**原因分析**：
- 2024 年 9·24 政策驱动的反弹和 2025 年上半年的结构性行情，与 2025 下半年至 2026 年的震荡/回调环境差异巨大。
- 给 2024-2025 年样本更高权重，反而让模型学习到一段“特殊行情”的模式，在后续测试中失效。
- 这印证了：当前问题不是简单的“窗口太长”或“老样本干扰”，而是 **alpha 信号在测试期本身失效**。

### 9.5 下一步建议

优先级 1 单独使用效果不佳，建议进入优先级 2 / 3：

1. **DDG-DA**（优先级 2）：动态选择历史分布，可能避免把 9·24 行情过度拟合。
2. **ADARNN / HIST / DoubleEnsemble**（优先级 3）：这类模型对 regime 切换更鲁棒。
3. **同时考虑标签重构**：把 20 日收益率换成方向性标签或波动率调整标签，可能降低极端行情影响。

---

## 10. 模型对比实验（2026-07-29）

### 10.1 实验目的

回答关键问题：**当前失效是“因子失效”还是“模型失效”？**

- 如果是**因子失效**：换什么模型（LGBM、ADARNN、Linear）都无效，需要重构特征或标签。
- 如果是**模型失效**：ADARNN 等分布自适应模型应明显优于 LGBM / Linear。

### 10.2 实验设计

| 实验 | 模型 | 因子集 | 训练窗口 | 验证窗口 | 测试窗口 |
|---|---|---|---|---|---|
| `lgbm_alpha158` | LightGBM | Alpha158 | 2021-01-01 ~ 2024-12-31 | 2025-01-01 ~ 2025-06-30 | 2025-07-01 ~ 2026-07-23 |
| `lgbm_alpha360` | LightGBM | Alpha360 | 同上 | 同上 | 同上 |
| `adarnn_alpha360` | ADARNN | Alpha360 | 同上 | 同上 | 同上 |
| `linear_alpha360` | Ridge | Alpha360 | 同上 | 同上 | 同上 |

说明：
- Alpha360 只有 6 个原始特征（OHLCV 相关），是 ADARNN 示例中的标准输入。
- 通过 `lgbm_alpha158` vs `lgbm_alpha360` 可观察“因子集”影响。
- 通过 `lgbm_alpha360` vs `adarnn_alpha360` vs `linear_alpha360` 可隔离“模型”影响。

### 10.3 实验文件

- 配置文件：
  - [`research/configs/exp_baseline.yaml`](research/configs/exp_baseline.yaml)（即 `lgbm_alpha158`）
  - [`research/configs/exp_lgbm_alpha360.yaml`](research/configs/exp_lgbm_alpha360.yaml)
  - [`research/configs/exp_adarnn_alpha360.yaml`](research/configs/exp_adarnn_alpha360.yaml)
  - [`research/configs/exp_linear_alpha360.yaml`](research/configs/exp_linear_alpha360.yaml)
- 运行脚本：[`research/run_model_comparison.py`](research/run_model_comparison.py)
- 结果 CSV：[`research/model_comparison_results.csv`](research/model_comparison_results.csv)

### 10.4 实验结果

| 实验 | n_samples | daily_ic_mean | daily_ic_std | icir | ic_positive_ratio | rank_ic_mean | rank_icir |
|---|---:|---:|---:|---:|---:|---:|---:|
| `lgbm_alpha158` | 76881 | **-0.0059** | 0.1771 | **-0.0333** | **48.64%** | 0.0209 | 0.1146 |
| `lgbm_alpha360` | 76881 | -0.0181 | 0.1960 | -0.0924 | 45.91% | 0.0173 | 0.0922 |
| `adarnn_alpha360` | 76881 | -0.0252 | 0.2415 | -0.1044 | 43.58% | **0.0218** | 0.0900 |
| `linear_alpha360` | 76881 | -0.0257 | 0.2181 | -0.1179 | 45.53% | 0.0129 | 0.0585 |

### 10.5 结论

1. **所有模型的 Daily IC 均为负**，说明 2025-07 ~ 2026-07 这个测试段本身极难。
2. **ADARNN 没有显著优于 LightGBM**：ADARNN Rank IC 略高（0.0218 vs 0.0173），但 Daily IC 更差（-0.0252 vs -0.0181）。
3. **Linear 表现最差**：Daily IC 和 Rank IC 都是最低，说明这个市场中**非线性模型仍有一定价值**。
4. **Alpha360 比 Alpha158 更差**：对 LightGBM 来说，6 个原始特征在测试期的 alpha 弱于 Alpha158。

**核心判断：当前问题更偏向“因子 alpha 衰减”，而不是“模型不够强大”。**

### 10.6 下一步建议

既然换模型和换因子集（Alpha360）都无效，下一步应重点尝试：

1. **标签重构**
   - 把未来收益率标签换成方向性标签、夏普标签、或分位数标签。
   - 降低 2024-09·24 等极端行情对标签分布的影响。
2. **特征工程**
   - 在 Alpha158 基础上筛选稳定特征（看特征 IC 时序稳定性）。
   - 加入宏观/市场环境特征（波动率、流动性、行业动量等）。
3. **更短预测周期或更长预测周期**
   - 当前标签是次日收益率（`Ref($close, -2) / Ref($close, -1) - 1`），可尝试 5 日、10 日、20 日标签，看哪个周期在当前 regime 更稳定。
4. **如果标签重构仍无效**
   - 说明 Alpha158 这套传统价量因子在 2025-2026 年 A 股已难以产生稳定 alpha，需要考虑另类数据源或更复杂的特征构建。

---

## 12. 特征工程实验（2026-07-30）

### 12.1 实验目的

验证两个问题：
1. **特征筛选**能否提升模型在概念漂移环境下的表现？
2. **加入市场环境特征**（波动率、收益、换手率、流动性）能否带来增量 alpha？

### 12.2 实验设计

| 实验 | 特征集 | 特征数 | 说明 |
|---|---|---:|---|
| `lgbm_alpha158`（基准） | Alpha158 全量 | 158 | 已有基准 |
| `lgbm_alpha158_top30` | Alpha158 重要性 Top 30 | 30 | 基于 LightGBM gain importance 筛选 |
| `lgbm_alpha158_top60` | Alpha158 重要性 Top 60 | 60 | 保留更多重要特征 |
| `lgbm_alpha158_enhanced` | Top 30 + 市场环境特征 | 35 | 加入波动率、20日/5日收益、换手率、Amihud |

市场环境特征：
- `MKT_VOL20` = `Std($close, 20)`
- `MKT_RET20` = `$close / Ref($close, 20) - 1`
- `MKT_RET5` = `$close / Ref($close, 5) - 1`
- `MKT_TURNOVER20` = `Mean($turnover, 20)`
- `MKT_AMIHUD20` = `Mean(Abs($close/Ref($close, 1) - 1) / ($volume + 1e-12), 20)`

### 12.3 实验文件

- 特征分析：
  - [`research/analyze_feature_ic.py`](research/analyze_feature_ic.py)
  - [`research/analyze_feature_importance.py`](research/analyze_feature_importance.py)
  - [`research/prepare_feature_subsets.py`](research/prepare_feature_subsets.py)
- 自定义 Handler：[`research/handlers/alpha158_subset.py`](research/handlers/alpha158_subset.py)
- 配置生成：[`research/create_fe_configs.py`](research/create_fe_configs.py)
- 运行脚本：[`research/run_feature_engineering.py`](research/run_feature_engineering.py)
- 结果 CSV：[`research/feature_engineering_results.csv`](research/feature_engineering_results.csv)
- 特征重要性：[`research/feature_importance_named.csv`](research/feature_importance_named.csv)

### 12.4 实验结果

| 实验 | n_samples | daily_ic_mean | daily_ic_std | icir | ic_positive_ratio | rank_ic_mean | rank_icir |
|---|---:|---:|---:|---:|---:|---:|---:|
| `lgbm_alpha158`（基准） | 76881 | **-0.0059** | 0.1771 | **-0.0333** | **48.64%** | 0.0209 | 0.1146 |
| `lgbm_alpha158_top30` | 76881 | -0.0138 | 0.2187 | -0.0629 | 45.14% | **0.0244** | **0.1034** |
| `lgbm_alpha158_top60` | 76881 | -0.0146 | 0.2182 | -0.0669 | 45.14% | 0.0237 | 0.1013 |
| `lgbm_alpha158_enhanced` | 76881 | -0.0161 | 0.2181 | -0.0739 | 44.75% | 0.0231 | 0.0965 |

### 12.5 结论

1. **特征筛选改善了 Rank IC，但损害了 Daily IC**
   - Top30 的 Rank IC 从 0.0209 提升到 0.0244，说明排序能力有所改善。
   - 但 Daily IC 从 -0.0059 恶化到 -0.0138，说明筛选后的特征在方向预测上更不稳定。

2. **Top60 不如 Top30**
   - 增加特征数量没有带来收益，反而 Daily IC 和 Rank IC 都略差于 Top30。
   - 说明在尾部添加的低重要性特征主要是噪声。

3. **市场环境特征没有带来增量收益**
   - Enhanced（Top30 + 5 个市场环境特征）的表现是三个实验中最差的。
   - 加入的波动率、收益、换手率、Amihud 这些特征在当前测试期没有提供额外 alpha。

4. **核心问题仍未解决**
   - 所有实验的 Daily IC 仍为负。
   - 特征工程（筛选 + 加环境特征）只能轻微改善 Rank IC，无法让模型在 2025-07 ~ 2026-07 这个测试段恢复正向 Daily IC。

### 12.6 关键发现：单变量 IC 极弱

在特征筛选前的分析中发现：
- Alpha158 的 158 个特征在训练期（2021-2024）的**单变量 Daily IC 几乎全部接近 0**。
- 没有任何特征能通过严格的 IC 稳定性筛选（train IC > 0、valid IC > 0、IC 正比率 ≥ 55%、|ICIR| ≥ 0.1）。
- 模型的预测能力主要来自**多特征组合**，而非单个强势因子。

这说明：**当前市场环境下，传统价量因子的单因子 alpha 已经极度稀薄**。

### 12.7 下一步建议

既然“模型更换”和“特征工程”都只能边际改善 Rank IC、无法扭转 Daily IC，接下来应尝试：

1. **标签重构（最高优先级）**
   - 当前标签是次日收益率（`Ref($close, -2) / Ref($close, -1) - 1`）。
   - 尝试方向性标签、分位数标签、夏普标签、或多日收益标签（5日/10日/20日）。
   - 目标：降低 2024-09·24 等极端行情对标签分布的扭曲。

2. **预测周期调整**
   - 次日预测可能受噪声主导，尝试更长预测周期。

3. **加入真正的宏观/另类数据**
   - 如果传统价量因子已失效，需要行业景气度、资金流向、舆情、高频数据等。

4. **重新审视目标市场/股票池**
   - csi300 在当前 regime 下可能整体 alpha 稀薄，可尝试 csi500、csi1000 或行业分层。

---

## 11. 备注

- 每次优化后建议记录：daily IC、rank IC、ICIR、年化超额收益、最大回撤、换手率。
- 核心实验文件均保存在 `research/` 目录下，开发日志为 `DEV_LOG_RollingTrainingOptimization.md`。
