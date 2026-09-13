# SH000852 基准复权因子断裂修复记录 v1

## 1. 决策

状态：`repaired_verified`

**修复 5 个指数在 2026-07-24 的复权因子断裂，并修正增量更新脚本的根因。**

## 2. 问题

`update_daily_market_data_v1.py::build_index_rows()` 把 Tushare `index_daily`
的**原始点位**（如 SH000852 ~6995）直接写入 qlib binary store 的 `close` 字段，
而 store 中此前的 close 是 `raw × factor`（如 SH000852 ~7.27，factor=0.00101）。

这导致 2026-07-23 -> 07-24 出现 ~96000% 的单日跳变，任何跨该日期的回测/分析
（含 v6 的 2026 新覆盖区、v7 的 HML 信号）都被污染。

受影响指数（5 个）：

| 指数 | 07-23 close | 07-24 close（修复前） | 跳变 |
|---|---|---|---|
| SH000300 | 4.8108 | 4649.19 | +96541% |
| SH000852 | 7.2683 | 6995.69 | +96149% |
| SH000905 | 7.8367 | 7532.70 | +96020% |
| SH000906 | 5.3253 | 5139.18 | +96405% |
| SZ399300 | 4.8108 | 4649.19 | +96541% |

## 3. 修复

### 3a. 数据修复

脚本：`scripts/repair_sh000852_factor_break_v1.py`

对 5 个受影响指数，从 raw CSV（`data/external/tushare/market_daily_v1/*.csv`）
重建 2026-07-24 ~ 2026-08-07 窗口的全部字段：

- 价格字段（open/high/low/close/vwap）= `raw × factor`（factor 为 store 中的常量）
- adjclose = raw close（保持 `close / adjclose == factor`）
- volume/amount/change/factor 保持 raw

### 3b. 根因修复

`scripts/data_collector/update_daily_market_data_v1.py::build_index_rows()`：

- 修复前：`close = raw`（直接写入原始点位）
- 修复后：`close = raw × factor`（与 `build_stock_rows` 一致，价格乘以 factor）

## 4. 验证

修复后 SH000852 close 在 07-23 -> 07-24 的日收益率 = **-2.78%**（与 Tushare
`pct_chg = -0.027768` 一致），不再是 +96149%。

Post-repair audit：5 个指数全部通过（无 >20% 单日跳变）。

## 5. 影响

- v6/v7 的 2026 新覆盖区（2025-07 ~ 2026-06）回测结果不受影响（断裂在 07-24，
  在新覆盖区截止日 06-30 之后）。
- v7 的 HML 信号不受影响（HML 用 `$open` 计算，断裂窗口在 HML 信号截止之后）。
- **后续任何延伸到 2026-07-24 之后的回测/分析现在可以使用正确的基准数据。**

## 6. 可复现证据

- 修复脚本：`scripts/repair_sh000852_factor_break_v1.py`
- 根因修复：`scripts/data_collector/update_daily_market_data_v1.py`（`build_index_rows`）
- Raw CSV：`data/external/tushare/market_daily_v1/sh000852.csv`（2026-07-24 起 11 行）
- Binary store：`~/.qlib/qlib_data/cn_data_2026/features/sh000852/`
