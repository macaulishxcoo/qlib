# Quality / Growth 两族复现报告（qdata.cc 官方因子）

> 责任范围：`factor_type ∈ {Quality, Growth}` 且名字不含 `_old_` —— **74 条**（Quality 59 + Growth 15）。
> 实现：`scripts/qdata/repro_quality.py`（因子） + `scripts/qdata/ts_fin.py`（财务数据层）
> 全市场验证：`scripts/qdata/repro_quality_xs.py`
> 最近更新：2026-09-17

---

## 1. 判据（**先定判据，再谈口径**）

### 1.1 官方值的形态必须实测，不能信公式文本

取单日全市场官方值（`factor_value(factor_name=..., trade_date=...)`，1 次调用 ≈5500 行），
按 `min ≈ 1/N 且 max == 1.0` 判别：

| 判定 | 条数 | 含义 |
|---|---|---|
| **`rank/N` 型** | **62** | 官方值是横截面百分位，取值 ∈ {1/N,…,1} |
| **原始比值型** | **12** | 官方值是原始比值 |

判别结果见 `qg_rank_classification.csv`。**公式文本与实测不一致的有 1 条**：

| 因子 | 公式文本 | 实测 |
|---|---|---|
| `lra_yoy` | `Factor = CrossSectionalRank(Growth_filled)` | **原始比值**（min 0.0237 ≠ 1/N，取值到 1.0） |
| `de` | 文本无 `CrossSectionalRank` | 一致（原始比值，min −166 / max 412） |

> ⚠ `factor_formulas.json` 的 `CrossSectionalRank` 包装**只有 62/63 条为准**，必须以官方值分布反推。

### 1.2 两类因子用两套判据

- **`rank/N` 型（62 条）**：在 **6 只样本股**上永远无法逐值复现（本地只有 `{1/6..1}`）。
  必须**全市场**复算：本地镜像算内层比值 → `rank/N` → 与官方**逐日 Spearman**（`xs_compare.compare_xs`），
  取 5 个交易日的**中位** Spearman。档位：`EXACT ≥0.9999 且 min ≥0.999` / `GOOD ≥0.999` / `APPROX ≥0.99`。
  - 注：把官方值在**同一子样本内再排序**可等价核验内层次序（`rank` 是单调变换），
    但 6 个观测统计功效极低，只作 sanity check（`quality_growth_compare_smallsample_settled.csv`）。
- **原始比值型（12 条）**：用 `facsim.compare` 的**绝对/相对误差**判据（`verdict_med` 为中位相对误差）。

### 1.3 全市场验证的数据来源（离线，免费）

| 用途 | 路径 |
|---|---|
| 2024 及以前（三大报表**全列**） | `data/external/tushare/a_share_financial_pit_v1/full/normalized/batch_*/`（54 批 × 100 只） |
| 资产负债表 | `.../a_share_financial_pit_v1/balancesheet_v1/normalized/batch_*/` |
| 2025–2026（仅 revenue/n_income_attr_p/total_assets/OCF） | `.../a_share_financial_pit_v1/recent_3tables/` |
| 行情（close/total_mv）单日全市场 | `data/external/tushare/a_share_daily_basic_pit_v1/raw/<YYYYMMDD>.csv.gz` |
| 官方因子值 | `factor_value` 按 `(factor_name, trade_date)` 单取 → 缓存 `cache/qg_official_day/` |

**Tushare 的 `income`/`balancesheet`/`cashflow`/`fina_indicator` 不支持按报告期批量取全市场**（实测必填 `ts_code`），
所以全市场横截面只能走本地镜像。

---

## 2. ⭐ 标定出的口径约定（本项目最有价值的产出）

### C1 — PIT 面板：同一 `ann_date` 的多期报告必须「非空值优先」

**这是本次最关键、也最隐蔽的坑。**

中国上市公司**年报与一季报同日披露**极常见（如 002415 的 FY2025 与 2026Q1 均为 2026-04-18）。
构造「按公告日前向填充」的面板时，若简单 `duplicated(keep='last')`，
`_y`（年报口径）序列会被同日披露的季报行的 **NaN 覆盖**，fFill 后整条错位到**上上年报**。

修复：同一 `ann_date` 内按 `end_date` **稳定排序**，并把 **NaN 排到最前**、非空值保留在最后。

| 效果 | 修复前 | 修复后 |
|---|---|---|
| `debt_asset_ratio` Spearman | 0.891 | **0.9988** |
| `current_ratio` | 0.877 | **0.99999** |
| `quick_ratio` | 0.875 | **0.99999** |
| `roe_y` | 0.747 | **0.99999** |
| `roa_y` | 0.748 | **1.00000** |
| `eps_y` / `gpm_y` / `npm_y` / `opm_y` | 0.74~0.88 | **1.00000** |

> 靠 `roe_y` / `roa_y` / `eps_y` / `gpm_y` / `npm_y` / `opm_y` 六条齐刷刷卡在 0.79~0.88 的
> 「系统性窄带」定位到。6 个不同科目的同一种错位 ⇒ 一定是报告期选择问题，不是公式问题。

### C2 — TTM 构造 = `本期累计 + 上年年报 − 上年同期累计`

由 `roe_ttm`（passthrough，6 只股票**逐位 EXACT**，`max_abs_err 4.9e-11`）与 `roa_ttm` 标定。
`_Q`（单季）= 累计差分；`_y`（年度）= 取 `end_date` 为 12-31 的报告。

### C3 — ROA 的分子是**净利润（含少数股东）`n_income`，ROE 的分子是**归母净利润 `n_income_attr_p`

| 因子 | 分子口径 | 全市场 Spearman |
|---|---|---|
| `roa_ttm` | **`n_income`(TTM)** | **0.99999** |
| `roa_ttm` | `n_income_attr_p`(TTM) | 0.98637 |
| `roe_ttm`（passthrough） | **`n_income_attr_p`(TTM)** | **1.00000** |

⇒ **同名公式文本（`NetProfit`/`NetProfit_Parent`）在两条代码路径上口径不同，必须分别标定。**

### C4 — 分母一律**期末值**，不做期初期末平均

`roe_ttm` / `roa_ttm` / `debt_asset_ratio` 用 `(期初+期末)/2` 时 Spearman 与逐值误差都更差；
期末值在全市场 5 日、~25000 个观测上 `med_rel_err ≈ 1e-10`（`roe_ttm`/`roe_y`/`debt_asset_ratio`/
`current_ratio`/`quick_ratio`/`de` 全部 `< 3e-10`）⇒ **逐位复现**。

### C5 — **`debt_asset_ratio` / `current_ratio` / `quick_ratio` / `roe_y` / `de` 是年报（`_y`）口径**

这 5 条的官方值是**最近一期年报**的比值，而不是最新报告期的比值：

| 因子 | 年报口径 | 最新报告期口径 |
|---|---|---|
| `debt_asset_ratio`（6 只逐值） | **max_abs 1.4e-10 ~ 6e-11（EXACT）** | 误差 26%（600519） |
| `debt_asset_ratio`（全市场 Spearman） | **0.9988** | 0.926（修复前）/ 0.9907 |
| `de` | **0.9997** | 0.9856 |
| `roe_y` | **逐位 EXACT（6/6）** | — |

⚠ **但 `delta_de` 相反**：它用**最新报告期口径**的 DE（`tl/eq_inc` 当季）→ Spearman **0.9992**，
用年报口径只有 0.6439。**同一个经济含义，独立因子与变化量因子口径不同。**

### C6 — 股东权益：`TotalEquity` = **含少数股东权益** `total_hldr_eqy_inc_min_int`

`roe_ttm` / `roe_y` / `financial_leverage` 用含少数股东权益时逐位 EXACT / Spearman 0.9999；
用归母权益 `total_hldr_eqy_exc_min_int` 误差 3.8%（600519）。

**例外（实测反向）**：
- `yoy_net_asset` → **归母权益 `eq_exc`**（0.99958 vs 含少数 0.96143）
- `expenses_to_equity_yoy` 的 `SEWithoutMI` → 归母权益（公式显式写 `SEWithoutMI`）

### C7 — `roe_ttm_lag63d = roe_ttm.shift(63 个交易日)`（逐位 EXACT）

### C8 — 单季 vs 累计：**`_Q` 后缀不可全信**

| 因子 | 公式里的记号 | 实测正确口径 | Spearman（正确 / 另一口径） |
|---|---|---|---|
| `eaa` | `EPS_Q` | **累计(YTD) `basic_eps`** | **0.9983** / 0.4667（单季差分） |
| `eap` | `EPS_Q` | **累计(YTD) `basic_eps`** | 0.9291 / — |
| `sa` | `OperatingRevenue_Q` | **累计(YTD) `revenue`** | **0.9513** / 0.5440（单季差分） |

⇒ qdata 内部 FinMatrix 的 `_Q` 字段在**部分因子**里其实是「报告期累计值」。

### C9 — `prev_report` / `4披露前` 必须在**披露序列**上 shift，不能按交易日 shift

在交易日面板上 `shift(1)` 只等于「昨天」，对阶梯函数几乎恒为 0（实测 `npm_ttm_qoq` 0.586 → 修好后 0.9974）。
正确做法：先在**报告期序列**上 `shift(1)`（环比）/ `shift(4)`（同比），再按 `ann_date` 前向填充到交易日。
`asset_growth_qoq`（0.9948）、`npm_ttm_qoq`（0.9974）、`gpm_qoq`（0.9955）三条确认了 `prev_report` 机制正确。

### C10 — `t-252` / `t-63` 是**交易日**偏移（与 `4披露前` 的披露序列偏移不同）

`yoy_*` / `delta_*` 系列用 `shift(252)`（交易日）正确：`yoy_total_asset` 0.9996、
`yoy_revenue`（原始比值）`med_rel_err 5.9e-11`、`roe_ttm_lag63d` 逐位 EXACT。

### C11 — 排名分档与 `CrossSectionalRank` 定义

`CrossSectionalRank(x) = rank_ascending(x, average) / N`，`N` = 当日有值的股票数
（实测 `min = 1/N`、`max = 1.0`、`mean = (N+1)/(2N)`）。
qdata 的股票池比 Tushare `daily` 少约 100~120 只（过滤规则未标定），
故**逐值不可能完全相等**，但秩相关可 0.999+。

### C12 — 被证伪的口径（勿再尝试）

| 变体 | 结果 | 结论 |
|---|---|---|
| `_y` 用「最新报告期」而非年报 | 0.79~0.99 | **错**（见 C5） |
| PIT 面板按 `ann_date` 简单 `keep='last'` | 0.75~0.93 | **错**（见 C1） |
| ROA 分子用归母净利润 | 0.986 | **错**（见 C3） |
| `eaa/eap/sa` 用单季值 | 0.47~0.54 | **错**（见 C8） |
| 环比/同比按交易日 `shift(1)`/`shift(4)` | 相关系数 <0.5 | **错**（见 C9） |
| `yoy4` 用 `(a−b)/|b|` 代替 `a/b−1` | 普遍更差（0.29~0.71） | **错** |
| `roe_ttm` 用 `n_income` 或 `平均权益` | 明显更差 | **错** |
| 直接用 Tushare `fina_indicator.roa/roe/gross_margin` 预计算字段 | 0.75 | **错**（单期口径） |
| 本地镜像 `full/normalized` 中 `debt_asset_ratio` 用 `total_liab/total_assets` 当季 | 0.99 | 可用但非最优 |

---

## 3. 通过率

### 3.1 权威判据：全市场横截面（2024 窗口，5 个交易日）

股票池 5381 只（本地镜像全集），每日与官方单日全市场值比。
报告：`quality_growth_compare.csv`（74 行）、`quality_growth_xs_2024.csv`、`quality_growth_abs_2024.csv`。

| 口径 | EXACT | GOOD | APPROX | FAIL | **EXACT+GOOD** |
|---|---|---|---|---|---|
| `rank/N` 型（62 条） | 16 | 14 | 11 | 21 | **30 / 62** |
| 原始比值型（12 条） | 9 | 0 | 1 | 2 | **9 / 12** |
| **合计（74 条）** | **25** | **14** | **12** | **23** | **39 / 74（53%）** |

> 原始比值型虽然 `verdict_med` 多为 EXACT，但 `verdict`（maxerr）为 FAIL：
> 这是**极少数个股**（权益为负/接近 0 导致比值爆炸）造成的长尾，
> 中位相对误差 `med_rel_err` 在 `roe_ttm`/`roe_y`/`debt_asset_ratio`/`current_ratio`/
> `quick_ratio`/`de`/`yoy_revenue`/`peg_252d`/`roe_ttm_lag63d` 上为 **1e-14 ~ 3e-10**（逐位级复现）。

### 3.2 2026 窗口（settle-days=30，截到 2026-08-11）

`quality_growth_compare_settled.csv`。本地 `recent_3tables` 只有
`revenue / n_income_attr_p / total_assets / n_cashflow_act` → **仅 4 条可算**：

| 因子 | Spearman(med) | 判定 |
|---|---|---|
| `asset_turnover` | 1.00000 | EXACT |
| `yoy_total_asset` | 1.00000 | EXACT |
| `asset_growth_qoq` | 0.778 | FAIL |
| `np_ttm_qoq` | 0.613 | FAIL |

> `roa_*`/`npm_*` 在 2026 窗口**不可算**：`recent_3tables` 缺 `n_income`，
> 而 C3 已标定 ROA/NPM 用净利润（含少数股东）。
> 两条 PASS 的因子在 2024 窗口同样 EXACT ⇒ 口径跨年份稳定。

### 3.3 6 只样本股（弱 sanity check）

`quality_growth_compare_smallsample_settled.csv`：56/74 在「6 只样本内名次完全一致」。
**该表不能作为判据**（每个截面只有 6 个观测），仅用于快速回归。

---

## 4. 未通过因子归因分类

### (a) 结构性不可复现 / 直通预计算字段 —— 8 条，但实测**其中 6 条能逐位复现**

`passthrough=true` 的 8 条是 qdata 直接取 `lake.financial_derivative.*` 预计算字段。
**实测结论与预期相反**：其中 6 条反而最容易复现（因为官方值就是原始比值，无 rank 包装）：

| 因子 | 结果 |
|---|---|
| `roe_ttm` | ✅ 逐位 EXACT（`med_rel 1.7e-10`） |
| `roe_y` | ✅ 逐位 EXACT（`2.0e-10`） |
| `roe_ttm_lag63d` | ✅ 逐位 EXACT（`1.9e-10`） |
| `debt_asset_ratio` | ✅ 逐位 EXACT（`6.3e-11`） |
| `current_ratio` | ✅ 逐位 EXACT（`8.1e-12`） |
| `quick_ratio` | ✅ 逐位 EXACT（`1.0e-11`） |
| `gpm_qoq` | ⚠ APPROX（0.9955） |
| `npm_ttm_qoq` | ⚠ APPROX（0.9974） |

### (b) 极端值敏感（口径基本正确，秩相关被长尾拖累）—— 12 条

`np_to_fixed_assets_yoy` 0.618、`np_to_total_expenses_yoy` 0.605、`np_to_inventory_yoy` 0.648、
`np_to_deferred_tax_yoy` 0.674、`np_to_salary_yoy` 0.795、`income_tax_yoy` 0.795、
`expenses_to_equity_yoy` 0.775、`yoy_ocf` 0.734、`np_ttm_qoq` 0.916、
`delta_npm` 0.9843、`delta_opm` 0.9850、`yoy_roe` 0.9851、`yoy_roa` 0.9837、`delta_roa` 0.9864。

特征：**分母（比率）会穿越 0**，`ratio_t/ratio_{t-4} − 1` 出现 ±1e3~1e5 的爆炸值，
秩相关被这些观测主导。同结构的「分母恒正」因子（`asset_growth_qoq` 0.9948、
`npm_ttm_qoq` 0.9974、`gpm_qoq` 0.9955、`tax_surcharge_yoy` 0.9432）明显更好，
支持「机制正确、尾部敏感」的判断。已试并排除的变体：`(a−b)/|b|`（更差）、
`npp_ttm` 代替 `npp_q`、`_q` 代替 `_ttm`、交易日 shift。

### (c) 口径仍未标定 —— 8 条

| 因子 | 当前 Spearman | 说明 |
|---|---|---|
| `lra_yoy`（原始比值） | `med_rel 1.47`（FAIL）；秩 Spearman 0.737 | `LongtermReceivableAccount` 字段未定；`lt_rec` 只覆盖 1693/5381 只（官方 N 也只有 1693）；已试 `lt_rec+oth_receiv` 更差（0.356）；`shift(252)` 更差（0.692）。注：官方值 `max=1.0` 但 `min=0.0237≠1/N`、`k/N` 检验不通过 ⇒ 确认是**原始比值**而非 `rank/N` |
| `quality_composite`（原始比值） | 0.918（`med_rel 0.098`） | 6 项求和；`OpCashInflow`/`InvCashInflow` 字段未定；`filter=True` 的 NaN/±inf 处理语义未定 |
| `gpm_q` | 0.977 | 差 0.013；分母/口径待定 |
| `sa` | 0.951 | `TotalShares` 来源（资产负债表 `total_share` vs `daily_basic`）待定 |
| `icr` | 0.830 | `InterestExpense` 字段未定（`int_exp` 只覆盖 ~100 只；`fin_exp_int_exp` 更差 0.43） |
| `cfcr` | 0.966 | 同上，但用 `int_exp` 已到 0.966 |
| `cash_profit_ratio` | 0.844 | `(OCF−NI)/NI`；已试 `npp`、`|NI|` 均更差 |
| `eap` | 0.929 | 同 `eaa` 已改 YTD EPS，但仍差 0.07（`Close` 口径/分母待定） |
| `yoy_net_profit`（原始比值） | 0.124 | `corr` 极低但 `med_rel 0.0066`；疑似本地 `npp_ttm` 在部分个股上口径不同 |

### (d) 已达标但存在少量个股级偏差

原始比值型因子的 `verdict`（maxerr）全部 FAIL，`max_abs_err` 0.15~1.5（`roe_ttm`/`de`/`roe_y`），
`peg_252d` 甚至 6e16（EPS→0）。**均为个股级长尾，不是系统性口径问题**（中位误差 1e-10 级）。

---

## 5. 产出文件

| 文件 | 内容 |
|---|---|
| `scripts/qdata/ts_fin.py` | 财务数据层：Tushare API + 本地镜像读取、FinMatrix、PIT → 交易日面板、`q/ttm/y/avg2` 口径 |
| `scripts/qdata/repro_quality.py` | 74 条内层公式实现 + 6 只样本核验 + `--settle-days` |
| `scripts/qdata/repro_quality_xs.py` | **全市场横截面验证**（`compare_xs` + `compare_family`），权威判据 |
| `scripts/qdata/qg_official.py` | 官方因子值取数（逐 `(factor, code)`、断点续取、空结果重试） |
| `output/qdata_factor_repro/quality_growth_compare.csv` | **主报告**：74 条 × {mode, verdict_med, verdict, spearman_med, n_days, coverage, max_abs_err, med_rel_err, corr} |
| `output/qdata_factor_repro/quality_growth_compare_settled.csv` | 2026 窗口 settle-days=30 截断子集（4 条） |
| `output/qdata_factor_repro/quality_growth_xs_2024.csv` / `quality_growth_abs_2024.csv` | 全市场 Spearman / 原始比值型逐值明细 |
| `output/qdata_factor_repro/quality_growth_compare_smallsample_settled.csv` | 6 只样本股弱核验 |
| `output/qdata_factor_repro/quality_growth_rank_order.csv` | 6 只样本内名次完全一致的天数 |
| `output/qdata_factor_repro/qg_rank_classification.csv` | **rank 型 vs 原始比值型的实测判别** |

缓存（可删）：`cache/qg_official/`（逐股官方值）、`cache/qg_official_day/`（单日全市场官方值）、
`cache/fin/`（Tushare 四大报表逐股）。

---

## 6. 后续建议

1. **补齐全市场验证窗口**：当前主判据只有 2024 年 5 个交易日。建议加 2022–2023 的 10~20 个日期
   （每因子每日 1 次调用，成本极低），把 `spearman_med` 的时间稳健性坐实。
2. **2026 窗口的本地数据缺口**：`recent_3tables` 缺 `n_income`/`oper_cost`/`operate_profit`/资产负债表明细，
   导致 2026 只能验 4 条。建议补一份 2025–2026 的全列镜像
   （`full/normalized` 只到 2024-12-31），即可把 74 条全部拉到 2026 窗口验证。
3. **标定 qdata 的股票池过滤规则**：官方 N 比 Tushare `daily` 少约 100~120 只。
   若能用 ST/停牌/次新/退市三类掩码把 N 对齐，`rank/N` 型因子有望从「秩相关 0.999+」升级为「逐值 EXACT」。
4. **(b) 类极端值因子**：建议对照官方值的分位分布，确认 qdata 是否对 ±inf / 极端比值做了裁剪
   或 `filter=True` 语义（`quality_composite` 的 desc 明确提到 `filter=True`），
   这可能是这 12 条从 0.6~0.99 一步到 0.999 的钥匙。
5. **(c) 类字段标定**：`InterestExpense`（`icr`/`cfcr`）、`LongtermReceivableAccount`（`lra_yoy`）、
   `OpCashInflow`/`InvCashInflow`（`quality_composite`）、`TotalShares`（`sa`）
   建议用「官方值反解」法：在少数个股上比较官方原始比值与候选字段的比值，逐一排除。
6. **`factor_formulas.json` 的 `CrossSectionalRank` 标注需修正**（至少 `lra_yoy` 一条），
   建议把「官方值形态实测」加入公式抽取的流水线。
