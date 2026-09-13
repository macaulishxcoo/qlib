# 五因子 top-30 信号管道落地与验证 v1

## 1. 决策

状态：`pipeline_landed_five_factor_top30`（2026-08-18）

信号管道 `run_daily_signal_pipeline_v1.py` 已从四因子 top-50 升级为
**五因子 top-30**（ep+bm+div_yield+accruals+g2，≥4/5 门槛）。
验证通过：管道 top-30 完全包含 v2 回测的 top-15（15/15 重叠）。

**现有 v8+v11 模拟盘不动**，五因子 top-30 作为新形态并存。

## 2. 改动清单

`scripts/run_daily_signal_pipeline_v1.py`：

| 位置 | 原值 | 新值 |
|---|---|---|
| `TOP_K` | 50 | **30** |
| composite 计算 | `composite_score(frame)` 四因子 ≥3 门槛 | `composite5_score(frame)` 五因子 ≥4 门槛 |
| g2 数据 | 无 | `load_g2_series()` + `g2_at()` PIT 加载 |
| `process_month` | 调 `composite_score` | 加 `fin_g2` 参数，调 `composite5_score` |
| 四处 `process_month` 调用 | 无 fin_g2 | 全部传 `fin_g2=fin_g2` |

**未改动的已有模块**（保护 v8 等已验证策略）：
- `analyze_a_share_value_quality_level_factors_extension_v1.py` 的
  `composite_score`、`build_snapshot`、`ols_residual` 原样不动
- `load_financials_extended_v1.py` 原样不动
- 过滤层（v11 超买/v12 T5/v13 价值陷阱）代码原样不动

## 3. 验证

### 3.1 管道输出（2026-06-30 top-30）

```
BUY  (7):  000425.SZ, 000528.SZ, 000975.SZ, 002637.SZ, 600150.SH, 603173.SH, 603279.SH
SELL (7): 000719.SZ, 000725.SZ, 003015.SZ, 600267.SH, 600742.SH, 603380.SH, 688093.SH
HOLD (23): 002249.SZ, 002296.SZ, ...
```

输出文件：`output/live_ledger/signal_2026-06-30.csv`（30 只，等权 3.33%）

### 3.2 一致性校验

v2 回测面板的 2026-06-30 top-15 与管道 top-30 重叠 15/15 -- 管道的
top-30 是 v2 回测 top-15 的超集，信号逻辑一致。

### 3.3 行业集中度

| 统计 | top-30 月均 | 2026-06 实际 |
|---|---|---|
| 单行业最大占比 | 20.2% | **36.7%**（异常） |
| 前三行业合计 | 46.9% | 63.3% |

2026-06 是 126 个月中集中度第 2 高的月份（机械设备 11/30）。
月均 20.2% 符合预期，但极端月份仍会冲高。这是后续加行业暴露上限
的正当理由，但按反 snooping 原则不在本轮做。

## 4. 使用方式

```bash
# 生成最新月份 top-30 信号名单
python scripts/run_daily_signal_pipeline_v1.py --date 2026-06-30 --top-k 30 --live

# 历史重演验证
python scripts/run_daily_signal_pipeline_v1.py --replay --from 2024-01-01 --to 2025-06-30 --top-k 30

# 过滤层仍可用（但五因子基线上不推荐，见 v16 closure）
python scripts/run_daily_signal_pipeline_v1.py --date 2026-06-30 --top-k 30 --live --overbought-filter
```

## 5. 遗留

1. **行业暴露上限**：2026-06 的机械设备 11/30 暴露了单月集中风险。
   后续可加"单行业 ≤4 只（13.3%）"约束，需另立实验
2. **模拟盘切换**：当前 v8+v11 模拟盘继续运行；五因子 top-30 的
   模拟盘初始化需另做（新持仓、新净值基线）
3. **cron 数据更新**：需确认 cron 任务拉取的 fina_indicator 包含
   dt_netprofit_yoy 列（已在顶层 normalized 文件中，无需额外拉取）
