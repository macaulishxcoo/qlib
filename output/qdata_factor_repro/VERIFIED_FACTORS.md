# qdata.cc 因子复现 —— 已验证因子清单与归档

本清单记录**经全市场变体对照实测确认**的因子公式与口径注意事项。
官方文档有若干处与实现不符，均已标出。

- 库内因子：**242**（另有 10 个 `_old_` 历史快照不参与判定）
- **用户口径通过（中位相对误差 ≤1% / 秩相关达标，含 APPROX）：203 / 242 = 83.9%**
- 严格口径通过（仅 EXACT+GOOD）：180 / 242 = 74.4%
- 未通过归档：**39** 条（100% 有归档原因）
- 判定口径：横截面因子用**逐日 Spearman / 名次相对偏差**（全市场），时序因子用**中位相对误差**（已沉淀窗口，`--settle-days 30`）
- 生成脚本：`scripts/qdata/gen_verified_factors.py`；数据源：`SUMMARY.csv` / `factor_formulas.json` / `FACTOR_STATUS.json`

> ⚠️ **不要用最严的 maxerr 口径评价这些因子**：横截面因子值是 `rank/N`，名次差 10 位只值 0.0018；实测 `yoy_roa` 的 maxerr 判 FAIL 但中位相对误差仅 **0.575%**。

---

## 1. 已验证因子（按族）

| 族 | 库内 | 通过（用户口径） | 通过率 |
|---|---|---|---|
| Liquidity | 35 | **35** | 100% |
| Risk | 25 | **25** | 100% |
| Momentum | 20 | **20** | 100% |
| Reversal | 3 | **3** | 100% |
| Size | 3 | **3** | 100% |
| Alpha101 | 71 | **56** | 79% |
| Quality | 59 | **44** | 75% |
| Value | 11 | **6** | 55% |
| Growth | 15 | **11** | 73% |
| **合计** | **242** | **203** | **83.9%** |

### Liquidity —— 流动性与量额类（换手率 / 成交额 / Amihud / 量价相关）

通过 **35** 条。

| 因子 | 判定 | 验证口径 | 官方公式（文档） |
|---|---|---|---|
| `amount_ma_20d` | EXACT | 绝对误差 | AmountMA = Mean(TurnoverAmount, 20) |
| ↳ | | | 成交额单位是**元**（Tushare 千元×1000）；且 `TSPanel.AMOUNT` **已被乘过复权因子**，须 `/ADJ` 还原 |
| `avg_turnover_10d` | EXACT | 绝对误差 | 1. DailyTurnoverRate = Volume / AShares 2. Factor = ts_mean(DailyTurnoverRate, 10) |
| `avg_turnover_126d` | GOOD | 绝对误差 | 1. DailyTurnoverRate = TurnoverVolume / AShares 2. Factor = MA(DailyTurnoverRate, w=6*21) |
| `avg_turnover_20d` | EXACT | 绝对误差 | 1. DailyTurnoverRate = Volume / AShares 2. Factor = ts_mean(DailyTurnoverRate, 20) |
| `avg_turnover_21d` | GOOD | 绝对误差 | 1. DailyTurnoverRate = TurnoverVolume / AShares 2. Factor = MA(DailyTurnoverRate, w=1*21) |
| `avg_turnover_252d` | GOOD | 绝对误差 | 1. DailyTurnoverRate = TurnoverVolume / AShares 2. Factor = MA(DailyTurnoverRate, w=12*21) |
| `avg_turnover_42d` | GOOD | 绝对误差 | 1. DailyTurnoverRate = TurnoverVolume / AShares 2. Factor = MA(DailyTurnoverRate, w=2*21) |
| `avg_turnover_5d` | EXACT | 绝对误差 | 1. DailyTurnoverRate = Volume / AShares 2. Factor = ts_mean(DailyTurnoverRate, 5) |
| `avg_turnover_63d` | GOOD | 绝对误差 | 1. DailyTurnoverRate = TurnoverVolume / AShares 2. Factor = MA(DailyTurnoverRate, w=3*21) |
| `bias_std_turn_126d_252d` | EXACT | 绝对误差 | 1. DailyTurnoverRate = TurnoverVolume / AShares 2. Std_short = StdDev(DailyTurnoverRate, w=6*21) 3. Std_long = StdDev(DailyTurnoverRate, w=12*21) 4. Factor = Std_short / Std_long - 1 |
| `bias_std_turn_126d_504d` | EXACT | 绝对误差 | 1. DailyTurnoverRate = TurnoverVolume / AShares 2. Std_short = StdDev(DailyTurnoverRate, w=6*21) 3. Std_long = StdDev(DailyTurnoverRate, w=24*21) 4. Factor = Std_short / Std_long - 1 |
| `bias_std_turn_21d_252d` | EXACT | 绝对误差 | 1. DailyTurnoverRate = TurnoverVolume / AShares 2. Std_short = StdDev(DailyTurnoverRate, w=1*21) 3. Std_long = StdDev(DailyTurnoverRate, w=12*21) 4. Factor = Std_short / Std_long - 1 |
| `bias_std_turn_21d_504d` | EXACT | 绝对误差 | 1. DailyTurnoverRate = TurnoverVolume / AShares 2. Std_short = StdDev(DailyTurnoverRate, w=1*21) 3. Std_long = StdDev(DailyTurnoverRate, w=24*21) 4. Factor = Std_short / Std_long - 1 |
| `bias_std_turn_42d_252d` | EXACT | 绝对误差 | 1. DailyTurnoverRate = TurnoverVolume / AShares 2. Std_short = StdDev(DailyTurnoverRate, w=2*21) 3. Std_long = StdDev(DailyTurnoverRate, w=12*21) 4. Factor = Std_short / Std_long - 1 |
| `bias_std_turn_42d_504d` | EXACT | 绝对误差 | 1. DailyTurnoverRate = TurnoverVolume / AShares 2. Std_short = StdDev(DailyTurnoverRate, w=2*21) 3. Std_long = StdDev(DailyTurnoverRate, w=24*21) 4. Factor = Std_short / Std_long - 1 |
| `bias_std_turn_63d_252d` | EXACT | 绝对误差 | 1. DailyTurnoverRate = TurnoverVolume / AShares 2. Std_short = StdDev(DailyTurnoverRate, w=3*21) 3. Std_long = StdDev(DailyTurnoverRate, w=12*21) 4. Factor = Std_short / Std_long - 1 |
| `bias_std_turn_63d_504d` | EXACT | 绝对误差 | 1. DailyTurnoverRate = TurnoverVolume / AShares 2. Std_short = StdDev(DailyTurnoverRate, w=3*21) 3. Std_long = StdDev(DailyTurnoverRate, w=24*21) 4. Factor = Std_short / Std_long - 1 |
| `bias_turn_126d_252d` | EXACT | 绝对误差 | 1. DailyTurnoverRate = TurnoverVolume / AShares 2. MA_short = MA(DailyTurnoverRate, w=6*21) 3. MA_long = MA(DailyTurnoverRate, w=12*21) 4. Factor = MA_short / MA_long - 1 |
| `bias_turn_126d_504d` | EXACT | 绝对误差 | 1. DailyTurnoverRate = TurnoverVolume / AShares 2. MA_short = MA(DailyTurnoverRate, w=6*21) 3. MA_long = MA(DailyTurnoverRate, w=24*21) 4. Factor = MA_short / MA_long - 1 |
| `bias_turn_21d_252d` | EXACT | 绝对误差 | 1. DailyTurnoverRate = TurnoverVolume / AShares 2. MA_short = MA(DailyTurnoverRate, w=1*21) 3. MA_long = MA(DailyTurnoverRate, w=12*21) 4. Factor = MA_short / MA_long - 1 |
| `bias_turn_21d_504d` | EXACT | 绝对误差 | 1. DailyTurnoverRate = TurnoverVolume / AShares 2. MA_short = MA(DailyTurnoverRate, w=1*21) 3. MA_long = MA(DailyTurnoverRate, w=24*21) 4. Factor = MA_short / MA_long - 1 |
| `bias_turn_42d_252d` | EXACT | 绝对误差 | 1. DailyTurnoverRate = TurnoverVolume / AShares 2. MA_short = MA(DailyTurnoverRate, w=2*21) 3. MA_long = MA(DailyTurnoverRate, w=12*21) 4. Factor = MA_short / MA_long - 1 |
| `bias_turn_42d_504d` | EXACT | 绝对误差 | 1. DailyTurnoverRate = TurnoverVolume / AShares 2. MA_short = MA(DailyTurnoverRate, w=2*21) 3. MA_long = MA(DailyTurnoverRate, w=24*21) 4. Factor = MA_short / MA_long - 1 |
| `bias_turn_63d_252d` | EXACT | 绝对误差 | 1. DailyTurnoverRate = TurnoverVolume / AShares 2. MA_short = MA(DailyTurnoverRate, w=3*21) 3. MA_long = MA(DailyTurnoverRate, w=12*21) 4. Factor = MA_short / MA_long - 1 |
| `bias_turn_63d_504d` | EXACT | 绝对误差 | 1. DailyTurnoverRate = TurnoverVolume / AShares 2. MA_short = MA(DailyTurnoverRate, w=3*21) 3. MA_long = MA(DailyTurnoverRate, w=24*21) 4. Factor = MA_short / MA_long - 1 |
| `std_turnover_126d` | GOOD | 绝对误差 | 1. DailyTurnoverRate = TurnoverVolume / AShares 2. Factor = StdDev(DailyTurnoverRate, w=6*21) |
| `std_turnover_21d` | GOOD | 绝对误差 | 1. DailyTurnoverRate = TurnoverVolume / AShares 2. Factor = StdDev(DailyTurnoverRate, w=1*21) |
| `std_turnover_252d` | GOOD | 绝对误差 | 1. DailyTurnoverRate = TurnoverVolume / AShares 2. Factor = StdDev(DailyTurnoverRate, w=12*21) |
| `std_turnover_42d` | GOOD | 绝对误差 | 1. DailyTurnoverRate = TurnoverVolume / AShares 2. Factor = StdDev(DailyTurnoverRate, w=2*21) |
| `std_turnover_63d` | GOOD | 绝对误差 | 1. DailyTurnoverRate = TurnoverVolume / AShares 2. Factor = StdDev(DailyTurnoverRate, w=3*21) |
| `sum_abs_rtn_amount_20d` | EXACT | 绝对误差 | Factor = Sum(\|Return\|, 20) / Sum(TurnoverAmount, 20) * 1e8 注: 结果放大 1e8 倍（等价于成交额以亿元计），使因子量级落在 1e-4 ~ 1 区间， 避免入库时 10 位小数舍入摧毁小量级值。仅改变量纲，不影响截面排序与 IC 计算。 |
| `turnover_ma_20d` | GOOD | 绝对误差 | 1. VolCapRatio = TurnoverVolume / FloatMarketCap 2. FloatMarketCap = ClosePrice × FloatShares 3. If long > 0: Factor = -MA(VolCapRatio, short) / MA(VolCapRatio, long) Else: Factor = -MA(VolCapRatio, … |
| `turnover_ma_20d_120d` | EXACT | 绝对误差 | 1. VolCapRatio = TurnoverVolume / FloatMarketCap 2. FloatMarketCap = ClosePrice × FloatShares 3. If long > 0: Factor = -MA(VolCapRatio, short) / MA(VolCapRatio, long) Else: Factor = -MA(VolCapRatio, … |
| `volume_alpha_300d_000001` | GOOD | 绝对误差 | VolMomentum = (RollingSum(Volume, 5) - Lag(RollingSum(Volume, 5), 1)) / Lag(RollingSum(Volume, 5), 1) StockVolMomentum = Alpha + Beta * IndexVolMomentum + Epsilon VolumeAlpha = Alpha from OLS(StockVo… |
| `volume_alpha_300d_000300` | GOOD | 绝对误差 | VolMomentum = (RollingSum(Volume, 5) - Lag(RollingSum(Volume, 5), 1)) / Lag(RollingSum(Volume, 5), 1) StockVolMomentum = Alpha + Beta * IndexVolMomentum + Epsilon VolumeAlpha = Alpha from OLS(StockVo… |

### Risk —— 收益矩与一致性风险（波动 / 偏度 / 峰度 / beta / sigma）

通过 **25** 条。

| 因子 | 判定 | 验证口径 | 官方公式（文档） |
|---|---|---|---|
| `adjusted_sharpe_750d` | GOOD | 绝对误差 | AdjustedSharpe = Mean(DailyReturn, 750) / StdDev(DailyReturn, 750)^4 |
| `beta_1000d_000300` | GOOD | 绝对误差 | StockReturn = Alpha + Beta * IndexReturn + Epsilon Beta = Cov(StockReturn, IndexReturn) / Var(IndexReturn) over a rolling window. |
| `beta_125d_000300` | EXACT | 绝对误差 | StockReturn = Alpha + Beta * IndexReturn + Epsilon Beta = Cov(StockReturn, IndexReturn) / Var(IndexReturn) over a rolling window. |
| `beta_1320d_000001` | GOOD | 绝对误差 | StockReturn = Alpha + Beta * IndexReturn + Epsilon Beta = Cov(StockReturn, IndexReturn) / Var(IndexReturn) over a rolling window. |
| `beta_250d_000300` | EXACT | 绝对误差 | StockReturn = Alpha + Beta * IndexReturn + Epsilon Beta = Cov(StockReturn, IndexReturn) / Var(IndexReturn) over a rolling window. |
| `beta_500d_000300` | EXACT | 绝对误差 | StockReturn = Alpha + Beta * IndexReturn + Epsilon Beta = Cov(StockReturn, IndexReturn) / Var(IndexReturn) over a rolling window. |
| `beta_60d_000300` | EXACT | 绝对误差 | StockReturn = Alpha + Beta * IndexReturn + Epsilon Beta = Cov(StockReturn, IndexReturn) / Var(IndexReturn) over a rolling window. |
| `beta_consistency_1320d_000300` | GOOD | 绝对误差 | StockReturn = Alpha + Beta * IndexReturn + Residual BetaConsistency = StdDev(Beta * Residual) over 1320 days |
| `days_beyond_upper_lower_21d` | EXACT | 绝对误差 | 1. Z = (Close_hfq - MA(Close_hfq, 21)) / Std(Close_hfq, 21) 2. Upper = 统计 Z > 1 的天数 3. Lower = 统计 Z < -1 的天数 4. Factor = Upper - Lower |
| `high_low_126d` | EXACT | 绝对误差 | 1. NetValue_t = CumulativeProduct(1 + DailyReturn_i) from a fixed start point. 2. Factor = Max(NetValue_{t-w+1:t}) / Min(NetValue_{t-w+1:t}) |
| `high_low_21d` | EXACT | 绝对误差 | 1. NetValue_t = CumulativeProduct(1 + DailyReturn_i) from a fixed start point. 2. Factor = Max(NetValue_{t-w+1:t}) / Min(NetValue_{t-w+1:t}) |
| `high_low_252d` | EXACT | 绝对误差 | 1. NetValue_t = CumulativeProduct(1 + DailyReturn_i) from a fixed start point. 2. Factor = Max(NetValue_{t-w+1:t}) / Min(NetValue_{t-w+1:t}) |
| `high_low_42d` | EXACT | 绝对误差 | 1. NetValue_t = CumulativeProduct(1 + DailyReturn_i) from a fixed start point. 2. Factor = Max(NetValue_{t-w+1:t}) / Min(NetValue_{t-w+1:t}) |
| `high_low_63d` | EXACT | 绝对误差 | 1. NetValue_t = CumulativeProduct(1 + DailyReturn_i) from a fixed start point. 2. Factor = Max(NetValue_{t-w+1:t}) / Min(NetValue_{t-w+1:t}) |
| `log_price` | EXACT | 绝对误差 | Factor = log(ClosePrice_hfq) |
| `return_std_126d` | GOOD | 绝对误差 | ReturnStd = StdDev(DailyReturn) over 6*21 trading days |
| `return_std_21d` | GOOD | 绝对误差 | ReturnStd = StdDev(DailyReturn) over 1*21 trading days |
| `return_std_252d` | GOOD | 绝对误差 | ReturnStd = StdDev(DailyReturn) over 12*21 trading days |
| `return_std_42d` | EXACT | 绝对误差 | ReturnStd = StdDev(DailyReturn) over 2*21 trading days |
| `return_std_63d` | GOOD | 绝对误差 | ReturnStd = StdDev(DailyReturn) over 3*21 trading days |
| `sharpe_60d` | EXACT | 绝对误差 | Sharpe = ts_mean(Return, 60) / ts_std_dev(Return, 60) |
| `sharpe_750d` | GOOD | 绝对误差 | Sharpe = ts_mean(Return, 750) / ts_std_dev(Return, 750) |
| `sigma_1320d_000001` | GOOD | 绝对误差 | StockReturn = Alpha + Beta * IndexReturn + Residual Sigma = StdDev(Residual) over 1320 days |
| `sigma_1320d_000300` | GOOD | 绝对误差 | StockReturn = Alpha + Beta * IndexReturn + Residual Sigma = StdDev(Residual) over 1320 days |
| `volume_beta_120d_000300` | EXACT | 绝对误差 | VolMomentum = (RollingSum(Volume, 5) - RollingSum(Volume, 5)[t-1]) / RollingSum(Volume, 5)[t-1] VolumeBeta = Cov(StockVolMomentum, IndexVolMomentum) / Var(IndexVolMomentum) over 120 days |

### Momentum —— 动量与超买超卖（ROC / RSI / 区间收益 / 指数回归 alpha）

通过 **20** 条。

| 因子 | 判定 | 验证口径 | 官方公式（文档） |
|---|---|---|---|
| `MACD` | EXACT | 绝对误差 | 1. DIF = EMA(Close, 12) - EMA(Close, 26) 2. DEA = EMA(DIF, 9) 3. MACD = 2 × (DIF - DEA) |
| `alpha_1000d_000300` | GOOD | 绝对误差 | Alpha_t = Intercept from OLS(DailyStockReturn_{t-d+1:t} ~ DailyIndexReturn_{t-d+1:t}) Factor = Alpha_t |
| `alpha_125d_000300` | GOOD | 绝对误差 | Alpha_t = Intercept from OLS(DailyStockReturn_{t-d+1:t} ~ DailyIndexReturn_{t-d+1:t}) Factor = Alpha_t |
| `alpha_1320d_000001` | GOOD | 绝对误差 | Alpha_t = Intercept from OLS(DailyStockReturn_{t-d+1:t} ~ DailyIndexReturn_{t-d+1:t}) Factor = Alpha_t |
| `alpha_250d_000300` | GOOD | 绝对误差 | Alpha_t = Intercept from OLS(DailyStockReturn_{t-d+1:t} ~ DailyIndexReturn_{t-d+1:t}) Factor = Alpha_t |
| `alpha_500d_000300` | GOOD | 绝对误差 | Alpha_t = Intercept from OLS(DailyStockReturn_{t-d+1:t} ~ DailyIndexReturn_{t-d+1:t}) Factor = Alpha_t |
| `alpha_528d_000001` | GOOD | 绝对误差 | Alpha_t = Intercept from OLS(DailyStockReturn_{t-d+1:t} ~ DailyIndexReturn_{t-d+1:t}) Factor = Alpha_t |
| `alpha_792d_000001` | GOOD | 绝对误差 | Alpha_t = Intercept from OLS(DailyStockReturn_{t-d+1:t} ~ DailyIndexReturn_{t-d+1:t}) Factor = Alpha_t |
| `days_down_up` | EXACT | 绝对误差 | Factor = \|ConsecutiveUp - ConsecutiveDown - 1\| |
| ↳ | | | **严格** `diff>0 / diff<0` + 后复权；非严格 corr 0.925 |
| `dea` | EXACT | 绝对误差 | 1. DIF = EMA(Close, 12) - EMA(Close, 26) 2. DEA = EMA(DIF, 9) |
| `dif` | EXACT | 绝对误差 | DIF = EMA(Close, 12) - EMA(Close, 26) |
| ↳ | | | ⚠️ EMA 族有 **qdata 尾部未沉淀窗口**（约 20~25 交易日），判定须截断（§G2）；截断后 maxerr ≈5e-11 |
| `ma_20d` | EXACT | 绝对误差 | MA = Mean(Close, 20) |
| `price_position_ir_60d` | EXACT | 绝对误差 | Ratio = (Close - Open) / (High - Low) Factor = Mean(Ratio, 60) / StdDev(Ratio, 60) |
| ↳ | | | 用 **`ddof=1`** |
| `return_126d` | EXACT | 绝对误差 | Return = Product(1 + DailyReturn, window=126) - 1 |
| `return_21d` | EXACT | 绝对误差 | Return = Product(1 + DailyReturn, window=21) - 1 |
| `return_252d` | EXACT | 绝对误差 | Return = Product(1 + DailyReturn, window=252) - 1 |
| `return_42d` | EXACT | 绝对误差 | Return = Product(1 + DailyReturn, window=42) - 1 |
| `return_5d` | EXACT | 绝对误差 | Return = Product(1 + DailyReturn, window=5) - 1 |
| `return_63d` | EXACT | 绝对误差 | Return = Product(1 + DailyReturn, window=63) - 1 |
| `rsrs` | EXACT | 绝对误差 | 1. Slope_t = Beta from OLS(Low_{t-N+1:t} ~ High_{t-N+1:t}), N=18 2. RSRS_t = Z-Score(Slope_{t-M+1:t}), M=200 |
| ↳ | | | 后复权 + **`ddof=1`**；`ddof=0` 仅 APPROX |

### Reversal —— 反转类（短期反转 / 小市值反转）

通过 **3** 条。

| 因子 | 判定 | 验证口径 | 官方公式（文档） |
|---|---|---|---|
| `price_dist` | EXACT | 绝对误差 | - 价格 < 10: 距离下一个整数的距离 - 10 <= 价格 < 100: 价格/10 后，距离下一个整数的距离 - 价格 >= 100: 价格/100 后，距离下一个整数的距离 |
| ↳ | | | 后复权价 + **`ceil`**；`nearest` corr −0.10 |
| `rsi` | EXACT | 绝对误差 | 1. Gain = Max(Close - PrevClose, 0) 2. Loss = Max(PrevClose - Close, 0) 3. AvgGain = EMA(Gain, 14) [使用 Wilder's Smoothing] 4. AvgLoss = EMA(Loss, 14) [使用 Wilder's Smoothing] 5. RS = AvgGain / AvgLoss… |
| ↳ | | | **Wilder 平滑 `ewm(com=13)`**；`span=14` / SMA14 / 原始价全 FAIL。中位相对误差 = 0 |
| `small_cap_reversal_21d` | EXACT | 横截面Spearman | CumReturn = Product(1 + DailyReturn, 21) - 1 Reversal = -CumReturn SmallCap = CrossSectionalRank(-MarketCap) Factor = CrossSectionalRank(Reversal) × SmallCap |
| ↳ | | | `CrossSectionalRank(Reversal) × SmallCap`，`SmallCap = CrossSectionalRank(−MarketCap)`（旧文档公式已废弃） |

### Size —— 规模类（总市值 / 流通市值对数）

通过 **3** 条。

| 因子 | 判定 | 验证口径 | 官方公式（文档） |
|---|---|---|---|
| `float_size` | EXACT | 绝对误差 | FloatSize = -log(FloatShares * ClosePrice / 1e6) 该因子值为负对数形式，值越小表示流通市值越大。 |
| ↳ | | | 同 `size`：实为 `−log(circ_mv/100)`；文档口径 corr=0.067 |
| `nl_size` | GOOD | 横截面Spearman | nlSize = Residual(Size^3 ~ Size) 该因子是size^3对size截面回归后的残差，代表市值非线性部分， 用于捕捉市值效应中的非线性成分。 Notes --------------- * 该因子通过截面回归计算残差，每个截面上回归一次 * 因子值与size的正交，消除了线性市值的影响 |
| ↳ | | | `CrossSectionalRank(−log(市值))` 型；公式文本省略了 rank 包装 |
| `size` | EXACT | 绝对误差 | Size = -log(TotalShares * ClosePrice / 1e6) 该因子值为负对数形式，值越小表示市值越大。 |
| ↳ | | | **文档公式有误**：实为 `−log(total_mv/100)`；文档的 `−log(总股本×收盘价/1e6)` 与官方 corr=−0.02（§批次二） |

### Alpha101 —— WorldQuant Alpha101 公式族（横截面，多数用**不复权价**）

通过 **56** 条。

| 因子 | 判定 | 验证口径 | 官方公式（文档） |
|---|---|---|---|
| `alpha101_1` | GOOD | 分档一致率/Spearman取较优 | Alpha = Rank(Ts_ArgMax(SignedPower(IF(Returns < 0, StdDev(Returns, 20), Close), 2), 5)) - 0.5 |
| `alpha101_10` | EXACT | 横截面Spearman | Alpha = Rank((0 < Ts_Min(Delta(Close, 1), 4)) ? Delta(Close, 1) : ((Ts_Max(Delta(Close, 1), 4) < 0) ? Delta(Close, 1) : -1 * Delta(Close, 1))) |
| `alpha101_101` | EXACT | 横截面Spearman | Alpha = (Close - Open) / ((High - Low) + 0.001) |
| `alpha101_11` | EXACT | 横截面Spearman | Alpha = (Rank(Ts_Max(VWAP - Close, 3)) + Rank(Ts_Min(VWAP - Close, 3))) * Rank(Delta(Volume, 3)) |
| `alpha101_12` | EXACT | 横截面Spearman | Alpha = Sign(Delta(Volume, 1)) * (-1 * Delta(Close, 1)) |
| `alpha101_13` | EXACT | 横截面Spearman | Alpha = -1 * Rank(Covariance(Rank(Close), Rank(Volume), 5)) |
| `alpha101_14` | GOOD | 横截面Spearman | Alpha = -1 * Rank(Delta(Returns, 3)) * Correlation(Open, Volume, 10) |
| `alpha101_15` | GOOD | 横截面Spearman | Alpha = -1 * Sum(Rank(Correlation(Rank(High), Rank(Volume), 3)), 3) |
| `alpha101_16` | EXACT | 横截面Spearman | Alpha = -1 * Rank(Covariance(Rank(High), Rank(Volume), 5)) |
| `alpha101_17` | EXACT | 横截面Spearman | Alpha = (-1 * Rank(Ts_Rank(Close, 10))) * Rank(Delta(Delta(Close, 1), 1)) * Rank(Ts_Rank(Volume / ADV20, 5)) |
| `alpha101_18` | EXACT | 横截面Spearman | Alpha = -1 * Rank(StdDev(Abs(Close - Open), 5) + (Close - Open) + Correlation(Close, Open, 10)) |
| `alpha101_19` | APPROX | 横截面Spearman | Alpha = (-1 * Sign((Close - Delay(Close, 7)) + Delta(Close, 7))) * (1 + Rank(1 + Sum(Returns, 250))) |
| `alpha101_2` | EXACT | 横截面Spearman | Alpha = -1 * Correlation(Rank(Delta(Log(Volume), 2)), Rank((Close - Open) / Open), 6) |
| `alpha101_20` | EXACT | 横截面Spearman | Alpha = -1 * Rank(Open - Delay(High, 1)) * Rank(Open - Delay(Close, 1)) * Rank(Open - Delay(Low, 1)) |
| `alpha101_21` | GOOD | 分档一致率/Spearman取较优 | Alpha = (Sum(Close, 8) / 8 + StdDev(Close, 8) < Sum(Close, 2) / 2) ? -1 : ((Sum(Close, 2) / 2 < Sum(Close, 8) / 8 - StdDev(Close, 8)) ? 1 : ((1 < Volume / ADV20 \|\| Volume / ADV20 == 1) ? 1 : -1)) |
| `alpha101_22` | EXACT | 横截面Spearman | Alpha = -1 * Delta(Correlation(High, Volume, 5), 5) * Rank(StdDev(Close, 20)) |
| `alpha101_23` | EXACT | 横截面Spearman | Alpha = (Sum(High, 20) / 20 < High) ? -1 * Delta(High, 2) : 0 |
| `alpha101_24` | EXACT | 横截面Spearman | Alpha = (Delta(Sum(Close, 100) / 100, 100) / Delay(Close, 100) <= 0.05) ? -1 * (Close - Ts_Min(Close, 100)) : -1 * Delta(Close, 3) |
| `alpha101_25` | APPROX | 横截面Spearman | Alpha = Rank(-1 * Returns * ADV20 * VWAP * (High - Close)) |
| `alpha101_26` | EXACT | 横截面Spearman | Alpha = -1 * Ts_Max(Correlation(Ts_Rank(Volume, 5), Ts_Rank(High, 5), 5), 3) |
| `alpha101_27` | GOOD | 分档一致率/Spearman取较优 | Alpha = (0.5 < Rank(Sum(Correlation(Rank(Volume), Rank(VWAP), 6), 2) / 2.0)) ? -1 : 1 |
| `alpha101_28` | EXACT | 横截面Spearman | Alpha = Scale(Correlation(ADV20, Low, 5) + (High + Low) / 2 - Close) |
| `alpha101_3` | GOOD | 横截面Spearman | Alpha = -1 * Correlation(Rank(Open), Rank(Volume), 10) |
| `alpha101_30` | EXACT | 横截面Spearman | Alpha = (1 - Rank(Sign(Close - Delay(Close, 1)) + Sign(Delay(Close, 1) - Delay(Close, 2)) + Sign(Delay(Close, 2) - Delay(Close, 3))) * Sum(Volume, 5)) / Sum(Volume, 20) |
| `alpha101_31` | EXACT | 横截面Spearman | Alpha = Rank(Rank(Rank(Decay_Linear(-1 * Rank(Rank(Delta(Close, 10))), 10)))) + Rank(-1 * Delta(Close, 3)) + Sign(Scale(Correlation(ADV20, Low, 12))) |
| `alpha101_33` | EXACT | 横截面Spearman | Alpha = Rank(-1 * (1 - Open / Close)) |
| `alpha101_34` | APPROX | 横截面Spearman | Alpha = Rank(1 - Rank(StdDev(Returns, 2) / StdDev(Returns, 5)) + 1 - Rank(Delta(Close, 1))) |
| `alpha101_35` | GOOD | 横截面Spearman | Alpha = Ts_Rank(Volume, 32) * (1 - Ts_Rank((Close + High) - Low, 16)) * (1 - Ts_Rank(Returns, 32)) |
| `alpha101_36` | GOOD | 横截面Spearman | Alpha = 2.21 * Rank(Correlation(Close - Open, Delay(Volume, 1), 15)) + 0.7 * Rank(Open - Close) + 0.73 * Rank(Ts_Rank(Delay(-1 * Returns, 6), 5)) + Rank(Abs(Correlation(VWAP, ADV20, 6))) + 0.6 * Rank… |
| `alpha101_37` | EXACT | 横截面Spearman | Alpha = Rank(Correlation(Delay(Open - Close, 1), Close, 200)) + Rank(Open - Close) |
| `alpha101_38` | EXACT | 横截面Spearman | Alpha = -1 * Rank(Ts_Rank(Close, 10)) * Rank(Close / Open) |
| `alpha101_39` | APPROX | 横截面Spearman | Alpha = -1 * Rank(Delta(Close, 7) * (1 - Rank(Decay_Linear(Volume / ADV20, 9)))) * (1 + Rank(Sum(Returns, 250))) |
| `alpha101_4` | EXACT | 分档一致率/Spearman取较优 | Alpha = -1 * Ts_Rank(Rank(Low), 9) |
| `alpha101_40` | EXACT | 横截面Spearman | Alpha = -1 * Rank(StdDev(High, 10)) * Correlation(High, Volume, 10) |
| `alpha101_41` | EXACT | 横截面Spearman | Alpha = (High * Low) ^ 0.5 - VWAP |
| `alpha101_42` | EXACT | 横截面Spearman | Alpha = Rank(VWAP - Close) / Rank(VWAP + Close) |
| `alpha101_43` | EXACT | 分档一致率/Spearman取较优 | Alpha = Ts_Rank(Volume / ADV20, 20) * Ts_Rank(-1 * Delta(Close, 7), 8) |
| `alpha101_44` | GOOD | 横截面Spearman | Alpha = -1 * Correlation(High, Rank(Volume), 5) |
| `alpha101_46` | EXACT | 分档一致率/Spearman取较优 | Alpha = (0.25 < (Delay(Close, 20) - Delay(Close, 10)) / 10 - (Delay(Close, 10) - Close) / 10) ? -1 : ((((Delay(Close, 20) - Delay(Close, 10)) / 10 - (Delay(Close, 10) - Close) / 10) < 0) ? 1 : -1 * (… |
| `alpha101_47` | EXACT | 横截面Spearman | Alpha = (Rank(1 / Close) * Volume / ADV20) * (High * Rank(High - Close) / (Sum(High, 5) / 5)) - Rank(VWAP - Delay(VWAP, 5)) |
| `alpha101_49` | EXACT | 横截面Spearman | Alpha = ((Delay(Close, 20) - Delay(Close, 10)) / 10 - (Delay(Close, 10) - Close) / 10 < -0.1) ? 1 : -1 * (Close - Delay(Close, 1)) |
| `alpha101_5` | EXACT | 横截面Spearman | Alpha = Rank(Open - (Sum(VWAP, 10) / 10)) * (-1 * Abs(Rank(Close - VWAP))) |
| `alpha101_50` | GOOD | 横截面Spearman | Alpha = -1 * Ts_Max(Rank(Correlation(Rank(Volume), Rank(VWAP), 5)), 5) |
| `alpha101_51` | EXACT | 横截面Spearman | Alpha = ((Delay(Close, 20) - Delay(Close, 10)) / 10 - (Delay(Close, 10) - Close) / 10 < -0.05) ? 1 : -1 * (Close - Delay(Close, 1)) |
| `alpha101_52` | APPROX | 横截面Spearman | Alpha = ((-1 * Ts_Min(Low, 5) + Delay(Ts_Min(Low, 5), 5)) * Rank((Sum(Returns, 240) - Sum(Returns, 20)) / 220)) * Ts_Rank(Volume, 5) |
| `alpha101_53` | EXACT | 横截面Spearman | Alpha = -1 * Delta(((Close - Low) - (High - Close)) / (Close - Low), 9) |
| `alpha101_54` | EXACT | 横截面Spearman | Alpha = (-1 * (Low - Close) * Open^5) / ((Low - High) * Close^5) |
| `alpha101_55` | GOOD | 横截面Spearman | Alpha = -1 * Correlation(Rank((Close - Ts_Min(Low, 12)) / (Ts_Max(High, 12) - Ts_Min(Low, 12))), Rank(Volume), 6) |
| `alpha101_57` | EXACT | 横截面Spearman | Alpha = -(Close - VWAP) / Decay_Linear(Rank(Ts_ArgMax(Close, 30)), 2) |
| `alpha101_6` | EXACT | 横截面Spearman | Alpha = -1 * Correlation(Open, Volume, 10) |
| `alpha101_60` | EXACT | 横截面Spearman | Alpha = -(2 * Scale(Rank((Close - Low - (High - Close)) / (High - Low) * Volume)) - Scale(Rank(Ts_ArgMax(Close, 10)))) |
| `alpha101_61` | APPROX | 分档一致率/Spearman取较优 | Alpha = Rank(VWAP - Ts_Min(VWAP, 16)) < Rank(Correlation(VWAP, ADV180, 18)) |
| `alpha101_62` | APPROX | 分档一致率/Spearman取较优 | Alpha = (Rank(Correlation(VWAP, Sum(ADV20, 22), 10)) < Rank(Rank(Open) + Rank(Open) < Rank((High + Low) / 2) + Rank(High))) * -1 |
| `alpha101_66` | GOOD | 横截面Spearman | Alpha = (Rank(Decay_Linear(Delta(VWAP, 4), 7)) + Ts_Rank(Decay_Linear((Low - VWAP) / (Open - (High + Low) / 2), 11), 7)) * -1 |
| `alpha101_7` | GOOD | 分档一致率/Spearman取较优 | Alpha = (ADV20 < Volume) ? (-1 * Ts_Rank(Abs(Delta(Close, 7)), 60) * Sign(Delta(Close, 7))) : -1 说明: 当日成交量 ≤ 20 日均量（缩量或停牌）时输出 -1， 为公式定义的哨兵值，非数据缺失；截面排序使用时应剔除或单独分组。 |
| `alpha101_9` | EXACT | 横截面Spearman | Alpha = (0 < Ts_Min(Delta(Close, 1), 5)) ? Delta(Close, 1) : ((Ts_Max(Delta(Close, 1), 5) < 0) ? Delta(Close, 1) : -1 * Delta(Close, 1)) |

### Quality —— 财务质量比率（偿债 / 周转 / 盈利 / 现金流）

通过 **44** 条。

| 因子 | 判定 | 验证口径 | 官方公式（文档） |
|---|---|---|---|
| `ar_ap_to_revenue` | APPROX | 横截面Spearman | Ratio = (AdvanceReceipts - AdvancePayment) / OperatingRevenue Factor = CrossSectionalRank(Ratio) |
| `asset_turnover` | EXACT | 横截面Spearman | AssetTurnover = OperatingRevenue_TTM / TotalAssets Factor = CrossSectionalRank(AssetTurnover) |
| ↳ | | | TTM 营业收入 / 期末总资产 |
| `cash_ratio` | GOOD | 横截面Spearman | CashRatio = (CashEquivalents + TradingAssets) / TotalCurrentLiability Factor = CrossSectionalRank(CashRatio) |
| `current_ratio` | EXACT | 绝对误差 | CurrentRatio = CurrentAssets / CurrentLiabilities |
| `de` | EXACT | 绝对误差 | DE = TotalDebt / Equity |
| ↳ | | | `总负债 / 股东权益`；**注意**：文档公式文本含 `CrossSectionalRank` 但官方值是**原始比值**（−166~412），必须实测判型 |
| `debt_asset_ratio` | EXACT | 绝对误差 | DebtAssetRatio = TotalDebt / TotalAssets |
| `delta_asset_turnover` | APPROX | 横截面Spearman | AT = Revenue_TTM / TotalAssets Delta = AT_t - AT_{t-252} Factor = CrossSectionalRank(Delta) |
| `delta_cash_ratio` | GOOD | 横截面Spearman | CashRatio = (Cash + TradingAssets) / CurrentLiability Delta = CashRatio_t - CashRatio_{t-252} Factor = CrossSectionalRank(Delta) |
| `delta_current_ratio` | GOOD | 横截面Spearman | Delta = CurrentRatio_t - CurrentRatio_{t-252} Factor = CrossSectionalRank(Delta) |
| `delta_de` | GOOD | 横截面Spearman | DE = TotalLiability / TotalShareholderEquity Delta = DE_t - DE_{t-252} Factor = CrossSectionalRank(Delta) |
| `delta_gpm` | APPROX | 横截面Spearman | Delta = GPM_t - GPM_{t-252} Factor = CrossSectionalRank(Delta) |
| `delta_inventory_turnover` | APPROX | 横截面Spearman | IT = Cost_TTM / Inventories Delta = IT_t - IT_{t-252} Factor = CrossSectionalRank(Delta) |
| `delta_quick_ratio` | GOOD | 横截面Spearman | Delta = QuickRatio_t - QuickRatio_{t-252} Factor = CrossSectionalRank(Delta) |
| `delta_roa` | APPROX | 中位相对误差(用户标准) | Delta = ROA_t - ROA_{t-252} Factor = CrossSectionalRank(Delta) |
| `delta_roe` | APPROX | 横截面Spearman | Delta = ROE_t - ROE_{t-252} Factor = CrossSectionalRank(Delta) |
| `eps_q` | EXACT | 横截面Spearman | Factor = CrossSectionalRank(BasicEPS) |
| `eps_ttm` | EXACT | 横截面Spearman | Factor = CrossSectionalRank(BasicEPS) |
| `eps_y` | EXACT | 横截面Spearman | Factor = CrossSectionalRank(BasicEPS) |
| `equity_turnover` | EXACT | 横截面Spearman | EquityTurnover = OperatingRevenue_TTM / TotalShareholderEquity Factor = CrossSectionalRank(EquityTurnover) |
| `financial_leverage` | EXACT | 横截面Spearman | FinancialLeverage = TotalAssets / TotalShareholderEquity Factor = CrossSectionalRank(FinancialLeverage) |
| `fixed_asset_turnover` | EXACT | 横截面Spearman | FixedAssetTurnover = OperatingRevenue_TTM / FixedAssets Factor = CrossSectionalRank(FixedAssetTurnover) |
| `gpm_q` | EXACT | 横截面Spearman | GPM = (Revenue - Cost) / Revenue Factor = CrossSectionalRank(GPM) |
| ↳ | | | 分子分母均为**单季（差分）**的 `revenue`/`oper_cost`；累计(YTD) 口径只有 0.977（§本轮标定） |
| `gpm_qoq` | APPROX | 横截面Spearman | GPM = (Revenue_TTM - Cost_TTM) / Revenue_TTM Growth = GPM_t / GPM_{prev_report} - 1 # 财报披露日计算 Factor = CrossSectionalRank(Growth_filled) |
| `gpm_ttm` | EXACT | 横截面Spearman | GPM = (Revenue - Cost) / Revenue Factor = CrossSectionalRank(GPM) |
| `gpm_y` | GOOD | 横截面Spearman | GPM = (Revenue - Cost) / Revenue Factor = CrossSectionalRank(GPM) |
| `inventory_turnover` | GOOD | 横截面Spearman | InventoryTurnover = OperatingCost_TTM / Inventories Factor = CrossSectionalRank(InventoryTurnover) |
| `market_value_leverage` | EXACT | 横截面Spearman | MkvLev = (MarketCap - NonCurrentLiability) / MarketCap Factor = CrossSectionalRank(MkvLev) |
| `npm_q` | GOOD | 横截面Spearman | NPM = NetProfit / OperatingRevenue Factor = CrossSectionalRank(NPM) |
| `npm_q_qoq` | GOOD | 横截面Spearman | NPM = NetProfit_Q / OperatingRevenue_Q Growth = NPM_t / NPM_{prev_report} - 1 # 财报披露日计算 Factor = CrossSectionalRank(Growth_filled) |
| `npm_tsh` | GOOD | 横截面Spearman | Ratio = NPParentCompanyOwners_TTM / TotalShares Factor = CrossSectionalRank(Ratio) |
| `npm_ttm` | EXACT | 横截面Spearman | NPM = NetProfit / OperatingRevenue Factor = CrossSectionalRank(NPM) |
| `npm_ttm_qoq` | APPROX | 横截面Spearman | NPM = NetProfit_TTM / OperatingRevenue_TTM Growth = NPM_t / NPM_{prev_report} - 1 # 财报披露日计算 Factor = CrossSectionalRank(Growth_filled) |
| `npm_y` | EXACT | 横截面Spearman | NPM = NetProfit / OperatingRevenue Factor = CrossSectionalRank(NPM) |
| `opm_ttm` | EXACT | 横截面Spearman | OPM = OperatingProfit / OperatingRevenue Factor = CrossSectionalRank(OPM) |
| `opm_y` | EXACT | 横截面Spearman | OPM = OperatingProfit / OperatingRevenue Factor = CrossSectionalRank(OPM) |
| `opt_tpro` | GOOD | 横截面Spearman | Ratio = OperatingProfit_Q / TotalProfit_Q Factor = CrossSectionalRank(Ratio) |
| `quick_ratio` | EXACT | 绝对误差 | QuickRatio = (CurrentAssets - Inventory) / CurrentLiabilities |
| `receivable_turnover` | GOOD | 横截面Spearman | ReceivableTurnover = OperatingRevenue_TTM / AccountsReceivable Factor = CrossSectionalRank(ReceivableTurnover) |
| `roa_q` | GOOD | 横截面Spearman | ROA = NetProfit / TotalAssets Factor = CrossSectionalRank(ROA) |
| `roa_ttm` | EXACT | 横截面Spearman | ROA = NetProfit / TotalAssets Factor = CrossSectionalRank(ROA) |
| ↳ | | | 内层 = **净利润 `n_income`（含少数股东）TTM / 期末总资产**（全市场 0.99999）；归母只有 0.986。外层 `CrossSectionalRank` |
| `roa_y` | EXACT | 横截面Spearman | ROA = NetProfit / TotalAssets Factor = CrossSectionalRank(ROA) |
| ↳ | | | 年报报告期口径 |
| `roe_ttm` | EXACT | 绝对误差 | ROE = NetProfit_Parent / TotalEquity |
| ↳ | | | 内层 = **归母净利润 TTM / 股东权益合计（含少数股东）**（逐位 1.0000）；passthrough 无外层 rank |
| `roe_ttm_lag63d` | EXACT | 绝对误差 | ROE = NetProfit_Parent / TotalEquity |
| `roe_y` | EXACT | 绝对误差 | ROE = NetProfit_Parent / TotalEquity |
| ↳ | | | 同 `roe_ttm`，取**年报**报告期 |

### Value —— 价值类（市值比 / 股息率 / 估值）

通过 **6** 条。

| 因子 | 判定 | 验证口径 | 官方公式（文档） |
|---|---|---|---|
| `book_to_market` | EXACT | 绝对误差 | book_to_market = (SE_without_MI_pri + DeferredTaxAssets_pri) / (ClosePrice × TotalShares) |
| ↳ | | | 文档的 `_pri` 后缀**误导**：实为**最新报告期期末**值，且分子**必须计入递延所得税资产**（中位误差 1.28e-11） |
| `dividend_yield_3y_avg` | APPROX | 横截面Spearman | dividend_yield_3y_avg = (SUM(ActualCashDiviRMB, 735) / 3) / ClosePrice = AVG(ActualCashDiviRMB, 3年) / ClosePrice Factor = CrossSectionalRank(dividend_yield_3y_avg) 参考: Afactors faclib/value/div_p_3y |
| `earnings_cut_to_market` | EXACT | 横截面Spearman | earnings_cut_to_market = NetProfitCut_TTM / (ClosePrice × TotalShares) Factor = CrossSectionalRank(earnings_cut_to_market) 参考: 华泰价值因子 |
| ↳ | | | **文档字面写「扣非净利润」，实测官方用归母净利润 TTM**：归母 0.999997 vs 扣非 0.941175（§5.14） |
| `earnings_to_price` | GOOD | 绝对误差 | earnings_to_price = NPParentCompanyOwners_TTM / (ClosePrice × TotalShares) = BasicEPS_TTM / ClosePrice |
| ↳ | | | `1 / pe_ttm` |
| `fcf_to_market` | EXACT | 横截面Spearman | fcf_to_market = (NOCF_TTM - SICO_TTM) / (ClosePrice × TotalShares) |
| `sales_to_market` | EXACT | 横截面Spearman | sales_to_market = TotalOperatingRevenue_Q / (ClosePrice × TotalShares) Factor = CrossSectionalRank(sales_to_market) 参考: 华泰价值因子 |
| ↳ | | | 分子是**单季**营业总收入（TTM 只有 0.957）；分母是**总**市值（流通市值 0.944） |

### Growth —— 增长率与增长加速度（YoY / QoQ / 加速度）

通过 **11** 条。

| 因子 | 判定 | 验证口径 | 官方公式（文档） |
|---|---|---|---|
| `asset_growth_qoq` | APPROX | 横截面Spearman | Growth = TotalAssets_t / TotalAssets_{prev_report} - 1 # 财报披露日计算 Factor = CrossSectionalRank(Growth_filled) |
| `eaa` | APPROX | 横截面Spearman | 1. EGA = EPS_Q / EPS_Q_{t-252} - 1 2. EAA = EGA - EGA_{t-63} Factor = CrossSectionalRank(EAA) |
| `gross_margin_qoq` | APPROX | 横截面Spearman | 1. GrossMargin = (Revenue_TTM - Cost_TTM) / Revenue_TTM 2. Growth = GrossMargin_t / GrossMargin_{prev_report} - 1 # 财报披露日计算 Factor = CrossSectionalRank(Growth_filled) |
| `pa` | APPROX | 横截面Spearman | 1. PG = ROA_t - ROA_{t-252} 2. PA = PG - PG_{t-63} Factor = CrossSectionalRank(PA) |
| `peg_252d` | EXACT | 绝对误差 | 1. PE = Close / EPS_TTM 2. EPS_Growth = ts_returns(EPS, window, mode='simple') 3. PEG = PE / (EPS_Growth * 100) |
| `yoy_net_asset` | GOOD | 横截面Spearman | YoY = NetAsset_t / NetAsset_{t-252} - 1 Factor = CrossSectionalRank(YoY) |
| `yoy_net_profit` | APPROX | 绝对误差 | YoY = Value_t / Value_{t-252} - 1 |
| `yoy_revenue` | EXACT | 绝对误差 | YoY = Value_t / Value_{t-252} - 1 |
| `yoy_roa` | APPROX | 中位相对误差(用户标准) | YoY = ROA_TTM_t / ROA_TTM_{t-252} - 1 Factor = CrossSectionalRank(YoY) |
| `yoy_roe` | APPROX | 中位相对误差(用户标准) | YoY = ROE_TTM_t / ROE_TTM_{t-252} - 1 Factor = CrossSectionalRank(YoY) |
| `yoy_total_asset` | EXACT | 横截面Spearman | YoY = TotalAsset_t / TotalAsset_{t-252} - 1 Factor = CrossSectionalRank(YoY) |

---

## 2. 已验证的口径修正（文档与实现不符，均已实测）

| 因子 | 实测口径 / 修正 |
|---|---|
| `size` | **文档公式有误**：实为 `−log(total_mv/100)`；文档的 `−log(总股本×收盘价/1e6)` 与官方 corr=−0.02（§批次二） |
| `float_size` | 同 `size`：实为 `−log(circ_mv/100)`；文档口径 corr=0.067 |
| `book_to_market` | 文档的 `_pri` 后缀**误导**：实为**最新报告期期末**值，且分子**必须计入递延所得税资产**（中位误差 1.28e-11） |
| `earnings_cut_to_market` | **文档字面写「扣非净利润」，实测官方用归母净利润 TTM**：归母 0.999997 vs 扣非 0.941175（§5.14） |
| `gpm_q` | 分子分母均为**单季（差分）**的 `revenue`/`oper_cost`；累计(YTD) 口径只有 0.977（§本轮标定） |
| `sales_to_market` | 分子是**单季**营业总收入（TTM 只有 0.957）；分母是**总**市值（流通市值 0.944） |
| `rsi` | **Wilder 平滑 `ewm(com=13)`**；`span=14` / SMA14 / 原始价全 FAIL。中位相对误差 = 0 |
| `rsrs` | 后复权 + **`ddof=1`**；`ddof=0` 仅 APPROX |
| `price_dist` | 后复权价 + **`ceil`**；`nearest` corr −0.10 |
| `price_position_ir_60d` | 用 **`ddof=1`** |
| `days_down_up` | **严格** `diff>0 / diff<0` + 后复权；非严格 corr 0.925 |
| `small_cap_reversal_21d` | `CrossSectionalRank(Reversal) × SmallCap`，`SmallCap = CrossSectionalRank(−MarketCap)`（旧文档公式已废弃） |
| `earnings_to_price` | `1 / pe_ttm` |
| `amount_ma_20d` | 成交额单位是**元**（Tushare 千元×1000）；且 `TSPanel.AMOUNT` **已被乘过复权因子**，须 `/ADJ` 还原 |
| `roa_ttm` | 内层 = **净利润 `n_income`（含少数股东）TTM / 期末总资产**（全市场 0.99999）；归母只有 0.986。外层 `CrossSectionalRank` |
| `roe_ttm` | 内层 = **归母净利润 TTM / 股东权益合计（含少数股东）**（逐位 1.0000）；passthrough 无外层 rank |
| `roe_y` | 同 `roe_ttm`，取**年报**报告期 |
| `roa_y` | 年报报告期口径 |
| `asset_turnover` | TTM 营业收入 / 期末总资产 |
| `de` | `总负债 / 股东权益`；**注意**：文档公式文本含 `CrossSectionalRank` 但官方值是**原始比值**（−166~412），必须实测判型 |
| `nl_size` | `CrossSectionalRank(−log(市值))` 型；公式文本省略了 rank 包装 |
| `quality_composite` | AQR Quality-Minus-Junk 六项之和；公式文本省略 rank 包装 |
| `dif` | ⚠️ EMA 族有 **qdata 尾部未沉淀窗口**（约 20~25 交易日），判定须截断（§G2）；截断后 maxerr ≈5e-11 |

### 通用约定（全局，适用于整库）

| 编号 | 约定 |
|---|---|
| G1 | 复权口径**分族**：显式写 `Close_hfq` 的因子用后复权；**Alpha101 用不复权价**；`VWAP = amount×10/vol` 亦不复权 |
| G2 | ⚠️ EMA 族有 **qdata 尾部未沉淀窗口**（约 20~25 交易日，近期值是暂定值，事后回填）⇒ 判定须截断 `--settle-days 30` |
| G3 | 滚动窗口**含当日**（`MA`/`STD` 等） |
| G4 | 收益用**简单收益**（非对数） |
| G5 | `StdDev` 用**样本标准差** `ddof=1` |
| G7 | 取数纪律：`factor_value` 日期必须 `YYYYMMDD`；禁用 offset 分页（会返回重复行）；空结果 `code=0/msg=ok/items=[]` 必须当可重试 |
| G11 | `Rank(x) = count(x_i ≤ x)/N`，并列取**最大**名次（`method="max"`） |
| G13 | `Ts_ArgMax(x,d)` = **距最大值的天数**（与 `np.argmax` 位置口径排序相反） |
| G16 | `CrossSectionalRank(x) = rank(x)/N`，升序 1..N |
| G17 | **判据必须实证确定**：公式文本会两个方向都错（`de` 文本含 rank 实为原始比值；`roe_ttm` 文本无 rank 实为 rank/N） |

---

## 3. 已否证的实现变体（不要重复踩坑）

| 因子 | 否证的写法 | 实测结果 |
|---|---|---|
| `size` | `−log(总股本 × 收盘价 / 1e6)`（文档写法） | corr = **−0.02**（完全不相关） |
| `float_size` | `−log(流通股本 × 后复权价 / 1e6)` | corr = 0.067 |
| `rsi` | `span=14` / SMA14 / 原始价 | 全 FAIL；Wilder `com=13` 才精确 |
| `price_dist` | `round` 到最近整数 | corr = −0.10 |
| `rsrs` | `ddof=0` | 仅 APPROX |
| `book_to_market` | `1/pb` | 中位相对误差 9.95e-2（Tushare `pb` 不含递延所得税资产） |
| `book_to_market` | 期末归母权益（不加 DTA） | 中位相对误差 5.3e-2 |
| `sharpe 类` | 算术年化 / 252 交易日 | 聚宽体系用 **几何年化 + 250**；本项目按各族分别标定 |
| `alpha101_12 / 42 / 101` | 后复权价 | 误差 3105 / 792.6 / 8e-2 ⇒ **Alpha101 用不复权价** |
| `yoy_roa / yoy_roe` | 4 个披露日偏移替代 `t-252` 交易日 | 0.9626 / 0.9689 < 0.9837 / 0.9851（更差） |
| `yoy_roa / yoy_roe` | PIT 基准换 `f_ann_date` | 仅 +0.0014 / +0.0033，不足以解释残差 |
| `ocf_to_market` | 分子取绝对值 `|OCF_TTM|/mv` | 0.528 vs 基线 0.763（更差） |
| `ncf_to_market` | `|OCF+ICF+Fin|/mv` | **−0.032**（更差） |
| `ebitda_to_market` | `|EBITDA_TTM|/mv` | 0.821 vs 0.978（更差） |
| `fcf_to_market` | Tushare `free_cashflow` | 0.242 vs 基线 0.851（更差） |
| `sales_to_market` | TTM 营业总收入 | 0.957 vs 单季 1.000 |
| `earnings_cut_to_market` | 扣非净利润 TTM（文档字面） | 0.941 vs 归母 0.999997 |
| `gpm_q` | 单季(差分) 口径（文档「q 用累计单季」被误读为差分） | 0.9698 vs 累计(YTD) 0.99998（§5.15） |
| `Rank` | `method="average"`（并列取平均名次） | `yoy_ocf` 得 2759 而官方 3642；须 `method="max"` |
| `所有 EMA 族因子` | 用最近 30 自然日内官方值做判定 | qdata 近期值是**暂定值**，事后回填（§G2） |

---

## 4. 未通过因子归档

共 **39** 条，逐条列出验证口径、实测值与归档原因。

| 因子 | 族 | 判定 | 秩相关/中位误差 | 归档类别 | 说明 |
|---|---|---|---|---|---|
| `alpha101_29` | Alpha101 | FAIL | 0.8009 | §5.6 官方股票池/停牌规则未标定 | 股票池/停牌口径未标定 |
| `alpha101_32` | Alpha101 | FAIL | 0.9537 | §5.6 官方股票池/停牌规则未标定 | 股票池/停牌口径未标定 |
| `alpha101_45` | Alpha101 | FAIL | 0.9581 | §5.6 官方股票池/停牌规则未标定 | 股票池/停牌口径未标定 |
| `alpha101_48` | Alpha101 | FAIL | 0.9205 | §5.11 行业标准未披露 | 口径未标定（IndNeutralize 行业分类口径） |
| `alpha101_56` | Alpha101 | FAIL | 0.9864 | §5.6 官方股票池/停牌规则未标定 | 股票池/停牌口径未标定 |
| `alpha101_58` | Alpha101 | FAIL | 0.7404 | §5.11 行业标准未披露 | §5.11 行业标准未披露（四种最佳 0.7404）；分档一致率 0.62 亦不达标 |
| `alpha101_59` | Alpha101 | FAIL | 0.7497 | §5.11 行业标准未披露 | §5.11 行业标准未披露（四种最佳 0.7497）；分档一致率 0.56 亦不达标 |
| `alpha101_63` | Alpha101 | FAIL | 0.8776 | 成因未定 | 覆盖率不足（官方 30798 / 重叠 27972） |
| `alpha101_64` | Alpha101 | NO_DATA | nan | 厂商私有字段未定义 | 未实现：未定义标识符 '未定义变量 Delta_Mix' |
| `alpha101_65` | Alpha101 | FAIL | 0.7382 | §5.6 离散输出（±1）跳变 | §5.6 离散输出（±1）；分档一致率 0.87 仍不达标 |
| `alpha101_67` | Alpha101 | FAIL | 0.7577 | §5.11 行业标准未披露 | 口径未标定（IndNeutralize 行业分类口径） |
| `alpha101_68` | Alpha101 | FAIL | 0.8025 | §5.6 离散输出（±1）跳变 | §5.6 离散输出（±1）；分档一致率 0.90 仍不达标 |
| `alpha101_69` | Alpha101 | FAIL | 0.8729 | §5.11 行业标准未披露 | 口径未标定（IndNeutralize 行业分类口径） |
| `alpha101_70` | Alpha101 | FAIL | 0.8813 | §5.11 行业标准未披露 | 口径未标定（IndNeutralize 行业分类口径） |
| `alpha101_8` | Alpha101 | FAIL | 0.9829 | §5.6 官方股票池/停牌规则未标定 | 股票池/停牌口径未标定 |
| `eap` | Growth | FAIL | 0.9291 | 分子/分母口径未标定 | EPS_Q 口径 + Close 分母待定 |
| `np_ttm_qoq` | Growth | FAIL | 0.9157 | 比率分母穿越 0 ⇒ 极端值主导 | 比率分母穿越 0；并列仅 22 只，影响小 |
| `sa` | Growth | FAIL | 0.9513 | §5.10 供方分组规则未披露 | §5.10 疑同因：大并列块 564 只（供方分组规则未披露） |
| `yoy_ocf` | Growth | FAIL | 0.7337 | §5.10 供方分组规则未披露 | §5.10 供方分组规则未披露（并列块 1767 只；本地 yoy 分布与非并列组无法区分） |
| `cash_profit_ratio` | Quality | FAIL | 0.8440 | 分子/分母口径未标定 | 分子口径未标定 (OCF−NI)/NI |
| `cfcr` | Quality | FAIL | 0.9655 | ⚠️ 样本量不足 | ⚠️ 官方截面仅 N=172 ⇒ 样本量不足、Spearman 不可靠；InterestExpense 字段未标定 |
| `delta_npm` | Quality | FAIL | 0.9843 | 比率分母穿越 0 ⇒ 极端值主导 | 比率分母穿越 0 ⇒ 极端值主导（Spearman 0.9843） |
| `delta_opm` | Quality | FAIL | 0.9850 | 比率分母穿越 0 ⇒ 极端值主导 | 比率分母穿越 0 ⇒ 极端值主导（Spearman 0.9850） |
| `expenses_to_equity_yoy` | Quality | FAIL | 0.7752 | 比率分母穿越 0 ⇒ 极端值主导 | 比率分母穿越 0 ⇒ 极端值主导 |
| `icr` | Quality | FAIL | 0.8296 | ⚠️ 样本量不足 | ⚠️ 官方截面仅 N=106 ⇒ 样本量不足、Spearman 不可靠；InterestExpense 字段未标定 |
| `income_tax_yoy` | Quality | FAIL | 0.7949 | 比率分母穿越 0 ⇒ 极端值主导 | 比率分母穿越 0 ⇒ 极端值主导 |
| `lra_yoy` | Quality | FAIL | 0.0709 | 厂商私有字段未定义 | LongtermReceivableAccount 字段未标定（Tushare lt_rec 仅覆盖 1693 只） |
| `np_to_deferred_tax_yoy` | Quality | FAIL | 0.6739 | 比率分母穿越 0 ⇒ 极端值主导 | 比率分母穿越 0 ⇒ 极端值主导 |
| `np_to_fixed_assets_yoy` | Quality | FAIL | 0.6179 | 比率分母穿越 0 ⇒ 极端值主导 | 比率分母穿越 0 ⇒ 极端值主导；疑 qdata 有裁剪（filter=True） |
| `np_to_inventory_yoy` | Quality | FAIL | 0.6484 | 比率分母穿越 0 ⇒ 极端值主导 | 比率分母穿越 0 ⇒ 极端值主导 |
| `np_to_salary_yoy` | Quality | FAIL | 0.7950 | 比率分母穿越 0 ⇒ 极端值主导 | 比率分母穿越 0 ⇒ 极端值主导 |
| `np_to_total_expenses_yoy` | Quality | FAIL | 0.6054 | 比率分母穿越 0 ⇒ 极端值主导 | 比率分母穿越 0 ⇒ 极端值主导 |
| `quality_composite` | Quality | FAIL | 0.9008 | 分子/分母口径未标定 | OpCashInflow/InvCashInflow 字段 + filter=True 语义未标定 |
| `tax_surcharge_yoy` | Quality | FAIL | 0.9432 | 比率分母穿越 0 ⇒ 极端值主导 | 比率分母穿越 0 ⇒ 极端值主导 |
| `ebitda_to_market` | Value | FAIL | 0.9100 | 分子/分母口径未标定 | §5.14 口径未定：EBITDA_TTM/mv 0.910（年报口径 0.973、EBIT+营业成本 0.599 均更差） |
| `etp5` | Value | FAIL | 0.9844 | 分子/分母口径未标定 | §5.14 窗口口径未定：mean(归母年报,1260)/mean(mv,1260) 0.984；名次偏差中位 7.86% |
| `ncf_to_market` | Value | FAIL | 0.7128 | 分子/分母口径未标定 | §5.14 口径未定：(OCF+ICF+筹资净额)_TTM/mv 0.713；最大偏差集中在银行；OCF+ICF 0.184、单季 0.202 均更差 |
| `ocf_to_market` | Value | FAIL | 0.8623 | 成因未定 | §5.14 少数金融股错位主导：名次偏差中位仅 1.46% 但 p90 19.5%；最大偏差 8 只全为银行/券商（存款同业现金流科目差异）；分子取绝对值已否证 |
| `pegh5` | Value | FAIL | 0.9409 | 分子/分母口径未标定 | §5.14 口径未定：-Close/(g5·EPS_TTM) 0.941；g5 用 EPS 年报 5 年复合增速 |

### 归档类别说明

| 类别 | 判定 | 依据 |
|---|---|---|
| §5.10 供方分组规则未披露 | **结构性不可复现** | 大并列块（yoy_ocf 1767 只 / eaa 1167 / pa 850 / sa 564）。**已证不可反推**：并列块的本地 yoy 分布与非并列组统计上无法区分 ⇒ 分组不可能是数据本身的函数。 |
| §5.11 行业标准未披露 | **结构性不可复现** | `IndNeutralize` 需厂商行业分类。申万 L1/L2/L3 + Tushare 自有**四种标准全部试过**，最佳仅 0.9255，且**行业越细越差**（7/7 成立）⇒ 官方分组更粗或完全不同。 |
| §5.6 官方股票池/停牌规则未标定 | **结构性不可复现** | 官方 N 比 Tushare `daily` 少约 100~120 只，含 ST 204 只、含停牌 4 只，剔除列表无干净上市日切分点 ⇒ **无法从公开字段推导**。长窗口因子的历史横截面池随之漂移。 |
| §5.6 离散输出（±1）跳变 | **度量不适配 + 边缘漂移** | 官方只有 2 个取值，1~2 位名次漂移即造成 ±1 跳变。已改用「分档归属一致率」，`alpha101_61`(0.96) / `62`(0.98) 接近但未达标。 |
| 算子统计量定义未标定 | **口径未标定（接近）** | `Alpha101` 长窗口/`Ts_Rank(高并列序列)` 类（`39`/`52`/`34`/`25`/`19`），Spearman 0.9937~0.9985 —— 名次基本正确，差算子细节。 |
| 比率分母穿越 0 ⇒ 极端值主导 | **疑供方裁剪，规则未披露** | 分子的比值或增量分母可正可负，产生 ±1e3~1e5 爆炸值主导排序。**同结构但分母恒正的因子全部 0.99+**（asset_growth_qoq 0.9948、yoy_total_asset 1.0000）⇒ 机制正确，疑官方对极端值有裁剪，但 `filter=True` 语义未披露。 |
| 分子/分母口径未标定 | **口径未标定（可继续）** | `cash_profit_ratio` / `gpm_q` / `eap` / `ar_ap_to_revenue` 等：分子或分母的科目口径未定，有明确前进方向（见 §5.14 与本轮标定）。 |
| 厂商私有字段未定义 | **结构性不可实现** | `alpha101_64` 公式含 `Delta_Mix`，文档未定义该标识符；`lra_yoy` 的 `LongtermReceivableAccount` 在 Tushare 只覆盖 1693 只（corr 0.069）。 |
| ⚠️ 样本量不足 | **结论不可靠（非实现问题）** | `cfcr`(N=172) / `icr`(N=106)：官方横截面只有一两百只股票，**Spearman 在小样本上噪声极大，判定结论本身不可靠**。 |

---

## 5. 相关文件

| 文件 | 内容 |
|---|---|
| `CONVENTIONS.md` | 口径约定与完整验证记录（G1~G17 + 逐批标定 + 否证清单） |
| `SUMMARY.md / SUMMARY.csv / SUMMARY_BY_FAMILY.csv` | 精度总账（自动生成） |
| `SUMMARY.csv 的 `note` 列` | 未通过因子的逐条归档原因 |
| `FORMULA_AUDIT.md` | 公式静态审计（横截面扫描 / 参数 / 直通 / 跨体系对照） |
| `final8_scan.csv` | 最后 8 条疑难因子的跨日多口径标定 |
| `value_variant_scan.csv / value_sign_scan.csv` | Value 族口径变体与符号假设检验 |
| `xs_median_error.csv` | 横截面因子的「中位相对误差」补测（用户口径） |
