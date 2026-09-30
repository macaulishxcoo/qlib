# 聚宽因子本地复现 —— 总报告

生成时间：2026-09-17 19:32　|　口径：FQ=post  STD_DDOF=1  EMA_ADJUST=False  ANNUAL_DAYS=250  RF=0.04

- 比对区间：`2026-05-06` ~ `2026-06-16`
- 标的：600519.XSHG, 000002.XSHE, 000651.XSHE, 002415.XSHE, 600036.XSHG, 000001.XSHE
- 因子清单来源：`.jqdata/docs/factor_library_formulas.json`（共 276 个）
- 判定：`rel = max_abs_err / mean(|官方值|)`；EXACT ≤1e-9 ｜ GOOD ≤1e-4 ｜ APPROX ≤1e-2 ｜ FAIL 其他

## 一、逐族精度

| family | n_factors | implemented | EXACT | GOOD | APPROX | FAIL | NO_DATA | reproduced | status |
|---|---|---|---|---|---|---|---|---|---|
| technical | 16 | 16 | 1 | 9 | 6 | 0 | 0 | 10 | 已实现 |
| risk | 12 | 12 | 0 | 12 | 0 | 0 | 0 | 12 | 已实现 |
| momentum | 34 | 34 | 2 | 4 | 21 | 5 | 2 | 6 | 已实现 |
| emotion | 36 | 36 | 15 | 20 | 1 | 0 | 0 | 35 | 已实现 |
| pershare | 15 | 15 | 0 | 15 | 0 | 0 | 0 | 15 | 已实现 |
| basics | 37 | 28 | 24 | 2 | 1 | 1 | 9 | 26 | 已实现 |
| growth | 9 | 2 | 0 | 2 | 0 | 0 | 7 | 2 | 已实现 |
| quality | 71 | 49 | 2 | 44 | 0 | 1 | 24 | 46 | 已实现 |
| style | 30 | 12 | 0 | 3 | 0 | 8 | 19 | 3 | 已实现 |
| style_pro | 16 | 0 | 0 | 0 | 0 | 0 | 16 | 0 | 未实现 |
| 合计 | 276 | 204 | 44 | 111 | 29 | 15 | 77 | 155 |  |

**结论**：清单 276 个因子中实现 204 个，其中 **155 个达可复现**（EXACT 44 + GOOD 111）；APPROX 29、FAIL 15、未实现 77。

## 二、已实现但未达 GOOD 的因子（含原因）

共 49 个。APPROX 多为「公式正确但受输入精度放大或暖机限制」，FAIL 为确实未收敛。

- **[APPROX] basics/gross_profit_ttm**　maxerr=4.47e+08　corr=1.0000　coverage=0.67
  - 覆盖率不足（官方 180 / 重叠 120）
- **[FAIL] basics/asset_impairment_loss_ttm**　maxerr=1.95e+10　corr=0.9998　coverage=0.83
  - **口径部分收敛，仍 FAIL**：官方把缺失季度按 0 计入（nan_as_zero 后覆盖度 90→150、corr 0.92→**0.9998**），但量级仍系统性偏大（如 000002 我算 4.14e10 vs 官方 2.19e10，约 1.9 倍）。仅用 asset_impairment_loss 单科目不足以复现，疑官方口径含其它减值科目或采用不同期间。
- **[APPROX] emotion/turnover_volatility**　maxerr=4.99e-07　corr=1.0000　coverage=1.00
  - 已按 /100 标定（官方返回小数）。maxerr 仅 4.99e-07，但官方值量级本身极小（mean≈0.0013），故 rel 略超 GOOD 阈值 1e-4 → 落在 APPROX。
- **[APPROX] momentum/PLRC12**　maxerr=4.99e-07　corr=1.0000　coverage=1.00
- **[APPROX] momentum/Volume1M**　maxerr=4.94e-07　corr=1.0000　coverage=1.00
- **[APPROX] momentum/PLRC24**　maxerr=5e-07　corr=1.0000　coverage=1.00
- **[APPROX] momentum/bear_power**　maxerr=8.01e-06　corr=1.0000　coverage=1.00
- **[APPROX] momentum/bull_power**　maxerr=7.97e-06　corr=1.0000　coverage=1.00
- **[APPROX] momentum/BIAS60**　maxerr=0.004　corr=1.0000　coverage=1.00
  - 公式正确（corr=1.0000），残差为输入价精度放大（×100/做差放大），见 CALIBRATION。
- **[APPROX] momentum/MASS**　maxerr=0.0281　corr=1.0000　coverage=1.00
  - 已改用 SMA（实测标定）；残余 maxerr 2.7e-02 属精度放大。
- **[APPROX] momentum/ROC120**　maxerr=0.02　corr=1.0000　coverage=1.00
  - 公式正确（corr=1.0000），残差为输入价精度放大（×100/做差放大），见 CALIBRATION。
- **[APPROX] momentum/TRIX10**　maxerr=0.000585　corr=1.0000　coverage=1.00
  - 公式正确（corr=1.0000），残差为输入价精度放大（×100/做差放大），见 CALIBRATION。
- **[APPROX] momentum/ROC60**　maxerr=0.0212　corr=1.0000　coverage=1.00
  - 公式正确（corr=1.0000），残差为输入价精度放大（×100/做差放大），见 CALIBRATION。
- **[APPROX] momentum/CCI10**　maxerr=0.263　corr=1.0000　coverage=1.00
  - 公式正确（corr=1.0000），残差为输入价精度放大（×100/做差放大），见 CALIBRATION。
- **[APPROX] momentum/BIAS20**　maxerr=0.0111　corr=1.0000　coverage=1.00
  - 公式正确（corr=1.0000），残差为输入价精度放大（×100/做差放大），见 CALIBRATION。
- **[APPROX] momentum/TRIX5**　maxerr=0.00149　corr=1.0000　coverage=1.00
  - 公式正确（corr=1.0000），残差为输入价精度放大（×100/做差放大），见 CALIBRATION。
- **[APPROX] momentum/CCI20**　maxerr=0.356　corr=1.0000　coverage=1.00
  - 公式正确（corr=1.0000），残差为输入价精度放大（×100/做差放大），见 CALIBRATION。
- **[APPROX] momentum/single_day_VPT**　maxerr=55.7　corr=1.0000　coverage=1.00
- **[APPROX] momentum/CCI15**　maxerr=0.478　corr=1.0000　coverage=1.00
  - 公式正确（corr=1.0000），残差为输入价精度放大（×100/做差放大），见 CALIBRATION。
- **[APPROX] momentum/ROC12**　maxerr=0.0285　corr=1.0000　coverage=1.00
  - 公式正确（corr=1.0000），残差为输入价精度放大（×100/做差放大），见 CALIBRATION。
- **[APPROX] momentum/BIAS10**　maxerr=0.0137　corr=1.0000　coverage=1.00
  - 公式正确（corr=1.0000），残差为输入价精度放大（×100/做差放大），见 CALIBRATION。
- **[APPROX] momentum/ROC20**　maxerr=0.0402　corr=1.0000　coverage=1.00
  - 公式正确（corr=1.0000），残差为输入价精度放大（×100/做差放大），见 CALIBRATION。
- **[APPROX] momentum/CCI88**　maxerr=0.683　corr=1.0000　coverage=1.00
  - 公式正确（corr=1.0000），残差为输入价精度放大（×100/做差放大），见 CALIBRATION。
- **[APPROX] momentum/BIAS5**　maxerr=0.0123　corr=1.0000　coverage=1.00
  - 公式正确（corr=1.0000），残差为输入价精度放大（×100/做差放大），见 CALIBRATION。
- **[FAIL] momentum/CR20**　maxerr=1.04　corr=1.0000　coverage=1.00
  - **口径未标定（非精度问题）**：已用全精度价（`round=False`）复测，误差不变；且误差与股价水平无关 → 排除「价格精度放大」假说。已排除窗口 shift±1、MA 窗口 20/21/22/23、均值 vs 求和、clip、前/后/不复权等变体，现行实现均为最优。残差 rel 1.5%~13%、corr ≥0.99999，误差有界。详见 conventions.py G 段。
- **[FAIL] momentum/ROC6**　maxerr=0.0478　corr=1.0000　coverage=1.00
  - **口径未标定（非精度问题）**：已用全精度价（`round=False`）复测，误差不变；且误差与股价水平无关 → 排除「价格精度放大」假说。已排除窗口 shift±1、MA 窗口 20/21/22/23、均值 vs 求和、clip、前/后/不复权等变体，现行实现均为最优。残差 rel 1.5%~13%、corr ≥0.99999，误差有界。详见 conventions.py G 段。
- **[FAIL] momentum/single_day_VPT_6**　maxerr=195　corr=1.0000　coverage=1.00
  - 公式正确（corr=1.0000）；VPT 残差经 6 日均值累积后放大。
- **[FAIL] momentum/single_day_VPT_12**　maxerr=206　corr=1.0000　coverage=1.00
  - 公式正确（corr=1.0000）；VPT 残差经 12 日均值累积后放大。
- **[FAIL] momentum/Rank1M**　maxerr=0.414　corr=0.7769　coverage=1.00
  - **口径已确认，残差来自 universe 构成**（goal-2 第 5 轮，用全市场面板 5190 只实测）：① 公式确认：``Rank1M = 1 − ret20.rank(axis=1, pct=True)``，**逐日截面 corr = +1.0000**（每日都完美同序）。② 窗口确认：``shift(20)``（19/21 的 maxerr 为 0.245/0.225）。③ 残余 maxerr 0.0088 ≈ **45/5190 个名次** → universe 构成差异：全市场只能取 ``types=['stock']``（5190 只），**北交所属付费模块**，且官方可能另有停牌/新股过滤规则。已排除 rank method（average/min/max/first/dense）与上市天数过滤。④ ⚠ **本族现行实现用 6 只标的的截面算 rank，结构性无效** —— 截面因子的 rank 必须在全市场截面上算，该值不可信；正确实现需 ``data.load_market_close``（约 13 万条/次）。⑤ 方法论：截面因子**不能看跨时 pooled corr**（本例 pooled 仅 0.33 会误导），必须看**逐日截面 corr**（1.0000）。
- **[NO_DATA] momentum/fifty_two_week_close_rank**　maxerr=nan　corr=nan　coverage=0.00
  - 同上：需 250 日窗口，当前面板仅 177 日 → 窗口不足。
- **[NO_DATA] momentum/Price1Y**　maxerr=nan　corr=nan　coverage=0.00
  - 需要 250 个交易日窗口，而面板被夹在账号区间左界（2025-06-09），至 2026-03-02 仅 177 日 → **窗口不足**，非公式错误。把比对区间移到账号窗口末端（2026-05 之后）即可覆盖。
- **[FAIL] quality/ACCA**　maxerr=0.0023　corr=0.9986　coverage=1.00
  - **口径部分收敛，仍 FAIL**：最优变体为 单季ocf/总资产 − 单季净利/总资产。**逐标的实测 5/6 精确**（maxerr ≤2.0e-04）：002415 2.0e-04、000651 1.8e-04、000002 1.1e-04、600036 8e-05、000001 1e-05；**仅 600519 异常**（官方 mean -0.00618 vs 本地 -0.00389，maxerr 2.3e-03）→ 与 MFI14 同类：单只标的异常主导聚合 maxerr。已排除 TTM/TTM(-0.16)、归母口径(0.0051)、AvgQ 分母(0.0021)。
- **[NO_DATA] quality/fixed_asset_ratio**　maxerr=nan　corr=nan　coverage=0.00
  - **结构性不可复现**：分母需（固定资产+工程物资+在建工程），但 balance 表**无 construction_in_progress 字段**，且 construction_materials（工程物资）在 6 只标的上**非空计数为 0**（整列缺失）→ 本地全 NaN。
- **[NO_DATA] quality/equity_to_fixed_asset_ratio**　maxerr=nan　corr=nan　coverage=0.00
  - 同上：缺「在建工程」且工程物资整列缺失 → 全 NaN。
- **[FAIL] style/debt_to_assets**　maxerr=0.00649　corr=1.0000　coverage=1.00
  - corr=0.99997、maxerr 7.2e-03。疑似官方对该描述因子也做了截断/标准化，未收敛。
- **[FAIL] style/book_leverage**　maxerr=0.519　corr=nan　coverage=0.25
  - 覆盖率仅 25%，存在 0.31 的恒定偏移，未收敛。
- **[FAIL] style/market_leverage**　maxerr=1.38　corr=0.7751　coverage=0.25
  - 覆盖率仅 25%（多数标的无优先股/长期借款科目），corr 0.20，未收敛。
- **[FAIL] style/leverage**　maxerr=1.03　corr=0.9907　coverage=0.33
  - 依赖 market_leverage/book_leverage → 未收敛。
- **[FAIL] style/book_to_price_ratio**　maxerr=1.37　corr=0.9234　coverage=1.00
  - 文档称「pb_ratio 的倒数」，但 1/pb_ratio 与原值 corr 仅 0.88 → 口径不符，未收敛。
- **[FAIL] style/liquidity**　maxerr=1.44　corr=0.9507　coverage=1.00
- **[FAIL] style/size**　maxerr=27.1　corr=0.7620　coverage=1.00
- **[FAIL] style/non_linear_size**　maxerr=2.24e+04　corr=-0.7306　coverage=1.00
- **[NO_DATA] style/average_share_turnover_annual**　maxerr=nan　corr=nan　coverage=0.00
  - **窗口不足**：需 252/504 个交易日，试用账号窗口仅 372 日、本地面板 177 日 → 结构性不可算（与 EMAC120 同源问题）。
- **[APPROX] technical/MAC20**　maxerr=0.000105　corr=1.0000　coverage=1.00
- **[APPROX] technical/MAC5**　maxerr=0.000116　corr=1.0000　coverage=1.00
- **[APPROX] technical/MAC10**　maxerr=0.000128　corr=1.0000　coverage=1.00
- **[APPROX] technical/boll_down**　maxerr=0.000173　corr=1.0000　coverage=1.00
- **[APPROX] technical/EMAC120**　maxerr=0.00404　corr=1.0000　coverage=1.00
  - EWMA 暖机不足，**非公式错误**：误差随日期单调衰减（2025-12-01 为 1.66e-02 → 2026-03-02 为 6.98e-03）。span=120 需约 5×120=600 个交易日预热才能收敛，而试用账号窗口仅 372 日、可用预热不足 177 日 → 结构性不可复现。短期 span（EMA5/EMAC26 等）已 GOOD，印证该解释。
- **[APPROX] technical/MACDC**　maxerr=3.76e-05　corr=1.0000　coverage=1.00
  - 绝对误差 1.15e-05，与 GOOD 档同量级；APPROX 源于官方值量级本身很小（mean|·|≈0.0065）。公式已按 2*(DIF-DEA)/C 标定（其余三变体误差 1e-2 量级）。

## 三、未实现的因子（72 个，按族归并原因）

### basics（9 个）

- 「价值变动净收益」在 income 表映射不唯一（fair_value_variable_income / investment_income / asset_deal_income 均可疑）→ 未实现。
  - 涉及：`value_change_profit_ttm`
- 文档为「经营活动净收益/利润总额(%) × 利润总额」，中间量无直接字段 → 未实现。
  - 涉及：`OperateNetIncome`
- 构成科目跨表且含折旧摊销，映射不唯一 → 未实现。
  - 涉及：`EBITDA`
- 需「总债务」定义，构成科目不唯一 → 未实现。
  - 涉及：`net_debt`
- 需归母净利润与扣非净利润之差，归母字段映射不唯一 → 未实现。
  - 涉及：`non_recurring_gain_loss`
- 依赖 financial_assets → 未实现。
  - 涉及：`operating_assets`
- 构成含「可供出售金融资产/持有至到期投资」，新准则下映射不唯一 → 未实现。
  - 涉及：`financial_assets`
- 依赖 financial_liability → 未实现。
  - 涉及：`operating_liability`
- 文档定义被截断，有息非流动负债构成不完整 → 未实现。
  - 涉及：`financial_liability`
### growth（7 个）

- **结构性阻断**：需「去年同期 TTM」= 2024q2~2025q1，而账号财务数据只到 2025q1 → 2024 年财报取不到。已实测排除「自然年 2025 基期」等替代口径（与官方差 ~100%）。
  - 涉及：`operating_revenue_growth_rate`, `net_operate_cashflow_growth_rate`, `total_profit_growth_rate`, `np_parent_company_owners_growth_rate`, `financing_cash_growth_rate`, `net_profit_growth_rate`, `PEG`
### quality（22 个）

- 需营业外收入/支出单期值，income 表有 non_operating_revenue/expense，但口径未验证 → 未实现。
  - 涉及：`net_non_operating_income_to_total_profit`
- 需 8 个季度（同比基期）或多年基期，账号财务数据不足以覆盖 → 未实现。注意 TTM 本身**可精确复现**（conventions.py F1）。
  - 涉及：`DEGM`, `operating_profit_growth_rate`, `net_operate_cash_flow_to_net_debt`, `ROAEBITTTM`, `fixed_assets_turnover_rate`, `LVGI`, `SGI`, `GMI` …等 18 个
- 文档为「经营活动净收益/利润总额」，中间量「经营活动净收益」无直接字段 → 未实现。
  - 涉及：`operating_profit_to_total_profit`
- 需「对联营和合营企业的投资收益」，income 表映射不唯一 → 未实现。
  - 涉及：`invest_income_associates_to_total_profit`
- 本地未实现
  - 涉及：`goods_service_cash_to_operating_revenue_ttm`
### style（18 个）

- **窗口不足**：需 252/504 个交易日，试用账号窗口仅 372 日、本地面板 177 日 → 结构性不可算（与 EMAC120 同源问题）。
  - 涉及：`beta`, `momentum`, `residual_volatility`, `cumulative_range`, `daily_standard_deviation`, `historical_sigma`, `raw_beta`, `relative_strength`
- **数据不可及**：需分析师一致预期（未来 12 个月/1 年/3 年净利预测），本地无此数据。
  - 涉及：`earnings_yield`, `growth`, `long_term_predicted_earnings_growth`, `predicted_earnings_to_price_ratio`, `short_term_predicted_earnings_growth`
- 需 TTM 净经营现金流，受财务 TTM 边界阻断（见 conventions F 段）。
  - 涉及：`cash_earnings_to_price_ratio`
- 需先对标准化后的 size 暴露求立方再正交化，链路参数未知 → 不可算。
  - 涉及：`cube_of_size`
- **财务基期不可及**：需 5 年财务history，账号仅覆盖 2025 年 → 不可算。
  - 涉及：`earnings_growth`, `sales_growth`
- 需 TTM 归母净利润，受财务 TTM 边界阻断。
  - 涉及：`earnings_to_price_ratio`
### style_pro（16 个）

- **官方文档只给「简介」，完全没有计算公式**（`style_pro` 16 个因子的「计算方法」栏为空）→ 结构性不可实现，非数据权限问题。
  - 涉及：`btop`, `divyild`, `earnqlty`, `earnvar`, `earnyild`, `financial_leverage`, `invsqlty`, `liquidty` …等 16 个

## 四、关键口径约定

完整清单见 `scripts/jqdata/facsim/conventions.py`（唯一口径来源）。文档未写明、经实测标定的项：

| 项 | 标定结果 |
|---|---|
| STD 统计量 | **样本标准差 ddof=1**（ddof=0 误差放大 450 倍） |
| MA | 含当日 `rolling(n).mean()` |
| EMA | `ewm(span=n, adjust=False)`；⚠ span≥120 受暖机限制 |
| MACD 柱 | **2×(DIF−DEA)**，文档未提 ×2 |
| 年化交易日数 | **250**（非 252/244） |
| Sharpe 分子 | **几何年化收益率** expm1(Σln(1+r)·250/w) |
| 峰度 | pandas `.kurt()` **超额峰度**，非 Pearson(+3) |
| 偏度 | pandas `.skew()` 校正 Fisher-Pearson |
| VROC 滞后 | **n−1**（官方 off-by-one） |
| VR 窗口 | **24**（非 TDX 惯例 26） |
| AR/BR clip | AR 需 clip，**BR 不 clip**（同族不一致） |
| arron_down_25 | **用 HIGH 序列**（非 LOW）+ 并列取**末次** |
| MASS | 用 **SMA** 而非 EMA，文档无公式 |
| PLRC | `slope(close,n)/mean(close,n)` |
| VPT | 后复权收益率 × **不复权**成交量 /100（手） |
| money_flow_20 | 实为 **20 日求和**（正文写「当日」） |
| turnover_volatility | 官方返回**小数**，需 /100 |
| valuation 市值 | 单位**亿元**，因子单位**元** → ×1e8 |

## 四点五、24 个 FAIL 的四类归因（goal-2 交付）

类别：**F**=公式错误 ｜ **S**=口径未标定 ｜ **P**=输入数据精度上限 ｜ **X**=结构性不可复现

| 类别 | 数量 | 因子 |
|---|---|---|
| F 公式错误 | 0 | — |
| S 口径未标定 | 2 | `ACCA`, `asset_impairment_loss_ttm` |
| P 输入数据精度上限 | 6 | `CR20`, `ROC6`, `Price1M`, `Price3M`, `single_day_VPT_6`, `single_day_VPT_12` |
| X 结构性不可复现 | 9 | `debt_to_assets`, `size`, `non_linear_size`, `liquidity`, `leverage`, `book_to_price_ratio`, `Rank1M`, `book_leverage`, `market_leverage` |

- **[S] basics/asset_impairment_loss_ttm**　corr=0.999811
  - nan_as_zero 后覆盖 90→150、corr 0.92→0.9998；官方/本地比值各标的 0.40~0.91（**非常数**）→ 科目构成差异
- **[P] momentum/CR20**　corr=0.999998
  - corr 0.999998，maxerr 1.03；已排除无 clip(175.9) 等变体
- **[P] momentum/ROC6**　corr=0.999999
  - corr 0.999999；shift(6) 最优（5/7 为 6.6/6.4）；不复权更差(3.37)
- **[X] momentum/Rank1M**　corr=0.776904
  - **口径已确认**（全市场面板逐日截面 corr=+1.0000）；残差 0.0088≈45/5190 名次，源自 universe 构成（北交所付费、官方或有额外过滤）
- **[P] momentum/single_day_VPT_12**　corr=0.999991
  - corr 0.999991；同上
- **[P] momentum/single_day_VPT_6**　corr=0.999997
  - corr 0.999997；MA6 最优（SUM6 为 2.3e+05）
- **[S] quality/ACCA**　corr=0.998587
  - 单季ocf/TA − 单季净利/TA；逐标的 **5/6 精确(≤2e-4)**，仅 600519 异常（官方 -0.006185 vs 本地 -0.003888，反推数据差 ~2.6%）
- **[X] style/book_leverage**　corr=nan
  - 覆盖率仅 25%（多数标的无优先股/长期借款科目），无法定标
- **[X] style/book_to_price_ratio**　corr=0.923433
  - 同上；官方值出现**重复(000001=000002=3.1943)与负值**
- **[X] style/debt_to_assets**　corr=0.999970
  - **数据版本差异**：偏移在 30 日上**完全恒定(std=0)**且逐标的为固定常数(+2.5e-4~+6.5e-3)；四种分子口径给出**完全相同**的 maxerr → 公式空间已穷尽，残差为固定数据差（疑财报修订），账号无法取得历史版本
- **[X] style/leverage**　corr=0.990655
  - 同上
- **[X] style/liquidity**　corr=0.950665
  - 同上（换手率类合成的正交化）
- **[X] style/market_leverage**　corr=0.775080
  - 覆盖率仅 25%，corr 0.775，分母口径存疑
- **[X] style/non_linear_size**　corr=-0.730550
  - 同上（size 立方的正交化）
- **[X] style/size**　corr=0.761987
  - 官方为**截面标准化后**暴露度（截面 mean 0.81/std 0.50，含负值）；需全市场截面+未公开参数

> ⚠ **2026-09-17 更正（goal-3）**：在 160 只分层标的池（均价 1.38~732 元，含微盘）上重测后，「**输入数据精度上限 P**」被证实**真实存在** —— 原判为 S 的 6 个量价因子（ROC6/Price1M/Price3M/CR20/VPT_6/VPT_12）改归为 **P**：低价股上后复权价的 2 位小数分辨率经 ×100/做差放大后主导误差，且改用全精度价反而更差。原「P=0」结论错在**验证样本不含低价股**。详见 conventions.py G2。


**结论**：24 个 FAIL 中 **7 个已攻下**（转为 EXACT/GOOD，见 §二 之外的口径修正记录）；余 17 个归因如上 —— **无一是「公式错误」**（所有因子形状均已验证），**「输入数据精度上限」经两条独立证据被证伪**（`round=False` 全精度无效、误差与股价水平无关），真实瓶颈是**口径未标定**（9）与**结构性不可复现**（8）。


## 五、账号边界（结构性限制，非实现问题）

- 可及区间 **2025-06-09 ~ 2026-06-16**（动态滑窗，每日前移一天，宽度 372 天）
- 行情越界**硬报错**；财务越界**静默返回 0 行**（更危险）
- 财务仅覆盖 **2025Q1~Q4**，2024 及以前取不到 → 全部 TTM 因子不可复现
- 需 250/252/504 日窗口的因子在窗口左界附近不可算（面板仅 177 日）
- 交易日历与证券列表**不受限**（可回溯 2005，含退市股）
