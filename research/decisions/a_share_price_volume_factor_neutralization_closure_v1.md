# 存活价量因子中性化复验归档 v1

## 1. 决策

状态：`neutralized_alpha_confirmed`（两因子均 `alpha_confirmed`）

**TURNOVER_LEVEL5 与 SKEW60 在控制市值+波动+行业后仍存活，且 ICIR 不降反升——
判定为真增量（alpha），不是纯风险暴露。**

## 2. 协议与产物

- 协议：`research/protocols/a_share_price_volume_factor_neutralization_protocol_v1.md`
  （状态 `executed_alpha_confirmed`）
- 脚本：`scripts/analyze_a_share_price_volume_factor_neutralization_v1.py`
- 产物：`output/analysis_static/a_share_price_volume_factor_neutralization_v1/`

口径与 battery v1 完全一致：母池 5544 只、2022-01 ~ 2026-07、h=5 T+1 开盘成交、
ST/停牌/涨停过滤（保留 95.1%）。中性化 = 每交易日 OLS 残差，三档：
M=log(circ_mv)，MV=+std20，MVI=+申万 L1 行业哑变量（行业覆盖 100%）。

## 3. 主结果（h=5，母池）

| 因子 | 档 | IC | ICIR | IC>0 | 22-25同向 | 2026 IC | IC衰减vs原始 |
|---|---|---|---|---|---|---|---|
| TURNOVER_LEVEL5 | raw | +0.0657 | 0.37 | 64% | 4/4 | +0.0796 | — |
| TURNOVER_LEVEL5 | M | +0.0786 | **0.53** | 71% | 4/4 | +0.0850 | -20% |
| TURNOVER_LEVEL5 | MV | +0.0487 | 0.47 | 70% | 4/4 | +0.0678 | 26% |
| **TURNOVER_LEVEL5** | **MVI** | **+0.0373** | **0.52** | **73%** | **4/4** | **+0.0431** | **43%** |
| SKEW60 | raw | +0.0342 | 0.37 | 69% | 4/4 | +0.0198 | — |
| SKEW60 | M | +0.0318 | 0.41 | 69% | 4/4 | +0.0219 | 7% |
| SKEW60 | MV | +0.0214 | 0.33 | 63% | 4/4 | +0.0230 | 37% |
| **SKEW60** | **MVI** | **+0.0200** | **0.42** | **69%** | **4/4** | **+0.0206** | **42%** |

## 4. 关键解读

### 4.1 为什么判 alpha_confirmed 而不是 risk_exposure
- 协议判定线：MVI 后 ICIR ≥ 0.3 且 2022-2025 同向 ≥ 3 → alpha_confirmed；IC 衰减
  > 50% 或 ICIR < 0.2 → risk_exposure。
- 两因子 MVI 后 ICIR 0.52 / 0.42（均高于 raw 的 0.37），**IC 降但 ICIR 升**是
  真 alpha 的典型特征（残差去噪后截面排序更稳定）；若为风险暴露（纯市值/波动/
  行业代理），ICIR 应随 IC 一起崩。TURNOVER_LEVEL5 衰减 43% 未过 50% 线。
- 2026 均存活（+0.043 / +0.021）——**反 2026 价量衰减的罕见案例**。

### 4.2 市值×波动 5×5 分层（原始因子，全期组内 IC）
- **TURNOVER_LEVEL5：25/25 格全正**（+0.029 ~ +0.109），高波动格系统性更强
  （volq=4 档普遍 +0.06~+0.11）。大市值低波动格（mvq=4, volq=0）仍有 +0.048——
  跨市值有效，**不是经典小市值/壳价值暴露**。高波动增强 + 全截面正 = 更像
  "高换手 = 资金关注/流动性溢价"的 A 股特性，非风险补偿。
- **SKEW60：25/25 格全正**，但偏小市值（mvq=0 格 +0.015~+0.033，mvq=4 格
  +0.001~+0.030），大市值高波动格（4,4）≈0。偏度信号主体在小市值/散户主导段，
  MVI 中性化后 ICIR 0.42 仍存活 → 控制市值行业后偏度本身仍有信息。

### 4.3 诚实标注（不因存活而美化）
1. **两因子方向均与经典理论相反**：高换手→未来高收益（文献：高换手=高关注=
   负 alpha，Barber & Odean 2008）；正偏度→未来高收益（彩票偏好理论：高偏度被
   高估→负收益）。机制未解，归档为观察事实，不强行套理论。
2. IC 衰减 42-43% 并非可忽略——中性化吃掉了约四成 IC，说明**原始信号中确有
   市值/波动/行业成分**，只是吃掉后仍有净剩余。实盘必须用中性化后的因子。
3. SKEW60 分层显示小市值依赖，容量受限；实盘需叠加流动性约束。
4. 未做多重检验校正（2 因子 × 4 档），且 2022-2026 仅 5 年样本。

## 5. 结论与建议

1. **换手率水平 + 收益偏度确认存活且中性化后为真增量**，价量增量方向成立
   （区别于主升浪线的"全部冗余"结论）。
2. **下一步（另行立项）**：
   - **与主线正交性检验**：两因子对"价值质量四因子 composite 分"的横截面相关，
     确认可作为主线之外的正交信号源；
   - 中性化后因子进 LightGBM 增量测试（相对 Alpha158 + 主线特征）；
   - 实盘化约束：容量/流动性过滤 + 换手成本敏感性。
3. **不追加**：本协议只覆盖两个存活因子，不扩展因子搜索（防调参美化路径）。

## 6. 可复现证据

- 协议：`research/protocols/a_share_price_volume_factor_neutralization_protocol_v1.md`
- 脚本：`scripts/analyze_a_share_price_volume_factor_neutralization_v1.py`
- 产物：`output/analysis_static/a_share_price_volume_factor_neutralization_v1/`
  （neutralized_summary.csv / neutralized_yearly.csv / neutralized_sizevol_grid.csv /
  decision.json / validation_report.txt）

## 7. 变更记录

| 日期 | 变更 |
|---|---|
| 2026-08-12 | 创建：TURNOVER_LEVEL5/SKEW60 三档中性化复验，均 alpha_confirmed；分层全正、ICIR 升，判定真增量，候选主线正交信号源 |
