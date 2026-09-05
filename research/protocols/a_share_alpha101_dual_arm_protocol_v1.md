# Alpha101 双臂假设检验协议 v1（干净微盘域 vs 全市场）

## 1. 状态与授权

状态：`frozen_awaiting_run`（2026-09-04）

前置证据：
- 日频量价 alpha 测尽清单（`a_share_daily_alpha_exhaustion_manifest_v1.md`）：
  Alpha158 同源量价方向 2021 后衰减、组合层不可交易；
- 主升浪复验：量价"有效"因子与 Alpha158 判定 duplicate（|corr|>0.95）/
  near_duplicate（>0.70）——形状差异≠信息增量；
- 干净微盘域（末10% - ST - 准ST）：2016-2026 费前年化 +32.9%（规模 β 已验证）。

**动机假设**：Alpha101（WorldQuant 算子代数：Rank/Ts_Rank/Corr/Cov/Delta/
SignedPower/Ts_ArgMax 深嵌套）与 Alpha158 输入同源（OHLCV+VWAP 日线），
但其"极值位置/分段函数/深嵌套秩"结构是 Alpha158 没有的形状。要测的是：
**这些形状在（a）全市场、（b）干净微盘域内是否有独立的横截面选股信息，
以及（b）中是否存在域内增量（域内 RankIC 高于全市场，或与规模暴露正交后仍显著）。**

## 2. 因子集与复现（冻结）

- tushare 因子库文档（doc_id=486）公开的 **31 个 Alpha101 因子**（alpha101_1
  ~ alpha101_31，编号按文档顺序，缺 21/24/27/29/30/31 等文档未列号者以文档
  实际列出为准）；
- 复现口径：qlib 表达式引擎优先（Rank/Ts_Rank/Corr/Cov/Delta/Std/Mean/Max/
  Min 原生支持），IF/SignedPower/Ts_ArgMax 等用逐股 pandas 实现；输入一律
  后复权 close/open/high/low/vwap/volume（`cn_data_2026`）；
- 缺失值处理：因子值截面 rank 化前不做填充；单日截面有效样本 < 30 时该日
  剔除。

## 3. 双臂与母池（冻结）

- **臂A（全市场）**：沪深三板块（沪/深主板+创业板+科创板，排除北交所），
  剔 ST/退市整理（PIT）与停牌日样本；
- **臂B（干净微盘域）**：臂A ∩ 月末市值末10%（动态阈值）∩ 非准ST
  （PIT: bps<0 或 连续两年年报亏损）。域每月末重算，月内固定。

两臂样本不独立（B ⊂ A），判定重点在 B 与 A 的**差分**而非绝对值。

## 4. 检验设计（冻结）

- 样本窗：2022-01-01 ~ 2026-08-31（与主升浪复验同窗，含 2026 衰减段），
  数据预热自 2021-01-01（长窗口因子需要）；
- 标签：T+1 开盘成交 h=5 收益 `open[t+1+h]/open[t+1]-1`（labelfix 后正确
  口径）；同时报 h=10 做稳健性；
- 每因子每日截面 Spearman RankIC，报告中位数、ICIR、IC>0 占比、分年度
  中位数（2022~2026）；
- 冗余判定（先于 IC）：31 因子 × Alpha158 158 特征逐日横截面 Spearman
  中位数：|corr|>0.95 duplicate、>0.70 near_duplicate、否则 distinct
  （沿用主升浪复验口径）。

## 5. 预注册判定（冻结）

对每个因子独立判定（30 次检验，多重性以"分年一致性+域内增量"双重约束
控制，不做 Bonferroni——目的是筛候选而非发表）：

主判定（域内增量，臂B）：
- 域内 RankIC 中位 |IC| ≥ 0.03 且 ICIR ≥ 0.30 且 2022-2026 五年同号 ≥4 年
  → `domain_candidate`

附加判定（仅对 domain_candidate 做）：
- 与规模暴露正交（域内因子值对 log(size) 截面回归取残差）后 RankIC 仍
  |IC| ≥ 0.02 → 增量独立于规模，`orthogonal_confirmed`；
- 域内 IC − 全市场 IC ≥ +0.01 → 微盘域内有特异性，`domain_specific`。

出口：
- domain_candidate 数 = 0 → `alpha101_no_domain_value`：量价公式门彻底关闭，
  新方向信号层转向基本面/风格类；
- 有 domain_candidate 但正交性全灭 → `alpha101_size_proxy_only`：只是规模
  的另一种度量，并入域规则而非信号层；
- 有 ≥1 个 orthogonal_confirmed → 进入下一轮（域内组合构造/扣成本回测），
  因子名记录在案。

## 6. 产物

`output/analysis_static/alpha101_dual_arm_v1/`：
`ic_summary.csv`（因子×臂×h 完整表）、`redundancy_vs_alpha158.csv`、
`yearly_ic.csv`、`decision.json`、`methodology.json`。

## 7. 风险预告（预注册的怀疑）

1. 31 因子中预计 ≥2/3 与 Alpha158 duplicate/near_duplicate——**这本身是
   结论的一部分**，不视为实验失败；
2. 微盘域内量价因子 IC 普遍会被高波动放大（噪声大 → |IC| 虚高），域内
   判定必须配分年一致性门槛，防止单年行情拟合；
3. 2022-2026 含 A 股量化拥挤度快速上升段，域内任何量价 IC 都可能处于
   衰减通道——单轮通过不代表长期存活，采纳后需年度复检。
