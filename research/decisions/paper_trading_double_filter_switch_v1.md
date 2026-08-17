# 模拟盘切换记录：双过滤（价值陷阱 + T5）臂 v1

> **文档定位**：工程变更记录。记录模拟盘从"混合/revfilter 名单"切换到"双过滤
> （vt+t5）名单"的全过程、修复的 tracker bug、以及当前状态。**性质**：只读记录。
> 依据：`research/decisions/a_share_triple_filter_closure_v1.md`（v14 双过滤 = 过滤层
> 最终形态）+ 用户指示"按建议执行"。

---

## 1. 背景

过滤层验证收口：v14 双过滤（价值陷阱 + T5）为最终形态（new_coverage +25.06pp、
holdout +1.93pp）；v15 三层（+revfilter）拒绝。按建议将模拟盘切换到**双过滤名单**
（`signal_*_vt+t5.csv`），实测双过滤在真实环境下的表现（尤其 MDD 真实形态）。

## 2. 修复的 tracker bug（重要）

`scripts/paper_trading_tracker_v1.py` 原 `load_signals()` 用 `sorted(LIVE_LEDGER.glob("signal_*.csv"))`
取全部文件：`signal_2026-06-30_filtered.csv`（revfilter）因字典序靠后被当作最新持仓，
且同一天多文件被合并成**并集**（可能 >15 只）——**切换前模拟盘一直在跟踪 revfilter
名单而非协议原版/双过滤**。

修复：`load_signals(signal_pattern)` 新增 `--signal-pattern` 参数显式指定名单
（如 `signal_*_vt+t5.csv`），同调仓日多文件按文件名字典序末位去重。

## 3. 双过滤名单生成

`run_daily_signal_pipeline_v1.py` 已支持 `--value-trap-filter --t5-filter`（本会话
新增，见脚本），生成 `output/live_ledger/signal_2026-06-30_vt+t5.csv`（top-15，
BUY 3 / SELL 3 / HOLD 12，均带过滤标记）。

## 4. 切换与当前状态

- 备份原 nav_log → `output/paper_trading/nav_log_legacy_mixed_backup.csv`（原混合臂，
  +10.8%，含 revfilter 名单污染，不作为双过滤对照）；
- 初始化双过滤臂：`--init --start-date 2026-07-01 --capital 100000 --signal-pattern "signal_*_vt+t5.csv"`；
- 回填 2026-07-01 ~ 08-14（33 天），最新 NAV **105,891.10**（+5.89%）；

| 指标 | 双过滤臂（2026-07-01 ~ 08-14） |
|---|---|
| 策略累计收益 | +5.89% |
| 基准（SH000852）累计 | −11.80% |
| 累计超额 | **+17.70%** |
| 最大回撤 | −4.31% |
| 硬止损 | 未触发（70,000 线） |

**诚实对比**：原混合臂 +10.8%（revfilter 污染 + 可能并集 >15 只，不可比）；双过滤臂
+5.89% 是干净口径。7-8 月为价值反弹期（基准 −11.8%），策略 +17.7% 超额显著，样本
仅 33 天不做结论外推。

## 5. 日常运行方式（更新）

```bash
python scripts/paper_trading_tracker_v1.py --update --signal-pattern "signal_*_vt+t5.csv"
python scripts/paper_trading_tracker_v1.py --status --signal-pattern "signal_*_vt+t5.csv"
```

每月调仓日用管道带过滤参数生成新名单后，tracker 自动跟随最新 `_vt+t5.csv`。

## 6. 变更记录

| 日期 | 变更 |
|---|---|
| 2026-08-17 | 创建：模拟盘切换至双过滤臂；修复 tracker 名单加载 bug（--signal-pattern + 同调仓日去重）；备份原混合 nav_log；初始化并回填 33 天（+5.89%，超额 +17.70%，MDD −4.31%） |
