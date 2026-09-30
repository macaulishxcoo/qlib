# JQData（聚宽）数据接入

> 创建：2026-09-15 ｜ 状态：**✅ 已接入可用**（登录通过、取数通过；账号区间 2025-06-07 ~ 2026-06-14）
> 本目录是聚宽 JQData 试用接入的唯一入口。

---

## 0. 为什么不能用官方那两行命令

聚宽文档给的步骤是：

```bash
pip install jqdatasdk
pip install thriftpy2==0.4.20     # 仅当 thriftpy2 编译失败时
```

**在本机这两条都会失败**，原因不是网络（PyPI 与聚宽域名实测均可达），而是文件系统只读：

| 位置 | 状态 |
|---|---|
| conda env `qlib` 的 `site-packages` | ❌ Read-only file system |
| `$HOME`（`/root`）与 `/root/.local` | ❌ Read-only file system |
| 仓库目录（workspace） | ✅ 可写 |

常规安装会落在 `/root/.local/lib` → `OSError: [Errno 30] Read-only file system`。

### 本项目的做法

装到仓库内可写目录 `.jqdata_env/`，用 `PYTHONPATH` 暴露：

```bash
# 安装 / 重装（幂等）
bash scripts/jqdata/install.sh
```

等价于：

```bash
pip install --no-user --target .jqdata_env --no-deps \
  jqdatasdk==1.9.8 thriftpy2 ply ijson pymysql msgpack \
  -i https://pypi.tuna.tsinghua.edu.cn/simple
```

两个关键参数：

- `--target .jqdata_env`：绕开只读的 site-packages；
- `--no-deps`：**必需**。若让 pip 自行解析依赖，它会顺手把 **pandas 升到 3.0.5、numpy 升到 2.5.3**
  装进 `.jqdata_env`；因为该目录在 `PYTHONPATH` 中，会**遮蔽掉 qlib 依赖的 pandas 2.3.3**，
  直接破坏现有研究环境。实测已复现并规避。
  依赖只补环境里没有的：`thriftpy2 / ply / ijson / pymysql / msgpack`。

`thriftpy2` 解析到 **0.7.1 的 cp312 预编译 wheel**，因此**不需要**文档里那种
「手动降级到 `thriftpy2==0.4.20`」的操作，也不需要 C++ 编译环境。

### 运行方式（统一用包装脚本）

```bash
bash scripts/jqdata/run.sh scripts/jqdata/check.py
bash scripts/jqdata/run.sh -c "import jqdatasdk; print(jqdatasdk.__version__)"
```

`run.sh` 会注入 `PYTHONPATH=.jqdata_env` 与 `TMPDIR=.jqdata_tmp`。

---

## 1. 凭据配置（**需要你本人操作**）

聚宽的登录凭据是**手机号 + 官网登录密码**，我无法代填。二选一：

**方式 A（推荐，交互式，密码不回显）**

```bash
bash scripts/jqdata/run.sh scripts/jqdata/set_credentials.py
```

写入 `.jqdata/credentials.json`（自动 `chmod 600`）。

**方式 B（环境变量，不落盘）**

```bash
export JQ_USERNAME=<手机号>
export JQ_PASSWORD=<密码>
```

优先级：环境变量 > `.jqdata/credentials.json`。

凭据文件已在 `.gitignore` 中（`.jqdata/credentials.json`），不会被提交。

---

## 2. 自检

```bash
bash scripts/jqdata/run.sh scripts/jqdata/check.py
```

退出码：

| code | 含义 |
|---|---|
| 0 | 全部通过（登录 + 账号信息 + 证券列表 + 取数） |
| 2 | 未找到凭据 |
| 3 | 登录失败（账号/密码/权限问题） |
| 4 | 取数失败 |

无凭据时当前输出（已实测）：

```
[check] 凭据缺失：未找到聚宽凭据。请任选其一：...
[exit 2]
```

### 2.1 登录失败：`用户不存在或密码错误`

配置凭据后实测（2026-09-15）登录被拒：

```
[check] 登录失败：Exception: 用户不存在或密码错误;
如果未开通调用权限，请打开以下链接提交申请：https://www.joinquant.com/default/index/sdk
[exit 3]
```

**这条报错同时覆盖两种成因**，SDK 层面无法进一步区分：

| # | 成因 | 判定方法 |
|---|---|---|
| ① | 手机号/密码不正确（含手机号并非聚宽账号、密码记错、用的是别站密码） | 用同一手机号+密码去 <https://www.joinquant.com> 登录；**登不上 → 就是密码问题** |
| ② | 账号正确但 **JQData SDK 调用权限未开通** | 能在官网登录却仍报此错 → 去 <https://www.joinquant.com/default/index/sdk> 确认申请状态 |

重要事实：**仅在聚宽注册账号并不等于开通 JQData 调用权限**，后者需要单独提交申请并获批
（报错文本自身给出的链接即为此申请入口）。凭据形态已排除格式问题（11 位手机号、
密码 11 位、无空白、无首尾空格、全 ASCII）。

诊断脚本：

```bash
bash scripts/jqdata/run.sh scripts/jqdata/diagnose_login.py
```

它会打印凭据形态（不含密码原文，仅长度+sha256 前缀）与上述判读建议。

> 备注：曾尝试直接探测聚宽网页登录端点来自动区分账号/密码，但 `www.joinquant.com` 的
> `/user/login` 等接口是 SPA + CSRF，只返回 HTML 空壳（`{"data": [], "status": "0", "msg": ""}`），
> 无法作为判据，该逻辑已从诊断脚本中移除，避免给错误结论。

---

## 3. 试用账号的能力边界（**已实测**，2026-09-15）

### 3.1 账号实际状态（`get_account_info()` 真实返回）

```text
mob                : 186****76
license            : 1                     # 试用
query_count_limit  : 1,000,000 / 日         # 100 万条
expire_time        : 2026-12-16 00:00:00    # 约 3 个月
date_range_start   : 2025-06-07
date_range_end     : 2026-06-14
```

区间是**动态滑窗**：`range_start` = 今天 −465 天、`range_end` = 今天 −93 天，
与官方「前 15 个月 ~ 前 3 个月」一致。**它不会前移，只能随日期整体漂移。**

### 3.2 接口可用性（在区间内实测通过）

| 接口 | 结果 |
|---|---|
| `get_price`（日线 OHLCV+money） | ✅ |
| `get_trade_days` | ✅ 35 个交易日（2026-01-01~03-02） |
| `get_all_securities` | ✅ 5,171 只（含已退市，如 `000004.XSHE 国华退` 止于 2026-07-13） |
| `get_index_stocks('000300.XSHG')` | ✅ 300 |
| `get_fundamentals(query(valuation...))` | ✅ |
| `get_fundamentals(query(income...), statDate='2025q4')` | ✅ **财务数据可用** |
| `alpha101.alpha_001()` | ✅ 因子库可用 |

### 3.3 因子可及性——**不是「只能拿 Alpha101」**（2026-09-15 实测）

一键复现：`bash scripts/jqdata/run.sh scripts/jqdata/probe_factors.py`

关键区别：`jqdatasdk.alpha101` / `alpha191` 是**客户端模块**，`get_factor_values` /
`get_fundamentals` 是**服务端 API**——「可用」的含义不同，容易误判。

| 因子来源 | 取用方式 | 本地/服务端 | 实测结果 |
|---|---|---|---|
| **Alpha101**（82 个） | `alpha101.alpha_xxx(date)` | **客户端本地计算** | ✅ 82/101（19 个 SDK 标「该因子未实现」）；**清空鉴权状态后仍可计算** → 是本地实现，**不是账号权益**，不耗额度 |
| **Alpha191** | `alpha191.alpha_xxx(date)` | 服务端 | ❌ 0/191（4 个未实现）；**换任何日期**都返回账号区间受限 → 受试用权益限制 |
| **风险模型风格因子（10 个）** | `get_factor_values(securities, factors)` | 服务端 | ✅ 全部 10 个：`size / beta / momentum / residual_volatility / non_linear_size / book_to_price_ratio / liquidity / earnings_yield / growth / leverage`，另含 `market_cap / circulating_market_cap` |
| **申万一级行业因子（31 个）** | `get_factor_cov()` 默认返回 | 服务端 | ✅ 风格 10 + 行业 31 |
| **财务/估值因子** | `get_fundamentals(query(valuation.*, indicator.*))` | 服务端 | ✅ `pe_ratio / pb_ratio / ps_ratio / market_cap / circulating_market_cap / turnover_ratio / dividend_ratio / roe / roa / eps / net_profit_margin / inc_revenue_year_on_year / inc_net_profit_year_on_year` |
| **技术指标（101 个）** | `technical_analysis.MACD(...)` 等 | 服务端 | ❌ **属于付费模块**，未授权（`get_technical_analysis 属于付费模块`） |
| 股东/十大股东、融资融券、龙虎榜等 | `get_...` 各类接口 | 服务端 | 未逐一实测，多数在试用权益内 |

**三个要点**：

1. **`get_factor_values` 不支持 alpha 因子**（报错原文：`不支持获取 alpha 因子, 请通过
   alpha191/alpha101 模块获取`）——但这**不代表**它只能取 alpha；它取的是**风险模型
   风格因子**（Barra 式），共 10 个 + 行业。
2. **Alpha101 的「可用」是模块本地实现，不是账号权限**。它靠 `get_price` 拉价量后本地算。
   因此**换账号也照样能用**，但受 `get_price` 的账号区间限制。
3. **Alpha191 与「技术指标库」是两个不同的付费/权益边界**：前者被账号区间卡住，后者直接
   标价付费。

### 3.4 对本项目的实际定位（重要）

**❌ 不能替代现有每日增量链路。** `date_range_end = 2026-06-14`，即**拿不到最近 3 个月
（2026-06-15 起）**；而 A 线 `output/live_ledger/` 与 B 线前瞻记录都依赖最新数据
（现有 qlib bin 已到 2026-09-10）。聚宽试用的数据比现有链路**旧 3 个月**。

**✅ 可用方向（2025-06 ~ 2026-06 与现有数据重叠，可互为校验）**：

1. **横截面交叉校验**：把 JQData 的 `get_price`（不复权/后复权可指定）与本地
   `$close/$factor` 或 tushare `daily_basic.close` 逐行比对，独立验证现有行情与复权口径
   —— 这正是 B 线 `validate_prices_vs_daily_basic_v1.py` 做过的事，可再加一个独立来源；
2. **PIT 财务交叉校验**：验证 `a_share_financial_pit_v1` 的 `available_date` 与聚宽
   `statDate`/公告日是否一致（本项目 PIT 纪律的核心风险点）；
3. **Alpha101 独立复算**（额度允许时）：用抓取的官方公式复核本项目自实现的 Alpha101 双臂结论
   （A 线 `a_share_alpha101_dual_arm_closure_v1.md`）；
4. **退市股历史**：`get_all_securities` 保留退市标的，可补强"幸存者偏差"检验
   （微盘线已证明 106 只已退市股终值 −76%）；
5. **风险模型风格因子**（10 个，§3.3）：独立复核 B 线风格中性化结论。

### 3.5 付费模块的绕过路径：文档公式抓取 + 本地重实现
**结论：Alpha191 可以自研；技术指标（101 个）不可以（缺公式）。**

#### 抓取方式（不需要登录、不耗额度）

帮助页 `https://www.joinquant.com/help/api/help` 是 SPA，直接 GET 只得 7KB 空壳；
但正文由两个 JSON 接口提供：

```text
GET https://www.joinquant.com/help/api/getHelpDocTree?name=<doc>   # 目录树
GET https://www.joinquant.com/help/api/getContent?name=<doc>       # 正文 HTML（JSON.data）
```

一键落盘（写到 `.jqdata/docs/`，已 gitignore）：

```bash
bash scripts/jqdata/run.sh scripts/jqdata/fetch_docs.py
```

实测抓取结果：

| 文档 | 正文 | 小节 | **公式** |
|---|---|---|---|
| `alpha191` | 92 KB | 197 | **191 条（191/191 解析成功）** |
| `alpha101` | 49 KB | 108 | **102 条** |
| `technicalanalysis` | 179 KB | 113 | **0 条** |
| `JQDatadoc` | 1.18 MB | 400 | 0 条 |

#### Alpha191 = 可自研 ✅

公式是**完整的数学表达式**，例如：

```text
alpha_002 = (-1 * CORR(RANK(DELTA(LOG(VOLUME),1)),RANK(((CLOSE-OPEN)/OPEN)),6)
```

算子词汇已统计（共 30 个）：`MEAN 62 / RANK 60 / SUM 49 / CORR 45 / MAX 32 / SMA 32 /
DELTA 26 / ABS 24 / DECAYLINEAR 17 / MIN 16 / TSRANK 16 / STD 15 / TSMIN 12 / TSMAX 10 /
COUNT 6 / LOG 5 / REGBETA 4 / SIGN 3 / SEQUENCE 3 / WMA 2 / COVIANCE 2 / LOWDAY 2 /
HIGHDAY 2 / SUMIF 2 / REGRESI 1 / FILTER 1 / PROD 1` …

解析产物：`.jqdata/docs/alpha191_formulas.json`（191 条公式）。

**已知质量瑕疵（必须注意）**：部分公式在官方文档里**本身就不完整/有调整**，例如
`alpha_190` 标注「公式有部分缺失 有调整」，`alpha_055/alpha_137` 的括号与
`DELAY(CL OSE,1)`（多了空格）这类排版破损需人工修正。**不能当唯一真值源**。

#### 技术指标（101 个）= 不可靠自研 ❌

文档给的是**签名 + 参数 + 返回值 + "算法"一句话**，**没有公式**。以 ACCER 为例：

```text
算法：先求出斜率，再对其价格进行归一
备注：计算方式与通达信相同，东方财富和同花顺没有该指标
```

全篇 104 次提到「通达信」、100 次「东方财富」、103 次「同花顺」，即**靠"与某平台一致"
兜底**。因此：

- 可以按公开的通达信/同花顺公式自行实现，但**无法保证与聚宽口径一致**
  （文档自己声明「部分算法不一致…计算得到的结果可能和其他平台存在差异」）；
- 对本项目而言，这类指标多半用现成库（`pandas-ta`/`TA-Lib`）即可，**不值得为"与聚宽一致"
  去逆向**。

#### 与项目的关系

已有 `alpha101` 本地实现（82/101）可作**独立参照**来验证文档公式的重实现是否正确；
而文档里给的部分示例数值（如 `alpha_002('000001.XSHE','2019-04-24',fq=None) = -0.403162`）
是**现成的验证锚点**——但注意**该日期在试用账号区间（2025-06-07~2026-06-14）之外**，
无法用于试用账号的端到端校验。

#### 技术指标"一句话算法"能否自研？—— 实测结论：**能实现，但不值得**

文档给的是「签名 + 参数 + 返回值类型 + 一句"算法" + 示例数值」。**没有公式。**
我做了一次反向验证（**零额度**：用本地 qlib 数据算 2017-01-04，与文档示例值比）：

```text
目标：ACCER('000001.XSHE', 2017-01-04, N=8) = 0.0013989466754443464   ← 文档给出

候选公式                        计算值              比值/目标
a / close                  0.001091719256          0.78
a / mean(close)            0.001098314184          0.79
a / mean(OHLC)             0.001098728855          0.79
a / mean(open)             0.000248523778          0.18
28a / mean(close)          0.030752792954         21.98
a(open)+2(...) / mean      0.001948206802          1.39
```

**没有一种常见变体命中目标**（最接近的差 21%）。说明从 1~2 个示例数值反推公式
**不可靠**——需要正确猜测：价格口径（前复权/加权均价）、窗口对齐、是否用 OHLC 加权。
此外文档自己声明：「因复权数据不同平台不一致、**部分算法不一致**…结果可能和其他平台存在差异」。

**因此的可执行建议**：

| 做法 | 评价 |
|---|---|
| 用成熟开源库（`pandas-ta`/`TA-Lib`）实现标准指标（MACD/RSI/KDJ/BOLL/ATR/WR/CCI/BIAS…） | ✅ **首选**。这些公式跨平台一致，属行业公认 |
| 逐个逆向聚宽口径的 101 个指标 | ❌ 不值得。投入大、结果仍不可保真 |
| 只自研**策略真正需要**的 1~2 个，用文档示例值验证到量级正确 | ⚠ 可接受 |
| 用 `technical_analysis` 官方值当基准 | ❌ 做不到（付费 + 试用区间限制） |

**关键提醒（本项目特有）**：技术指标类因子在本项目**已被系统性证伪多次**：

- A 线微盘九族双臂已扫过 Alpha101 / Momentum(含 **MACD**) / Reversal(含 RSI) / Risk / Liquidity 等
  共 **202 原始 → 178 实现 → 24 候选**；
- `momentum20_dual_arm_closure_v1.md`：20 个动量因子里 **MACD** 仅得 `Q5−Q1 −0.91%/月`
  且方向为**负（反转）**；
- B 线涨停/隔夜日内/行业轮动等日频线全部 `not_supported`；
- `a_share_daily_alpha_exhaustion_manifest_v1.md`：13 条日频线全闭环、无存活者。

→ **再花时间复刻聚宽 101 个技术指标，很可能只是第四次验证一个已被证伪的方向。**
若确有某指标从未测过，先走三问门槛立项，而不是先建整个库。

### 3.6 「充会员/买正式账号」能解决什么？（**别混淆两个产品**）

聚宽有**两个独立产品**，付费不能互相替代：

| 产品 | 用途 | 与本目录的关系 |
|---|---|---|
| **聚宽网站 VIP** | 在**聚宽网站上**跑策略/回测/研究的会员 | **与 JQData 本地取数无关**，买了也改不了本地 SDK 的权限 |
| **JQData 正式账号** | **本地 SDK 取数**（本目录用的就是这个） | 必须单独购买 JQData 授权 |

官方口径（`JQDatadoc` 文档原文）：

```text
试用账号历史范围：前15个月~前3个月；正式账号历史范围：不限制。
get_query_count：试用账号默认是每日50万条；正式账号是每日2亿条。
```

#### 对照你的三个问题

| 问题 | 买正式账号能解决？ | 依据 |
|---|---|---|
| ① 当日额度只剩 12%（100 万条不够拉全市场 250 日） | **✅ 能**（100 万 → 2 亿条/日） | 官方文档 |
| ② 历史范围只有「前 15 个月 ~ 前 3 个月」 | **⚠ 部分**：历史**起点**放开（可回溯 2005），但**拿不到最近 3 个月**——这是 JQData 的**产品定位**（保护网站付费用户），**不是权限问题** | 「试用账号历史范围：前15个月~前3个月；正式账号历史范围：不限制」中的"前 3 个月"仍需向客服确认是否同样放开 |
| ③ 技术指标 101 个 / Alpha191 属付费模块 | **❌ 不确定能**——这类通常是**单独售卖的模块**（文档明确「属付费模块，如您有购买需求，请联系 JQData 运营人员」），不随基础账号自动开通 | `technicalanalysis` 文档备注 |
| ④ 你项目的"最新日频数据"（`live_ledger`、前瞻记录） | **❌ 完全不能** | 现有 tushare + qlib bin 已到 **2026-09-10**，JQData 任何档位都到不了这里 |

#### 判断建议

**先别急着充**，理由：

1. **你的主线数据需求（每日最新行情）JQData 任何档位都满足不了**——这已经由现有的
   tushare `market_daily_v1` / `daily_basic` + `cn_data_2026`（到 2026-09-10）覆盖，
   而且**免费**；
2. **买账号主要解决"额度"和"历史深度"**，但你的研究是 2016 起、月频为主，
   历史深度不是瓶颈；
3. 真正想要的**技术指标 101 个 / Alpha191** 大概率**要额外单独买模块**——
   而它们的公式我们已经免费拿到（§3.5），**Alpha191 可自研**，
   技术指标用 `pandas-ta`/`TA-Lib` 即可；
4. **性价比最低的场景**：只为跑「全市场 Alpha191 面板」而买——那需要 ~125 万条/日，
   正式账号的 2 亿条确实够，但先问自己：这 191 个因子能给你项目带来什么增量？
   本项目已经证伪过 Alpha101 域内 top-N（`clean_microcap_combo_closure_v1.md` 6/6 全灭）。

**如果确实要买**，值得先向客服问清三件事：

1. 正式账号的 `date_range_end` 是否还是"前 3 个月"？（这决定能否用于近期研究）
2. 技术分析指标 / Alpha191 是否包含在账号内，还是单独模块、单独报价？
3. 最小购买周期与价格（年付/月付、是否含分钟线/tick）。

> 注：以上权益差异来自官方文档原文；**具体价格未查到可靠公开信息**
> （官网售价页需登录/联系客服），请以客服报价为准。

### 3.7 ⚠ 额度纪律（**踩过的坑，务必先读**）

一键查看/估算：

```bash
bash scripts/jqdata/run.sh scripts/jqdata/quota.py
bash scripts/jqdata/run.sh scripts/jqdata/quota.py --cost 5000 250   # 行/次 × 次数
```

实测规则：

| 规则 | 实测值 |
|---|---|
| 计费单位 | **每返回 1 行 = 1 条，与字段数无关**（取 4 字段的 245 行 = 245 条） |
| `get_query_count()` / `get_account_info()` | **不耗额度**（连续调用差值为 0），可放心查 |
| 当日额度 | `total = 1,000,000`；**按日重置** |
| 单次返回上限 | `query`/`get_fundamentals` 最多 **5,000 行**，需分页 |

**教训**：探测因子权限时跑了约 300 次调用而**没有记账**，把当日 100 万条烧掉约 88 万条
（`get_all_securities` 每次返回 5,000+ 行，是主要消耗源）。

常见任务成本：

```text
❌ 全市场 5,000 只 × 250 日    1,250,000 条   > 日额度，一天拉不完
❌ 全市场 5,000 只 ×  60 日      300,000 条
✅ 沪深300 × 250 日              75,000 条
✅ 单只 × 250 日                    250 条
```

**任何批量取数前必须先估算**；`quota.py` 提供 `with quota(label, limit=...) as q: q.charge(n)`
上下文管理器，超预算立即抛 `QuotaExceeded` 中止。

---

## 4. 文件说明

| 文件 | 作用 |
|---|---|
| `install.sh` | 安装/重装 SDK 到 `.jqdata_env`（幂等） |
| `run.sh` | 运行包装：注入 `PYTHONPATH`/`TMPDIR` |
| `_env.py` | 环境引导 + 凭据加载 + `auth()`；也是 `import` 时的依赖 |
| `check.py` | 接入自检（登录 + 账号 + 取数） |
| `set_credentials.py` | 交互式写入凭据（chmod 600） |
| `diagnose_login.py` | 登录失败诊断（凭据形态 + 双成因判读） |
| `probe_factors.py` | 因子可及性实测（Alpha101/191、风险模型、技术指标、财务） |
| `fetch_docs.py` | 抓取官方公式文档到 `.jqdata/docs/`（离线参考） |
| `quota.py` | 额度查看/估算 + `quota()` 记账上下文管理器 |

在自有脚本中使用：

```python
import sys; sys.path.insert(0, "scripts/jqdata")
from jqdata_env import auth          # 或 from _env import auth（同目录时）
auth()                                # 自动读凭据并登录
from jqdatasdk import get_price
```

---

## 4.5 因子复现与自动比对体系（`facsim/`）

一站式回答「文档里的因子公式，本地能不能算对、能算到多少精度」。

```bash
bash scripts/jqdata/run.sh scripts/jqdata/run_factor_compare.py --family emotion   # 单族
bash scripts/jqdata/run.sh scripts/jqdata/run_factor_summary.py                     # 总报告
bash scripts/jqdata/run.sh scripts/jqdata/run_factor_compare.py --list              # 各族状态
```

| 模块 | 职责 |
|---|---|
| `facsim/conventions.py` | **口径约定唯一来源**（文档未写明、经实测标定的全部结果） |
| `facsim/data.py` | 面板 / 官方因子值 / 财务表 / **全市场截面** 加载 + 强缓存 + 额度记账 |
| `facsim/ops.py` | 算子库（复用 `factorlib.ops`） |
| `facsim/families/*` | 10 个族的本地实现（各族 `NOTES` 归档未达标原因） |
| `facsim/compare.py` | 精度判定：`rel = max_abs_err / mean(｜官方值｜)`，EXACT/GOOD/APPROX/FAIL |

产物：`output/jqdata_factor_repro/SUMMARY.md`（总报告）+ `SUMMARY.csv`（逐因子）
+ 每族 `{family}_{时间戳}.csv`。全程走 `.jqdata_cache/facsim/`，**重跑不联网、不耗额度**。

### 实测总览（2026-09-17，比对区间 2026-05-06~2026-06-16，6 只标的）

> **为什么用这个区间**：TTM（过去四季之和）要求「截至比对日的最新 4 季」全部可及，
> 即 **2026-04-30 之后**（2026q1 披露后）。该区间同时让长窗口因子获得更充分的预热。

| 族 | 因子数 | 已实现 | EXACT | GOOD | APPROX | FAIL | 未实现 |
|---|---|---|---|---|---|---|---|
| technical | 16 | 16 | 1 | 9 | 6 | 0 | 0 |
| risk | 12 | 12 | 0 | 12 | 0 | 0 | 0 |
| momentum | 34 | 34 | 2 | 2 | 21 | 7 | 2 |
| emotion | 36 | 36 | 15 | 20 | 1 | 0 | 0 |
| pershare | 15 | 15 | 0 | 13 | 0 | 2 | 0 |
| basics | 37 | 28 | 23 | 2 | 1 | 2 | 9 |
| growth | 9 | 2 | 0 | 2 | 0 | 0 | 7 |
| quality | 71 | 49 | 2 | 40 | 0 | 5 | 24 |
| style | 30 | 12 | 0 | 3 | 0 | 8 | 19 |
| style_pro | 16 | 0 | — | — | — | — | 16 |
| **合计** | **276** | **204** | **43** | **103** | 29 | 24 | 77 |

**146 个达可复现**、**204 个已实现**。早前在 2025-12~2026-03 区间只能做到 90 个，
差距主要来自财务族（TTM 在该区间不可算）。剩余 79 个未实现的全部是结构性阻断：
需 8 个季度/多年基期（growth 9、quality 24）、需分析师预期（3）、官方无公式
（style_pro 16）、需 252/504 日窗口（style 19）、balance 表科目缺失（3）。

⚠ **判定对区间敏感**：例如 `MAC5`/`MAC10`/`boll_down` 的相对误差 ~1.1e-4，
刚好越过 GOOD 阈值 1e-4 而落 APPROX（corr 仍为 1.0000）；`MFI14` 则相反——
晚期区间避开了单只标的异常期，由 FAIL 转为 GOOD。读报告需结合区间解读。

### ⚠ 对本文档早前结论的更正

0. **TTM 可以精确复现**（重要更正）。正确配方是取「截至比对日已披露的最新 4 个单季」
   求和，而非固定某一年。实测 6 只标的 × 6 个 TTM 科目在 2026-05-15/06-15
   **相对误差全部为 0.0000%**。早前 F 段「TTM 结构性不可复现」是错的，错因是固定用了
   `stat_date="2025q4"`，而 2026-04-30 之后最新季已是 2026q1。
1. **「聚宽因子库取不到」是错的**。`get_all_factors()` 返回 **276 个**因子，10 大类
   逐类抽样**全部可取**；CNE6 pro 的 **16 个**也能取。早前结论源于用错了因子名
   （试了 `MACD`/`RSI`，真实 code 是 `MAC5`/`MACDC`/`MFI14`）。
2. **「只有 10 个风格因子」不完整**。CNE5 有 **30 个** style 描述/合成因子均可用；
   `get_factor_cov` 另给 10 风格 + 31 申万一级行业。
3. **`get_factor_kanban_values` 可用**（实测 5520×21），并非文档表格标注的 ✗。
4. **财务族存在硬边界**：账号财务数据仅覆盖 **2025Q1~Q4**（2024 及以前**静默返回 0 行**），
   且四季求和的 TTM 与官方有 0.35%~6.26% 残差（现金流类可达 137%）→ 依赖 TTM 的
   因子结构性不可复现。单期科目因子则可精确复现（已实现 25 个，20 个达 EXACT/GOOD）。
5. **北交所（bjse）属付费模块**，全市场截面只能取 `types=['stock']`（5190 只）。

完整的口径标定结果（ddof、复权、参数来源、单位陷阱、中文字段映射等 20 余条）
见 `facsim/conventions.py`；总报告见 `output/jqdata_factor_repro/SUMMARY.md`。

---

## 5. 变更记录

| 日期 | 变更 |
|---|---|
| 2026-09-15 | 创建：SDK 1.9.8 + thriftpy2 0.7.1 装入 `.jqdata_env`（规避只读 FS 与 pandas 遮蔽）；`run.sh`/`check.py`/`set_credentials.py` 就绪并自检通过；等待用户提供凭据 |
| 2026-09-15 | 首次登录失败（密码错，exit 3）→ 新增 `diagnose_login.py` 并记录「用户不存在或密码错误」的双成因表 |
| 2026-09-15 | 用户更正密码后 **登录成功**；修正 `auth()` 的错误判定——`jqdatasdk.auth()` 只设置凭据、返回 None、不发请求，改为「设置凭据 + `get_account_info()` 触发鉴权 + `is_auth()` 复核」；`check.py` 改为从账号区间推导抽样日（不再硬编码日期） |
| 2026-09-15 | 实测账号边界与接口：窗口 2025-06-07~2026-06-14（今天 −465 ~ −93 天）、100 万条/日、有效期至 2026-12-16；`get_price`/`get_trade_days`/`get_all_securities`/`get_index_stocks`/`get_fundamentals(valuation,income)` 全部通过 |
| 2026-09-15 | **修正一条过度声称**：先前用 `alpha101.alpha_001(day)` 的通过来判断「因子库可用」是错的——该模块是**本地计算、不鉴权、不代表账号权益**。新增 `probe_factors.py` 实测三类来源：Alpha101 本地 82/101（清空鉴权后仍可算）、Alpha191 0/191（账号区间受限）、风险模型 10 风格因子 + 31 申万行业因子（`get_factor_values` / `get_factor_cov` 可用）、技术指标**付费未授权**、财务/估值走 `get_fundamentals` 可用 |
| 2026-09-15 | **打通付费模块的文档获取**：发现 SPA 背后的 `/help/api/getContent`、`/help/api/getHelpDocTree`（公开、免登录、不耗额度），新增 `fetch_docs.py`。实测 Alpha191 **191/191 条公式全部解析成功**（`.jqdata/docs/alpha191_formulas.json`）、Alpha101 102 条；**技术指标 101 个无公式**（仅"算法"文字 + "与通达信相同"兜底）→ 结论：Alpha191 可自研，技术指标不可靠自研 |
| 2026-09-15 | **⚠ 发现额度严重消耗并新增守卫**：当日 100 万条被探测调用烧掉约 88 万条（剩余 12.2%）。实测计费 = 每返回 1 行 1 条（与字段数无关）、`get_query_count()`/`get_account_info()` 不耗额度、额度按日重置。新增 `quota.py`（查看/估算/记账上下文管理器） |
| 2026-09-15 | 新增 §3.6「充会员能解决什么」：区分**网站 VIP** 与 **JQData 正式账号**（两个独立产品）；买正式账号可解决额度（100万→2亿/日）与历史起点，但**拿不到最近 3 个月**，付费模块（技术指标/Alpha191）大概率需单独购买 |
| 2026-09-17 | **建成因子复现与自动比对体系 `facsim/`**（10 族、276 因子清单）。实测：实现 144 个、**90 个达可复现**（23 EXACT + 67 GOOD）。新增 `run_factor_compare.py`（单族）/ `run_factor_summary.py`（总报告）。更正三条早前结论：聚宽因子库 **276 个全部可取**（早前误判源于用错因子名）、CNE5 **30 个** style 因子可用、`get_factor_kanban_values` 可用。取证财务族硬边界（2024 财报静默返空、TTM 残差 0.35%~137%）与北交所付费模块。 |
