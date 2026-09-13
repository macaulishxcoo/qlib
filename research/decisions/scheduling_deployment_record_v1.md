# 调度部署记录：每日模拟盘更新 + 月度调仓名单生成 v1

> **文档定位**：工程记录。记录 ZCode 定时自动化的部署状态（已建/待建）、本次修复的
> 网格 bug、模拟盘 8 月段重建，供后续会话直接接手，避免重复排查。
> **性质**：只读记录。日期 2026-08-17。

---

## 1. 已部署的 automation（ZCode 自动化）

| 任务 | cron | 状态 | 说明 |
|---|---|---|---|
| 每日数据更新：行情+daily_basic | `35 17 * * 1-5` | ✅ active（其他窗口建） | 行情 bin + daily_basic normalized |
| **每日模拟盘更新（双过滤臂）** | `40 17 * * 1-5` | ✅ active（本会话建，automation-bc609de3） | `paper_trading_tracker_v1.py --update --signal-pattern "signal_*_vt+t5.csv"` + status |
| **月度调仓名单生成** | `45 17 * * 1-5`（待建） | ⏳ **未建** | 见 §3 |

## 2. 本次修复的网格 bug（重要）

`backtest_a_share_value_quality_monthly_dailygrid_v6.py` 的 `build_daily_grid()` 原本
硬编码 `BT_END=2026-06-30`，导致信号管道的调仓网格**截止 6-30**——`--date 2026-07-31`
回退到 6-30 名单（7 月调仓名单生成不出来）。

修复：`build_daily_grid(end=None)` 新增 `end` 参数，默认 `BT_END`（回测可复现）；
信号管道 `load_aux(end=calendar[-1])` 传最新日历日。验证：7-31 名单正常生成。

## 3. 待建：月度调仓名单生成 automation

- **方案 A（推荐）**：每天 17:45 检查是否月末交易日，是则生成名单、否则秒退；
- 生成命令：`python scripts/run_daily_signal_pipeline_v1.py --date <月末> --top-k 15 --live --value-trap-filter --t5-filter`；
- **受限**：本会话已建 1 个 automation，系统限制同一会话只能建 1 个 scheduled task；
  需**新开会话**创建（CronCreate 参数见会话记录）。

## 4. 模拟盘状态（2026-08-17）

| 段 | 名单 | 日期范围 | NAV | 备注 |
|---|---|---|---|---|
| 7 月段 | `signal_2026-06-30_vt+t5.csv` | 2026-07-01~07-31 | +5.89%（超额 +17.70%） | 备份 `nav_log_2026-07_630list.csv` |
| 8 月段 | `signal_2026-07-31_vt+t5.csv` | 2026-08-03~08-14 | +1.84% | 当前 `nav_log.csv`（持仓已验证 = 7-31 名单） |

**月度调仓节奏已恢复**：6-30 名单 → 7 月持仓 → 7-31 名单 → 8 月持仓。下次 8-31 名单
由待建 automation 生成。

## 5. 日常维护

```bash
# 每日（automation 自动）：模拟盘更新
python scripts/paper_trading_tracker_v1.py --update --signal-pattern "signal_*_vt+t5.csv"

# 月度（automation 自动）：月末调仓名单
python scripts/run_daily_signal_pipeline_v1.py --date <月末> --top-k 15 --live --value-trap-filter --t5-filter

# 数据更新（automation 自动，17:35）
python scripts/data_collector/update_daily_market_data_v1.py
python scripts/data_collector/update_daily_basic_v1.py
```

## 6. 变更记录

| 日期 | 变更 |
|---|---|
| 2026-08-17 | 创建：调度部署记录——修复网格 bug（build_daily_grid 支持 end 参数，管道网格延伸至最新数据）；重建模拟盘 8 月段（7-31 名单）；建每日模拟盘更新 automation；月度调仓 automation 待新会话创建 |
