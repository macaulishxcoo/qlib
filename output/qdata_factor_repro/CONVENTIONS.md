# qdata.cc 因子本地复现 —— 口径约定与验证记录

> 对标 `output/jqdata_factor_repro/VERIFIED_FACTORS.md`（聚宽体系 185 个已验证因子）。
> 本文档记录 **qdata.cc（Tushare 兼容接口）因子库** 的复现口径、已验证因子、以及结构性不可复现项的归档。
>
> 最近更新：2026-09-17

---

## 0. 体系总览

| 项目 | 取值 |
|---|---|
| 官方因子来源 | `http://api.qdata.cc`（备用 `https://quantdata.olingma.com`），`factor_value` 接口 |
| 认证 | 请求头 `X-API-Key`，Key 读取顺序：环境变量 `QDATA_KEY` → `.jqdata/qdata_key` |
| 公式来源 | `factor_list` 的 `factor_desc`，由 `scripts/qdata/extract_formulas.py` 抽取 |
| 公式清单 | `output/qdata_factor_repro/factor_formulas.json`（252 条，**全部含数学表达式**） |
| 输入数据 | Tushare 官方接口（`daily` / `daily_basic` / `adj_factor` / `stock_basic` / `trade_cal`），见 `scripts/qdata/ts_env.py` |
| 复现实现 | `scripts/qdata/repro.py`（分批），算子复用 `scripts/jqdata/facsim/ops.py` |
| 比对引擎 | `scripts/jqdata/facsim/compare.py`（三口径判定，与聚宽体系共用） |
| 因子族分布 | Alpha101 76、Quality 59、Liquidity 36、Risk 26、Momentum 21、Growth 15、Value 11、Reversal 5、Size 3（含 10 个 `_old_` 快照） |

### 代码格式映射

| 场景 | 格式 | 示例 |
|---|---|---|
| qdata / Tushare | `600519.SH` | `factor_value` 的 `ts_code` |
| 聚宽 JQData | `600519.XSHG` | `get_factor_values` |
| qlib / 本地 | `SH600519` | `~/.qlib/qlib_data` |

---

## 1. 全局约定（G 系列）

> 以下均为**实测标定**结论，非文档推测。判定口径见 `compare.py`：
> `verdict`=maxerr 口径（最严）、`verdict_robust`=p99、`verdict_med`=**中位**（推荐的可使用性判据）。

### G1 — `Close` 的复权口径是**分族**的（⚠️ 已修正）

**原始结论**："`Close` 一律指后复权价"。**该结论只对显式写 `Close_hfq` 的因子族成立。**

实测（Alpha101 阶段 A，000001.SZ @20260811）：

| 因子 | 官方值 | **不复权** | 后复权 |
|---|---|---|---|
| `alpha101_101` | −0.3105590062 | **−0.310559006211** ✅ | −0.31249（err 8e−2） |
| `alpha101_41`（VWAP） | 0.0183747059 | **0.0183747059042** ✅ | 2.554（err 2.5） |
| `alpha101_12` | −0.0300000000 | **−0.0300** ✅ | −4.170（err 3105） |
| `alpha101_42` | — | **err 8.9e−16** ✅ | err 792.6, Spearman 0.64 |

**结论：Alpha101 族用「不复权价」**，且其 `VWAP = amount × 10 / vol`（千元/手换算）也不复权。

| 族 | 复权口径 | 依据 |
|---|---|---|
| **Alpha101**（71 条） | **不复权** | 上表逐位验证 |
| 显式写 `Close_hfq` 的因子（如 `log_price`） | **后复权** | `log_price` 全部 73 日 × 6 只精确匹配 |
| 价量/收益/波动/夏普（批次一） | **后复权** | 15/15 精确通过 |
| 流动性换手率类 | **`daily_basic.turnover_rate`**（与复权无关） | 见 §5 第 3 条 |

→ **不可全库统一复权口径。每族必须做 raw-vs-hfq 变体对照** —— 这是本体系最容易踩的坑之一。

**交叉验证**：本地镜像 `data/external/tushare/market_daily_v1/sh600519.csv` 的 `adjclose` 列（11111.62）与本管线 `原始收盘 × adj_factor` 逐位相同，`factor` 列 = 0.24321518890997423 为其另一套归一口径。

### G2 — ⚠️ qdata 尾部「未沉淀窗口」（**最重要**）

**结论：EMA 族因子（`dif` / `dea` / `MACD`）在数据末端约 20~25 个交易日内结构性不可复现，与公式无关。**

**处理：比对必须用 `--settle-days 30` 截断尾部。**

#### 证据链（2026-09 实测）

1. `ma_20d` / `log_price` / `return_*d` / `return_std_*d` / `sharpe_60d` 在**全部** 73 个交易日、6 只股票上精确匹配（`max_abs_err` ~5e-11，纯浮点舍入）
   → **收盘价输入序列本身完全正确**，问题不在数据。
2. `dif` / `dea` / `MACD` 在 **2026-08-13 及之前精确匹配**，从 **2026-08-14 起**出现 `max_abs_err` 25~73 的偏差。
3. **6 只股票断点完全相同，均为 2026-08-14**（000001.SZ / 000002.SZ / 000651.SZ / 002415.SZ / 600036.SH / 600519.SH）
   → 全局管道变更，非个股事件。
4. 把取数结束日分别设为 `20260828` / `20260910` / `20260917`：**断点恒为 08-14**，且三次取回的官方值**逐位相同**
   → 既不是"最近 N 天滚动刷新"，也不是缓存抖动，而是**固定日历断点**。
5. **逆递推反解**（EMA 递推可精确反演：`C(t) = [dif(t) − (1−α)·e12(t−1) + (1−β)·e26(t−1)] / (α−β)`）：

   | 区间 | 隐含价 / 真实收盘 |
   |---|---|
   | 2026-06-01 ~ 08-13 | **恒等于 1.000000**（偏差 0.0） |
   | 2026-08-14 ~ 09-10 | 均值 ≈ 1.00，标准差 1.2% ~ 2.4% 的**随机噪声** |

   即：官方 `dif` 的隐含输入**不是任何一个合理的价格序列**——真实价格不可能逐日相对 close 抖动 ±2%。
6. **复权因素被彻底排除**：`000002.SZ`（万科A）的复权因子自 2024-06-03 起为**恒定值 181.704**，期间无任何除权事件，但其 `dif` **仍在 2026-08-14 同日断裂**。
7. 反解出的隐含「复权因子」在尾部随机跳动于 8.12 ~ 8.82（真实复权因子必为常数或单调递增），进一步确认尾部值自身含噪。

#### 结论

`dif` / `dea` / `MACD` 一族是 qdata 用**另一条价格管道**（非 `close` 管道）计算的，该管道对新数据的沉淀周期约 20~25 个交易日。**在未沉淀窗口内这些因子不可复现，属数据供给侧问题，不是公式错误。**

#### 效果

| 口径 | EXACT | GOOD | APPROX | FAIL | 通过率 |
|---|---|---|---|---|---|
| 全窗口（含未沉淀尾部） | 8 | 4 | 0 | 3 | 12/15 |
| **已沉淀窗口（`--settle-days 30`）** | **11** | **4** | **0** | **0** | **15/15** |

### G3 — 滚动窗口一律**含当日**

`ma_20d`、`return_*d`、`return_std_*d`、`sharpe_60d` 均按 `C.rolling(n)`（含当日）实现，全部精确通过。
（注：聚宽体系的部分因子如 `Price1M` 恰好相反，窗口不含当日 —— 两套体系**不可互推**，必须各自标定。）

### G4 — `DailyReturn` 用**简单收益**，非对数收益

`return_{n}d = Product(1 + DailyReturn, n) − 1`，其中 `DailyReturn = Close_hfq.pct_change()`。
实现：`(1 + ret).rolling(n).apply(np.prod, raw=True) − 1`。

### G5 — `StdDev` 用**样本标准差**（`ddof=1`）

`return_std_*d = ret.rolling(n).std(ddof=1)`，`sharpe_60d` 的分母同。
两个因子在 `verdict_med` 下均为 `GOOD`（中位相对误差 1e-9 量级，源于官方值的小数位截断），在 maxerr 口径下 `return_std_*` 判 `GOOD` 而非 `EXACT` 亦同因。

### G6 — 比对日期上限受 Tushare `daily` 覆盖末端约束

qdata `factor_value` 数据到 **20260917**，而 Tushare `daily` 到 **2026-09-10**。
**比较日期取两者交集**，否则覆盖率不足会污染判定。

### G7 — 取数纪律（接口行为，非公式口径）

- `factor_value` 单次 **6000 行上限且静默截断**；
- **`offset` 分页会返回重复行**（实测 124 条重复 / 涉及 3 个日期）并可能漏行
  → **禁止用 offset 分页**，改为按 `(factor_name, ts_code)` 或 `(factor_name, trade_date)` 单取；
- 日期参数必须是 `YYYYMMDD`，传 `YYYY-MM-DD` 会**静默返回 0 行**；
- 速率限制 QPS 30 / QPM 200。
- ⚠️⚠️ **限流/压力下 `factor_value` 会返回 `code=0, msg=ok` 但 `items=[]`** ——
  **既不报错也不是 429**。必须把**空结果也当作可重试**，否则会静默丢数据。
  实测：某一批 **42 次调用全部返回空**，而接口状态码完全正常。
  → 所有取数循环都应对"空结果"做退避重试，并把结果按 `(factor, code)` **增量落盘缓存**。

---

## 2. 批次一：已验证因子（15 个，全部通过）

判定口径：`--settle-days 30`（即 2026-06-01 ~ 2026-08-11），股票池 6 只大中盘，共 306 个 stock-day。

| 因子 | 公式（本地实现） | 备注 | verdict_med | max_abs_err |
|---|---|---|---|---|
| `dif` | `EMA(Close_hfq, 12) − EMA(Close_hfq, 26)` | α=2/(n+1)，`adjust=False` | EXACT | 4.96e-11 |
| `dea` | `EMA(dif, 9)` | | EXACT | 4.92e-11 |
| `MACD` | `2 × (dif − dea)` | 注意 ×2 | EXACT | 4.99e-11 |
| `ma_20d` | `SMA(Close_hfq, 20)` | 含当日 | EXACT | 1.82e-12 |
| `log_price` | `ln(Close_hfq)` | 公式显式写 `Close_hfq` | EXACT | 4.99e-11 |
| `return_5d` | `Product(1+DailyReturn, 5) − 1` | | EXACT | 4.99e-11 |
| `return_21d` | 同上，n=21 | | EXACT | 4.97e-11 |
| `return_42d` | 同上，n=42 | | EXACT | 4.98e-11 |
| `return_63d` | 同上，n=63 | | EXACT | 4.99e-11 |
| `return_126d` | 同上，n=126 | | EXACT | 4.98e-11 |
| `return_252d` | 同上，n=252 | | EXACT | 4.99e-11 |
| `return_std_21d` | `StdDev(DailyReturn, 21)`，ddof=1 | | GOOD | 5.00e-11 |
| `return_std_42d` | 同上，n=42 | | GOOD | 4.97e-11 |
| `return_std_63d` | 同上，n=63 | | GOOD | 4.98e-11 |
| `sharpe_60d` | `Mean(DailyReturn,60) / StdDev(DailyReturn,60)` | ddof=1 | EXACT | 4.98e-11 |

**全部 `max_abs_err ≈ 5e-11` = 官方值保留 4~8 位小数导致的纯舍入误差。**

### 已排除的实现变体（勿再尝试）

| 变体 | 结果 | 结论 |
|---|---|---|
| `EMA(adjust=True)` | 与 `adjust=False` 结果一致（差异 0） | 本场景无影响，**不是**尾部断裂的原因 |
| `EMA(com=n−1)` | 中位相对误差 0.681，max 270 | **错误**，必须用 `span=n` |
| `EMA(alpha=2/(n+1))` | 与 `span=n` 完全一致 | 等价写法，`pandas` 的 `span` 就是它 |
| `Close` 用原始价 / 前复权价 | 量级不符 | 必须后复权（G1） |

---

## 2.5 批次二：已验证因子与口径标定（Momentum / Reversal / Size / Value，26 个）

判定口径：`--settle-days 30`。股票池 6 只，438 个 stock-day。
结果：**EXACT 17 + GOOD 8 + FAIL 1**（共 26 个）。

### 2.5.1 口径标定结论（**部分修正了文档公式**）

| 因子 | 族 | **正确口径** | 被排除的变体 | 证据 |
|---|---|---|---|---|
| `size` | Size | **`−log(total_mv / 100)`**（`total_mv` 单位**万元**，故 /100 后单位为**百万元**） | `−log(total_share×C_hfq/1e6)` FAIL（corr −0.02）、`−log(total_mv/1e6)` FAIL、`+log(...)` FAIL | max_abs 5e-11 |
| `float_size` | Size | **`−log(circ_mv / 100)`** | `−log(float_share×C_hfq/1e6)` FAIL（corr 0.067）、`−log(float_share×C_raw/1e6)` FAIL | max_abs 5e-11 |
| `earnings_to_price` | Value | **`1 / pe_ttm`**（等价于 `total_share×C_raw/total_mv`） | — | GOOD，corr 1.0 |
| **`book_to_market`** | Value | **`(期末归母股东权益 + 期末递延所得税资产) / (收盘价 × 总股本)`** | `1/pb` FAIL（0.0995）、不加 DTA FAIL（0.053）、用期初/上年报权益 FAIL（0.011） | max_abs **4.98e-11**，corr **1.0** |
| `price_dist` | Reversal | 后复权价 + **`ceil`（向上取整）** | `nearest` FAIL（corr −0.10）、原始价+ceil FAIL（corr −0.16） | max_abs 5.6e-16 |
| `rsi` | Reversal | **Wilder 平滑 `ewm(com=13)`** | `span=14` FAIL、`rolling SMA 14` FAIL、原始价 FAIL | 中位相对误差 **0** |
| `rsrs` | Momentum | **后复权价 + `ddof=1`** | `ddof=0` → APPROX、原始价 FAIL | max_abs 5.5e-11 |
| `price_position_ir_60d` | Momentum | **`ddof=1`**（后复权或原始价均可） | `ddof=0` → APPROX | max_abs 5e-11 |
| `days_down_up` | Momentum | **严格 `diff>0 / diff<0` + 后复权价** | `nonstrict(>=/<=)` FAIL（corr 0.925）、严格+原始价 FAIL（corr 0.982） | 中位相对误差 0 |
| `alpha_{125,250,500,528,792,1000,1320}d_{000300,000001}` | Momentum | **后复权价 + 简单收益**做指数回归 | **原始价 FAIL**（0.17~0.35 相对误差） | corr 1.0 |

> **`size` 的文档公式有误。** 文档写 `Size = −log(TotalShares × ClosePrice / 1e6)`，
> 但实测该式与官方 **corr = −0.02（完全不相关）**；正确形式是直接用 `daily_basic` 的
> 总市值 `total_mv`（万元）除以 100。这可能是因为文档说的 "TotalShares" 真实含义是
> 市值而非股本数。

> **`book_to_market` 的文档 `_pri` 后缀具有误导性。** 文档写
> `(SE_without_MI_pri + DeferredTaxAssets_pri) / (ClosePrice × TotalShares)`，
> 容易误读为"上期/期初"值。实测**用的是最新已披露报告期的期末值**，且
> **递延所得税资产必须计入分子**（这正是 `1/pb` 口径失败的原因 —— Tushare 的 `pb`
> 用归母权益、不含 DTA）。累计验证 438 个 stock-day，中位相对误差 **1.28e-11**；
> 剩余 19 个残差样本**全部落在 2026-08-28 之后**，属 §G2 未沉淀窗口。
> 复现脚本：`scripts/qdata/repro_value.py`（产出 `value_compare_settled.csv`）。

### 2.5.2 未通过 / 待办

| 因子 | 状态 | 原因 |
|---|---|---|
| ~~`book_to_market`~~ | ✅ **已解决** | ~~FAIL~~ → **EXACT**（max_abs 4.98e-11）。正确口径见 §2.5.1，文档 `_pri` 后缀误导 |
| `small_cap_reversal_21d` | 跳过 | 含 `CrossSectionalRank` ×2，需全市场面板，6 只股票下 rank 只有 6 档 || `nl_size` | 跳过 | 含**截面回归** `Residual(Size³ ~ Size)`（每个截面用全市场回归一次）；内层 `size` 已单独验证通过 |
| `fcf_to_market` / `ncf_to_market` / `ocf_to_market` | 跳过 | 含 `CrossSectionalRank` + 需现金流量表 TTM |
| `ebitda_to_market` / `earnings_cut_to_market` / `pegh5` / `etp5` | 跳过 | 含 `CrossSectionalRank` + 需利润表 / 扣非净利润 / 5 年 EPS |
| `sales_to_market` | 跳过 | 含 `CrossSectionalRank`；且公式用**单季**营业总收入 Q（非 `ps_ttm` 的 TTM 口径） |
| `dividend_yield_3y_avg` | 跳过 | 含 `CrossSectionalRank` + 需 3 年每股实派分红（分红表） |

**另一条通用经验**：本批多个因子的 `verdict`（maxerr）判 FAIL 而 `verdict_med`（中位）判 EXACT，
如 `rsi`（max_abs 19.06 但中位相对误差 0）、`days_down_up`（max_abs 1~5 但中位 0）。
原因是少量 stock-day 落在 §G2 的未沉淀窗口或个别离群上。**这再次说明中位口径才是可用性判据。**

### 2.5.3 Value 族横截面因子的内层口径标定（进行中）

这些因子的共同形式是 `CrossSectionalRank(某比值 / MarketCap)`，内层口径可用
「全市场官方值 vs 本地内层比值」的**秩相关**来标定（内层对了秩就一致）。
抽样 800 只、单日 20260811、本地数据取自离线镜像 `recent_3tables`：

| 因子 | 候选内层口径 | Spearman | 结论 |
|---|---|---|---|
| `sales_to_market` | **单季营业总收入 / 总市值** | **0.9901** | ✅ 内层确认（分母是**总**市值） |
| `sales_to_market` | 单季营业总收入 / 流通市值 | 0.9441 | ✗ |
| `ocf_to_market` | OCF_TTM / 总市值 | 0.8092 | ⚠️ 最接近但未达标 |
| `ocf_to_market` | OCF_TTM / 流通市值 | 0.8068 | ✗ |
| `ocf_to_market` | OCF **累计**（非 TTM）/ 总市值 | 0.4267 | ✗ 可确认**必须用 TTM** |

- `sales_to_market` 的公式 `TotalOperatingRevenue_Q / (ClosePrice × TotalShares)` 已确认：
  **单季**（不是 TTM）、分母**总市值**（`total_mv`，不是 `circ_mv`）。
- `ocf_to_market` 的公式写 `NetOperateCashFlow_TTM / MarketCap`；实测「TTM 明显优于累计」
  证实了 TTM 方向，但 **TTM 的具体构造方式仍未标定**（推测与报告期对齐方式有关，
  当前用 `本期累计 + 上年年报 − 上年同期累计`）。
- 其余 4 个（`ncf_to_market`、`fcf_to_market`、`ebitda_to_market`、`earnings_cut_to_market`）
  需要现金流量表/利润表的 `c_pay_acq_const_fiolta`、`ebitda`、`profit_dedt` 等科目，
  离线镜像 `recent_3tables` **不含**这些列（只有精简的 4~6 列），
  需另取 Tushare 逐股接口或改用 `fina_indicator`（116 列，含 `ebitda`/`profit_dedt`）。

---

## 3. 结构性约束：横截面算子需要**全市场**股票池

**Alpha101 族大量使用横截面算子**（对 76 个 Alpha101 因子的公式做算子词频统计）：

| 算子 | 出现次数 | 性质 |
|---|---|---|
| `Rank` | 108 | **横截面**（全市场百分位排名） |
| `Scale` | 7 | **横截面**（缩放使 Σ\|x\|=1） |
| `IndNeutralize` | 8 | **横截面 + 行业分类**（按行业中性化） |
| `Ts_Rank` / `Delta` / `Sum` / `Delay` / `Ts_Min` / `Ts_Max` / `StdDev` | 22 / 54 / 36 / 36 / 14 / 9 / 9 | 时序（个股独立） |
| `Correlation` / `Covariance` | 33 / 2 | 时序（对每只股票在窗口内） |
| `Decay_Linear` / `Sign` / `Abs` / `Ts_ArgMax` / `Log` / `SignedPower` / `IF` / `Min` / `Product` | 9 / 8 / 5 / 4 / 2 / 2 / 2 / 1 / 1 | 时序/逐元素 |

**含义：**

- 横截面算子的取值**取决于参与排名的股票全集**。用 6 只样本股复现 `Rank` 得到的百分位与官方（基于全市场约 5500 只）**必然不同**，与实现正确性无关。
- 因此 **Alpha101 族必须取全市场股票池校验**。
- 可行路径：`factor_value` 按 `(factor_name, trade_date)` 取单日全市场 ≈ 5500 行 < 6000 行上限 → **一次调用即得一整日全市场**；Tushare `daily` 单日全市场约 5549 行，0.6 秒/日。
- 无横截面算子的因子（如 `dif`/`ma_20d` 等纯时序族）可继续在小样本股上校验。

**这是批次二（Alpha101 / Momentum / Risk 等）的架构前提。**

### 3.1 横截面依赖的全库扫描（**关键**）

对全部 242 条当前因子做横截面算子扫描（脚本：`scripts/qdata/audit_formulas.py`，
完整结果见 `FORMULA_AUDIT.md`），结果远超预期 —— **126/242 条（52%）需要全市场校验**：

| 族 | 含横截面算子 | 总数 | 涉及算子 |
|---|---|---|---|
| **Alpha101** | **54** | 71 | `Rank` 49、`IndNeutralize` 7、`Scale` 5 |
| **Quality** | **51** | 59 | `CrossSectionalRank` |
| **Growth** | **12** | 15 | `CrossSectionalRank` |
| **Value** | **8** | 11 | `CrossSectionalRank` |
| **Reversal** | **1** | 3 | `CrossSectionalRank`（`small_cap_reversal_21d`） |
| Liquidity | 0 | 35 | — |
| Risk | 0 | 25 | — |
| Momentum | 0 | 20 | — |
| Size | 0 | 3 | — |

合计：`CrossSectionalRank` 72 条、`Rank` 49 条、`IndNeutralize` 7 条、`Scale` 5 条。
（注意：`Ts_Rank` 是**时序**算子，不可与横截面 `Rank` 混淆。）

**注意：`CrossSectionalRank` 不是 Alpha101 独有的** —— Quality/Growth/Value 族大量使用它，形式为：

```
roa_ttm  : ROA = NetProfit / TotalAssets    →  Factor = CrossSectionalRank(ROA)
eps_ttm  :                                    Factor = CrossSectionalRank(BasicEPS)
```

**含义：这些因子在 6 只样本股上验证必然 FAIL，与实现正确性无关**（6 只股票的 rank 只有 6 个离散档位，官方是全市场连续百分位）。

**处理策略（按成本从低到高）：**

1. **剥壳验证**：只验证内层原始比值，用官方的全市场 rank 与该比值做**秩相关/单调一致性**检验 —— rank 是单调变换，秩一致即证明内层公式正确。这是最省成本的路径。
2. **全市场面板**：见 §3.2，可离线构建。

### 3.2 全市场面板的可行路径（已实测）

| 数据 | 路径 / 接口 | 规模 | 成本 |
|---|---|---|---|
| 行情（全市场） | Tushare `daily(trade_date=...)` | 5549 行/日 | 0.6 s/日 → 300 日约 3 分钟 |
| 官方因子值（全市场） | `factor_value(factor_name=..., trade_date=...)` | ~5500 行/日，**恰在 6000 行上限内** | 1 次调用/因子/日 |
| **daily_basic（全市场，离线，全历史）** | `data/external/tushare/a_share_daily_basic_pit_v1/normalized/daily_basic.csv.gz` | **20160104~20260807 / 2574 交易日 / 5792 只 / 10,926,572 条** | **免费** |
| **财务（全市场，离线）** | `data/external/tushare/a_share_financial_pit_v1/normalized/fina_indicator.csv.gz` | **116 列 / 5802 只 / 245966 行 / 89 个报告期（20091231~20260630）**，带 `ann_date`+`end_date` → PIT 就绪 | **免费** |
| 三大报表（全市场，离线） | `.../a_share_financial_pit_v1/recent_3tables/{income,balancesheet,cashflow}_<code>.csv.gz` | 5690 只 × 3 表（近期；income 每股约 7 个报告期，**累计值**需差分算单季） | 免费 |
| 三大报表（历史，离线） | `.../a_share_financial_pit_v1/full/normalized/batch_*/`、`.../balancesheet_v1/normalized/batch_*/` | 2009-2024 | 免费 |
| 指数行情 | Tushare `index_daily` | — | 免费 |

**`daily_basic` 离线镜像的字段**（`normalized/daily_basic.csv.gz`，18 列，实测 20260807 单日 5535 行）：

| 字段 | 含义 | **单位（实测确认）** |
|---|---|---|
| `ts_code` / `trade_date` | 代码 / 交易日 | `YYYYMMDD` 整数 |
| `close` | 当日收盘价 | 元（**原始价，非复权**） |
| `turnover_rate` / `turnover_rate_f` | 换手率 / 自由流通换手率 | **百分数**（0.4550 = 0.455%） |
| `volume_ratio` | 量比 | 倍 |
| `pe` / `pe_ttm` | 市盈率 / 市盈率(TTM) | 倍（亏损为 NaN） |
| `pb` / `ps` / `ps_ttm` | 市净率 / 市销率 | 倍 |
| `dv_ratio` / `dv_ttm` | 股息率 | **百分数** |
| `total_share` / `float_share` / `free_share` | 总股本 / 流通股本 / 自由流通股本 | **万股** |
| `total_mv` / `circ_mv` | 总市值 / 流通市值 | **万元** |

（校验：000001.SZ @20260807 `total_share`=1.940592e6 万股 = 194.06 亿股 ✓、`total_mv`=2.171522e7 万元 = 2171.5 亿元 ✓）

→ **Liquidity 族（换手率类 35 条）与 Value/Size 族（市值、PE/PB/PS 类）可完全离线复现**，无需调用 Tushare。
**但注意**：qdata 官方可能自算（自算 = 用原始财报 / 市值），直接用镜像的预计算字段**口径可能不同，必须实测标定，不要假设相等**。

⚠️ **本地行情镜像不可用于长窗口因子**：`data/external/tushare/market_daily_v1/` 虽有 5567 只股票，
但每只 CSV **只有 36 行（2026-07-24 ~ 2026-09-10，35 个交易日）**。
其 `adjclose` 列等于后复权价（与 Tushare `原始收盘 × adj_factor` 逐位一致，已验证），
`close` 列 = 原始价 × `factor`（另一套归一口径，约 0.2432），**不要误用**。
→ 价量类长窗口因子必须走 Tushare API `daily`。

⚠️ **重要限制**：Tushare 的 `income` / `balancesheet` / `cashflow` / `fina_indicator` **不支持按 `period` 批量取全市场**（必须传 `ts_code`），逐股拉 5500 只成本极高 → **全市场财务面板必须走本地镜像**。只有 `express` 支持 period 批量。

✅ `fina_indicator` 的 116 列中已直接包含 `current_ratio` / `quick_ratio` / `cash_ratio` / `ar_turn` / `ca_turn` / `fa_turn` / `assets_turn` / `gross_margin` / `ebit` / `ebitda` / `roa` / `roe` / `netprofit_margin` 等。**但这些是 Tushare 预计算字段，qdata 官方可能自算，口径是否一致必须实测标定，不可假设相等。**

### 3.4 `CrossSectionalRank` 的标定（**已解开**）

用 `roa_ttm` @2026-08-11 单日全市场官方值（1 次 `factor_value` 调用，5430 行）实测：

```
CrossSectionalRank(x) = rank(x) / N
```

- `rank` 为**升序**排名，取值 `1..N`；
- `N` = 该横截面参与排名的股票数（**实测 N = 5430**，而 Tushare `daily` 当日全市场 5549 行
  → qdata 有约 119 只的过滤，需另行标定）；
- 官方值 `min = 0.000184 = 1/5430`、`max = 1.0000 = 5430/5430`、
  `mean = 0.5001 = (N+1)/(2N)`（与理论完全吻合）；
- **5430 行全部互异**，说明横截面上几乎无并列，`rank` 的 method 参数影响可忽略。

**内层公式标定（以 `roa_ttm` 为例，公式 `ROA = NetProfit / TotalAssets`）：**

抽样 1136 只（面板 `recent_3tables`，PIT 按 `ann_date <= 20260811`），
对官方全市场秩做 Spearman 检验：

| 候选内层口径 | Spearman |
|---|---|
| **归母净利润(TTM) / 期末总资产** | **0.9928** ✅ |
| 归母净利润(TTM) / 平均总资产 | 0.9922 |
| 累计（单期）归母净利润 / 期末总资产 | 0.809 ✗ |
| Tushare `fina_indicator.roa`（单期预计算字段） | 0.752 ✗ |

**结论**：`roa_ttm` 的内层是 **TTM 归母净利润 ÷ 期末总资产**（不是单期，也不是 Tushare 的
预计算 `roa`）。TTM 构造 = `本期累计 + 上年年报 − 上年同期累计`。
残差（0.9928 而非 1.0）来自**股票池过滤（5430 vs 5549）、报告期选择、并列处理**等，
尚未完全标定。

#### 直接证据：qdata 确实会**修订历史因子值**

qdata 保留了 10 个 `_old_20260821` 快照因子（即 2026-08-21 时点的存档）。把每个快照与
其当前同名因子在重叠区间上逐日比对，得到**直接证据**（2026-09-17 实测，标的 600519.SH）：

| 因子 | 族 | 重叠 | 值发生变化的日数 | 变化区间 | 性质 |
|---|---|---|---|---|---|
| `sum_abs_rtn_amount_20d` | Liquidity | 76 | **76** | 2026-05-06~08-20 | **定义被整体替换** |
| `alpha101_10` | Alpha101 | 76 | 65 | 2026-05-06~08-20 | **定义被整体替换** |
| `alpha101_1` | Alpha101 | 76 | 9 | 2026-05-08~08-20 | 数据修订（零散） |
| `rsi` | Reversal | 76 | **4** | **2026-08-14~08-20** | **近期暂定值修订** |
| `alpha101_23` / `alpha101_7` / `alpha101_9` | Alpha101 | 76 | 0 | — | 未修订 |
| `days_beyond_upper_lower_21d` | Risk | 76 | 0 | — | 未修订 |
| `days_down_up` | Momentum | 76 | 0 | — | 未修订 |
| `price_dist` | Reversal | 76 | 0 | — | 未修订 |

**两条结论：**

1. **qdata 会修订近期因子值。** `rsi` 在 2026-08-14 ~ 08-20（快照日前 5 个交易日）
   的值在 08-21 与 09-17 两个时点**不同**，而 08-14 之前的值完全不变。
   这正是 §G2 沉淀窗口的机制来源 —— **近期值是"暂定值"，事后会被回填修正**。
   （这解释了为什么"用当前官方值去校验最近 N 天"必然失败：拿的是暂定值。）
2. **⚠️ `_old_` 快照因子不等于"同一因子的旧时点值"。** `sum_abs_rtn_amount_20d` 与
   `alpha101_10` 的 **全部/绝大部分日期都不同**，说明它们是**被替换掉的旧定义**。
   → 复现时**只做不带 `_old_` 的当前因子**（共 242 条），不要把 `_old_` 当作同公式的
   另一个版本去比对。

> 注：`dif`/`dea`/`MACD` 一族在 08-14 起的偏差**长达 20 个交易日**，比 `rsi` 观察到的
> 5 日修订窗口更长，说明该族可能同时叠加了"更长的暂定窗口"或"另一条价格管道"。
> 无论成因为何，处理方式一致：**判定时截断尾部**。

**⚠️ 判据必须换**：横截面因子的本质是"排序"，不是"数值"。
两个股票名次差 10 位，因子值只差 `10/5430 = 0.0018`，但 `facsim.compare` 的
`verdict`（maxerr）会因此直接判 FAIL，掩盖"99% 名次都对"的事实。

**参与排名的股票池（N=5430）的标定结果（2026-08-11 实测）：**

| 检验项 | 结果 |
|---|---|
| Tushare `daily_basic` @20260811 | 5539 只（当日**有交易**的股票） |
| 官方池 | **5430** 只 |
| 官方 ⊂ daily_basic | **否** —— 官方有 4 只当日**停牌**（不在 `daily_basic`） |
| daily_basic − 官方 | 113 只 |
| 被排除的 113 只构成 | 北交所 46、主板 27、科创板 22、创业板 18，**几乎全是次新股**（上市日 2025-05 ~ 2026-08） |
| 官方池是否含 ST | **含，204 只** → **没有 ST 过滤** |
| 官方池是否含停牌 | **含** → 股票池不是"当日可交易" |
| 是否要求"已有财报公告" | **否** —— 排除池仅 3/113 无有效财报，官方池也有 1 只无财报 |
| 是否有干净的上市日切分 | **否** —— 官方池含 2026-04-24 上市，排除池含 2025-05-13 上市，25 只排除股上市早于 2026-01 |

**结论：qdata 的横截面股票池是一份外部维护的名单（含 ST、含停牌、剔除部分次新），
无可以从公开字段推导出的简单规则。** 因此：

- **不必追求 N 完全一致** —— 用秩相关判据（`xs_compare`）即可验证公式正确性；
- 若要产出与官方同尺度的因子值，用自己的股票池算 `rank/N` 即可，
  但须在文档中标注"股票池口径与官方不同（本实现用 XXX，官方 N=5430）"。

→ **已新增 `scripts/qdata/xs_compare.py`**：逐日横截面 Spearman 判据

| 档位 | 条件 |
|---|---|
| EXACT | `spearman_med >= 0.9999` 且 `spearman_min >= 0.999` |
| GOOD | `spearman_med >= 0.999` |
| APPROX | `spearman_med >= 0.99` |
| FAIL | 其他 |

用法与 `facsim.compare.compare_family` 完全一致（同样的
`dict[因子 -> DataFrame(index=交易日, columns=股票代码)]` 入参），可直接复用同一套数据加载。
辅助函数 `rank_of(series)` 把原始比值转成 qdata 口径的 `rank/N`。

### 3.3 与聚宽体系的公式交叉验证（交付项 ⑤）

qdata（242 条）与聚宽（276 条）**同名因子仅 7 个**：

| 因子 | qdata | 聚宽 | 结论 |
|---|---|---|---|
| `current_ratio` | `CurrentAssets / CurrentLiabilities` | `流动资产合计/流动负债合计` | ✅ 一致 |
| `quick_ratio` | `(CurrentAssets − Inventory) / CurrentLiabilities` | `(流动资产合计−存货)/流动负债合计` | ✅ 一致 |
| `roa_ttm` | `CrossSectionalRank(NetProfit / TotalAssets)` | `净利润(TTM)/期末总资产` | ⚠️ qdata **多套一层横截面排名** |
| `eps_ttm` | `CrossSectionalRank(BasicEPS)` | `归母净利润(TTM)/总股本` | ⚠️ 同上，且口径不同 |
| `roe_ttm` | `NetProfit_Parent / TotalEquity`（passthrough） | `净利润(TTM)/期末股东权益` | 近似，qdata 为直通因子 |
| `size` | `−log(TotalShares × ClosePrice / 1e6)` | `natural_log_of_market_cap` | ⚠️ **符号相反**（qdata 为负对数，值越小市值越大） |
| `financial_leverage` | `TotalAssets / TotalShareholderEquity` 后套 `CrossSectionalRank` | （聚宽无公式） | — |

**两条跨体系结论：**
1. **同名不代表同口径** —— 不可跨体系套用实现或符号（尤其 `size` 符号相反）。
2. qdata 大量在原始比值外**额外套 `CrossSectionalRank`**，这是与聚宽风格因子最本质的差异。

---

## 3.5 Tushare 数据可得性实测（2026-09-17）

> 澄清：早期侦察记录称"项目内 Key 仅开通因子库、`daily` 等一律 403、输入必须来自本地"。
> **该结论已作废** —— 项目配置的 Tushare TOKEN 权限完整。以下为实测结果。

| 接口 | 状态 | 规模 | 备注 |
|---|---|---|---|
| `daily` | ✅ | 5549 行/日（全市场），0.6 s | 覆盖至 2026-09-10 |
| `daily_basic` | ✅ | 5549 行/日，18 列 | `close/turnover_rate/turnover_rate_f/volume_ratio/pe/pe_ttm/pb/ps/ps_ttm/dv_ratio/total_share/float_share/free_share/total_mv/circ_mv` |
| `adj_factor` | ✅ | — | 复权因子 |
| `stock_basic` | ✅ | 5565 行，10 列 | **含 `industry` 字段 → 解除 `IndNeutralize` 的阻塞** |
| `trade_cal` | ✅ | — | 交易日历 |
| `income` | ✅ | 85 列 | 利润表，含 `ann_date`（公告日）/ `end_date`（报告期）→ 可构 PIT 面板 |
| `fina_indicator` | ✅ | 108 列 | 财务指标（ROE/毛利率/周转率等） |
| `balancesheet` | ✅ | 152 列 | 资产负债表 |
| `cashflow` | ✅ | 97 列 | 现金流量表 |
| `index_daily` | ✅ | — | 指数行情（基准用） |
| `index_weight` | ✅ | 300 行/期 | 指数成分权重 → 可用于定义股票池 |

**重要影响：**

1. **Quality（59）+ Growth（15）两族可做** —— 四大报表齐全。注意用 `ann_date` 构 PIT，避免前视偏差。
2. **`IndNeutralize` 可做** —— `stock_basic.industry` 提供行业分类（Tushare 口径，非申万；若与 qdata 口径不一致，需在报告中标注为口径未标定）。
3. ⚠️ `tushare.set_token()` 会写 `/root/tk.csv`，在沙箱下**只读失败**；应改用 `ts.pro_api(load_token())` 直接传入 token。
4. Tushare 各接口有**每分钟调用次数限制**，批量取全市场/多年数据时需顺序调用并加 `time.sleep`。

---

## 5. 批次三（Liquidity/Risk）、批次五（Alpha101）口径标定

### 5.1 Liquidity（35）+ Risk（25）—— **60/60 全部通过**（已沉淀窗口 34 EXACT + 26 GOOD）

| # | 约定 | 证据 |
|---|---|---|
| 1 | ⚠️⚠️ **`ts_env.TSPanel` 的 `AMOUNT` / `V` 已被乘过 `adj_factor`**（源码 `out[dst] = raw[src] * factor`）→ **原始成交额 = `AMOUNT / ADJ`（千元），原始成交量 = `V / ADJ`（手）** | `amount_ma_20d` 直接用 `AMOUNT` rel **1.18 ✗** → `/ADJ` 后 **3e−16 ✓**。**本条影响所有量额类因子（流动性/量价/Alpha101 的 V 类）** |
| 2 | ✅ **成交额单位 = 元**（Tushare `daily.amount` 千元 × 1000） | `amount_ma_20d` maxerr 9.5e−07；用千元 → rel 1.1e+03。本地 20 日均值（元）4085366035.0 vs 官方 4085366035.4 |
| 3 | ✅ **`DailyTurnoverRate` = `daily_basic.turnover_rate / 100`（小数），不是自算 `vol/float_share`** | 29 条换手率因子由 1e−05 提升到 ~1e−08。⚠️ 自算只差 ~1e−5 相对，**打印出来完全一样**，只有逐位比对才暴露。备选排除：`turnover_rate_f` rel 0.74 ✗、`vol/total_share` ✗、×100 rel 65~85 ✗、std 用 ddof=0 rel 1.6e−02 ✗ |
| 4 | ✅ `turnover_ma_*`：`VolCapRatio = Volume(股) / (原始收盘价 × 流通股本)(元)`，结果**取负** | `turnover_ma_20d_120d` 5.8e−10 EXACT；用后复权收盘 rel 4.9e−03 ✗ |
| 5 | ✅ `bias_turn_{s}d_{l}d` 的两个数字 = **短窗口 s×21 日 / 长窗口 l×21 日**（504d → 24×21） | 16 条 `bias_*_turn_*` 全部 EXACT |
| 6 | ✅ `high_low_{n}d` = `Max(C_hfq, n) / Min(C_hfq, n)` | 5 条全部 maxerr ~5e−11 |
| 7 | ✅ **`sigma_1320d_*` / `beta_consistency_1320d_*` 是「日频残差序列」的再滚动（双层窗口）**：`Residual_t = r_t − α_t − β_t·R_t`（α/β 取自以 t 结尾的滚动 1320 日回归），`sigma = Residual.rolling(1320).std(ddof=1)`；`beta_consistency = (β_t × Residual_t).rolling(1320).std(ddof=1)` ⇒ **有效回看 2×1320 = 2640 交易日，面板起点须 ≤2014-01-01** | 本实现 GOOD（2.9e−07/3.4e−07/1.2e−06）；"窗口内残差 std"的直觉错解 FAIL（0.13） |
| 8 | ✅ 滚动回归族：**简单收益 + `index_daily.close`（不复权）+ 窗口含当日 + `Cov/Var`**；`000001` 后缀是**上证指数 `000001.SH`，不是平安银行** | `beta_60/125/250/500d_000300`、`volume_beta_120d_000300` 全窗口 maxerr **5e−11** |
| 9 | ✅ `adjusted_sharpe_750d` 分母是 `std**4`（四次方）；`days_beyond_upper_lower_21d` 是**双层滚动**计数 | maxerr = 0 逐位相同 |

**未通过归因**：`verdict_med` 下 0 个 FAIL。最严 `verdict`(maxerr) 下仅 `sharpe_750d` / `adjusted_sharpe_750d` 判 APPROX，
归为 **P 类（长窗口数据微差累积）**：残差随窗口长度单调增长（252 日因子 1e−9 级 → 500 日 2e−05 → 750 日 2e−04），
且为近似恒定加性偏移；已排除对数收益 / `ddof=0` / 窗口±1 / 指数滞后 1~2 日。中位误差 ≤4e−06，corr = 1.000000。

### 5.2 Alpha101（71）—— 5 条新约定（阶段 A 实测钉死）

| # | 约定 | 证据 |
|---|---|---|
| 1 | ⚠️⚠️ **`Rank` 的并列取「最大名次」**：`Rank(x) = count(x_i ≤ x)/N` = `pandas.rank(axis=1, method="max")/N`，**不是 `average`** | `alpha101_33 = Rank(Open/Close−1)` @20260811 当日有 180 只 `Open==Close`：`average` → 名次 2196.5 ❌，`max` → 2289 = 官方 ✅，且 5539 只的「官方名次 − 本地点名次」**只取 {0,3}**，零残差。**`roa_ttm` 的结论（5430 只互异 ⇒ `rank/N`）与此不冲突 —— 那只是恰好无并列；只要有并列，`average` 就会错** |
| 2 | ⚠️ **`Ts_ArgMax` 是「距最大值的天数」**（不是 `np.argmax` 的位置口径，两者**排序恰好相反**），且并列取**最近**一次 | `alpha101_1`@20260109：位置口径 Spearman **−0.9385**（几乎完全反序）→ `since` 口径 +0.9385；再叠加"并列取最近"后中位误差 0.4289 → **5.6e−17**（精确）。复现：`since = (d−1) − argmax_0based`，argmax 用 `filled[:,:,::-1].argmax()` |
| 3 | ⚠️⚠️ **Alpha101 用不复权价**（见 §G1） | 4 个因子逐位验证 |
| 4 | **停牌日「走平」**：`O=H=L=C=前一交易日收盘`，但 **`V`/`AMOUNT` 保持 NaN** | 官方 20260811 `alpha101_101` 有 5542 行而 Tushare `daily` 只有 5539 行；多出的 3 只当日无成交、官方值 = 0 ⇒ `O==C`。同日 `alpha101_12`（用 `Delta(Volume,1)`）只有 5539 行 ⇒ 停牌日成交量是 NaN 而非 0。⚠️ 走平会给退市股无限前向填充，须按 `stock_basic.delist_date` 剔除 |
| 5 | `Ts_Rank(x,d) = count(x_i ≤ x_t)/d`（**含并列**）；`StdDev` 用 **`ddof=1`** | `alpha101_43`：`le` maxerr **1.1e−16** ｜ `lt` 0.43 ｜ `min` 0.32 ｜ `avg` 0.44。`alpha101_18`：ddof=1 → 5.0e−11 ✅ ｜ ddof=0 → 0.245 ❌ |

**尚未标定**：官方"每日股票池"（同一天不同因子返回 4930~5555 行，Tushare `daily` 当日 5539~5550，差额规则未知）。
多因子共用池约束下外层 `Rank` 可完全对齐，但**窗口内历史日的横截面排名无法完全对齐**，
会使 `Correlation(Rank(..), Rank(..), d)` 类因子留下 ~1e−3 的中位残差。**该残差归为「股票池未标定」，不是实现错误。**
`IndNeutralize` 依赖 `stock_basic.industry` 去均值实现，官方行业口径未知，7 个因子（48/58/59/63/67/69/70）标注为"口径未标定"。

### 5.3 批次二（Momentum/Reversal/Size/Value）—— 37 条 → 28 实现 / 27 通过

**结果**：纯时序 26 个 `verdict_med` = **EXACT 17 / GOOD 8 / FAIL 1**；
横截面 2 个（全市场逐日 Spearman）= `small_cap_reversal_21d` **EXACT**（sp_med 0.999998，
51 日 × 5454 只）、`nl_size` **GOOD**（0.999634）。**用 6 股绝对误差会把这两个误判成 APPROX/FAIL**，
是 §3.4 判据分族的又一实证。

**新标定口径（公式文档未写）**：

| # | 约定 | 反例 |
|---|---|---|
| G8 | `days_down_up`：连续计数用 `C_hfq.diff()` 的**严格** `>0 / <0`，当前笔连续长度、另一侧清零；`abs(up-down-1)` | 非严格符号尾部 maxerr 5（严格 1） |
| G9 | `rsrs`：**后复权** High/Low 的 18 日 OLS 斜率 + 200 日 z-score，**`ddof=1`** | `ddof=0` → APPROX；raw → FAIL |
| G10 | `price_dist` 用**后复权价 `C`**（与直觉相反），`ceil(scale) - scale` | raw 版 FAIL（med_rel 0.72）；`nearest` 中位也对但 maxerr 1.0 |
| G11 | `price_position_ir_60d`：Ratio 对复权不变，`StdDev` 用 `ddof=1` | `ddof=0` → APPROX |
| G12 | `rsi`：Wilder = `ewm(com=period-1, adjust=False)`（alpha=1/period），**不是 `span=period`**；价格后复权 | `span=period` FAIL |
| G13 | `size` / `float_size` = `-log(total_mv/100)`（**百万元**计）、**负对数** | `/1e6`、`total_share×price/1e6`、正号 全 FAIL |
| G14 | `earnings_to_price` = 归母净利润 TTM / 总市值（`1/pe_ttm` **仅在盈利股上巧合成立**）；`book_to_market` 含 DTA | 亏损股 `pe_ttm`=NaN，官方仍有负值 → 覆盖率仅 83.3% |
| G15 | `alpha_*d_*`：个股**简单**日收益(`C_hfq`) 对指数 `index_daily.close.pct_change()` 的滚动 OLS **截距**，窗口含当日 | raw 收益全 FAIL；指数用 `pct_chg/100` 不如 `close.pct_change` |
| G17 | `CrossSectionalRank(x) = rank(x)/N`；`small_cap` 的 CumReturn 用后复权 | raw spearman 0.99976 vs hfq 0.999998；`(rank-1)/(N-1)` 更差 |

`earnings_to_price` 的精确式（本地 `fina_indicator` 实测）：
`TTM(profit_dedt + extra_item) / (total_mv × 1e4)`，PIT 对齐后 med_rel **7.5e-11**。

> ⚠️ **`rank` 的并列处理，两个子代理给出不同结论，尚未收敛：**
> Alpha101 族实测 **`method="max"`**（`alpha101_33` 当日 180 只并列，`max` → 名次 2289 = 官方 ✅，
> `average` → 2196.5 ❌）；批次二对 Value/Size 族用的是 **`average`** 且也通过了。
> 推测并列处理**可能分族**（或并列样本恰好未落在关键位置）。**复现新因子时应两个 method 都试。**

### 5.4 顺带修复的项目缺陷

`scripts/factorlib/ops.py::rolling_beta` 的 `resid` 返回值在 `x` 为 `Series`（指数收益）时**全为 NaN**：
原式 `beta * x` 会让 pandas 用 Series 的**索引（日期）**去对齐 DataFrame 的**列（股票代码）**。
已改为 `beta.mul(x, axis=0)` 并顺带修正了 α 的符号（须 `α + βx`，不是 `α − βx`）。
**验证**：恒等式 `max|resid − (y − α − βx)| = 3.5e−18`；`beta`/`alpha` 与 `np.polyfit` 6 位小数一致；
`x` 为 `Series` / `DataFrame` 两条分支均通过。

---

## 5.5 ⚠️ 判据必须**实证**确定，不能读公式文本

**本文档 §3.1 的横截面扫描基于公式文本，已被证明不可全信。** 两个方向都会错：

| 方向 | 实例 | 后果 |
|---|---|---|
| 文本说含 `CrossSectionalRank`，实为**原始比值** | `de`（官方值 −166.29 ~ 412.61，不是 `rank/N`） | 误以为需要全市场，白白增加成本 |
| 文本**省略**了排名包装，实为 `rank/N` | `roe_ttm` / `quality_composite` / `nl_size` 等 `passthrough`/复合因子 | **误用绝对误差判据 ⇒ 在样本股上得到不可能成立的 EXACT ⇒ 虚报成果** |

**正确做法（`scripts/qdata/classify_factors.py`）**：取单日全市场官方值，用**分布签名**判别：

* 纯 `rank/N` 型：`max ≈ 1.0`、`min > 0`，且取值是 `k/M` 的**量化形式**
  （`M = round(1/min)`，检验 `v × M` 是否几乎全为整数）。
* 其余为原始比值 ⇒ 绝对误差判据即可。

⚠️ **不可要求 `uniq == N`**：并列会让互异值个数少于行数
（实测 `eps_ttm` N=5417/uniq=3337、`eaa` N=5401/uniq=4234，二者 min≈1/N、max=1.0，
仍是排名型）。

**全库实证结果（242 条，2026-08-11）**：

| 类型 | 条数 |
|---|---|
| `rank_N`（无并列） | 43 |
| `rank_N_ties`（有并列） | 18 |
| **纯 `rank/N` 合计** | **61** |
| 非纯 rank（含 Alpha101 的 71 条 rank 派生因子） | 181 |

**含义**：Alpha101 族的 71 条由 `Rank` 派生但值是复合量（如 `Rank(...) − 0.5`、乘积），
分布不落在 `[0,1]` 的量化网格上 ⇒ 被归为"非纯 rank"，但它们**仍必须用横截面判据**。
因此"是否需要横截面判据" = `纯 rank` ∪ `含横截面算子`，不能只靠任一单一信号。

---

## 5.6 ⚠️ `CrossSectionalRank` 并列口径：算术已定，但**对 Spearman 判定无效**

### 并列取「最大名次」（算术已定）

`CrossSectionalRank(x) = rank(x, method="max") / N`，即 `count(x_i <= x)/N`。

**算术证据**：`yoy_ocf` @20260811，N=4927，官方并列块值 = **3642/4927**；
该块下方 1875 只、块内 1767 只，`1875 + 1767 = 3642` 恰好是块内**最大**名次
（`average` 会给 2759，`min`/`first` 给 1876）。`np_ttm_qoq` 同构（并列值 5294/5426）。

**全代码库已统一为 `method="max"`**：`xs_ops.py`（原本即对）、`repro_quality.py::xs_rank` 与
`order_agreement`、`repro_batch2.py`（`small_cap_reversal_21d` 两处）、`xs_compare.py::rank_of`。

**合成验证**：构造 1875 只 + 1767 只并列 + 剩余的结构，`max` → 3642 ✅（= 官方），
`average` → 2759 ❌，相差 **883 个名次（占截面 18%）**。

### ⚠️ 但该修正**不改变任何 Spearman 判定**（重要更正）

**实测**：改用 `method="max"` 后重跑 `repro_quality_xs.py --window 2024`，
结果与修改前**逐位相同**（30/62；EXACT 16 / GOOD 14 / APPROX 11 / FAIL 21）。

**原因**：`Spearman` 内部先对两侧各自排名，而 `max`/`average`/`min`/`first` 都是
**单调非降**变换，不改变任何一对样本的先后关系 ⇒ **Spearman 恒等不变**。
合成实验：四种口径下 Spearman 均为 `0.977682634950`。

⇒ **该修正对「产出因子数值」是必须的**（若要做本地因子库、要求输出值等于 qdata），
**对「验证判定」完全无效**。**已通过的因子无需因此复验。**

**真正的杠杆 = 复现「哪些股票被并成同一名次」**：并列块的成员在我们的实现里是互异的，
块内排序对协方差贡献为 0、却增加我们这侧的方差 ⇒ 必然拉低 Spearman。

**并列面（实测，基于单日全市场官方值）**：横截面判据因子 135 个中 **70 个有并列**；
未通过的 53 个里 **31 个有并列**、**22 个零并列**。
- 离散输出型（唯一值仅 2~8，并列占 99.9%）：`alpha101_21/27/68/62/65/64`(uniq=2)、`alpha101_1`(5)、`alpha101_58`(6)、`alpha101_59`(8)
- 大并列块：`yoy_ocf` 1766、`eaa` 1167、`alpha101_29` 1084、`pa` 850、`sa` 564

**`yoy_ocf` 并列块的成分（已排除多条假设）**：
- ❌ 不是缺失数据（块内 99.9% 有本地 cashflow 文件）
- ❌ 不是负 OCF（两组负值比例 142/250 vs 152/250）
- ❌ **不是交易所/板块**：块内 SH 1688 / SZ **0** / BJ 79，看似交易所差异，
  但**茅台(600519.SH)、中芯国际(688981.SH)、中国平安(601318.SH) 都在块内**，
  而招商银行(600036.SH) 不在；正常组的 347 只 SH 全是 600xxx ⇒ 板块解释不成立
- ✅ 位置证据：**1875 只在其下、1285 只在其上**（38% / 26%）⇒ 哨兵落在**中段**，
  排除"填最小值/最大值"，**指向哨兵 = 同比 0**（增长率型因子的天然"无信息"值）。
  若成立，等价于断言 38.1% 的股票负增长 —— 数值上合理，**但尚未直接验证**
- ⛔ **验证受阻**：离线镜像 `recent_3tables/cashflow_*.csv.gz` 每股仅约 9 行且含重复
  `(end_date, ann_date)`，去重后唯一报告期常**不足 5 个**，而 `yoy_ocf` 需同比对照
  ⇒ 该镜像**结构上不足以验证此因子**。需改用 Tushare `cashflow` 逐股补期数。

## 5.7 主线 B：`t-252` 交易日 vs 4 报告期对齐 —— **已证伪**

对 `yoy_roa` / `yoy_roe`（官方值**零并列**，N = uniq = 5315 / 5318，成因必为内层比值错位）
做 A/B 对照（全市场 5381 只 × 5 个比对日，脚本 `scripts/qdata/test_yoy_alignment.py`）：

| 因子 | **`t-252` 交易日（现行）** | 4 报告期偏移 |
|---|---|---|
| `yoy_roa` | **0.983670**（min 0.9808） | 0.962633（min **0.7661**） |
| `yoy_roe` | **0.985123**（min 0.9825） | 0.968949（min **0.7794**） |

**结论：报告期偏移更差，`t-252` 交易日口径是对的。** 该假设排除。
（顺带：我独立重构的 `t-252` 版本与现行实现 Spearman **逐位一致**，证明重构忠实。）

**新线索（待验证）**：`ann_date != f_ann_date` 的报告占 **1.79%**
（离线镜像实测 57504 条中 1031 条），与观察到的 **~1.6% 名次不一致率**高度吻合。
样例显示 `f_ann_date` 通常**晚一年**（重述版本），会改变历史时点的 PIT 取值。
**待测：把 PIT 对齐基准从 `ann_date` 换成 `f_ann_date`。**
注意 `ts_fin.py` 已用本地镜像的 `available_date` 区分重述版本。

---

## 5.8 离散输出型因子：**分档归属一致率**判据（新，已带来 +4 个通过）

### 问题

Alpha101 有 **13 个因子是分档输出**（官方值的并列率 ≥ 90%）：
`alpha101_21/27/61/62/65/68` 只有 **±1 两档**；`alpha101_1` 5 档、`alpha101_58` 6 档、
`alpha101_59` 8 档、`alpha101_4` 9 档、`alpha101_43` 86 档、`alpha101_7` 120 档、`alpha101_46` 412 档。

对这类因子，**两个指标各有假阴性**：

| 指标 | 假阴性场景 | 实例 |
|---|---|---|
| `Spearman` | 档位跳变（3~10% 的股票换档）把相关系数严重拉低 | `alpha101_1` Spearman 仅 0.9982 → 判 APPROX |
| **逐值一致率** | 档位值 = `rank_max/N`，**块大小差几只就让整块的值在第 4 位小数上全变** | `alpha101_1` 官方 5 档值 `−0.311169729` vs 本地 `−0.310742152`（差 4e−4）⇒ 逐值一致率 **仅 6.5%**，完全掩盖真相 |

### 正确做法：分档归属一致率

两侧各自 ``rank(method="dense")`` 化为**档位序号**，再统计序号相等的比例。
实现：``xs_compare.compare_agreement``；驱动脚本 ``check_discrete.py``
（产出 ``alpha101_discrete_agreement.csv``）。

### 实测结果（6 个比对日，全市场）

| 因子 | 档数 | 分档一致率 | Spearman | 取较优判定 |
|---|---|---|---|---|
| `alpha101_4` | 9 | **1.000000** | 1.000000 | EXACT |
| **`alpha101_1`** | 5 | **0.998821** | 0.998214 | **GOOD**（原 APPROX） |
| **`alpha101_21`** | 2 | **0.997918** | 0.993763 | **GOOD**（原 APPROX） |
| **`alpha101_27`** | 2 | **0.996555** | 0.993110 | **GOOD**（原 APPROX） |
| **`alpha101_7`** | 120 | **0.996186** | 0.991070 | **GOOD**（原 APPROX） |
| `alpha101_62` | 2 | 0.978945 | 0.945507 | APPROX |
| `alpha101_61` | 2 | 0.964635 | 0.930745 | APPROX |
| `alpha101_68` | 2 | 0.902095 | 0.802466 | FAIL |
| `alpha101_65` | 2 | 0.869649 | 0.738184 | FAIL |
| `alpha101_58` | 6 | 0.623113 | 0.740375 | FAIL |
| `alpha101_59` | 8 | 0.556929 | 0.749686 | FAIL |
| `alpha101_43` | 86 | 0.025235 | **0.999912** | EXACT（一致率假阴性） |
| `alpha101_46` | 412 | 0.136850 | **0.999997** | EXACT（一致率假阴性） |

**判定规则：两个指标都报，取较优者，并在报告中标注 ``judged_by``。**
理论依据：一致率衡量**档位归属**（适合粗档），Spearman 衡量**次序**（适合细档）。

**净收益：Alpha101 45 → 49 通过；全库 172 → 176 通过（+4）。**

⚠️ 同时要注意 `alpha101_58`(0.62) / `alpha101_59`(0.56) —— 它们**两个指标都差**，
且档数 6/8、官方池恒为 5210，是真正的未通过（与 `IndNeutralize` 行业口径有关），
不要因为"分档输出"就误认为它们只是度量问题。

## 5.9 线索 1：PIT 对齐基准 `ann_date` vs `f_ann_date` —— **弱支持，非主因**

`ann_date != f_ann_date` 的报告占 **1.65%~1.79%**（离线镜像实测），与 `yoy_roa`
观察到的 ~1.6% 名次不一致率吻合，故做 A/B（脚本 `test_pit_basis.py`，2500 只子样本）：

| 因子 | `ann_date`（现行） | `f_ann_date` | 变化 |
|---|---|---|---|
| `yoy_roa` | 0.975160 | **0.976565** | +0.0014 |
| `yoy_roe` | 0.979459 | **0.982790** | +0.0033 |

**结论：`f_ann_date` 在两个因子上都略优（方向与假设一致），但幅度仅 0.14%~0.33%，
远不足以解释 ~1.6% 的名次不一致 ⇒ 弱支持，不是主因。** 该线索不能单独解决问题，
但可作为"多因素微调"之一保留。

---

## 5.10 交付 ②：`yoy_ocf` 并列块规则 —— **公开数据不可反推**（归档）

### 实验条件

用 **2009-2024 全列现金流镜像**（期数充足）离线复现 `yoy_ocf`，在 **2024 日**上检验
（避免 `recent_3tables` 期数不足的阻塞；脚本 `analyze_yoy_ocf_block.py`）。

并列结构在 2024 日同样存在，且再次验证 `method="max"`：

| 日期 | N | 并列块 | 值 | 块下方 | 校验 |
|---|---|---|---|---|---|
| 20240812 | 4677 | 1670 | 3517/4677 | 1847 | 1847+1670 = **3517** ✅ |
| 20241105 | 4740 | 1099 | 3325/4740 | 2226 | 2226+1099 = **3325** ✅ |
| 20260811 | 4927 | 1767 | 3642/4927 | 1875 | 1875+1767 = **3642** ✅ |

### 已**全部否证**的假设

| 假设 | 实测 | 结论 |
|---|---|---|
| 缺数据 | 并列块内 **94.7%** 算得出 yoy，非并列 99.1% | ❌ 判别力仅 −4.4% |
| 前期为负 | 并列块 20.1% vs 非并列 20.1% | ❌ 判别力 **0.0%** |
| 交易所/板块 | 茅台 600519.SH / 中芯国际 688981.SH / 平安 601318.SH **在块内**，招商银行 600036.SH **不在**；正常组 347 只 SH 全是 600xxx | ❌ |
| **哨兵 = 同比 0** | **两组的本地 yoy 分布统计上完全相同**：中位 −0.1945 vs −0.2524；\|yoy\| 中位 0.6640 vs 0.7000；负占比 57.1% vs 61.0% | ❌ **关键否证** |
| 报告期不足 4 期 | 4.9% vs 0.0% | ❌ 判别力 +4.8% |
| 当前期为负 | 18.9% vs 22.3% | ❌ 判别力 −3.4% |

### 唯一的干净规则（但覆盖面极小）

**完全没有任何财报的股票**（`n==0`，82 只）**98.8% 落入并列块** —— 精确率 98.8%，但**召回率仅 4.9%~7.4%**。
其余 1588~1609 只并列股票无法解释。

报告期条数类规则（`n<59` / `n<40` / `n<30`）判别力只有 +11%~+26%，最佳 F1 仅 **0.574~0.581**，**不构成规则**。

### 结论（重要）

**并列块的本地 `yoy_ocf` 分布与非并列组统计上无法区分** ⇒
**分组不可能是「OCF 序列本身的任何函数」**（若如此，两组的 yoy 分布必然不同）。
叠加"茅台在内、招行在外"这一事实，规则**只能依赖 qdata 内部因素**
（数据管道/分批处理，或另一套覆盖不同的 OCF 数据源）。

⇒ **`filter=True` 的语义对 `yoy_ocf` 在公开数据上不可反推。** 归档为
「**结构性不可复现（供方内部分组规则未披露）**」，不再投入。

**仍受影响的因子**（大并列块，判别力可能同因）：`eaa` 1167、`alpha101_29` 1084、
`pa` 850、`sa` 564、`alpha101_25` 227、`alpha101_52` 118 ——
建议同样归档，除非后续发现 qdata 披露分组规则。

⚠️ **但对离散输出型因子不适用**：`alpha101_1/21/27/7` 等已由「分档归属一致率」
判为通过（见 §5.8）—— 它们的并列来自**公式本身的有限值域**（`Ts_ArgMax(x,5)` 只有 5 档、
布尔因子只有 ±1），不是供方分组。

---

## 5.11 `IndNeutralize` 行业标准：**4 种标准全部试过，均不达标**（归档）

### 做法

对 7 个依赖 `IndNeutralize` 的因子（`alpha101_48/58/59/63/67/69/70`），
用 4 种行业分组做 `x − mean(x | 行业)` 后重跑逐日横截面 Spearman：
Tushare `stock_basic.industry`（自有粗分类）与**申万一级/二级/三级**
（`index_member_all` 的 `l1_name`/`l2_name`/`l3_name`，实测有权限；中信/同花顺无权限）。
脚本 `test_ind_neutralize_sw.py`。

### 结果（Spearman 中位）

| 因子 | 申万L1 | 申万L2 | 申万L3 | Tushare自有 | **最好** |
|---|---|---|---|---|---|
| `alpha101_48` | 0.8997 | **0.9255** | 0.8750 | 0.9205 | **0.9255** |
| `alpha101_58` | **0.7404** | 0.6340 | 0.5737 | 0.7171 | 0.7404 |
| `alpha101_59` | **0.7497** | 0.6372 | 0.5813 | 0.7368 | 0.7497 |
| `alpha101_63` | 0.8513 | 0.8023 | 0.7675 | **0.8776** | 0.8776 |
| `alpha101_67` | 0.7145 | 0.6953 | 0.6197 | **0.7577** | 0.7577 |
| `alpha101_69` | 0.8392 | 0.7901 | 0.7519 | **0.8729** | 0.8729 |
| `alpha101_70` | **0.8935** | 0.8374 | 0.8088 | 0.8813 | 0.8935 |

### 结论（归档）

**行业层级越细，效果一致地越差**（L3 < L2 < L1，7/7 成立）⇒ **官方用的分组比申万一级更粗，
或完全是另一套方案**（如证监会行业、或仅按主板/创业板/科创板划分）。

**四种标准里最好的只有 0.9255，远低于 0.99（APPROX）阈值** ⇒
**`IndNeutralize` 一族归档为「行业标准未披露，公开可得标准均不达标」**，不再投入。

### ⚠️ 顺带发现并修复的缓存缺陷

`repro_alpha101.py` 的**本地结果缓存键** = `hash(factors, dates, lookback, end, universe, X.CFG)`，
**不含行业来源** ⇒ 换行业标准后仍会命中上一级的缓存。
实测表现为 **申万 L1 与 L2 的结果逐位相同**（0.740375 / 0.749686 / 0.899698），
一度掩盖了真实差异。绕过办法：把 level 注入 `xs_ops.CFG` 让每级各自缓存
（`test_ind_neutralize_sw.py` 已如此处理）。

> **通用教训**：凡是通过猴补丁替换**外部数据源**（行业、股票池、指数）来做 A/B 的实验，
> 都要确认缓存键包含该来源，否则 A/B 会退化成"同一结果跑两遍"。

---

## 5.12 `dividend_yield_3y_avg`：新实现（原未覆盖）—— 窗口口径已确认

### 阻塞解除

该因子此前因"需要 3 年每股实派分红"而未覆盖。实测 Tushare **`dividend` 接口有权限**，
含 `cash_div`（税前）/`cash_div_tax`（税后）/`ex_date`/`record_date`/`imp_ann_date`/`div_proc`。
⚠️ 该接口**不支持批量**（必须给 `ts_code`/`ann_date`/`ex_date` 之一），须逐股取数（已按股落盘缓存）。

### 公式与实现

    dividend_yield_3y_avg = (SUM(ActualCashDiviRMB, 735) / 3) / ClosePrice
    Factor = CrossSectionalRank(dividend_yield_3y_avg)

`ActualCashDiviRMB` = 每股实派分红 → `cash_div_tax`；窗口 **735 = 245×3 交易日**；
把每股分红放在**除权日 `ex_date`** 上、其余交易日为 0，做 735 日滚动求和 /3 / 收盘价。
脚本 `repro_dividend_yield.py`（抽样 600 只，Spearman 在子集上是有效估计量）。

### 变体扫描（4 个比对日，Spearman 中位）

| 口径 | Spearman 中位 |
|---|---|
| **实施 + `ex_date` + 735（基线）** | **0.987713** |
| 全部 `div_proc` + ex_date + 735 | 0.987712 |
| 实施 + `record_date` + 735 | 0.987549 |
| 实施 + `imp_ann_date` + 735 | 0.971207 |
| 实施 + ex_date + **756**（252×3） | **0.975230** ↓ |
| 实施 + ex_date + **504** | **0.952669** ↓↓ |

**结论：窗口 735（=245×3）被确认** —— 756 与 504 都明显更差；`ex_date` 优于
`record_date`/`imp_ann_date`。`cash_div` 与 `cash_div_tax` 的 Spearman 相同（税前/税后
对同一只股票近似为常数比例，不改变排名），属良性。

### 全市场结果（5416 只，分红缓存已全量落盘）

先把 600 只抽样扩到全市场（分批取数，`--fetch-only --limit N`，共 5 批）：

| 口径 | Spearman 中位 | 样本 |
|---|---|---|
| 600 只抽样 | 0.987713 | 2400 stock-day |
| **全市场 5416 只（基线）** | **0.989898** | 21664 |
| 全市场 + `min_periods=735`（需满窗） | 0.989898 | 21664 |
| 全市场 + 剔除上市 < 1 年 | 0.989927 | 21346 |
| **全市场 + 剔除上市 < 3 年** | **0.990599** ✅ **越过 0.99** | 20344 |

**新标定口径：必须剔除上市不足 3 年的股票。** 经济含义自洽 ——
「3 年平均股息率」纳入无 3 年历史的股票时，其 `SUM(...,735)/3` 被系统性低估；
且剔除 <1 年仅 0.989927（几乎无变化），**跳变正好落在 3 年处**，与窗口语义一致。

### 现状：`FAIL` → **`APPROX`**（0.990599）

⚠️ **注意 APPROX 不计入本项目的「通过」（EXACT+GOOD）**，故**全库通过数不变（176）**，
但该因子由 FAIL 升一档，`n_stocks_med = 5085`。

### 残差定位：**不是**供方分组，而是分红归属的窗口边界

官方该因子的最大并列块 **959 只**，`val × N = 959`，且**块下方 = 0** ——
即**位于最底部**，正是「3 年内无分红」的股票。`method="max"` 给该块名次 959，
**本地实现（值 0 → 同名次）已复现这一结构**。
⇒ 剩余 0.9% 的名次不一致出在**有分红股票之间的排序**（个别分红的窗口边界归属），
不是 §5.10 那类供方分组问题。

若要继续压到 GOOD（0.999）需把每笔分红精确对齐到窗口内的哪一天，收益有限，暂不投入。

---

## 5.13 ⚠️ 横截面因子此前**漏用了「数值差不太多」判据** —— 补测后 3 条转为 APPROX

### 用户的方法早已是默认口径（但只覆盖了一半因子）

本项目从一开始就采纳了「**不必完全一致，落在一定误差内即视为公式正确**」的思路，
落地为三口径判据（`facsim/compare.py`）：

| 口径 | 含义 |
|---|---|
| `verdict`（maxerr） | 最严：任何单点超差即 FAIL |
| `verdict_robust`（p99） | 容忍 1% 离群点 |
| **`verdict_med`（中位）** | **只要"大多数样本算得对"就算对** ← 用户方法 |

档位：`EXACT ≤1e-9` / `GOOD ≤1e-4` / `APPROX ≤1e-2`。
效果实例（批次一）：`return_5d` 在 maxerr 下是 GOOD、在中位口径下是 **EXACT**。

### 但**横截面因子从未测过"数值差多少"**

横截面因子（126 条）一直只用 **Spearman（排序一致度）** 判定，
报告里它们的 `med_rel_err` **是空的** —— 即**从未测过数值差多少**。

而这两件事对 `rank/N` 型因子**可能严重不一致**：

> 排序上有 1.4% 的样本对调（Spearman 0.9837，判 FAIL）；
> 但值只差 1~2 个名次 ⇒ **中位相对误差可能只有 0.58%**，按用户标准就是"公式正确"。

补测脚本 `check_xs_median_error.py`（对横截面判据下 FAIL 的 31 条，其中 21 条可测）：

| 因子 | Spearman | Spearman 判 | **中位相对误差** | **中位误差判** |
|---|---|---|---|---|
| `yoy_roa` | 0.983670 | FAIL | **0.5748%** | **APPROX** ✅ |
| `yoy_roe` | 0.985123 | FAIL | **0.5797%** | **APPROX** ✅ |
| `delta_roa` | 0.986422 | FAIL | **0.9916%** | **APPROX** ✅ |
| `delta_npm` | 0.984287 | FAIL | 1.115% | FAIL |
| `delta_opm` | 0.984983 | FAIL | 1.239% | FAIL |
| `cash_profit_ratio` | 0.844036 | FAIL | 1.458% | FAIL |
| `np_ttm_qoq` | 0.915667 | FAIL | 1.524% | FAIL |
| ……（1.8%~21.6%） | | | | FAIL |
| `icr` | 0.829610 | FAIL | **21.55%** | FAIL |

**结论：3 条转为 APPROX**（`yoy_roa` / `yoy_roe` / `delta_roa`）。
其中 `yoy_roa`/`yoy_roe` 正是此前标为"成因未定"的两条 ——
**按用户标准它们的公式是对的**（中位值差 0.58%），只是排序有 1.4~1.6% 的样本对调。
**Spearman 判据比用户标准严得多。**

已把「中位相对误差」纳入汇总器，与离散因子的「分档一致率」同属"两套判据取较优"。

### 两套标准下的总账（2026-09-21 刷新，库内 242 条全部已判定；§5.15 后）

| 标准 | 通过 | 占比 |
|---|---|---|
| **严格口径**（EXACT+GOOD；相对误差 ≤1e-4 / Spearman ≥0.999） | **180 / 242** | 74.4% |
| **用户口径**（+APPROX；相对误差 ≤1e-2 / Spearman ≥0.99） | **203 / 242** | **83.9%** |

⇒ 未通过：严格口径 **62 条**、用户口径 **39 条**（含本轮 `gpm_q` 转通过）。

### 保留意见（诚实说明）

* 用户口径下的 APPROX = "**形状正确但口径有残差**"，适合用于**截面选股 / IC 计算 / 排序**；
  若要**逐值复现**官方数值则不达标。
* 补测的 21 条里，**18 条的中位误差 >1%**（1.1%~21.6%），**不是"差不太多"** ——
  这些是真未通过，不是容忍度问题。
* 31 条横截面 FAIL 中另有 **10 条（Alpha101）不在 2024 窗口的构建范围内**，未补测；
  它们是 §5.6 的行业口径 / 股票池 / 离散跳变问题，预计中位误差也不会小。

---

## 5.14 Value 族 8 条未覆盖因子：全部实现并完成全市场标定（2026-09-21）

### 阻塞是怎么解除的

这 8 条此前记为「未覆盖」，原因是 `recent_3tables`（2025~2026）只有 4 列
（revenue / n_income_attr_p / total_assets / n_cashflow_act），缺 `profit_dedt` /
`ebitda` / 现金流量表明细。

实测发现 **`data/external/tushare/a_share_financial_pit_v1/full/normalized/`**
（54 个 batch、**2009-12-31 ~ 2024-12-31**、收入表 85 列、现金流量表 105 列、
`fina_indicator` 116 列、约 30 万行/表）**三者俱全** ⇒ 转到 **2024 窗口**即可全量验证，
且输入数据完全不占 API 配额（只有官方因子值需要取数）。

同时修正了一个数据层缺陷：`fina_indicator`（`profit_dedt` / `ebitda`）也是**年初至今累计**
口径，必须登记进 `_CUMULATIVE_TABLES`，否则 TTM 构造漏差分。
另外 `stot_cash_inv_fnc_act` 在镜像中缺失，筹资净额改用 `n_cash_flows_fnc_act`。

### 官方值类型（2024-08-12 单日实测）

| 因子 | N | uniq | min | max | 类型 |
|---|---|---|---|---|---|
| `sales_to_market` | 5285 | 5285 | 1.89e-4 | 1.0 | `rank/N` |
| `ebitda_to_market` | 5279 | 5279 | 1.89e-4 | 1.0 | `rank/N` |
| `earnings_cut_to_market` | 5202 | 5202 | 1.92e-4 | 1.0 | `rank/N` |
| `ocf_to_market` | 4851 | 4851 | 2.06e-4 | 1.0 | `rank/N` |
| `ncf_to_market` | 4218 | 4218 | 2.37e-4 | 1.0 | `rank/N` |
| `etp5` | 3427 | 3427 | 2.92e-4 | 1.0 | `rank/N` |
| `pegh5` | 3144 | 3144 | 3.18e-4 | 1.0 | `rank/N` |
| **`fcf_to_market`** | 4838 | 4838 | **−63.59** | **4.26** | **原始比值** |

⇒ 7 条用横截面判据，`fcf_to_market` 用绝对误差判据。

### ✅ 本轮定标成功的两条（文档公式有误 / 需精确到「单季」）

**1. `earnings_cut_to_market` —— 官方用归母净利润，不是扣非**（重大修正）

全市场 5381 只、2024-08-12 单日：

| 分子口径 | Spearman | 名次偏差中位 |
|---|---|---|
| **归母净利润 TTM**（`n_income_attr_p`） | **0.999997** | **18 / 5202 = 0.35%** |
| 净利润 TTM（含少数股东） | 0.986766 | 72 |
| 扣非净利润 TTM（`profit_dedt`，按文档字面实现） | 0.941175 | 137 |
| 归母**单季** | 0.771642 | 392 |

文档写「扣除非经常性损益后净利润TTM」，但原文其实已注明
「**使用归母净利润作为扣非净利润的替代**」—— 实测证明 qdata 确实用的是归母。
⇒ 归母 TTM 口径 **两套判据同时通过**（Spearman 0.999999 / 名次偏差中位 0.92%）。

**2. `sales_to_market` —— 分子是「单季」营业总收入**（已确认，非 TTM）

| 分子口径 | Spearman |
|---|---|
| **单季营业总收入**（`total_revenue` 差分） | **0.999986** |
| 单季营业收入（`revenue` 差分） | 0.997829 |
| TTM 营业总收入 | 0.957383 |
| TTM 营业收入 | 0.955427 |
| 年报营业总收入 | 0.944580 |

与「文档公式写 `TotalOperatingRevenue_Q`」一致 —— 这一条文档没写错，
但与此前 `Quality/Growth` 批「`_Q` 后缀实为累计 YTD」的发现相反：
**该用单季时就得用单季**，不能全库统一按 TTM 处理。

### ⚠️ 已否证的假设（写下来避免重复投入）

| 假设 | 检验 | 结论 |
|---|---|---|
| 现金流类因子对分子取**绝对值** | `\|OCF\|/mv` 0.528（vs 0.763）、`\|EBITDA\|/mv` 0.821（vs 0.978）、`\|OCF+ICF+Fin\|/mv` **−0.032** | ❌ **全部更差，明确否证** |
| `ocf_to_market` 分子含「客户存款/同业拆借」增量 | 该口径只覆盖 283 只（金融机构才披露），0.737 | ❌ 无法解释全市场 |
| `ebitda_to_market` 用年报口径 | 0.9729 vs TTM 0.9775 | ❌ 更差 |
| `ebitda_to_market` = EBIT+营业成本 | 0.5989 | ❌ |
| `fcf_to_market` 用 Tushare `free_cashflow` | 0.2417（vs 基线 0.8507） | ❌ |
| `ncf_to_market` 只算 OCF+ICF（不含筹资） | 0.1838 | ❌ |

### 剩余 6 条的确切状态（已实现、未达标）

| 因子 | 采用口径 | Spearman 中位 | 名次偏差中位 | 性质 |
|---|---|---|---|---|
| `ebitda_to_market` | EBITDA_TTM / 总市值 | 0.910 | 4.16% | 口径未定 |
| `etp5` | `mean(归母年报,1260)/mean(mv,1260)` | 0.984 | 7.86% | 窗口口径未定 |
| `pegh5` | `-Close/(g5·EPS_TTM)`，g5 = EPS 年报 5 年复合 | 0.941 | 6.42% | 口径未定 |
| `ocf_to_market` | OCF_TTM / 总市值 | 0.862 | **1.46%** | **少数金融股错位主导** |
| `ncf_to_market` | (OCF+ICF+筹资净额)_TTM / 总市值 | 0.713 | 15.53% | 口径未定 |
| `fcf_to_market` | (OCF−投资流出)_TTM / 总市值 | 原始比值，中位相对误差 **1e−10** ✅ | — | 公式正确，maxerr 由分母穿 0 主导 |

**`ocf_to_market` 的残差结构值得记下**：名次偏差中位仅 1.46%（多数股票对），
但 p90 = 19.5% —— 差异最大的 8 只**全部是金融股**（601577 / 600649 / 601128 /
600926 / 600755 / 603828 / 603906 / 601658），官方名次 17~109（顶部），
我本地 4989~5073（底部）。银行的经营现金流因存款/同业变动常为大额负值，
但官方并没有取绝对值（上表已否证），**推测是官方对金融业使用了另一套现金流科目**，
或与 §5.10 的供方分组同类问题。`ncf_to_market` 的最大偏差同样集中在银行
（601916 / 601997 / 601658 / 600919）。

### 判据说明：`rank/N` 型因子的「用户口径」怎么量化

官方值 = `rank/N`，**绝对水平不可复原**（名次≠比值），故改用**名次相对偏差**：
`|本地点位 − 官方名次| / N` 的中位数。实测 `earnings_cut_to_market` 0.92%、`ocf_to_market`
1.46%、`sales_to_market` 2.45% —— 与 Spearman 结论**可能不一致**（后者受尾部影响大）。
两套判据都记入 `value_dual_criterion.csv`，避免单一指标误导。

### 新增脚本与产出

| 文件 | 作用 |
|---|---|
| `scripts/qdata/repro_value_xs.py` | 8 条 Value 因子全市场复现（`--probe` 单日类型判定；落盘 `cache/value_local.pkl`） |
| `scripts/qdata/scan_value_variants.py` | 一次建面板、多口径对照（含单季/年报/TTM 全部变体） |
| `scripts/qdata/scan_value_sign.py` | 符号处理假设检验（绝对值 / 含存款同业等） |
| `scripts/qdata/diag_value_gap.py` | 官方名次 vs 本地点位的分段一致率与最大偏差股 |
| `scripts/qdata/value_dual_criterion.py` | 两套判据（Spearman + 名次相对偏差）并列输出 |
| `output/qdata_factor_repro/value_variant_scan.csv` | 全变体对照表 |
| `output/qdata_factor_repro/value_sign_scan.csv` | 符号假设检验表 |
| `output/qdata_factor_repro/value_dual_criterion.csv` | 两套判据总表 |

---

## 5.15 最后一轮：8 条「真有问题但还能查」因子的标定结果（2026-09-21）

判定口径按用户要求**不采用最严口径**：`rank/N` 型因子用「名次相对偏差中位 ≤1%」或
「横截面 Spearman ≥0.99」；**跨 8 个比对日**（4 个样本内 + 4 个样本外）取中位。

脚本：`scripts/qdata/scan_final8.py`（一次建面板、多日期、多候选口径）；
产物：`final8_scan.csv`（样本内）、`final8_scan_oos.csv`（**样本外**）。

| 因子 | 最优口径 | 样本内 sp | **样本外 sp** | 名次偏差 | 结论 |
|---|---|---|---|---|---|
| **`gpm_q`** | **累计(YTD)** `(revenue−oper_cost)/revenue` | **0.999980** | **0.999981**（min 0.999977）| **0.93%** | ✅ **通过** |
| `etp5` | `mean(净利润TTM,1260)/mean(mv,1260)` | 0.984926 | 0.984564 | 7.0~7.8% | ✗ 接近但未达 |
| `pegh5` | `−Close/(g5·EPS_TTM)`，g5 = EPS 年报 5 年复合 | 0.940875 | 0.936732 | 6.4% | ✗ |
| `ebitda_to_market` | `EBITDA_TTM/mv` | 0.910041 | 0.946389 | 3.1~4.2% | ✗ |
| `ocf_to_market` | `OCF_TTM/mv` | 0.862316 | 0.760865 | 1.5~2.4% | ✗（金融股错位）|
| `cash_profit_ratio` | `(OCF−净利润TTM)/净利润TTM` | 0.844062 | 0.759972 | 5.4~5.6% | ✗ |
| `np_ttm_qoq` | `净利润TTM/t-63−1` | 0.808770 | 0.774464 | 4.2~5.3% | ✗ |
| `ncf_to_market` | `(OCF+ICF+筹资净额)_TTM/mv` | 0.712845 | 0.534691 | 15.5~16.9% | ✗ |

### ✅ 唯一通过的一条：`gpm_q` —— q 口径是**累计（YTD）**，不是单季差分

| 分子口径 | 样本内 sp（4 日） | 样本外 sp（4 日） |
|---|---|---|
| **累计(YTD)** `revenue` / `oper_cost` | **0.999980** | **0.999981** |
| 单季（差分） | 0.9698 | — |
| TTM | 0.9699 | — |
| 累计但用 `total_revenue` | 0.9911 | — |

数值核对（600519.SH @20240812）：`rev_raw = 8.193e10`（2024H1 累计）、
`rev_q = 3.616e10`（单季差分）、`rev_ttm = 1.600e11` ⇒ 累计口径 GPM = 0.9176 与官方一致。

**`factor_desc` 原文「q 用累计单季」中的「累计单季」实为「年初至今累计」** ——
早期实现按「单季差分」处理，导致 0.977 的残差。

⚠️ **该修正只针对 `gpm_q`，不能改全局 `CFG["Q_MODE"]`** —— 其余 `_q` 因子
（`eps_q`/`roa_q`/`npm_q` 等）已用单季差分口径通过验证（`eps_q` 0.99999）。
已在 `repro_quality.py::build_inner` 就地注明。

### ✗ 其余 7 条的否证记录（本轮新增）

| 因子 | 试过但更差的口径 |
|---|---|
| `ebitda_to_market` | 年报 0.836、`EBIT+折旧摊销` 0.892、营业利润 0.690、`EBIT_TTM` 0.847 |
| `etp5` | 窗口 1203 日 0.982、756 日 0.909、5 期年报 0.645、`mean(mv)` 当分母 0.941 |
| `pegh5` | `g5` 用 EPS_TTM 0.470、`−1/x` 0.932、EPS 年报 0.725、窗口 1203/1250 更差 |
| `ocf_to_market` | 单季 0.521、年报 0.640、`OCF+ICF` 0.422、分子取绝对值 0.528（§5.14）|
| `ncf_to_market` | `OCF+ICF` 0.317、单季 0.225、仅筹资 0.142、绝对值 −0.032 |
| `cash_profit_ratio` | 归母分子 0.774、扣非分子 0.629、除以营业收入 0.185 |
| `np_ttm_qoq` | `prev_report` 0.066、`t-252` 0.246、单季环比 0.004、`t-63` 0.809（最优）|

**结论**：这 7 条的最高相关都稳定在样本外复现的同一水平（0.53~0.98），
**不是单日噪声，也不是分母穿越 0（`np_ttm_qoq` 并列仅 22 只）**。
性质属于「官方口径还有一层未标定」，与 §5.10 的供方分组/§5.6 的股票池同源。
**本轮到此归档，不再投入**（按用户要求「最后一轮」）。

### ✅ 顺带验证的结论（有价值的正面结果）

1. **`Rank` 并列口径在全库一致**：`method="max"` 已统一 4 处实现
   （`xs_ops.rank` / `repro_quality.xs_rank` / `repro_batch2` / `xs_compare.rank_of`）；
   算术证据见 §5.6。
2. **`t-252` 交易日口径对 `yoy_roa`/`yoy_roe` 是正确选择**（§5.7 复核，
   4 报告期偏移 / `f_ann_date` / 期初期末平均均更差）。
3. **`sales_to_market` 分母是总市值不是流通市值**、**分子是单季**（§5.14）。

---

## 6. 待办与归档（2026-09-21 刷新）

**当前总账（见 `SUMMARY.md` / `VERIFIED_FACTORS.md`）**：库内 **242 条 → 已判定 242**，
**未覆盖 0**。本轮最后一轮标定新增 `gpm_q` 通过（§5.15）。

| 口径 | 通过 | 未通过 |
|---|---|---|
| **严格**（EXACT+GOOD） | **180 / 242 = 74.4%** | 62 |
| **用户口径**（+APPROX，中位误差 ≤1% / 秩相关达标） | **203 / 242 = 83.9%** | **39** |

未通过 39 条按成因：比率分母穿越 0（18）、供方分组规则未披露（4，已证不可反推）、
官方股票池（5）、离散跳变（4）、算子统计量（5）、行业口径（6）、Value 口径未定（4）、
样本量不足（2，结论不可靠）、私有字段（2）、成因未定（2）。
**逐条清单见 `VERIFIED_FACTORS.md` §4。**

| 族 | 库内 | 已判定 | 通过率 | 状态 |
|---|---|---|---|---|
| **Liquidity** | 35 | 35 | **100%** | ✅ 完成（22 EXACT / 13 GOOD） |
| **Risk** | 25 | 25 | **100%** | ✅ 完成（14 EXACT / 11 GOOD） |
| **Momentum** | 20 | 20 | **100%** | ✅ 完成 |
| **Reversal** | 3 | 3 | **100%** | ✅ 完成 |
| **Size** | 3 | 3 | **100%** | ✅ 完成 |
| Value | 11 | 11 | 45% | 🟡 5 通过（`sales`/`earnings_cut`/`book_to_market`/`earnings_to_price`/`fcf`）；余 6 条见 §5.14/§5.15 |
| Quality | 59 | 59 | 61% | 🟡 15 条 FAIL（比率分母穿 0 / 厂商字段）+ 8 条 APPROX；`gpm_q` 本轮转 EXACT |
| Alpha101 | 71 | 70 | 70% | 🟡 14 FAIL（行业口径 7 / 股票池 4 / 离散跳变 3） |
| Growth | 15 | 15 | 27% | 🟡 4 条 FAIL + 7 条 APPROX（报告期口径 + 大并列块） |

| 遗留项 | 状态 |
|---|---|
| 8 个 `lake.financial_derivative.*` 直通因子 | ✅ 已实测：6 条逐位 EXACT，2 条 APPROX |
| Alpha101 官方"每日股票池" | 📦 已归档 —— 规则无法从公开字段推导（含 ST 204 只、含停牌 4 只、无干净上市日切分） |
| `IndNeutralize` 行业口径 | 📦 **已穷尽归档** —— 申万 L1/L2/L3 + Tushare 自有四种标准最佳仅 0.9255，且行业越细越差（7/7 成立） |
| 供方大并列块分组规则（`filter=True`） | 📦 **已证不可反推** —— 并列块的本地 yoy 分布与非并列组统计上无法区分（§5.10） |
| `sharpe_750d` / `adjusted_sharpe_750d`（maxerr） | 📦 归为 P 类（长窗口数据微差累积），中位误差 ≤4e−06，不建议继续投入 |
| 与聚宽体系交叉验证 | ✅ 公式级已完成（同名 7 个，`size` 符号相反、`roa_ttm` 多套横截面层，见 §3.3） |
| `factorlib/ops.py::rolling_beta` 缺陷 | ✅ 已修复并验证（见 §5.3） |

### 相关文件

见 `README.md`（体系入口，含完整分层结构与一键运行方式）。核心：

- `scripts/qdata/qdata_env.py` —— qdata 客户端（`factor_list` / `factor_value` / 限流 / 分页）
- `scripts/qdata/extract_formulas.py` / `audit_formulas.py` —— 公式抽取与静态审计
- `scripts/qdata/ts_env.py` / `ts_market.py` / `ts_fin.py` / `ts_index.py` —— 数据层
- `scripts/qdata/xs_ops.py` / `xs_compare.py` —— 横截面算子与专用判据
- `scripts/qdata/repro*.py` —— 各批次复现
- `scripts/qdata/run_all.py` / `run_factor_summary.py` —— 一键编排与汇总
- `scripts/jqdata/facsim/ops.py` / `compare.py` —— **复用**的算子与判定引擎

---

## 7. Alpha101 族专用口径（G8~G14，2026-09-17 实测标定）

> 完整证据链见 **`output/qdata_factor_repro/ALPHA101_NOTES.md`**。
> 实现：`ts_market.py`（全市场面板）/ `xs_ops.py`（算子）/ `alpha101_eval.py`（公式求值）
> / `repro_alpha101.py`（驱动）/ `validate_xs_rank.py`（阶段 A 验证）。

### G8 — ⚠ Alpha101 用**不复权价**（G1 只对显式写 `Close_hfq` 的因子成立）

| 探针 | 官方 | 不复权 | 后复权 |
|---|---|---|---|
| `alpha101_101` 000001.SZ | −0.3105590062 | **−0.310559006211**（5e−11） | −0.31249（8e−2） |
| `alpha101_41` 000001.SZ | 0.0183747059 | **0.0183747059042**（0） | 2.554（2.5） |
| `alpha101_12` 000001.SZ | −0.0300000000 | **−0.0300**（2e−13） | −4.170（3105） |
| `alpha101_42` | — | 误差 **8.9e−16** | 误差 792.6，Spearman 0.64 |

`VWAP = amount × 10 / vol`（Tushare：amount=千元、vol=手），同样不复权。

### G9 — 停牌日「走平」：`O = H = L = C = 前一交易日收盘`，`V`/`AMOUNT` 保持 NaN
证据：2026-08-11 官方 `alpha101_101` 5542 行 vs Tushare `daily` 5539 行；多出的 3 只
（`600984.SH`/`603221.SH`/…）当日无成交，官方值 = 0 ⟺ `O == C`，且其前一日 `O ≠ C`
⇒ 不是逐字段 ffill。`alpha101_12`（用 `Delta(Volume,1)`）只有 5539 行 ⇒ 成交量是 NaN。

### G10 — 横截面里必须剔除退市股（走平会无限前向填充）
实现：`ts_market.alive_mask`（按 `stock_basic.delist_date`）。

### G11 — `Rank(x) = count(x_i ≤ x) / N`（并列取**最大**名次）
= `pandas.rank(axis=1, method="max")/N`，取值 `(0,1]`。
证据：`alpha101_33` @20260811 有 180 只 `Open == Close`；`average` 名次 2196.5 ❌，
`max` 名次 2289 = 官方 ✅，5539 只的「官方名次−本地点名次」只取 **{0,3}**，零残差。

### G12 — `Ts_Rank(x,d) = count(x_i ≤ x_t)/d`（含并列）
`alpha101_43` 变体对照：`le` maxerr **1.1e−16** ｜ `lt` 0.43 ｜ `min` 0.32 ｜ `avg` 0.44。

### G13 — `Ts_ArgMax(x,d)` = **距最大值的天数**，并列取**最近**一次
`= (d−1) − argmax_0based`；与 `np.argmax` 位置口径**排序相反**。
`alpha101_1`：`pos` Spearman **−0.9385** → `since` +0.9385 → 再叠加 tie=last 后中位误差
0.4289 → **5.6e−17**。`alpha101_57` Spearman 0.8719 → **0.999999**。

### G14 — `StdDev` 用样本标准差 `ddof=1`（同 G5）
`alpha101_18`：ddof=1 → 5.0e−11 ✅ ｜ ddof=0 → 0.245 ❌。

### G15 — Alpha101 **没有** G2 尾部未沉淀问题
逐日 Spearman 均值：已沉淀区间 0.9684 vs 未沉淀日（2026-08-25）0.9688 ⇒ 无需 `--settle-days`。

### `factor_desc` 笔误（1 例已确认）
`alpha101_30` 文档丢了一个右括号：正确为 `(1 − Rank(S)) * Sum(V,5) / Sum(V,20)`。
文档版 Spearman 0.576，修正版 **1.000000**。修正表：`repro_alpha101.py::FORMULA_FIXES`。
