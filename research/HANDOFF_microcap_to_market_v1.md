# 会话交接记录 v1：干净微盘线收官与全市场实验待办

> **文档定位**：会话交接。记录 2026-08-31 ~ 2026-09-10 本会话完成的全部
> 实验（九族因子扫描 + 干净微盘线三段组合实验）与结论，以及下一步待做
> 实验的完整设计。供新会话直接接手，**避免重复研究、避免遗漏结论**。

---

## 一、本会话完成的工作总览

### 1.1 主线背景（接手前必读）

- **项目主线**：五因子（ep/bm/div/accruals/g2）top30_cap3 月度策略，
  信号管道已升级（`run_daily_signal_pipeline_v1.py`），用户决定**不再
  在五因子上继续开发**，转向新方向探索；
- **用户原始诉求**：开发更灵活的日频（5日/10日）策略；
- **探索路径**：本会话沿"干净微盘域"展开（末10%市值- ST- 退市整理-
  准ST，沪深三板块、排除北交所），最终月度 enhance 形态被验证为该域
  唯一可行形态，短周期正式关闭。

### 1.2 已完成实验清单（按时间序，全部有协议+closure+数据落盘）

| # | 实验 | 协议 | closure | 核心结论 |
|---|---|---|---|---|
| 0 | 北交所市值统计 / 末10%池画像 | — | — | 北交所中位 16 亿≈沪深末10%；末10%池 43% 是 ST/准ST |
| 1 | 前瞻 ST 风险（bps<0/连续两年亏损） | 会话内 | 会话内 | 全市场 948 只准ST；微盘池 43% 风险；**"连续两年亏损"2年窗口"跑赢"被证实为规模β伪装+幸存者偏差（106只已退市股终值-76%）** |
| 2 | 干净微盘域 10 年回测 | 会话内 | 会话内 | 费前 +32.9%/yr vs 全市场 +8.2%；剔除 ST/准ST 收益不降、MDD 改善 4.7pp；落盘 `b10_clean_vs_market_monthly_v1.csv` |
| 3 | 困境分层（准ST拆分 G1/G2） | `a_share_distress_split_protocol_v1.md` | `a_share_distress_split_closure_v1.md` | G1 主业崩坏 4/5 窗口稳定跑输；2y"反超"为行情驱动 |
| 4 | **Alpha101 双臂**（31 因子） | `a_share_alpha101_dual_arm_protocol_v1.md` | `a_share_alpha101_dual_arm_closure_v1.md` | 10 候选全过规模正交化；**alpha101_13/16（量价负协方差）IC 0.07/ICIR 0.72**；与 Alpha158 冗余仅 7/31（预注册怀疑被否定） |
| 5 | **干净微盘组合回测**（top-N） | `clean_microcap_combo_protocol_v1.md` | `clean_microcap_combo_closure_v1.md` | **top-N 6/6 臂全灭**（base 成本下亦负超额）；2024 崩盘段 top 臂更深；"IC 正≠可交易"第三例 |
| 6 | **分层单调性**（标准阶梯第4步补课） | `alpha101_quintile_shape_protocol_v1.md` | `alpha101_quintile_shape_closure_v1.md` | Z1 形状=倒U（信息峰 Q4，Q4−Q1 t=2.80）；top-N 死因="为无增量尖端付集中度代价"；修正上轮"头部有毒"误诊 |
| 7 | **Q4 型构造回测** | `clean_microcap_q4_protocol_v2.md` | `clean_microcap_q4_closure_v2.md` | 分位臂扛不住 microcap 摩擦（+6.4pp→-0.4pp）；**enhance 全池加权唯一存活（+2.0pp 稳定）**；修复 qlib 量纲坑（成交额=(close/factor)×vol×100） |
| 8 | **Growth 15 因子双臂** | `growth15_dual_arm_protocol_v1.md` | `growth15_dual_arm_closure_v1.md` | **pa（ROA 加速度）唯一候选**（域内 IC 0.026/t 2.26/4-5年，全市场仅 0.005）；水平类 yoy_* 集体失效；peg 异常率 100% |
| 9 | **Liquidity 35 因子双臂** | `liquidity35_dual_arm_protocol_v1.md` | `liquidity35_dual_arm_closure_v1.md` | 4 个 BIAS 换手冷却候选（负 IC、t 2.3+、与 Z1 正交）；换手率水平域内 IC -0.08 强但价差不显；**持有期符号翻转**（h=5 正→月度负） |
| 10 | **Momentum 20 因子双臂** | `momentum20_dual_arm_protocol_v1.md` | `momentum20_dual_arm_closure_v1.md` | **MACD（t=2.24）/ alpha_1000d_000300（t=2.04）** 两反转候选；alpha_1000d 全市场 IC -0.093 强于域内 3 倍（→全市场清单）；pandas DataFrame/Series 对齐三坑记录 |
| 11 | **Quality 59 因子双臂** | `quality59_dual_arm_protocol_v1.md` | `quality59_dual_arm_closure_v1.md` | **delta_gpm/roe/roa 三候选**（全市场 IC≈0 的**微盘特异**信号）；delta_roe~roa 相关 0.94 归并；"只看变化不看水平"定律确立 |
| 12 | **Reversal 3 因子双臂** | `reversal3_dual_arm_protocol_v1.md` | `reversal3_dual_arm_closure_v1.md` | 0 候选，轴闭合；small_cap_reversal=return_21d 精确换肤（相关-1.00）；rsi 方向最强（-0.063/5-5）但价差不过；price_dist 月度证伪（日内口径为开放项）；**三因子失效类型学**（冗余/构造错配/尺度错配） |
| 13 | **Size 3 因子双臂** | `size3_dual_arm_protocol_v1.md` | `size3_dual_arm_closure_v1.md` | 0 独立候选；size 域内 IC +0.053（5/5 年）=规模梯度在域内延续但均匀涂抹；**规模轴=域地基，只能全池持有变现** |
| 14 | **Value 11 因子双臂（九族收官）** | `value11_dual_arm_protocol_v1.md` | `value11_dual_arm_closure_v1.md` | 0 增量候选，价值轴被主线 ep/bm 覆盖；主线锚双臂均不过线→**主线 alpha 来自复合结构而非单因子** |
| 15 | **实验一：5 簇融合回测** | `clean_microcap_final_dual_protocol_v1.md` | `clean_microcap_fusion_closure_v1.md` | **fusion_adopted：费后 +24.1%/IR 0.89/超额 +4.3pp（vs Z1 单源 +3.4pp）**；归并后 5 簇（Z1/盈利改善/换手冷却/MACD/波动惩罚） |
| 16 | **实验二：Z1 短周期 enhance 专项** | 同上 | `clean_microcap_shortcycle_closure_v1.md` | **short_cycle_closed**：p10 +0.9pp/p15 +0.5pp 不达 +1pp 门槛；灵活调仓诉求在微盘域完整闭环（两种构造×四周期全排除） |

### 1.3 最终形态（干净微盘线终点，已归档）

> **域**：沪深三板块末 10% 市值 − ST/退市整理 − 准ST（bps<0 或连续两年
> 年报亏损），月末重建，约 300~400 只；
> **信号**：5 簇融合（簇内等权 rank 均值→跨簇等权）：
> ① Z1 量价背离合成；② delta_gpm+pa 盈利改善；③ bias_std_turn 换手
> 冷却；④ MACD 负向；⑤ return_std_21d 负向（Q4 峰形态）；
> **构造**：enhance 全池加权 = 等权 ×(1+0.5×(rank−0.5))，无删票；
> **周期**：月度调仓，T+1 开盘成交；
> **费后画像**（microcap 0.80% 单边最悲观）：**+24.1%/年，IR 0.89，
> MDD −30.3%，月均换手 15.8%**。

### 1.4 用户对本线最终形态的评判（重要，接手必读）

用户明确判断：**"+4.3pp 信号超额对个人策略太低，风险收益不成比例"**
（信号超额骑在 -30% MDD 的微盘 β 上，且全池持有对个人不可执行）。
**微盘线就此收口**，结论全部归档但不再投入。用户意向指向**全市场口径
的因子验证**（摩擦低、构造空间大、单位研究投入的超额产出更高）。

---

## 二、下一阶段待做实验（按优先级）

### 2.1 【优先级最高】全市场存活候选的组合验证

**背景**：九族扫描的双臂设计里全市场臂只算了 IC（日频/月度），**从未
做过全市场分组价差、分年一致性、扣成本组合回测**。现有全市场存活候选
见 `output/analysis_static/market_survivors_candidates_v1.csv`
（19 个 |IC|≥0.05）与进度快照
`output/analysis_static/market_survivors_progress_snapshot_v1.md`。

**重点候选（第一梯队，两臂同向都强）**：
- `sum_abs_rtn_amount_20d`（Amihud 非流动性，全市场 IC +0.096）
- `amount_ma_20d`（-0.090，负向）
- BIAS 换手冷却族（-0.07~-0.09）

**第二梯队（全市场特有，域内反向，yoy_total_asset +0.144 vs 域内
-0.085）**：应作为**独立的全市场信号**立项，绝不并入微盘域。

**实验设计要点**：
1. 全市场 quintile 分组 + 价差 t 检验（复用 `alpha101_quintile_shape`
   框架，换域重跑）；
2. 全市场组合回测：top-N 与分位带两构造 × 三档成本（全市场成本可低于
   microcap 档，建议 0.15/0.30/0.50% 三档）；
3. 对照臂：全市场等权、中证1000；
4. 判定：净超额 ≥+3pp 且 IR≥0.5（沿既有门槛）。

### 2.2 【次优先】ML 因子合成（LightGBM 排序）

- 特征集：178 个已实现因子的 PIT 面板（代码全在
  `scripts/analyze_*_dual_arm_v1.py` 各文件内，需整合）；
- 粗筛：只剔 |IC|<0.01 纯噪音，**not_qualified 的因子要保留**（ML 的
  增量恰恰来自弱信号组合与交互效应）；
- 模型：LightGBM ranker，深度 3~4 防过拟合；2016-2023 训练、
  2024-2026 滚动测试；
- **对照臂必须含 Z_final 线性融合（+4.3pp）**——ML 只有在非线性增益
  真实存在时才值得用；
- 判定：同 enhance 门槛，且需 > 线性融合。
- **注意**：用户若继续认为微盘域性价比不足，ML 可直接做全市场口径。

### 2.3 【可选】微盘线模拟盘验证（仅在用户愿意保留卫星配置时）

- 融合 enhance 挂模拟盘 6~12 个月做样本外验证；
- 定位应为分散配置卫星仓（β 风险需仓位预算管理），非主策略。

### 2.4 【工程债】git 提交与 manifest

- 本会话全部新文件未提交（协议/closure/脚本/output）；
- 缺一份 `clean_microcap_line_manifest_v1.md` 汇总文档；
- 提交建议：feat（脚本+output）+ docs（协议/closure）分两个 commit。

---

## 三、关键方法论教训（新会话直接复用，勿再踩坑）

1. **IC 正 ≠ 可交易**（三次验证：换手率因子、PV 日频、Alpha101 top-N）；
   组合回测是唯一裁决；
2. **双臂设计是默认**：域内结论不可外推全市场（yoy_total_asset 两域
   反向实证）；
3. **先分层后构造**（标准阶梯第 4 步先于第 7 步）：信息峰位置决定
   构造——倒U/enhance、单调/top-N、中段/分位带；
4. **水平 vs 变化定律**：微盘域基本面定价只认"变化"（delta_*/pa 存活），
   不认"水平"（roe/ep/yoy_* 全灭）；
5. **持有期符号翻转**：换手率 h=5 正 → 月度 -0.08；因子结论必须绑定
   持有期口径；
6. **微盘成本铁律**：月均换手 >50% 在 0.8% 单边下必死；月度是唯一
   可行频率（两种构造×四周期完整排除）；
7. **qlib 量纲**：volume=手、close=后复权，成交额=(close/factor)×
   vol×100（与 tushare 误差<3%）；
8. **pandas 对齐三坑**：DataFrame×Series 按列对齐（数值运算、除法、
   where 均如此），跨 index 运算必须显式 axis=0/'index' 或显式广播；
9. **失效三类型**：方向错（真死）/信息薄（弱，可 ML 回收）/口径错
   （假死，换口径重测）。

---

## 四、关键文件索引

| 类别 | 位置 |
|---|---|
| 本阶段全部协议（9 份） | `research/protocols/*dual_arm*`、`*distress*`、`*clean_microcap*` |
| 本阶段全部 closure（11 份） | `research/decisions/*closure*`（本会话新增 11 份） |
| 实验脚本 | `scripts/analyze_{alpha101,liquidity35,momentum20,quality59,growth15,size3,reversal3,value11,risk25}*.py`、`analyze_a_share_distress_split_v1.py`、`backtest_clean_microcap_*.py`、`analyze_board_segmentation_v1.py`、`export_pa_npttm_factors_v1.py` |
| 因子面板 | `output/analysis_static/growth15_dual_arm_v1/factor_panel_*.csv.gz` |
| 双臂 IC 主表 | `output/analysis_static/market_vs_domain_ic_master_v1.csv`（77 因子） |
| 全市场存活候选 | `output/analysis_static/market_survivors_candidates_v1.csv`（19 个） |
| 进度快照 | `output/analysis_static/market_survivors_progress_snapshot_v1.md` |
| 融合实验 | `output/analysis_fundamental/clean_microcap_fusion_v1/` |
| 短周期实验 | `output/analysis_fundamental/clean_microcap_shortcycle_v1/` |

## 五、变更记录

| 日期 | 变更 |
|---|---|
| 2026-09-10 | 创建：本会话 16 项实验的完整清单与结论、最终形态与用户评判、下一阶段三路线实验设计（全市场验证优先）、方法论九条、文件索引 |
