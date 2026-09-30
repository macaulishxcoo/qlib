# qdata.cc 因子本地复现 —— 总汇总

> 判定口径：**已沉淀窗口**（`--settle-days 30`），见 `CONVENTIONS.md` §G2。
> 库内当前因子 **242** 个；**已判定 241** 个（有明确结论）；**通过 180 个（占已判定 74.7%，占库内 74.4%）**。
> 另有 1 个已跑但 NO_DATA（未实现 / 无重叠样本），未覆盖 0 个。

> ⚠️ **判据存疑**：1 条因子的结果由**不合适的判据**得出（其中 0 条当前记为「通过」）。实测已确认这类因子的官方值是 `rank/N`（如 `roa_y` N=5545、`asset_turnover` N=5430，min=1/N、max=1.0、全互异），**在 6 只样本股上不可能复现**。
> ⇒ **保守通过数 = 180**（剔除判据存疑项）。这些因子必须用 `xs_compare.py` 在全市场重跑才能定论。

## 1. 总账

| 指标 | 值 |
|---|---|
| 库内因子总数 | 242 |
| 已判定（有明确结论） | 241 |
| 已跑但 NO_DATA | 1 |
| 未覆盖 | 0 |
| EXACT | 120 |
| GOOD | 60 |
| APPROX | 23 |
| FAIL | 38 |
| NO_DATA | 1 |
| **通过（EXACT+GOOD）** | **180** |

## 2. 按族汇总

| 族 | 库内 | 已判定 | 覆盖率 | EXACT | GOOD | APPROX | FAIL | NO_DATA | 通过率 |
|---|---|---|---|---|---|---|---|---|---|
| Alpha101 | 71 | 70 | 99% | 36 | 13 | 7 | 14 | 1 | 70% |
| Quality | 59 | 59 | 100% | 23 | 13 | 8 | 15 | 0 | 61% |
| Liquidity | 35 | 35 | 100% | 22 | 13 | 0 | 0 | 0 | 100% |
| Risk | 25 | 25 | 100% | 14 | 11 | 0 | 0 | 0 | 100% |
| Momentum | 20 | 20 | 100% | 13 | 7 | 0 | 0 | 0 | 100% |
| Growth | 15 | 15 | 100% | 3 | 1 | 7 | 4 | 0 | 27% |
| Value | 11 | 11 | 100% | 4 | 1 | 1 | 5 | 0 | 45% |
| Reversal | 3 | 3 | 100% | 3 | 0 | 0 | 0 | 0 | 100% |
| Size | 3 | 3 | 100% | 2 | 1 | 0 | 0 | 0 | 100% |

## 3. 未通过因子

| 因子 | 族 | verdict_med | n_overlap | max_abs_err | med_rel_err | corr | note |
|---|---|---|---|---|---|---|---|
| `alpha101_61` | Alpha101 | APPROX | 6.0 | nan | nan | 0.930745 | §5.6 离散输出（±1）；分档一致率 0.96 接近 |
| `alpha101_62` | Alpha101 | APPROX | 6.0 | nan | nan | 0.945507 | §5.6 离散输出（±1）；分档一致率 0.98 接近 |
| `alpha101_34` | Alpha101 | APPROX | 33128.0 | 0.7564 | 0.9947 | 0.994665 | 口径未标定（算子统计量定义） |
| `alpha101_25` | Alpha101 | APPROX | 32820.0 | 0.9736 | 0.9977 | 0.997710 | 口径未标定（算子统计量定义） |
| `alpha101_19` | Alpha101 | APPROX | 32297.0 | 0.6139 | 0.9937 | 0.993661 | 口径未标定（算子统计量定义） |
| `alpha101_52` | Alpha101 | APPROX | 32224.0 | 7.772 | 0.9967 | 0.996670 | 口径未标定（算子统计量定义） |
| `alpha101_39` | Alpha101 | APPROX | 31852.0 | 0.3846 | 0.9985 | 0.998495 | 口径未标定（算子统计量定义） |
| `alpha101_65` | Alpha101 | FAIL | 6.0 | nan | nan | 0.738184 | §5.6 离散输出（±1）；分档一致率 0.87 仍不达标 |
| `alpha101_68` | Alpha101 | FAIL | 6.0 | nan | nan | 0.802466 | §5.6 离散输出（±1）；分档一致率 0.90 仍不达标 |
| `alpha101_58` | Alpha101 | FAIL | 4.0 | nan | nan | 0.740375 | §5.11 行业标准未披露（四种最佳 0.7404）；分档一致率 0.62 亦不达标 |
| `alpha101_59` | Alpha101 | FAIL | 4.0 | nan | nan | 0.749686 | §5.11 行业标准未披露（四种最佳 0.7497）；分档一致率 0.56 亦不达标 |
| `alpha101_29` | Alpha101 | FAIL | 33122.0 | 1.108 | 0.8009 | 0.800851 | 股票池/停牌口径未标定 |
| `alpha101_8` | Alpha101 | FAIL | 33100.0 | 0.9933 | 0.9829 | 0.982941 | 股票池/停牌口径未标定 |
| `alpha101_56` | Alpha101 | FAIL | 33085.0 | 0.8111 | 0.9864 | 0.986353 | 股票池/停牌口径未标定 |
| `alpha101_45` | Alpha101 | FAIL | 31947.0 | 0.6976 | 0.9581 | 0.958108 | 股票池/停牌口径未标定 |
| `alpha101_69` | Alpha101 | FAIL | 30250.0 | 0.9182 | 0.8729 | 0.872862 | 口径未标定（IndNeutralize 行业分类口径） |
| `alpha101_32` | Alpha101 | FAIL | 29621.0 | 0.07595 | 0.9537 | 0.953683 | 股票池/停牌口径未标定 |
| `alpha101_48` | Alpha101 | FAIL | 29495.0 | 0.1631 | 0.9205 | 0.920494 | 口径未标定（IndNeutralize 行业分类口径） |
| `alpha101_67` | Alpha101 | FAIL | 29330.0 | 0.6473 | 0.7577 | 0.757726 | 口径未标定（IndNeutralize 行业分类口径） |
| `alpha101_70` | Alpha101 | FAIL | 29215.0 | 0.7968 | 0.8813 | 0.881264 | 口径未标定（IndNeutralize 行业分类口径） |
| `alpha101_63` | Alpha101 | FAIL | 27972.0 | 1.032 | 0.8776 | 0.877625 | 覆盖率不足（官方 30798 / 重叠 27972） |
| `alpha101_64` | Alpha101 | NO_DATA | 0.0 | nan | nan | nan | 未实现：未定义标识符 '未定义变量 Delta_Mix' |
| `yoy_roa` | Growth | APPROX | 5.0 | nan | 0.005748 | 0.983670 | §5.7 已排除报告期偏移；§5.9 f_ann_date 仅 +0.0014 ⇒ 成因未定 |
| `yoy_roe` | Growth | APPROX | 5.0 | nan | 0.005797 | 0.985123 | §5.7 已排除报告期偏移；§5.9 f_ann_date 仅 +0.0033 ⇒ 成因未定 |
| `asset_growth_qoq` | Growth | APPROX | 4.0 | 0.7561 | 0.9958 | 0.995849 | APPROX 0.9948：环比用 prev_report（上一披露期），报告期选择待定 |
| `eaa` | Growth | APPROX | 4.0 | 0.996 | 0.998 | 0.998045 | §5.10 疑同因：大并列块 1167 只（供方分组规则未披露） |
| `gross_margin_qoq` | Growth | APPROX | 4.0 | 0.7217 | 0.9964 | 0.996441 | APPROX 0.9955：同 gpm_qoq（二者实现相同） |
| `pa` | Growth | APPROX | 4.0 | 0.9745 | 0.9952 | 0.995232 | §5.10 疑同因：大并列块 850 只（供方分组规则未披露） |
| `yoy_net_profit` | Growth | APPROX | 18949.0 | 3398 | 0.006956 | 0.109355 | §5.10 疑同因：原始比值型，长尾由分母穿越 0 主导（med_rel 0.0066 但 corr 0.12） |
| `np_ttm_qoq` | Growth | FAIL | 5.0 | nan | 0.01524 | 0.915667 | 比率分母穿越 0；并列仅 22 只，影响小 |
| `sa` | Growth | FAIL | 5.0 | nan | 0.04109 | 0.951334 | §5.10 疑同因：大并列块 564 只（供方分组规则未披露） |
| `eap` | Growth | FAIL | 5.0 | nan | 0.1247 | 0.929098 | EPS_Q 口径 + Close 分母待定 |
| `yoy_ocf` | Growth | FAIL | 5.0 | nan | 0.1327 | 0.733657 | §5.10 供方分组规则未披露（并列块 1767 只；本地 yoy 分布与非并列组无法区分） |
| `delta_roa` | Quality | APPROX | 5.0 | nan | 0.009916 | 0.986422 | 比率分母穿越 0 ⇒ 极端值主导（Spearman 0.9864） |
| `ar_ap_to_revenue` | Quality | APPROX | 4.0 | 0.981 | 0.9931 | 0.993148 | APPROX 0.9739：(预收−预付)/营收，科目口径待定 |
| `delta_asset_turnover` | Quality | APPROX | 4.0 | 0.9927 | 0.9939 | 0.993864 | APPROX：Delta = 本期 − t-252；长尾由分母接近 0 主导 |
| `delta_gpm` | Quality | APPROX | 4.0 | 0.9887 | 0.9901 | 0.990117 | APPROX：Delta = 本期 − t-252；长尾由分母接近 0 主导 |
| `delta_inventory_turnover` | Quality | APPROX | 4.0 | 0.9951 | 0.996 | 0.996006 | APPROX：Delta = 本期 − t-252；长尾由分母接近 0 主导 |
| `delta_roe` | Quality | APPROX | 4.0 | 0.9888 | 0.991 | 0.991016 | APPROX：Delta = 本期 − t-252；长尾由分母接近 0 主导 |
| `gpm_qoq` | Quality | APPROX | 4.0 | 0.7217 | 0.9964 | 0.996441 | APPROX 0.9955：TTM 毛利率环比，分母穿越 0 影响长尾；并列 23 只 |
| `npm_ttm_qoq` | Quality | APPROX | 4.0 | 0.5863 | 0.9974 | 0.997407 | APPROX：TTM 净利率环比，分母穿越 0 影响长尾；并列 22 只 |
| `delta_npm` | Quality | FAIL | 5.0 | nan | 0.01115 | 0.984287 | 比率分母穿越 0 ⇒ 极端值主导（Spearman 0.9843） |
| `delta_opm` | Quality | FAIL | 5.0 | nan | 0.01239 | 0.984983 | 比率分母穿越 0 ⇒ 极端值主导（Spearman 0.9850） |
| `cash_profit_ratio` | Quality | FAIL | 5.0 | nan | 0.01458 | 0.844036 | 分子口径未标定 (OCF−NI)/NI |
| `income_tax_yoy` | Quality | FAIL | 5.0 | nan | 0.01827 | 0.794903 | 比率分母穿越 0 ⇒ 极端值主导 |
| `expenses_to_equity_yoy` | Quality | FAIL | 5.0 | nan | 0.04698 | 0.775244 | 比率分母穿越 0 ⇒ 极端值主导 |
| `cfcr` | Quality | FAIL | 5.0 | nan | 0.04981 | 0.965504 | ⚠️ 官方截面仅 N=172 ⇒ 样本量不足、Spearman 不可靠；InterestExpense 字段未标定 |
| `tax_surcharge_yoy` | Quality | FAIL | 5.0 | nan | 0.05327 | 0.943213 | 比率分母穿越 0 ⇒ 极端值主导 |
| `np_to_salary_yoy` | Quality | FAIL | 5.0 | nan | 0.057 | 0.794985 | 比率分母穿越 0 ⇒ 极端值主导 |
| `np_to_deferred_tax_yoy` | Quality | FAIL | 5.0 | nan | 0.07287 | 0.673899 | 比率分母穿越 0 ⇒ 极端值主导 |
| `np_to_inventory_yoy` | Quality | FAIL | 5.0 | nan | 0.07939 | 0.648427 | 比率分母穿越 0 ⇒ 极端值主导 |
| `np_to_fixed_assets_yoy` | Quality | FAIL | 5.0 | nan | 0.1029 | 0.617855 | 比率分母穿越 0 ⇒ 极端值主导；疑 qdata 有裁剪（filter=True） |
| `np_to_total_expenses_yoy` | Quality | FAIL | 5.0 | nan | 0.1089 | 0.605378 | 比率分母穿越 0 ⇒ 极端值主导 |
| `icr` | Quality | FAIL | 5.0 | nan | 0.2155 | 0.829610 | ⚠️ 官方截面仅 N=106 ⇒ 样本量不足、Spearman 不可靠；InterestExpense 字段未标定 |
| `quality_composite` | Quality | FAIL | 20275.0 | 2.787e+04 | 0.09885 | 0.900806 | OpCashInflow/InvCashInflow 字段 + filter=True 语义未标定 |
| `lra_yoy` | Quality | FAIL | 5891.0 | 2569 | 1.467 | 0.070889 | LongtermReceivableAccount 字段未标定（Tushare lt_rec 仅覆盖 1693 只） |
| `dividend_yield_3y_avg` | Value | APPROX | 4.0 | 0.9904 | 0.9906 | 0.990599 | §5.12 全市场 5416 只（原 600 只抽样）：0.987713 → **0.990599（APPROX）**；关键口径 = **剔 |
| `ebitda_to_market` | Value | FAIL | 4.0 | 0.9017 | 0.91 | 0.910041 | §5.14 口径未定：EBITDA_TTM/mv 0.910（年报口径 0.973、EBIT+营业成本 0.599 均更差） |
| `etp5` | Value | FAIL | 4.0 | 0.9839 | 0.9844 | 0.984379 | §5.14 窗口口径未定：mean(归母年报,1260)/mean(mv,1260) 0.984；名次偏差中位 7.86% |
| `ncf_to_market` | Value | FAIL | 4.0 | 0.5361 | 0.7128 | 0.712845 | §5.14 口径未定：(OCF+ICF+筹资净额)_TTM/mv 0.713；最大偏差集中在银行；OCF+ICF 0.184、单季 0.20 |
| `ocf_to_market` | Value | FAIL | 4.0 | 0.7628 | 0.8623 | 0.862316 | §5.14 少数金融股错位主导：名次偏差中位仅 1.46% 但 p90 19.5%；最大偏差 8 只全为银行/券商（存款同业现金流科目差异） |
| `pegh5` | Value | FAIL | 4.0 | 0.9388 | 0.9409 | 0.940875 | §5.14 口径未定：-Close/(g5·EPS_TTM) 0.941；g5 用 EPS 年报 5 年复合增速 |

## 5. 判据差异（需人工确认）

共 16 条：**A 类（实际判据错误，结果不可信）1 条**；**B 类（登记表待补，实际结果通常正确）15 条**。

### A 类 —— 必须用 `xs_compare` 重跑

这些因子含横截面算子，却用了**绝对误差**判据。横截面因子的值是 `rank/N`，名次差 10 位只值 0.0018，绝对误差判据会把「99% 名次都对」错报成 FAIL。

### B 类 —— `FACTOR_STATUS.json` 的判据列待补

这些因子在 `FACTOR_STATUS.json` 里按**公式文本**被标为「绝对误差」（公式未出现 `CrossSectionalRank`），但实测实际用的是**横截面**判据。常见于 `passthrough` 因子与复合因子（qdata 的公式文本省略了外层排名包装，如 `roe_ttm` / `quality_composite` / `nl_size`）。**实际结果通常是对的**，应在登记表中补标「含横截面（公式文本未体现）」。

| 因子 | 族 | 实际判据 | 应有判据 | 差异方向 | 当前结论 |
|---|---|---|---|---|---|
| `fcf_to_market` | Value | 横截面Spearman | 绝对误差 | B:登记表待补（实际用横截面判据，通常正确） | EXACT |
| `alpha101_101` | Alpha101 | 横截面Spearman | 绝对误差 | B:登记表待补（实际用横截面判据，通常正确） | EXACT |
| `alpha101_9` | Alpha101 | 横截面Spearman | 绝对误差 | B:登记表待补（实际用横截面判据，通常正确） | EXACT |
| `alpha101_41` | Alpha101 | 横截面Spearman | 绝对误差 | B:登记表待补（实际用横截面判据，通常正确） | EXACT |
| `alpha101_12` | Alpha101 | 横截面Spearman | 绝对误差 | B:登记表待补（实际用横截面判据，通常正确） | EXACT |
| `alpha101_23` | Alpha101 | 横截面Spearman | 绝对误差 | B:登记表待补（实际用横截面判据，通常正确） | EXACT |
| `alpha101_51` | Alpha101 | 横截面Spearman | 绝对误差 | B:登记表待补（实际用横截面判据，通常正确） | EXACT |
| `alpha101_49` | Alpha101 | 横截面Spearman | 绝对误差 | B:登记表待补（实际用横截面判据，通常正确） | EXACT |
| `alpha101_54` | Alpha101 | 横截面Spearman | 绝对误差 | B:登记表待补（实际用横截面判据，通常正确） | EXACT |
| `alpha101_6` | Alpha101 | 横截面Spearman | 绝对误差 | B:登记表待补（实际用横截面判据，通常正确） | EXACT |
| `alpha101_24` | Alpha101 | 横截面Spearman | 绝对误差 | B:登记表待补（实际用横截面判据，通常正确） | EXACT |
| `alpha101_53` | Alpha101 | 横截面Spearman | 绝对误差 | B:登记表待补（实际用横截面判据，通常正确） | EXACT |
| `alpha101_26` | Alpha101 | 横截面Spearman | 绝对误差 | B:登记表待补（实际用横截面判据，通常正确） | EXACT |
| `nl_size` | Size | 横截面Spearman | 绝对误差 | B:登记表待补（实际用横截面判据，通常正确） | GOOD |
| `alpha101_35` | Alpha101 | 横截面Spearman | 绝对误差 | B:登记表待补（实际用横截面判据，通常正确） | GOOD |
| `lra_yoy` | Quality | 绝对误差 | 横截面Spearman | A:实际判据错误（须用 xs_compare 重跑） | FAIL |

## 6. 已标定的全局口径

见 `CONVENTIONS.md`：§G1 后复权价、§G2 尾部未沉淀窗口（含完整证据链）、§G3 滚动窗口含当日、§G4 简单收益、§G5 样本标准差、§G6 日期上限、§G7 取数纪律、§3.1 横截面依赖扫描（126/242）、§3.2 全市场面板可行路径、§3.4 `CrossSectionalRank = rank/N` 标定与横截面 Spearman 判据、§3.3 跨体系交叉验证、§3.5 Tushare 数据可得性。

> `scripts/qdata/FORMULA_AUDIT.md` 为公式静态审计（横截面扫描 / 参数清单 / 直通因子 / 跨体系对照）。
