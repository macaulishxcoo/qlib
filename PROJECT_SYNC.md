# PROJECT_SYNC — A 股量化研究项目总览与进度同步

> **本文档定位**：项目唯一入口/总览。后续任何新会话开始工作前，**先读本文件**即可恢复
> 项目整体概貌，无需重新通读全部研究文档。本文件只记录"已完成什么、当前状态、
> 下一步该做什么"，详细证据仍以 `research/protocols|decisions|specifications` 下的
> 正式文档为准。
>
> 创建日期：2026-08-21（基于对全仓的重新盘点）
> 最后更新：2026-08-21
> 维护规则：每次完成一个重要闭环后，在 §11 变更记录追加一行；重要结论变化时同步更新正文。

---

## 1. 一句话总览

**在 Qlib（微软开源量化平台）上做 A 股个人量化研究，核心结论是：**

1. **纯价量短周期 alpha 已测尽并关闭**（Alpha158/LightGBM、15 因子主升浪、事件流、
   PEAD、换手率/偏度等 13 条线全部闭环，无存活者）——见
   `research/decisions/a_share_daily_alpha_exhaustion_manifest_v1.md`；
2. **当前主战场是基本面月频策略线**：价值/质量四因子（v8 基线）→ 五因子
   （+成长 g2）→ 行业 cap3 → **最终实盘形态 = 五因子（ep+bm+div_yield+accruals+g2，
   ≥4/5 门槛）+ top-30 + 单行业≤3 只（cap3）+ 无过滤层**；
3. **已在运行的实盘模拟盘**仍是旧形态（四因子 top-15 + vt+T5 双过滤），
   五因子 top30_cap3 的模拟盘切换**尚未做**（工程待办）。

---

## 2. 环境与运行方式

| 项 | 值 |
|---|---|
| 工作目录 | `/home/xiaocong/worksapces/qlib` |
| Python 环境 | conda env `qlib`（`/home/xiaocong/anaconda3/envs/qlib/bin/python`，pandas 2.3.3） |
| qlib | 仓库本地开发版（`import qlib` 指向本仓 `qlib/`，dev 安装） |
| Qlib 数据 | `~/.qlib/qlib_data/cn_data_2026`（843MB，2000-01-04 ~ 2026-07-23） |

```bash
conda activate qlib
cd /home/xiaocong/worksapces/qlib
# 例：运行五因子信号管道
python scripts/run_daily_signal_pipeline_v1.py --date 2026-06-30 --top-k 30 --live
```

---

## 3. 目录结构（重要路径）

| 路径 | 内容 |
|---|---|
| `qlib/` | Qlib 上游核心库（勿改，除非明确需要） |
| `data/external/tushare/` | **外部数据（4.4GB）**，见 §4 |
| `data/derived/` | 派生数据（股票分类 v1/v2、事件面板） |
| `scripts/` | **全部自定义研究/回测/管道脚本**（约 60 个） |
| `scripts/data_collector/` | 下载/审计/更新脚本 |
| `output/analysis_fundamental/` | 基本面线实验结果（每策略一个目录） |
| `output/analysis_static/` | 静态/日频线实验结果 |
| `output/live_ledger/` | 信号名单（`signal_*.csv`，含实盘月度名单） |
| `output/signal_ledger/` | 信号/持仓/组合三账本（replay 用） |
| `output/paper_trading/` | 模拟盘 nav_log |
| `research/charters/` | 章程（母池定义） |
| `research/protocols/` | 冻结的实验协议（每个实验先写协议再执行） |
| `research/decisions/` | **结论文档**（每个闭环一条 closure；唯一证据源） |
| `research/specifications/` | 数据最小规范 |
| `DEV_LOG_*.md` | 开发日志（RollingTraining=线1；DailyStrategyExploration=线3） |
| `PROJECT_SYNC.md` | 本文件 |
| `metrics_judgment_standard.md` | IC/IR/MDD/换手率等指标评审标准 |
| `alpha158_factor_guide.md` | Alpha158 因子指南（线1资产） |

---

## 4. 数据资产清单（已下载，勿重复下载）

### 4.1 Qlib bin 数据 `cn_data_2026`
- 2000-01-04 ~ 2026-07-23，calendars/features/instruments；
- instruments：`all.txt`、`csi300/csi500/csi800/csi1000`（**无 csi100**，旧脚本用 csi100 会报错）。

### 4.2 Tushare 外部数据（`data/external/tushare/`）

| 数据集 | 范围/规模 | 消费状态 |
|---|---|---|
| `market_daily_v1` | 全 A 日线（bin + raw） | ✅ 用之 |
| `a_share_daily_basic_pit_v1` | 2016-01-04 ~ 2026-08-13，1095 万行（close/总市值/成交额等） | ✅ 用之（网格、容量、取整价格） |
| `a_share_financial_pit_v1` | 报表期 2009-12-31 ~ 2026-06-30；fina_indicator 24.6 万行；**PIT 键 = available_date（公告日，如 2010-04-20）** | ✅ 四因子+g2 全用 |
| `a_share_forecast_v1` | 2022 起，21,142 条业绩预告（ann_date/end_date/type/净利区间） | ⚠️ **未测**（成长因子高频领先版候选） |
| `a_share_events_daily_v1` | 2022-01-01 ~ 2026-08-07，325.7 万行（增减持/解禁/龙虎榜 top_list） | ✅ T5 剔除层用；其余已判定无方向信息 |
| `margin_pit_v1` | 2016-01-04 ~ 2026-08-07，607 万行（rzye/rqye/rzmre/rqyl/rqmcl...） | ⚠️ 仅 rzye（融资余额）测过：IC -0.043，作过滤层无增量；**rqye/rqyl/rqmcl（融券）未测** |
| `moneyflow_pit_v1` + `moneyflow_hsgt_pit_v1` | 2022 起 | ✅ 已测关闭（`moneyflow_not_supported`；修复 lookahead 后 ICIR 0.27 < 0.3） |
| `a_share_st_status_pit_v1` | 14,170 条 ST/退市区间 | ✅ 用之（ST 过滤） |
| `a_share_style_pit_v1` | 申万 L1/L2/L3 行业有效区间 + 月度自由流通市值 | ✅ 用之（中性化、cap3 行业约束） |
| `a_share_index_membership_pit_v1` | 指数成分历史 | ✅ 用之（CSI1000 线 + 指数调整效应已测关闭） |
| `holdernumber_pit_v1` | 股东户数 | ✅ 已测关闭（见 decisions） |
| `sw_industry_index_v1` | 申万行业指数日线 | ⚠️ 行业轮动候选（未测，见 §8） |
| `a_share_stock_classification_v2`（derived） | 月度股票分类 | 中性化辅助 |

---

## 5. 研究线全景（结论要点）

### 线 1：CSI1000 价量 ML 线（**2026-07 前，已关闭**）
- 问题：静态训练（2008-2020）效果尚可 → 滚动训练 2025-2026 完全失效。
- 排查：数据无重大 bug；**核心原因 = 2021 后概念漂移/alpha 衰减**（标签均值趋 0、方差收敛）。
- 无效尝试：缩短窗口+时间衰减权重、DDG-DA、ADARNN/HIST/DoubleEnsemble、
  Alpha360、特征筛选 top30/60、加市场环境特征——全部无法转正 Daily IC。
- 158 特征单变量 IC 几乎全趋 0。**结论：纯价量短周期路线终结，不再投入。**
- 证据：`DEV_LOG_RollingTrainingOptimization.md`；`research/rolling_comparison_results.csv` 等。

### 线 2：A 股基本面月频策略线（**当前主线**）
- 母池：沪深普通 A 股（`research/charters/a_share_research_universe_charter_v1.md`），
  排除北交所；报告须含规模/行业/流动性/市场状态分层。
- **四因子（ep+bm+div_yield+accruals）价值/质量线**：
  - v1→v8：v8 = 四因子 top15（≥3/4 门槛）+ ST/容量过滤 + 行业/规模中性化 + 月度调仓 + T+1 开盘/涨跌停 9.5% 成本；封存期（23-25H1）IR 0.92；
  - 过滤层：v11 超买（+20%/20d）✅、v12 T5 跌幅上榜 ✅、v13 价值陷阱 ✅、
    **v14 双过滤（vt+t5）= 过滤层最终形态**（new_coverage +25.06pp、holdout +1.93pp）；
    v15 三层（+revfilter）❌（holdout 侵蚀）；
  - 判定门槛：**holdout 侵蚀 ≥ -0.5pp 与 new_coverage 改善 ≥ +5pp 双门槛**；
    过滤层若 holdout 被侵蚀 → 拒绝（v15/v16 同机制）。
- **五因子线（+g2 = dt_netprofit_yoy 扣非净利同比，PIT，≥4/5 门槛）**：
  - v2 判定 `regime_robust_improved`：全期 stress IR 0.685 > v8 0.611，新覆盖段 -31.1% >
    v8 -35.0%；机理 = **g2 削峰填谷**（2019/2020/2024/2025 全面优于 v8，2023 顺风顶点略逊）；
  - top-K 扫描：**top-30 为实盘推荐**（全期 IR 0.90）；top-50 回测最优（IR 0.93）但
    50 只 × 50 万资金有整手约束/执行成本问题；
  - **行业 cap3（greedy，单行业≤3 只）在 top15/top30 均为净正贡献**（不改变信号，
    只替换同行业信息冗余；无 holdout 侵蚀）；
  - **最终实盘形态 = 五因子 + top-30 + cap3 + 无过滤层**，全期 IR 0.94（四臂最高）、
    holdout IR 1.09、full MDD -25.9%、新覆盖段 -16.8%、单行业 10%/前三 29.9%；
  - 关键决定：**过滤层在五因子基线上收口（不再追加）**——g2 已吸收逆风保护，
    T5/revf 叠上反而 holdout 侵蚀（v16：holdout -2.82pp ❌）。

### 线 3：日频方向探索（**2026-08-14~17，基本测尽**）
- 总览：`research/decisions/a_share_daily_alpha_exhaustion_manifest_v1.md`（**13 条线全闭环清单**，必读）。
- 存活资产：仅 "基本面域+日频调仓" main 策略（net +0.164/IR 1.68、换手 4.8%）；
  趋势状态 TS_UP60（仅作系统性暴露层）；两融拥挤 rzye_zscore（IC -0.043，过滤层无增量）。
- 事件分类型（T1-T5 负面）：T5 跌幅上榜事件层 -1.87%/20d（t=-13.09）显著，
  但日频可交易形态 `t5_daily_not_adopted`（2/4 年同向、组合层不可交易）；
  T5 剔除层在**四因子**月频基线 adopted（holdout +0.73pp、new_coverage +20.33pp）。
- 正面事件 P1/P2/P3：`positive_event_subtype_not_adopted`（无"利好兑现"制度性负漂移）。
- 指数调整效应：`index_adjustment_effect_not_supported`（纳入组 H=40 -1.14% t=-4.42，方向与假设相反）。
- 市场宽度/恐慌择时：direction_c 关闭（breadth IC≈0）——**风控不靠择时**。
- **三大教训**（写死，勿重犯）：
  1. **IC 正 ≠ 可交易**：必须过"扣成本真实调仓回测"才算数；
  2. **事件层显著 ≠ 组合层剔除有效**（逆势强势股剔除反而更差）；
  3. **标签必须用 open-to-open 口径**（`open[t+1+h]/open[t+1]-1`）；
     旧式 `FWD=open[t+1]/close[t+h+1]-1` ≈ -r 是 bug（已修复；影响面见
     `event_label_bug_recheck_closure_v1.md`，排查命令 `grep -rn "shift(-(h + 1))\|shift(-(h+1))" scripts/`）。

---

## 6. 当前实盘/工程状态（2026-08-21）

### 6.1 模拟盘（运行中）
- **形态：四因子 v8 + vt+T5 双过滤臂（top-15，50 万名义）**；
- 名单源：`output/live_ledger/signal_*_vt+t5.csv`（2026-06-30 名单 → 7 月段；2026-07-31 名单 → 8 月段）；
- NAV：7 月段 +5.89%（超额 +17.70%，基准 -11.80%）；8 月段至 08-14 +1.84%；
- **8-31 月度名单将依赖"月度调仓 automation"——尚未建**（见 §8）。

### 6.2 信号管道（`scripts/run_daily_signal_pipeline_v1.py`）
- **存在 163 行未提交改动（2026-08-20）**，已实现：TOP_K=30、五因子 composite5（≥4/5）、
  **行业 greedy cap3**、**整手取整 `round_to_lots`**（`--capital` 默认 50 万，用 daily_basic 真实收盘价）、
  BUY/SELL/HOLD 名单带 lots/price/invested；
- `output/live_ledger/signal_2026-06-30.csv` 已于 08-20 19:57 重生成（top-15 含 lots：BUY3/SELL3/HOLD12）；
- 兼容保留：`--overbought-filter`（v11）/`--value-trap-filter`（v13）/`--t5-filter`（v12）开关仍在，
  **但五因子基线上不推荐叠加**（v16 closure）；
- **待办：该改动应提交 git**（当前 `git status`：1 modified + 12 untracked，均为五因子线文件）。

### 6.3 尚未入库的产出（2026-08-20 生成的对比）
- `output/holdings_3strategies_cap3_2026/`：三策略（A=四因子 top15 cap3、B=五因子 top15 cap3、
  C=五因子 top30 cap3）的 per_stock + **per_stock_lots**（A/B/C 各含 lots/price/invested/最新市值/收益率）；
- **注意：没有对应的生成脚本/决策文档入库**（现有 `scripts/generate_holdings_cap3_comparison_v1.py`
  只覆盖 A/B 两臂且无 lots）；
- 日期范围：2026-06-30 → 最新交易日（qlib 数据至 2026-07-23）。

### 6.4 自动化（ZCode automation）
| 任务 | 状态 |
|---|---|
| 每日数据更新（行情+daily_basic）17:35 | ✅ active |
| 每日模拟盘更新（双过滤臂）17:40 | ✅ active |
| **月度调仓名单生成（月末 17:45）** | ⏳ **未建**（上一会话限制只建了 1 个 scheduled task，需新会话） |

---

## 7. 评审标准与治理规则（红线）

1. **指标门槛**：IC ≥0.05/ICIR ≥0.5 才算有效（`metrics_judgment_standard.md`）；
   但**最终以扣费回测为准**（毛 IC 正但回测 dead 的教训）。
2. **双门槛判定**（过滤层）：holdout 侵蚀 ≤ -0.5pp → 拒绝；new_coverage 改善 ≥ +5pp → 通过。
3. **反 snooping**：每个实验先写协议冻结参数；不追加"刚好有效"的分层/调参；
   极端月（如 2026-06 集中度）观察后按规则加约束，不在同轮内加。
4. **PIT 纪律**：财务/事件数据一律用 available_date（公告日）<= 信号日；
   fina_indicator 的 PIT 键 = available_date；禁止把今日财报倒填到过去。
5. **母池纪律**：新因子先在沪深普通 A 股母池验证；CSI1000 只是已研究样本不是默认池；
   结论须按规模/行业/流动性分层报告。
6. **单一变量**：与 v8 的唯一差异需在协议中声明；复合门槛比例保持等比例收紧（3/4→4/5）。

---

## 8. 下一步候选（未测 / 待办）

**工程（优先级高，非研究）**：
1. 提交 git 现有未提交改动（管道 5 因子+cap3+lots、五因子线 12 个文件）；
2. 月度调仓 automation（新会话建）；
3. 五因子 top30_cap3 模拟盘初始化（新持仓、新净值基线；v8+v11 模拟盘继续跑作对照）；
4. （可选）三策略 A/B/C 对比脚本补入库 + 对应的决策文档。

**研究（未测方向，按 DEV_LOG_DailyStrategyExploration.md §5 + 数据盘点）**：
1. **业绩预告增速**（`a_share_forecast_v1`，2022 起）：成长因子高频领先版本，独立事件族实验；
2. ~~**融券余量信号**（rqye/rqyl/rqmcl）~~ → **已测并关闭**（2026-09-13）：
   方向正确（IC 全负）、与价量及 rzye 正交（最大 |corr| 0.22）、3/4 通过 T-1 滞后对齐，
   但效应量不足（主口径 h=5 \|IC\| 0.0237 vs 门槛 0.05；h=20 仅 0.0406）。
   见 `research/decisions/a_share_short_interest_signal_closure_v1.md`；
3. **涨幅类上榜（涨停/连板）**：top_list reason 文本已有（零下载），T+1 开盘行为；
   **← 优先级已提升**：隔夜/日内线（2026-09-13 关闭）的十分位诊断证明
   「极端近期涨幅」正是毒尾所在（D10 前瞻 5 日年化 −19.5%），本方向是从该毒尾内部
   区分"连板 vs 见顶"，是当前证据支持度最高的日频候选；
4. **行业轮动/行业内相对恶化**：财务 + 申万行业已有，状态型/轮动型两种形态；
5. **指数调整/行业轮动**：指数调整已关闭；~~sw_industry_index_v1 未测~~ →
   **已于 2026-09-13 测试并关闭**（`signal_absent`）：开发段行业动量 t=6.59，
   样本外降到 t=1.82，12 个 (k,h) 组合无一通过门槛。
   见 `research/decisions/a_share_sw_industry_rotation_closure_v1.md`。
   **行业内选股**（本条另一半）未测，但优先级低——属跨个股截面，
   已被隔夜/日内、涨停事件、毒尾否决三条线证明梯度极薄。

**新增方法论要求（2026-09-13，来自隔夜/日内线关闭）**：

6. **任何新因子在只看 IC 之前，必须先输出十分位单调性表**。隔夜/日内线的
   `id_vol_20` 达到 IC −0.078 / t = −20.6（项目史上最强日频截面信号），
   但十分位表显示 D1~D9 是 `+0.12~+0.14` 的平坦高原、全部 IC 由单个 D10 崩塌制造，
   故多头组合必亏。**IC 的统计强度不能替代截面梯度**。既有教训 1
   （换手率水平 IC +0.064 → top50 −0.49/年）的根因即在此。
   见 `research/decisions/a_share_overnight_intraday_daily_closure_v1.md` §2。
7. **换手量级是回测正确性的第一道哨兵**：该线首版因强制保留逻辑取反导致组合冻结，
   年化换手仅 0.6（正常 15~35）却输出 `SUPPORTED`。任何回测若换手显著低于
   调仓频率的倒数，应先怀疑实现缺陷而非庆祝低成本。

8. **【下一线，已定】毒尾否决 + 宽基等权**：两条独立日频线（隔夜/日内、涨停事件）
   共同证明——多头超额不在"买入强势股"，而在"避开极端强势股"；
   否决价值量级 ≈ **+3.2pp/年**。形态为：宽基等权（近似等权全池 +7.06%/年）
   + 剔除毒尾名单，低换手、日频执行。需另立协议，**必须预设样本外段**
   （前两条线均为全样本内，否决本身来自事后诊断，未做样本外验证）。
   基准须同时报"相对中证1000"与"相对等权全池"两组口径。
   → **已执行并完成（2026-09-13）**：判定 `partially_supported`，
   否决贡献开发 +1.96pp / 样本外 +2.20pp（逐抽样偏移稳健），但不足以支撑 10pp。
   见 `research/decisions/a_share_toxic_veto_broad_decision_v1.md`。
   → **v2 成本现实性修正后推翻 v1 数字**：策略样本外 **+7.45% → −0.76%**；
   否决 alpha 存活（≈ +1.3pp）但被可实施性成本（5~8pp/年）吞没。
   见 `research/decisions/a_share_toxic_veto_broad_decision_v2.md`。

9. **【强制】资金可行性约束必须进入每一个组合回测**（2026-09-13 量化）：
   50 万本金、100 股整手 → 等权 N 只要求 `100×价格 ≤ 500000/N`。
   N=150 → P≤33.3 元，而主板收盘价中位数 32.68 元 → **仅 42.7% 样本可持有**；
   "等权持有全池"（1,800~3,700 只）**不可实施**。
   **陷阱**：按成交额取前 N 只 = 极端大市值押注，样本外代价 **−10.6%/年**（对比系统抽样的 +5.25%）。
   后续任何回测必须**同时**满足：① 报持仓只数与价格分布；② 禁止用"流动性前 N"作为中性选样；
   ③ **佣金 = max(5 元, 成交额×费率)**；④ **100 股整手 + 显式现金**。
   ③④ 合计拖累约 **5~8pp/年**（最低佣金 0.15%/单边；整手使仓位利用率仅 68~72%），
   与小资金策略的全部优势同量级 —— **在此口径修正前，任何"接近达标"的结论都不成立**。
   （项目既有 qlib 回测自带 `min_cost 5` 与整手逻辑，故只影响本次 session 自建的轻量脚本。）

**明确不再做**（避免重复）：Alpha101/191 扩库、自动因子挖掘（AlphaGen/gplearn/PySR）、
更复杂深度学习、先指定 CSI1000/微盘池、完整多因子模型、市场宽度择时、
龙虎榜/北向资金（数据权限或已证伪）。

---

## 9. 常用命令速查

```bash
# 五因子 top-30 实盘名单（含 lots）
python scripts/run_daily_signal_pipeline_v1.py --date 2026-06-30 --top-k 30 --live --capital 500000
# 历史重演
python scripts/run_daily_signal_pipeline_v1.py --replay --from 2024-01-01 --to 2025-06-30 --top-k 30
# 模拟盘状态/更新（双过滤臂）
python scripts/paper_trading_tracker_v1.py --status --signal-pattern "signal_*_vt+t5.csv"
python scripts/paper_trading_tracker_v1.py --update --signal-pattern "signal_*_vt+t5.csv"
# 每日数据更新（automation 已有）
python scripts/data_collector/update_daily_market_data_v1.py
python scripts/data_collector/update_daily_basic_v1.py
```

---

## 10. 关键文件索引（按优先级）

| 优先级 | 文件 | 读它为了 |
|---|---|---|
| 1 | `research/decisions/a_share_daily_alpha_exhaustion_manifest_v1.md` | 日频测尽总表（13 条线） |
| 2 | `research/decisions/a_share_value_growth_five_factor_industry_cap_closure_v3.md` | **最终实盘形态依据**（top30_cap3） |
| 3 | `research/decisions/a_share_value_growth_five_factor_strategy_closure_v2.md` | 五因子 vs v8 全期对照 |
| 4 | `research/decisions/a_share_five_factor_top30_pipeline_landing_v1.md` | 管道升级记录 |
| 5 | `DEV_LOG_DailyStrategyExploration.md` | 日频探索线日志（候选 A-D、复核清单） |
| 6 | `DEV_LOG_RollingTrainingOptimization.md` | 线 1 排查全过程 |
| 7 | `research/charters/a_share_research_universe_charter_v1.md` | 母池/分层/验证治理 |
| 8 | `research/decisions/scheduling_deployment_record_v1.md` + `paper_trading_double_filter_switch_v1.md` | 自动化/模拟盘工程状态 |
| 9 | `metrics_judgment_standard.md` | 指标评审标准 |

---

## 11. 变更记录

| 日期 | 变更 |
|---|---|
| 2026-08-21 | 创建：全仓盘点后生成项目总览（结构/数据/三研究线/实盘状态/待办/红线），供新会话直接入口 |
| 2026-09-13 | 关闭 §8 研究候选第 2 条（融券信号）：四信号方向正确、正交、通过滞后对齐，但效应量不足 → `not_supported_closed`，见 `research/decisions/a_share_short_interest_signal_closure_v1.md` |
| 2026-09-13 | 迁移到新机器后的环境与数据重建记录：见 `research/docs/MIGRATION_STATUS_2026-09.md`（WSL2 + CPython 3.12 + pyqlib 0.9.7；`cn_data_2026` 重建为 2015-2026、5,802 只；`main` 与五因子 top30_cap3 已复现，cap3 集中度逐位一致） |
| 2026-09-13 | 开启并按协议关闭**隔夜/日内收益分解日频因子线**（用户要求转向真正日频、不再沿月频主线）：端点 A RankIC 强通过（`id_vol_20` IC −0.078 / t −20.6），端点 B 扣成本多头组合 28 个组合 stress 下无一为正 → `not_supported`。十分位诊断揭示 IC 由单个极端十分位制造、截面 90% 平坦，回溯解释教训 1。见 `research/decisions/a_share_overnight_intraday_daily_closure_v1.md`；§8 新增第 6/7 条方法论要求，第 3 条（涨停/连板）优先级提升 |
| 2026-09-13 | 修复五因子线 balancesheet 读取路径缺陷（`load_financials_extended_v1.py` 增加 `BAL_FULL` 基址）→ top30_cap3 全期 stress IR 0.825 → **0.630**，全期净 +0.0836；commit `737d985` |
| 2026-09-13 | 开启并按协议关闭**涨停板事件日频策略线**：39 个 h×分档单元**全部为负**（两半样本同号，t 达 −29），最接近中性的 `炸板 h=1` 也仅 −0.02%（t=−0.66）。4 条冻结先验中 **3 条被数据反向推翻**（一字板/缩量/封板越"强"负超额越大）→ `not_supported`。见 `research/decisions/a_share_limit_up_event_closure_v1.md` |
| 2026-09-13 | **基准口径标定**（重要，影响后续所有超额口径）：等权全池月度再平衡 **+7.06%/年**，中证1000 **+2.39%/年**，差 **+4.67pp** 为小市值溢价。日度再平衡 bonus 仅 +0.47pp/年 → 此前"基准不可实现"的质疑**被证伪**，两条日频线的负结论**按原样成立**。后续协议须同时报"相对中证1000"与"相对等权全池"两组口径。见 `research/decisions/benchmark_calibration_v1.md` |
| 2026-09-13 | 两条独立日频线（隔夜/日内、涨停事件）指向同一机制：**多头超额不在"买入强势股"，而在"避开极端强势股"**。毒尾否决价值量级 ≈ +3.2pp/年，定为下一线（否决过滤+宽基等权），见 §8 |
| 2026-09-13 | **毒尾否决 v2 成本现实性修正（推翻 v1）**：补上 **5 元最低佣金 + 100 股整手 + 显式现金 + 真实 NAV** 后，策略样本外由 **+7.45% → −0.76%**（−8.2pp），判定 `not_supported`。**否决效应本身存活**（alpha 在 20 个 N×成本×分段组合中 19 个为正，均值 ≈ +1.3pp），但**可实施性成本 5~8pp/年**（最低佣金 0.15%/单边 + 整手导致仓位利用率仅 68~72% + 换手 13.5 次/年）大于策略全部优势。见 `research/decisions/a_share_toxic_veto_broad_decision_v2.md` |
| 2026-09-13 | **可实施性成本侧研究 v3（转向成本侧的结论）**：把 N 由 150 降到 30、调仓由 10 天放到 20 天，成本从 5~8pp 压到约 1pp，策略由 v2 的 **−2.2pp 转为 +2~+5pp**（开发/样本外同号）。机制：N 越小 → 单笔越大 → 整手残差/佣金下限/价格约束同时松绑（仓位利用率 0.67 → 0.89）。**网格最优格子（N=60/STEP=20, +7.15pp）在开发段仅 +0.27pp，判定为选择偏差不予采信**；可信量级以开发段选出的 N=30/STEP=20 为准（+3.81/+4.34pp）。判定 `cost_improved_only`。见 `research/decisions/a_share_cost_frontier_decision_v3.md` |
| 2026-09-13 | 确认本地**无任何分钟级数据**（`scripts/data_collector/baostock_5min/` 采集器存在但从未运行；`~/.qlib/qlib_data/` 仅 `cn_data_2026` 日线）。两条已关闭线（涨停封板时间/开板次数、隔夜竞价结构）的证据缺口均只能由分钟级数据回答。**但已评估为不可行**：baostock 单只股票全历史 5 分钟请求会挂起，只能按季度拉取（2.9s/只/季），全量约 **92 小时**；且涨停线已证明"最强封板（一字板）负超额最大"，分钟级数据的预期收益被日线代理反向证伪，故**不投入** |
| 2026-09-13 | **申万一级行业轮动线（诊断阶段）关闭**：30 个行业指数覆盖完整（2015-01-05~2026-08-14，无分类切换断裂）。**开发段行业动量极强**（k=10,h=10 价差 +0.74%/期，**t=6.59**），**样本外消失**（+0.19%，t=1.82）；12 个 (k,h) 组合无一通过"两段同号且均≥1.0pp"门槛 → `signal_absent`。该线是"因子衰减"的可复现实例，且证明**衰减是因子特有、不能推广为"市场整体变难"**（毒尾否决在样本外反而略强）。见 `research/decisions/a_share_sw_industry_rotation_closure_v1.md` |
| 2026-09-13 | **否决定义稳健性检验（`definition_robust`，12/12 变体为正）**：为排除"我选的那组参数过拟合"，测了 12 个毒尾定义变体。**全部为正**（full 增量 +1.21 ~ +5.51pp，中位数 **+3.68pp**），且全部在 holdout/new_coverage 段亦为正。三个关键点：① **不是阈值刀尖**（q80/85/90/95 全有效）；② **不依赖隔夜/日内分解**——`comp_cc`（20日涨幅+波动+振幅，**纯 close-to-close**）仍有 +3.33~+3.71pp，说明是通用的"避开极端近期涨幅"机制；③ **诚实口径应取中位数 +3.68pp**（我选的 q90 处于上沿），按中位数全期净超额 ≈ **+12.6%，仍达标**。见 `research/decisions/a_share_five_factor_daily_execution_decision_v1.md` §8 |
| 2026-09-13 | **五因子 + 日频执行 + 毒尾否决（本 session 最强结果，判定 `supported`）**：A 臂精确复现既有基线（full net +0.0836 / IR 0.630）。叠加毒尾否决后 **full 净超额 +0.0836 → +0.1408（滞后1日保守口径 +0.1356）**，IR 0.630 → **1.2245**，MDD −35.1% → **−16.9%**；holdout 段 +6.46% → +17.82%；new_coverage −24.57% → −6.72%。**贡献几乎全部来自否决（+5.2pp），日频执行仅 +0.5pp 且 development 段为负**。**前瞻性检验通过**：毒尾分滞后 1 交易日后增量仍有 +4.68pp（仅损失 0.5pp）。机制：五因子在低估值端与"低价+高波动+近期大涨"的投机标的天然重叠，**价值因子本身会系统性选进毒尾股**。**局限（必须披露）**：否决定义来自本 session 样本内诊断，四个 stage 全部落在该样本期内，**不构成独立样本外确认**；全期数字 2/3 来自 2016-2019；最近一年仍为负。见 `research/decisions/a_share_five_factor_daily_execution_decision_v1.md` |
| 2026-09-13 | **50 万口径验证通过**：把 qlib 回测 `account` 由 1 亿改为 **500,000**（qlib 自动套用 100 股整手 + `min_cost=5`），策略表现**几乎无衰减**（full +8.88%→+8.88% 无否决；+14.08%→**+13.83%** 含否决；IR 1.2245→1.203）。→ **50 万 + top30（单笔 ≈16,667 元）可实施，不存在"资金太小做不了"的问题**。见 `research/decisions/a_share_five_factor_500k_decision_v1.md` |
| 2026-09-13 | **发现既有线一处潜伏缺陷（流动性过滤从未生效）**：`load_amount_avg` 内部的 `D.features` 对显式传入的 5,770 只 ts_code 列表返回空结果，静默返回**零列** DataFrame；导致 `build_snapshots` 中 `avg` 全为 NaN、`NaN < 门槛` 恒 False，**流动性过滤是 no-op**。证据：门槛降低 200 倍后每期候选数**逐位相同**（2,925 = 2,925），而实测两门槛的真实约束力为 34.7% vs 98.9%。影响：五因子线所有复用该函数的脚本，其实际池为约 **2,925 只**而非设计中的约 1,000 只（因小市值溢价为正，很可能有利）。**对本用户无影响**（2,925 只在 50 万/top30 下完全可交易）。**本次未修复**——修复属独立实验，另立协议。**更正**：上一轮"门槛比 50 万所需高估 400 倍、白白剔除中小票"的判断**不成立** |
| 2026-09-13 | **最终策略画像（滚动/成本/频率三查）**：① **成本拖累仅 1.92%/年、换手 9.5 次/年**（top30 集中形态，远低于 N=150 宽基的 5~8pp），否决只增加 0.3pp 成本却带来 +5.9pp 毛超额；② **滚动 12 个月 84.2%（32/38）为正**、中位 +9.82%，**但收益集中在 2017-2019 与 2023-2024，2025 起降到 +0.6~+6.3%，最近窗口 −7.5% —— 近两年明显衰减**；③ **否决在 10 日与月末两个频率下全期都有效**（+5.69pp vs +1.98pp），证明不是频率特异伪影，但强度绑定短持有期（与毒尾 5~20 日反转机制一致）。**结论：全期 +14.5% 达标，但不可按此外推未来，近期水平（+0~+5%）更可能是前瞻性的。** 见 `research/decisions/a_share_final_strategy_profile_v1.md` |
| 2026-09-13 | **实盘执行清单生成器落地**：`scripts/generate_five_factor_veto_holdings_v1.py`（+ `scripts/migration/wsl_run_holdings.sh`），复用**完全相同**的回测管线，输出持仓 CSV / orders / meta。首次产出 `output/live/five_factor_veto_top30/holdings_2026-08-13.csv`：30 只、投入 403,448 元、**仓位利用率 0.807**、行业 cap3 生效、否决屏蔽 70/3,360=2.1%。**实现发现**：50万/top30 单笔预算 16,667 元 → **股价 >166.67 元的股票连 1 手都买不起**，首次清单有 2 只（173.3/177.6 元）目标股数为 0，白占 top30 名额。回测中 qlib 同样买不进，故**回测数字未高估**，但建议后续在选股前加价格可行性过滤（属策略变更，需另立协议）。见 `research/decisions/a_share_five_factor_veto_live_execution_guide_v1.md` |
| 2026-09-13 | **价格可行性过滤（整手约束事前化）测试通过并采纳**：50万/top30 单笔预算 16,667 元 → 股价 >166.67 元买不起（屏蔽 9.8% 候选）。改为**选股前**剔除，让名次递补。全期净超额 **+13.83% → +16.35%**（滞后1日口径 +15.91%，非同日伪影），**IR 1.203 → 1.378**。**归因必须诚实**：+2.52pp 混合了①资金利用率修复（0.807→~0.93，等比放大约 15%）与②低价倾斜（策略变更）；IR 同时上升说明②确实存在（纯等比放大不会改变 IR）。**负面证据**：`new_coverage` 段由 −6.65% **变差到 −10.04%**。见 `research/decisions/a_share_price_feasibility_decision_v1.md` |
| 2026-09-13 | **衰减监测看板落地**：`scripts/monitor_strategy_decay_v1.py`（+ `wsl_run_monitor.sh`），输出滚动 12 个月净超额、当前状态判定，**滚动12个月转负即返回退出码 2 触发复核**。首次运行（最终策略含价格过滤）结果：全期年化净超额 **+17.40%**、滚动12个月为正比例 **87.7%**、中位 +16.94%，**但当前滚动 12 个月 = −10.35%，已触发复核**。→ **"全期很好、最近一年很差"是本策略最需要正视的事实** |
| 2026-09-13 | **近期表现归因 —— 更正上一轮"最近一年在亏"的错误表述**：拆解后发现 **最近 12 个月策略绝对收益 +28.61%**（不是亏钱），"−10.35%" 只是**跑输中证1000**，而中证1000 同期走出 **+41.01%** 的极端牛市。**关键事实**：① 策略**每一段都是正收益**（+10.2%~+28.6%）；② 策略**每一段都跑赢等权全池**（+3.95~+15.69pp），**包括最近一年 +9.20pp**；③ 全期 vs 中证1000 **+17.40pp**、vs 等权全池 **+9.01pp**。**滚动 12 个月两口径相反**：vs中证1000 为正比例 87.2% 但当前 −10.35%；vs等权全池 70.6% 但当前 **+19.55%**。**处置**：不得择优挑选基准——「选股能力」看 vs 等权全池（四段全正，更稳健），「用户真实体验」看 vs 中证1000（最近一年跑输）。**监测看板触发条件修正**为两口径**同时**为负才触发（单口径转负只记录）。见 `research/decisions/a_share_recent_underperformance_attribution_v1.md` |
| 2026-09-13 | **数据完整性缺陷：日历领先于行情 21 个交易日（已修复）**。`calendars/day.txt` 末端 2026-09-11，但**个股 bin 数据实际止于 2026-08-13**（仅 1 个指数到 09-11）→ 实盘信号在最新交易日**静默产出全 NaN 清单**（30 只目标股数全 0、毒尾否决屏蔽 0 个候选）。根因：`update_daily_market_data_v1.py` 用**日历末日**当"数据末端"，故永远判定"无新交易日"，缺口永不补齐。**已修补**为 `min(日历末日, raw 行情末日)` 并兼容两种 raw 目录布局；**已补齐 21 天**（`[repair] rebuilt appended window for 5,563 stocks`，现 5,550 只个股到 2026-09-11）。**补齐后实盘清单**（asof 2026-09-11）：30 只、投入 424,760 元、**利用率 0.850**、否决屏蔽 130/3,360=3.9%（与回测 3.8% 一致）。见 `research/decisions/data_integrity_calendar_ahead_of_data_v1.md`。**要求**：后续生成实盘清单的脚本必须显式校验 asof 当日价格非空，否则失败退出 |
| 2026-09-13 | **前瞻跟踪链路打通 + 模拟盘两处缺陷修复**。① 持仓生成器新增写出 `output/live_ledger/signal_YYYY-MM-DD_ffveto.csv`（格式对齐既有 `paper_trading_tracker_v1.py`，**复用而非重写**），并加**数据完整性断言**：asof 当日查不到价格则直接失败退出（回应上一轮静默 NaN 缺陷）。② 修复 `get_holdings_on` 的 **1 日前瞻**：原用 `rebalance_date <= date`，而 `daily_return` 是 `close(prev)→close(day)`，导致**每个调仓日拿新组合赚信号生成前一天的收益**（10日调仓下约占 10% 交易日）→ 已改为严格 `<`。③ 修复状态页初始资金恒为 100,000（`PORTFOLIO_CAPITAL` 只在 `--init` 赋值）导致的「累计收益 +390.69%」荒谬显示 → 改为从 NAV 日志首行取。**当前状态**：初始资金 500,000、净值 500,000、持仓 0（**正确**：信号 09-11 于 t+1 生效，而 09-11 是最后一个有行情日）。见 `research/decisions/paper_trading_forward_tracking_v1.md` |
| 2026-09-13 | **毒尾否决的底仓迁移检验（`transfers`，4/5 为正）**：此前 12 个稳健性变体全部只测过五因子底仓，本次换 **5 个结构完全不同的 alpha 源**（小市值 / 5日反转 / 低换手 / 低波动 / 20日反转）各做有无否决对照。增量：`size_small` **+2.77pp**、`rev_5` **+2.56pp**、`lowturn` **+1.59pp**、`lowvol` +0.18pp、`rev_20` −0.10pp → **4/5 为正**，证明否决是**通用风险叠加层**而非与五因子共同拟合的产物。**但必须清醒**：五个底仓本身**全部为负**（−4.1%~−19.6%），否决改善了它们却没有一个转为正超额——**否决是过滤器，不是 alpha 源**。`lowturn` 尤为典型：项目记录其 IC +0.064，纯多头却是 −4.13%，再次印证教训 1。`rev_20` 是例外，因 20 日反转与毒尾在选股方向上直接冲突，说明否决的作用范围**有边界且可解释**。见 `research/decisions/a_share_veto_transfer_decision_v1.md` |
| 2026-09-13 | **剔除开发段后的表现 —— 对"全期靠 2016-2019 撑"的正面回答**：把 2016-2019 整段剔除后重算，**2020-2026H1（6.5年）策略净 +21.00%/年 vs 中证1000 +7.39%/年 → 净超额 +11.22pp/年，仍高于 10pp 门槛**。关键在于**该段中证1000 是上涨的（+7.39%），不存在"靠基准下跌取胜"**。且 **vs 等权全池的超额在两个窗口几乎完全相同**（全期 +9.01pp / 2020起 +9.12pp，差 0.11pp）——这是"选股能力"最可信的证据。**仍未解决**：最近12个月 vs 中证1000 仍 −10.35%（中证1000 同期 +41.01%）；2020-2026 仍属样本内，"剔除一段"不等于"未见过的数据"；价格可行性过滤含未单测的低价倾斜。见 `research/decisions/a_share_ex_development_performance_v1.md` |
| 2026-09-13 | **低名义价格因子验证 + 迁移检验扩至 6 个底仓**：为拆解价格可行性过滤的 +2.52pp（粗算 ≈ +0.7pp 仓位利用率 + +1.8pp 选股），把 **`lowprice`（低名义价格，截面排序）**作为独立 alpha 放进迁移框架。**结果：`lowprice` 是六个底仓中【唯一】为正的单因子（full +4.82% / IR +0.286）**，其余五个全负（−4.1%~−19.6%）→ **验证了那 +1.8pp 的选股部分确是真实因子**，此前被"整手约束"掩盖。**第二发现**：`lowprice` (+4.82%) 与 `size_small`(−4.91%) **方向相反** → **低名义价格 ≠ 小市值**，本样本里"小市值"并非收益来源、"低股价"才是；这与"等权全池跑赢中证1000"不矛盾（那是**基准口径**差异，非小市值因子有效）。**第三发现**：否决对 `lowprice` 无效（−0.68pp），因毒尾（近期极端涨幅）与低名义价格（便宜被忽视）**两集合基本不相交**，再次说明否决作用范围有边界。否决迁移仍 **4/6 → `transfers`**。见 `research/decisions/a_share_lowprice_factor_v1.md` |
| 2026-09-13 | **低名义价格显式建模 —— 判定 `reject`（协议挡住了 −2.7pp 退步）**。Q1 正交性：`corr(lowprice, composite5) = +0.174 ≪ 0.5`，**确实与五因子基本独立**（与 `bm` 最强 +0.365）。Q2 增量：`composite6`（显式加入 lowprice）使 **full −2.73pp / holdout −3.78pp** → 拒绝。**但这个失败给出两个真信息**：① **B(comp6+价格过滤) +13.63% ≈ C(comp6无过滤) +13.56%，差 0.07pp** → 一旦 lowprice 显式化，价格过滤不再提供增量，**反证其此前 +2.52pp 确实全部来自低价倾斜**；② **同样的低价暴露，用"约束"实现（A +16.35%）优于用"因子"实现（B +13.63%）**——约束只做温和倾斜，因子会激进加载最便宜那批，而 `lowprice` 的 new_coverage 段是 −24%。**最终策略维持 A 臂不变**。见 `research/decisions/a_share_lowprice_factor_closure_v1.md` |
| 2026-09-13 | **流动性过滤缺陷：根因定位 + 修复 + 影响量化**。**根因**：`load_amount_avg` 使用**本模块的** `BT_START/BT_END`，而该模块是另一条实验线（其 BT_START 是近期日期），被五因子线调用时出现 **`warm_start=2026-08-03 > end_time=2025-06-30` 的倒置窗口** → `D.features` 返 0 行 → pivot 得 0 列 → 调用方 `avg` 全 NaN → `NaN < 门槛` 恒 False → **过滤静默失效**。**修复**为按传入 calendar 决定窗口 + 显式倒置检查（同类问题今后立刻报错）；验证：`(2843,0)` → **`(2843,3)`，每列 2,839 非空**。**50万口径影响与预测一致、几乎为零**：full **+13.83% → +13.45%（−0.38pp）**，各 stage 差 ≤0.85pp，**每期候选数 2,924（生效）vs 2,925（失效），平均只剔除 1 只**。**但推论严重**：1亿门槛只 34.7% 通过，故**项目既有五因子线报告的"容量控制"从未生效**（实际池约 2,925 只而非设计约 1,000 只），很可能高估其表现——**引用前须在 1 亿口径重跑（本次未做，列为待办）**。见 `research/decisions/a_share_liquidity_filter_bug_closure_v1.md` |
| 2026-09-13 | **⚠ 重大更正：流动性过滤修复使【1 亿口径】结果大幅下修**。因 1 亿门槛（1.33亿/日）只让 34.7% 通过、而 50 万门槛（66.7万/日）让 98.9% 通过，两者受 no-op 缺陷的影响天差地别。**1 亿口径修复前后**：C 臂（10日+否决）**+14.08% → +8.57%**（IR 1.2245 → **0.763**，**−5.51pp**）；D 臂 +13.56% → +7.96%；B 臂 +8.88% → +4.52%；A 臂（项目记录的基线）+8.36% → **+7.42%**；C 的 new_coverage **−6.72% → −24.31%**。否决增量 full **+5.19 → +4.04pp**（仍为正但缩小），new_coverage 段符号**由正转负**。**50 万口径不受影响**：本轮用修复后过滤重建快照重跑，最终策略 **+16.35% → +16.01%（−0.34pp）**、IR **1.349**。→ **用户策略全部结论不变；项目既有五因子线的 headline 须按此更正**。见 `research/decisions/a_share_liquidity_filter_100m_impact_v1.md` |
| 2026-09-13 | **更正账户规模结论：小资金反而是优势**。原结论"50万与1亿无实质差异（≤0.25pp）"**是 no-op 缺陷造成的假象**——修复前过滤在两个口径下都不生效，两者共用同一个池，自然相同。修复后：**50万 +13.45%（IR 1.172）vs 1亿 +8.57%（IR 0.763），差 +4.88pp，方向是小资金更优**。机制：资金小→单笔小→所需流动性门槛低（98.9% 通过）→保留中小市值/低价段；资金大→门槛高（34.7% 通过）→被迫放弃该段，而该段正是收益来源（与 `lowprice` 是六个底仓中唯一为正的单因子一致）。**教训**：用"两配置结果相同"论证"该因素不重要"前，必须先证明两个配置真的不同；**"无差异"本身可能是缺陷的症状**。见 `research/decisions/a_share_account_size_correction_v1.md` |
| 2026-09-13 | **稳健性检验在修复后基座上复核**：1 亿口径池由约 2,925 只压缩到约 1,000 只后，12 个变体重新计算 → **`definition_robust` 仍成立（12/12 为正）**，中位数 +3.68 → **+4.24pp**。**但一条附加推论被削弱**：`comp_cc_q90`（纯 close-to-close 复合）由 +3.33pp **塌到 +0.22pp**；不过纯 c2c 的**单因子**（`vol_20` +4.43pp、`ret_20` +3.29pp、`amp_20` +2.56pp）仍有效。**准确表述**：毒尾效果**不是**隔夜/日内分解特有的（仍成立），但"纯 c2c 复合分可替代"**不再成立**。见 `research/decisions/a_share_robustness_recheck_v1.md` |
| 2026-09-13 | **最终策略阶段拆解复核（修复后权威数字）**：全期策略净 **+16.33%**、净超额 **+16.99pp**（vs 中证1000）/ **+8.59pp**（vs 等权全池）；**★2020-2026H1 剔除开发段：策略 +20.88% vs 中证1000 +7.39% → +11.11pp，仍高于 10pp 门槛**（且该段基准是上涨的，不存在"靠基准下跌取胜"）；对等权全池超额在两窗口高度一致（+8.59 / +9.00pp）。滚动 12 个月为正比例 **87.6%**、中位 +16.17%、**当前 −10.42%**。→ **流动性过滤修复未改变策略结论**（全期 +17.40 → +16.99pp）。`research/STRATEGY_DELIVERY_v1.md` 已同步为权威数字 |
