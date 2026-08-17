# 主线路线图：沪深主板日频选股量化交易系统 v1

> 目标重锚：本项目只做一件事——**沪深主板日频选股量化交易系统**。
> 基本面研究轨道冻结声明（`research/decisions/a_share_fundamental_research_freeze_v1.md`）
> 已于 2026-08-13 依用户指示解除约束（冻结为当时条件下的资源分配决策，非未来研究门槛）。
> 本路线图是主线工作的唯一执行依据。

---

## 0. 已就绪资产（不要再重新研究）

| 资产 | 位置/状态 |
|---|---|
| 行情数据 | `~/.qlib/qlib_data/cn_data_2026`（2000-01 ~ 2026-07，含 csi300/500/800/1000） |
| 模型配置 | `LGBModel + Alpha158`，csi300 滑点扫描结论：`sliding + n_drop=5 + 真实费率` |
| 训练配置 | `examples/benchmarks/LightGBM/workflow_config_lightgbm_Alpha158_csi500/csi1000_static_*.yaml` |
| 结果分析 | `analyze_static_results.py`（HTML 报告）+ `metrics_judgment_standard.md` |
| 根因诊断 | `DEV_LOG_RollingTrainingOptimization.md`：2021 后概念漂移、alpha 衰减，非流程 bug |

**已确认的风险（实盘前必须处理，无需再验证）**：
1. 静态模型 IC 弱（2025-2026 测试段 Daily IC 为负）；
2. 需要滚动训练对抗漂移（DDG-DA 为候选）；
3. `close` 撮合理想化，未含滑点。

---

## 阶段 1：数据管道自动化（当前）

**目标**：每个交易日收盘后自动增量更新 `cn_data_2026`，无需人工干预。

| 任务 | 验收标准 | 状态 |
|---|---|---|
| 日频增量更新：tushare `daily` 拉取当日 OHLCV → `dump_bin` 增量写入 `cn_data_2026` | 一条命令跑通，数据日期 = 最新交易日 | ✅ 2026-08-07 完成（见下） |
| 交易日历管理：缺数据的交易日标记、非交易日跳过 | 日历文件正确，无重复写入 | ✅ |
| 更新结果自检：新交易日样本数与前一交易日偏差告警 | 异常时输出日志而非静默通过 | ✅（check_update 模式） |
| 定时执行：收盘后自动触发（cron），失败自动重试并通知 | 连续 1 周无人值守运行成功 | ⏳ 脚本就绪，cron 待部署 |

### 阶段 1 实施记录（2026-08-07）

**脚本**：
- `scripts/data_collector/update_daily_market_data_v1.py` —— 日频增量更新主脚本
- `scripts/data_collector/verify_market_data_update_v1.py` —— 口径验证（更新前）+ 更新后自检
- `scripts/data_collector/repair_market_data_update_v1.py` —— 停牌错位修复（`--check` 审计 / `--repair` 修复）

**关键口径结论（已实测验证）**：`cn_data_2026` 的 close/vwap 为**后复权价**
（`qlib_close = ts_close_raw × qlib_factor`，factor 除权日跳变）。增量必须重算复权，
不能直接追加原始价。每股复权比例 K 不同（sh600000=0.0391, sz000001=0.0025），
K 由 bin 内部 `close_last/adjclose_last` 校准，零 API 请求。

**已发现并修复的 bug（重要）**：`dump_bin dump_update` 对增量区间内**停牌**的股票
会产生错位/缺失（append 假定每天都有行，停牌缺行 → 后续值整体偏移 N 天或尾部缺失）。
首次更新 5545 只中 18 只受影响（如 sz000793、sh688277），已用
`repair_market_data_update_v1.py --repair` 按 raw 值重建修复，修复后三重验证
（全库审计 0 损坏 + 更新自检 ALL PASS + 长度完整性 ALL OK）通过。主脚本在 dump 后
自动执行该修复，无需人工干预。

**运行方式**：
```bash
conda activate qlib
# 增量更新（自动跳过已有日期，断点续跑；dump 后自动修复停牌错位）
python scripts/data_collector/update_daily_market_data_v1.py
# 更新后自检（建议每次更新后运行；失败退出非 0）
python scripts/data_collector/verify_market_data_update_v1.py --check-update --end-date 2026-08-07
# 手动审计/修复（一般不需要，主脚本已内置）
python scripts/data_collector/repair_market_data_update_v1.py --check
```

**落地结果**：日历 6434→6445 天（2000-01-04 ~ 2026-08-07），5535 股票 + 5 指数，
18 只停牌错位修复，最终三重验证全过。

**注意**：指数成分文件（csi300/500/1000.txt）本次未更新（已确认范围外），
依赖历史股票池的回测不受影响；实盘名单生产的当日 universe 需在阶段 2 单独处理。


---

## 阶段 2：信号生产管道

**目标**：每个交易日收盘后自动产出"明日选股名单"。

| 任务 | 验收标准 | 状态 |
|---|---|---|
| 收盘后自动训练/更新模型（先静态，后滚动/DDG-DA） | 输出当季模型 | ⏳ 信号=已验证基本面四因子，模型训练不适用（非 ML 策略） |
| 自动生成全市场预测分 → TopkDropout 生成明日持仓名单 | 输出候选名单（含排名、权重、风险提示） | ✅ 2026-08-11：管道日频网格切换完成，覆盖到 2026-06，一致性 100%，见 `scripts/run_daily_signal_pipeline_v1.py` + `output/signal_ledger/` |
| 信号与名单入库存档（MLflow / 数据库） | 每日记录可回查 | ✅ signal/holding/portfolio 三张台账（CSV） |
| 盘后自动复盘：昨日名单今日表现 → 更新 IC/收益台账 | 与 `metrics_judgment_standard.md` 对齐 | ⏳ 台账已产出，cron 定时执行未部署 |

### 阶段 2 实施记录（2026-08-11）

**策略**：基本面四因子（E/P、BM、股息率、应计质量）→ composite（≥3 因子门槛）
→ 行业/市值中性化 → ST/退市过滤 → 容量过滤 → top50 月度换手。修复了
"因子缺失污染"（缺失股分数虚高顶进 top50）bug，回验 v3/v4/v6 全部通过。

**真实画像（重要）**：策略是**强周期性价值策略**，非稳定 alpha。封存期
2023-2025 修复后 IR 1.33~1.48，但 2026H1 风格逆风（价值 vs 成长）累计超额
-18.6%。**风格风控尝试（HML，v7）已失败并关闭**（单 BM 代理与四因子暴露不同轴，
无法捕捉逆风），周期性风险保持"已知、未解"，实盘前需决策：接受周期性 / 换用法 /
未来新信号。详见
`research/decisions/stage2_pipeline_landed_strategy_profile_v1.md`、
`research/decisions/hml_risk_control_not_effective_closure_v1.md`。

**数据补齐**：财务 PIT 到 2026Q2、市值/行情日频到 2026-08、ST 表、margin 表。

---

## 阶段 3 及以后（暂不展开，按阶段推进）

- 阶段 3：策略执行层（券商接口对接、实盘撮合、下单风控）
- 阶段 4：滚动训练落地（DDG-DA / 滑动窗口 + 验证窗口）
- 阶段 5：实盘试运行（小资金、纸上交易对比）
- 阶段 6：风险与容量控制（ST/停牌/退市过滤、流动性约束、滑点实测）

---

## 执行纪律

1. 每个阶段内按"任务→验收标准"推进，验收不通过不进入下一项；
2. 任何新工作先过三问门槛（服务哪个决策 / 最小版本 / 验收标准），见冻结文档第 5 节；
3. 本路线图变更必须更新本文件并记录原因，不允许口头改道；
4. 基本面相关需求一律回到冻结文档第 3 节的最小接入路径。

---

## 变更记录

| 日期 | 变更 |
|---|---|
| 2026-08-07 | 创建：重锚目标至日频交易系统，冻结基本面轨道，明确阶段 1/2 任务与验收标准 |
| 2026-08-13 | 解除基本面冻结约束（用户指示）：冻结为当时条件下的资源分配决策，非未来研究门槛 |
