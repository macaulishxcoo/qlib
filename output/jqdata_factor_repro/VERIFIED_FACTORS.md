# 聚宽因子复现 —— 已验证因子清单

本清单记录**经变体对照实测确认**的因子公式与口径注意事项。
与官方文档不同之处均已标出——文档有若干处与实现不符。

- 通过因子数（中位口径）：**185** / 276
- 验证区间：`2026-05-06` ~ `2026-06-16`（6 只标的）
- 判定：`verdict_med`（中位误差 / 官方值量级）
- 生成脚本：`scripts/jqdata/gen_verified_catalog.py`

---

## 通用口径约定


### G1. 复权

- **统一用后复权**（`fq='post'`），全项目唯一来源 `conventions.FQ`。
- 前复权与后复权对**比值/均值类因子结果完全相同**（两者只差一个全局常数，
  比值把它约掉）——实测 ROC6/Price1M 的前后复权 maxerr 逐位相同。
- **不复权**只用于 `price_no_fq` 一个因子；VPT 用到不复权**成交量**。

### G2. ⚠ 必须使用 2 位小数价格（`round=True`）

官方因子是基于 **2 位小数**的原始价计算的。实测把 `get_price(..., round=False)`
（全精度）接进来，**结果反而变差**（全局 150 → 132 通过，risk 族 12/12 GOOD 全退化为 APPROX）。
复现的定义是**对齐官方口径**，不是追求更高精度。

### G3. 算子口径

| 项 | 口径 |
|---|---|
| `MA(X,N)` | `rolling(N).mean()`，**含当日**（唯一例外：`Price1M/Price3M`） |
| `STD(X,N)` | **样本标准差** `rolling(N).std(ddof=1)`（ddof=0 误差放大 450 倍） |
| `EMA(X,N)` | `ewm(span=N, adjust=False).mean()` |
| 年化交易日数 | **250**（不是 252，也不是 244） |
| 夏普分子 | **几何年化收益率** `expm1(Σln(1+r)·250/w)` |
| 峰度 | pandas `.kurt()` = **超额峰度**（Fisher），不是 Pearson(+3) |
| 偏度 | pandas `.skew()` = 校正 Fisher-Pearson |

### G4. 财务数据口径

- 用**最新一期单季度**数据；TTM = **截至比对日已披露的最新 4 个单季之和**。
  ⚠ 必须取「最新 4 季」而非固定某一年——这是早期误判「TTM 不可复现」的根因。
- `AvgQ(X,4)` = 最新 4 个单季的**均值**（用于资产负债表时点科目）。
- 单位陷阱：`valuation.market_cap` 是**亿元**（×1e8）；
  `valuation.capitalization` 是**万股**（×1e4）。
- **「货币资金」≠「现金及现金等价物」**：前者 `balance.cash_equivalents`，
  后者 `cash_flow.cash_and_equivalents_at_end`。

### G5. 精度判定的三个口径

| 判定 | 统计量 | 用途 |
|---|---|---|
| `verdict` | maxerr / mean(｜官方值｜) | 「能否逐位复现对方流水线」——对尾部极值最敏感 |
| `verdict_robust` | p99 误差 | 中间口径 |
| **`verdict_med`** | **中位误差** | **「这个因子实际能不能用」——推荐作为可用性主判据** |

⚠ `maxerr` 会被极少数观测（如某只低价股某天）完全支配。例如 `arron_up_25`
在 94.4% 的标的上误差是 **7e-15**（精确），却因 9/160 只离群而 maxerr 达 84。

### G6. ⚠ 价格类因子的精度上限（结构性，不可修复）

`后复权价 = 不复权价(2位小数) × 复权因子`，故相对分辨率 ≈ `0.005 / 原始股价`。
对 ×100 或做差放大型因子：

```
err ≈ A × 0.005 / 原始股价      （实测 log-log 斜率 −1.08，理论 −1）
```

**A 股中位价约 15.9 元，因此下列因子在典型价位上不可能达到 GOOD 档**：

| 因子 | 达到 GOOD 需原始价 ≥ |
|---|---|
| `ROC6` | 378.83 元 |
| `BIAS10` | 310.80 元 |
| `single_day_VPT` | 246.98 元 |
| `CCI20` | 146.84 元 |

实用含义：这些因子**数值有偏差，但排序几乎完全一致**（corr ≥ 0.99999），
**横截面排序/分组用法有效**，精确数值比较无效。


---

## 逐族清单

「已验证公式」列是与文档核对后的实际口径；⚠ 标记表示**文档会误导你**。

> 说明：若「已验证公式」单元格只是中文名称的重复（如「每股未分配利润」），表示**官方文档未给可执行公式**，该因子的口径由因子名 + 变体对照实测标定得出，具体实现见 `scripts/jqdata/facsim/families/*.py`。

### technical（15 个通过）—— 纯价量技术指标（均线/布林/MACD/资金流）

| 因子 | 中文名 | 已验证公式 | 精度 | 注意事项 |
|---|---|---|---|---|
| `price_no_fq` | 不复权价格 | 不复权收盘价（fq='none'） | EXACT 0.0e+00 | 定义即不复权，是**唯一不使用后复权**的价格类因子 |
| `MFI14` | 资金流量指标 | 100 − 100/(1 + ΣMF⁺/ΣMF⁻)，TYP=(H+L+C)/3，MF=TYP×成交量，按 TYP 涨跌分正负，窗口 14 | GOOD 4.9e-07 | 5/6 标的精确到 2e-4；单只标的异常会使 maxerr 偏大 |
| `EMA5` | 5日指数移动均线 | EMA(C, 5) / C | GOOD 7.1e-07 | `ewm(span=5, adjust=False)`；EMA 无界记忆，span 越大越吃预热 |
| `MAC5` | 5日移动均线 | MA(C, 5) / C | GOOD 9.9e-07 | **含当日**（已实测：shift(1) 版误差放大 3 个数量级） |
| `EMAC10` | 10日指数移动均线 | EMA(C, 10) / C | GOOD 1.1e-06 | 同 EMA5 |
| `EMAC26` | 26日指数移动均线 | EMA(C, 26) / C | GOOD 1.3e-06 | 同 EMA5 |
| `MAC10` | 10日移动均线 | MA(C, 10) / C | GOOD 1.3e-06 | 含当日 |
| `EMAC20` | 20日指数移动均线 | EMA(C, 20) / C | GOOD 1.3e-06 | 同 EMA5 |
| `EMAC12` | 12日指数移动均线 | EMA(C, 12) / C | GOOD 1.4e-06 | 同 EMA5 |
| `MAC60` | 60日移动均线 | MA(C, 60) / C | GOOD 1.6e-06 | 含当日 |
| `boll_down` | 下轨线（布林线）指标 | (MA(C,20) − 2×STD(C,20)) / C | GOOD 1.6e-06 | 同 boll_up |
| `MAC20` | 20日移动均线 | MA(C, 20) / C | GOOD 1.7e-06 | 含当日 |
| `boll_up` | 上轨线（布林线）指标 | (MA(C,20) + 2×STD(C,20)) / C | GOOD 1.8e-06 | **STD 是样本标准差 ddof=1**（ddof=0 版误差 1.28e-03）；含当日 |
| `MAC120` | 120日移动均线 | MA(C, 120) / C | GOOD 2.2e-06 | 含当日 |
| `MACDC` | 平滑异同移动平均线 | 2 × (DIF − DEA) / C，其中 DIF = EMA(C,12) − EMA(C,26)，DEA = EMA(DIF, 9) | GOOD 4.4e-05 | **文档未提 ×2**。四变体对照：(DIF−DEA)/C 误差 2.1e-02、DIF/C 6.8e-02、DEA/C 7.3e-02，**2×(DIF−DEA)/C 为 1.1e-05** |

### risk（12 个通过）—— 收益矩类风险指标（方差/偏度/峰度/夏普）

| 因子 | 中文名 | 已验证公式 | 精度 | 注意事项 |
|---|---|---|---|---|
| `Kurtosis120` | 个股收益的120日峰度 | pct_change().rolling(120).kurt() | GOOD 5.9e-08 | 同 Kurtosis20 |
| `sharpe_ratio_20` | 20日夏普比率 | (Rp − 0.04) / (std(ddof=1) × √250)，Rp = expm1(Σln(1+r)·250/20) | GOOD 6.5e-08 | Rp 是**几何年化收益率**（算术均值×250 版误差 7.69 ❌）；std 用 ddof=1（ddof=0 版 2.94e-01 ❌）；√250 不是 √252 |
| `Kurtosis20` | 个股收益的20日峰度 | pct_change().rolling(20).kurt() | GOOD 7.1e-08 | pandas `.kurt()` 返回**超额峰度**（Fisher）；+3 的 Pearson 峰度误差 3.00e+00 ❌ |
| `Kurtosis60` | 个股收益的60日峰度 | pct_change().rolling(60).kurt() | GOOD 8.1e-08 | 同 Kurtosis20 |
| `sharpe_ratio_60` | 60日夏普比率 | (Rp − 0.04) / (std(ddof=1) × √250)，Rp = expm1(Σln(1+r)·250/60) | GOOD 2.1e-07 | 同 sharpe_ratio_20 |
| `Skewness20` | 个股收益的20日偏度 | pct_change().rolling(20).skew() | GOOD 2.2e-07 | pandas `.skew()` = **校正 Fisher-Pearson**；未校正的 g1 误差 2.52e-01 ❌ |
| `sharpe_ratio_120` | 120日夏普比率 | (Rp − 0.04) / (std(ddof=1) × √250)，Rp = expm1(Σln(1+r)·250/120) | GOOD 2.6e-07 | 同 sharpe_ratio_20 |
| `Skewness120` | 个股收益的120日偏度 | pct_change().rolling(120).skew() | GOOD 2.7e-07 | 同 Skewness20 |
| `Skewness60` | 个股收益的60日偏度 | pct_change().rolling(60).skew() | GOOD 4.1e-07 | 同 Skewness20 |
| `Variance120` | 120日年化收益方差 | pct_change().rolling(120).var(ddof=1) × 250 | GOOD 4.5e-06 | 同 Variance20 |
| `Variance20` | 20日年化收益方差 | pct_change().rolling(20).var(ddof=1) × 250 | GOOD 5.0e-06 | **250 不是 252**（252 版误差 2.25e-03、244 版 6.75e-03）；简单收益率（对数版 1.17e-02 ❌）；**样本方差** ddof=1 |
| `Variance60` | 60日年化收益方差 | pct_change().rolling(60).var(ddof=1) × 250 | GOOD 5.1e-06 | 同 Variance20 |

### momentum（30 个通过）—— 动量与超买超卖指标（ROC/BIAS/CCI/TRIX/CR/Aroon/PLRC…）

| 因子 | 中文名 | 已验证公式 | 精度 | 注意事项 |
|---|---|---|---|---|
| `arron_down_25` | Aroon指标下轨 | **[HIGH]** 序列的 argmin 位置 → (idx+1)/25 × 100 | EXACT 0.0e+00 | ⚠⚠ **用 HIGH 序列，不是 LOW**（与 Aroon 通行定义相反）。宽池 160 只：HIGH 版 3/160 超标、LOW 版 **156/160** ❌ |
| `arron_up_25` | Aroon指标上轨 | HIGH 序列的 argmax 位置 → (idx+1)/25 × 100 | EXACT 0.0e+00 | 并列极值取**末次**（取首次 maxerr 4.4e+01 ❌）；宽池 9/160 超标 |
| `BBIC` | BBI 动量 | BBI(3, 6, 12, 24) / 收盘价 （BBI 为常用技术指标类因子“多空均线”） | GOOD 1.2e-06 |  |
| `Price3M` | 当前股价除以过去三个月股价均值再减1 | 当日收盘价 / MA(C, 60).shift(1) − 1 | GOOD 3.8e-06 | ⚠ 同上，不含当日的过去 60 日 |
| `Price1M` | 当前股价除以过去一个月股价均值再减1 | 当日收盘价 / MA(C, 20).shift(1) − 1 | GOOD 7.0e-06 | ⚠⚠ 均值窗口是**不含当日的过去 20 日**。文档写「(21天)」是**跨度**（20 历史日 + 当日），但均值不含当日。MA(21) 版 3.7e-02 ❌ |
| `MASS` | 梅斯线 | Σ₂₅( SMA(H−L, 9) / SMA(SMA(H−L,9), 9) ) | GOOD 7.7e-06 | ⚠ 文档只写「MASS(N1=9,N2=25,M=6)」无公式。实测用 **SMA 而非 EMA**（EMA 版 corr 0.972 ❌） |
| `CCI20` | 20日顺势指标 | CCI:=(TYP-MA(TYP,N))/(0.015*AVEDEV(TYP,N)); TYP:=(HIGH+LOW+CLOSE)/3; N | GOOD 1.9e-05 |  |
| `TRIX10` | 10日终极指标TRIX | MTR=收盘价的10日指数移动平均的10日指数移动平均的10日指数移动平均(求三次ema10); TRIX=(MTR-1日前的MTR)/1日 | GOOD 1.9e-05 |  |
| `ROC60` | 60日变动速率（Price Rate of Change） | ①AX=今天的收盘价—60天前的收盘价 ②BX=60天前的收盘价 ③ROC=AX/BX*100 | GOOD 2.3e-05 |  |
| `CCI88` | 88日顺势指标 | CCI:=(TYP-MA(TYP,N))/(0.015*AVEDEV(TYP,N)); TYP:=(HIGH+LOW+CLOSE)/3; N | GOOD 2.4e-05 |  |
| `TRIX5` | 5日终极指标TRIX | MTR=收盘价的5日指数移动平均的5日指数移动平均的5日指数移动平均(求三次ema5); TRIX=(MTR-1日前的MTR)/1日前的MT | GOOD 2.4e-05 |  |
| `BIAS60` | 60日乖离率 | （收盘价-收盘价的N日简单平均）/ 收盘价的N日简单平均*100，在此n取60 | GOOD 2.5e-05 |  |
| `CCI15` | 15日顺势指标 | CCI:=(TYP-MA(TYP,N))/(0.015*AVEDEV(TYP,N)); TYP:=(HIGH+LOW+CLOSE)/3; N | GOOD 2.6e-05 |  |
| `CCI10` | 10日顺势指标 | CCI:=(TYP-MA(TYP,N))/(0.015*AVEDEV(TYP,N)); TYP:=(HIGH+LOW+CLOSE)/3; N | GOOD 2.9e-05 |  |
| `ROC120` | 120日变动速率（Price Rate of Change） | ①AX=今天的收盘价—120天前的收盘价 ②BX=120天前的收盘价 ③ROC=AX/BX*100 | GOOD 3.0e-05 |  |
| `CR20` | CR指标 | ①中间价=1日前的最高价+最低价/2 ②上升值=今天的最高价-前一日的中间价（负值记0） ③下跌值=前一日的中间价-今天的最低价（负值记0） | GOOD 3.0e-05 |  |
| `ROC20` | 20日变动速率（Price Rate of Change） | ①AX=今天的收盘价—20天前的收盘价 ②BX=20天前的收盘价 ③ROC=AX/BX*100 | GOOD 3.1e-05 |  |
| `ROC12` | 12日变动速率（Price Rate of Change） | ①AX=今天的收盘价—12天前的收盘价 ②BX=12天前的收盘价 ③ROC=AX/BX*100 | GOOD 3.9e-05 |  |
| `PLRC6` | 6日收盘价格与日期线性回归系数 | 回归斜率(C, 6) / MA(C, 6) | GOOD 4.0e-05 | 文档：(close/mean(close)) = β·t + α；逐日滚动均值归一化版误差 2.6e-02 ❌ |
| `single_day_VPT_12` | 单日价量趋势12均值 | MA(single_day_VPT, 12) | GOOD 4.3e-05 |  |
| `BIAS20` | 20日乖离率 | （收盘价-收盘价的N日简单平均）/ 收盘价的N日简单平均*100，在此n取20 | GOOD 4.4e-05 |  |
| `single_day_VPT_6` | 单日价量趋势6日均值 | MA(single_day_VPT, 6) | GOOD 4.7e-05 |  |
| `bear_power` | 空头力道 | (最低价-EMA(close,13)) / close | GOOD 5.0e-05 |  |
| `ROC6` | 6日变动速率（Price Rate of Change） | ①AX=今天的收盘价—6天前的收盘价 ②BX=6天前的收盘价 ③ROC=AX/BX*100 | GOOD 5.0e-05 |  |
| `BIAS10` | 10日乖离率 | （收盘价-收盘价的N日简单平均）/ 收盘价的N日简单平均*100，在此n取10 | GOOD 5.2e-05 |  |
| `PLRC12` | 12日收盘价格与日期线性回归系数 | 回归斜率(C, 12) / MA(C, 12) | GOOD 5.5e-05 | 同上 |
| `bull_power` | 多头力道 | (最高价-EMA(close,13)) / close | GOOD 6.8e-05 |  |
| `BIAS5` | 5日乖离率 | （收盘价-收盘价的N日简单平均）/ 收盘价的N日简单平均*100，在此n取5 | GOOD 6.9e-05 |  |
| `PLRC24` | 24日收盘价格与日期线性回归系数 | 回归斜率(C, 24) / MA(C, 24) | GOOD 7.3e-05 | 同上 |
| `Volume1M` | 当前交易量相比过去1个月日均交易量 与过去过去20日日均收益率乘积 | 当日交易量 / 过去20日交易量MEAN * 过去20日收益率MEAN | GOOD 8.2e-05 |  |

### emotion（36 个通过）—— 情绪与量能指标（换手率/成交量/成交额/ATR/PSY/WVAD…）

| 因子 | 中文名 | 已验证公式 | 精度 | 注意事项 |
|---|---|---|---|---|
| `VOL20` | 20日平均换手率 | 20日换手率的均值,单位为% | EXACT 0.0e+00 |  |
| `VOL5` | 5日平均换手率 | 5日换手率的均值,单位为% | EXACT 0.0e+00 |  |
| `VOL10` | 10日平均换手率 | 10日换手率的均值,单位为% | EXACT 0.0e+00 |  |
| `MAWVAD` | 因子WVAD的6日均值 |  | EXACT 9.8e-14 |  |
| `VEMA12` | 12日成交量的移动平均值 |  | EXACT 1.2e-13 |  |
| `VEMA10` | 成交量的10日指数移动平均 |  | EXACT 1.2e-13 |  |
| `VEMA5` | 成交量的5日指数移动平均 |  | EXACT 1.2e-13 |  |
| `WVAD` | 威廉变异离散量 | (收盘价－开盘价)/(最高价－最低价)×成交量，再做加和，使用过去6个交易日的数据 | EXACT 2.2e-13 |  |
| `VSTD20` | 20日成交量标准差 | 20日成交量标准差 | EXACT 2.8e-13 |  |
| `VSTD10` | 10日成交量标准差 | 10日成交量标准差 | EXACT 3.1e-13 |  |
| `TVSTD20` | 20日成交金额的标准差 | 20日成交额的标准差 | EXACT 3.9e-13 |  |
| `TVSTD6` | 6日成交金额的标准差 | 6日成交额的标准差 | EXACT 4.5e-13 |  |
| `money_flow_20` | 20日资金流量 | Σ₂₀( (H+L+C)/3 × 成交量 ) | EXACT 5.3e-13 | ⚠ **正文只写「当日资金流量」，实际是 20 日求和**（单日版 maxerr 2.0e+11 ❌） |
| `TVMA6` | 6日成交金额的移动平均值 | 6日成交金额的移动平均值 | EXACT 6.5e-13 |  |
| `TVMA20` | 20日成交金额的移动平均值 | 20日成交金额的移动平均值 | EXACT 7.9e-13 |  |
| `VEMA26` | 成交量的26日指数移动平均 |  | GOOD 1.1e-09 |  |
| `AR` | 人气指标 | Σ₂₆(H − 今开) / Σ₂₆(今开 − L) × 100，**clip 负值为 0** | GOOD 2.5e-09 | n=26，文档明写 |
| `BR` | 意愿指标 | Σ₂₆(H − 昨收) / Σ₂₆(昨收 − L) × 100，**不 clip 负值** | GOOD 2.6e-09 | ⚠ **BR 不 clip 负值**，而同族的 AR 需要 clip（口径不一致）；clip 版 maxerr 5.4e+01 ❌ |
| `ATR14` | 14日均幅指标 | 真实振幅的14日移动平均 | GOOD 3.8e-09 |  |
| `ATR6` | 6日均幅指标 | 真实振幅的6日移动平均 | GOOD 4.4e-09 |  |
| `VROC12` | 12日量变动速率指标 | (V − REF(V, 11)) / REF(V, 11) × 100 | GOOD 6.0e-09 | ⚠ 同上，滞后 n−1 |
| `ARBR` | ARBR | 因子 AR 与因子 BR 的差 | GOOD 7.6e-09 |  |
| `VROC6` | 6日量变动速率指标 | (V − REF(V, 5)) / REF(V, 5) × 100 | GOOD 7.8e-09 | ⚠ **滞后是 n−1 不是 n**（官方 off-by-one） |
| `PSY` | 心理线指标 | 12日内上涨的天数/12 *100 | GOOD 1.0e-08 |  |
| `VMACD` | 成交量指数平滑异同移动平均线 | 快的指数移动平均线（EMA12）减去慢的指数移动平均线（EMA26）得到快线DIFF, 由DIFF的M日移动平均得到DEA，由DIFF-DE | GOOD 1.6e-08 |  |
| `VDIFF` | 计算VMACD因子的中间变量 | EMA(VOLUME，SHORT)-EMA(VOLUME，LONG) short设置为12，long设置为26，M设置为9 | GOOD 2.1e-08 |  |
| `VDEA` | 计算VMACD因子的中间变量 | EMA(VDIFF，M) short设置为12，long设置为26，M设置为9 | GOOD 3.3e-08 |  |
| `VOSC` | 成交量震荡 | 'VEMA12'和'VEMA26'两者的差值，再求差值与'VEMA12'的比，最后将比值放大100倍，得到VOSC值 | GOOD 5.9e-08 |  |
| `DAVOL5` | 5日平均换手率与120日平均换手率 | 5日平均换手率 / 120日平均换手率 | GOOD 2.1e-07 |  |
| `DAVOL10` | 10日平均换手率与120日平均换手率之比 | 10日平均换手率 / 120日平均换手率 | GOOD 2.3e-07 |  |
| `VOL120` | 120日平均换手率 | 120日换手率的均值,单位为% | GOOD 2.3e-07 |  |
| `DAVOL20` | 20日平均换手率与120日平均换手率之比 | 20日平均换手率 / 120日平均换手率 | GOOD 2.4e-07 |  |
| `VOL240` | 240日平均换手率 | 240日换手率的均值,单位为% | GOOD 3.5e-07 |  |
| `VR` | 成交量比率（Volume Ratio） | (AVS + ½CVS) / (BVS + ½CVS)，窗口 **24** 日 | GOOD 3.9e-07 | ⚠ **窗口 24，不是 TDX 惯例的 26**（26 版 maxerr 4.4e-01 ❌）；文档未给 N |
| `VOL60` | 60日平均换手率 | 60日换手率的均值,单位为% | GOOD 5.3e-07 |  |
| `turnover_volatility` | 换手率相对波动率 | std(换手率, 20, ddof=1) ÷ 100 | GOOD 9.3e-05 | ⚠ 文档说「取 20 日换手率标准差」，官方返回的是**小数**而非百分数（off/loc 恒为 0.010000） |

### pershare（15 个通过）—— 每股指标（科目 / 总股本）

| 因子 | 中文名 | 已验证公式 | 精度 | 注意事项 |
|---|---|---|---|---|
| `cash_and_equivalents_per_share` | 每股现金及现金等价物余额 | cash_flow.cash_and_equivalents_at_end / 总股本 | GOOD 4.4e-09 | ⚠ 不能用 balance.cash_equivalents（货币资金），corr 仅 0.80 |
| `retained_profit_per_share` | 每股未分配利润 | balance.retained_profit / 总股本 | GOOD 4.9e-09 | 总股本 = capitalization × 1e4（万股→股） |
| `retained_earnings_per_share` | 每股留存收益 | (盈余公积金 + 未分配利润) / 总股本 | GOOD 4.9e-09 | 留存收益 = surplus_reserve_fund + retained_profit |
| `operating_profit_per_share_ttm` | 每股营业利润TTM | TTM(income.operating_profit) / 总股本 | GOOD 6.0e-09 | TTM = 最新 4 个单季之和 |
| `operating_revenue_per_share_ttm` | 每股营业收入TTM | TTM(income.operating_revenue) / 总股本 | GOOD 6.2e-09 | TTM = 最新 4 个单季之和 |
| `total_operating_revenue_per_share_ttm` | 每股营业总收入TTM | TTM(income.total_operating_revenue) / 总股本 | GOOD 7.2e-09 | TTM = 最新 4 个单季之和 |
| `net_asset_per_share` | 每股净资产 | (归母权益 − 其他权益工具) / 总股本 | GOOD 1.1e-08 | 总股本 = valuation.capitalization × 1e4（单位万股） |
| `operating_revenue_per_share` | 每股营业收入 | 单季 income.operating_revenue / 总股本 | GOOD 1.8e-08 | **单期**口径 |
| `total_operating_revenue_per_share` | 每股营业总收入 | 单季 income.total_operating_revenue / 总股本 | GOOD 1.8e-08 | **单期**口径 |
| `eps_ttm` | 每股收益TTM | net_profit(TTM) / 总股本 | GOOD 1.9e-08 | ⚠ 文档写「归母净利润(TTM)/总股本」，实测分子是 **net_profit**（归母版 maxerr 2.379 ❌） |
| `surplus_reserve_fund_per_share` | 每股盈余公积金 | balance.surplus_reserve_fund / 总股本 | GOOD 3.4e-08 |  |
| `operating_profit_per_share` | 每股营业利润 | 单季 income.operating_profit / 总股本 | GOOD 4.2e-08 | **单期**口径 |
| `net_operate_cash_flow_per_share` | 每股经营活动产生的现金流量净额 | **单季**经营现金流 / 总股本 | GOOD 5.2e-08 | ⚠ 名字含「12 个月」但实测是**单期**（单季版 4.97e-07 ✅，TTM 版 42.2 ❌） |
| `cashflow_per_share_ttm` | 每股现金流量净额，根据当时日期来获取最近变更日的总股本 | TTM(经营 + 投资 + 筹资三项现金流净额) / 总股本 | GOOD 1.7e-07 | 「现金流量净额」是**三项之和**，不是现金流表里现成的 cash_equivalent_increase 字段（后者 maxerr 0.172 ❌） |
| `capital_reserve_fund_per_share` | 每股资本公积金 | balance.capital_reserve_fund / 总股本 | GOOD 2.2e-07 |  |

### basics（26 个通过）—— 财务基础科目（TTM 求和、单期科目、市值）

| 因子 | 中文名 | 已验证公式 | 精度 | 注意事项 |
|---|---|---|---|---|
| `net_interest_expense` | 净利息费用 | 利息支出-利息收入 | EXACT 0.0e+00 |  |
| `administration_expense_ttm` | 管理费用TTM | 计算过去12个月 管理费用 之和 | EXACT 0.0e+00 |  |
| `market_cap` | 市值 | valuation.market_cap × 1e8 | EXACT 0.0e+00 | ⚠ valuation 单位是**亿元**，因子单位是**元** |
| `circulating_market_cap` | 流通市值 | valuation.circulating_market_cap × 1e8 | EXACT 0.0e+00 | 同上，×1e8 |
| `sale_expense_ttm` | 销售费用TTM | 计算过去12个月 销售费用 之和 | EXACT 0.0e+00 |  |
| `net_invest_cash_flow_ttm` | 投资活动现金流量净额TTM | 计算过去12个月 投资活动现金流量净额 之和 | EXACT 8.9e-19 |  |
| `net_operate_cash_flow_ttm` | 经营活动现金流量净额TTM | 计算过去12个月 经营活动产生的现金流量净值 之和 | EXACT 1.7e-18 |  |
| `non_operating_net_profit_ttm` | 营业外收支净额TTM | 营业外收入（TTM） - 营业外支出（TTM） | EXACT 1.1e-17 |  |
| `EBIT` | 息税前利润 | 单季(净利润 + 所得税 + 财务费用) | EXACT 1.9e-17 | ⚠ **单期口径，非 TTM**（文档未写）。TTM 版 maxerr 7.7e+10 ❌ |
| `operating_profit_ttm` | 营业利润TTM | 计算过去12个月 营业利润 之和 | EXACT 4.9e-17 |  |
| `financial_expense_ttm` | 财务费用TTM | 计算过去12个月 财务费用 之和 | EXACT 1.0e-16 |  |
| `net_profit_ttm` | 净利润TTM | 计算过去12个月 净利润 之和 | EXACT 7.2e-14 |  |
| `total_operating_revenue_ttm` | 营业总收入TTM | 计算过去12个月的 营业总收入 之和 | EXACT 7.9e-14 |  |
| `retained_earnings` | 留存收益 | 盈余公积金+未分配利润 | EXACT 8.8e-14 |  |
| `total_operating_cost_ttm` | 营业总成本TTM | 计算过去12个月的 营业总成本 之和 | EXACT 1.6e-13 |  |
| `interest_carry_current_liability` | 带息流动负债 | 流动负债合计 - 无息流动负债 | EXACT 1.9e-13 |  |
| `np_parent_company_owners_ttm` | 归属于母公司股东的净利润TTM | 计算过去12个月 归属于母公司股东的净利润 之和 | EXACT 2.9e-13 |  |
| `total_profit_ttm` | 利润总额TTM | 计算过去12个月 利润总额 之和 | EXACT 3.8e-13 |  |
| `net_finance_cash_flow_ttm` | 筹资活动现金流量净额TTM | 计算过去12个月 筹资活动现金流量净额 之和 | EXACT 4.0e-13 |  |
| `operating_revenue_ttm` | 营业收入TTM | 计算过去12个月的 营业收入 之和 | EXACT 4.2e-13 |  |
| `interest_free_current_liability` | 无息流动负债 | 应付票据+应付账款+预收账款(用 预售款项 代替)+应交税费+应付利息+其他应付款+其他流动负债 | EXACT 7.3e-13 |  |
| `operating_cost_ttm` | 营业成本TTM | 计算过去12个月的 营业成本 之和 | EXACT 1.2e-12 |  |
| `goods_sale_and_service_render_cash_ttm` | 销售商品提供劳务收到的现金 | 计算过去12个月 销售商品提供劳务收到的现金 之和 | EXACT 1.4e-12 |  |
| `net_working_capital` | 净运营资本 | 流动资产 － 流动负债 | EXACT 2.2e-12 |  |
| `sales_to_price_ratio` | 营收市值比 | 1 / ps_ratio (ttm) | GOOD 2.0e-07 |  |
| `cash_flow_to_price_ratio` | 现金流市值比 | 1 / pcf_ratio (ttm) | GOOD 2.8e-06 |  |

### growth（2 个通过）—— 增长率指标

| 因子 | 中文名 | 已验证公式 | 精度 | 注意事项 |
|---|---|---|---|---|
| `net_asset_growth_rate` | 净资产增长率 | **总权益**(当季) / **总权益**(4 个季度前) − 1 | GOOD 3.4e-06 | ⚠ 文档写「三季度前」且未说口径，实测是 **4 个季度前**、且用**总权益**而非归母（归母版平均误差 11.0%） |
| `total_asset_growth_rate` | 总资产增长率 | 总资产(当季) / 总资产(4 个季度前) − 1 | GOOD 4.7e-06 | ⚠ 文档写「总资产_4」，实测为 **4 个季度前**（平均相对误差 0.0004%） |

### quality（46 个通过）—— 财务质量比率（偿债/周转/盈利/现金流）

| 因子 | 中文名 | 已验证公式 | 精度 | 注意事项 |
|---|---|---|---|---|
| `inventory_turnover_days` | 存货周转天数 | 存货周转天数=360/存货周转率 | EXACT 1.1e-10 |  |
| `OperatingCycle` | 营业周期 | 应收账款周转天数+存货周转天数 | EXACT 2.9e-10 |  |
| `account_receivable_turnover_days` | 应收账款周转天数 | 应收账款周转天数=360/应收账款周转率 | GOOD 1.2e-09 |  |
| `accounts_payable_turnover_days` | 应付账款周转天数 | 应付账款周转天数 = 360 / 应付账款周转率 | GOOD 1.3e-09 |  |
| `account_receivable_turnover_rate` | 应收账款周转率 | 即，TTM(营业收入,0)/（AvgQ(应收账款,4,0)+ AvgQ(应收票据,4,0)） | GOOD 1.0e-08 |  |
| `equity_turnover_rate` | 股东权益周转率 | 股东权益 / 营业总收入(TTM) | GOOD 2.8e-08 | ⚠ **文档公式写反**：文档写「营业收入(TTM)/股东权益」，但官方发布的是**倒数**（该写法 corr 为 −0.96；倒数版误差 1.4e-07） |
| `current_ratio` | 流动比率(单季度) | 流动资产合计 / 流动负债合计 | GOOD 5.2e-08 | **含当日最新一期**报表。⚠ 金融类（银行/保险/券商）报表无「流动/非流动」划分，官方对其直接返回 nan（实测覆盖率 67%） |
| `debt_to_tangible_equity_ratio` | 有形净值债务率 | 负债合计/有形净值 其中有形净值=股东权益-无形资产净值，无形资产净值= 商誉+无形资产 | GOOD 5.5e-08 |  |
| `debt_to_equity_ratio` | 产权比率 | 负债合计 / 归属母公司所有者权益合计 | GOOD 5.8e-08 |  |
| `quick_ratio` | 速动比率 | (流动资产合计 − 存货) / 流动负债合计 | GOOD 7.5e-08 | 同 current_ratio 的覆盖率说明 |
| `accounts_payable_turnover_rate` | 应付账款周转率 | TTM(营业成本,0)/（AvgQ(应付账款,4,0) + AvgQ(应付票据,4,0) ） | GOOD 9.5e-08 |  |
| `cash_to_current_liability` | 现金比率 | cash_flow.cash_and_equivalents_at_end / AvgQ(流动负债, 4) | GOOD 1.3e-07 | ⚠ 分子取 **cash_flow 表的期末现金及现金等价物**，**不是** balance.cash_equivalents（货币资金）；分母用 AvgQ 而非期末 |
| `cash_rate_of_sales` | 经营活动产生的现金流量净额与营业收入之比 | 经营活动产生的现金流量净额（TTM） / 营业收入（TTM） | GOOD 1.4e-07 |  |
| `debt_to_asset_ratio` | 债务总资产比 | 负债合计 / 总资产 | GOOD 1.4e-07 | 期末口径（AvgQ 版更差，corr 0.995） |
| `super_quick_ratio` | 超速动比率 | （货币资金+交易性金融资产+应收票据+应收帐款+其他应收款）／流动负债合计 | GOOD 1.5e-07 |  |
| `inventory_turnover_rate` | 存货周转率 | 存货周转率=营业成本（TTM）/AvgQ(存货,4,0) | GOOD 1.9e-07 |  |
| `net_operating_cash_flow_coverage` | 净利润现金含量 | 经营活动产生的现金流量净额/归属于母公司所有者的净利润 | GOOD 1.9e-07 |  |
| `net_operate_cash_flow_to_operate_income` | 经营活动产生的现金流量净额与经营活动净收益之比 | TTM(经营现金流) / (营业总收入(TTM) − 营业总成本(TTM)) | GOOD 2.1e-07 | 分母必须用「营业**总**收入 − 营业**总**成本」；误用营业收入时 maxerr 2.6e-02 |
| `equity_to_asset_ratio` | 股东权益比率 | 股东权益比率=股东权益/总资产 | GOOD 2.2e-07 |  |
| `adjusted_profit_to_total_profit` | 扣除非经常损益后的净利润/利润总额 | 扣除非经常损益后的净利润/利润总额 | GOOD 2.5e-07 |  |
| `long_debt_to_working_capital_ratio` | 长期负债与营运资金比率 | 长期负债与营运资金比率=非流动负债合计/(流动资产合计-流动负债合计) | GOOD 2.8e-07 |  |
| `total_profit_to_cost_ratio` | 成本费用利润率 | 成本费用利润率=利润总额/(营业成本+财务费用+销售费用+管理费用)，以上科目使用的都是TTM的数值 | GOOD 3.5e-07 |  |
| `operating_profit_to_operating_revenue` | 营业利润与营业总收入之比 | 营业利润与营业总收入之比=营业利润（TTM）/营业总收入（TTM） | GOOD 3.8e-07 |  |
| `operating_cost_to_operating_revenue_ratio` | 销售成本率 | 销售成本率=营业成本（TTM）/营业收入（TTM） | GOOD 4.0e-07 |  |
| `current_asset_turnover_rate` | 流动资产周转率TTM | 过去12个月的营业收入/过去12个月的平均流动资产合计 | GOOD 4.3e-07 |  |
| `profit_margin_ttm` | 销售利润率TTM | 营业利润/营业收入 | GOOD 4.8e-07 |  |
| `operating_profit_ratio` | 营业利润率 | 营业利润率=营业利润（TTM）/营业收入（TTM） | GOOD 4.8e-07 |  |
| `net_operate_cash_flow_to_total_current_liability` | 现金流动负债比 | TTM(经营现金流) / AvgQ(流动负债, 4) | GOOD 5.0e-07 | 分母用 **AvgQ**：TTM/AvgQ 误差 5.0e-07 ✅ ｜ TTM/期末 0.193 ｜ 单季/AvgQ 1.24 |
| `gross_income_ratio` | 销售毛利率 | 销售毛利率=(营业收入（TTM）-营业成本（TTM）)/营业收入（TTM） | GOOD 5.1e-07 |  |
| `net_profit_ratio` | 销售净利率 | 售净利率=净利润（TTM）/营业收入（TTM） | GOOD 5.5e-07 |  |
| `net_profit_to_total_operate_revenue_ttm` | 净利润与营业总收入之比 | 净利润与营业总收入之比=净利润（TTM）/营业总收入（TTM） | GOOD 8.3e-07 |  |
| `total_asset_turnover_rate` | 总资产周转率 | 总资产周转率=营业收入(ttm)/总资产 | GOOD 8.6e-07 |  |
| `roe_ttm` | 权益回报率TTM | TTM(归母净利润) / 归母股东权益 | GOOD 9.4e-07 | ⚠ 文档写「净利润/期末股东权益」，实测**分子分母都要用归母口径**（误差 4.4e-07；用净利润/总权益为 0.397 ❌） |
| `MLEV` | 市场杠杆 | 市场杠杆=非流动负债合计/(非流动负债合计+总市值) | GOOD 1.0e-06 |  |
| `non_current_asset_ratio` | 非流动资产比率 | 非流动资产比率=非流动资产合计/总资产 | GOOD 1.1e-06 |  |
| `admin_expense_rate` | 管理费用与营业总收入之比 | 管理费用与营业总收入之比=管理费用（TTM）/营业总收入（TTM） | GOOD 2.3e-06 |  |
| `net_operate_cash_flow_to_asset` | 总资产现金回收率 | 经营活动产生的现金流量净额(ttm) / 总资产 | GOOD 2.4e-06 |  |
| `net_operate_cash_flow_to_total_liability` | 经营活动产生的现金流量净额/负债合计 | 经营活动产生的现金流量净额/负债合计 | GOOD 2.5e-06 |  |
| `roa_ttm` | 资产回报率TTM | 资产回报率=净利润（TTM）/期末总资产 | GOOD 3.1e-06 |  |
| `long_debt_to_asset_ratio` | 长期借款与资产总计之比 | 长期借款与资产总计之比=长期借款/总资产 | GOOD 3.9e-06 |  |
| `long_term_debt_to_asset_ratio` | 长期负债与资产总计之比 | 长期负债与资产总计之比=非流动负债合计/总资产 | GOOD 4.0e-06 |  |
| `cfo_to_ev` | 经营活动产生的现金流量净额与企业价值之比TTM | 经营活动产生的现金流量净额TTM / 企业价值。其中，企业价值=司市值+负债合计-货币资金 | GOOD 4.2e-06 |  |
| `sale_expense_to_operating_revenue` | 营业费用与营业总收入之比 | 营业费用与营业总收入之比=销售费用（TTM）/营业总收入（TTM） | GOOD 4.4e-06 |  |
| `operating_tax_to_operating_revenue_ratio_ttm` | 销售税金率 | 销售税金率=营业税金及附加（TTM）/营业收入（TTM） | GOOD 7.8e-06 |  |
| `financial_expense_rate` | 财务费用与营业总收入之比 | 财务费用（TTM） / 营业总收入（TTM） | GOOD 1.3e-05 |  |
| `intangible_asset_ratio` | 无形资产比率 | 无形资产比率=(无形资产+研发支出+商誉)/总资产 | GOOD 2.7e-05 |  |

### style（3 个通过）—— 风险模型风格因子（CNE5 描述因子）

| 因子 | 中文名 | 已验证公式 | 精度 | 注意事项 |
|---|---|---|---|---|
| `natural_log_of_market_cap` | 对数市值 | 公司的总市值的自然对数。 | GOOD 1.0e-08 |  |
| `average_share_turnover_quarterly` | 季度平均平均月换手率 | ln( Σ₆₃(换手率 ÷ 100) ÷ 3 ) | GOOD 1.2e-07 | ⚠「过去 3 个月平均」= **3 个月度和的均值**，不是 63 日均值（后者恰差 ln(21)=3.0445） |
| `share_turnover_monthly` | 月换手率 | ln( Σ₂₁(换手率 ÷ 100) ) | GOOD 1.3e-07 | ⚠ 官方先把换手率换算成**小数**再取对数；未换算时 maxerr 恒为 ln(100)=4.605171 |


---

## 附：未通过因子

共 19 个（中位口径）。失败原因见 `SUMMARY.md` §四点五。

| 因子 | 族 | 中位相对误差 |
|---|---|---|
| `non_linear_size` | style | 1.55e+04 |
| `size` | style | 28.7 |
| `liquidity` | style | 0.864 |
| `book_to_price_ratio` | style | 0.477 |
| `leverage` | style | 0.403 |
| `Rank1M` | momentum | 0.297 |
| `book_leverage` | style | 0.181 |
| `market_leverage` | style | 0.172 |
| `asset_impairment_loss_ttm` | basics | 0.0983 |
| `ACCA` | quality | 0.0133 |
| `debt_to_assets` | style | 0.0025 |
| `gross_profit_ttm` | basics | 0.00217 |
| `EMAC120` | technical | 0.000683 |
| `single_day_VPT` | momentum | 0.000128 |
| `fifty_two_week_close_rank` | momentum | nan |
| `Price1Y` | momentum | nan |
| `fixed_asset_ratio` | quality | nan |
| `equity_to_fixed_asset_ratio` | quality | nan |
| `average_share_turnover_annual` | style | nan |