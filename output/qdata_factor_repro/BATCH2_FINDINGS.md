# qdata 批次二复现记录 —— Momentum / Reversal / Size / Value

> 脚本：`scripts/qdata/repro_batch2.py`
> 公式来源：`output/qdata_factor_repro/factor_formulas.json`（**逐条读公式后实现**）
> 判定：`scripts/jqdata/facsim/compare.py`（逐股绝对误差，主判据 `verdict_med`）
>      + `scripts/qdata/xs_compare.py`（横截面逐日 Spearman，横截面因子的正确判据）
> 口径基线：`CONVENTIONS.md` G1~G7（后复权 / 尾部未沉淀窗口 / 窗口含当日 / 简单收益 / ddof=1）
> 最近更新：2026-09-17

---

## 0. 结论速览

| 族 | 因子总数 | 已实现 | 通过 | 失败 | 跳过 |
|---|---|---|---|---|---|
| Momentum | 20 | 20 | **20** | 0 | 0 |
| Reversal | 3 | 3 | **3** | 0 | 0 |
| Size | 3 | 3 | **3** | 0 | 0 |
| Value | 11 | 2 | **1** | 1 | 9 |
| **合计** | **37** | **28** | **27** | **1** | **9** |

- 纯时序因子（26 个，6 只股票池）：`batch2_compare_settled.csv`
  → **`verdict_med`：EXACT 17、GOOD 8、FAIL 1**（25/26 达标）；
  严格 `verdict`（maxerr）口径：EXACT 16、GOOD 5、APPROX 4、FAIL 1。
- 横截面因子（2 个，全市场 ~5500 只）：`batch2_xs_compare_settled.csv`
  → **`verdict_xs`：EXACT 1（`small_cap_reversal_21d`）、GOOD 1（`nl_size`）**（2/2 达标）。
- 唯一失败项：`book_to_market` —— **口径上需要资产负债表科目（递延所得税资产），不是公式推错**，详见 §4.1。
- 跳过 9 个 Value 因子 —— **均含 `CrossSectionalRank` 且需要财务报表原始科目**，详见 §5。

---

## 1. 四类归档

### 1.1 纯时序已验证（26 个，`--settle-days 30`，306 个 stock-day）

| 因子 | 族 | 本地实现 | verdict_med | max_abs_err |
|---|---|---|---|---|
| `dif` | Momentum | `EMA(C_hfq,12) − EMA(C_hfq,26)` | EXACT | 4.96e-11 |
| `dea` | Momentum | `EMA(dif,9)` | EXACT | 4.92e-11 |
| `MACD` | Momentum | `2 × (dif − dea)` | EXACT | 4.99e-11 |
| `ma_20d` | Momentum | `MA(C_hfq,20)` | EXACT | 1.82e-12 |
| `return_5/21/42/63/126/252d` | Momentum | `∏(1+DailyReturn,n) − 1` | EXACT | ~4.99e-11 |
| `days_down_up` | Momentum | `\|ConsecutiveUp − ConsecutiveDown − 1\|`（G8） | EXACT | 0 |
| `rsrs` | Momentum | `ZScore(OLS_slope(Low_hfq~High_hfq,18),200,ddof=1)`（G9） | EXACT | 5.49e-11 |
| `price_position_ir_60d` | Momentum | `Mean(Ratio,60)/StdDev(Ratio,60)`，ddof=1（G11） | EXACT | 4.98e-11 |
| `alpha_125d_000300` / `alpha_250d_000300` | Momentum | 滚动 OLS 截距（G15） | GOOD | 4.96e-11 / 4.99e-11 |
| `alpha_500/528/792/1000/1320d_*` | Momentum | 同上（长窗口） | GOOD | 1e-7 ~ 1.2e-7 |
| `rsi` | Reversal | Wilder RSI，`com=period−1`（G12） | EXACT | 0 |
| `price_dist` | Reversal | `ceil(scale(C_hfq)) − scale(C_hfq)`（G10） | EXACT | 5.55e-16 |
| `size` | Size | `−log(total_mv / 100)`（G13） | EXACT | 4.98e-11 |
| `float_size` | Size | `−log(circ_mv / 100)` | EXACT | 4.99e-11 |
| `earnings_to_price` | Value | `1 / pe_ttm`（G14；精确式见 §4.2） | GOOD | 2.41e-06 |

### 1.2 内层已验证 / 外层横截面已验证（2 个，全市场逐日 Spearman）

| 因子 | 族 | 全市场实现 | verdict_xs | spearman_med | spearman_min | n_days / n_stocks |
|---|---|---|---|---|---|---|
| `small_cap_reversal_21d` | Reversal | `rank(−CumRet_21d_hfq)/N × rank(−total_mv)/N` | **EXACT** | 0.9999983 | 0.9999913 | 51 / 5454 |
| `nl_size` | Size | 全市场截面 `Residual(Size³ ~ Size)` | **GOOD** | 0.9996338 | 0.9979130 | 51 / 5517 |

> ⚠ 这两个因子**不能用** 6 只股票池的绝对误差判定：`CrossSectionalRank` 是
> 全市场 ~5500 只的百分位，6 只股票只有 6 档。用 6 只股票池的绝对误差看，
> `small_cap` 判 APPROX、`nl_size` 判 FAIL，但全市场秩相关分别是 0.999998 / 0.999634
> —— **判据用错会把「名次几乎全对」错报成 FAIL**（见 `batch2_fullmarket_compare_settled.csv`
> 与 `batch2_xs_compare_settled.csv` 的对照）。

### 1.3 待全市场验证

无。本批涉及的横截面因子只有 `small_cap_reversal_21d` 与 `nl_size`，均已在 §1.2 用全市场验证。

### 1.4 结构性不可复现 / 未做

- `book_to_market`（FAIL）—— 见 §4.1（需要资产负债表：归母权益 **+ 递延所得税资产**）。
- 9 个 Value 因子（跳过）—— 见 §5（含 `CrossSectionalRank` + 需要财务报表原始科目）。

---

## 2. 本批新标定的口径约定（G8~G17）

> 全部为**实测标定**（对照官方值），配套变体表见 `batch2_variants.csv`。

### G8 — `days_down_up` 用连续长度之差，符号判定为**严格正/负**

```
ConsecutiveUp   = 截止当日 Close 连续上涨（diff > 0）的天数
ConsecutiveDown = 截止当日 Close 连续下跌（diff < 0）的天数
Factor = |ConsecutiveUp − ConsecutiveDown − 1|
```
- 口径：`C_hfq.diff()`；一侧当前笔连续长度，另一侧必然为 0。
- 拒绝变体：`diff >= 0 / <= 0`（非严格）在尾部 `max_abs_err` 达 5（严格版 1）；
  用原始价 `strict(raw)` 达 3。**严格符号最优**（已沉淀窗口 max_abs_err = 0）。

### G9 — `rsrs` 用**后复权** High/Low，Z-Score 用**样本标准差 ddof=1**

```
Slope_t = β from OLS(Low_{t-17:t} ~ High_{t-17:t})      # N=18，含当日
RSRS_t  = (Slope_t − Mean(Slope_{t-199:t})) / StdDev(Slope_{t-199:t}, ddof=1)   # M=200
```
- 变体对照（`batch2_variants.csv`）：
  | 变体 | verdict_med | med_rel_err |
  |---|---|---|
  | HFQ + ddof=1 | **EXACT** | 2.3e-11 |
  | HFQ + ddof=0 | APPROX | 1.7e-03 |
  | raw（不复权）+ ddof=1 | FAIL | 5.5e-02 |
- 结论：**复权**与 **样本标准差** 两项都必须对；`raw` 价在此因子错得很明显
  （斜率对 High/Low 的相对缩放敏感，而 adj_factor 在窗口内会变）。

### G10 — `price_dist` 的「价格」是**后复权价** C（与直觉相反）

```
y = C_hfq                     (C_hfq < 10)
y = C_hfq / 10                (10 <= C_hfq < 100)
y = C_hfq / 100               (C_hfq >= 100)
Factor = ceil(y) − y          # 到「下一个整数关口」的距离
```
- 变体：`HFQ+ceil` → EXACT（5.55e-16）；`raw+ceil` → FAIL（med_rel_err 0.72）。
- **注意**：直觉上心理整数关口应该用原始报价，但官方实测用**后复权价**。
  同一文件的 `HFQ+nearest` 中位误差也是 0（数值上常与 ceil 重合），
  但 `max_abs_err` 达 1.0 → `ceil` 才是官方口径。
- `window > 0` 时才做移动平均；官方 `params.window` 默认 0（本批不做 MA）。

### G11 — `price_position_ir_60d` 的 Ratio 与复权无关，StdDev 用 ddof=1

```
Ratio = (Close − Open) / (High − Low)          # 复权/不复权恒等（比值对共同尺度不变）
Factor = Mean(Ratio, 60) / StdDev(Ratio, 60)   # ddof=1
```
- `HFQ+ddof1` 与 `raw+ddof1` 结果**逐位相同**（max_abs_err 4.98e-11）；
  `ddof=0` → APPROX（med_rel_err 7.4e-03）。再证 G5。

### G12 — `rsi` 的 Wilder 平滑 = `ewm(com=period−1, adjust=False)`

```
Gain = max(Close − PrevClose, 0),  Loss = max(PrevClose − Close, 0)
AvgGain = EMA(Gain, α=1/period),   AvgLoss = EMA(Loss, α=1/period)   # 即 com = period−1
RSI = 100 − 100/(1 + AvgGain/AvgLoss)
```
- 变体：`com=13` → **EXACT**；`span=14`（α=2/15）→ FAIL（med_rel_err 9.9e-02）；
  `rolling SMA 14` → FAIL；`raw` 价 → FAIL（med_rel_err 1.4e-02）。
- 结论：α 必须是 **1/period**（Wilder），不是 pandas 默认的 2/(period+1)。
- 尾部提示：主线实测 `rsi` 在**最近约 5 个交易日**是「暂定值」，事后会被回填修订
  （`_old_20260821` 快照对照，76 日中 4 日变化，均在 08-14 之后）。
  **`--settle-days 30` 截断后 `rsi` max_abs_err = 0。**

### G13 — `size` / `float_size` 是**负对数**，市值单位**百万元**

```
size       = −ln(TotalShares × ClosePrice / 1e6)
float_size = −ln(FloatShares  × ClosePrice / 1e6)
```
- Tushare `daily_basic.total_mv` / `circ_mv` 单位是**万元**，
  故 `TotalShares × ClosePrice / 1e6 = total_mv × 1e4 / 1e6 = total_mv / 100`。
- 官方实测 = `−log(total_mv/100)`，max_abs_err 4.98e-11（**EXACT**）。
- 拒绝变体（全部 FAIL）：
  `−log(total_mv/1e6)`（差 ln(100)=4.605）、`−log(total_share×C_raw/1e6)`（`total_share` 单位是万股）、
  `−log(total_share×C_hfq/1e6)`、`+log(total_mv/100)`（符号相反）。
- 跨体系提醒：聚宽同名 `natural_log_of_market_cap` 是**正**对数，**符号不可互推**。

### G14 — `earnings_to_price` = 归母净利润TTM / 总市值；`book_to_market` 需要资产负债表

- `earnings_to_price`：`1 / pe_ttm` 与官方在**盈利股**上相对误差 ~1.5e-06
  （残差来自 Tushare `pe_ttm` 的 4 位小数舍入）→ `verdict_med = GOOD`；
  **覆盖率 255/306 = 83.3%**，缺的 51 条全是**亏损股**（`000002.SZ` 万科A：
  Tushare `pe_ttm` 为 NaN，官方仍有负值）。
- **精确式**（本批额外用本地 `fina_indicator` 实测确认）：
  `earnings_to_price = 归母净利润TTM / (ClosePrice_raw × TotalShares)`
  = `TTM(profit_dedt + extra_item) / (total_mv × 1e4)`。
  用 PIT（ann_date）对齐后与官方 **med_rel_err = 7.5e-11**、6 只股票中 4 只 maxerr = 0，
  仅 `002415.SZ` / `000651.SZ` 在半年报披露边界日有 PIT 选择差异（maxerr 2.7e-03）。
  → 这证明「1/pe_ttm 的匹配」只是盈利股下的巧合等式，**官方口径是财务口径**，
  亏损股必须走财务报表才能补齐。
- `book_to_market`：官方 = `(SE_without_MI + DeferredTaxAssets) / (ClosePrice × TotalShares)`，
  而 Tushare `pb` 的倒数只含归母权益 ⇒ **1/pb 系统性低估**。实测
  `official / (1/pb)` 在窗口内**逐股恒定**：600519=1.023、002415=1.028~1.117（换报期跳变）、
  000651=1.111、600036=1.214、000002=1.246、000001=1.280
  ⇒ 该比值 = `1 + 递延所得税资产 / 归母权益`（2%~28%，银行最高）。
  相关系数 0.9996，但 10.5% 的系统性偏差使 `verdict_med = FAIL`。**属口径（数据可得性）问题，非公式错误。**

### G15 — `alpha_{N}d_*` = 个股**简单**日收益对指数**简单**日收益的滚动 OLS **截距**

```
Alpha_t = Intercept of OLS(StockReturn_{t-N+1:t} ~ IndexReturn_{t-N+1:t})   # 窗口含当日
StockReturn = C_hfq.pct_change()          # 简单收益（G4）
IndexReturn = index_daily.close.pct_change()   # 000001.SH / 000300.SH
```
- 变体：`HFQ simple ret` 全部 GOOD；`raw simple ret` 全部 **FAIL**（med_rel_err 0.17~0.35）。
- 指数收益源：`close.pct_change()` 优于 `pct_chg/100`（后者把 125d/250d 从 2e-08 劣化到 4e-06）。
- 长窗口残差：125d/250d 达 `max_abs_err ~5e-11`（逐位一致），但 500d/792d/1000d/1320d
  残差升到 ~1e-07（相对 ~1e-06 ~ 5e-06）→ 长窗口的指数历史与官方略有差异
  （非公式问题；`verdict`(maxerr) 判 APPROX，`verdict_med` 仍为 GOOD）。

### G16 — ⚠ `factor_value` 会**静默返回空结果**（必须当作可重试状态）

- 现象：服务端压力/限流时返回 `code=0, msg=ok` 但 `data.items = []`，
  **既不报错也不是 HTTP 429**。若只重试异常，会**静默丢数据**（首批实测 42 次调用全部返回空）。
- 处理：本脚本对「空结果」做 6 次退避重试（1.2s×n），并对 `(factor, code)` **增量落盘缓存**，
  中断/重跑不丢已取数据。
- 与 G7 并列：仍**禁用 offset 分页**，按 `(factor_name, ts_code)` 或 `(factor_name, trade_date)` 单取。

### G17 — `CrossSectionalRank(x) = rank(x) / N`（升序平均秩）

- 实测（全市场 `small_cap_reversal_21d`，51 日）：
  `rank(pct=True)` 与 `rank()/N` 结果**一致**（N = 当日非空股票数），逐日 Spearman 0.999998。
- `(rank−1)/(N−1)` 明显更差（med_rel_err 4.9e-3 vs 1.7e-4）→ 官方是 `rank/N`。
- `small_cap_reversal_21d` 的 `CumReturn` 用**后复权**价：
  `hfq + rank/N` → `spearman_med 0.999998`；`raw` → `spearman_med 0.99976`、6 股绝对误差劣化 80 倍。

---

## 3. 变体标定总表（摘要）

完整表见 `batch2_variants.csv`。**`<== canonical` 标记为最终采用口径。**

| 因子 | 对 | 错 |
|---|---|---|
| `days_down_up` | `diff>0/<0` + HFQ（maxerr 1） | `>=0/<=0`（maxerr 5）、raw（maxerr 3） |
| `rsrs` | HFQ + ddof=1（EXACT） | ddof=0（APPROX）、raw（FAIL） |
| `rsi` | Wilder `com=13` + HFQ（EXACT） | `span=14`（FAIL）、SMA14（FAIL）、raw（FAIL） |
| `price_dist` | HFQ + `ceil`（EXACT 5.6e-16） | raw + ceil（FAIL） |
| `price_position_ir_60d` | ddof=1（EXACT） | ddof=0（APPROX） |
| `size` / `float_size` | `−log(mv/100)`（EXACT） | `/1e6`、`total_share×price/1e6`（万股口径）、正号 |
| `earnings_to_price` | `1/pe_ttm`（GOOD，盈利股） | 亏损股无值（需财务口径，§4.2） |
| `book_to_market` | ——（需资产负债表 DTA） | `1/pb`（FAIL，系统性低估 2%~28%） |
| `alpha_*` | HFQ 简单收益（GOOD） | raw 简单收益（FAIL） |
| `small_cap_reversal_21d` | HFQ 收益 + `rank/N`（xs EXACT） | raw 收益、`(rank−1)/(N−1)` |

---

## 4. 未通过因子的失败原因

### 4.1 `book_to_market` —— 口径（需要资产负债表科目）

- **不是公式推错**：公式显式写 `(SE_without_MI_pri + DeferredTaxAssets_pri) / MarketCap`，
  即归母权益 **加上递延所得税资产**。
- 本地可用字段只有 Tushare `pb`（= 总市值 / 归母权益，**不含** DTA），
  因此 `1/pb` 系统性低估：`official/(1/pb)` 逐股恒定在 1.023~1.280。
- 相关系数 0.9996，形状完全正确，仅量纲偏移 → `verdict_med = FAIL`（相对误差 10.5%）。
- 要精确复现，需要**资产负债表**的归母权益与递延所得税资产两个科目
  （本地 `a_share_financial_pit_v1` 只有 `fina_indicator`，无 `balancesheet`）。

### 4.2 `earnings_to_price` —— 通过，但覆盖率 83.3%（亏损股）

- 在盈利股上 `1/pe_ttm` 与官方相对误差 1.4e-06 → `verdict_med = GOOD`。
- 缺的 51 条是亏损股：Tushare 对负 TTM 净利润不提供 `pe_ttm`，而官方仍给
  `归母净利润TTM / 总市值`（负值）。
- 已实测确认精确式 = `TTM(profit_dedt + extra_item) / (total_mv × 1e4)`
  （med_rel_err **7.5e-11**，PIT 对齐），补齐覆盖率需接财务表（见 G14）。

### 4.3 `alpha_500/528/792/1000/1320d_*` —— 通过（GOOD），maxerr 判 APPROX

- `verdict_med = GOOD`（相对误差 2.4e-07 ~ 5.5e-06），但严格 `verdict`(maxerr) 为 APPROX
  （阶跃在个别 stock-day）。
- 短窗口 125d/250d 逐位一致（5e-11）→ **公式正确**；长窗口残差 ~1e-07 反映
  指数历史序列与官方的细微差异（或官方长窗口指数数据的沉淀情况），**不是公式问题**。

### 4.4 `dif` / `dea` / `MACD` / `rsi` / `days_down_up` —— 全窗口 FAIL，截断后 EXACT

- 这是 **G2 尾部未沉淀窗口** 的已知结构性问题：`verdict_med` 在全窗口仍是 EXACT（中位误差 ~1e-13），
  但 `verdict`(maxerr) 被尾部噪声支配 → FAIL。
- `rsi` 另有**近期值会被回填修订**的独立证据（`_old_20260821` 快照，08-14 后 4 日变化）。
- **判定必须用 `--settle-days 30`。**

---

## 5. 跳过因子及原因（9 个 Value）

`batch2_skipped.csv`。共同原因：**含 `CrossSectionalRank`（需要全市场 ~5500 只）+ 需要财务报表原始科目**
（本地 `a_share_financial_pit_v1/normalized/` 只有 `fina_indicator.csv.gz`，没有 `income` / `cashflow` / `balancesheet`）。

| 因子 | 缺口 |
|---|---|
| `fcf_to_market` | 现金流量表 TTM：`NOCF_TTM − SICO_TTM` |
| `ncf_to_market` | 现金流量表 TTM（筹资+投资+经营净现金流）+ Rank |
| `ocf_to_market` | 现金流量表 TTM（经营现金流净额）+ Rank |
| `ebitda_to_market` | 利润表 EBITDA + Rank |
| `earnings_cut_to_market` | 扣非净利润 TTM + Rank（内层已确认 = `profit_dedt_TTM/total_mv`） |
| `sales_to_market` | 单季营业总收入 Q（非 `ps_ttm` 的 TTM 口径）+ Rank |
| `pegh5` | 5 年 EPS 复合增速与 EPS_TTM + Rank |
| `etp5` | 5 年净利润与市值滚动均值 + Rank |
| `dividend_yield_3y_avg` | 3 年每股实派分红 + Rank |

> 注：`fina_indicator` 提供 `eps` / `profit_dedt` / `extra_item` / `bps` 等**比率类**字段，
> 足以做 `earnings_to_price` 的 PIT 补齐；但做不了现金流/EBITDA/分红原始科目。

---

## 6. 产出文件

| 文件 | 内容 |
|---|---|
| `scripts/qdata/repro_batch2.py` | 实现 + 取数 + 比对 + 全市场横截面验证（本批唯一新增脚本） |
| `output/qdata_factor_repro/batch2_compare.csv` | 全窗口（含未沉淀尾部）26 个因子报告 |
| `output/qdata_factor_repro/batch2_compare_settled.csv` | **已沉淀窗口（判定口径）** 26 个因子报告 |
| `output/qdata_factor_repro/batch2_variants.csv` | 口径变体标定表（对/错逐条记录） |
| `output/qdata_factor_repro/batch2_fullmarket_compare_settled.csv` | 2 个横截面因子的 6 股绝对误差（**仅诊断**） |
| `output/qdata_factor_repro/batch2_xs_compare_settled.csv` | **全市场横截面逐日 Spearman（判定口径）** |
| `output/qdata_factor_repro/batch2_skipped.csv` | 9 个跳过因子及原因 |
| `output/qdata_factor_repro/BATCH2_FINDINGS.md` | 本文档 |

### 复现命令

```bash
/home/xiaocong/anaconda3/envs/qlib/bin/python scripts/qdata/repro_batch2.py --full-market --variants
```

- 面板默认起点 `2020-01-01`（`alpha_1320d_000001` 需要 ~1320 交易日回看；
  其余因子只看各自窗口，起点不影响结果）。
- 首次运行会：拉 Tushare 面板（6 股 × 3 接口）、拉指数日线、拉 qdata 官方值
  （按 `(factor, code)` 增量缓存）、`--full-market` 时再拉全市场行情（~101 日 × 2 接口）
  与单日全市场官方值（51 日 × 2 因子）。全部落盘缓存，重跑不联网。
