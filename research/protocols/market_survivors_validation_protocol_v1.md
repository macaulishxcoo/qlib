# 全市场存活候选组合验证协议 v1

## 1. 状态与授权

状态：`frozen_awaiting_run`（2026-09-11）

前置链：
- `market_survivors_progress_snapshot_v1.md`：19 个全市场存活候选
  （|IC|≥0.05），**只有 IC，无分组价差、无分年一致性、无组合回测**；
- `clean_microcap_fusion_closure_v1.md`：微盘线融合形态收口但被用户
  判定性价比不足，主线转向全市场口径；
- `a_share_distress_split_closure_v1.md`：**"连续两年亏损跑赢"被证实为
  规模β伪装**——本实验对流动性/规模族候选保留同等强怀疑；
- 微盘线三例"IC 正 ≠ 可交易"：组合回测是唯一裁决。

**先验声明（预注册的强怀疑）**：
1. `sum_abs_rtn_amount_20d`（Amihud）与 `amount_ma_20d` 本质是**规模的
   代理**（小票天然 Amihud 高、成交额低），全市场 IC 可能是规模β伪装——
   必须过规模中性臂才能定罪/脱罪；
2. BIAS 换手冷却是**拥挤度反转**（近期换手相对长期降温），已知与换手率
   水平因子同源，而换手水平因子组合层曾 dead——价差过线但组合不过线的
   风险真实存在；
3. `yoy_total_asset` 两域反向（全市场 +0.144 / 微盘 -0.085）是扩张股
   （成长风格）暴露，其全市场表现可能被 2022-2026 特定风格段驱动——
   分年一致性是关键裁决。

## 2. 信号集（冻结，22 个）

来源 `market_survivors_candidates_v1.csv` + 快照第三梯队 + 换手激增补充：

| 梯队 | 信号 | 方向（IC符号） |
|---|---|---|
| T1 第一梯队 | sum_abs_rtn_amount_20d / amount_ma_20d / bias_std_turn_42d_252d / bias_std_turn_21d_252d / bias_turn_63d_252d | + / − / − / − / − |
| T2 第二梯队 | yoy_total_asset / asset_growth_qoq | + / + |
| T3 第三梯队 | alpha101_{13,16,15,12,3,6,4,19,52,14} | +（同微盘域方向） |
| 补充 | turn_surge_21d_252d（换手 1月/12月比，快照 -0.064 附近） | − |
| 基准诊断 | total_mv（规模本身） | + |

复现口径沿用 liquidity35/alpha101 脚本：换手率=量(手×100)/总股本
（daily_basic 月末 total_share 前向填充），成交额=(close/factor)×vol×100，
alpha101 公式与 quintile_shape 脚本逐行一致。

`yoy_total_asset` PIT 面板**本次扩深**：fina_indicator `assets_yoy`
（2009-2024 报告期，available_date 全）∪ recent_3tables balancesheet
（2022Q4-2026Q2）重算同比/环比，concat 后按 (ts_code, end_date,
available_date) 去重留最新。`asset_growth_qoq` 仅 balancesheet 可算
（截面自 2023-04 起），**只进 Stage A，不进 Stage B 单源臂**。

## 3. Stage A：全市场 quintile 形状检验（冻结）

- **域**：沪深三板块（非北交所）− ST/退市整理期（调仓日时点状态）−
  上市不满 120 个交易日的次新股；
- 分组：调仓月首日 T 截面 qcut 5 等份，T+1 开盘买，下月首日 T+1 开盘卖，
  费前；对照 ALL=域等权；
- 报告：Q5−Q1 月均价差、t、分年同号、Spearman rho 形状分类、各分组
  平均 total_mv（规模阶梯诊断）、Q5 涨停/停牌占比；
- 另算一份**无剔除口径的月度 RankIC**（含 ST/次新，与 master 表对账，
  确认与 candidates CSV 的 market_ic 同向同量级）。

## 4. Stage B：全市场组合回测（冻结）

调仓机制与微盘线完全一致：月度，T 日信号 → T+1 开盘买入 → 下月首日
T+1 开盘卖出；成本按换手双边计提。可执行性过滤（微盘线未加、本线新加）：
买入日涨停（对前收 ≥9.5%）或停牌（volume=0）的票剔除，权重按存活票
等权重归一。

**臂**（等权构造）：

| 臂 | 构造 |
|---|---|
| bias_cool_top30 | bias_std_turn_21d_252d 最小 30（做多冷却端） |
| a101_comp_top30 | Stage A 单调存活 7 因子（alpha101_13/16/15/3/6/4/14）rank 均值前 30 |
| z_comp_v0_top30 | 协议冻结 4 源：rank(amihud)+rank(−amount)+rank(−bias_std_42_252)+rank(yoy_ta)，前 30 |
| z_comp_v1_top30 | **主判定臂**：Stage A 存活源（a101 7 单调 + bias_std_21d 冷却端）rank 均值前 30（≥3 源非缺失） |
| z_comp_v1_top100 | 同上取前 100（宽度对照） |
| **z_neutral_top30** | **规模中性版**：z_comp_v1 在 total_mv 十分位内重排名后取前 30 |
| pool_ew | 域等权对照 |
| csi1000 | sh000852 收盘价对照（费前） |

**成本三档**：0.15% / **0.30%（主判定档）** / 0.50%（单边）。

**修订说明（2026-09-11，Stage A 落地后、Stage B 跑批前）**：协议 §5
原定主判定臂 z_comp_top30 的 4 源中，Stage A 显示 amihud（价差 t 1.34
不显著 + Q5/Q1 市值比 0.315 规模β）、amount_ma_20d（t −1.28 不显著）、
yoy_total_asset（真实 IC −0.014，master +0.144 为 4 个月样本伪影）三源
在分层层降级。按"先分层后构造"阶梯（方法论 3），复合源改为 Stage A
存活信号（a101 7 单调 + bias 冷却端），命名 z_comp_v1；原冻结 4 源保留
为 z_comp_v0 对照臂。修订在 Stage B 运行前完成，信号集与构造路由均为
预注册规则的机械应用，非事后拟合。

## 5. 预注册判定（冻结）

主判定（z_comp_v1_top30，0.30% 档）：
- **存活**：年化净超额（vs pool_ew）≥ +3pp 且 IR ≥ 0.5 且 2024-01/02
  崩盘段回撤不差于 pool_ew 超过 5pp；
- **规模β伪装**：主判定臂过线但 z_neutral_top30 不过线 → 判"规模β伪装"，
  关闭全市场口径该组合（与困境线"规模β伪装"判例同款处理）；
- 其余臂（bias_cool / a101_comp / z_comp_v0 / top100 / 中性臂）过线与否
  仅作归因与稳健性，不作存活判定（多重比较防护：只允许一个主判定臂）；
- 分年一致性：主判定臂年化超额分年同号 ≥4/5 才可宣称稳定。

## 6. 输出

- Stage A：`output/analysis_static/market_survivors_quintile_v1/`
  （quintile_monthly_returns.csv / shape_summary.csv / reconciliation_ic.csv / decision.json）
- Stage B：`output/analysis_fundamental/market_survivors_bt_v1/`
  （backtest_summary.csv / yearly_excess.csv / crash_2024.csv / decision.json）
- 脚本：`scripts/analyze_market_survivors_quintile_v1.py`、
  `scripts/backtest_market_survivors_v1.py`
- closure：`research/decisions/market_survivors_closure_v1.md`

## 7. 变更记录

| 日期 | 变更 |
|---|---|
| 2026-09-11 | 创建：22 信号 Stage A 分层 + 9 臂 Stage B 回测，预注册规模β怀疑与中性臂裁决 |
