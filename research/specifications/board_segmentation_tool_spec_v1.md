# 板块/市值/风险分层分析工具 v1

> **文档定位**：工具说明。`scripts/analyze_board_segmentation_v1.py` 的使用指南，
> 对应研究母池章程（`research/charters/a_share_research_universe_charter_v1.md` §3）
> 的分层报告要求。方向三（板块分层分析框架）的落地物。

---

## 1. 能力

| # | 能力 | 输出 |
|---|---|---|
| 1 | 板块分层市值分布 | 沪主板/深主板/创业板/科创板的数量、中位/均值/p25/p75/min/max |
| 2 | 市值分档 | 末 N% 分位档 + 任意绝对阈值档（≤30亿、≤20亿…），含板块分布与市值区间 |
| 3 | 风险状态 | ST（PIT 区间匹配）、退市整理、换手率/量比（末档 vs 全市场对照） |
| 4 | 准ST（可选） | bps<0 或 连续两年年报亏损（剔除已ST），全市场与末档占比 |

口径固定：**北交所默认排除**（章程规定沪深母池不含北交所）；市值用 daily_basic
的 `total_mv`（万元，工具内转亿元）；ST 用 PIT 区间匹配（`is_st`/`is_delist_phase`）。

## 2. 用法

```bash
# 最新交易日，末10%档
python scripts/analyze_board_segmentation_v1.py

# 指定日期 + 自定义阈值档
python scripts/analyze_board_segmentation_v1.py --trade-date 20260813 --thresholds 50 30 20

# 末5%档 + 准ST统计（慢：需读财务 PIT）+ 落盘
python scripts/analyze_board_segmentation_v1.py --tail-pct 0.05 --with-quasi-st --out report.csv
```

## 3. 输出示例（2026-08-31 截面）

- 板块市值中位：沪主板 79.4 亿 / 深主板 67.0 亿 / 创业板 50.8 亿 / 科创板 77.7 亿；
- 末10%档（≤26.1 亿）521 只：创业板 177 > 深主板 142 > 沪主板 137 > 科创板 65；
- 末档 ST 率 18.4%（全市场 3.9%）、准ST+ST 合计 42.8%——**微盘池近半不可/不宜交易**；
- 全市场准ST 823 只（15.8%）。

## 4. 已知约束

- 退市整理股在 `is_delist` 单列但当前截面恒为 0（已退市股票不在 daily_basic 里），
  历史截面调用时才有意义；
- 准ST 的"连续两年亏损"用年报（12-31 期）判定，与
  `a_share_distress_split_closure_v1.md` 的 G1/G2 拆分是不同粒度（该文是
  事件层检验，本工具是状态快照）；
- 历史截面（--trade-date 早于 2016）daily_basic 无数据，会直接报错。

## 5. 变更记录

| 日期 | 变更 |
|---|---|
| 2026-09-01 | 创建：固化本会话验证过的板块/市值/ST/准ST/流动性分层统计为标准 CLI 工具 |
