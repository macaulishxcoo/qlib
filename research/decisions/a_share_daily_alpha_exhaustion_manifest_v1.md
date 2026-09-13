# A 股日频 alpha 测尽清单 v1

> **文档定位**：只读汇总清单（manifest）。汇总本项目全部已检验的日频 alpha 方向
> 及其结论、证据位置、保留资产，供后续会话直接引用——**避免重复研究、避免误判
> "还有没测的方向"**。
>
> **性质**：不启动新实验。每条线均为已归档结论，引用的协议/决策/产物是唯一证据源。

---

## 1. 一句话总论

**独立于动量/反转的 A 股日频截面 alpha，在本项目可及数据（价量/估值/事件/PEAD/
两融/趋势）下已全部测完，无存活者。** 所有"显著"的日频信号要么是动量/反转的
换皮（事件流、龙虎榜、PEAD 方向），要么是系统性暴露/过滤层（趋势状态、两融
拥挤），要么组合层不可交易（换手率水平、偏度）。**唯一"活着的日频策略"是
基本面域 + 日频调仓（月频 alpha 的日频执行），不含日频 alpha。**

---

## 2. 已测方向总表（全部闭环）

| # | 方向 | 检验 | 结论 | 证据位置（协议/决策/产物） |
|---|---|---|---|---|
| 1 | **Alpha158 价量（量比/动量/波动族）** | LightGBM 静态/滚动 + 特征 IC | 2021 后衰减；测试段 Daily IC 全负；158 特征单变量 IC 几乎全趋 0 | `DEV_LOG_RollingTrainingOptimization.md` §3/§10/§12.6；`research/rolling_comparison_results.csv` |
| 2 | **主升浪横截面形态（15 因子）** | 仓库口径复验 | 紧凑蓄势/突破前高/条件组合全判死；多数因子是 Alpha158 duplicate/near | `research/a_share_zsl_main_wave_factor_line_assessment_v1.md`；`output/analysis_static/zsl_main_wave_factor_validation_v1/` |
| 3 | **趋势持续性（时序状态 TS_UP60）** | 母池 5542 只 T1-T4 | T1 显著（+0.166）但排序层 ICIR 0.23 弱；定位为**系统性暴露/趋势确认层**，不单飞 | `research/protocols/a_share_trend_persistence_protocol_v1.md`（executed_supported）；`output/analysis_static/a_share_trend_persistence_v1/` |
| 4 | **日频估值（S1）** | 单因子/组合 | 负 IC（-0.03~-0.05），日频估值无 alpha | `research/protocols/a_share_daily_valuation_s1_protocol_v1.md` |
| 5 | **事件流（龙虎榜/增减持/解禁）** | 325.6 万行 × 动量正交 | **not_supported**：事件超额是动量代理（龙虎榜上榜=当日强势股），事件本身无方向信息 | `research/decisions/a_share_events_daily_stream_assessment_v1.md`；`output/analysis_static/a_share_events_daily_v1/` |
| 6 | **PEAD（财报公告后漂移）** | 99,073 事件 × 方向分组 × 动量正交 | **pead_direction_unclear_closed**：正负公告均正超额（负向更大=利空出尽），方向不符 PEAD 假设；2026 反转 | `research/decisions/a_share_pead_closure_v1.md`；`research/protocols/a_share_pead_protocol_v1.md`；`output/analysis_static/a_share_pead_v1/` |
| 7 | **非 Alpha158 量价（电池 7 因子）** | RankIC + 冗余判定 | 换手率水平/偏度存活，其余死（含 2 伪增量：换手率变化≡量比、相对强度≡动量） | `research/decisions/a_share_price_volume_factor_battery_closure_v1.md`；`output/analysis_static/a_share_price_volume_factor_battery_v1/` |
| 8 | **存活因子中性化复验** | M/MV/MVI 残差 + 市值×波动分层 | 换手率水平/偏度 MVI 后 ICIR 反升、25 格全正 → 真 alpha 非风险暴露 | `research/decisions/a_share_price_volume_factor_neutralization_closure_v1.md` |
| 9 | **与主线正交性 + h40 补测** | 42 调仓日 × 主线 composite | 与基本面主线正交（\|corr\|<0.11）但**短周期信号**：h=40 反转，不能并入月频主线 | `research/decisions/a_share_price_volume_factor_orthogonality_closure_v1.md`、`..._orthogonality_h40_closure_v1.md` |
| 10 | **纯量价日频回测** | TopkDropout top50 日频 × 真实费率 | **dead**：换手率组合层反转（IC 正≠可交易）、偏度弱正 IR 0.25 | `research/decisions/a_share_pv_daily_strategy_closure_v1.md`；`output/analysis_static/a_share_pv_daily_strategy_v1/` |
| 11 | **域内偏度** | 基本面域内排序 × 日频 | 2024 失效被域过滤消除（-0.127→-0.001），但增量 < 域功劳 | `research/decisions/a_share_pv_domain_skew_strategy_closure_v1.md` |
| 12 | **两融拥挤（rzye_zscore）** | 正交性/过滤层验证 | IC -0.043 有效但作**过滤层无增量**；保留为独立信号源候选 | `research/protocols/margin_signal_orthogonality_protocol_v1.md`；`research/decisions/a_share_margin_data_adoption_v1.md` |
| 13 | **日频策略基线（main）** | 基本面域 + 日频调仓 | **net +0.164/IR 1.68 四年全正、换手 4.8%、stress 下 IR 1.58**；量价增强不采纳 | `research/decisions/a_share_daily_strategy_closure_v1.md`；`output/analysis_static/a_share_daily_strategy_v1/` |

---

## 3. 关键机制总结（为什么测尽）

1. **A 股短周期真实规律是动量/反转**：事件流（龙虎榜）、PEAD 的"显著超额"经
   动量正交检验后都被证明是**动量代理**（事件股 = 当周强势股，vs 基准本就跑赢）。
   事件只是"强弱股"的选择器标签，不携带独立方向信息。
2. **PEAD 方向不符**：A 股正负公告**都正超额**（负向更大 = 利空出尽），不是
   盈余信息逐步扩散的方向性漂移——与美股机制根本不同。
3. **IC 正 ≠ 可交易**（本轮最大教训）：换手率水平 IC +0.064 但 top50 组合年化
   -0.49（Q5 极端高换手 = 题材股，集中持有后均值回归）。**RankIC/ICIR 判定
   "有效"必须过真实调仓回测才算数。**
4. **量价候选是短周期、主线是长周期**：换手率/偏度 h=5 有效、h=40 反转；
   基本面 h=40 强、h=5 弱。两者时间尺度不同轨，等权合并稀释主线。

---

## 4. 存活资产（可部署/可复用，勿弃）

| 资产 | 定位 | 证据 |
|---|---|---|
| **main 日频策略**（基本面域+日频调仓） | 唯一达标的日频策略形态：net +0.164/IR 1.68、换手 4.8% | `a_share_daily_strategy_closure_v1.md` |
| 两融拥挤过滤层（rzye_zscore） | IC -0.043，唯一存活的可部署日频过滤组件 | `margin_signal_orthogonality_protocol_v1.md` |
| 趋势状态（TS_UP60） | 系统性暴露/趋势确认层候选，不单飞 | `a_share_trend_persistence_protocol_v1.md` |
| 事件数据 325.6 万行 | 已入库，未来事件研究直接可用 | `data/external/tushare/a_share_events_daily_v1/` |
| 动量正交检验方法 | 判定"事件超额是否动量代理"的现成方法 | `analyze_a_share_events_daily_v1.py` |
| 量价因子数据/脚本链 | battery→neutralization→orthogonality→回测，全部可复跑 | `scripts/analyze_a_share_price_volume_factor_*` + `backtest_a_share_*` |

---

## 5. 未测方向（需要新数据/新能力，非已有资产）

| 方向 | 障碍 | 备注 |
|---|---|---|
| 另类数据（舆情/资金流/高频/席位） | 无数据源；tushare 全文本公告 `anns_d` 无权限 | 超出个人可及范围 |
| 业绩预告/快报 PEAD | 数据缺失（提案 §4 明确"不做"） | 待数据后另行立项 |
| 公告文本情绪 | 需 NLP + 公告全文 | 同 `anns_d` 权限障碍 |
| 多事件叠加/事件冲突清洗 | 复杂度高，提案冻结为后续 | — |

---

## 6. 引用规则（给后续会话）

- 任何"试试日频 alpha"的想法，先对照 §2 总表：方向已在表内 → **不重复，读对应
  归档**；方向在表外且不依赖新数据 → 走三问门槛立项；依赖新数据 → 先确认数据
  可得性（tushare 权限）再立项。
- "日频策略"四字在仓库语境下默认指 **main（基本面域+日频调仓，月频 alpha 的
  日频执行）**，非日频 alpha 策略——引用时注意区分。

---

## 7. 变更记录

| 日期 | 变更 |
|---|---|
| 2026-08-13 | 创建：汇总 13 条已测日频 alpha 方向的结论/证据/保留资产；总论 = 独立于动量/反转的日频截面 alpha 已测尽 |
