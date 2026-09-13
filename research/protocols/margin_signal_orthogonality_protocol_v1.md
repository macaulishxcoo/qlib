# 融资融券信号正交性与发布滞后对齐检验协议 v1

## 1. 状态、问题与授权边界

状态：`design_frozen_before_data`

承接另一会话的 margin 建议 1/2 实验（数据可用性 ✅、信号有效性 ✅，`rzye_zscore`
20 日负 IC -0.043、2021 后增强、中性化后存活）。但"独立于价量衰减"只证明了
**时间上**不同步衰减，未证明**截面上**独立于价量因子；且 ICIR 与发布滞后
对齐未做硬校验。本协议只回答两个问题：

```text
Q1. 融资余额信号是否按"发布滞后"正确对齐（T 日盘后公布，T+1 才可见）？
Q2. rzye_zscore / rzye_chg5d 与换手率/量比/动量/波动率等价量因子的截面
    相关性是否 < 0.4（即真正正交，而非换手率的代理）？
```

本协议不训练模型、不回测、不构造新信号；只做数据对齐校验与截面相关性检验。

## 2. 信息边界与数据

| 项 | 固定值 |
|---|---|
| margin 数据 | Tushare `margin_detail`，2016-01-01 至 2026-08-07（全量重拉） |
| 存储 | `data/external/tushare/margin_pit_v1/`（按日 csv.gz + manifest） |
| 价量因子 | Qlib `cn_data_2026`：换手率、量比、20 日动量、20 日波动率 |
| 股票池 | 沪深普通 A 股（非金融口径用于主策略；相关性检验用全 A 可算样本） |

## 3. Q1：发布滞后对齐检验（冻结方法）

融资余额 `rzye` 为 T 日收盘后披露、T+1 交易日才可交易决策使用。检验方法：

1. 取样本股票（如 50 只）连续 30 个交易日的 `rzye`，与 Tushare 官方文档
   确认披露时点（margin_detail 字段为当日盘后值）；
2. 构造两个对齐版本：
   - `aligned`：信号日 = 数据日 + 1 交易日（T+1 使用 T 日数据）；
   - `misaligned`：信号日 = 数据日（当日使用当日数据，未来函数）；
3. 分别计算 20 日负 Rank IC，对比两者：
   - 若 `aligned` 的负 IC 保持显著（|IC| 损失 < 30%），判定当前用法正确；
   - 若 `misaligned` 显著强于 `aligned`，则之前结论被未来函数污染，需按
     `aligned` 重估。

本步骤的结论写入 `decision.json` 的 `lag_alignment` 字段。

## 4. Q2：截面正交性检验（冻结方法）

对每个交易日 `t`（2016-2026 全样本）：

| 信号 | 定义（使用 t-1 及更早可见数据） |
|---|---|
| `rzye_zscore` | 250 日窗口 `rzye` 的 z-score（至少 60 日历史） |
| `rzye_chg5d` | `rzye(t-1) / rzye(t-6) - 1` |

| 价量因子（Qlib，t-1 时点值） | 定义 |
|---|---|
| 换手率 | `$volume / $float_share`（或 qlib 已有字段） |
| 量比 | 当日量 / 过去 5 日均量 |
| 20 日动量 | `Ref($close, -20)/Ref($close, -1) - 1`（反向） |
| 20 日波动率 | `Std($close, 20)/$close` |

对每个交易日，在截面内计算信号与各价量因子的 **Spearman 相关**；汇总为
每日相关的时间序列，报告均值、标准差、|均值| > 0.4 的天数占比。

判定（预先冻结）：
- 若 `rzye_zscore` 与所有价量因子的 |均值截面相关| < 0.4 → `orthogonal`，
  允许以过滤层身份进入 v5；
- 若任一 ≥ 0.4 → `proxy_of_pv_factor`（具体指明是哪个价量因子的代理），
  降级为廉价替代，不单独投入。

## 5. 产物与目录

```text
output/analysis_fundamental/margin_signal_orthogonality_v1/
  lag_alignment_check.csv
  cross_section_correlation.csv.gz
  correlation_summary.csv
  decision.json
  methodology.json
  orthogonality_report.txt
```

数据产物：`data/external/tushare/margin_pit_v1/`（按日 raw + manifest）。

## 6. 预设结论与后续

- `orthogonal` + 滞后对齐正确 → 进入 v5（月度策略加 margin 过滤层，对比
  回撤与超额）；
- `proxy_of_pv_factor` 或滞后对齐失败 → 停止该信息源，记录原因，不追加公式。

## 7. 结论边界

本协议只检验"正交性"与"对齐正确性"，不重新估计信号有效性（另一会话已做）；
不模拟交易成本。
