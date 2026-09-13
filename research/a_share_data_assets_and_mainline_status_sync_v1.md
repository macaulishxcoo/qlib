# A 股数据资产与主线状态同步 v1

> **文档定位**：状态快照/知识文档。记录 2026-08-09 ~ 08-11 在其他窗口完成的数据完善、
> 策略研究与管道建设工作，供后续会话直接读取，**避免信息缺失、滞后或重复操作**。
>
> **性质**：只读事实记录，**不启动任何实验、不下载数据、不训练、不回测**，不改变任何
> 冻结/授权决策。所有路径、列名、数字均为 2026-08-11 经核查的实际状态。
>
> **与其他文档的关系**：价值质量研究线经
> `research/decisions/a_share_value_quality_level_factors_proposal_v1.md` 授权（冻结后
> 唯一获批的议题路线）；结果记录在 `research/protocols/` 与 `output/analysis_fundamental/`
> 各版本的 decision.json / strategy_report.txt 中，本文件不替代它们。

---

## 1. 新增数据资产（data/external/tushare/ 下，均未纳入 git）

### 1.1 `a_share_daily_basic_pit_v1/` — 每日估值/行情基本面

| 项目 | 内容 |
|---|---|
| 目录 | `data/external/tushare/a_share_daily_basic_pit_v1/`（raw/ + normalized/ + manifests/） |
| 范围 | 2016-01-04 → 2026-08-07，2574 个交易日，5792 只股票，10,926,572 行 |
| 文件 | `raw/YYYYMMDD.csv.gz` 按日；合并 `normalized/daily_basic.csv.gz`（655MB） |
| 列 | ts_code, trade_date, close, turnover_rate, turnover_rate_f, volume_ratio, pe, pe_ttm, pb, ps, ps_ttm, dv_ratio, dv_ttm, total_share, float_share, free_share, total_mv, circ_mv |
| 下载脚本 | **无**（一次性下载；名称中 "PIT" 为名义性，数据无 available_date 列） |
| 消费方 | v6 日度网格、每日信号管道 |

### 1.2 `a_share_st_status_pit_v1/` — ST/退市整理状态（PIT 区间）

| 项目 | 内容 |
|---|---|
| 目录 | `data/external/tushare/a_share_st_status_pit_v1/` |
| 来源 | tushare `namechange` 全市场历史（14,170 行）→ 归一化为状态区间 |
| 覆盖 | 5878 家公司；2838 个 ST 区间；153 个退市整理区间；ann_date 至 2026-08-11 |
| 归一化列 | ts_code, name, start_date, end_date, ann_date, change_reason, is_st, is_delist_phase（开放区间 end_date=2100-01-01） |
| 下载脚本 | `scripts/data_collector/download_a_share_st_status_pit_v1.py` |
| 消费方 | v3/v4/v5/v6 回测、每日信号管道 |

### 1.3 `margin_pit_v1/` — 融资融券明细

| 项目 | 内容 |
|---|---|
| 目录 | `data/external/tushare/margin_pit_v1/`（raw/ + normalized/ + manifests/） |
| 范围 | 2016-01-04 → 2026-08-07，2574 个交易日，5190 只标的，6,072,984 行 |
| 列 | trade_date, ts_code, rzye(融资余额), rqye(融券余额), rzmre(融资买入额), rqyl(融券余量), rzche(融资偿还额), rqchl(融券偿还量), rqmcl(融券卖出量), rzrqye(融资融券余额) |
| 下载脚本 | **无** |
| 消费方 | 融资融券信号研究、v5 过滤层 |

### 1.4 `a_share_financial_pit_v1/` 扩展（2026-08-11 新增）

| 子目录 | 内容 |
|---|---|
| `recent/` | 5690 股 × fina_indicator（108 列，无 PIT 元数据尾），end_date 2025-03-31 → 2026-03-31 |
| `recent_3tables/` | 5690 股 × 3 表精简列：balancesheet(total_assets)、income(n_income_attr_p/revenue/total_revenue)、cashflow(n_cashflow_act)；end_date 至 2026-06-30 |
| `normalized/fina_indicator.csv.gz` | 2009-2026 合并（89 报告期、5802 股、245,966 行），含 PIT 元数据尾（available_date 等） |
| `manifests/fina_indicator_manifest.json` | 新旧组件分界：old→full/normalized/(2009-2024)，recent→recent/(2025-2026) |

下载脚本：`scripts/data_collector/download_a_share_financial_3tables_recent_v1.py`（自 2025Q1 起，
ann_date 作披露日，可断点续跑）。

---

## 2. 价值质量月度策略（主线研究，v1 → v6）

### 2.1 因子层（已冻结）

通过（开发→确认→holdout 复现，40 日中性 RankIC）：**ep(0.0695)、bm(0.0827)、
div_yield(0.0738)、accruals(0.0443)**。失败：**roe_stability**（开发期即负）。
复合信号 = 4 因子等权百分位秩平均（≥3 因子门）。

### 2.2 策略演进

统一口径：月度调仓 top50 等权、沪深非金融 A 股、基准 SH000852、T+1 开盘成交、
涨跌停 9.5%、两档成本（base 买0.05%/卖0.15%；stress 买0.10%/卖0.30%）。

| 版本 | 关键变化 | 结论（关键数字，stress 费后） |
|---|---|---|
| v1 | 4 因子等权复合、无 ST 过滤 | 全期正（约 +9%/yr），**holdout 2023-2025 为负**（-5.5%/yr） |
| v2 | log市值 + 申万一级行业 OLS 中性化 | **holdout 转正 +9.33%/yr (IR 0.64)** → 证明 v1 是风格暴露非信号失效 |
| v3 | ST/*ST/退市整理过滤 | **alpha 存活**：holdout +9.31%/yr (IR 0.66)、full +9.99%/yr (IR 0.85) |
| v4 | 滑点×容量 12 格敏感性 | 极端格 S3+P2 仍可行：holdout +7.32%/yr (IR 0.54) → `viable_under_stress` |
| v5 | 融资融券过滤层（rzye 250d z>2，T-1 对齐） | **劣于 v3 被拒**：holdout +7.64%/yr vs v3 +9.31%，MDD -35.4% vs -26.6% → `margin_filter_neutral_positive` |
| v6 | daily_basic 日度网格重建 + 财务延至 2026Q2 | holdout **+11.69%/yr (IR 1.33)**、full +10.00%/yr (IR 0.90)，**但 new_coverage 2025-07→2026-06 = -25.6%/yr (IR -2.29)，2026 年 -50.5%/yr** → `dailygrid_viable`（带严重告警） |

### 2.3 当前进行中（快照时刻 2026-08-11）

- **v1 回测正在重跑**（PID 3996500，14:42 启动）：验证 **`min_factors=3` 因子门修复**——
  2026 回撤的隐藏驱动是"因子缺失（<3 个）的股票得分被挤到 ~0.9，挤掉 4 因子正常股
  （~0.5）"。v1 panel 是 v2–v5 脚本的上游输入，属承重产物。
- 各版本脚本：`scripts/backtest_a_share_value_quality_monthly_{v1,neutral_v2,st_filter_v3,
  sensitivity_v4,margin_filter_v5,dailygrid_v6}.py`；共享信号构建在
  `scripts/analyze_a_share_value_quality_level_factors_extension_v1.py`（build_snapshot /
  composite_score / ols_residual / load_financials）。

### 2.4 输出目录

`output/analysis_fundamental/a_share_value_quality_monthly_strategy_v{1,2_neutral,3_st_filtered,
4_sensitivity,5_margin_filtered,6_dailygrid}/`，每目录含 decision.json / methodology.json /
strategy_report.txt / backtest_summary.csv / yearly_summary.csv 等。

---

## 3. 融资融券信号研究

| 项目 | 结果 |
|---|---|
| rzye_zscore（250d 时序 z，min 120） | 20 日 IC **-0.043**、ICIR **-5.86**、pos ratio 0.347（h=5 IC -0.031） |
| rzye_chg5d | 20 日 IC -0.0245、ICIR -5.89 |
| rzjme_zs（净买入 z） | 20 日 IC -0.0117、ICIR -3.15 |
| 滞后对齐（Q1） | aligned(T-1) IC -0.0112 ≈ misaligned(T0) -0.0113 → `aligned_ok`（无未来函数） |
| 横截面正交性（Q2） | 与价量因子最大 |corr| = **0.235**（vs vol20）→ `orthogonal` |
| 结论 | 信号真实且独立，但作为 v5 过滤层**未提升策略，被拒** |

脚本：`scripts/validate_a_share_margin_signal_v1.py`（注：**仍指向旧路径 /tmp/margin_probe，
未切换到 margin_pit_v1**）、`scripts/analyze_margin_signal_orthogonality_v1.py`。
输出：`output/analysis_fundamental/{a_share_margin_signal_v1, margin_signal_orthogonality_v1}/`。

---

## 4. 每日信号生产管道（阶段 2 落地）

### 4.1 现状

- **脚本**：`scripts/run_daily_signal_pipeline_v1.py`——**纯信号生成，无模型训练**。
  复用冻结函数（composite_score / ols_residual / build_snapshot），不拟合任何参数。
- **模式**：`--replay --from --to`（回填一致性校验）/ `--date T`（单日模式，仅打印 top10，
  不更新台账）。
- **过滤顺序**（与 v4 一致）：ST/退市 → 容量（单票 200 万/20 日均额，参与率 5%）→
  中性化复合 top50。
- **协议**：`research/protocols/signal_production_pipeline_protocol_v1.md`。

### 4.2 台账产物（output/signal_ledger/，replay 2024-01-02 → 2025-06-30 已产出）

| 台账 | 内容 | 规模 |
|---|---|---|
| `signal_ledger.csv` | 全市场 4 因子原始分 + 中性化残差 + ST/容量标记 | 900 行（18 个月 × top50） |
| `holding_ledger.csv` | 每日持仓：rank/code/score/weight/调仓日标记 | 17,950 行 |
| `portfolio_ledger.csv` | 每日组合收益/基准收益/超额/换手/成本/账户值 | 358 行 |

### 4.3 一致性验收

与 v2 neutral panel（`a_share_value_quality_monthly_strategy_v2_neutral/monthly_neutral_signal.csv.gz`）
同口径 top50 重叠：**代码阈值 0.90，协议文本 0.95 —— 两处不一致**，需留意。

### 4.4 调度

**尚未部署 cron**（仓库内无任何调度配置）。协议设计为：replay 回填 + 每日 `--date T`，
前置条件是财务/size/ST PIT 的每日更新链（部分已建：ST 有下载脚本、财务 recent_3tables 有
下载脚本；daily_basic/margin 无下载脚本；style/size 月度更新链未建）。

---

## 5. 未决项 / 风险 / 缺口

| # | 项目 | 说明 |
|---|---|---|
| 1 | v6 最新样本期严重为负 | new_coverage 2025-07→2026-06 = -25.6%/yr（2026 -50.5%/yr）；min_factors=3 修复在 v1 重跑中验证，尚未确认是否解决 |
| 2 | 管道完整名单数据边界 | 协议记录财务 PIT 止 2025-06-28、size PIT 止 2025-05-30 → 完整名单仅限 T ≤ 2025-06-30；v6 的 daily_basic + extended 财务已把覆盖推到 2026-08，但属另一条链路 |
| 3 | `pipeline_meta.json` 未写入 | 协议列出但脚本改为 stdout 输出 JSON |
| 4 | `validate_a_share_margin_signal_v1.py` 旧路径 | 仍读 `/tmp/margin_probe`，未切换到 `margin_pit_v1/` |
| 5 | daily_basic / margin 无下载脚本 | 一次性下载，未来增量更新链缺口 |
| 6 | 一致性阈值不一致 | 代码 0.90 vs 协议 0.95 |
| 7 | v1 重跑进行中 | 其产物 `monthly_composite_signal.csv.gz` 是 v2–v5 上游，重跑完成前勿并行动 v1 panel |

---

## 6. 变更记录

| 日期 | 变更 |
|---|---|
| 2026-08-11 | 创建：同步 2026-08-09~11 其他窗口完成的数据完善（4 类）、价值质量 v1-v6 结论、融资融券信号、每日信号管道状态与未决项 |
