# RQAlpha 回测口径对照与引入可行性评估 v1

> 创建日期：2026-08-21
> 定位：只读分析文档。回答"把本项目信号名单拿到 RQAlpha 里重跑一遍、验证执行层真实度"是否可行、
> 成本多大、与本项目现行回测口径差在哪里。
> **已验证事实**（非推测）：rqalpha 6.3.0 已在 `.venv-rqalpha` 安装成功并冒烟；bundle 格式从
> 安装源码（`rqalpha/data/bundle/__init__.py`、`utils.py`、`storages.py`）逐条核实。
> 参考：[RQAlpha 官方 README](https://github.com/ricequant/rqalpha)、[扩展数据源文档](https://rqalpha.readthedocs.io/zh-cn/develop/development/data_source.html)。

---

## 1. 结论（TL;DR）

1. **可行，且比预期简单**：RQAlpha 官方明示"按相同格式生成 bundle 文件即可替换数据源"——
   不需要写自定义数据源 mod，**只需要写一个"本地数据 → RQAlpha bundle"的生成脚本**。
   bundle 各文件格式已从源码摸清（见 §5）。
2. **本项目数据 90% 可映射**：行情（含复权因子、可还原原始价）、交易日历、ST 区间、停牌推断、
   上市/退市日期、板块（创业板/科创板/主板）、涨跌停价（可由规则精确计算）全部有；
   **唯一硬缺口 = 分红/送转明细表**（`dividends.h5`/`split_factor.h5` 需要每股派息与送转比例，
   需补下载 tushare `dividend` 接口——本项目为 2000 积分账号，可用；或从复权因子变化反推）。
3. **口径差异最大的是分红税与复权**：本项目 qlib 用后复权价（分红隐含在价格里、**无红利税**）；
   RQAlpha 用真实价格 + 分红事件 + **红利税阶梯（20%/10%/0%）**。本策略是显著高股息暴露，
   这是两者收益差的主要来源，恰好是"实盘真实度"最值得验证的一点。
4. **涨跌停更精确**：本项目近似 `limit_threshold=0.095`；RQAlpha 用每股当日真实
   `limit_up/limit_down`（主板 10%、创业板/科创板 20%、ST 5%、北交所 30%，四舍五入到分）。
   对月频低换手策略影响小（估计 <0.3%/年，方向：本项目偏保守）。
5. **推荐路线**：先做"自建 bundle + 五因子 top30_cap3 名单重测"（工作量约 1.5~2 天，
   含补 dividend 数据 0.5 天）；qlib 侧补红利税口径（约 0.5 天）作为对照/快速巡检。

---

## 2. 已完成的验证（2026-08-21）

| 步骤 | 结果 |
|---|---|
| 安装 rqalpha 6.3.0 | ✅ `.venv-rqalpha` 独立 venv（Python 3.12、pandas 2.3.3、numpy 2.5.2）——**注意：必须用 `--no-cache-dir`**（沙箱下 `/root/.cache/pip/wheels` 只读会误报 build 失败） |
| `rqalpha mod list` | ✅ 7 个默认 mod 全 enabled（sys_accounts/sys_simulation/sys_progress/sys_risk/sys_analyser/sys_scheduler/sys_transaction_cost） |
| 最小策略冒烟 | ⚠️ 唯一阻塞 = `bundle path /root/.rqalpha/bundle not exist`（预期；数据未建） |
| 默认费率（源码实测） | 股票佣金 **0.0008**（万 8，双边）+ 最低 **5 元**；印花税 **0.0005**（卖出；`pit_tax` 开启则 2023-08-28 前按历史 **0.001**）；`tax_multiplier`/`commission_multiplier` 可调 |
| 红利税 | 6.2+ 支持按持股期限差异化征收（≤1 月 20%、1 月~1 年 10%、>1 年 0%） |

安装环境（勿动 qlib 主环境，二者依赖不兼容风险）：
```bash
/home/xiaocong/worksapces/qlib/.venv-rqalpha/bin/rqalpha run -f <strategy.py> --data-bundle-path <bundle目录>
```

---

## 3. 回测口径逐项对照

| 维度 | 本项目当前（qlib） | RQAlpha | 差异定性 |
|---|---|---|---|
| 回测范式 | 组合级信号回测：TopkDropout 月度调仓、等权 | 事件驱动逐 bar：每bar撮合、逐笔订单 | 方法论不同（信号 vs 执行），**执行层 RQAlpha 更真** |
| 成交价 | `deal_price=open`（调仓日 T+1 开盘价） | `matching_type=current_bar`（当日 bar 价，可配 next_bar/当前价） | 相近 |
| 涨跌停 | **固定 9.5% 阈值**（涨跌幅超 9.5% 即不可成交） | **真实涨停/跌停价**（按板块规则+当日前收计算，tick_size 容差） | **RQAlpha 精确**；9.5% 对 10% 主板是保守近似，对 ST（5%）会漏拦（但本项目已先过滤 ST） |
| 交易成本 | base：买 5bp / 卖 15bp，min 5 元；stress：10bp/30bp | 默认：佣金 8bp 双边（min 5 元）+ 印花税 5bp 卖出（2023 后）；可配 `-smc/-scm/-tm` | **相近但不等**：base 往返 20bp vs RQAlpha 默认 21bp（20bp+1bp 四舍五入）；stress 40bp 比 RQAlpha 严 |
| 滑点 | 无显式滑点 | 无默认滑点（tick 级撮合可选） | 相同（都偏乐观） |
| T+1 | 组合回测不显式建模（月频无日内回转，等效） | 制度内置：当日买入当日不可卖 | 月频策略无实质差异 |
| 分红/送转 | **后复权价**（分红隐含、无税、无再投资明细） | 真实价 + 分红/送转事件 + **红利税阶梯** + 分红现金入账 | **最主要差异**（见 §4.1） |
| 停牌 | bin 停牌日补 NaN；组合回测近似处理 | 停牌不可交易、持仓继续持有 | **RQAlpha 精确**；月频影响小 |
| ST | 已加 ST/退市整理过滤（v8+） | 自动 st_stock_days + ST 涨跌停 5% | 相近（RQAlpha 更自动） |
| 无风险利率 | 无（超额按 SH000852 日收益计算） | yield_curve.h5（风险指标用，不影响交易） | 可简化（常数 3%） |
| 基准 | SH000852 日线（qlib bin，**不复权**） | indexes.h5 需自备 | 本项目已有（bin 中 sh000852）可导出 |

---

## 4. 差异影响分级

### 4.1 大：分红税与复权口径（预计影响最大，全部为"高估"方向）
- 本项目 qlib 后复权收益 **≈ 含息再投资、零税**；实际 A 股个税：持股 ≤1 月 20%、1 月~1 年 10%、>1 年 0%。
- 本策略 div_yield 因子是五大构成之一，持仓 1~12 个月 → 理论税负 0~10% 的现金分红部分。
  **估算：对股息率 4~6% 的持仓，年化高估约 0.3~0.6pp**（需实测，与持有期限分布有关）。
- 若只在意"相对基准超额"，该项目标是"对齐实盘"而非"对齐 qlib"，此差异是核心价值。

### 4.2 中：涨跌停近似（本项目偏保守）
- 9.5% 阈值 vs 真实 10%：主板上"涨幅 9.5%~10%"的股票 qlib 认为不可买、实盘其实也能买到（未封死）；
  反之封死涨停（10.00%）两边都不可买。→ qlib **低估**收益、偏差小（涨跌幅刚好落在这 0.5pp 区间的概率低）。
- ST 5% 板：本项目 9.5% 阈值会**漏拦**（5% 就封死却按可交易处理），但五因子管道先做 ST 过滤 → 影响可忽略。
- 20% 板（创业板/科创板）与北交所 30%：被 9.5% 拦住 → 正确方向（可能略保守）。
- **结论：RQAlpha 用真实 limit_up/limit_down 后，此差异消除；月频策略影响 <0.3%/年。**

### 4.3 小/无：T+1、min_cost 5、佣金差、停牌、容量
- min_cost 一致（5 元）；佣金 base 20bp vs RQAlpha 21bp（0.8bp 差）≈ 无。
- 停牌：月频小样本，RQAlpha 更精确但方向中性。
- 容量/参与率（5%）：RQAlpha 需用 `order_target_percent` + 成交量约束近似（默认不拦），
  需要额外配置 **订单价值 ≤5% 成交额** 的约束（策略代码中按历史成交额过滤）。

---

## 5. bundle 格式（源码逐条核实，可直接照抄生成）

`rqalpha/data/bundle/utils.py` + `__init__.py`：

| 文件 | 格式 | 本项目数据来源 |
|---|---|---|
| `stocks.h5` | 每股票一个 h5 dataset，字段 = `open/close/high/low/prev_close/limit_up/limit_down/volume/total_turnover`，索引 = 日期 int（YYYYMMDD） | qlib bin **后复权价 ÷ 复权因子**还原原始 OHLC（`raw = adjclose / ts_adj_factor`，`K_stock` 在 `data/external/tushare/market_daily_v1/aux/k_factor_stock.csv` —— update 脚本已实证该恒等式）；`prev_close`/`limit_up`/`limit_down` 由前收+板块规则计算（主板 10%/创业板科创板 20%/ST 5%/北交所 30%，分以下四舍五入）；`volume`（手）bin `$volume` 原始、`total_turnover`（元）= `$amount×1000` |
| `indexes.h5` | 同上（无 limit 字段） | qlib bin `sh000852` 导出（bin 指数**不复权**，直接可用） |
| `trading_dates.npy` | int 日期数组 | `~/.qlib/qlib_data/cn_data_2026/calendars/day.txt` |
| `st_stock_days.h5` | `order_book_id` → 日期 int 数组 | `a_share_st_status_pit_v1/normalized/st_status_intervals.csv.gz`（`is_st` 区间） |
| `suspended_days.h5` | 同上（停牌日期） | qlib bin 中 NaN 回填日（update 脚本：停牌日 reindex 补 NaN）→ 按每股每交易日检查 |
| `dividends.h5` | `order_book_id` → records：`dividend_cash_before_tax, book_closure_date, ex_dividend_date, payable_date, round_lot` | **缺口** → 补下载 tushare `dividend`（2000 分接口，本项目账号可用） |
| `split_factor.h5` | `ex_date` + `split_factor`（送转比例） | 同上（tushare `dividend` 含送转字段）或由复权因子变化反推 |
| `ex_cum_factor.h5` | `start_date` + `ex_cum_factor`（复权因子分段） | `ts_adj_factor`（已含在行情 `factor` 列） |
| `instruments.pk` | **pickle(protocol=2) 的 dict 列表**，字段至少：`type/order_book_id/symbol/listed_date/de_listed_date/round_lot/board_type`（源码 `load_instruments_from_pkl` 直接 `Instrument(i, ...)` 构造） | `data/derived/a_share_stock_classification_v2/monthly_stock_classification.csv.gz`（有 `list_date/delist_date/board/exchange/security_name/list_status`）✅ |
| `yield_curve.h5` | records：`date` + 各期限利率 | 简化：常数 3%（仅风险指标用，可后补） |

**关键发现**：只要这些文件格式对，**默认 `BaseDataSource` 直接读，无需写 mod**（官方文档"按相同格式生成对应文件并替换"即为正式支持路径）；如个别接口不齐，再按官方示例写 50 行左右的 `BaseDataSource` 子类（`get_bar/history_bars/available_data_range`）读本地数据兜底。

---

## 6. 实施计划（三条路线）

### 方案 A：自建 bundle + RQAlpha 全量重测（推荐）
| 步骤 | 工作量 | 说明 |
|---|---|---|
| A1 补数据：tushare `dividend` + `adj_factor` 全量下载入库 | 0.5 天 | 仅缺分红/送转表；其余齐全 |
| A2 `build_rqalpha_bundle_v1.py`（本项目 → bundle） | 1 天 | 按 §5 格式；含原始价还原（约 6 千股 × 26 年日线，建议先 2020-01-01 起切片验证） |
| A3 试跑：小策略（持有沪深300 市值权重）对齐基准 | 0.5 天 | 验证 bundle 正确性：以"买入持有 SH000852 成分股等权"应近似基准收益 |
| A4 五因子 top30_cap3 名单重测（2020-01 起月频） | 0.5 天 | 策略 = 月初用 `order_target_percent` 调仓到管道名单；成本用默认（或 `-scm 0.625` 对齐 5bp） |
| **合计** | **2.5 天** | 产出：与 qlib 口径的逐期差异分解（分红税、涨跌停、撮合） |

### 方案 B：订阅 RQData（商业）
不推荐：费用 + 与本项目自建数据体系重复；仅当 A 卡死在数据还原时才考虑。

### 方案 C：qlib 侧补口径（快速巡检，0.5 天）
- 在现有回测上加：① 红利税近似（按持仓期 10% 档）；② 涨跌停改真实值（用 daily_basic/板块规则）；
  ③ 停牌日收益置 0。优点：脚本内完成、与现有 v8/v16 体系对比直接；缺点：仍非真实撮合。
- 建议 **先做 C 再启动 A**：C 能马上量化"红利税≈X bp"这个最大差异，为 A 的结果做基准对照。

---

## 7. 建议

1. **本轮立即可做**：方案 C（0.5 天，收益 = 马上知道税/涨跌停口径影响量级）；
2. **随后做**：方案 A1（补 dividend 表，1 次下载永久复用，顺便无风险利率可后补）→ A2/A3/A4；
3. **不引入**：RQData 订阅、tick 级回测（本策略月频，日线足够）；
4. **注意**：RQAlpha 许可为"仅限非商业使用"（个人研究 OK）；回测结果与 qlib 口径差异要
   在 `research/decisions/` 补一份 closure + 协议（按本项目"先协议后实验"的治理惯例）。

---

## 8. 变更记录

| 日期 | 变更 |
|---|---|
| 2026-08-21 | 创建：rqalpha 6.3.0 安装验证（.venv-rqalpha，--no-cache-dir 避沙箱缓存问题）；默认费率/红利税源码核实；bundle 全格式源码核实；口径对照表；三方案与工作量评估 |
