# 负面事件分类型研究协议 v1

## 1. 状态、问题与授权边界

状态：`design_frozen_before_first_label_read`

承接 `research/decisions/a_share_negative_event_subtype_proposal_v1.md`。PEAD 关闭
结论（`a_share_pead_closure_v1.md`）是**全部负面公告的混合平均**：正负公告均正超额、
负向公告更大（+1.41% vs +0.77%，h=10）→ "利空出尽"。本协议检验：

```text
把"负面事件"按类型拆开（经营类-预亏/预减、制度类-ST 戴帽、资金类-减持/解禁、
交易类-跌幅上榜），各类事件后 10/20/40 个交易日的市场调整超额是否方向一致、
非动量代理、且类型间存在显著行为差异？
```

- 若某类显著持续为负且非动量代理 → 该类进入"剔除层候选"，走组合层回测验证
  （复用 v11 过滤层口径）；
- 若全部类型均"利空出尽"或方向混乱 → 关闭归档，结论"负面事件分类型在 A 股无
  系统负漂移，反向视角在事件层不成立"，与 PEAD 结论自洽。

本协议只授权**事件层单因子信息含量检验**（+ 对通过类型的组合层对比回测），不授权
模型训练、阈值搜索或实盘。事件类型定义在读取任何标签前冻结；跑完不因结果调整
事件定义、持有期或判定门槛。

## 2. 与既有研究的关系

| 项 | 说明 |
|---|---|
| PEAD（已关闭） | 混合平均"利空出尽"。本协议**不重测混合效应**，只拆类型——类型间行为相同则确认 PEAD，不同则修正 |
| 事件流（not_supported） | 龙虎榜/增减持/解禁的"显著超额"是**动量代理**（正向事件=强势股）。本协议的负面事件恰是**弱势股**，动量正交化是防混淆闸门而非重复 |
| 价值陷阱（adopted） | 财务恶化**状态截面**（报告期标识的未来持有期）；本协议是**事件窗口**（公告日后的持有期）。机制链不同 |
| 权限探测（2026-08-13 实测） | tushare `forecast`（业绩预告）个人权限✅可用（按 ann_date 逐日拉取）；`express`（快报）✅可用；**违规/立案/处罚类接口个人权限不可得**（violation_violation 等均无）→ T2 制度类改用 ST 戴帽事件（namechange）替代，局限见 §7 |

## 3. 事件类型定义（冻结，不做搜索）

| 类型 | 定义 | 事件日 | 数据源 | 状态 |
|---|---|---|---|---|
| T1 经营类-预亏/预减 | `forecast.type ∈ {预亏, 首亏, 续亏, 预减, 略减}` | `ann_date` | `a_share_forecast_v1/`（新下载，2022-2026） | ✅ 权限已确认 |
| T2 制度类-ST 戴帽 | `namechange` 中 `is_st` 由 false→true 的区间起点 | `start_date` | `a_share_st_status_pit_v1/`（已有） | ✅（监管处罚的替代代理） |
| T3 资金类-减持 | `stk_holdertrade.in_de == 'DE'`；分层：holder_type（P 个人/G 高管/C 机构）、change_ratio 分档 | `ann_date` | `a_share_events_daily_v1/`（已有） | ✅ |
| T4 资金类-解禁 | `share_float.float_ratio` 分档（大/小解禁） | `float_date` | `a_share_events_daily_v1/`（已有） | ✅ |
| T5 交易类-跌幅上榜 | `top_list.reason` 含"跌幅"或"负向异常波动" | `trade_date` | `a_share_events_daily_v1/`（已有） | ✅ |
| C 对照 | 无事件股票（同日全市场，隐含于市场调整超额口径） | — | 母池 | — |

约束：
- T1 的 `type` 枚举完整含：预增/预减/扭亏/首亏/续亏/续盈/略增/略减/减亏/增亏/不确定。
  主信号 = 预亏/首亏/续亏/预减/略减（5 类负面），剔除"不确定"；`p_change_min` 观察口径；
- T5 的 reason 映射规则（含"跌幅"或"负向异常波动"）在实验前冻结，不事后调整；
- 多重事件重叠（冻结）：同股同日多事件 → 按 T1 > T2 > T3 > T4 > T5 优先级取主事件；
  同股 20 日内多事件 → 仅保留首个；
- 分年度报告（2022-2025 主检验，2026H1 观察）。

## 4. 检验框架（复用既有事件管线）

- **母池**：沪深普通 A 股（非金融），剔除北交所/指数/B 股，口径同
  `analyze_a_share_events_daily_v1.py`（`build_universe`）；
- **数据**：`cn_data_2026`（后复权）+ ST 区间 PIT（`st_status_intervals.csv.gz`）；
- **标签**：`r_H(t) = open(t+H)/open(t) − 1`，H ∈ {10, 20, 40}；
- **超额**：市场调整 = 个股未来收益 − 同期 SH000852 未来收益（T+1 开盘成交）；
- **过滤**：ST/退市整理（事件日 asof）+ 停牌 + 涨停信号日（10%/20% 分板块）；
- **窗口**：2022-01-01 ~ 2026-07-31（事件数据全覆盖；2026-07 后行情复权因子异常
  已记录于 stage2 画像，本轮不延展）；
- **对照组**：市场调整超额隐含"对照=市场平均"（与 PEAD/事件流脚本同口径）。

### 4.1 主检验（每类事件 vs 市场平均）

- 每类事件股的 H 日市场调整超额均值，单样本 t 检验（|t| 从紧，参考 > 2.5）；
- 分年度方向一致性：2022-2025 至少 3 年同向；
- 分层报告：按规模（log 市值五等分）、按事件规模（change_ratio/float_ratio 分档）、
  按行业（一级行业，仅观察非主检验）。

### 4.2 动量正交化闸门（复用 PEAD 方法）

- 按事件前 20 日收益 5 组，检验事件后超额是否随动量单调变化；
- 若显著负超额在控制动量后消失或被单调解释 → 该类型判为"下跌动量代理"，关闭。

### 4.3 组间差异（本方向核心问题）

- 四类事件（T1/T3/T4/T5）的 20 日超额两两比较（Welch t 检验）+ 单因素 ANOVA，
  回答"经营 vs 制度 vs 资金 vs 交易是否行为不同"；
- T2（ST 戴帽）样本相对稀疏，单独报告，不强制进入组间主比较。

## 5. 验收（冻结，不达标就停）

1. **事件层**：某类 20 日市场调整超额**显著为负**（t < −2.5 从紧）+ 分年度方向一致
   （2022-2025 ≥3/4 年同向）+ **动量正交化后仍显著为负**（非下跌动量代理）；
2. **组合层**（对通过事件层的类型，逐类独立）：将该类事件股从主线月度多头名单剔除
   （公告日生效的剔除层）→ holdout（2023-2025）压力费后年化超额**不降**（容忍
   ≥ −0.5pp），且 new_coverage（2025-07~2026-06）年化超额**改善 ≥ +5pp**
   （复用 v11 过滤层口径，基线 = v8 top15 同构复现）。

任一不满足 → 该类型关闭归档，如实记录失败机制。全部类型不通过 → 关闭整个方向，
结论与 PEAD 自洽。不追加搜索、不调阈值。

## 6. 产物、目录与审计

```text
output/analysis_static/a_share_negative_event_subtype_v1/
  event_excess_by_type.csv        # 主检验：每类型 × H 的超额均值/t/分年度
  event_type_breakdown.csv        # 分类型分层报告（规模/事件规模/行业）
  momentum_orthogonality.csv      # 动量正交化（每类型 × 动量 5 组）
  type_pairwise_diff.csv          # 组间差异（两两 Welch t + ANOVA）
  decision.json                   # 每类型独立判定
  methodology.json                # 口径快照
  validation_report.txt           # 中文报告
```

组合层对比回测产物（若事件层有通过类型）：
`output/analysis_fundamental/a_share_negative_event_subtype_filter_v*/`。

## 7. 诚实标注与结论边界

- **T2 代理局限**：监管处罚/立案类接口个人权限不可得，ST 戴帽（制度性负面）只能
  近似"政策/监管利空"，且 ST 戴帽多为财务/审计问题触发——若 T2 显著，结论表述为
  "制度性风险警示事件"，不夸大为监管处罚效应；
- **T5 的固有重叠**：跌幅上榜天然与"弱势/下跌动量"重叠，动量正交化若不过关则
  判代理，不强行保留；
- 事件数量：T1/T2 数量少于 T3/T4/T5，分组后把握度可能不足——报告中如实给出 n 与
  把握度说明，不为凑显著性合并类型；
- 若事件层通过而组合层不通过 → 记录"信号存在但不足以支撑剔除层"，关闭组合用法；
  若事件层不通过 → 不再启动组合层回测。无论结果，本协议只跑一次。

## 8. 可复现证据

- 提案：`research/decisions/a_share_negative_event_subtype_proposal_v1.md`
- 复用管线：`scripts/analyze_a_share_events_daily_v1.py`（事件窗口 + 超额口径）、
  `scripts/analyze_a_share_pead_v1.py`（动量正交化）、
  `scripts/analyze_a_share_trend_persistence_v1.py`（build_universe / qlib_to_ts / is_gem）、
  `scripts/backtest_a_share_value_quality_monthly_value_trap_filter_v11.py`（组合层口径）
- 新数据：`data/external/tushare/a_share_forecast_v1/`（下载脚本
  `scripts/data_collector/download_a_share_forecast_v1.py`）
