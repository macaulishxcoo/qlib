# 低名义价格作为显式因子 —— 协议 v1

状态：`design_frozen_before_data`

## 1. 背景

上一轮在 6 个底仓的迁移检验中发现：**`lowprice`（低名义价格）是唯一为正的单因子**
（full 净超额 +4.82% / IR +0.286，其余五个底仓全为负）。

但它此前是通过**价格可行性过滤**（排除买不起的高价股）被动引入的。
本协议问两个问题：

```text
Q1 (正交性): lowprice 与五因子(尤其 EP/BM 这类"便宜"因子)是否高度重叠?
             若高度重叠, 它只是价值因子的另一种表达, 不应重复计入。
Q2 (增量)  : 把 lowprice 显式加入复合分, 是否在扣成本后带来增量?
```

## 2. 冻结的诊断端点

**正交性**：每个调仓日计算 `lowprice` 与各因子的**截面 Spearman 相关**，
再对 255 个调仓日取均值：

```text
corr(lowprice, X)  for X in {ep, bm, div_yield, accruals, g2, composite5}
```

| 判定 | 阈值（冻结） |
|---|---|
| 高度重叠（视同价值因子） | 与 composite5 的 \|corr\| **> 0.5** |
| 中度相关 | 0.25 ~ 0.5 |
| 基本独立 | < 0.25 |

## 3. 冻结的增量检验

```text
composite6 = mean( pct_rank(ep), pct_rank(bm), pct_rank(div_yield),
                   pct_rank(accruals), pct_rank(g2), pct_rank(lowprice) )
             需 >= 5 个非空 (原五因子需 >=4)
lowprice   = -close(asof_date)
```

三臂对照（其余完全不变：top30、行业cap3、10 交易日调仓、50万、stress 成本、毒尾否决）：

| 臂 | 复合分 | 价格可行性过滤 | 作用 |
|---|---|---|---|
| **A** | composite5 | 有 | **= 当前最终策略（基线）** |
| **B** | composite6 | 有 | 隔离"显式加入 lowprice"的增量 |
| **C** | composite6 | 无 | 检验是否与价格过滤重复计入 |

## 4. 判定

| 结论 | 条件（**全部满足**） |
|---|---|
| `adopt` | B 相对 A 全期净超额提升 > 0，且 **holdout 段不劣化超过 1pp**，且 Q1 显示 \|corr\| ≤ 0.5 |
| `redundant` | Q1 显示 \|corr\| > 0.5（即使 B 提升也不采纳，避免重复计入） |
| `reject` | B 相对 A 提升 ≤ 0 或 holdout 明显劣化 |

## 5. 结论边界

1. 本协议**不主张 lowprice 是新因子**——它已被上一轮证明存在；
   本协议只回答"是否应显式纳入、是否与价值因子重复"。
2. `lowprice` 的 new_coverage 段为 −24.04%，**regime 依赖**；
   即使采纳，也必须标注该局限。
3. 不做事后调整：阈值 5 个非空、corr 门槛 0.5、三臂结构全部冻结。
4. 本检验仍在同一市场同一时段，不构成时间维度样本外。
