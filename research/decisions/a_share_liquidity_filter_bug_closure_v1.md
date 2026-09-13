# 流动性过滤缺陷：根因、修复与 50 万口径影响

| 项 | 值 |
|---|---|
| 缺陷 | `load_amount_avg` 返回**零列**，导致五因子线的流动性过滤**从未生效** |
| 根因 | 模块级常量冲突 → 查询窗口**倒置** |
| 修复 | `scripts/backtest_a_share_value_quality_monthly_sensitivity_v4.py::load_amount_avg` |
| 50 万口径影响 | **−0.38pp**（过滤生效后 full +13.83% → +13.45%）——与预测一致 |
| 日期 | 2026-09-13 |

## 1. 根因（干净地定位到了）

```text
warm_start = 2026-08-03      end_time (BT_END) = 2025-06-30
                             ↑ warm_start > end_time  →  窗口倒置
```

`load_amount_avg` 原实现使用**本模块的** `BT_START`/`BT_END`。而
`backtest_a_share_value_quality_monthly_sensitivity_v4.py` 是**另一条实验线的脚本**，
它的 `BT_START` 是近期日期。当五因子线调用它时：

```python
warm_start = calendar[calendar.searchsorted(BT_START) - 30]   # -> 2026-08-03
D.features(..., start_time=warm_start, end_time=BT_END)       # 倒置 -> 0 行
piv = raw.pivot_table(...)                                    # -> 0 列
```

调用方拿到 0 列 DataFrame，`avg` 全为 NaN，而 `NaN < 门槛` 恒为 `False`
→ **一个候选都不过滤，且不报错**。

## 2. 修复

改为由**传入的 calendar** 决定窗口（不再依赖模块级常量），并显式检查倒置：

```python
s = pd.Timestamp(start) if start is not None else calendar[0]
e = pd.Timestamp(end)   if end   is not None else calendar[-1]
pos = int(calendar.searchsorted(s)); warm_start = calendar[max(0, pos - 30)]
if pd.Timestamp(warm_start) >= pd.Timestamp(e):
    raise ValueError("窗口倒置 ...")      # 同类问题今后会立刻报错而非静默失效
```

**验证**：同一调用由 `shape=(2843, 0)` 变为 **`shape=(2843, 3)`，每列 2,839 个非空**。

## 3. 50 万口径的影响：与预测一致，几乎为零

修复前预测：50 万门槛 = 66.7 万元/日，实测**全市场 98.9% 通过**（1 亿门槛只 34.7% 通过），
故对 50 万配置应几乎无影响。

**实测验证**：

| stage | 过滤失效（原） | **过滤生效（修复后）** | 差 |
|---|---|---|---|
| development | +24.26% | +23.41% | −0.85pp |
| confirmation | +4.13% | +4.00% | −0.13pp |
| holdout | +16.92% | +16.84% | −0.08pp |
| new_coverage | −6.65% | −6.67% | −0.02pp |
| **full** | **+13.83%** | **+13.45%** | **−0.38pp** |
| full IR | 1.203 | 1.172 | −0.031 |

**每期平均候选数：2,924（过滤生效）vs 2,925（失效）** —— 平均只剔除 **1 只**。

→ **过滤在 50 万口径下确实几乎不 binding，此前的 no-op 对该策略无害。**

## 4. 但有一个必须记录的推论（尚未验证）

同样的缺陷在**项目自己的 1 亿口径**下**不是无害的**：

```text
1亿门槛 1.33亿/日 → 全市场仅 34.7% 通过
```

即项目既有五因子线所报告的"名义流动性/容量控制"从未生效，
**其实际池约 2,925 只而非设计中的约 1,000 只**。
由于小市值/低价端收益为正，该 no-op 很可能**高估**了该线的表现。

**要求**：在把五因子线当作既有成果引用前，必须先用修复后的 `load_amount_avg`
在 1 亿口径下重跑一次。**本次未做**（另需约 30 分钟重建快照），列为待办。

## 5. 同类缺陷清单（"静默失效"家族）

| 缺陷 | 表现 | 状态 |
|---|---|---|
| `load_amount_avg` 零列 | 流动性过滤 no-op | **已修复** |
| store 日历领先行情 21 天 | 实盘清单全 NaN | 已修复（含断言） |
| `get_holdings_on` 用 `<=` | 每个调仓日 1 日前瞻 | 已修复 |
| 强制保留逻辑取反 | 组合冻结、换手 0.6 | 已修复 |
| 缓冲带无界 | 持仓膨胀至 875 只 | 已修复 |

**共性**：都不报错，只是安静地给出错误结果。
**对策（已写入治理）**：关键量必须做**量级断言**（换手、候选数、仓位利用率、价格非空率）。
