# 五因子 + T5 + 超买双层过滤回测关闭记录 v16

## 1. 决策

状态：`holdout_erosion_closed`（2026-08-18）

双层过滤（T5 + revf）在五因子基线上的判定结果与 v15 在四因子基线上
**完全一致**：new_coverage 大幅改善（+18.47pp）但 holdout 侵蚀
（-2.82pp，超 -0.5pp 硬门槛）。**不采纳。**

**v15 的机制警示在五因子基线上重演**：revfilter 叠在 T5 之上会把
候选挤向"低波动但非最优"的替补，顺风期（holdout）代价集中。
五因子的 g2 没能缓解这个挤压（g2 让候选池在成长方向更宽，但 T5
先剔除了部分高波动高增速候选，revfilter 的替补池质量仍不够）。

## 2. 三臂完整对照（stress 费后，相对 SH000852）

| 阶段 | baseline（五因子） | t5（+T5） | t5+revf（双层） |
|---|---|---|---|
| **holdout net** | +9.66% / IR 0.78 | +7.89% / IR 0.61 | **+6.84% / IR 0.58** |
| **new_coverage net** | -31.06% | **-17.47%** | **-12.58%** |
| holdout MDD | -15.6% | -18.4% | -16.7% |
| confirmation net | +3.0% | +3.8% | +6.6% |
| development net | +24.1% | +24.1% | +23.7% |

双门槛：
- holdout delta = **-2.82pp**（>= -0.5 -> ❌ 不通过）
- new_coverage delta = **+18.47pp**（>= +5 -> ✅ 通过）

revfilter 在 T5 之上的独立增量：new_coverage +4.88pp（有增量但
不够抵消 holdout 侵蚀）。

## 3. 与 v15 的跨基线对比

| 指标 | v15（四因子三层 vt+t5+revf） | v16（五因子两层 t5+revf） |
|---|---|---|
| holdout 侵蚀 | -1.18pp | **-2.82pp**（更严重） |
| new_coverage 改善 | +33.64pp | +18.47pp（更弱） |
| holdout MDD | -33.0% | -16.7%（更浅） |

v16 比 v15 更严重地侵蚀 holdout（-2.82 vs -1.18pp），且逆风修复
更弱（+18.47 vs +33.64pp）。**两层不如三层**--去掉 vt 层后，
revfilter 的"削峰"效应未被 vt 的"填谷"效应抵消，holdout 侵蚀
反而放大。v15 的三层虽有侵蚀，但 vt 至少在 new_coverage 上贡献
了额外 +8pp（三层 +33.64 vs 两层估算 +25pp），且 MDD 恶化是 vt
带来的（v14 显示 vt 单层 MDD -30.7%）。

## 4. T5 单层在五因子基线上的表现（副产品发现）

T5 单层在五因子基线上是**干净的增量**：

| 指标 | baseline | t5 | delta |
|---|---|---|---|
| holdout net | +9.66% | +7.89% | **-1.77pp** |
| new_coverage net | -31.06% | -17.47% | **+13.59pp** |
| holdout MDD | -15.6% | -18.4% | -2.8pp |

T5 单层也有 holdout 侵蚀（-1.77pp，超 -0.5pp 门槛），但 new_coverage
修复 +13.59pp。与四因子基线上的 T5（holdout +0.73pp、new_coverage
+20.33pp）对比，五因子基线上 T5 的逆风修复更弱（+13.59 vs +20.33pp），
holdout 侵蚀更明显（-1.77 vs +0.73pp）--g2 已经吸收了部分逆风保护，
T5 的边际增量被稀释。

## 5. 结论

1. **双层（t5+revf）不采纳**，与 v15 三层同机制关闭
2. **T5 单层在五因子基线上也有 holdout 侵蚀**，不满足 v14 双门槛
   的 holdout >= -0.5pp 条件。但按 v12 的原始判定口径（T5 单层
   adopted 是基于四因子基线 holdout +0.73pp > -0.5pp），五因子
   基线上 T5 的 holdout -1.77pp 已超标
3. **五因子 v2（无过滤）保持为 v16 候选基线**，不加过滤层。
   过滤层在四因子基线上是净正贡献（v14 vt+t5 adopted），但在
   五因子基线上 g2 已提供了逆风保护，过滤层的边际增量被稀释且
   带来 holdout 侵蚀
4. **过滤层形态在五因子基线上收口**：不再追加过滤层实验

## 6. 实盘形态建议

- **最终实盘基线 = 五因子 v2（ep+bm+div+accruals+g2，无过滤）**
- 现有 v8+v11 模拟盘不动，作为四因子对照继续运行
- 信号管道需扩展 composite_score 为五因子版本（加 g2 列、门槛
  ≥4/5），另立落地任务

## 7. 产物

| 文件 | 内容 |
|---|---|
| `research/protocols/a_share_value_growth_five_factor_strategy_protocol_v16.md` | 协议（冻结） |
| `scripts/backtest_a_share_value_growth_five_factor_v16.py` | 回测脚本（三臂） |
| `output/analysis_fundamental/a_share_value_growth_five_factor_strategy_v16_t5_revf/` | 全套结果 |

## 8. 遗留

- 五因子版本的信号管道落地（composite_score 扩展 + g2 数据接入）
  是工程任务，非研究实验
- 业绩预告增速（forecast，2022 起）仍未测，作为成长因子的
  高频领先版本可另立事件族实验
