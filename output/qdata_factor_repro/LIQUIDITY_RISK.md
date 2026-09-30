# qdata.cc Liquidity / Risk 两族复现报告

> 批次：**Liquidity（35）+ Risk（25）= 60 条**（已排除 `_old_` 快照）
> 实现：`scripts/qdata/repro_liquidity_risk.py`（新增指数层 `scripts/qdata/ts_index.py`）
> 公式来源：`output/qdata_factor_repro/factor_formulas.json`（逐条读，非记忆）
> 判定口径：`scripts/jqdata/facsim/compare.py`（`verdict_med` = 中位相对误差，推荐主判据）
> 报告：`liquidity_risk_compare.csv`（全窗口）、`liquidity_risk_compare_settled.csv`（`--settle-days 30`）
> 日期：2026-09-17 ｜ 面板 2013-01-04 ~ 2026-09-10（3325 交易日）× 6 只标的

---

## 0. 结论速览

| 口径 | 全窗口 | 已沉淀窗口（判定口径，2026-06-01~08-11） |
|---|---|---|
| `verdict_med` 通过（EXACT+GOOD） | **60/60（100%）** | **60/60（100%）** |
| `verdict_med` 分布 | EXACT 36 / GOOD 24 | EXACT 34 / GOOD 26 |
| `verdict`（maxerr 严格）通过 | 58/60 | 58/60 |
| `verdict` 分布 | EXACT 33 / GOOD 25 / APPROX 2 / FAIL 0 | EXACT 33 / GOOD 25 / APPROX 2 / FAIL 0 |

**按族（已沉淀窗口）**

| 族 | 条数 | 已实现 | `verdict_med` EXACT | GOOD | 通过率 | `verdict` APPROX | FAIL |
|---|---|---|---|---|---|---|---|
| Liquidity | 35 | 35 | 22 | 13 | 35/35 | 0 | 0 |
| Risk | 25 | 25 | 12 | 13 | 25/25 | 2 | 0 |

- **跳过 0 条**：两族 60 条全部实现并有官方重叠样本，`coverage = 1.00`，`n_overlap = 306`（沉淀）/ `438`（全窗口）。
- 全窗口与沉淀窗口结论**几乎一致** ⇒ 本族基本**不受 G2「尾部未沉淀窗口」影响**
  （该现象集中在 EMA 族；本批仅 `EMA`-free 的滚动统计，故无需靠截断救回任何因子）。
- 唯二 maxerr 档 APPROX 的因子（`sharpe_750d` / `adjusted_sharpe_750d`）中位误差仅
  3.4e-06 / 2.0e-06，**中位口径为 GOOD**；maxerr 由长窗口上的单点数据微差支配（见 §4）。

---

## 1. ⚠ 全局数据层发现（对全项目通用，建议并入 `CONVENTIONS.md`）

### 1.1 `ts_env.load_panel` 的 `AMOUNT` / `V` 已被乘过 `adj_factor`

`ts_env.py` 把 `open/high/low/close/vol/amount` **统一** `× factor`（`factor = ADJ`）。
因此 **原始成交额 = `panel.AMOUNT / panel.ADJ`（单位千元）**，
**原始成交量 = `panel.V / panel.ADJ`（单位手）**。

这是本批最"坑"的一条：`amount_ma_20d` 用 `AMOUNT` 直接算得 rel **1.18 ✗**，
除以 `ADJ` 后 rel **3e-16 ✓**。凡是需要**不复权**成交量/成交额的因子（流动性、量价、
Alpha101 的 V 类）都必须先还原。`panel.vwap_raw()` 之所以正确，是因为
`(amount×ADJ)×10/(vol×ADJ)` 中 `ADJ` 恰好抵消。

### 1.2 `TurnoverAmount` 的单位是「元」

Tushare `daily.amount` 单位「千元」⇒ 官方口径 = **千元 × 1000**。

| 因子 | 实现 | max_abs_err | 判定 |
|---|---|---|---|
| `amount_ma_20d` | `MA(AMT/ADJ × 1000, 20)` | 9.54e-07 | EXACT |
| `amount_ma_20d` | `MA(AMT/ADJ, 20)`（千元） | 1.4e+09 | FAIL（rel 1.18） |
| `amount_ma_20d` | `MA(AMT, 20)`（未还原） | 1.2e+09 | FAIL |
| `sum_abs_rtn_amount_20d` | `Σ\|ret,20\| / Σ(amt_元,20) × 1e8` | 4.99e-16 | EXACT |
| `sum_abs_rtn_amount_20d` | 同上但成交额用千元 | 0.234 | FAIL（rel 1.1e+03） |

### 1.3 指数行情：`000001` 后缀 = **上证指数 `000001.SH`**

不是平安银行 `000001.SZ`。`index_daily` 无复权概念，直接用 `close`；
`vol` 单位手、`amount` 单位千元（与 `daily` 一致）。见 `scripts/qdata/ts_index.py`。

---

## 2. 口径标定（逐条 + 验证因子）

> 每一条都是**实测变体对照**的结果，不是文档推测。判定用 `verdict_med`（中位相对误差）。

### L1 `AMOUNT`/`V` 需 `/ADJ` 还原 — 见 §1.1
验证因子：`amount_ma_20d`、`sum_abs_rtn_amount_20d`，以及 `turnover_ma_*`（成交量）、
`volume_alpha_*` / `volume_beta_*`（成交量动量）。

### L2 `TurnoverAmount` 单位 = 元 — 见 §1.2
验证因子：`amount_ma_20d`、`sum_abs_rtn_amount_20d`。

### L3 ✅ **`DailyTurnoverRate` = Tushare `daily_basic.turnover_rate / 100`（小数）**

公式写 `Volume / AShares`，`AShares` 确为**流通股本**；但官方**直接使用供应商已四舍五入
的 `turnover_rate` 字段**，而不是自算 `vol/float_share`。

| 换手率口径 | `avg_turnover_5d` | `std_turnover_21d` | `bias_turn_21d_252d` |
|---|---|---|---|
| **`turnover_rate`/100（本实现）** | **2.1e-16 EXACT** | **9.8e-09 EXACT** | **≈1e-08 EXACT** |
| 自算 `vol(股)/float_share(股)` | 1.08e-05 | 1.59e-05 | ≈2e-05 |
| `turnover_rate_f`/100（自由流通股本） | 7.4e-01 ✗ | 6.2e-01 ✗ | ✗ |
| `vol / total_share` | 8.1e-01 ✗ | ✗ | ✗ |
| ×100（百分数量纲） | 81.6 ✗ | 65.4 ✗ | ✗ |
| `std` 用 `ddof=0` | — | 1.6e-02 ✗ | — |

⚠ 前两行**数值上只差 ~1e-5 相对**，打印出来完全一样（`0.00201995`），
**只有逐位比对才暴露** —— 这是一条"看起来等价、其实不等价"的口径。
验证因子：全部 29 条换手率族（`avg_turnover_{5,10,20,21,42,63,126,252}d`、
`std_turnover_{21,42,63,126,252}d`、`bias_turn_{21,42,63,126}d_{252,504}d`、
`bias_std_turn_{21,42,63,126}d_{252,504}d`）。

### L4 ✅ `turnover_ma_*`：`VolCapRatio = Volume(股) / (ClosePrice_原始 × FloatShares)(元)`，结果**取负**

| 变体 | `turnover_ma_20d_120d` | 判定 |
|---|---|---|
| **原始收盘 × 流通股本（本实现）** | **5.8e-10** | EXACT |
| 后复权收盘 × 流通股本 | 4.9e-03 | FAIL |
| `vol / circ_mv`（万元，未换算） | ~1e+02 | FAIL |

注意该因子量级 ~1e-6（若用「元」/「手」混算会偏 1e+02 倍）：
它**不是换手率**，而是"成交额换手"再除以价格。验证因子：`turnover_ma_20d`（2.6e-08）、
`turnover_ma_20d_120d`（5.8e-10）。

### L5 ✅ `bias_turn_{s}d_{l}d` 的两个数字 = **短窗口 s×21 日 / 长窗口 l×21 日**

`21d_252d → MA(turn, 1×21) / MA(turn, 12×21) − 1`；`504d → 24×21`。
（`params` 字段为空，靠公式里显式的 `w=1*21` / `w=12*21` / `w=24*21` 确定。）
验证因子：16 条 `bias_*_turn_*`（`bias_std_turn_21d_504d` max_abs_err 4.98e-11 = EXACT）。

### L6 ✅ `high_low_{n}d` = 窗口内 `Close_hfq` 极值比

`NetValue_t = CumulativeProduct(1+DailyReturn)`，而 `DailyReturn` = 后复权收盘日收益
⇒ `NetValue ∝ Close_hfq`，`Max/Min` 与常数因子无关 ⇒ **等价于 `Max(C_hfq,n)/Min(C_hfq,n)`**。
验证因子：`high_low_{21,42,63,126,252}d`（max_abs_err 4.8e-11 ~ 5.0e-11 全 EXACT）。

### L7 ✅ 滚动回归族（`beta_*` / `sigma_*` / `beta_consistency_*` / `volume_alpha_*` / `volume_beta_*`）

- 收益 = **简单收益** `pct_change()`（延续 G4）；对数收益更差（`sigma` 由 2.9e-07 → 7.0e-03）。
- 指数 = `index_daily.close`，**不复权**；滚动窗口**含当日**（延续 G3）。
- `beta = Cov/Var`。
  验证因子：`beta_60d_000300` / `beta_125d_000300` / `beta_250d_000300` / `beta_500d_000300`
  全窗口 max_abs_err **5e-11（EXACT）**；`volume_beta_120d_000300` 同为 5e-11 EXACT。
- `volume_alpha_300d_*` = 上式回归的**截距 α = ȳ − β·x̄**，双指数验证 GOOD（3.4e-09 / 5.4e-09）。
- 收益序列需处理停牌缺失：`C.pct_change().fillna(0)`。实测在比对窗口内**无差异**
  （面板 2020 年后无缺失），仅用于让双层窗口良定义。

### L7a ✅✅ **`sigma` / `beta_consistency` 是"日频残差序列"的再滚动（双层窗口）**

公式 `Sigma = StdDev(Residual) over 1320 days` 中的 `Residual` 是**日频残差序列**

```
Residual_t = r_t − α_t − β_t·R_t      （α_t, β_t 取自"以 t 结尾"的滚动 1320 日回归）
sigma_1320d  = Residual.rolling(1320).std(ddof=1)
beta_consistency_1320d = (β_t × Residual_t).rolling(1320).std(ddof=1)
```

⇒ **有效回看 = 2×1320 = 2640 个交易日（≈10.5 年）**，面板起点必须 ≤ 2014-01-01。

| 实现变体 | `sigma_1320d_000001` | `sigma_1320d_000300` | `beta_consistency_1320d_000300` |
|---|---|---|---|
| **日频残差再滚动（本实现）** | **2.85e-07 GOOD** | **3.44e-07 GOOD** | **1.20e-06 GOOD** |
| 窗口内残差 `std`（直觉错解） | 2.11e-03 APPROX | 1.53e-03 APPROX | 1.33e-01 **FAIL** |
| 日频残差再滚动但 `ddof=0` | 3.50e-04 APPROX | 3.44e-04 APPROX | 3.41e-04 APPROX |
| `\|β\| × sigma`（把乘积当标量乘） | — | — | 1.3e-01 **FAIL** |

⚠ **两个实现陷阱（都踩过）**

1. `factorlib.ops.rolling_beta` 返回的第三个值 `resid`，在 `x` 为 `Series` 时**是错的**：
   该行写作 `y - (alpha + beta * x)`，**缺少 `.mul(x, axis=0)`**，pandas 会把 `x` 按
   **列（股票代码）**对齐 ⇒ **全 NaN**。本模块自己算残差
   （`ret - alpha - beta.mul(iret, axis=0)`）。**未改动 `scripts/jqdata/` 与 `factorlib/`**，
   仅在此记录，供后续维护者修。
2. 「残差」有两种都说得通的定义（窗口内残差向量 vs 日频残差序列），**只差 0.2%**，
   但正好决定 sigma 是 APPROX 还是 GOOD、`beta_consistency` 是 FAIL 还是 GOOD。
   **必须实测区分，不能靠读公式字面猜。**

### L8 `adjusted_sharpe_750d` = `Mean(ret,750) / Std(ret,750)**4`（**四次方**）
`sharpe_{60,750}d` = `Mean/Std`（一次方）。分母 `ddof=1`。
验证因子：`sharpe_60d`（EXACT 5e-11）、`sharpe_750d`（med_rel 3.4e-06）、
`adjusted_sharpe_750d`（med_rel 2.0e-06）。

### L9 `days_beyond_upper_lower_21d` = **双层滚动**计数

`Z = (C_hfq − MA(C_hfq,21)) / Std(C_hfq,21)`，然后**再对 `Z` 做 21 日滚动**统计
`#(Z>1) − #(Z<−1)`。验证：全窗口/沉淀窗口 **max_abs_err = 0（逐位相同，整数因子）**。
（备选「只用当日 Z 与阈值比较」为另一量级，已排除。）

---

## 3. 未实现 / 跳过

**无。** 60 条全部实现并取得官方重叠样本。

需要说明的两点：

1. `log_price` / `return_std_{21,42,63}d` / `sharpe_60d` 在 JSON 中属于 **Risk 族**
   （不在 Momentum/Technical），本批一并实现，与批次一结论一致（EXACT/GOOD）。
2. `alpha_{125,250,500,528,792,1000,1320}d_{000300,000001}` 共 8 条**不在 Risk 族**，
   JSON 里 `factor_type = Momentum`（用户任务描述中把它们列在 Risk 下，以 JSON 为准）。
   本批未实现，属 Momentum 批次职责 —— 但**其输入口径已由本批完全标定**
   （同一套 `index_daily` + 简单收益 + `Cov/Var` 滚动回归），Momentum 批次可直接复用
   `ts_index.py` 与 `repro_liquidity_risk.py::rolling_reg_series`。

---

## 4. 不通过 / 偏弱因子的归因

按 `verdict`（maxerr 最严口径）只剩 2 条 APPROX，`verdict_med` 下 60/60 通过。归因分类：

### P 类 —— 输入数据精度 / 长窗口数据微差累积（2 条，**非公式错误**）

| 因子 | verdict_med | max_abs_err | med_rel_err | 未通过原因 |
|---|---|---|---|---|
| `sharpe_750d` | GOOD (3.4e-06) | 7.51e-06 | 3.4e-06 | 单点 maxerr 落在 600036/600519 |
| `adjusted_sharpe_750d` | GOOD (2.0e-06) | 3.344 | 2.0e-06 | 同上（分母 `std^4` 放大 4 倍） |

**证据（残差随窗口长度单调增长，且六只标的普遍存在）：**

| 因子 | 600519 | 000001 | 000002 | 600036 | 002415 | 000651 |
|---|---|---|---|---|---|---|
| `return_std_252d` | 3.8e-09 | 5.0e-09 | 2.4e-09 | 4.9e-09 | 3.0e-09 | 4.5e-09 |
| `beta_250d_000300` | 1.9e-10 | 2.5e-10 | 6.8e-11 | 5.2e-10 | 6.0e-11 | 1.7e-10 |
| `beta_500d_000300` | 2.1e-05 | 1.6e-06 | 1.8e-07 | 1.2e-05 | 2.7e-06 | 1.6e-07 |
| `beta_1000d_000300` | 5.9e-06 | 6.9e-07 | 8.5e-09 | 1.2e-05 | 1.6e-06 | 4.8e-07 |
| `sharpe_750d` | 2.4e-04 | 1.2e-05 | 1.7e-06 | 1.9e-04 | 1.1e-04 | 7.9e-06 |

- **252 日窗口内的所有兄弟因子都是 1e-9 级**（`return_std_252d`、`high_low_252d`、
  `avg_turnover_252d`、`log_price` 全 EXACT/GOOD-极紧）；
- 一旦窗口跨到 **250~750 日之前（约 2024-06~2025-06）**，误差跳到 1e-5~2e-4；
- 误差是**近似恒定的加性偏移**（同一标的连续多日几乎不变，如 `sharpe_750d` 在
  600036 上 2026-06-15/16/17 恒为 2.0e-4），符合"个别历史交易日的数据微差被长窗口固定携带"；
- 已排除的公式变体：对数收益（更差 1e-2）、`ddof=0`、窗口 ±1、指数滞后/提前 1~2 日
  （更差 1e-1）、`min_periods` 变化 —— 均劣于现行实现。
- **结论：属结构性精度上限，不能靠改公式修复。** 实际可用性无影响
  （`med_rel_err ≤ 4e-06`，`corr = 1.000000`）。

### 已排除的其余口径变体（勿再尝试）

| 变体 | 受影响因子 | 结果 |
|---|---|---|
| 换手率 ×100（百分数） | `avg_/std_/bias_*turn*` | rel 65~85 ✗ |
| 换手率用自由流通股本 | 同上 | rel 0.57~0.80 ✗ |
| `std` 用 `ddof=0` | `std_turnover_*` / `*_std_turn_*` | rel 1.5e-02 ✗ |
| 成交额用「千元」/未还原 `ADJ` | `amount_ma_20d` / `sum_abs_rtn_amount_20d` | rel 1.1~1.2 ✗ |
| `VolCapRatio` 用后复权收盘 | `turnover_ma_*` | rel 4.9e-03 ✗ |
| `high_low` 用原始价 | `high_low_*` | 应更差（后复权已验证 EXACT，未再测） |
| 残差用「窗口内 std」 | `sigma_1320d_*` / `beta_consistency_*` | 1.5e-03 / 1.3e-01 ✗ |
| `beta_consistency = \|β\|·sigma` | `beta_consistency_1320d_000300` | 1.3e-01 ✗ |
| 对数收益 | 全部收益类 | 1e-02~1e-03 ✗ |
| `days_beyond` 单层（当日 Z） | `days_beyond_upper_lower_21d` | 量级不符 ✗ |

---

## 5. 复现方式

```bash
# 完整跑（首次会拉 Tushare 2013 起面板 + 4 个指数/因子缓存，之后零联网）
/home/xiaocong/anaconda3/envs/qlib/bin/python scripts/qdata/repro_liquidity_risk.py

# 只跑已沉淀窗口判定 / 换口径做变体对照
... repro_liquidity_risk.py --settle-days 30
... repro_liquidity_risk.py --variant turnover_src=vol_float ddof=0
```

**缓存**（`output/qdata_factor_repro/cache/`）
- `ts_panel_v1_post_<hash>.pkl` —— 2013-01-04~2026-09-10 × 6 只（3325 日）
- `index_000300_SH_*.pkl` / `index_000001_SH_*.pkl`
- `official_liqrisk_20260601_20260910.pkl` —— 60 因子 × 6 标的官方值

---

## 6. 后续建议

1. **把 §1.1（`AMOUNT`/`V` 已乘 `adj_factor`）与 L3（`turnover_rate` 字段口径）、
   L7a（双层窗口残差）补进 `CONVENTIONS.md`** —— 三条都会影响其他批次。
2. **修 `factorlib/ops.py::rolling_beta` 的 `resid` 返回值**（`x` 为 `Series` 时缺
   `axis=0`）。本批未改（不属职责），但任何复用该返回值的族都会拿到全 NaN。
3. `alpha_*d_{000300,000001}`（8 条，JSON 归 Momentum）可直接复用本批的
   `ts_index.py` + `rolling_reg_series`，口径已标定，预计一次通过。
4. 若要进一步压 `sharpe_750d`/`beta_500..1320d` 的 maxerr，需要**更长/更早的历史行情**
   或 qdata 侧的输入快照；当前 1e-5 量级已属数据层残差，不建议继续投入。
5. 本批结论基于 **6 只大中盘股**。按 `CONVENTIONS.md` §J6 的教训，若要把结论外推到
   全市场（尤其低价股），需在分层池上复核；但本批因子均为**比值型**（不乘 100、不做差），
   受价格分辨率影响远小于 momentum/technical 族，`verdict_med` 预计稳定。
