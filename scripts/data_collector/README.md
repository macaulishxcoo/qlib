# Data Collector

## Introduction

Scripts for data collection

- yahoo: get *US/CN* stock data from *Yahoo Finance*
- fund: get fund data from *http://fund.eastmoney.com*
- cn_index: get *CN index* from *http://www.csindex.com.cn*, *CSI300*/*CSI100*
- us_index: get *US index* from *https://en.wikipedia.org/wiki*, *SP500*/*NASDAQ100*/*DJIA*/*SP400*
- contrib: scripts for some auxiliary functions


## Custom Data Collection

> Specific implementation reference: https://github.com/microsoft/qlib/tree/main/scripts/data_collector/yahoo

1. Create a dataset code directory in the current directory
2. Add `collector.py`
   - add collector class:
     ```python
     CUR_DIR = Path(__file__).resolve().parent
     sys.path.append(str(CUR_DIR.parent.parent))
     from data_collector.base import BaseCollector, BaseNormalize, BaseRun
     class UserCollector(BaseCollector):
         ...
     ```
   - add normalize class:
     ```python
     class UserNormalzie(BaseNormalize):
         ...
     ```
   - add `CLI` class:
     ```python
     class Run(BaseRun):
         ...
     ```
3. add `README.md`
4. add `requirements.txt`


## Description of dataset

  |             | Basic data                                                                                                       |
  |------------------------------------------------------------------------------------------------------------------|---------------------------------------------------------------|
  | Features    | **Price/Volume**: <br>&nbsp;&nbsp; - $close/$open/$low/$high/$volume/$change/$factor                             |
  | Calendar    | **\<freq>.txt**: <br>&nbsp;&nbsp; - day.txt<br>&nbsp;&nbsp;  - 1min.txt                                          |
  | Instruments | **\<market>.txt**: <br>&nbsp;&nbsp; - required: **all.txt**; <br>&nbsp;&nbsp;  - csi300.txt/csi500.txt/sp500.txt |

  - `Features`: data, **digital**
    - if not **adjusted**, **factor=1**

### Data-dependent component

> To make the component running correctly, the dependent data are required

  | Component      | required data                                     |
  |---------------------------------------------------|--------------------------------|
  | Data retrieval | Features, Calendar, Instrument                    |
  | Backtest       | **Features[Price/Volume]**, Calendar, Instruments |

---

## 日频增量更新（主线数据管道，阶段 1）

> 用途：每个交易日收盘后，把 tushare 最新行情增量追加到 `~/.qlib/qlib_data/cn_data_2026`
> （Alpha158 管线使用的同一数据目录）。配套脚本：

| 脚本 | 作用 |
|---|---|
| `update_daily_market_data_v1.py` | 增量拉取 tushare 行情（stock 复权 + index）→ 写入 raw CSV → `dump_bin dump_update` 追加到 qlib 二进制目录 → 自动修复停牌错位 |
| `verify_market_data_update_v1.py` | 更新前验证数据口径（close/vwap/factor 与 tushare 一致性）；`--check-update` 模式在更新后自检追加数据 |
| `repair_market_data_update_v1.py` | 修复 `dump_update` 对停牌股产生的错位/缺失；`--check` 审计，`--repair` 修复 |

> **已知坑（勿再踩）**：`dump_bin dump_update` 假定增量区间每天都有数据行，
> 停牌股缺行会导致该股增量段整体错位 N 天或尾部缺失。`update_daily_market_data_v1.py`
> 已在 dump 后自动调用 repair 逻辑重建增量窗口（按 raw 值 + 日历对齐，停牌日填 NaN），
> 无需手动处理。主脚本的 checkpoint（`aux/completed_dates.csv`）仅在 dump+repair
> 成功后才写入，失败重跑同一命令即可续跑。

### 运行

```bash
conda activate qlib
# 1) 增量更新（自动跳过已有交易日；断点续跑：已完成日期记录在 aux/completed_dates.csv）
python scripts/data_collector/update_daily_market_data_v1.py
# 2) 更新后自检（建议每次更新后执行）
python scripts/data_collector/verify_market_data_update_v1.py --check-update --end-date 2026-08-07
```

产物目录 `data/external/tushare/market_daily_v1/`：
- `raw/*.csv`：每只股票/指数一文件，字段 `symbol,date,open,high,low,close,volume,amount,change,factor,vwap,adjclose`（后复权口径）
- `aux/k_factor_stock.csv`：每股复权比例 K = `close_bin_last / adjclose_bin_last`（从既有 bin 校准，零 API 请求）
- `aux/completed_dates.csv`：已完成交易日 checkpoint

### cron 配置示例

```crontab
# qlib 日频行情更新，工作日收盘后 17:35（北京时间）；conda 环境用绝对路径的 python
35 17 * * 1-5  cd /home/xiaocong/worksapces/qlib && \
    /home/xiaocong/anaconda3/envs/qlib/bin/python \
    scripts/data_collector/update_daily_market_data_v1.py \
    >> /home/xiaocong/worksapces/qlib/output/logs_static/daily_update.log 2>&1
```

注意事项：
- cron 环境无 conda 初始化，须用绝对路径的 python（如上）
- TUSHARE_TOKEN 未设置时，脚本回退读取 `/root/.config/tushare/token`
- 失败日记录在 `aux/failed_dates.csv`；重跑同一命令即续跑
- 自检可另加一条 cron 在更新后 10 分钟执行；验证失败会退出非 0 并告警

### 口径说明（实测验证，勿改动）

`cn_data_2026` 的 close/vwap 为**后复权价**：`qlib_close = ts_close_raw × qlib_factor`。
增量不能直接追加 tushare 原始价，否则每个除权日产生跳变。脚本用
`factor = ts_adj_factor × K_stock` 重算复权（K 每股不同，按股校准）。
Alpha158 仅使用 `$close`/`$vwap`（label 也用 close 比价），所以 close/vwap 口径是
正确性的关键；`factor`/`adjclose` 为完整记录，不被 Alpha158 直接消费。