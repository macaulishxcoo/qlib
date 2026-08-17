# 个股资金流向（moneyflow）信号验证协议 v1

## 1. 状态与授权

状态：`design_frozen_before_experiment`

方向 B 的首轮实验：测试个股资金流向（moneyflow）是否包含独立于
价值/质量因子的截面 alpha。**只做信号层验证，不碰组合回测、不修改
v8 策略代码。**

## 2. 研究问题

```text
A 股个股资金流向（大单/超大单净买入）的截面排名，
对未来 5/10/20 日收益是否有预测力？
该预测力是否独立于已有的价值/质量四因子（|corr| < 0.3）？
```

## 3. 数据（冻结）

| 项 | 值 |
|---|---|
| 接口 | Tushare `moneyflow`（按 trade_date 下载全市场） |
| 字段 | `net_mf_amount`（净资金流入）、`buy_elg_amount - sell_elg_amount`（超大单净额）、`buy_lg_amount - sell_lg_amount`（大单净额） |
| 窗口 | 2022-01-01 ~ 2026-08-12（与 PEAD/事件流检验可比） |
| 存储 | `data/external/tushare/moneyflow_pit_v1/`（按日 raw + normalized） |

## 4. 信号设计（冻结，不搜索）

| 信号 | 公式 | 逻辑 |
|---|---|---|
| `net_mf_5d` | 过去 5 日 `net_mf_amount` 之和 / 总市值 | 近期主力净流入 |
| `net_mf_20d` | 过去 20 日 `net_mf_amount` 之和 / 总市值 | 中期主力净流入 |
| `elg_net_5d` | 过去 5 日超大单净额之和 / 总市值 | 超大单（机构）净流入 |

用总市值标准化（`total_mv` from daily_basic），消除大盘股绝对额偏大的影响。
截面排名用 `rank(pct=True)`。

**不搜索**：不试 3/10/60 日窗口、不试大单/中单/小单的其他组合、不试非线性变换。
固定以上 3 个信号，跑完判断。

## 5. 验证方法（冻结）

### 5a. RankIC

- 每个交易日，计算信号截面排名 vs 未来 H 日收益截面排名的 Spearman 相关
- H = 5, 10, 20
- 报告：IC 均值、ICIR、IC>0 占比、分年度 IC

### 5b. 与价值/质量因子的正交性

- 计算信号与 `neutral_composite`（v8 面板）的截面相关系数
- |corr| < 0.3 -> 独立信号；|corr| >= 0.3 -> 可能重叠

### 5c. 与动量的正交性

- 计算信号与过去 20 日收益率的截面相关
- |corr| < 0.3 -> 独立于动量

### 5d. 分组单调性

- 按信号分 5 组，检验 Q5-Q1 价差是否显著且单调

## 6. 预设判定（冻结）

| 条件 | 判定 |
|---|---|
| 至少 1 个信号 20 日 IC > 0.02 且 ICIR > 0.3 | `moneyflow_viable` -> 进组合回测 |
| IC 显著但与 neutral_composite |corr| >= 0.3 | `moneyflow_not_orthogonal` -> 记录，不进组合 |
| IC 不显著（< 0.02 或 ICIR < 0.3） | `moneyflow_not_supported` -> 关闭 |
| IC 显著但与动量 |corr| >= 0.3 | `moneyflow_is_momentum` -> 关闭 |

**不做**：不调信号参数、不试其他字段组合、不进组合回测（信号有效后另立协议）。

## 7. 产物

```text
data/external/tushare/moneyflow_pit_v1/
  raw/                    (按日 YYYYMMDD.csv.gz)
  normalized/moneyflow.csv.gz
output/analysis_static/a_share_moneyflow_signal_v1/
  ic_by_horizon.csv       (3 信号 x 3 horizon IC + ICIR)
  ic_yearly.csv           (分年度 IC)
  orthogonality.csv       (与 neutral_composite + 动量的相关)
  quintile_spread.csv     (5 分组价差)
  decision.json
  strategy_report.txt
scripts/download_moneyflow_v1.py
scripts/analyze_a_share_moneyflow_signal_v1.py
research/protocols/a_share_moneyflow_signal_protocol_v1.md
```

## 8. 结论边界

moneyflow 反映短期资金博弈，在 A 股散户占比高的市场中可能有效也可能
是噪音。预期放低：此实验的价值是**判断资金流向是否是独立的 alpha 来源**，
如果有效则获得与价值/质量正交的第二个信号，如果无效则方向 B 的首轮关闭。
