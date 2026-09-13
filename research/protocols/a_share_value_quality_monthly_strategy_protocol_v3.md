# 沪深非金融 A 股价值/质量多因子月度策略 ST 过滤对照协议 v3

## 1. 状态、问题与授权边界

状态：`design_frozen_before_backtest`

承接 v2（`a_share_value_quality_monthly_strategy_protocol_v2.md`）：组合信号
做行业/市值中性化后，封存期 2023-2025 翻正（+9.8%，IR 0.67），证明 v1 的
封存期亏损来自风格暴露而非信号失效。但 v1/v2 均**未做 ST 过滤**（已声明为
已知偏差）。

价值因子天然倾向选出"最便宜"的股票，而 A 股最便宜的股票中混有大量
ST/*ST/退市整理股——它们是"价值陷阱"：回测按正常价格成交计入收益，实盘
却买不进/卖不出甚至退市归零。本协议回答：

```text
剔除 ST/*ST/退市整理期股票后，中性化组合的封存期超额是否仍为正？
```

本协议只授权一次 ST 过滤对照回测，不授权调优 topk/加权/过滤阈值，不修改
因子定义。

## 2. ST 状态数据（冻结）

| 项 | 固定值 |
|---|---|
| 来源 | `data/external/tushare/a_share_st_status_pit_v1/normalized/st_status_intervals.csv.gz` |
| 口径 | Tushare `namechange` 区间：`[start_date, end_date)` 内该股票处于该名称/状态 |
| ST 判定 | 区间内名称含 "st"（大小写不敏感）→ `is_st=True` |
| 退市整理判定 | 区间内名称含 "退" → `is_delist_phase=True` |
| 过滤规则 | `asof_date` 当日 `is_st` 或 `is_delist_phase` 为真的股票，从当月选股样本中剔除（composite 置 NaN） |

## 3. 唯一对比

| 版本 | 处理 | 角色 |
|---|---|---|
| v2 | 中性化选股，未过滤 ST | 对照（已有结果） |
| **v3** | 中性化选股 + ST/退市整理过滤 | **本协议唯一检验** |

股票池、流动性过滤、topk=50、月度换手、执行时点、成本与 v2 完全一致。

## 4. 回测设置（与 v2 相同）

- 股票池：非金融 A 股；流动性过滤剔除前 20 日均额最低 20%；
- 中性化：composite 对 log(自由流通市值) + 申万一级行业哑变量 OLS 残差；
- topk=50 等权，月度换手；t+1 开盘价成交，涨跌停 9.5%，最低佣金 5；
- 基准 SH000852；成本两套：基准（买 0.05%/卖 0.15%）、压力（买 0.10%/卖 0.30%）；
- 区间 2014-01-01 至 2025-06-30；报告全期 + 三阶段 + 分自然年。

## 5. 预设判定

- 若 v3 封存期压力成本后年化超额 > 0 且 IR > 0 → ST 过滤不破坏 alpha，
  价值 alpha 真实，进入可交易池细化（滑点/容量）；
- 若 v3 封存期转负或大幅缩水 → 此前收益部分依赖 ST 陷阱，如实记录，
  需评估剩余 alpha 是否值得继续。

## 6. 产物与目录

```text
output/analysis_fundamental/a_share_value_quality_monthly_strategy_v3_st_filtered/
  monthly_st_filtered_signal.csv.gz
  st_filter_summary.csv
  backtest_summary.csv
  yearly_summary.csv
  decision.json
  methodology.json
  strategy_report.txt
```

## 7. 结论边界

本对照检验 ST 陷阱对组合收益的影响。成交价仍为开盘价（滑点未单独建模），
1 日成交滞后仍存在；结果只说明"剔除 ST 陷阱后 alpha 是否真实"。
