# qdata 因子公式静态审计

> 由 `scripts/qdata/audit_formulas.py` 生成（不调用 API）。
> 当前因子 **242** 条；历史快照 `_old_` **10** 条。

## 1. 横截面依赖扫描

**126/242 条（52%）含横截面算子，必须在全市场股票池上校验。**

| 族 | 含横截面 | 总数 |
|---|---|---|
| Alpha101 | 54 | 71 |
| Quality | 51 | 59 |
| Liquidity | 0 | 35 |
| Risk | 0 | 25 |
| Momentum | 0 | 20 |
| Growth | 12 | 15 |
| Value | 8 | 11 |
| Reversal | 1 | 3 |
| Size | 0 | 3 |

### 按算子分组

| 算子 | 条数 | 因子 |
|---|---|---|
| `CrossSectionalRank` | 72 | `ar_ap_to_revenue`、`asset_growth_qoq`、`asset_turnover`、`cash_profit_ratio`、`cash_ratio`、`cfcr`、`delta_asset_turnover`、`delta_cash_ratio`、`delta_current_ratio`、`delta_de`、`delta_gpm`、`delta_inventory_turnover`、`delta_npm`、`delta_opm`、`delta_quick_ratio`、`delta_roa`、`delta_roe`、`dividend_yield_3y_avg`、`eaa`、`eap`、`earnings_cut_to_market`、`ebitda_to_market`、`eps_q`、`eps_ttm`、`eps_y`、`equity_turnover`、`etp5`、`expenses_to_equity_yoy`、`financial_leverage`、`fixed_asset_turnover`、`gpm_q`、`gpm_qoq`、`gpm_ttm`、`gpm_y`、`gross_margin_qoq`、`icr`、`income_tax_yoy`、`inventory_turnover`、`lra_yoy`、`market_value_leverage`、`ncf_to_market`、`np_to_deferred_tax_yoy`、`np_to_fixed_assets_yoy`、`np_to_inventory_yoy`、`np_to_salary_yoy`、`np_to_total_expenses_yoy`、`np_ttm_qoq`、`npm_q`、`npm_q_qoq`、`npm_tsh`、`npm_ttm`、`npm_ttm_qoq`、`npm_y`、`ocf_to_market`、`opm_ttm`、`opm_y`、`opt_tpro`、`pa`、`pegh5`、`receivable_turnover`、`roa_q`、`roa_ttm`、`roa_y`、`sa`、`sales_to_market`、`small_cap_reversal_21d`、`tax_surcharge_yoy`、`yoy_net_asset`、`yoy_ocf`、`yoy_roa`、`yoy_roe`、`yoy_total_asset` |
| `Rank` | 49 | `alpha101_1`、`alpha101_10`、`alpha101_11`、`alpha101_13`、`alpha101_14`、`alpha101_15`、`alpha101_16`、`alpha101_17`、`alpha101_18`、`alpha101_19`、`alpha101_2`、`alpha101_20`、`alpha101_22`、`alpha101_25`、`alpha101_27`、`alpha101_29`、`alpha101_3`、`alpha101_30`、`alpha101_31`、`alpha101_33`、`alpha101_34`、`alpha101_36`、`alpha101_37`、`alpha101_38`、`alpha101_39`、`alpha101_4`、`alpha101_40`、`alpha101_42`、`alpha101_44`、`alpha101_45`、`alpha101_47`、`alpha101_5`、`alpha101_50`、`alpha101_52`、`alpha101_55`、`alpha101_56`、`alpha101_57`、`alpha101_60`、`alpha101_61`、`alpha101_62`、`alpha101_63`、`alpha101_64`、`alpha101_65`、`alpha101_66`、`alpha101_67`、`alpha101_68`、`alpha101_69`、`alpha101_70`、`alpha101_8` |
| `IndNeutralize` | 7 | `alpha101_48`、`alpha101_58`、`alpha101_59`、`alpha101_63`、`alpha101_67`、`alpha101_69`、`alpha101_70` |
| `Scale` | 5 | `alpha101_28`、`alpha101_29`、`alpha101_31`、`alpha101_32`、`alpha101_60` |

> `CrossSectionalRank` 不只出现在 Alpha101：Quality/Growth/Value 大量在原始比值外额外套一层全市场排名。用小样本股验证这些因子**必然 FAIL**，与实现正确性无关 —— 应剥壳后做秩相关检验，或建全市场面板。

## 2. 参数化因子

共 **52** 条带 `params`。

| 因子 | 族 | 参数 |
|---|---|---|
| `MACD` | Momentum | `fast`: 快线周期，默认为 12；`slow`: 慢线周期，默认为 26；`signal`: 信号线周期，默认为 9 |
| `adjusted_sharpe_750d` | Risk | `window`: 窗口天数，默认 750 |
| `alpha_1000d_000300` | Momentum | `window`: 回归窗口天数 |
| `alpha_125d_000300` | Momentum | `window`: 回归窗口天数 |
| `alpha_1320d_000001` | Momentum | `window`: 回归窗口天数 |
| `alpha_250d_000300` | Momentum | `window`: 回归窗口天数 |
| `alpha_500d_000300` | Momentum | `window`: 回归窗口天数 |
| `alpha_528d_000001` | Momentum | `window`: 回归窗口天数 |
| `alpha_792d_000001` | Momentum | `window`: 回归窗口天数 |
| `amount_ma_20d` | Liquidity | `window`: 移动平均窗口，默认为 20 |
| `avg_turnover_10d` | Liquidity | `window`: 窗口天数 |
| `avg_turnover_20d` | Liquidity | `window`: 窗口天数 |
| `avg_turnover_5d` | Liquidity | `window`: 窗口天数 |
| `beta_1000d_000300` | Risk | `window`: 滚动窗口天数 |
| `beta_125d_000300` | Risk | `window`: 滚动窗口天数 |
| `beta_1320d_000001` | Risk | `window`: 滚动窗口天数 |
| `beta_250d_000300` | Risk | `window`: 滚动窗口天数 |
| `beta_500d_000300` | Risk | `window`: 滚动窗口天数 |
| `beta_60d_000300` | Risk | `window`: 滚动窗口天数 |
| `beta_consistency_1320d_000300` | Risk | `window`: 回归和滚动窗口天数 (默认 1320，约60个月) |
| `days_beyond_upper_lower_21d` | Risk | `window`: 计算窗口 |
| `dea` | Momentum | `fast`: 快线周期，默认为 12；`slow`: 慢线周期，默认为 26；`signal`: 信号线周期，默认为 9 |
| `dif` | Momentum | `fast`: 快线周期，默认为 12；`slow`: 慢线周期，默认为 26 |
| `ma_20d` | Momentum | `window`: 移动平均窗口，默认为 20 |
| `peg_252d` | Growth | `window`: EPS增长率计算窗口，默认 252天 |
| `price_dist` | Reversal | `window`: 移动平均窗口，默认为 0（不计算移动平均） |
| `price_position_ir_60d` | Momentum | `window`: 窗口天数，默认 60 |
| `return_126d` | Momentum | `window`: 窗口天数 |
| `return_21d` | Momentum | `window`: 窗口天数 |
| `return_252d` | Momentum | `window`: 窗口天数 |
| `return_42d` | Momentum | `window`: 窗口天数 |
| `return_5d` | Momentum | `window`: 窗口天数 |
| `return_63d` | Momentum | `window`: 窗口天数 |
| `return_std_126d` | Risk | `month`: 月数 (如 1 表示 21 个交易日) |
| `return_std_21d` | Risk | `month`: 月数 (如 1 表示 21 个交易日) |
| `return_std_252d` | Risk | `month`: 月数 (如 1 表示 21 个交易日) |
| `return_std_42d` | Risk | `month`: 月数 (如 1 表示 21 个交易日) |
| `return_std_63d` | Risk | `month`: 月数 (如 1 表示 21 个交易日) |
| `roe_ttm` | Quality | `lag`: 交易日滞后天数 |
| `roe_ttm_lag63d` | Quality | `lag`: 交易日滞后天数 |
| `roe_y` | Quality | `lag`: 交易日滞后天数 |
| `rsi` | Reversal | `period`: RSI 周期 |
| `rsrs` | Momentum | `regress_window`: 回归窗口，默认为 18；`zscore_window`: Z-Score 标准化窗口，默认为 200 |
| `sharpe_60d` | Risk | `window`: 窗口天数 |
| `sharpe_750d` | Risk | `window`: 窗口天数 |
| `sigma_1320d_000001` | Risk | `window`: 回归和滚动窗口天数 |
| `sigma_1320d_000300` | Risk | `window`: 回归和滚动窗口天数 |
| `small_cap_reversal_21d` | Reversal | `window`: 累计收益窗口天数 |
| `sum_abs_rtn_amount_20d` | Liquidity | `window`: 滚动窗口，默认为 20 |
| `volume_alpha_300d_000001` | Liquidity | `window`: 回归窗口天数 (默认 300)；`sum_window`: 成交量滚动求和窗口 (默认 5) |
| `volume_alpha_300d_000300` | Liquidity | `window`: 回归窗口天数 (默认 300)；`sum_window`: 成交量滚动求和窗口 (默认 5) |
| `volume_beta_120d_000300` | Risk | `window`: 回归窗口天数 (默认 120)；`sum_window`: 成交量滚动求和窗口 (默认 5) |

## 3. 直通（passthrough）因子

共 **8** 条，qdata 直接用预计算的 `lake.financial_derivative.*` 字段，预计**结构性不可复现**。

| 因子 | 族 | 文档公式 |
|---|---|---|
| `current_ratio` | Quality | CurrentRatio = CurrentAssets / CurrentLiabilities |
| `debt_asset_ratio` | Quality | DebtAssetRatio = TotalDebt / TotalAssets |
| `gpm_qoq` | Quality | GPM = (Revenue_TTM - Cost_TTM) / Revenue_TTM Growth = GPM_t / GPM_{prev_report} - 1   # 财报 |
| `npm_ttm_qoq` | Quality | NPM = NetProfit_TTM / OperatingRevenue_TTM Growth = NPM_t / NPM_{prev_report} - 1   # 财报披露 |
| `quick_ratio` | Quality | QuickRatio = (CurrentAssets - Inventory) / CurrentLiabilities |
| `roe_ttm` | Quality | ROE = NetProfit_Parent / TotalEquity |
| `roe_ttm_lag63d` | Quality | ROE = NetProfit_Parent / TotalEquity |
| `roe_y` | Quality | ROE = NetProfit_Parent / TotalEquity |

## 4. 与聚宽体系交叉验证

qdata **242** 条 / 聚宽 **276** 条 / **同名仅 7 条**。

| 因子 | qdata 族 | qdata 公式 | 聚宽类别 | 聚宽公式 |
|---|---|---|---|---|
| `current_ratio` | Quality | CurrentRatio = CurrentAssets / CurrentLiabilities | quality | 流动比率=流动资产合计/流动负债合计 |
| `eps_ttm` | Quality | Factor = CrossSectionalRank(BasicEPS) | pershare | 过去12个月归属母公司所有者的净利润（TTM）除以总股本 |
| `financial_leverage` | Quality | FinancialLeverage = TotalAssets / TotalShareholderEquity Factor = CrossSectional | style_pro |  |
| `quick_ratio` | Quality | QuickRatio = (CurrentAssets - Inventory) / CurrentLiabilities | quality | 速动比率=(流动资产合计-存货)/ 流动负债合计 |
| `roa_ttm` | Quality | ROA = NetProfit / TotalAssets Factor = CrossSectionalRank(ROA) | quality | 资产回报率=净利润（TTM）/期末总资产 |
| `roe_ttm` | Quality | ROE = NetProfit_Parent / TotalEquity | quality | 权益回报率=净利润（TTM）/期末股东权益 |
| `size` | Size | Size = -log(TotalShares * ClosePrice / 1e6)  该因子值为负对数形式，值越小表示市值越大。 | style | 1•natural_log_of_market_cap |

**结论：同名不代表同口径** —— 不可跨体系套用实现或符号。典型：`size` 在 qdata 是 `−log(市值)`（负对数，值越小市值越大），聚宽是 `natural_log_of_market_cap`（正对数），**符号相反**；`roa_ttm`/`eps_ttm` 在 qdata 额外套了 `CrossSectionalRank`。
