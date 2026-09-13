# 前瞻跟踪链路打通 + 模拟盘两处缺陷修复

| 项 | 值 |
|---|---|
| 脚本 | `scripts/generate_five_factor_veto_holdings_v1.py`（加 live_ledger 输出）、`scripts/paper_trading_tracker_v1.py`（2 处修复） |
| 驱动 | `scripts/migration/wsl_run_holdings.sh` → `wsl_run_paper_trading.sh` |
| 日期 | 2026-09-13 |

## 1. 为什么做这个

策略在历史数据上已无法再取得可信证据（效应可能部分来自样本内定义，
全期 +17.4pp 有 2/3 来自 2016-2019）。**唯一能回答"是不是真的"的办法是在
真实前瞻下持续记录。** 本轮把这条链路打通。

## 2. 新增：持仓生成器直接写 live_ledger

`generate_five_factor_veto_holdings_v1.py` 现在除持仓 CSV 外，还写出：

```text
output/live_ledger/signal_YYYY-MM-DD_ffveto.csv   (ts_code, action, industry,
                                                   close, shares, target_value,
                                                   weight, score)
```

格式对齐既有 `paper_trading_tracker_v1.py` 的输入约定，**复用而非重写**跟踪器。

同时加了**数据完整性断言**（回应上一轮的静默 NaN 缺陷）：
若 asof 当日查不到任何价格，**直接失败退出**，不再安静地产出全 0 清单。

## 3. 修复缺陷 A：调仓日存在 1 日前瞻

`paper_trading_tracker_v1.py::get_holdings_on` 原为：

```python
valid = signals[signals["rebalance_date"] <= date]      # 错
```

而 `daily_return` 是 `close(prev_day) → close(day)`。两者相乘的后果：
**在每个调仓日，用"新选出的组合"去赚"信号生成之前那一天"的收益** ——
即每个调仓日凭空多出 1 天不可实现的前瞻收益。10 日调仓下约占 10% 的交易日。

**已改为 `<`**：信号在 t 日收盘生成、t+1 开盘成交，故 t 日当天仍持有上一期组合。

> 首次运行时该缺陷表现为：信号日期 2026-09-11，却在 2026-09-11 当天
> 记出 −1.86% 的收益（用 09-10 收盘建仓）。

## 4. 修复缺陷 B：状态页初始资金恒定 100,000

`PORTFOLIO_CAPITAL` 只在 `--init` 分支被赋值，`--status` 读到的一直是模块默认值
100,000。于是 `--init --capital 500000` 之后状态页显示
「初始资金 100,000 / 当前净值 490,688 / **累计收益 +390.69%**」——荒谬数字。

**已改为从 NAV 日志首行取初始资金。**

## 5. 修复后的状态

```text
初始资金:        500,000 元
当前净值:        500,000.00 元
当前持仓数:      0
最新日期:        2026-09-11
```

**持仓数为 0 是正确行为**，不是故障：信号日期 2026-09-11 于 **t+1（下一交易日）**
才生效，而 2026-09-11 已是当前最后一个有行情的交易日。下一次运行时
（数据推进到 09-14 及以后）即会持有 30 只。

## 6. 已知局限

1. 跟踪器按 **收盘价** 计净值，而策略实际按 **t+1 开盘** 成交；
   前瞻期内净值会与实际开盘成交存在偏差。若要求精确，需改按开盘价计价。
2. 未计入 5 元最低佣金与整手约束（跟踪器为等权虚拟净值）。
   **历史回测（qlib）已含这两项**，故这不影响此前结论，仅影响模拟盘口径。
3. 策略清单需要**每 10 个交易日重新生成**；当前无自动化调度。

## 7. 下一步

1. 每 10 个交易日重跑 `wsl_run_holdings.sh` 生成新信号（可挂自动化）。
2. 定期跑 `wsl_run_paper_trading.sh --update` 与 `monitor_strategy_decay_v1.py`。
3. 累积 ≥6 个月前瞻记录后，再评估"效应是否仍然存在"。
