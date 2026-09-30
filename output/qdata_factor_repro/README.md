# qdata.cc 因子本地复现体系

> 对标 `scripts/jqdata/`（聚宽体系），在 `scripts/qdata/` 下建成同规格的
> **「公式抽取 + 本地复现 + 自动逐日比对」** 框架。
>
> 数据源：官方因子值走 `http://api.qdata.cc`（备用 `https://quantdata.olingma.com`）；
> 输入数据走 Tushare 实时接口 + 本地离线镜像。
>
> **入口先读这三个文件**：
> 1. `CONVENTIONS.md` —— 口径约定与验证记录（**最重要**，含全部实测标定结论）
> 2. `FORMULA_AUDIT.md` —— 公式静态审计（横截面扫描 / 参数 / 直通因子 / 跨体系对照）
> 3. `SUMMARY.md` —— 全批次精度总账（自动生成）

---

## 1. 一键运行

```bash
PY=/home/xiaocong/anaconda3/envs/qlib/bin/python

$PY scripts/qdata/run_all.py                    # 列出将执行的步骤（dry-run）
$PY scripts/qdata/run_all.py --run              # 顺序跑完全部批次 + 审计 + 汇总
$PY scripts/qdata/run_all.py --run --skip-batches   # 只重跑审计与汇总（不占 API 配额）
$PY scripts/qdata/run_all.py --run --only repro_batch2
```

**必须顺序执行**：所有批次共享 qdata 配额（QPS 30 / QPM 200），并行会触发 429 与静默截断。

各批次自带 `output/qdata_factor_repro/cache/` 缓存，重复运行命中缓存、秒级返回。

---

## 2. 分层结构

```
scripts/qdata/
├── qdata_env.py           ← qdata 客户端：factor_list / factor_value / 限流 / 分页
├── extract_formulas.py    ← ① 从 factor_list 抽公式 → factor_formulas.json
├── audit_formulas.py      ← ② 公式静态审计（不调 API）→ FORMULA_AUDIT.md + FACTOR_STATUS.json
│
├── ts_env.py              ← Tushare 数据层：行情面板（后复权/原始/复权因子/daily_basic 字段）
├── ts_market.py           ← 全市场面板（横截面因子必需）
├── ts_fin.py              ← 财报数据层（PIT，按 ann_date 对齐）
├── ts_index.py            ← 指数行情（beta/alpha/sigma 类因子）
│
├── xs_ops.py              ← 横截面算子：Rank / Scale / IndNeutralize
├── xs_compare.py          ← 横截面因子专用比对器（逐日 Spearman 判据）
│                              （时序算子沿用 scripts/jqdata/facsim/ops.py）
│
├── repro.py               ← 批次一：价量 15 个
├── repro_batch2.py        ← 批次二：Momentum / Reversal / Size / Value
├── repro_liquidity_risk.py← 批次三：Liquidity / Risk
├── repro_quality.py       ← 批次四：Quality / Growth
├── repro_quality_xs.py    ← 批次四（横截面部分）
├── repro_alpha101.py      ← 批次五：Alpha101（71 个）
├── repro_value.py         ← Value 族补测（book_to_market 等需财报科目的）
│
├── run_factor_summary.py  ← 全批次汇总 → SUMMARY.md / SUMMARY.csv / SUMMARY_BY_FAMILY.csv
└── run_all.py             ← 一键编排入口
```

**复用而非重造**：判定引擎 `scripts/jqdata/facsim/compare.py`（三口径 max / p99 / 中位）
与算子库 `scripts/jqdata/facsim/ops.py` 直接复用。仅 `xs_compare.py` 为新增
（横截面因子用绝对误差判据会系统性误判，见 `CONVENTIONS.md` §3.4）。

---

## 3. 判定口径（三口径 + 横截面专用口径）

| 口径 | 适用 | 档位 |
|---|---|---|
| `verdict`（maxerr） | 时序因子，最严 | EXACT ≤1e-9 / GOOD ≤1e-4 / APPROX ≤1e-2 |
| `verdict_robust`（p99） | 时序因子，抗离群 | 同上阈值 |
| **`verdict_med`（中位）** | **推荐的可使用性判据** | 同上阈值 |
| `verdict_xs`（横截面 Spearman） | 含 `Rank`/`CrossSectionalRank`/`Scale`/`IndNeutralize` 的因子 | EXACT ≥0.9999 / GOOD ≥0.999 / APPROX ≥0.99 |

`SUMMARY.md` 中每行标注用了哪套**判据**，并对"横截面因子却用了绝对误差判据"发出告警。

---

## 4. 必须遵守的四条铁律

### G1 — `Close` 一律指后复权价
`后复权价 = 原始收盘价 × adj_factor`。不是原始价、不是前复权价。

### G2 — ⚠️ 判定必须截断尾部（`--settle-days 30`）
qdata 在数据末端约 20~25 个交易日内的因子值是**暂定值**，事后会被回填修正
（已用 `_old_20260821` 快照直接证明：`rsi` 在 2026-08-14~08-20 的值两个时点不同）。
不截断会把"暂定值"当"公式错误"。

### G3 — 横截面因子必须在**全市场**股票池上校验
`CrossSectionalRank(x) = rank(x) / N`（升序 1..N，官方实测 N=5430）。
在 6 只样本股上校验必然 FAIL（rank 只有 6 档），与实现正确性无关。
**126/242 条因子含横截面算子**，不只 Alpha101。

### G7 — 取数纪律
- 单次 6000 行上限且**静默截断**；
- **禁用 `offset` 分页**（会返回重复行并漏行）→ 按 `(factor_name, ts_code)` 或 `(factor_name, trade_date)` 单取；
- 日期必须 `YYYYMMDD`，传 `YYYY-MM-DD` 会**静默返回 0 行**；
- QPS 30 / QPM 200，顺序取数。

---

## 5. 输入数据来源

| 数据 | 来源 | 覆盖 |
|---|---|---|
| 行情（全市场） | Tushare `daily` | 至 2026-09-10，5549 行/日 |
| **daily_basic（离线）** | `data/external/tushare/a_share_daily_basic_pit_v1/` | **20160104~20260807 / 2574 交易日 / 5792 只** |
| **财务指标（离线）** | `.../a_share_financial_pit_v1/normalized/fina_indicator.csv.gz` | **116 列 / 5802 只 / 89 个报告期（20091231~20260630）** |
| 三大报表（离线） | `.../a_share_financial_pit_v1/recent_3tables/` | 5690 只 × 3 表（精简列） |
| 三大报表（历史，离线） | `.../a_share_financial_pit_v1/full/normalized/batch_*/` | 2009-2024（完整列） |
| 指数行情 | Tushare `index_daily` | — |

⚠️ `data/external/tushare/market_daily_v1/` **每只仅 36 行（35 个交易日）**，不可用于长窗口因子。

---

## 6. 产出物索引

| 文件 | 内容 |
|---|---|
| `factor_formulas.json` | 252 条因子公式（242 当前 + 10 个 `_old_` 快照） |
| `FORMULA_AUDIT.md` | 横截面扫描 / 参数清单 / 直通因子 / 与聚宽交叉验证 |
| `FACTOR_STATUS.json` | 242 条逐因子状态（族 / 应有判据 / 是否直通 / 公式 / 归档原因） |
| **`CONVENTIONS.md`** | **口径约定与验证记录（G1~G7 + 逐批标定表）** |
| `SUMMARY.md` / `SUMMARY.csv` / `SUMMARY_BY_FAMILY.csv` | 精度总账（自动生成） |
| `batch1_compare_settled.csv` | 批次一精度报告 |
| `batch2_compare_settled.csv` / `batch2_variants.csv` / `batch2_skipped.csv` | 批次二精度报告 + 42 条口径变体标定 |
| `value_compare_settled.csv` | Value 族（`book_to_market` + 8 条 2026-09-21 新实现因子） |
| `value_variant_scan.csv` / `value_sign_scan.csv` / `value_dual_criterion.csv` | Value 族口径变体 / 符号假设 / 双判据对照 |
| `quality_growth_xs_2024.csv` | Quality/Growth 横截面秩相关报告 |
| `phaseA_xs_validation.csv` | Alpha101 全市场横截面 `Rank` 验证 |
| `xs_median_error.csv` | 横截面因子的「中位相对误差」补测（用户口径）|
| **`VERIFIED_FACTORS.md`** | **已验证因子清单与归档（含口径修正、否证清单、逐条归档原因）** |
| `final8_scan.csv` / `final8_scan_oos.csv` | 最后 8 条疑难因子的跨日多口径标定（含样本外）|
| `cache/` | 官方因子值 / 面板 / 财务数据 / `value_local.pkl` 缓存 |

---

## 7. 关键标定结论速查（详见 `CONVENTIONS.md`）

| 结论 | 说明 |
|---|---|
| `CrossSectionalRank(x) = rank(x)/N` | 升序 1..N；官方 N=5430；5430 行互异 |
| `size` 文档公式**有误** | 应为 `−log(total_mv/100)`；文档的 `−log(总股本×收盘价/1e6)` 与官方 **corr=−0.02** |
| `book_to_market` 的 `_pri` 后缀**误导** | 实为**期末**值，且**必须计入递延所得税资产** |
| `rsi` 用 **Wilder 平滑 `ewm(com=13)`** | `span=14` / SMA14 / 原始价全 FAIL |
| `price_dist` 用 **`ceil`** | `nearest` corr −0.10 |
| `rsrs` / `price_position_ir_60d` 用 **`ddof=1`** | `ddof=0` 仅 APPROX |
| `alpha_*d_*` 指数回归用**后复权 + 简单收益** | 原始价相对误差 0.17~0.35 |
| `sales_to_market` = **单季**营收 / **总**市值 | 流通市值口径 corr 降到 0.944 |
| `earnings_cut_to_market` = **归母**净利润 TTM / 总市值 | 文档字面写「扣非」，实测归母 **0.999997** vs 扣非 0.941（§5.14）|
| `roa_ttm` = **TTM 归母净利润 / 期末总资产** | Tushare 预计算 `roa` 只有 0.75 |
| 直通因子 8 个 | 实测 **6 条逐位 EXACT**，2 条 APPROX |
