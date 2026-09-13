# PEAD（正式财报公告后漂移）研究协议 v1

## 1. 状态与授权

状态：`design_frozen_before_experiment`

依据：`research/decisions/a_share_event_driven_pead_proposal_v1.md`（选题已评审）。
本协议冻结实验设计，只授权一轮最小实验，不授权调优。

## 2. 研究问题

```text
A 股正式财报公告（ann_date）后 5/10/20 日，公告股票相对基准（SH000852）
是否有显著的市场调整超额收益？漂移方向是否与盈余方向（netprofit_yoy 正/负）
一致？该效应是否独立于截面动量？
```

## 3. 事件定义（冻结）

| 项 | 固定值 |
|---|---|
| 事件日 | `fina_indicator.ann_date`（正式财报公告日） |
| 母池 | 沪深普通 A 股（与价值/质量策略同一母池） |
| 盈余方向 | `netprofit_yoy > 0` = 正向公告；`netprofit_yoy < 0` = 负向公告；`netprofit_yoy = NaN` -> 不分组但保留在"全公告"组 |
| 去重 | 同一股票同一 `end_date` 取最早 `ann_date`（首次公告） |

## 4. 实验设计（冻结）

### 4a. 超额收益计算

- 事件日 T = `ann_date`（若非交易日，取下一个交易日）
- 入场价 = T 日开盘价（`$open`）
- 出场价 = T+5 / T+10 / T+20 个交易日后的开盘价
- 个股超额 = 个股收益 − SH000852 同期收益
- 市场调整超额 = mean(所有事件个股超额)

### 4b. 分组

| 组 | 条件 |
|---|---|
| All | 全部公告事件 |
| Positive | `netprofit_yoy > 0` |
| Negative | `netprofit_yoy < 0` |

### 4c. 动量正交性检验（关键）

与事件流评估相同的方法：事件股票按公告前 20 日收益率分 5 组，检验公告后超额
是否在各动量组间一致。如果超额随动量组单调变化 -> 超额是动量暴露，非事件信息。

### 4d. 时间窗口

- 检验窗口：2022-01-01 ~ 2026-07-31
- 分年度报告：2022 / 2023 / 2024 / 2025 / 2026
- 分财报季集中段：1-4 月（年报披露季）、7-10 月（中报+三季报披露季）

## 5. 预设判定（冻结）

| 条件 | 判定 |
|---|---|
| All 组 5/10/20 日超额 \|t\| > 2，且 Positive 与 Negative 方向相反 | `pead_viable` -> 进 S2 组合回测 |
| 超额显著但 Positive/Negative 方向相同（均为正或均为负） | `pead_direction_unclear` -> 记录，不进组合 |
| 超额不显著（\|t\| < 2） | `pead_not_supported` -> 关闭 |
| 超额显著但动量正交性检验显示为动量暴露 | `pead_is_momentum_artifact` -> 关闭 |

**不做**：不调优持有期（固定 5/10/20）、不搜索其他盈余代理（固定 netprofit_yoy）、
不加入业绩预告/快报、不做公告文本情绪。

## 6. 数据与边界

| 数据 | 来源 | 覆盖 |
|---|---|---|
| 事件日 + 盈余方向 | `fina_indicator` (normalized) | ann_date 到 2026-08-11，netprofit_yoy 非空率 95% |
| 行情 | `~/.qlib/qlib_data/cn_data_2026` (`$open`, `$close`) | 到 2026-08-07 |
| 基准 | SH000852 (`$close`) | 已修复 2026-07-24 断裂 |

零新增下载。

## 7. 产物

```text
output/analysis_static/a_share_pead_v1/
  pead_excess_by_horizon.csv    (全公告/正向/负向 x 5/10/20 日超额 + t 值)
  pead_yearly_breakdown.csv     (分年度超额)
  pead_momentum_orthogonality.csv (动量分组正交性检验)
  decision.json
  strategy_report.txt
scripts/analyze_a_share_pead_v1.py
```

## 8. 结论边界

PEAD 在美股是最稳健的异象之一，但 A 股散户占比高、T+1、涨跌停限制，
underreaction 机制可能不同（假设模板 §3.2 已标注 A 股动量弱、反转强）。
预期放低：此实验的价值是**关闭最后一个未测的大信息类别**，
若有效则获得一个与价值/质量正交的事件驱动信号，若无效则日频信息源路线全部闭环。
