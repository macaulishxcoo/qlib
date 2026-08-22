# 五因子 top-15 + 行业暴露上限回测协议 v3

## 1. 状态与授权

状态：`frozen_awaiting_run`（2026-08-18）
前置：五因子 v2（regime_robust_improved）、top-K sweep（top-15
月均单行业 24.3%、前三 55.4%；2026-06 极端月单行业 36.7%）。

单一变量：在五因子 top-15 基线上，**唯一改动是选股最后一步加行业
暴露上限约束**。其余全部照抄 v2（composite5 ≥4/5、ST/容量/中性化/
top-15/成本/执行）。

## 2. 行业约束规则（冻结）

- **单行业上限 = 3 只**（3/15 = 20%，vs 无约束月均 24.3%、极端 36.7%）
- 实现方式：在 `neutral_composite` 排序选 top-15 时，按分数从高到低
  依次选入，当某行业已有 3 只入选则跳过该行业后续候选，由下一名
  替补（greedy 贪心算法，不重新优化权重）
- 约束作用于中性化后的 `neutral_composite` 排序阶段，不改 composite5
  分数本身
- 上限设 3 而非 2：2/15 = 13.3% 过于严格（通信运营商 3 只会强制
  拆散），3/15 = 20% 是自然分界（top-30 月均 20.2%）

## 3. 对照臂（同环境四臂）

| 臂 | 说明 |
|---|---|
| top15_free | 五因子 top-15 无约束（= v2 的 top-15 版本） |
| **top15_cap3** | **五因子 top-15 + 单行业 ≤3** |
| top30_free | 五因子 top-30 无约束（sweep 结果已有） |
| top30_cap3 | 五因子 top-30 + 单行业 ≤3（附加对照） |

主判定：top15_cap3 vs top15_free
- holdout IR 不降超 0.10（约束的代价）
- 全期 IR 不降超 0.05
- 单行业月均占比从 24.3% 降到 ≤20%

附加判定：top15_cap3 vs top30_free（回答"15 只够不够"）
- 如果 top15_cap3 的全期 IR ≥ top30_free 的 0.90，则 15 只
  + 约束足以替代 30 只

## 4. 产物

`output/analysis_fundamental/a_share_value_growth_five_factor_industry_cap_v3/`

## 5. 不授权调优

- 不试 cap=2 或 cap=4
- 不试行业二级行业约束
- 不试优化权重（保持等权）
