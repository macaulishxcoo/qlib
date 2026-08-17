# 价值陷阱过滤层验证结论 v1

> **文档定位**：研究结论文档。记录"价值陷阱识别"（域内财务恶化过滤层）从立项评估
> 到 IC 层与组合层验证的完整结果，供后续会话直接引用，避免重复研究。
> **性质**：只读结论。协议与产物：
> `research/protocols/a_share_value_trap_identification_protocol_v1.md`（`executed`）、
> `output/analysis_fundamental/a_share_value_trap_identification_v1/`、
> `output/analysis_fundamental/a_share_value_quality_monthly_strategy_v13_value_trap_filter/`。

---

## 1. 背景与选题

主线价值策略四因子（E/P、BM、股息率、应计质量）全部为**水平因子**，无法区分
"便宜且稳定"与"便宜且正在恶化"。2026 价值逆风中可能混有"价值陷阱成分"（便宜+恶化
= 越跌越便宜）。本线检验：财务恶化信号（净利/营收/经营现金流同比为负）作为主线的
**质量过滤层**，能否在识别价值陷阱的同时不伤害主线。

立项评估：`research/decisions/a_share_value_trap_identification_proposal_v1.md`（提案）。

---

## 2. 信号与口径（冻结）

- 恶化信号：`deter_any2` = `netprofit_yoy < 0` / `or_yoy < 0` / `ocf_yoy < 0`
  中 **≥2 个命中**（≥2 个可观察维度）；
- 域：composite（≥3 因子）→ 行业+log_size 中性化残差前 50%（主线选股域）；
- PIT：`available_date <= rebalance_date` 最新报告期；YoY 列来自 fina_indicator
  归一化文件（非空率 93-95%），零新增下载；
- 标签：open-to-open r_H，H∈{20,40,60}；标签中性化 = 行业+log_size OLS 残差。

## 3. IC 层结果（域内恶化组 vs 稳定组，中性化收益差）

| 阶段 | 40d 组均值差 | t | 负向月占比 |
|---|---|---|---|
| development (2016-2019) | **-0.0084** | **-5.06** | 77% |
| confirmation (2020-2022) | -0.0044 | -1.36 | 58% |
| holdout (2023-2025-06) | -0.0056 | **-2.30** | 63% |
| new_coverage (2025-07~2026-06) | -0.0097 | **-2.08** | 55% |

**结论：`ic_layer_pass`（四个阶段全负、dev/holdout/new_coverage 显著）**。
恶化组 40 日跑输稳定组 0.4~1.0pp，方向四阶段一致。

**诊断**：
- 单信号：净利维度主导（deter_ni dev t=-3.30、holdout t=-1.74）；现金流维度开发期
  强（t=-4.81）但确认期转正（+0.0007，噪音）；营收维度 new_coverage 最强（t=-2.47）；
- 规模层：效应**非小市值驱动**——holdout 各层全负（S1 -0.0063 ~ S5 -0.0033），
  new_coverage 中大盘层反而最强（S5 -0.0205）；确认期 S4 单层转正（+0.0059，噪音）。

## 4. 组合层结果（v8 top15 基线 vs 基线+过滤层，压力费后相对 SH000852）

| 阶段 | 基线 net | 过滤后 net | delta |
|---|---|---|---|
| development | +21.81% | +13.75% | **-8.06pp（削弱）** |
| confirmation | +3.50% | -0.04% | **-3.54pp（转负）** |
| holdout | +10.16% | +12.14% | **+1.98pp（改善）** |
| **new_coverage（2026 逆风段）** | **-35.01%** | **-26.34%** | **+8.67pp（改善）** |

**判定（按协议双门槛）：`value_trap_filter_adopted`** —— holdout delta +1.98pp
（≥-0.5pp ✅）、new_coverage delta +8.67pp（≥+5pp ✅）。

---

## 5. 结果解读：三个必须如实记录的事实

### 5.1 过滤层确实抓到了 2026 逆风中的"价值陷阱成分"

new_coverage 净超额从 -35.0% 收窄到 -26.3%（**+8.67pp**）：价值逆风期里跌得最惨的
正是"便宜+财务恶化"的股票，剔除它们减轻了伤害。**这支持"2026 逆风部分可修复"假说
（价值陷阱成分真实存在），但逆风主体（纯风格暴露）仍在——-26% 依然是大负超额。**

### 5.2 过滤层在开发/确认期显著削弱策略（重大矛盾）

dev net -8.1pp、conf net -3.5pp（转负）。**IC 层开发期信号最强（t=-5.06），但组合层
开发期削弱最多**——机制推测：
- 开发期（2016-2019，含 2016-2017 价值顺风 + 2018 熊市）top15 里恶化股本就不多，
  剔除后由排名 16-20 的"替补"顶上，这些替补在顺风期并不更好；
- 过滤层把"便宜且正在改善"的股票也一并剔除了吗？——**否**（deter_any2 只剔恶化，
  不碰改善股），但组合层面剔除 1-2 只后集中度变化会放大个别股波动。

### 5.3 holdout MDD 恶化（-16.6% → -30.7%，几乎翻倍）

净超额提升但最大回撤恶化：过滤后候选池变小，top15 更集中，2023-2025 内个别
"被剔除股的反弹"或"替补股的回撤"放大了回撤。**对个人实盘（MDD 敏感）这是重要警示。**

---

## 6. 结论与建议

1. **按协议判定 `adopted`**：IC 层四阶段全负 + 组合层 holdout 不降且 new_coverage
   大幅改善——过滤层**在 2026 逆风段有真实保护作用**（+8.67pp），且不伤害 holdout。
2. **是否并入实盘管线需用户决策**（本线只验证到"过滤层有效"）：
   - 支持并入：new_coverage +8.67pp 直接缓解 2026 式逆风伤害，holdout 反升；
   - 反对并入：dev/conf 削弱 + holdout MDD 翻倍——长期看过滤层可能牺牲了顺风期
     的部分收益换取逆风期保护，且集中度风险上升；
   - 折中：过滤层作**观察开关**——仅当进入价值逆风（如 market breadth 恶化）时
     启用，顺风期不启用（但这又回到"风格择时"，v7/v9 已关闭，需谨慎立项）。
3. **周期性风险对策的更新**：2026 逆风 = 纯风格暴露 + 可修复的价值陷阱成分
   （过滤层收窄 8.67pp，约 1/4）。剩余 -26% 仍需 20% 仓位/止损钝化（部署协议 v1），
   但"可修复部分"已实证存在。
4. **后续候选（另行立项）**：指数调整效应（已提案）、融券侧信号、市场宽度防御。

---

## 7. 诚实标注

- dev/conf 组合层削弱与 IC 层方向（dev 最强）矛盾，机制未完全定位（§5.2 为推测）；
- holdout MDD 恶化（-16.6%→-30.7%）未在协议验收门槛内（协议只查 net 超额与 IR），
  属**协议未覆盖的意外发现**，对实盘决策至关重要；
- 未做参数搜索（deter_any2 定义、域分位数、持有期冻结）；不因矛盾调阈值；
- new_coverage 为观察区（2025-07~2026-06），样本 11 个月，结论稳健性待时间验证；
- **标签口径复核（2026-08-14）**：另一条探索线发现既有事件/趋势脚本的 FWD 标签
  （`open[t+1]/close[t+h+1]−1`）方向反转（corr=−0.93），据此更正了事件流结论
  （龙虎榜=注意力反转负漂移，非"动量代理"）。**本实验不受影响**：本线标签为
  `open[T+H]/open[T]−1`（分子为后值、分母为前值，方向正确），且与主线
  `build_snapshot`/`fetch_labels` 历史口径一致（T 日 open 入场）；另一线的正确口径
  为 `open[t+1+h]/open[t+1]−1`（T+1 入场），与本线差一个交易日——该差异与主线
  历来的入场口径一致，不影响本实验的相对比较结论。

## 8. 可复现证据

- 提案：`research/decisions/a_share_value_trap_identification_proposal_v1.md`
- 协议：`research/protocols/a_share_value_trap_identification_protocol_v1.md`
- IC 层：`scripts/analyze_a_share_value_trap_identification_v1.py` →
  `output/analysis_fundamental/a_share_value_trap_identification_v1/`
- 组合层：`scripts/backtest_a_share_value_quality_monthly_value_trap_filter_v13.py` →
  `output/analysis_fundamental/a_share_value_quality_monthly_strategy_v13_value_trap_filter/`
  （baseline 臂 = v8 同构复现，非重跑既有 v8 产物）

## 9. 变更记录

| 日期 | 变更 |
|---|---|
| 2026-08-13 | 创建：价值陷阱过滤层验证结论——IC 层四阶段全负（dev t=-5.06/holdout t=-2.30/new_coverage t=-2.08），组合层 new_coverage +8.67pp/holdout +1.98pp → `value_trap_filter_adopted`；如实记录 dev/conf 组合层削弱（-8.1pp/-3.5pp）与 holdout MDD 翻倍矛盾 |
| 2026-08-14 | 命名 v11→v13（另一条探索线的 revfilter 已占用 v11）；补记标签 bug 复核（本线标签口径不受影响） |
