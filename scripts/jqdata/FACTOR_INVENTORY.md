# 因子可及性总清单（2026-09-15 实测）

> **⚠ 2026-09-17 更正**：本文件 §C 关于「聚宽因子库取不到」「只有 10 个风格因子」的结论
> **已被推翻**。实测 `get_all_factors()` 返回 **276 个**因子（10 大类全部可取），
> CNE6 pro 16 个可用。早前误判是因为用了错误因子名（`MACD`/`RSI`，
> 真实 code 为 `MAC5`/`MACDC`/`MFI14`）。完整结论见
> `scripts/jqdata/README.md` §4.5 与 `facsim/conventions.py`。

> **文档定位**：一次性回答「我们现在能拿到哪些因子」。分**三个来源**列清，
> 每个来源都标注**是否已实测、是否要钱、是否有额度限制**。
> 复现命令见文末。

---

## 0. 一页纸总览

| 来源 | 可直接用的因子 | 要钱？ | 额度/范围限制 |
|---|---|---|---|
| **A. 本地已有数据**（tushare + qlib bin） | **最全**：全市场 OHLCV + 18 个 daily_basic 字段 + **116 列财务指标** + 行业/ST/事件/两融/资金流 | ✅ 已付/免费 | 数据到 **2026-09-10**，无额度限制 |
| **B. 项目自实现**（`scripts/analyze_*_dual_arm_v1.py`） | **178 个实现因子**（202 原始），九族扫描产物 | ✅ 免费 | 无 |
| **C. JQData 试用** | Alpha101 本地 **82 个** + 风险模型 **10 个** + 申万一级行业 **31 个** + 财务/估值字段 | ⚠ 试用免费 | **区间 2025-06-07~2026-06-14**；**100 万条/日** |
| C′. JQData 付费模块 | Alpha191（191 个）、技术指标（101 个） | ❌ **需单独购买** | — |

**一句话**：**本地的因子供给已经比聚宽试用更全、更新**；聚宽真正多出来的只有
**风险模型风格因子（10 个）**和**行业因子（31 个）**。

---

## A. 本地已有数据能构造的因子（**主力**）

### A1. 行情（`cn_data_2026` + `market_daily_v1`）
- **5,570 只**股票日线（raw 文件数实测），区间 2000-01-04 ~ **2026-09-10**
- OHLCV + 复权因子 → 可衍生：动量/反转/波动/振幅/换手/量比/偏度/峰度/Amihud 非流动性/日内-隔夜分解…

### A2. `a_share_daily_basic_pit_v1`（**18 列，实测**）
```
ts_code, trade_date, close,
turnover_rate, turnover_rate_f, volume_ratio,        # 换手/量比
pe, pe_ttm, pb, ps, ps_ttm,                          # 估值
dv_ratio, dv_ttm,                                    # 股息率
total_share, float_share, free_share,                # 股本
total_mv, circ_mv                                    # 市值（总/流通）
```
区间 2016-01-04 ~ **2026-09-10**。

### A3. `a_share_financial_pit_v1`（**116 列**，实测）
`fina_indicator` 116 列，含 `eps / dt_eps / revenue_ps / gross_margin / current_ratio /
quick_ratio / cash_ratio / ar_turn / ca_turn / fa_turn / assets_turn / op_income /
ebit / ebitda / fcff / fcfe / interestdebt / roe / roa / netprofit_margin /
inc_revenue_year_on_year / inc_net_profit_year_on_year / dt_netprofit_yoy` 等
→ 即项目五因子的 ep/bm/div_yield/accruals/g2 **全部来自这里**；另有
`balancesheet_v1 / full / recent / recent_3tables` 三大报表。
**PIT 键 = `available_date`（公告日）**。

### A4. 其他已入库、可直接构因子
| 数据集 | 可构因子 |
|---|---|
| `a_share_style_pit_v1` | 申万 L1/L2/L3 行业（中性化、cap3）、月度自由流通市值 |
| `a_share_st_status_pit_v1` | ST/退市状态（过滤） |
| `a_share_events_daily_v1` | 增减持/解禁/龙虎榜（325.7 万行） |
| `margin_pit_v1` | 融资余额/融券余额/净买入（607 万行） |
| `moneyflow_pit_v1` + `hsgt` | 个股资金流、沪深港通 |
| `a_share_forecast_v1` | 业绩预告（21,142 条，**尚未测**） |
| `holdernumber_pit_v1` | 股东户数（已测关闭） |
| `a_share_index_membership_pit_v1` | 指数成分历史 |
| `sw_industry_index_v1` | 30 个申万一级行业指数日线 |
| `us_index_v1` | 7 个美股指数（隔夜传导） |

---

## B. 项目已自实现的因子（`scripts/analyze_*_dual_arm_v1.py`）

九族双臂扫描：**202 原始 → 178 实现 → 24 候选 → 归并 7 源**（A 线 `HANDOFF_microcap_to_market_v1.md`）。

| 族 | 脚本 | 实测规模 |
|---|---|---|
| Alpha101 | `analyze_alpha101_dual_arm_v1.py` | 31 |
| Momentum | `analyze_momentum20_dual_arm_v1.py` | 20（含 **MACD**、CAPM alpha） |
| Quality | `analyze_quality59_dual_arm_v1.py` | 59 → 41 实现 |
| Liquidity | `analyze_liquidity35_dual_arm_v1.py` | 35（含 BIAS 换手冷却族） |
| Risk | `analyze_risk25_dual_arm_v1.py` | 25（含 return_std_21d） |
| Growth | `analyze_growth15_dual_arm_v1.py` | 15（含 pa=ROA 加速度） |
| Value | `analyze_value11_dual_arm_v1.py` | 11 |
| Size | `analyze_size3_dual_arm_v1.py` | 3 |
| Reversal | `analyze_reversal3_dual_arm_v1.py` | 3 |

产物：`output/analysis_static/market_vs_domain_ic_master_v1.csv`（77 因子）、
`*/factor_panel_*.csv.gz`。

---

## C. JQData 试用账号（实测，见 `README.md` §3.3）

| 因子来源 | 取用方式 | 可用数 | 说明 |
|---|---|---|---|
| **Alpha101** | `alpha101.alpha_xxx(date)` | **82/101** | **客户端本地计算**（不鉴权、不耗额度）；19 个 SDK 标「未实现」 |
| **风险模型风格因子** | `get_factor_values` | **10** | `size / beta / momentum / residual_volatility / non_linear_size / book_to_price_ratio / liquidity / earnings_yield / growth / leverage`，另 `market_cap / circulating_market_cap` |
| **申万一级行业因子** | `get_factor_cov()` | **31** | 与上 10 个风格因子并列 |
| **财务/估值** | `get_fundamentals` | **14 列** | `pe_ratio / pb_ratio / ps_ratio / market_cap / circulating_market_cap / turnover_ratio / dividend_ratio / roe / roa / eps / net_profit_margin / inc_revenue_year_on_year / inc_net_profit_year_on_year` |

**限制**：区间 **2025-06-07 ~ 2026-06-14**（动态滑窗，拿不到最近 3 个月）；
**100 万条/日**；每返回 1 行 = 1 条。

### C′. 拿不到的（付费模块）
- **Alpha191**：服务端，0/191（账号区间受限）→ 官方文档有 **191/191 条公式**，可自研（见 README §3.5）
- **技术指标 101 个**：**付费模块**，文档**无公式**，不建议自研
- `get_factor_kanban_values`：不支持试用

---

## D. 结论与建议

1. **主力继续用本地 tushare + qlib**：因子覆盖面最广、数据最新（2026-09-10）、无额度焦虑；
2. **聚宽试用的独特增量 = 风险模型 10 个风格因子 + 31 个行业因子**：
   正好补上本项目「没有 Barra 式风格因子（只有自拼代理）」的缺口，
   可用于**独立复核 B 线风格中性化结论**（`a_share_style_neutralization_decision_v1.md`）；
3. **Alpha101 本地版（82 个）** 可作为项目自实现 Alpha101 的**独立交叉验证**；
4. **不要为技术指标付费**：项目已在九族扫描 / 13 条日频线中系统性证伪该方向；
5. **任何聚宽批量取数前先估算额度**：`bash scripts/jqdata/quota.py --cost <行/次> <次数>`。

---

## E. 复现命令

```bash
cd /home/xiaocong/worksapces/qlib
# 聚宽因子可及性（耗额度，谨慎）
bash scripts/jqdata/run.sh scripts/jqdata/probe_factors.py
# 额度查看/估算（不耗额度）
bash scripts/jqdata/run.sh scripts/jqdata/quota.py
# 抓取官方公式文档（不耗额度）
bash scripts/jqdata/run.sh scripts/jqdata/fetch_docs.py
```

## F. 变更记录

| 日期 | 变更 |
|---|---|
| 2026-09-15 | 创建：三来源因子总清单（本地数据 18+116 列 / 自实现 178 个 / 聚宽试用 82+10+31） |
