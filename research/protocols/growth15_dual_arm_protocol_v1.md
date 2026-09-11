# Growth 15 因子假设检验协议 v1（干净微盘域 + 全市场对照）

## 1. 状态与授权

状态：`frozen_awaiting_run`（2026-09-05）

前置链：
- `clean_microcap_q4_closure_v2.md`：干净微盘线收口，enhance 全池增强为
  唯一带出线构造（+2pp/marginal）；Z1（量价背离）为唯一存活信号；
- 用户指示（2026-09-05）：探索 tushare 因子库 Growth 类（15 个）。

**动机假设**：Growth 类因子是**基本面慢变量**（季频财报驱动、PIT 可得），
与已收口的量价信号（快变量、换手重、被微盘摩擦杀死）**不同轴**。若
Growth 因子在干净微盘域内有截面区分度，其变现形态天然适配**月度调仓 +
enhance 轻权重**（换手低、无集中度风险）——这正是量价信号走不通的路。
同时 g2（dt_netprofit_yoy）已是五因子主线成员，本实验可顺带回答"Growth
族在微盘域是否有 g2 之外的增量"。

## 2. 因子集与复现（冻结）

tushare 文档 Growth 类 15 个，按数据可得性全部复现（原料覆盖率均 >93%）：

| # | 因子 | 公式要点 | 本项目原料 |
|---|---|---|---|
| 1 | peg_252d | PE / (EPS 增速×100) | close/eps（daily_basic + fina） |
| 2 | np_ttm_qoq | 净利 TTM 环比 | n_income_attr_p TTM（income 表） |
| 3 | yoy_net_profit | 净利同比 | netprofit_yoy |
| 4 | yoy_ocf | 经营现金流同比 | ocf_yoy |
| 5 | sa | 每股营收增长加速度 | total_revenue_ps / total_share |
| 6 | gross_margin_qoq | 毛利率 TTM 环比 | gross_margin |
| 7 | pa | ROA 增长加速度 | roa（TTM 差分再差分） |
| 8 | yoy_roa | ROA 同比 | roa |
| 9 | yoy_net_asset | 净资产同比 | bps×total_share（daily_basic） |
| 10 | yoy_revenue | 营收同比 | or_yoy |
| 11 | yoy_roe | ROE 同比 | roe |
| 12 | yoy_total_asset | 总资产同比 | total_assets（balancesheet） |
| 13 | eaa | EPS 增长加速度 | eps |
| 14 | eap | EPS/价格增长加速度 | eps/close |
| 15 | asset_growth_qoq | 总资产环比 | total_assets |

复现口径：全部 **PIT**（available_date/ann_date ≤ 观察日，同 (ts_code,
end_date) 取最新）；"同比 252 天"在季频数据上实现为**同期财报同比**
（同 end_date 月份、上一年），"环比 63 天"实现为**上一报告期环比**；
加速度 = 增速 − 增速的上一期。方向：文档原始方向（增长为正 = 分数高），
不翻面。TTM 用最近 4 个季度报告期求和（n_income_attr_p / n_cashflow_act）。

## 3. 双臂与母池（冻结）

- **臂B（主，干净微盘域）**：与 alpha101/quintile 各轮完全一致——
  月度重建（月末末10% - ST - 退市整理 - 准ST），沪深三板块，排除北交所；
- **臂A（对照，全市场）**：沪深三板块剔除 ST/退市（隔日抽样 1/3 交易日）。

## 4. 检验设计（冻结）

- 样本窗：2022-01 ~ 2026-08（与量价各轮一致），财务 PIT 天然覆盖；
- 标签：月度（月末组合口径，与 quintile 轮一致：月末收盘分组、次月同日
  收盘结算，费前）+ **h=5 日频 IC（辅助口径）**；
- 每因子：**月度截面 RankIC**（月末分组前一日计算因子值）中位、ICIR、
  分年同号（2022~2026）、Q4−Q1 与 Q5−Q1 分组价差 t 检验（复用 quintile
  框架）；
- 冗余判定（先于结论）：15 因子互相关矩阵 + 与 g2（dt_netprofit_yoy）
  的相关——**与 g2 相关 >0.80 的因子标记"主线已有"**，其域内表现仅
  记录不立项。

## 5. 预注册判定（冻结）

对每个因子独立判定（15 次检验，以双门槛控多重性）：

主判定（域内，月度口径）：
- 月度 RankIC 中位 |IC| ≥ 0.02 且 Q4−Q1 或 Q5−Q1 价差 t ≥ 2 且分年
  同号 ≥4/5 → `growth_domain_candidate`；
- 三条件缺一 → 不立项（记录）。

附加判定（仅对 candidate）：
- 与 g2 相关 <0.60 → `incremental_over_mainline`（主线增量，优先进入
  enhance 权重实验）；
- 与 g2 相关 ≥0.60 → `mainline_duplicate`（记录，不重复建设）。

出口：
- candidate 数 = 0 → `growth_no_domain_value`：基本面慢变量在微盘域
  无截面增量，域的收益纯靠规模 β 与量价背离，本方向关闭；
- 有 candidate 且 incremental → 进入 enhance 权重融合实验（Z1 + Growth
  合成），走 q4 协议同款回测判定；
- 有 candidate 但全部 mainline_duplicate → `growth_absorbed_by_g2`：
  结论为"g2 已覆盖 Growth 族"，主线不动。

## 6. 产物

`output/analysis_static/growth15_dual_arm_v1/`：
`ic_summary.csv`、`corr_matrix.csv`、`g2_correlation.csv`、
`quintile_shape.csv`、`decision.json`。

## 7. 风险预告（预注册的怀疑）

1. 微盘域内增长因子的有效性存疑：微盘定价者是散户/游资，财报信息
   扩散慢可能被炒作噪音淹没——IC 预期弱于全市场口径（与量价因子相反
   的域效应），这正是双臂设计要测的；
2. 增长因子在 A 股的有效性历史证据偏弱（石川等：A股成长因子长期 IC
   偏低），15 个里预计过双门槛的 ≤3 个；
3. 极端增长值（扭亏、并购导致的增速爆炸）在 rank 化后仍有影响，
   qoq/加速度类因子（差分再差分）对财报噪音尤其敏感——分年同号
   门槛是主要防线；
4. peg_252d 用 EPS 增速作分母，微盘亏损股 EPS 增速为负或接近 0 时
   PEG 语义崩坏（负增速 → 负 PEG → 排名错乱），该因子单独报告
   异常率，若 >20% 则其结论降级。
