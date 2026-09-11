# Risk 25 因子假设检验协议 v1（干净微盘域 + 全市场对照）

## 1. 状态与授权

状态：`frozen_awaiting_run`（2026-09-09）

前置链与先验：
- 主升浪轮：TIGHTNESS（与 STD 相关 0.94）负 IC -0.057、"高波动低收益"
  是 A 股已知彩票偏好/特质波动异象；
- Momentum 轮：本族近亲 price_position_ir/sharpe 类方向偏负；
- 学术先验：特质波动率异象（Ang et al. 2006）——高特质波动 → 低收益，
  A 股散户市更强；
- **先验声明**：25 个因子里 return_std_*(5 个)、high_low_*(5 个)、
  sharpe/adjusted_sharpe(2 个) 本质是"波动率及其变换"，预期**负 IC**
  且与 Z1 正交（Z1 是量价协方差非波动）；beta_*(7 个) 是系统性风险
  ——在等权微盘组合中 beta 的定价含义弱（无对冲工具），预期 IC≈0；
  sigma/beta_consistency(3 个) 是特质风险，与 std 同族；volume_beta(1)
  是量的 beta，新颖；**log_price(1) 放在 Risk 族名不副实**——它是
  价格水平因子，与 ma_20d 同类（Momentum 轮 IC +0.024 未过线），
  且与规模高相关，预期是"低价股效应"代理。

## 2. 因子集与复现（冻结，25 个）

| 组 | 数量 | 因子 | 实现 |
|---|---|---|---|
| R1 波动率 | 5 | return_std_{21,42,63,126,252}d | RET.rolling(w).std() |
| R2 净值高低比 | 5 | high_low_{21,42,63,126,252}d | (1+RET).cumprod 滚动窗口 max/min（用 rolling max of cumsum 近似精确净值比，log 空间：exp(max(cs)-min(cs))） |
| R3 Sharpe | 2 | sharpe_60d、sharpe_750d、adjusted_sharpe_750d（3 个） | mean/std、mean/std^4 |
| R4 Beta（沪深300） | 6 | beta_{60,125,250,500,1000}d_000300、beta_1320d_000001（指数用沪深300替代，注明） | 滚动 cov/var |
| R5 特质风险 | 3 | sigma_1320d_000300/000001、beta_consistency_1320d_000300 | 残差 std、std(β×残差) |
| R6 量 Beta | 1 | volume_beta_120d_000300 | 量动量对指数量动量滚动 cov/var |
| R7 异常波动 | 1 | days_beyond_upper_lower_21d | Z>1 天数 − Z<−1 天数 |
| R8 价格水平 | 1 | log_price | log(未复权 close)（与名义低价股效应对齐） |

全部输入后复权（log_price 除外）。长窗口（750/1000/1320）样本从
2025 年前后起，单独标注降级。

## 3. 双臂与判定（冻结，与前六族同框架）

臂B=干净微盘域、臂A=全市场，月度持有费前，2022-01~2026-08（长窗口
按可用样本）。门槛同前：|IC|≥0.02 + 价差|t|≥2 + 分年≥4/5 →
`risk_domain_candidate`；冗余：与 Z1 |corr|≥0.60 → z1_duplicate；
组内 |corr|>0.90 归并；log_price 与 ma_20d 对照标注。

出口：候选=0 → `risk_no_domain_value`（波动/Beta 轴关闭，"高波动低
收益"仅作为反向加权候选记录）；有候选 → 并入 enhance 池。

## 4. 产物

`output/analysis_static/risk25_dual_arm_v1/`：全套（同前各族）。

## 5. 风险预告（预注册的怀疑）

1. R1/R2 组 10 个因子互相关预计 >0.8（std 与 high_low 同源），归并后
   至多 1-2 个有效；
2. 特质波动异象在 A 股微盘的强度是本族最大看点：若 return_std_21d
   负 IC 过线（预期 -0.04~-0.08），它与"反炒作"信号族（Z1/MACD/BIAS）
   同向但正交（波动≠协方差≠换手），是 enhance 第 6 源的有力竞争者；
3. beta 组在无对冲工具的微盘域预期无定价（IC≈0）——若意外过线，
   更可能是与波动/规模的混杂而非 beta 本身；
4. log_price 的正 IC（低价股溢价）会与规模因子高度混杂，过线也只
   记录为"规模暴露的另一种度量"；
5. 长窗口组（750/1000/1320）样本 <2 年，只记录不判定。
