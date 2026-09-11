# 干净微盘线资产清单 manifest v1

> **文档定位**：微盘线（2026-08-31 ~ 2026-09-10 会话）全部研究资产汇总。
> 该线已收口（用户判定信号超额 +4.3pp 性价比不足），本文档为归档索引，
> 供回溯。完整实验结论见 `HANDOFF_microcap_to_market_v1.md`。

## 1. 线路全景

```
北交所统计 → 干净微盘域构建（10年回测 +32.9%/yr 费前）
  → 困境分层（准ST 拆分 G1/G2）
  → 九族因子双臂扫描（202 原始因子 → 178 实现 → 域内候选 24 → 归并 7 源）
  → top-N 组合（6/6 全灭）→ 分层形状（倒U，Q4 信息峰）→ Q4/enhance 构造
  → 5 簇融合回测（fusion_adopted：费后 +24.1%/IR 0.89/超额 +4.3pp）
  → 短周期专项（closed）
```

## 2. 协议（11 份，research/protocols/）

| 协议 | 主题 |
|---|---|
| a_share_distress_split_protocol_v1 | 准ST 拆分 G1/G2 分层 |
| a_share_alpha101_dual_arm_protocol_v1 | Alpha101 双臂扫描 |
| growth15_dual_arm_protocol_v1 | Growth 族双臂 |
| liquidity35_dual_arm_protocol_v1 | Liquidity 族双臂 |
| momentum20_dual_arm_protocol_v1 | Momentum 族双臂 |
| quality59_dual_arm_protocol_v1 | Quality 族双臂 |
| reversal3_dual_arm_protocol_v1 | Reversal 族双臂 |
| size3_dual_arm_protocol_v1 | Size 族双臂 |
| value11_dual_arm_protocol_v1 | Value 族双臂（九族收官） |
| alpha101_quintile_shape_protocol_v1 | 分层单调性（标准阶梯第4步） |
| clean_microcap_q4_protocol_v2 / clean_microcap_final_dual_protocol_v1 | 构造回测 / 融合+短周期双实验 |

## 3. Closure（15 份，research/decisions/）

alpha101_quintile_shape / clean_microcap_fusion / clean_microcap_q4_v2 /
clean_microcap_shortcycle（short_cycle_closed）/ growth15 / liquidity35 /
momentum20 / quality59 / reversal3 / risk25 / size3 / value11（以上 *_closure_v1）
a_share_distress_split_closure_v1 / mainboard_bottom20_dual_arm_closure_v1 /
mainboard20_enhance_closure_v1（主板末20%线，+2.0pp marginal）

## 4. 脚本（scripts/）

- 双臂扫描：`analyze_{alpha101,growth15,liquidity35,momentum20,quality59,reversal3,size3,value11,risk25}_dual_arm_v1.py`
- 分层/构造/融合：`analyze_alpha101_quintile_shape_v1.py`、
  `backtest_clean_microcap_q4_v2.py`、`analyze_clean_microcap_fusion_v1.py`、
  `analyze_clean_microcap_shortcycle_v1.py`
- 域构建/画像：`analyze_a_share_distress_split_v1.py`、
  `analyze_board_segmentation_v1.py`、`analyze_mainboard20_*.py`、
  `backtest_mainboard20_enhance_v1.py`
- 数据导出：`export_pa_npttm_factors_v1.py`

## 5. 数据产物（output/，gitignore 外，本地留存）

- 因子面板：`output/analysis_static/*_dual_arm_v1/factor_panel_*.csv.gz`
- 双臂 IC 主表：`output/analysis_static/market_vs_domain_ic_master_v1.csv`（77 因子）
- 全市场存活候选：`output/analysis_static/market_survivors_candidates_v1.csv`（19 个）
- 分层/融合/短周期：`output/analysis_static/alpha101_quintile_shape_v1/`、
  `output/analysis_fundamental/clean_microcap_{fusion,shortcycle}_v1/`

## 6. 最终形态一句话

域=沪深末10%−ST−准ST；信号=5簇融合（Z1量价背离/盈利改善/换手冷却/
MACD负向/波动惩罚）；构造=enhance 全池加权 1+0.5×(rank−0.5)；月度
T+1 开盘；费后 +24.1%/IR 0.89/MDD −30.3%。**已收口，不作为主策略**。

## 7. 变更记录

| 日期 | 变更 |
|---|---|
| 2026-09-11 | 创建：微盘线收官归档 manifest（交接工程债清偿） |
