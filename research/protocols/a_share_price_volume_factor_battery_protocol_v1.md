# 非 Alpha158 价量因子电池检验协议 v1

状态：`executed_with_survivors`（2026-08-12 执行；7 因子检毕，2 存活
TURNOVER_LEVEL5 / SKEW60，5 死亡；结论归档见
`research/decisions/a_share_price_volume_factor_battery_closure_v1.md`）

## 1. 状态、问题与授权边界

**问题**：Alpha158（qlib 默认基准，国内日频使用者最拥挤的因子集）2021 后单因子
alpha 衰减严重（`DEV_LOG_RollingTrainingOptimization.md` §3/§10/§12.6：测试段
Daily IC 全负、158 特征单变量 IC 几乎全趋 0）。但 Alpha158 只是量价空间里很窄的
一片——**结构上吃不到**时间分解（隔夜/日内）、换手率、滚动 VWAP 偏离、市场相对
强度、收益高阶矩五类信息。本协议检验：这些 Alpha158 之外的量价信息，在当前
regime 下是否仍有未被定价的横截面选股能力。

**定位**：价量线（主升浪线）收口后的**重启检**——若本电池有因子存活，作为
价值质量主线之外的正交量价信号源候选；若全部死亡，则"非 Alpha158 量价增量"在
仓库口径下判空，价量方向最终收口，资源转向事件/制度（PEAD）线。

**不重复研究**（仓库纪律）：
- 时序趋势状态（TS_UP60 等）已由 `a_share_trend_persistence_protocol_v1.md`
  检验（判定 `supported`，排序层弱 ICIR 0.23），本电池**不重复**自相关/Hurst 类
  因子；
- 长窗口位置因子（UP_FROM_LOW_250）已由主升浪复验覆盖，不重复；
- 横截面动量变体（ROC/MA 族）已被证明是 Alpha158 冗余（duplicate/near），不重复。

**授权边界**：只检验本协议冻结的 7 个因子 × 预设检验；不授权搜索更优窗口/阈值、
不因结果修改因子定义、不做"因子族"扩展搜索。存活因子仅获得"候选"资格，是否并入
主线另行立项。

## 2. 假设（冻结）

- H1：隔夜/日内收益结构（时间分解）含 Alpha158 未覆盖的截面信息；
- H2：换手率水平/变化（自由流通口径）是注意力与流动性的增量代理；
- H3：滚动 VWAP 偏离（量价背离）含 Alpha158 单日 VWAP0 之外的增量；
- H4：市场相对强度（个股−指数）含个股动量之外的增量；
- H5：收益偏度（高阶矩，彩票偏好代理）含波动率之外的负向增量。

每个假设的判定标准：RankIC 显著（ICIR ≥ 0.3）+ 分年度同向 ≥ 3/5 年 + 与最近
Alpha158 对照因子 distinct（|corr| < 0.7）。

## 3. 因子电池（冻结）

数据源：`cn_data_2026`（后复权 OHLCV）`+ a_share_daily_basic_pit_v1`（自由流通
换手率）+ `sh000852` 指数行情（中证 1000，市场相对基准）。

| # | 因子 | 定义（全部 pandas 逐股计算，规避 qlib 表达式语义坑） | 信息族 |
|---|---|---|---|
| 1 | `OVN_INT5` | 过去 5 日隔夜收益均值：`Mean(open/Ref(close,1)-1, 5)` | 时间分解（T+1/注意力） |
| 2 | `INTRADAY_INT5` | 过去 5 日日内收益均值：`Mean(close/open-1, 5)` | 时间分解（T+1/注意力） |
| 3 | `TURNOVER_LEVEL5` | 自由流通换手率 5 日均值：`Mean(turnover_rate_f, 5)` | 注意力/流动性 |
| 4 | `TURNOVER_CHG` | 当日换手率相对 20 日均值的偏离：`turnover_rate_f / Mean(turnover_rate_f,20) - 1` | 量能异动 |
| 5 | `VWAP_DEV5` | 收盘价相对 5 日 VWAP 均值的偏离：`close / Mean(vwap,5) - 1`（**Alpha158 的 VWAP0 是单日 $vwap/$close，本因子用滚动窗口均值，无重叠**） | 量价背离 |
| 6 | `REL_STRENGTH20` | 个股 20 日收益 − 中证 1000 20 日收益：`close/Ref(close,20)-1 − index_ret20` | 市场相对 |
| 7 | `SKEW60` | 60 日日收益偏度（pandas rolling skew） | 高阶矩（彩票偏好） |

不采用：更长/更短窗口的变体搜索、Hurst/自相关（已测）、价量相关族（CORR 已
在 Alpha158）、OBV/资金流（需要量价方向组合，留待存活后深验）。

## 4. 股票池与过滤（冻结）

| 项 | 冻结值 |
|---|---|
| 主池 | 沪深普通 A 股母池（`all.txt` 历史在市，剔除 BJ/指数/B 股），同 `a_share_trend_persistence_protocol_v1.md` §4 |
| 辅助层 | csi1000 历史成分（同一套 RankIC 重跑，不作主结论） |
| 数据 | `~/.qlib/qlib_data/cn_data_2026`（后复权）；换手率来自 `daily_basic_pit_v1/normalized/daily_basic.csv.gz`（2016-2026，缺失率 0.004%，merge 按 ts_code+trade_date） |
| ST/停牌/涨停过滤 | 同主升浪复验：ST PIT 区间 + 停牌（量=0）+ 涨停信号日（主板 0.095/创业板科创板 0.195） |
| 检验窗口 | 2022-01-01 ~ 2026-07-31（与主升浪/趋势持续性一致，可比） |
| 数据预热 | 自 2020-01-01 |

## 5. 标签与口径（冻结）

- 主 label：T+1 开盘成交口径 `Ref($open,-1)/Ref($close,-6)-1`（h=5）；
- 附录：h=10/20 同口径。
- 年化：日均统计 × 238/h。全部 Spearman RankIC。

## 6. 检验设计与报告

每因子逐日计算，输出全期 + 分年度：

- **R1 RankIC**：逐日截面 Spearman（factor vs FWD_5_open），全期 IC 均值/ICIR/
  IC>0 占比 + 分年度 IC。
- **R2 Q5-Q1 价差**：逐日五分位，全期年化 Q5−Q1 价差 + 五分位均值表（检查单调性
  与方向）。
- **R3 冗余判定**：逐日横截面 Spearman，候选 × 最近 Alpha158 对照（OPEN0、KBAR、
  VWAP0、VMA20、ROC20、STD20、STD60），报告**中位数** |corr|。判定：
  |corr| ≥ 0.95 = duplicate（判死）、0.70~0.95 = near（警告）、< 0.70 = distinct。
- **R4 2026 衰减**：2026 年 IC 单独列示，如实报告，不因历史好看加宽。

Alpha158 对照因子（qlib 表达式，取最近语义）：

| 候选 | 对照 | 语义 |
|---|---|---|
| OVN_INT5 | OPEN0、KBAR | 单日隔夜/日内结构 |
| INTRADAY_INT5 | KBAR | 单日日内结构 |
| TURNOVER_LEVEL5 / CHG | VMA20 | 量能族 |
| VWAP_DEV5 | VWAP0 | 量价位置 |
| REL_STRENGTH20 | ROC20 | 个股动量 |
| SKEW60 | STD20、STD60 | 波动族 |

## 7. 预设判定

对齐 `metrics_judgment_standard.md`（ICIR 0.3 中 / 0.5 好）：

| 条件 | 判定 |
|---|---|
| ICIR ≥ 0.3 **且** 2022-2025 至少 3 年同向 **且** 对全部对照 distinct | `alive` → 候选量价信号源，建议并入主线做正交叠加或独立深验 |
| ICIR 0.2~0.3 或分年度同向 2/4 年 | `weak` → 需中性化/组合后再评，暂不投入 |
| ICIR < 0.2 或方向不稳或对任一对照 duplicate/near | `dead` → 归档不投入 |
| 全部 7 因子 dead | 价量增量方向最终收口，资源转事件/制度（PEAD）线 |

2026 衰减不改变判定路径，仅如实记录。

## 8. 产物与目录

```text
output/analysis_static/a_share_price_volume_factor_battery_v1/
  battery_daily_ic.csv.gz        R1 每因子每日 RankIC（long 格式）
  battery_ic_summary.csv         全期 IC/ICIR/pos_ratio/2026 IC
  battery_ic_yearly.csv          分年度 IC（2022-2026）
  battery_qspread.csv            每因子每日 Q5-Q1 价差
  battery_quantile_means.csv     五分位均值（全期）
  battery_redundancy.csv         候选×对照 逐日相关（含中位数/均值）
  decision.json                  预设判定（每因子）
  methodology.json               口径快照
  validation_report.txt          中文报告
```

脚本：`scripts/analyze_a_share_price_volume_factor_battery_v1.py`
（复用主升浪复验/趋势持续性线的过滤与统计框架）。辅助层 csi1000 产物加
`_csi1000` 后缀。

## 9. 结论边界

本检验只回答"Alpha158 之外的量价信息是否存活"，不改变主线（价值质量月频）任何
决策。存活因子只获候选资格：是否接入、如何接入另行立项。所有结论在仓库口径
（后复权 + 历史成分 + 过滤）下成立。

## 10. 变更记录

| 日期 | 变更 |
|---|---|
| 2026-08-12 | 创建：冻结 7 因子电池 × R1-R4 检验 × 预设判定；定位为价量线收口后重启检 |
| 2026-08-12 | 执行：2 alive（TURNOVER_LEVEL5/SKEW60）、5 dead（TURNOVER_CHG/REL_STRENGTH20 因 duplicate 判死，INTRADAY_INT5 因 2026 翻转，OVN_INT5/VWAP_DEV5 弱）；结论归档 `a_share_price_volume_factor_battery_closure_v1.md` |
