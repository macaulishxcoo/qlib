# A股横截面选股的深度学习模型与框架调研（2025–2026）

> 调研视角：你已有 Qlib 本地开发版（torch 2.6.0+cu124 / lightgbm 4.6 / pandas 2.3.3 / tushare），
> 目前只用 LightGBM + Alpha158 类人工因子，深度学习线基本空白。
> 本文按"推荐度"分档，每条给出：名称 / 链接 / 一句话价值 / 接入成本 / A股适配度 / 已知风险。
> 所有结论尽量标注来源；**我自己的判断与推测会明确写成"判断："**，与有出处的硬事实区分开。

---

## 0. 结论先行（TL;DR）

1. **"A股 DL 打不过 GBDT"这句话在 2025–2026 年依然大体成立，但它的成立有一个精确边界：在人工因子表（Alpha158 类）上成立，在原始量价序列（Alpha360 类）上不成立。** 这不是玄学，是 Qlib 官方 20-seed benchmark 的直接读数（见 §1）。
2. **你现在的处境正好落在 DL 没有优势的那一档。** 你喂 Alpha158，DL 学不到 GBDT 学不到的东西；要吃到 DL 红利，得换输入表征，而不是换更复杂的网络。
3. **当前 ROI 最高的动作不是接新模型，而是在你现有的 LightGBM 上加一层"市场漂移适应"（DDG-DA，Qlib 主仓自带），官方数据是 IR 1.32 → 2.01。**
4. **真正值得投入的新东西只有两类**：(a) Qlib 主仓自带的 Alpha360 + DL 组合；(b) Kronos 这条有官方 Qlib A股微调管线的基础模型线。
5. **2026 年最一致的实证结论是：架构不是瓶颈，损失函数/输出头/样本构造/评估口径才是。** 见 §1.3–§1.4。
6. **⭐⭐ 最便宜、收益最大、且被控制变量实验证明的两件事（零模型/零数据/零 GPU 成本，建议排在引入任何新模型之前）**：
   - **改损失函数**：架构固定、只换 loss，Sharpe 0.6637→0.7529、最大回撤 -19.58%→-15.77%，而 IC 几乎不动。**用 MSE 做模型选择会系统性选错模型。**（[arXiv:2510.14156](https://arxiv.org/abs/2510.14156)，§1.4(0)）
   - **改评估口径**：**风格残差化** + 改用**首个可成交价**计价。不做这两步，你后面所有模型对比的结论都不可信。（[STRATA](https://arxiv.org/abs/2608.28060)，§1.4(1)）
7. **对"图神经网络/关系型选股"要压低保期望**：中金 2026-08 实测**原始关联收益因子 RankIC ≈ 0（-0.55% / 0.03%），Newey-West t 值仅 1.64/1.59 不显著**；华泰实测图结构增量仅 **+0.42pp RankIC**。**图传播本身更可能是噪声而非 alpha**（§4.7）。且 Qlib 的 "GATs" **根本不是关系图 GNN**，而是当日截面全连接注意力，**全 A 规模必然 OOM**。
8. **如果要碰文本/舆情线，先记住符号是反的**：A股舆情因子 **ICIR ≈ −2.0 ~ −2.3，靠反号才赚钱**；且股吧爬虫有**实际法律风险**（2025 判例判赔 228 万）。**更推荐先做公告事件因子**（PIT 安全、无法律风险、规则+小模型即可）。（§4.8）

> **⚠️ 勘误与修订记录（v3，经交叉核查后修订）**
> **v2 勘误两处（我错了）：**
> 1. ~~"TimeMixer++ 官方实现就在 kwuking/TimeMixer 仓库内"~~ → **错误**。该仓库只在 News 中宣布了 TimeMixer++，**未提供任何代码**；TimeMixer++ 也未被 TSLib 收录。**论文真实（ICLR 2025），代码不存在。**
> 2. ~~"TSLib 维护良好"~~ → **误导**。TSLib 已于 **2026.04 官方宣布停止演进**，并在 README 中自认"**many of its benchmarks may no longer be meaningful**"。baseline 实现仍正确，但不能当"持续演进的 SOTA 库"选型。
>
> **v3 新增与收窄：**
> 3. **新增（改变优先级）**：[损失函数控制变量实验 arXiv:2510.14156](https://arxiv.org/abs/2510.14156)——架构固定只换 loss，Sharpe 0.6637→0.7529，而 **MSE 最低的模型策略最差**。已把"改 loss + 改评估口径"上调到接入路径中**模型引入之前**（§8 第 4 步）。
> 4. **新增**：[Re(Visiting) TSFMs in Finance](https://arxiv.org/abs/2511.18578)（横截面日频超额收益上现成 TSFM 零样本与微调均失败）+ [STRATA](https://arxiv.org/abs/2608.28060)（A股中盘，风格残差化 + 首个可成交价口径）。
> 5. **收窄**：FRL 那篇 "Foundation models do not beat simple volatility benchmarks" 的主题是**波动率**而非收益/横截面，**不能**作为"基础模型在 A股选股上无效"的证据（§9）。
> 6. **核实**：Kronos 论文摘要已读取，原文数字与仓库地址均已确认；**中金/国信引用的"+93%"/"21.9%"就是 Kronos 原论文数字**，非券商自研 A股回测（§2.3）。
>
> **v4 新增（含我从本地 qlib 源码的二次验证）：**
> 7. **HIST 其实是真图模型**——`pytorch_hist.py` 会下载真实的"股票×概念"二分图（`qlib_csi300_stock2concept.npy`），我已在本地源码确认；但**只支持 csi300 且是静态快照**（§2.2）。
> 8. **GNN/关系图的独立负面证据**：[中金 2026-08《如何利用关联图谱信息进行选股？》](https://finance.sina.cn/2026-08-11/detail-inimwyqr0745269.d.html) 实测**原始关联收益因子 RankIC ≈ 0（-0.55% / 0.03%），NW t 值仅 1.64/1.59 不显著**，图传播的价值是"当反向控制项"而非 alpha 来源（§4.7）。
> 9. **RD-Agent 唯一的第三方独立实测**（国联民生 2026-05）：**"组合 ICIR 提升始终弱于 IC"、"仅代表单次运行结果，不保证可再次按顺序挖到"** → 已下调其推荐力度（§3.3）。
> 10. **FinGPT 的"A股因子"commit 是幌子**：PR #274 实为 86 行 JSON schema 校验脚本；且 FinGPT-Forecaster 架构上单 ticker、无截面能力（§4.3）。
> 11. **新增 §4.8**：A股舆情因子 **IC 符号大概率是负的**（开源证券 ICIR −2.0~−2.3）、数据源与法律风险、以及 **Qlib 的 csi300/csi500 是当前成分股（幸存者偏差）** 这个通用坑。

---

## 1. 先回答核心争议：DL 到底打不打得过 GBDT

### 1.1 Qlib 官方 benchmark 硬数据（CSI300，20 random seeds）

来源：[microsoft/qlib `examples/benchmarks/README.md`](https://github.com/microsoft/qlib/blob/main/examples/benchmarks/README.md)

**Alpha158（人工因子表，158 个量价因子）**

| 模型 | IC | ICIR | RankIC | RankICIR | 年化收益 | IR | MaxDD |
|---|---|---|---|---|---|---|---|
| **DoubleEnsemble (LGBM 底座)** | **0.0521** | **0.4223** | 0.0502 | 0.4117 | **11.58%** | **1.343** | -9.2% |
| XGBoost | 0.0498 | 0.3779 | 0.0505 | 0.4131 | 7.80% | 0.907 | -11.7% |
| CatBoost | 0.0481 | 0.3366 | 0.0454 | 0.3311 | 7.65% | 0.803 | -10.9% |
| **LightGBM（你现在的基线）** | **0.0448** | 0.3660 | 0.0469 | 0.3877 | **9.01%** | 1.016 | -10.4% |
| TRA（DL 里最好的） | 0.0440 | 0.3535 | 0.0540 | 0.4451 | 7.18% | **1.084** | **-7.6%** |
| MLP | 0.0376 | 0.2846 | 0.0429 | 0.3220 | 8.95% | 1.141 | -11.0% |
| SFM | 0.0379 | 0.2959 | 0.0464 | 0.3825 | 4.65% | 0.567 | -12.8% |
| ALSTM | 0.0362 | 0.2789 | 0.0463 | 0.3661 | 4.70% | 0.699 | -10.7% |
| Localformer | 0.0356 | 0.2756 | 0.0468 | 0.3784 | 4.38% | 0.660 | -9.5% |
| GATs | 0.0349 | 0.2511 | 0.0462 | 0.3564 | 4.97% | 0.734 | -7.8% |
| TCN | 0.0279 | 0.2181 | 0.0421 | 0.3429 | 2.62% | 0.413 | -10.9% |
| Transformer | 0.0264 | 0.2053 | 0.0407 | 0.3273 | 2.73% | 0.397 | -11.0% |
| TabNet | 0.0204 | 0.1554 | 0.0333 | 0.2552 | 2.27% | 0.368 | -10.9% |

**Alpha360（原始量价，60 天 × 6 通道，几乎无特征工程）**

| 模型 | IC | ICIR | RankIC | RankICIR | 年化收益 | IR | MaxDD |
|---|---|---|---|---|---|---|---|
| **HIST** | **0.0522** | 0.3530 | **0.0667** | 0.4576 | **9.87%** | **1.373** | **-6.8%** |
| TCTS (GRU 底座) | 0.0508 | 0.3931 | 0.0599 | 0.4756 | 8.93% | 1.226 | -8.6% |
| ALSTM | 0.0497 | 0.3829 | 0.0599 | 0.4736 | 6.26% | 0.865 | -9.9% |
| GRU | 0.0493 | 0.3772 | 0.0584 | 0.4638 | 7.20% | 0.973 | -8.2% |
| TRA | 0.0485 | 0.3787 | 0.0587 | 0.4756 | 9.20% | 1.279 | -8.3% |
| **IGMTF** | 0.0480 | 0.3589 | 0.0606 | 0.4773 | 9.46% | 1.351 | -7.2% |
| GATs | 0.0476 | 0.3508 | 0.0598 | 0.4604 | 8.24% | 1.108 | -8.9% |
| AdaRNN | 0.0464 | 0.3619 | 0.0539 | 0.4287 | 7.53% | 1.020 | -9.4% |
| LSTM | 0.0448 | 0.3474 | 0.0549 | 0.4366 | 6.47% | 0.896 | -8.8% |
| TCN | 0.0441 | 0.3301 | 0.0519 | 0.4130 | 6.04% | 0.830 | -10.2% |
| ADD | 0.0430 | 0.3188 | 0.0559 | 0.4301 | 6.67% | 0.899 | -8.6% |
| **LightGBM（基线）** | 0.0400 | 0.3037 | 0.0499 | 0.4042 | 5.58% | 0.763 | -6.6% |
| DoubleEnsemble | 0.0390 | 0.2946 | 0.0486 | 0.3836 | 4.62% | 0.615 | -9.2% |
| **KRNN** | 0.0173 | 0.1210 | 0.0270 | 0.2018 | **-4.65%** | -0.542 | -29.2% |
| **Sandwich** | 0.0258 | 0.1924 | 0.0337 | 0.2624 | 0.05% | 0.000 | -17.5% |

### 1.2 从这张表读出的三条结论（这是全文最重要的一段）

**结论 A：DL 的胜负完全取决于输入表征，而不是模型本身。**

- Alpha158 上：**没有任何一个 DL 模型在 IC 上超过 LightGBM**（最好的 TRA 0.0440 vs LGBM 0.0448）。唯一超过 LightGBM 的是 DoubleEnsemble（IC 0.0521 / 年化 11.58%），但它的底座就是 LGBM。
- Alpha360 上：HIST / IGMTF / TRA / GATs / TCTS / GRU / ALSTM **全面超过 LightGBM**，IC 提升约 20–30%，年化收益从 5.58% 提到 7.2%–9.9%，IR 从 0.76 提到 0.97–1.37。

**我的判断（这是给你的核心建议）**：Alpha158 把横截面结构、时序结构、排序关系都已经人工编码进特征里了，DL 在这上面只能做"更花哨的查表"，反而因为参数量大、样本效率低而输。Alpha360 几乎没有特征工程，DL 的表示学习能力才有发挥空间。
→ **你要吃 DL 红利，第一步不是换模型，是把输入从 Alpha158 换成 Alpha360（或你自己构造的原始量价张量）。** 在 Alpha158 上继续堆 Transformer/LSTM 是纯粹的负回报投入。

**结论 B：有明确的"坏模型"，别踩。**
KRNN（IC 0.0173，年化 **-4.65%**，MaxDD -29.2%）和 Sandwich（IC 0.0258，年化 0.05%，MaxDD -17.5%）是两个确定的失败实现。我读了源码，KRNN 的问题是可定位的（见 §5.2），不是"运气不好"。

**结论 C：注意 std，别被单次运行骗了。**
LGBM/XGBoost/CatBoost 的 std 是 0.00（确定性）；DL 模型的 std 普遍是 0.02–0.05（年化收益一栏）。也就是说 **DL 单次跑出来的 9% 和 2% 可能没有统计差异**。官方是 20 runs 取 mean±std。你自己做对比时如果只跑一次，很容易得出"DL 更好/更差"的错误结论。

**⚠️ 重要的诚实声明**：这张官方表的 train/valid/test 切分是固定的（源自 Yahoo 口径的 qlib cn_data），时间跨度偏早（约 2008–2020），**它不是 2025–2026 的样本外结果**。它证明了"机制"，但不能直接外推到今天的市场。请务必在你自己的数据上重跑（见 §7 的路径设计）。

### 1.3 2025–2026 年的新证据：这个说法还成立吗？

**证据 1：券商实测——"AI 策略 2025 年真的跑输了传统策略"**

[国金证券《量化漫谈系列之十九：AI选股模型失效的三种应对方法》（2025-12-30，高智威）](https://stock.finance.sina.com.cn/stock/go.php/vReport_Show/kind/lastest/rptid/820428637580/index.phtml)

报告原文要点（不是我的推测）：
- 2025 年 8–9 月，前期资金在市值因子上过度拥挤，触发剧烈均值回归；**主流 AI 指增策略因未能适应这种历史上少见的风格漂移，出现与小市值因子反转高度同步的净值回撤**。
- 原文措辞：**"AI 策略由于对历史数据路径的依赖较强，在应对流动性收缩及板块快速轮动时，其表现甚至不如传统策略。"**
- 归因：**"行业内普遍采用 GRU 与 LightGBM 作为基座模型"**，导致不同机构生成的因子与公募指增基金净值相关性持续走高 → 策略同质化 → 共振时流动性压力。
- 他们给出的解法**不是换更大的模型**，而是：
  - LightGBM：高质量样本加权（引导关注抗跌因子）+ 损失函数换 **Huber Loss** → 多头超额最大回撤压到 5.88%
  - GRU：加 **Attention Pooling** + **Memory 模块 + CVaR Loss**（强制记忆历史极端行情）→ 最大回撤降到 8.54%，Calmar 3.02
  - 外加独立于选股模型的**事件化择时风控层** → 年化超额稳定在 4.15%，Sharpe 4.12

**证据 2：券商实测——2026 年 A股在用的 DL 基座是 AGRU，增益来自"样本构造"而非架构**

[广发证券《金融工程：基于市场状态划分的机器学习ALPHA因子构建》（2026-09-01，安宁宁/陈原文/王小康）](https://stock.finance.sina.com.cn/stock/go.php/vReport_Show/kind/11/rptid/841632221169/index.phtml)

- 基准模型是 **AGRU（Attention-GRU）**，2020-01 至 2026-06 样本外。
- 用"难做指数"（行业成交额集中度 + 行业正收益贡献头部集中度 + 个股收益截面离散度）划分市场状态，**分别训练两套 AGRU**：
  - 难做状态模型：IC 10.93%，ICIR 0.96，多头年化超额 9.38%，**多头超额最大回撤仅 -6.55%**
  - 好做状态模型：IC 10.66%，多头年化超额 9.96%
  - **两套模型多头超额收益的时序相关性仅 48.00%** ← 这才是真正的分散化来源
  - 等权合成后：IC 11.32%，ICIR 0.96，IC 胜率 84.62%，多头年化超额 10.38%，多头 IR 1.85，多空年化 41.18%，多空 Sharpe 3.07
- （注：这里的 IC ~10% 是不同票池/不同标签口径，**不可与 §1.1 的 CSI300 IC 0.045 直接比较**。）

**证据 3：2026 年三篇论文，结论高度一致——架构不是瓶颈**

| 论文 | 场景 | 核心结论 |
|---|---|---|
| [Heads, Not Backbones: Output Heads Dominate Architectures on Fat-Tailed Returns](https://ar5iv.labs.arxiv.org/html/2606.30037)（ACM ICAIF 2026，[代码](https://github.com/Routhleck/heads-not-backbones)） | S&P500 月/日频，4 backbone × 3 head，720 runs | **换输出头（point → Gaussian → GMM 密度头）的 CRPS 提升 3.7pp，远大于换 backbone 的 <1.5%。** 且 **R²_OOS 全部落在 -3.8% ~ +3.7%**，方向准确率在短周期接近 50%。作者明确说："一个消费我们密度预测的朴素均值回复策略在**每一个**变体上都亏钱。" |
| [Pretrained Time-Series Foundation Models for Financial Return Forecasting](https://ar5iv.labs.arxiv.org/html/2606.27100)（2026-08） | 5 只美股，TimeGPT/TimesFM-2.5/Moirai-2.0/Chronos/Chronos-2 vs NBEATS/NHITS/PatchTST/iTransformer/KAN | 预训练 TSFM 在排名上占优（10 个任务赢 8 个），**但 iTransformer 在 META 上两个任务全赢**，说明本地监督学习仍可在特定资产上击败通用预训练。更关键：**"相对随机游走的增益又小又稀疏"**，Diebold–Mariano 检验只在 Chronos(AMZN) 和 Moirai-2.0(GOOG) 上拒绝"等于或劣于"原假设。结论：TSFM 是降低建模成本的先验，**不是可靠的 alpha 引擎**。 |
| [A Controlled Comparison of Deep Learning Architectures for Multi-Horizon Financial Forecasting: Evidence from 918 Experiments](https://ar5iv.labs.arxiv.org/html/2603.16886)（2026） | 9 架构 × 3 资产类 × 2 horizon，918 runs | ModernTCN 最佳、PatchTST 次之；架构解释 99.90% 的 RMSE 方差（seed 只占 0.01%）；**但"方向准确率在全部 54 个 model–category–horizon 组合上与 50% 无法区分"**，作者结论：**"directional forecasting requires explicit loss-function redesign"**。 |

**⚠️ 注意上表的适用边界**：证据 3 的三篇都是**单资产时序预测**，不是**横截面排序**。它们不能直接证明"A股选股上架构不重要"。但把它们和证据 1、2 放在一起，方向是一致的：**在这个信噪比极低的领域，模型容量的边际收益递减得极快，而损失函数、输出头、样本构造、评估口径的边际收益还很大。**

**我的综合判断**：
> "A股上 DL 打不过 GBDT + 好因子"——**在"你用人工因子喂模型"和"你比的是单模型 IC"这两个前提下，2025–2026 年依然成立**。
> 但这个说法**不成立于**三种情形：
> 1. 输入是原始量价序列而非人工因子表（Alpha360 类，§1.1）
> 2. 比的是"GBDT + 漂移适应" vs "GBDT"（DDG-DA，§2.1）
> 3. 比的是多模型集成 / 多频率融合 / 市场状态分治（广发 2026、东吴 2026）
> 所以正确的问法不是"DL 还是 GBDT"，而是**"DL 应该在管线的哪一层介入"**——我的答案是：**不要用 DL 替换 GBDT 做最终打分器；用 DL 做表征学习（原始序列）、做漂移适应（元学习）、做多频率/多模态融合、以及做因子生成（LLM）。**

### 1.4 ⭐ 三篇必读：最能改变你行动优先级的实证

**（0）损失函数 vs 骨干网络：一个控制变量实验（这是本文对"改 loss 还是换架构"最直接的证据）**

**[On Evaluating Loss Functions for Stock Ranking: An Empirical Analysis With Transformer Model](https://arxiv.org/abs/2510.14156)**（Kwiatkowski & Chudziak，华沙理工，2025-10，已投 CIKM 2025）

**实验设计的价值在于控制变量**：**模型架构完全固定**（PortfolioMASTER，正是受 §3.1 的 MASTER 启发），**只换损失函数**，共 8 种。110 只 S&P500 股票（11 个 GICS 行业各取市值前 10），2015-01 ~ 2024-12，lookback T=20，特征只有 2 个（日收益 + 换手率），Top-5 日频等权多头。

| 损失函数 | 类别 | 年化% | Sharpe | 最大回撤% | IC(Spearman) | **测试集 MSE** |
|---|---|---|---|---|---|---|
| **MSE（基线）** | Pointwise | 14.78 | **0.6637** | -19.58 | 0.0754 | **0.00286（最低）** |
| Hinge | Pointwise+Pairwise | 15.33 | 0.6984 | -19.58 | 0.0762 | 0.00301 |
| **Margin** | Pointwise+Pairwise | **16.23** | **0.7529** | -18.33 | 0.0758 | 0.00632 |
| **BPR** | Pointwise+Pairwise | 15.74 | 0.7200 | **-15.77** | **0.0733（最低）** | 0.01145 |
| RankNet | Pointwise+Pairwise | 15.01 | 0.6771 | -18.97 | **0.0767（最高）** | **0.01909（6.7×）** |
| WHR1 | Weighted Hinge | 15.25 | 0.6938 | -19.54 | 0.0763 | 0.00352 |
| WHR2 | Weighted Hinge | 15.17 | 0.6866 | -19.74 | 0.0764 | 0.00300 |
| **ListNet** | Listwise | 16.00 | 0.7407 | -18.36 | 0.0761 | **1.01212** |

**三条可用的推论**：
1. **测试集 MSE 与组合表现几乎反向。** MSE 基线的 MSE **最低**（0.00286），但它的 Sharpe **低于全部 7 种排序损失**。RankNet 的 MSE 是基线的 **6.7 倍**，IC 却**最高**（0.0767）。ListNet 的 MSE 更是高达 1.01212。→ **用 MSE 做模型选择会系统性选错模型。** 这也正好解释了 §1.1 里 Qlib TFT 的病症：**IC 0.0358 但 RankIC 崩到 0.0116**——用 MSE 训出来的模型在"数值准"和"排序对"之间选了前者。
2. **IC 对损失函数几乎不敏感，经济结果却敏感。** 8 种损失的 IC 全落在 **0.0733–0.0767（极差仅 0.0034）**，而 Sharpe 跨度 **0.6637→0.7529**、最大回撤跨度 **-19.58%→-15.77%**。→ **IC 相近 ≠ 策略相近；只报 IC 会掩盖真正重要的差异。**
3. **BPR 的 IC 最低但回撤最优（-15.77%）** → 风控与排序精度是**两个不同目标**，需要分开优化。

**⚠️ 必须打上的折扣（我的判断，请勿过度外推）**：
- **票池只有 110 只美股大盘股**，与 A股 CSI300/全 A 不可比；绝对 IC ~0.075 也不能与 Qlib 的 CSI300 IC 0.045 直接比较。
- **Top-5 日频调仓 + 论文未讨论交易成本** —— 日频换手 5 只的成本可能吃掉大部分 14–16% 的年化。
- **单次切分（70/15/15）、无 walk-forward、无多 seed** → 属于单次运行结果，差异可能不显著。
- 表中 **ICIR 一列（~8.8）量级可疑**（与 IC/Std IC 对不上），**不要引用这一列**。
- 这是一篇华沙理工的**预印本/学生工作**，样本规模小；**当作方向性证据，不是定论**。

**但其方法论结论我认可并采纳**：**改损失函数与评估口径是零模型成本、零数据成本、零 GPU 成本的动作，而它影响的经济结果与"换骨干网络"同量级。** 因此在 §8 的接入路径中，我把"改 loss + 改评估口径"的优先级**上调到模型引入之前**（见第 4 步）。

---

**（1）STRATA（[arXiv:2608.28060](https://arxiv.org/abs/2608.28060)，2026-08，v3 2026-09）——本文最值得你花 10 分钟读摘要的一篇**

标题：*A Compact Selective State-Space Model for Cross-Sectional Stock Return Ranking from Raw Intraday Bars*

**任务设置与你的场景高度重合**：约 **1000 只 A股中盘股**，输入 **5 天原始 5 分钟 bar + 订单簿**（**无任何人工特征**），输出**次日横截面收益排序**；训练 4 年、留出 1 年只评测一次。模型只有 **244,633 参数**。

**报告结果**：风格残差化后的 **RankIC 0.0728 / IR 1.128 / 多空 Sharpe 12.85**，在全部 4 个指标上超过 6 个参数量匹配的序列基线，RankIC 的日度配对差异 **p < 0.001**。

**但摘要里有两句话，价值超过上面所有数字：**

> ① *"Because a score that merely tilts toward common style factors scores well on raw rank correlations, **every model's scores are residualised against eight price-volume style factors before any metric is computed**."*
> （一个仅仅偏向常见风格因子的打分，在**原始** rank correlation 上就能拿高分——所以他们在计算任何指标之前，**先把所有模型的分数对 8 个量价风格因子做了残差化**。）

> ② *"**The close-to-close target opens before the score exists**: measured instead from the first executable price, **the decile spread is indistinguishable from zero**, while the ordering of the seven architectures is unchanged."*
> （收盘到收盘的标签在分数产生之前就已经开盘了；**改用首个可成交价计价后，十分位价差与零无法区分**——尽管七个架构的排序没变。）

**这两句话的含义（我认为这是本次调研最有实操价值的结论）：**
- **你的回测很可能高估了自己。** 如果你的信号是收盘后算出来、标签是 close-to-close，那你实际上在用一个"分数还不存在时就已经开盘"的价格成交。**换成首个可成交价，很多 alpha 会直接归零。**
- **不做风格残差化，你测的是 beta 不是 alpha。** A股上"偏向小市值/低波/动量"就能在原始 RankIC 上拿高分，这跟模型能力无关。
- **注意**：即使做了残差化，STRATA 的分数**在可成交价下也归零**——这说明**口径问题是独立于模型的、更底层的问题**。

**行动项（立刻可做，零成本）**：
1. 重跑你的 LightGBM 回测，**标签和成交价都改用首个可成交价**（如次日 VWAP 或次日开盘后 N 分钟均价），看超额还剩多少。
2. **在计算 IC/RankIC 之前，先把预测值对市值、行业、波动率、动量等风格因子做截面回归取残差**，再算 IC。
3. 把这两条**写进你的所有对比协议**——否则你后面比较 DL 和 GBDT 时，比的可能是谁更会偷风格暴露。

**（2）[Re(Visiting) Time Series Foundation Models in Finance](https://arxiv.org/abs/2511.18578)（2025-11）**——已在 §4.2 详述，此处只记结论：**横截面日频超额收益任务上，现成 TSFM 零样本和微调都不行，只有金融原生从零预训练有效。**

---

## 2. 强烈推荐接入

### 2.1 DDG-DA（市场动态适应）—— 当前 ROI 最高的单点改进

| 项 | 内容 |
|---|---|
| 名称 | DDG-DA（DDG-DA: Data Distribution Generation for Predictable Concept Drift Adaptation, AAAI 2022） |
| 链接 | [microsoft/qlib `examples/benchmarks_dynamic/DDG-DA`](https://github.com/microsoft/qlib/tree/main/examples/benchmarks_dynamic/DDG-DA) |
| 一句话价值 | **不换 backbone，只加一层"预测未来数据分布并据此重训"的元学习外壳，在 LightGBM 上把 IR 从 1.32 提到 2.01。** |
| 接入成本 | **极低**。已在 `microsoft/qlib` 主仓（不是 fork），你现有环境直接跑；不需要 GPU 重训网络，底座就是你的 LightGBM。 |
| A股适配度 | **原生**。就是为 A股/CSI300 设计的，官方用 qlib cn_data。 |
| 官方数据 | Alpha158，label horizon=20，滚动 20 交易日，测试期 2017-01 ~ 2020-08，众包数据源：<br>RR[Linear] IC 0.0945 / IR 1.368；DDG-DA[Linear] IC 0.0983 / IR 1.190<br>**RR[LightGBM] IC 0.0816 / ICIR 0.5887 / RankIC 0.0912 / 年化 7.71% / IR 1.3196**<br>**DDG-DA[LightGBM] IC 0.0878 / ICIR 0.6185 / RankIC 0.0975 / 年化 12.61% / IR 2.0096** |
| 已知风险 | ① 官方 README 明确警告：Yahoo 版 qlib 数据缺 `VWAP`，相关因子被填 0 会导致**秩亏矩阵，DDG-DA 的下层优化无解** → 必须用众包数据（见 §7）。<br>② 增益依赖"漂移可预测"这个假设，2025 年那种突变式风格漂移（国金报告的场景）未必被覆盖。<br>③ 对比 RR[Linear] 可见：DDG-DA 对 Linear 反而**降低了** IR（1.368→1.190）。它不是普适增益，**对弱基线增益更大**——这恰好说明它补的是"模型对分布漂移的脆弱性"。 |

**判断：这是全篇我最推荐的一步。** 理由：你的瓶颈不是模型容量（LightGBM + Alpha158 已经接近这张表的 GBDT 上限），而是**模型对 2025 年式风格漂移的适应能力**——这正是国金报告指出的行业级痛点。DDG-DA 花的是一天时间，动的是 IR 这个你真正关心的指标。

### 2.2 Qlib 主仓 Alpha360 + DL 模型（HIST / IGMTF / TRA / GATs / TCTS / GRU）

| 项 | 内容 |
|---|---|
| 名称 | Qlib 内置 PyTorch 模型族（HIST、IGMTF、TRA、GATs、TCTS、GRU、ALSTM、LSTM、TCN、ADD、AdaRNN、Localformer、Transformer…） |
| 链接 | [Quant Model (Paper) Zoo](https://github.com/microsoft/qlib/tree/main/examples/benchmarks)；模型实现：[`qlib/contrib/model/`](https://github.com/microsoft/qlib/tree/main/qlib/contrib/model) |
| 一句话价值 | **在 Alpha360（原始量价序列）上，HIST/IGMTF/TRA/GATs/TCTS 全面超过 LightGBM，IC +20~30%、年化 +70~75%、IR +80%。** |
| 接入成本 | **极低。** 全部随 `pip install pyqlib` 就有，无需额外出处。<br>单模型：`qrun benchmarks/HIST/workflow_config_hist_Alpha360.yaml`<br>批量：`python run_all_model.py run 20 hist Alpha360`（会自动建独立 venv 并跑 20 seeds） |
| A股适配度 | **原生**。官方 benchmark 就是 A股/CSI300。 |
| 首选模型（按 Alpha360 表现） | **① HIST**（IC 0.0522 / 年化 9.87% / IR 1.373 / MaxDD -6.8%，综合最强）<br>**② IGMTF**（IC 0.0480 / 年化 9.46% / IR 1.351）<br>**③ TRA**（IC 0.0485 / 年化 9.20% / IR 1.279；Alpha158 上 IR 也高于 LGBM，1.084 vs 1.016）<br>**④ GATs** 入门最简单 |
| **⭐ HIST 其实是真的图模型（我从本地 qlib 源码验证）** | 我读了 `qlib/contrib/model/pytorch_hist.py`：第 258–260 行会**自动下载一张真实的"股票×概念"二分图**：<br>`url = "https://github.com/SunsetWolf/qlib_dataset/releases/download/v0/qlib_csi300_stock2concept.npy"`<br>前向传播里用 `stock_to_concept` 矩阵做 concept 维度聚合（第 431–444 行）。**所以 HIST 是 Qlib 内唯一带真实关系图的模型**，比 GATs 名实相符得多。<br>⚠️ **但有两个硬限制**：① **只支持 csi300**（文件名写死了）；② 那是**静态快照图，无时间维度** → **长周期回测会有前视/幸存者偏差**，你要用的话必须自己重建 PIT 版本的概念图。 |
| 已知风险 | 见 §5「Qlib DL 的七个坑」。最关键的三条：<br>① **HIST/IGMTF/GATs 需要先训练一个 GRU/LSTM 底座并加载 checkpoint**（`base_model` + `model_path` 参数），不是端到端一键训练；<br>② DL std 大（年化收益 std 0.02–0.05），**必须多 seed**；<br>③ 这个 benchmark 的时间跨度偏早，务必自测样本外。 |

**判断：这是你建立 DL 工程能力的正确起点。** 不是因为它的绝对收益有多高（年化 9.87% vs LGBM 9.01% 在 Alpha158 上并不惊人），而是因为：它零接入成本、原生 A股、有官方多 seed 基线可对标。**但请务必在 Alpha360 上跑，不要在 Alpha158 上跑**（§1.2 结论 A）。

### 2.3 Kronos（K 线基础模型）—— 唯一有官方 Qlib A股微调管线的基础模型

| 项 | 内容 |
|---|---|
| 名称 | Kronos: A Foundation Model for the Language of Financial Markets |
| 链接 | **GitHub（真仓库）：[shiyu-coder/Kronos](https://github.com/shiyu-coder/Kronos)**<br>论文：[arXiv:2508.02739](https://arxiv.org/abs/2508.02739)（AAAI 2026）<br>权重（HuggingFace）：[NeoQuasar](https://huggingface.co/NeoQuasar) |
| 一句话价值 | 首个开源金融 K 线基础模型，**官方自带基于 Qlib 的 A股微调 + 回测管线**（`finetune/qlib_data_preprocess.py` / `train_tokenizer.py` / `train_predictor.py` / `qlib_test.py`），可直接读你的 Qlib 数据目录。 |
| **论文摘要已核实（原文数字）** | [arXiv:2508.02739](https://arxiv.org/abs/2508.02739) 摘要原文：*"...their application to financial candlestick (K-line) data remains limited, **often underperforming non-pre-trained architectures**... We pre-train Kronos using an autoregressive objective on a massive, multi-market corpus of **over 12 billion K-line records from 45 global exchanges**... Kronos boosts price series forecasting **RankIC by 93% over the leading TSFM and 87% over the best non-pre-trained baseline**. It also achieves a **9% lower MAE in volatility forecasting** and a **22% improvement in generative fidelity** for synthetic K-line sequences."*<br>**摘要末尾明确给出仓库地址 `github.com/shiyu-coder/Kronos`** —— 这从论文侧独立确认了官方仓库身份。<br>**三点判读**：① 中金/国信引用的"+93%"和"21.9%/IR 1.42"**就是 Kronos 原论文摘要数字，不是券商自研 A股回测**，下游引用时要标注来源性质；② **+93% 是相对提升、不是绝对 RankIC**，且对照基线是"leading TSFM"，摘要**未给绝对值**——从低基数出发的相对提升，绝对水平可能仍很小；③ **最有价值的一点：Kronos 作者自己的动机陈述就承认通用 TSFM 在 K 线数据上"often underperforming non-pre-trained architectures"** —— 金融原生 TSFM 的作者亲口印证了本文 §4.2 的核心结论。 |
| 体量 | ⭐ **约 3.86 万 star，6,447 fork，271 open issues**，MIT 协议，最新 push 2026-04-13。这是本文所有仓库里社区规模最大的。 |
| 模型规格 | Kronos-mini 4.1M（ctx 2048）/ small 24.7M（ctx 512）/ base 102.3M（ctx 512）**已开源**；large 499.2M **未开源**。 |
| 接入成本 | **中。** 需要 GPU；官方脚本用 `torchrun` 多卡（`--nproc_per_node=N`，单卡填 1 也能跑）；small 只有 24.7M 参数，单张消费级卡可微调。两阶段微调：先 tokenizer 再 predictor。 |
| A股适配度 | **官方一等公民。** 作者提供的 finetune 示例**就是** A股 + Qlib；数据预处理脚本原生读 Qlib bin 格式；自带 top-K 策略回测脚本。 |
| 社区实测 | ① [中金《大模型系列（5）：大语言时序模型 Kronos 的 A股择时应用》（2025-10-15）](https://reportify.cn/social-media/730544331169394)<br>　 2025-01~09：5 日收盘价预测与真实序列平均 Spearman **0.78**；**沪深300 0.92，中证1000 0.85**；价值指数优于成长指数。<br>　 **标准版择时"总体获得正收益，但错过了 2025 年 7 月以来的大部分涨幅"，原因是模型依赖前期的指数反转逻辑。**<br>　 微调 + 滚动搜参（T / top_p / lookback_window 月度网格搜索）后：中证1000 上 5 日预测 Spearman **0.732 → 0.856**，MAE **435.2 → 275.5**；2025 年收益 **33.9%**，年化超额 **9%**，比原方法提升 20+ 个百分点。<br>② [国信证券《AI赋能资产配置（二十二）：大模型如何征服K线图？》（2025-11-10）](http://m.hibor.net/wap_detail.aspx?id=afc3cb34786c041cfb811c367981d4b6)：转述 Kronos 论文指标——RankIC 较领先通用时序模型 **+93%**，波动率预测 MAE **-9%**，组合年化超额 **21.9%**，IR **1.42**。<br>③ 中文实战指南：[Vincentwei1021/kronos-guide-cn](https://github.com/Vincentwei1021/kronos-guide-cn)（A股 K 线预测中文实战，数据获取/预测/微调/回测集成）。 |
| 已知风险 | ① **官方自己声明这是 demo 不是生产系统**："This pipeline is intended as a demonstration... not a production-ready quantitative trading system." 且提示需要风险因子中性化才能得到纯 alpha。<br>② 官方提示 `finetune/` 目录的注释**由 Gemini 2.5 Pro 生成，可能有不准确之处**，"请以代码本身为准"。<br>③ ctx 只有 512（small/base），输入超过会被截断。<br>④ **中金的实测是最有价值的风险提示**：标准版 Kronos 在 A股是**均值回复逻辑**，在 2025 年 7 月那种趋势行情里系统性踏空。**它不是万能的，必须微调 + 滚动调参。**<br>⑤ 论文的 21.9% 超额 / IR 1.42 是**作者自己的回测**，我未找到独立第三方复现。<br>⑥ 一篇 2026 年 Finance Research Letters 论文标题直接唱反调：[Foundation models do not beat simple volatility benchmarks: Evidence from 5000 Chinese stocks](https://www.sciencedirect.com/science/article/abs/pii/S1544612326011347)（**我无法读取正文，ScienceDirect 返回 403，仅能确认标题与出处，请勿据此下结论**）。 |

**判断：值得投入，但要摆正预期。** Kronos 的价值不在"开箱即用的 alpha"，而在于：**它是唯一一个"你的 Qlib 数据 → 微调 → 回测"全链路已有官方脚本的开源基础模型**，学习成本和试错成本被作者压到了最低。把它当作"基础模型这条技术路线的低成本入场券"，而不是"替代 LightGBM 的下一代模型"。

---

## 3. 值得一试

### 3.1 MASTER（Market-Guided Stock Transformer, AAAI 2024）

| 项 | 内容 |
|---|---|
| 链接 | 官方轻量仓：[SJTU-DMTai/MASTER](https://github.com/SJTU-DMTai/MASTER)（⭐ 533，**最新 push 2025-06-26，已基本停更**）<br>Qlib 集成版：[SJTU-DMTai/qlib `examples/benchmarks/MASTER`](https://github.com/SJTU-DMTai/qlib/tree/main/examples/benchmarks/MASTER)（注意：**`SJTU-Quant/qlib` 会 301 重定向到这个仓库**）<br>论文：[arXiv:2312.15235](https://arxiv.org/abs/2312.15235) |
| 一句话价值 | 用市场信息（指数收益/成交额的均值与波动）作为**门控**来动态选择因子的股票 Transformer，同时建模"同一时刻的横截面相关"和"跨时间的时序相关"。 |
| 接入成本 | **高，且与你的环境直接冲突。** 官方 README 明确要求 `pandas==1.5.3` + **`torch==1.11.0`**，而你是 pandas 2.3.3 + torch 2.6.0。 |
| A股适配度 | 高（论文本身就是 CSI300/CSI800），但**数据获取是硬伤**（见风险）。 |
| 已知风险 | ① **环境冲突**：torch 1.11 vs 你的 2.6，需要自己升版调试。<br>② **数据不可复现（作者亲述）**：README 原文——原始实验在"公司业务代码库"中完成，"the original code is confidential and exhaustive"；**作者已失去原始数据访问权限**（"our access has expired and we cannot dump the original correct valid & test data again"）。<br>③ **已发表的 valid/test 数据有 bug**：作者承认错误地对 valid/test 使用了 `learn_processor` 而非 `infer_processor`，导致每日 valid/test 数据只含 95% 的股票。作者说"不影响 checkpoint 和结果"（如果你用训练 loss 阈值而非验证 loss 来停止训练的话）。<br>④ **作者明确拒绝回答 Qlib 相关问题**："please refrain us from answering questions on how to use Qlib"。Qlib 集成版是**未参与原研究的志愿者**贡献的，作者建议以轻量仓为准。<br>⑤ 2025-06-26 之后再无更新。 |

**判断：论文强、工程半成品。** 它值得一试的唯一理由是"市场信息门控"这个 idea 本身很有价值，且 Qlib 集成版能跑。但你要做好"自己啃代码 + 自己造数据"的准备。**不要把它当作即插即用的方案。**

### 3.2 DoubleAdapt（KDD 2023，增量学习 + 元学习）

| 项 | 内容 |
|---|---|
| 链接 | 代码在 fork 里：[SJTU-DMTai/qlib `examples/benchmarks_dynamic/incremental`](https://github.com/SJTU-DMTai/qlib/tree/main/examples/benchmarks_dynamic/incremental)（⭐ 148，最新 push 2024-12-12）<br>论文：[arXiv:2306.09862](https://arxiv.org/abs/2306.09862)<br>无 Qlib 依赖的 API 版：[SJTU-Quant/DoubleAdapt](https://github.com/SJTU-Quant/DoubleAdapt)（**作者自述"not well maintained and may have undiscovered bugs"，建议仍用 qlib 版**） |
| 一句话价值 | 两个 adapter（数据 adapter 把增量数据/测试数据都映射到一个"局部平稳分布"，模型 adapter 学一个更好的初始化）来解决在线增量学习中的概念漂移。 |
| 接入成本 | **中高。** 需要额外装 [`higher`](https://github.com/facebookresearch/higher)（meta-gradient 库，`conda install higher -c conda-forge`）；CSI500 + step=20 时约 **8GB RAM + 最多 10GB 显存**。 |
| A股适配度 | 高（论文就是 CSI300/CSI500）。官方跑在众包 qlib 数据上。 |
| 作者亲授的部署建议（README 原文，非常重要） | ① **必须把 IL 和 RR 结合**："retrain DoubleAdapt from scratch every month and, during the month, perform DoubleAdapt every 2~3 trading days"。<br>② **数据 adapter 对 Alpha158 过参数化**：论文只用了 6×6 仿射变换（针对 Alpha360），**面对上百个因子时那个全连接层过参数化、表现次优**，需要自己重新设计（建议按因子分组学仿射，或对每个因子 embedding 学逐元素变换）。<br>③ **必须对 3 个学习率（`lr_da` / `lr_ma` / 下层 `lr`）做网格搜索**，且线上学习率可以和离线不同（`--online_lr`）。<br>④ **`step` 必须比 `horizon` 大 3~4 以上**，当前实现不支持 `step <= horizon`。<br>⑤ 用 rank label 时建议 `--adapt_y False`。<br>⑥ **显存不够时把 `step` 调小**：step=5 只要约 2GB，**而且性能更好**（step=20 只是为了和其它方法的耗时可比）。 |
| 已知风险 | ① 不在 `microsoft/qlib` 主仓，需要自己 merge fork 或单独 clone。<br>② 依赖 `higher` + 双层优化，训练慢、调参敏感。<br>③ 2024-12 后停更。 |

**判断：理论最优雅、工程最挑剔的一个。** 作者的 README 写得极其诚实（这在我调研的所有仓库里是罕见的），把这些"坑"都写明了对你是好事。**如果你要做"小步快跑式在线更新"（而不是每天全量重训），它是目前开源里设计最对路的方案。但请先从 step=5 小配置开始。**

### 3.3 RD-Agent / RD-Agent-Quant（微软，LLM 自动因子挖掘 + 模型优化）

| 项 | 内容 |
|---|---|
| 链接 | [microsoft/RD-Agent](https://github.com/microsoft/RD-Agent)（⭐ **14,582**，fork 1,903，MIT，**最新 push 2026-09-04，非常活跃**）<br>论文：[R&D-Agent-Quant, arXiv:2505.15155](https://arxiv.org/abs/2505.15155) |
| 一句话价值 | 微软官方在 qlib 主 README 里首推的方向，用 LLM agent 自动做**因子挖掘**和**模型优化**，且**直接接 Qlib**。 |
| 接入成本 | **中**。需要 LLM API（成本是主要变量），框架本身已在 Qlib 生态内。 |
| A股适配度 | 高（demo 就是 Qlib + A股）。 |
| 已知风险 | ① **LLM token 成本不可控**，跑一轮因子挖掘的 API 费用可能是你实验预算的主要项。<br>② 挖出来的因子需要你自己做多重检验校正/去幸存者偏差——LLM 生成 + 回测筛选是典型的多重比较陷阱。<br>③ 这是"因子生成"而不是"DL 模型"——它不解决你"DL 线空白"的问题，但可能是比 DL 更划算的投入方向（见 §3.3 旁证）。 |
| **⭐⭐ 唯一的第三方独立实测（这份报告彻底改变了我的推荐力度）** | **[国联民生证券《AGENT专题报告 RD-AGENT实测：AI驱动的因子挖掘框架》（叶尔乐，2026-05-20）](http://stock.finance.sina.com.cn/stock/go.php/vReport_Show/kind/strategy/rptid/832591048933/index.phtml)**<br>这是我在整个调研中找到的**唯一一份对 RD-Agent 的独立、可验证实测**（非微软自述）。设置：Wind A股 **5,792 只 / 165 字段**，财务数据全部按公告日 **PIT 对齐**；场景 `fin_factor`，**模型固定为 LightGBM**，新因子**与 Alpha158 的 158 个量特征合并**后送入（**这点极为关键，见下**）。<br>**正面**：完成 **36 个有效 Loop**，组合双周频 IC 提升至 **0.07**，触发 11 次 SOTA 更新；最终 SOTA 因子以交叉/交互、盈利质量、分析师预期、现金流四类为主；预估效率可达人工数十倍（约 900 个有效因子/月）。<br>**🔴 必须知道的四条负面**：<br>① **"组合 ICIR 的提升始终弱于 IC"**——即提升的是信号强度而非**稳定性**，而稳定性才是实盘要的东西。<br>② **"机器学习类因子在激进参数下过拟合明显"**。<br>③ **LLM 选择决定成败**：**GLM-V5.1 全面优于 DeepSeek-V3.2**（后者频繁陷入无限重复输出、行业截面因子**多个提案全部编码失败**）→ 报告结论：**"代码工程能力比单纯推理能力更关键"**。**这意味着"用便宜模型省钱"是假象。**<br>④ **作者定位**：RD-Agent 是**"具升级潜力的辅助因子研究工具"**，**"暂不能替代传统研究流程"**；明列劣势为运行稳定性差、LLM 代码质量不稳定、**IC 优化目标与实盘收益脱钩**、对 A股特殊机制与前视偏差把握不足。<br>**🔴 最致命的一条（风险提示原文）**：**"报告中得到的因子仅代表单次运行结果，不保证可再次按顺序挖到。"** → **可复现性结构性缺失**，无法纳入 CI/回归测试，也无法做严格的因子归因。<br>**⚠️ 一个容易被误读的数字**：那个"IC 提升至 0.07"是**与 Alpha158 合并后的双周组合 IC**，**不是新因子的独立 IC**。|

**旁证：东吴证券《深度学习系列之一：AI重塑量化，基于大语言模型驱动的因子改进与情绪Alpha挖掘》（2026-01-10，于明明）**（[摘要](http://dx.microbell.com/wap_detail.aspx?id=4976485)）——这份百页报告给出了 LLM+Prompt 做 A股因子的完整实证：
- 以 **Alpha158 为基础做"优化"**：AI 能识别原始因子逻辑缺陷并提出改进（如波动率因子 std20），在 5~60 日多个窗口下优化效果具备普适性。
- 从"优化"升级到"生成"：挖出多个与样例因子相关性低、**ICIR 0.8 以上**的新因子，部分**样本外 ICIR > 1.0**。
- 基本面维度：生成 CGP_TTM（现金毛利）、REP_LF（留存收益）、ART_QR（应收账款周转率）等增强/新颖因子。
- **高频维度**：给 AI 生成 Python 代码的能力，挖出的强信号因子（如投机波动因子）**多空组合年化收益超 60%**。
- **关键组合结果**：把 AI 高频因子库融入 **AGRU 神经网络（融合日K与周K行情）**后，**年化多头超额从 18.24% → 25.28%，RankIC 均值 +0.71pp**。
- 用 Gemini 2.5 Pro 解析近百万字调研纪要，双速动态衰减构建周度情绪因子：**非对称预测能力——正面情绪与上涨关系不强，但负面情绪是未来下跌的强预警信号，空头组合年化超额 8.26%**，且与传统量价/基本面因子相关性极低。
- 最终中证800 指增：年化超额 **11.15% → 11.81%**，IR **2.18 → 2.31**。
- **风险提示里作者自己写了**："大语言模型的输出具有随机性，同时可能存在模型幻觉问题，**导致报告结果无法复现**"。这句话很重要。

**判断：方向对、但请降级为"值得一试（谨慎）"。** 综合东吴的正面实证与国联民生的独立实测，我把 RD-Agent 的定位调整为：
- **它适合的**：**新数据源因子潜力的快速探索**、以及**现有因子库的增量补充**（这也是国联民生给出的建议）。你的瓶颈是"因子多样性/策略同质化"（国金报告的行业共识），这个方向是对的。
- **它不适合的**：**替代你的研究流程**，或作为**可复现的生产管线**（"仅代表单次运行结果，不保证可再次按顺序挖到"）。
- **实操建议**：① **不要用便宜模型**（GLM-V5.1 明显优于 DeepSeek-V3.2，弱模型的编码失败率会让你浪费更多钱）；② 把 RD-Agent 产出的因子当作**候选池**，必须经你自己的**多重检验校正 + 样本外 + PIT 校验**才能进生产；③ 关注 **ICIR 而不是 IC**——这是国联民生实测里最直接的教训。

### 3.4 AGRU 式改造（Attention-GRU + Memory + CVaR Loss）

| 项 | 内容 |
|---|---|
| 名称 | 不是某个仓库，而是 2026 年 A股卖方共识的 GRU 工程化改造配方 |
| 出处 | [国金证券 2025-12-30](https://stock.finance.sina.com.cn/stock/go.php/vReport_Show/kind/lastest/rptid/820428637580/index.phtml)、[广发证券 2026-09-01](https://stock.finance.sina.com.cn/stock/go.php/Report_Show/kind/11/rptid/841632221169/index.phtml)、[东吴证券 2026-01-10](http://dx.microbell.com/wap_detail.aspx?id=4976485) 三家独立给出同一配方 |
| 配方 | ① GRU 底座 + **Attention Pooling**（解决长序列信息利用率不足）<br>② **Memory 模块**（强制存储历史极端行情特征）<br>③ **CVaR Loss**（对尾部风险敏感）<br>④ 与日K/周K 多频率数据融合<br>⑤ LightGBM 侧：高质量样本加权 + **Huber Loss**（替代 MSE，对异常值不敏感） |
| 效果（国金口径） | GRU 最大回撤 → **8.54%**，Calmar → **3.02**；LightGBM 多头超额最大回撤 → **5.88%** |
| 效果（东吴口径） | AGRU + AI 高频因子：年化多头超额 **18.24% → 25.28%** |
| 接入成本 | **低–中。** 不需要新框架，就是在 Qlib 的 `pytorch_gru.py` 基础上改 poolong 层 + 加 memory + 换 loss。 |
| A股适配度 | 原生（就是 A股卖方做出来的）。 |
| 已知风险 | ① 卖方报告不提供代码，需要自己实现；② 效果数字来自各自回测，口径不统一、无法互相验证；③ 三家都强调这是"缓释"而非"解决"同质化。 |

**判断：这是"最小改动、最贴合 A股实务"的一条路。** 如果你只想动一件事来提升现有 GRU/LightGBM 的稳健性，改 loss（Huber / CVaR）+ 加 attention pooling 的性价比高于换任何新架构。

**⭐ 现在这条判断有控制变量实验支撑了**：[§1.4(0)](https://arxiv.org/abs/2510.14156) 在架构完全固定、只换 8 种损失函数的条件下，得到 **Sharpe 0.6637（MSE）→ 0.7529（Margin）**、**最大回撤 -19.58% → -15.77%（BPR）**，而 IC 几乎不动（0.0733–0.0767）。**且 MSE 基线的测试集 MSE 最低却是最差策略**——这正是"改 loss 比换架构划算"的量化证据。注意该实验是美股 110 只大盘股、有上述折扣，但方法论可直接迁移。

### 3.5 中信建投 TFT on Qlib Alpha360（一个被忽视的正例）

| 项 | 内容 |
|---|---|
| 出处 | [中信建投《"逐鹿"ALPHA专题报告(九)：基于 QLIB ALPHA360 的 Temporal Fusion Transformer 选股模型》（丁鲁明/王超，2022-05-24）](https://stock.finance.sina.com.cn/stock/go.php/vReport_Show/kind/11/rptid/706731927365/index.phtml) |
| 结论 | 用 Qlib Alpha360 中**表现更好的 20 个因子**作为输入，TFT 预测中证500 成分股次日收益，TopKdropN 回测。**TFT(50,1) 取得年化 19.57%、超额 15.57%、IR 1.74、换手率 4.6**，优于传统 ICIR 加权。 |
| 为什么值得注意 | 这是**罕见的、由券商独立完成的"Qlib Alpha360 + DL 跑赢因子加权基线"的公开记录**，独立于 Qlib 官方 benchmark，佐证了 §1.2 结论 A（DL 在原始序列表征上更有效）。 |
| 已知风险 | ① **2022 年的报告，不是 2025–2026 样本外**；② Qlib 官方的 TFT 实现依赖 `tensorflow==1.15.0`，**只支持 Python 3.6~3.7**（Qlib README 原文），**在你的环境里跑不了官方的 TFT**；③ 中证500 票池，与 CSI300 结论不能直接迁移。 |

**判断：作为"DL 在 Alpha360 上确实能超过因子加权"的旁证有价值；但 TFT 本身因为 TF1.15 依赖已经死了，不要为了它去搭 Python 3.7 环境。** 想复现这个思路，用主仓的 GRU/ALSTM/TRA 在 Alpha360 + 中证500 上跑即可。

---

## 4. 观望

### 4.1 Time-Series-Library（TSLib）系模型：iTransformer / PatchTST / TimesNet / TimeMixer / TimeMixer++ / ModernTCN

| 项 | 内容 |
|---|---|
| 链接 | [thuml/Time-Series-Library](https://github.com/thuml/Time-Series-Library)（⭐ **12,843**，MIT，最新 push 2026-04-18）<br>[thuml/iTransformer](https://github.com/thuml/iTransformer)（⭐ 2,212，ICLR 2024 Spotlight）<br>[kwuking/TimeMixer](https://github.com/kwuking/TimeMixer)（⭐ 1,983，ICLR 2024 TimeMixer） |
| ⚠️ **勘误 1：TSLib 已于 2026.04 官方宣布停止演进** | TSLib README 原文（News 2026.04）：**"Due to the limited bandwidth of the current maintainers, we will not be actively adding new features to this library. Since the library was originally released three years ago, many of its benchmarks may no longer be meaningful for evaluating the effectiveness or progress of current research. However, the baseline implementations remain correct. We therefore recommend seeking out newer benchmarks."**<br>**即维护者自己承认"很多 benchmark 可能已不再有意义"。** 我原先"维护良好"的说法是误导性的，特此更正。它仍可作为**代码库**用（baseline 实现是对的），但**不能当作"持续演进的 SOTA 模型库"来选型**。 |
| ⚠️ **勘误 2：TimeMixer++ 没有官方代码** | 我原报告说"官方实现就在 `kwuking/TimeMixer` 仓库内"，**这是错的**。我复核了该仓 README：TimeMixer++ 只在 News 里被**宣布**（指向 [arXiv:2410.16032](https://arxiv.org/abs/2410.16032)），**但 README 里没有任何 TimeMixer++ 的代码路径、脚本或文件夹**——所有 `scripts/` 和复现命令都是 TimeMixer (ICLR'24) 的。且 TimeMixer++ **未被 TSLib 收录**。<br>**结论：论文真实（ICLR 2025），但无官方可用代码。不要列入可落地候选。** |
| 一句话价值 | 通用时序预测的 SOTA 集合，工程质量和复现性都很好。 |
| **为什么只给"观望"** | **它们解决的是"单个序列的未来值预测"，不是"横截面上千只股票的排序"。** 这是一个任务范式的错配，不是质量问题：<br>① 训练目标：TSLib 用 MSE 预测数值，选股需要的是**截面排序**（应使用 IC loss 或 rank loss）。<br>② 归一化：TSLib 普遍用 instance norm / RevIN 做**逐序列**归一化，这会**抹掉横截面可比性**——而截面比较恰恰是选股的全部信息。<br>③ 评估：TSLib 报 MSE/MAE，而 [Heads, Not Backbones](https://ar5iv.labs.arxiv.org/html/2606.30037) 明确显示 **MAE/MSE 与盈利性脱钩**（"消费密度预测的朴素均值回复策略在每个变体上都亏钱"）。<br>④ [918 实验论文](https://ar5iv.labs.arxiv.org/html/2603.16886) 显示这些架构的**方向准确率与 50% 无法区分**。<br>⑤ 这些模型都是**单资产**的，天然不建模股票间关系。 |
| 但有一个真正的例外 | **[iTransformer](https://github.com/thuml/iTransformer) 的"倒置注意力"是把每个变量的整条时间轨迹作为一个 token，在变量维度做 attention。** 这个 inductive bias（"变量间关系是主要信息源"）在概念上**非常契合横截面选股**——把"变量"换成"股票"，就是横截面 attention。事实上 Qlib 的 GATs 做的正是这件事（见 §5.1）。<br>[TSFM 论文](https://ar5iv.labs.arxiv.org/html/2606.27100) 里也记录了一个反例：**在 META 的两个任务上，iTransformer 这个本地监督基线赢了全部 6 个预训练 TSFM。** |
| 已知风险 | ① 直接套用 TSLib 做选股 = 范式错配，大概率跑不过 LightGBM，然后你会得出"DL 没用"的错误结论。<br>② TSLib 的 DLinear/PatchTST 等强调的"线性模型能打平 Transformer"结论，是在通用时序数据集上得出的，**不能外推到选股**。 |

**判断：不要为了选股去接 TSLib。** 如果你要借鉴，只借鉴两件事：(a) iTransformer 的变量维 attention 思想（迁移成股票维 attention）；(b) ModernTCN 的大核深度卷积（[918 实验](https://ar5iv.labs.arxiv.org/html/2603.16886) 里它的平均排名第一，1.333，75% 夺冠率）。**其余当作通用时序工具箱，与选股无关。**

### 4.2 预训练时序基础模型（Chronos / TimesFM / Moirai / TimeGPT / Chronos-2 / Timer / Sundial）

| 项 | 内容 |
|---|---|
| 一句话价值 | 零样本/少样本预测，省去逐资产建模成本。 |
| 为什么观望 | [Pretrained TSFMs for Financial Return Forecasting (2026-08)](https://ar5iv.labs.arxiv.org/html/2606.27100) 是目前最严谨的金融场景评测，结论对你不利：<br>① 虽然 TSFM 在排名上占优（10 个任务赢 8 个），但**"相对随机游走的增益又小又稀疏"**；Diebold–Mariano 检验只在 2 个任务上拒绝了"等于或劣于随机游走"。<br>② **iTransformer 这个本地监督基线在 META 上两个任务全赢**。作者结论：TSFM 是"降低建模成本的先验"，**不是"可靠 alpha 生成或交易表现的通用引擎"**。<br>③ 该论文引用的同期工作指出：**现成 TSFM 在零样本和微调两种模式下都跑不过标准 ensemble 和神经网络基线**，只有"金融原生预训练"才能缩小差距。 |
| A股相关性 | 上述评测是**美股单资产**，不是 A股横截面。但目前**我没有找到任何 A股横截面 + TSFM 的可信实证**。 |
| **⭐ 最强的负面证据（比上面那篇更对症）** | **[Re(Visiting) Time Series Foundation Models in Finance](https://arxiv.org/abs/2511.18578)**（Rahimikia, Ni, Wang，2025-11-23，q-fin.CP）——**这是我找到的与你的问题最直接相关的一篇**。摘要原文：<br>*"This paper presents the **first comprehensive empirical study of TSFMs in global financial markets**. Using a large-scale dataset of **daily excess returns** across diverse markets, we evaluate zero-shot inference, fine-tuning, and pre-training from scratch against strong benchmark models. **We find that off-the-shelf pre-trained TSFMs perform poorly in zero-shot and fine-tuning settings**, whereas models **pre-trained from scratch on financial data achieve substantial forecasting and economic improvements**, underscoring the value of domain-specific adaptation."*<br>**三个要点**：① 评测对象是**横截面日频超额收益**（不是单资产价格），与选股任务同构；② **现成 TSFM 在零样本和微调两种模式下都不行**；③ **只有金融原生从零预训练才有效**。<br>这直接解释了本文的核心推荐逻辑：**Kronos 之所以值得推荐而通用 TSFM 不值得，正是因为它属于"金融原生预训练"这一类。** |
| 已知风险 | 用通用领域预训练模型做 A股选股，目前属于"没有证据支持"的投入。**Kronos 是唯一的例外**——因为它是**金融原生预训练**（45 个交易所的 K 线），且自带 Qlib A股管线。[Re(Visiting) TSFMs](https://arxiv.org/abs/2511.18578) 的结论给这个判断提供了直接支撑。<br>另需警惕**预训练数据污染**：有统计指出主流 TSFM 评测数据集中**仅约 6% 未被预训练见过**，"零样本超越"因此高度可疑。 |

### 4.3 FinGPT / FinRobot（AI4Finance）

| 项 | 内容 |
|---|---|
| 链接 | [AI4Finance-Foundation/FinGPT](https://github.com/AI4Finance-Foundation/FinGPT)（⭐ **21,237**，fork 3,009，MIT，**最新 push 2026-09-08，看起来活跃**）<br>[AI4Finance-Foundation/FinRobot](https://github.com/AI4Finance-Foundation/FinRobot)（⭐ 7,966，Apache-2.0，最新 push 2026-09-07） |
| 一句话价值 | 开源金融 LLM 与金融 agent 平台，含情感分析、财报解读等。 |
| 为什么观望 | ① **仓库活跃 ≠ 模型可用**：FinGPT 主要是 Jupyter Notebook 集合 + HuggingFace 权重，不是可复现的量化管线。star 数高但**缺少针对 A股横截面选股的端到端实证**。<br>② **与你的任务错配**：FinGPT 做的是金融文本理解/情感，输出的是文本标签，**要变成日频因子还差一整套工程**（对齐交易日、处理公告时点、防止未来信息泄漏）。<br>③ **在 A股上，东吴证券的路线更有参考价值**：不是用金融专用小模型，而是**用通用大模型（Gemini 2.5 Pro）+ Prompt Engineering** 去解析调研纪要，反而拿到了 8.26% 的空头年化超额。**通用大模型 + 好的 prompt/数据管道 > 金融专用小模型**，这是我目前的判断。<br>④ 该方向的通用风险见 §4.5。 |
| 已知风险 | ① 数据许可、基准挑选（benchmark cherry-picking）、可复现性质疑是该系列长期争议点。<br>② **"仓库活跃"具有欺骗性（实测）**：FinGPT 最近 12 条 commit 全是依赖修复（Triton 导入错误、`prepare_model_for_int8_training` 废弃、`offload_folder` KeyError 等）与 Docker 化；**README 的"What's New"停在 2023-11——模型发布线已停约 3 年**。（对比：[FinNLP](https://github.com/AI4Finance-Foundation/FinNLP) 已死，2024-07 后无提交。） |
| **🔴 关键辟谣：那个"A股因子"commit 是幌子** | 网上流传"FinGPT 已支持 A股因子"的说法，来源是 2026-09-08 的 [PR #274 "add A-share factor report evaluator"](https://github.com/AI4Finance-Foundation/FinGPT/pull/274)。**实测该 PR 的完整 diff：它只是一个 86 行的 JSON schema 校验脚本**——只检查 JSON 里 `symbol/factors/risks/recommendation/confidence` 字段全不全，打分公式是 `1.0 - min(len(errors),5)/5`。**不读行情、不算 IC、不回测、不接任何数据源。** 它自己的 docstring 都写明 *"intentionally does not claim that a recommendation is correct"*。**结论：FinGPT 并未支持 A股因子。** |
| **🔴 更根本的问题：架构层面就不适配横截面选股** | **FinGPT-Forecaster 官方 README 明确：训练于 DOW30（2022-12-30~2023-09-01），基座 Llama-2-7b LoRA，硬依赖 Finnhub（美股）API key。** 但比数据源更难修的是**架构**：它输出**自然语言点评**，且**一次只处理一个 ticker → 没有截面能力**，无法做横截面排序。**这不是换个数据源能解决的问题。** |
| **A股上唯一的正面证据（但封闭）** | [国金证券《Alpha掘金系列之八：沪深300另类舆情增强因子——FinGPT对金融论坛数据情感的精准识别》（高智威，2023-10-18）](https://m.163.com/dy/article/IHAVJKV305384CKJ.html)：FinGPT V3.1 = **ChatGLM-6B + LoRA**；数据来自**付费供应商**（1,300 万主帖 + 480 万评论，2018-01~2023-06）。结果：单因子 **IC 3.68%**、多空年化 12.71%；**但落地多头策略年化仅 6.69%、Sharpe 仅 0.32**。<br>**我的独立判读（研报未强调）**：Sharpe 0.32 vs 多空 12.71% 说明**信号主要在空头端，而 A股个人基本无法有效做空**；**因子与市值相关性 0.55 → 一半以上是小市值暴露的代理**，必须先市值中性化。<br>**结论：它证明了 LLM 情感因子在 A股有信号，没证明你能用开源 FinGPT 免费复制。** |

### 4.4 FinWorld（一体化金融 AI 平台，KDD 2026）

| 项 | 内容 |
|---|---|
| 链接 | [DVampire/FinWorld](https://github.com/DVampire/FinWorld) / [TradeMaster-NTU/FinWorld](https://github.com/TradeMaster-NTU/FinWorld)<br>论文：[arXiv:2508.02292](https://arxiv.org/abs/2508.02292)（KDD 2026） |
| 一句话价值 | 号称统一 ML/DL/RL/LLM/Agent 的一体化金融 AI 平台，**声明支持 AKShare、TuShare，覆盖 SSE50 与 HS300**。 |
| 为什么观望 | ① **README 顶部就是"Preview Version Notice"**："部分代码组件仍在更新中，可能无法在本仓库完整获取"。**现在还不是能用的状态。**<br>② 它**声称** "TimeXer 在 DJ30 上 MAE 0.0529 显著优于 LightGBM (MAE 0.1392)"、**"深度学习模型一致取得更高的 RankICIR"**——但给出的对比指标是 **MAE/MSE**，而 MAE/MSE 与选股收益脱钩（§4.1）。LightGBM 的 MAE 比 TimeXer 差 2.6 倍，这个差距大到**更像是 LightGBM 基线没有认真配置**，而不是架构差异。<br>③ 数据下载器以 FMP/Alpaca 为主，AKShare/TuShare 的支持深度未知。 |
| 判断 | 方向对（一体化、多模态、含 RL/LLM），但**现阶段是论文工程而非可用工具**。等它去掉 preview 标记再看。 |

### 4.5 ACT（Anti-Crosstalk Learning for Cross-Sectional Stock Ranking, 2026）

| 项 | 内容 |
|---|---|
| 链接 | [arXiv:2604.20204](https://ar5iv.labs.arxiv.org/html/2604.20204v1) |
| 一句话价值 | **少见的真正针对"横截面股票排序"设计的 2026 新模型**：把股票序列分解为 trend / fluctuation / shock 三分量，只让 trend 走多关系图（行业图 + 地域图 + 动态 kNN 图），fluctuation 和 shock 走隔离分支不做跨股传播；损失函数用 **IC loss + MSE loss** 组合。 |
| 报告效果 | CSI300 / CSI500，声称较 16 个基线 SOTA，"improvements of up to 74.25% on the CSI300 dataset"。检索到的指标片段：IC 0.0692 / ICIR 0.6955 / RankIC 0.0786 / RankICIR 0.7810 / AR 0.0877 / IR 0.8522。 |
| 为什么观望 | ① **我未能确认是否有开源代码**（arXiv 页面与检索结果里都没找到 GitHub 链接）→ 属于"论文强、开源弱"。<br>② "74.25% 提升" 的基线口径不明，**不能与 Qlib benchmark 的 IC 0.045 直接对比**（不同票池、不同标签、不同切分）。<br>③ 2026 年 4 月的新论文，**无独立复现**。 |
| 但值得记住 | 它的**核心 insight 对我们有价值**：*"crosstalk"——趋势分量是可跨股迁移的，波动和冲击分量是股票特有的，把三者混在一个表示里再做图传播会互相污染。* 这个设计直觉**和我从 Qlib benchmark 读出的结论是一致的**（Alpha360 上 DL 有效，是因为它让模型自己学分量；Alpha158 上无效，是因为人工因子已经把分量混好了）。**如果你要在 Qlib 里自己造模型，这个"分量隔离 + 只让可迁移分量过图"的思路值得借鉴。** |

### 4.6 RelationalStock / RSR（Temporal Relational Stock Ranking）—— 你问的那个，我找到了

| 项 | 内容 |
|---|---|
| 名称 | **RSR（Relational Stock Ranking）+ TGC（Temporal Graph Convolution）**——这应该就是你提到的 "RelationalStock" |
| 链接 | **代码：[fulifeng/Temporal_Relational_Stock_Ranking](https://github.com/fulifeng/Temporal_Relational_Stock_Ranking)**<br>论文：[Temporal Relational Ranking for Stock Prediction](https://arxiv.org/abs/1809.09441)，**ACM TOIS 2019**（Feng Fuli / He Xiangnan 等，NUS + 清华） |
| 一句话价值 | **"股票关系图 + 排序损失"这条技术路线的奠基工作之一**：用 Rank_LSTM 做时序编码，用 Temporal Graph Convolution 在**股票关系图**上传播，直接优化排序而非回归。 |
| 依赖 | **Python 3.6 + TensorFlow > 1.3**（README 原文） |
| 仓库元数据（实测） | ⭐ **527 star**，**最后提交 2021-03-04（停更 5.5 年）**，**AGPL-3.0**。另：**「RelationalStock」这个名字对应的仓库不存在**（多个命名变体均 404，元数据镜像查无此仓）——真实资产就是本仓库的 RSR 模型。README 内链指向 `hennande/...` 但该 URL 返回 fulifeng 页面，说明**是原作者改名，不是第三方复刻**。 |
| A股适配度 | ❌ **低。这是美股数据集，没有 A股版本。** |
| 数据构成（README 原文） | ① **Sequential Data**：Google Finance 30 年 EOD（OHLCV），**8000+ 只美股**<br>② **Industry Relation**：NASDAQ/NYSE 股票的**行业关系图**（`sector_industry/`，含 row relation 文件与 `.npy` 二进制编码）<br>③ **Wiki Relation**：来自 **Wikidata** 的**公司间关系图**（`wikidata/`）——这是它最独特的地方 |
| 已知风险 | ① **技术栈已死**：TF 1.x + Python 3.6，**与你的 torch 2.6 环境完全不兼容**，且 TF1 官方早已停止支持。<br>② **2019 年的工作，未维护**（仓库最后活动远早于 2025）。<br>③ **无 A股数据、无 A股关系图**。<br>④ 预训练 sequential embedding 托管在 Google Drive，国内访问不便。 |
| **但方法论值得偷（这是重点）** | 它的**架构思路对 A股完全适用**，只是需要你替换两样东西：<br>**(a) 关系图数据**：A股的关系图其实**比美股好拿**——`tushare` 直接提供申万/中信**行业分类**，一张行业关系图基本免费；产业链/供应链图才是难的部分（这是国内 GNN 选股真正的门槛）。<br>**(b) 排序损失**：它用 ranking loss 而非 MSE，这与 [ACT](https://ar5iv.labs.arxiv.org/html/2604.20204v1)（IC loss）、[Heads, Not Backbones](https://ar5iv.labs.arxiv.org/html/2606.30037)（输出头比 backbone 重要）的结论方向一致：**选股是排序任务，损失函数必须对排序敏感。** 广发金工也提过同样建议（借鉴推荐系统的 LTR 排序损失）。 |

**判断：代码不要用，思想一定要用。** 具体来说——如果你将来要做 GNN 选股，**最小可行路径是把 tushare 的行业分类做成邻接矩阵，然后套在 Qlib 主仓的 HIST（它就是"概念关系图"的官方实现，Alpha360 上 IC 0.0522 / IR 1.373，官方表里最强）上做改造**，而不是去移植这个 2019 年的 TF1 仓库。

### 4.7 GNN / 股票关系建模（含 Qlib GATs 的真相）

**先说一个我从源码验证出来的重要事实（这会改变你对 Qlib GATs 的理解）：**

我读了 [`qlib/contrib/model/pytorch_gats.py`](https://github.com/microsoft/qlib/blob/main/qlib/contrib/model/pytorch_gats.py)。在 `GATModel.cal_attention` 里，注意力的计算方式是把**当天 batch 内的所有股票**作为节点、两两计算 attention，再 `att_weight.mm(hidden) + hidden`：

```python
sample_num = x.shape[0]          # ← 当天截面里的股票数
e_x = x.expand(sample_num, sample_num, dim)
...
att_weight = self.softmax(attention_out)
hidden = att_weight.mm(hidden) + hidden
```

**所以：Qlib 的 "GATs" 不是一个基于行业/产业链先验图的 GNN，而是一个"对当日截面内所有股票做全连接注意力"的模型。** 这意味着：

1. **好消息**：它确实在做横截面信息交互（这正是选股需要的东西），所以它在 Alpha360 上有不错的表现（IC 0.0476 / 年化 8.24% / IR 1.108）。
2. **坏消息（坑）**：
   - **官方 README 自己承认了**——[`examples/benchmarks/GATs/README.md`](https://github.com/microsoft/qlib/blob/main/examples/benchmarks/GATs/README.md) 原文：*"GATs leverage masked self-attentional layers on graph-structured data... **without requiring any kind of costly matrix operation (such as inversion) or depending on knowing the graph structure upfront**."* **"不依赖预先知道图结构"是它的设计声明，不是缺陷**——但也正因如此，它学到的注意力**不可跨日复用、没有语义**。
   - **显存墙（我按代码估算）**：`attention_in` 是 `[N², 2·hidden]` 的 float32。**N=300 → 约 0.05GB；N=3,000 → 约 4.6GB；N=5,000（全 A）→ 约 12.8GB，必然 OOM。** Qlib 没有 top-k 稀疏化或分块选项 → **GATs 无法扩展到全 A 股**。
   - **没有关系先验**：它不知道哪两只股票同行业、同产业链，全靠数据学。
   - **它要求你先训练一个 GRU/LSTM 底座**（`base_model="GRU"` + 必须提供 `model_path` 加载 pretrained checkpoint），不是端到端可训的。
   - 代码里 `pretrained_model = GRUModel()` 用的是默认参数（`d_feat=6`），**当你的特征维度不是 6 时，加载 checkpoint 会很脆弱**。
   - 性能只是中游：Alpha158 上 GATs IC 0.0349 / 年化 4.97%，**不如 XGBoost（0.0498 / 7.80%）**。

**⭐ 更重要的验证：这批"股票关系图"到底能不能产生 alpha？2026 年有一份罕见的诚实负面结果。**

[中金公司《基本面量化系列（30）：如何利用关联图谱信息进行选股？》（2026-08-06 发布，古翔/周萧潇/曹钰婕/刘均伟）](https://finance.sina.cn/2026-08-11/detail-inimwyqr0745269.d.html)——数据源 Wind + 朝阳永续，回测 2017-01 ~ 2026-06。**中金在这份报告里把负面结果写得很直白**：

- **原始关联收益因子基本没有 alpha**：SC 加权关联收益 RankIC **-0.55%**、主题网络关联收益 RankIC **0.03%**（RankICIR 分别是 -0.034 和 0.003）。多空月均收益 0.89% / 0.92%，**Newey-West t 值仅 1.64 / 1.59 → 统计上不显著**，且分组收益非严格单调。
- **中金原文："分析师共同覆盖关联动量因子 IC 并不高"**、"未经信息筛选的关联股票收益尚未形成稳定、单调的全截面预测关系"。
- **它最终的结论是：原始关联收益"主要作用不是直接贡献正向收益，而是在后续复合因子中作为负向控制项"**——即**图传播本身是噪声，它的价值是当反向过滤器**。
- 真正有效的是**基本面惊喜**（研报标题正向惊喜 / 评级上调 / 盈利预测上修）在网络上的扩散，而不是股价联动。加入后 Top10 年化净收益 12.90% → 22.80%，Sharpe 0.61 → 0.92；RankIC 2.36% / RankICIR 0.389；**持仓越分散增量越小**（Top50 增量仅 +0.35pp）。
- ⚠️ **但请注意我读出的两个问题**：① **Top10 最大回撤仍高达 -40.31% / -39.51%**；② 月均 L1 换手约 **173%**、与上月持仓重合率仅约 **14%**；③ "年化 22.80%" 高度依赖 2024–2026 的增量（+9.59 / +58.44 / +24.64 pp，2026 年仅半年），**单年贡献极大**。

**旁证（华泰）**：华泰 AI58（2022-07-07）对比 GAT 与全连接网络，**RankIC 仅从 6.87% 提升到 7.29%（+0.42pp）**，IC_IR 0.46→0.55 —— **图结构的真实增量很小**；且作者自述"测试股票池仅包含有分析师覆盖的 A 股，结论不能推广到全 A"。

**这解释了为什么"Qlib GATs"和文献里的"GNN 选股模型"完全不是一回事。** 真正的股票关系图模型（HIST 的真实概念图、IGMTF 的数据驱动图、ACT 的行业/地域图、供应链图）需要在 Qlib 之外自己搭。

**判断**：
- 如果你要**真正的**关系图建模，**先用 HIST**（Qlib 主仓自带，Alpha360 上 IC 0.0522 / IR 1.373，是官方表里最好的模型，且**它下载的是真实的股票×概念二分图**，见 §2.2）。IGMTF（数据驱动 top-k 稀疏图，更可扩展）次之。
- ⚠️ **但请把期望值压低**：中金与华泰两份独立证据都指向"**图结构本身带来的增量很小**"，中金甚至发现原始关联收益的 IC 接近零。**你从图模型上能期待的是小幅增量（RankIC 量级 +0.4pp ~ +1pp），不是质变。**
- 自己接外部 GNN 图数据（行业分类、供应链）是一条**长周期、高不确定**的路。**当前不建议作为第一优先级。**
- **但如果你要做，A股的关系图数据比美股好拿**：Tushare [`index_member_all`](https://tushare.pro/document/2?doc_id=335) 含 `in_date`/`out_date`/`is_new` → **真正的 point-in-time 申万行业成分**，积分门槛低，**这是所有 A股图项目的正确起点**（我 §4.6 说的"tushare 提供行业分类"具体就是这个接口）。产业链图唯一免费开源集是 [liuhuanyong/ChainKnowledgeGraph](https://github.com/liuhuanyong/ChainKnowledgeGraph)，但**作者自己列了三条致命局限：产业链主观性、静态快照（回测有前视偏差）、缺定量权重（无法做加权传播）**。

---

### 4.8 文本 / 舆情 / LLM 情感因子：⭐ 一个必须知道的符号反转 + 一个法律风险

**（1）⭐ 最重要的一条领域知识：A股舆情因子的 IC 符号大概是负的。**

开源证券 × 通联数据实测（[投资界报道](https://news.pedaily.cn/20210716/19358.shtml)）：**双周频多空年化 12.00% / 年化 ICIR = −2.30**；月频 11.92% / **ICIR = −2.00** —— **靠反号才拿到正收益**。

学术印证：JPM 2023 "Media Reinforcement Effect"（331 个网站 / 1,500 万篇新闻）——**新闻情绪应用于"增强反转"而非动量**：做多"前期低收益 + 低情绪"组合年化 8.38%，而标准反转组合 −0.53%。

**→ 结论：「利好新闻 → 买入」在 A股是错的。** 如果你要接舆情/LLM 情感线，**先假设符号是负的**，让数据告诉你方向，不要预设"正面情绪=看多"。这与东吴 2026 的发现一致（**正面情绪与上涨关系不强，负面情绪才是强空头信号**，见 §3.3 旁证）。

**（2）数据可得性的硬约束（决定你的架构）**

- **Tushare 没有任何情感打分接口**——"大模型语料"整栏全是原文；其自研因子库 202 个因子里**一个舆情因子都没有**。
- **AkShare 没有股吧帖子、没有任何情感接口**，且**新闻类接口全是"最近 N 条"滚动窗口、无历史归档**（`stock_news_em` 仅最近 100 条）。
- **⚠️ 这条决定架构：你今天不落盘，明天的历史就永远拿不到。** 如果要做文本因子，**第一步就得建 append-only 的原始文本归档（含内容 hash），而不是先做模型。**

**（3）⚠️ 法律风险（不是危言耸听）**

`robots.txt: Allow: /` **不是法律许可**。[福建高院 2025 年判例](https://iprchn.com/cipnews/news_content.aspx?newsId=144569)（腾讯诉"战鹰"舆情平台）**判赔 228 万余元**，说理是"robots 协议针对搜索引擎，被告使用场景不属于搜索引擎……造成实质性替代"。实测：东财 `Allow: /`、股吧无 robots、**雪球明文禁止 AI 训练/RAG/归档数据集**。

**→ 我的建议：股吧/雪球爬虫不做。** 免费替代路径是先验证信号是否存在（零成本、1–2 天）：用 AkShare 的**关注度类时序**接口（`stock_comment_detail_scrd_focus_em`、`stock_hot_rank_detail_em`、`stock_comment_detail_scrd_desire_em`）搭代理因子跑通 Qlib 全流程——**如果这一步都跑不出 IC，加 LLM 也救不回来。**

**（4）更推荐的方向：公告事件因子（而不是舆情）**

公告**结构化、有法定发布时间（PIT 安全）、免费/低价、无法律风险、历史完整**。"减持/增持/回购/诉讼/问询函/业绩预告修正/解禁"本身就是强因子，**规则 + 小模型即可，不需要 LLM**。巨潮 [`hisAnnouncement/query`](http://www.cninfo.com.cn/new/hisAnnouncement/query) 已实测返回规整 JSON（`announcementTime` 为 epoch 毫秒，`adjunctUrl` 拼 `static.cninfo.com.cn` 前缀得 PDF）。

**（5）必踩的三个陷阱**

① **`date` vs `pub_time`**：实测某接口 `trade_date=20250212` 而 `pub_time=2025-02-12 21:46:32`——**当天晚上，A股已收盘，按 `trade_date` 对齐就是未来函数**。
② **免费源会回填/修订** → 必须 append-only 落盘 + 内容 hash。
③ **覆盖率陷阱**：即使付费的通联数据，日均也只约 1,600 只有舆情；**"无新闻"应记 NaN 而非 0**；且**不要把"关注度/热度"和"情感"混成一个因子**。

**（6）情感模型的选型（如果一定要做）**

**情感三分类是 BERT 的活，用 7B/70B LLM 是浪费钱且更不稳定。** 可用的中文金融底座：[Langboat/mengzi-bert-base-fin](https://huggingface.co/Langboat/mengzi-bert-base-fin)（20G 金融语料领域自适应，**正确用法是拿它微调而非直接打分**）、[yiyanghkust/finbert-tone-chinese](https://huggingface.co/yiyanghkust/finbert-tone-chinese)、[bardsai/finance-sentiment-zh-base](https://huggingface.co/bardsai/finance-sentiment-zh-base)（注意：训练集是 Financial PhraseBank 机器翻译版，自报 0.973 **不能外推**）。
**→ 模型不是瓶颈，"文本 → 分数 → 因子"中间那一层才是。**

**（7）⭐ 一个容易忽略但很关键的 Qlib 坑**

**Qlib 内置的 `csi300` / `csi500` 是"当前"成分股，不是历史成分。** 直接用它们做长周期回测会引入**幸存者偏差**。必须换成 **PIT 历史成分**（例如用 Tushare 的 [`index_member_all`](https://tushare.pro/document/2?doc_id=335)，含 `in_date`/`out_date`），或自建 PIT 票池。**这条对所有模型都适用，不只是文本因子。**

---

## 5. 不推荐

### 5.1 ❌ 在 Alpha158（人工因子表）上堆深度学习模型

**理由**：§1.1 的官方数据显示，Alpha158 上**没有任何 DL 模型超过 LightGBM 的 IC**。你已经在这条路上，继续投入是负回报。
**唯一例外**：TRA 在 Alpha158 上的 IR 是 1.084，略高于 LightGBM 的 1.016，且 MaxDD 更好（-7.6% vs -10.4%）——如果你特别在意回撤，可以试 TRA 做**集成的一员**，但不要作为主力替换。

### 5.2 ❌ KRNN 和 Sandwich（Qlib 内置，但实测崩溃）

**官方数据**：KRNN IC 0.0173 / 年化 **-4.65%** / MaxDD **-29.2%**；Sandwich IC 0.0258 / 年化 0.05% / MaxDD -17.5%。

**我读了 [`pytorch_krnn.py`](https://github.com/microsoft/qlib/blob/main/qlib/contrib/model/pytorch_krnn.py) 源码，问题可定位**：

```python
def train_epoch(self, x_train, y_train):
    ...
    indices = np.arange(len(x_train_values))
    np.random.shuffle(indices)                      # ← 跨所有日期随机打乱
    for i in range(len(indices))[:: self.batch_size]:   # ← batch_size=2000
        ...
```

**它把整个训练集随机打乱后按 2000 条切 batch，完全破坏了"同一天的股票构成一个截面"这个结构**——而横截面排序任务的全部信息就在这个结构里。对比同仓库的 GATs，它老老实实用了 `get_daily_inter()` 按日切分。此外：
- `predict()` 用 `data_key=DataHandlerLP.DK_I`，而 `fit()` 用 `DK_L`，**推理和训练用了不同的数据键**。
- `KRNNModel.forward` 把展平后的特征当成序列（`x.view(x.shape[0], -1, self.input_dim)` 后取 `encode[:, -1, :]`），语义可疑。

**判断：KRNN 不是"效果不好"，是实现有结构性缺陷。Sandwich 大概率有同类问题。这两个直接从候选列表里划掉。**

### 5.3 ❌ 直接 `pip install` 官方 MASTER 仓库（环境冲突）

官方要求 `torch==1.11.0` + `pandas==1.5.3`，你是 torch 2.6.0 + pandas 2.3.3。硬装会污染你现有的 Qlib 环境。若要试，**必须在独立 venv 里**（`run_all_model.py` 就是这么做的），且做好自己升版调试的准备。

### 5.4 ❌ Qlib 官方 TFT（依赖死亡）——但注意 TFT 架构本身没死

Qlib README 原文：**"TFT only supports Python 3.6~3.7 due to the limitation of `tensorflow==1.15.0`"**。为了一个模型把环境降级到 Python 3.7 不值得。

**重要补充**：**TSLib 现在提供了 PyTorch 版的 TFT 实现**（[`models/TemporalFusionTransformer.py`](https://github.com/thuml/Time-Series-Library/blob/main/models/TemporalFusionTransformer.py)），所以**死的是 Qlib 的 TF1.15 实现，不是 TFT 这个架构**。如果你想复现中信建投那个"Alpha360 + TFT"的思路，**用 TSLib 的 PyTorch TFT 即可，不需要降级 Python**。这是我原报告遗漏的一条实用信息。

---

## 6. 两类任务的性价比判断（你问的"月频基本面 vs 日频价量"）

### 6.1 日频价量：**DL 有明确的用武之地，推荐做**

| 维度 | 判断 |
|---|---|
| 数据量 | 日频 A股：~5000 股 × ~5000 交易日 ≈ 2500 万样本行，**足以训练 100M 级以下的模型**（Kronos-small 才 24.7M）。 |
| DL 优势区间 | **原始量价序列（Alpha360 类）**。官方数据：HIST/IGMTF/TRA 全面超 LightGBM。 |
| 性价比 | **中高**。收益：IC +20~30%、年化 +70~75%、IR +80%（vs LightGBM on Alpha360）。成本：需要 GPU、需要多 seed、训练时间是 LGBM 的 10–100 倍。 |
| 最大的坑 | **不要把 DL 的输出直接替换 LGBM 的输出**。正确做法是**集成**（DL 因子 + GBDT 因子等权/IC 加权，或 DL 预测作为 GBDT 的一个特征）。官方表里 DoubleEnsemble（LGBM 集成）在 Alpha158 上碾压所有单模型，就是这个道理。 |
| 2025 年的现实 | 国金报告：**2025 年 8–9 月 AI 指增策略在风格漂移期跑输传统策略**。所以日频 DL 必须配**漂移适应机制**（DDG-DA / DoubleAdapt）和**外围风控**，否则会在突变市中失效。 |

### 6.2 月频基本面：**DL 的性价比低，不推荐把 DL 当主力**

| 维度 | 判断 |
|---|---|
| 数据量 | 月频基本面面板：~5000 股 × ~200 个月 ≈ 100 万行，**但独立的时间点只有 ~200 个**。在时序维度上样本量极小，**DL 极易过拟合到 200 个宏观状态上**。 |
| DL 的天敌 | 基本面因子的信噪比极低、因子数量少（几十个）、经济含义明确。**这种场景下，因子的经济逻辑 > 表示学习能力。** GBDT + 线性模型 + 因子正交化更稳。 |
| 那基本面这条线怎么做？ | **不要让 DL 去拟合基本面面板，让 LLM 去"生成"基本面因子。** 东吴证券 2026-01 实证：AI 生成的 CGP_TTM（现金毛利）、REP_LF（留存收益）、ART_QR（应收账款周转率）等基本面因子，部分**样本外 ICIR > 1.0**。这是"AI 用于基本面"的正确姿势——**生成器，不是拟合器**。 |
| 补一个被低估的方向 | **文本/另类数据**。东吴用 Gemini 2.5 Pro 解析近百万字调研纪要做的周度情绪因子：**非对称预测能力**——正面情绪与上涨关系不强，**负面情绪是未来下跌的强预警信号，空头组合年化超额 8.26%**，且与传统量价/基本面因子相关性极低。**对 A股来说，"负面情绪的空头信号"可能比"正面情绪的多头信号"更值钱**（受涨跌停和融券约束影响）。 |
| 性价比排序 | 月频这条线上：**LLM 因子生成 + 文本情绪因子 > GBDT 因子合成 > DL 端到端拟合**。 |

### 6.3 一句话总结

> **日频价量：值得上 DL，但要上在"表征学习"层（原始序列）+ "漂移适应"层（元学习），而不是"最终打分器"层。**
> **月频基本面：不要上 DL 拟合，要上 LLM 生成因子。**

---

## 7. Qlib DL 的七个坑（实战清单）

| # | 坑 | 具体表现 | 规避方法 |
|---|---|---|---|
| 1 | **数据源已失效** | Qlib README：**"Due to more restrict data security policy. The official dataset is disabled temporarily."** 官方数据下载已停。 | 用社区众包数据 [chenditc/investment_data](https://github.com/chenditc/investment_data)（⭐ 1,454，**最新 push 2026-09-11，维护活跃**）：<br>`wget https://github.com/chenditc/investment_data/releases/latest/download/qlib_bin.tar.gz`<br>**注意 DDG-DA/DoubleAdapt 必须用众包数据**，Yahoo 口径缺 VWAP 会导致 DDG-DA 下层优化无解（秩亏）。你已有 tushare，也可自建 bin。 |
| 2 | **batch 必须按"日截面"切** | KRNN 就是踩了这个坑（§5.2）。横截面任务的信息全在"同一天"这个结构里，跨日随机打乱 = 毁掉任务。 | 参考 GATs 的 `get_daily_inter()` 实现。**自己写模型时，第一个要检查的就是 batch 语义。** |
| 3 | **部分模型需要预训练底座** | HIST / IGMTF / GATs 都要先训一个 GRU/LSTM 并加载 checkpoint（`base_model` + `model_path`）。 | 先跑 `qrun benchmarks/GRU/workflow_config_gru_Alpha360.yaml` 产出 checkpoint，再喂给 HIST/IGMTF/GATs。 |
| 4 | **pandas 1.5→2.0 破坏性变更** | Qlib README 专门列了 "Break change"：`groupby` 的 `group_key` 默认值从"无默认"变为 `True`，Qlib 设成 `False`，但**不保证所有程序都正确**，点名了三个受害者：`rl_order_execution/scripts/gen_training_orders.py`、**`benchmarks/TRA/src/dataset.MTSDatasetH.py`**、`benchmarks/TFT/tft.py`。 | 你在 pandas 2.3.3 上跑 TRA 时留意这个。 |
| 5 | **DL 的方差比 GBDT 大一个数量级** | 官方表：GBDT 的 std 是 0.00（确定性），DL 的年化收益 std 是 0.02–0.05。**单次运行无法区分模型好坏。** | 用官方脚本 `python run_all_model.py run 20 <model> <dataset>` 跑 20 次取 mean±std。**少于 5 次不要下结论。** |
| 6 | **训练慢 / 显存** | 官方 README 自承："We have very limited resources to implement and finetune the models." DoubleAdapt 在 CSI500 + step=20 时需 ~8GB RAM + 10GB 显存。GATs 是 O(N²) 截面注意力。 | ① **用 `_ts.py` 变体**（配合 `TSDatasetH`）而不是 `DatasetH` 版本，减少内存；② 减小 `hidden_size`/`num_layers`，靠 `early_stop` 收敛；③ DoubleAdapt 用 step=5（2GB 且**性能更好**）；④ **不要在全 A 上跑 GATs**，从 CSI300 开始。 |
| 7 | **标签处理决定成败** | MASTER 作者特别强调他们实现了 `DropExtremeLabel`（训练时丢弃 5% 极端标签）+ `CSZscoreNorm`，而 Qlib 框架默认**没有**这两个，他们是"clumsily"（作者原话）加在 `base_model.py` 里的。 | 训练时：DropNA → **DropExtreme(5%)** → CSZscoreNorm；推理时：**对所有股票预测**（不要用训练 processor）。这是 MASTER 论文复现的关键细节。另注意 Qlib 有 `CSRankNorm`（排序标签）和 `CSZscoreNorm`（标准化标签）两种，DoubleAdapt 作者建议用 rank label 时设 `--adapt_y False`。 |

---

## 8. 如果你现在只有 Qlib + LightGBM：最小代价的接入路径

> 设计原则：**每一步都能独立产出可比较的结果，任何一步失败都不影响已有的 LightGBM 生产基线。**

### 第 0 步（半天）：把地基打对
1. **数据源**：切换到 [chenditc/investment_data](https://github.com/chenditc/investment_data) 众包数据（官方源已停）。用你的 tushare 权限做交叉校验。
   ```bash
   wget https://github.com/chenditc/investment_data/releases/latest/download/qlib_bin.tar.gz
   mkdir -p ~/.qlib/qlib_data/cn_data
   tar -zxvf qlib_bin.tar.gz -C ~/.qlib/qlib_data/cn_data --strip-components=1
   ```
2. **冻结一个可复现的 LightGBM 基线**：跑 `Alpha158` 和 **`Alpha360`** 两个版本，各 5 seeds，记录 IC / ICIR / RankIC / 年化超额 / IR / MaxDD / 换手。**这是你后面所有对比的锚。** 用 `python run_all_model.py run 5 lightgbm Alpha360`。
3. 环境隔离：为 DL 模型单独建 venv（官方 `run_all_model.py` 就是这机制），避免污染你的主环境。

### 第 1 步（1 天）：用最低成本建立 DL 工程认知
```bash
python run_all_model.py run 3 gru      Alpha360
python run_all_model.py run 3 alstm    Alpha360
```
**目的不是拿收益，而是走通"数据 → TSDatasetH → 训练 → 预测 → 回测 → 分析"的全链路**，同时亲眼看一遍 DL 的 seed 方差有多大（这比任何文章都有说服力）。
**这一步的验收标准**：你能解释清楚为什么 GRU 在 Alpha360 上 IC 0.0493 而 LightGBM 只有 0.0400。

### 第 2 步（2–3 天）：把真正有效的 DL 模型跑在对的数据集上
```bash
python run_all_model.py run 5 hist   Alpha360   # 官方表里最强
python run_all_model.py run 5 igmtf  Alpha360
python run_all_model.py run 5 tra    Alpha360
python run_all_model.py run 5 gats   Alpha360   # 注意要先有 GRU checkpoint
```
**对比口径必须与第 0 步的 `lightgbm Alpha360` 完全一致。**
**决策点**：如果 DL 的 IC 提升在你的数据/时段上不复现（完全可能，官方 benchmark 时段偏早），**就停在这里，不要再投入 DL**——这个结论本身价值很高，帮你省下几个月。

### 第 3 步（约 1 周）：做 ROI 最高的一件事——加漂移适应 ⭐
```bash
# DDG-DA 在 microsoft/qlib 主仓，直接可用
cd examples/benchmarks_dynamic/DDG-DA
# 参照 README 跑 RR[LightGBM] 与 DDG-DA[LightGBM] 的对照
```
**为什么这是 ROI 最高的**：官方数据显示在同一个 LightGBM 底座上 **IR 1.32 → 2.01**，年化 7.71% → 12.61%。而且它直接对症国金报告指出的"AI 策略对历史路径依赖过强、无法适应风格漂移"这个行业级痛点。
**验收标准**：在你自己的 2023–2026 样本外区间上，DDG-DA[LightGBM] 的 IR 是否高于 RR[LightGBM]。

### 第 4 步（约 1 周）：⭐ 改 loss 和评估口径 —— **优先级已上调至模型引入之前**
**这一步现在是全篇优先级最高的动作之一**，因为 [§1.4(0)](https://arxiv.org/abs/2510.14156) 的控制变量实验证明：**架构固定、只换损失函数**，Sharpe 0.6637→0.7529、最大回撤 -19.58%→-15.77%；而 **MSE 基线的测试集 MSE 最低却是最差策略**——意味着**你现在用 MSE/MAE 挑模型，很可能一直在挑错**。

具体动作：
- **A. 换掉 MSE/MAE 目标**（成本零）：
  - LightGBM：损失函数换 **Huber Loss**（对异常值不敏感）+ 高质量样本加权 → 国金报告多头超额最大回撤压到 5.88%
  - GRU/DL：引入**排序损失**。论文里 **Margin**（Sharpe 最优 0.7529）、**BPR**（回撤最优 -15.77%）、**ListNet**（年化 16.00%）表现最好；Qlib 也有现成的 IC loss 思路可参考（[ACT](https://ar5iv.labs.arxiv.org/html/2604.20204v1) 用 IC loss + MSE 组合）
  - 若要用 CVaR 控尾部风险：国金 GRU 加 **CVaR Loss** 后最大回撤 8.54%、Calmar 3.02
- **B. 换掉评估口径**（成本零，见 [STRATA](https://arxiv.org/abs/2608.28060)）：
  - **风格残差化**：算 IC/RankIC 前，先把预测值对市值、行业、波动率、动量做截面回归取残差
  - **首个可成交价计价**：标签和成交价都用次日 VWAP 或次日开盘后 N 分钟均价，而不是 close-to-close
- **C. 停止用 MSE/MAE 挑模型**，改用 RankIC + 多头超额 + 最大回撤 + 换手。

> 这四步（A/B/C）加起来是**零模型成本、零数据成本、零 GPU 成本**，却可能比你接任何一个新 DL 模型带来的改进都大。**建议先做完这一步，再考虑第 5、6 步。**

### 第 5 步（持续）：做集成，不做替换 ⭐
- **不要用 DL 替换 LightGBM**。把 DL 的预测值作为一个**新因子**喂给你的 LightGBM，或做等权/IC 加权集成。
- 依据：官方表里 **DoubleEnsemble（LGBM 集成）在 Alpha158 上 IC 0.0521 / 年化 11.58%，碾压所有单模型（含 LightGBM 自己）**。
- 这也是对抗国金报告"策略同质化"的正解：**相关性低的多个信号源，比一个更强的单信号源更有价值**（广发 2026：两套状态模型多头超额相关性仅 48%）。

### 第 6 步（可选，2–4 周）：Kronos 基础模型线
只有在第 2–5 步都跑通、且你确实想探索基础模型方向时再做：
```bash
git clone https://github.com/shiyu-coder/Kronos
pip install -r requirements.txt && pip install pyqlib
# 改 finetune/config.py 里的 qlib_data_path / dataset_path / save_path
python finetune/qlib_data_preprocess.py
torchrun --standalone --nproc_per_node=1 finetune/train_tokenizer.py
torchrun --standalone --nproc_per_node=1 finetune/train_predictor.py
python finetune/qlib_test.py --device cuda:0
```
**关键提醒（来自中金 2025-10 实测）**：标准版 Kronos 在 A股是**均值回复逻辑**，在 2025 年 7 月之后的趋势行情里系统性踏空。**必须做参数微调 + 滚动搜参（T / top_p / lookback_window 月度网格搜索）**，中金用这个方法把 5 日预测 Spearman 从 0.732 提到 0.856。

### 贯穿全程的四条纪律
1. **多 seed**。DL 的 std 是 0.02–0.05（年化收益），单次运行毫无意义。
2. **评估看 RankIC + 多头超额 + 换手 + 最大回撤**，不要看 MSE/MAE。IC 是信号质量，多头超额和回撤才是你能不能赚钱。（[Heads, Not Backbones](https://ar5iv.labs.arxiv.org/html/2606.30037) 明确显示 MSE 与盈利性脱钩。）
3. **⭐ 强制风格残差化 + 强制用首个可成交价计价**（来自 [STRATA](https://arxiv.org/abs/2608.28060)，见 §1.4）。**不做这两步，你所有的模型对比结论都不可信**——你比的可能是谁更会偷风格暴露、谁更会用不可成交的价格。这是本文最便宜、收益最大的一条建议。
4. **每年/每季度做一次样本外滚动复核**。国金报告的教训：2025 年 8–9 月的风格漂移让所有依赖历史路径的模型同时失效。

---

## 9. 我未能验证 / 证据不足的事项（请勿当作结论）

1. **MASTER、DoubleAdapt、HIST、IGMTF 在 A股的真实样本外表现**——我引用的是论文和 Qlib 官方 benchmark，**时段偏早（约 2008–2020）**，没有找到 2023–2026 的独立第三方复现。
2. **[Foundation models do not beat simple volatility benchmarks: Evidence from 5000 Chinese stocks](https://www.sciencedirect.com/science/article/abs/pii/S1544612326011347)**（Finance Research Letters）——**只能确认标题、期刊和"约5000只中国股票"这个范围，正文被 ScienceDirect 403 拦截，摘要也未在其它渠道找到。**<br>⚠️ **重要限定（我原先的表述需要收窄）**：从标题看，**这篇论文的主题是"波动率预测（volatility）"，不是收益预测/横截面选股**。因此它对"DL 能不能选股"这个问题只是**间接的、方向性的**反调，**不能作为"基础模型在 A股选股上无效"的证据**。真正对该问题给出直接证据的是 [Re(Visiting) TSFMs in Finance](https://arxiv.org/abs/2511.18578)（§4.2）和 [STRATA](https://arxiv.org/abs/2608.28060)（§1.4）。
3. **ACT（arXiv:2604.20204）是否开源**——我没有找到代码仓库。其"提升 74.25%"的基线口径也不明，**不能与 Qlib benchmark 的数字横向比较**。
4. **Kronos 论文的 21.9% 年化超额 / IR 1.42**——来自作者自己的回测，我没找到独立复现。中金的实测（超额 9%）与之差距明显，**更接近真实预期**。
5. **FinWorld 的实际可用性**——仓库标注 preview，其"DL 显著优于 LightGBM"的结论基于 MAE/MSE（与选股收益脱钩），且 LightGBM 基线质量存疑。**我没有实际安装验证。**
6. **广发/东吴/国金/中金/国信研报的 IC 数字互不可比**——票池、标签口径、时段、成本假设都不同。它们各自内部自洽，但**不要跨报告做数字比较**。
7. **Qlib 的 `SJTU-Quant/qlib` 与 `SJTU-DMTai/qlib` 是同一个仓库**（前者 301 重定向到后者），这是我从 HTTP 重定向验证的。README 里同时指向两个名字容易混淆。
8. **没有任何一个 GNN 股票模型有"独立第三方在相同数据上复现出论文数字"的公开证据。** 请把所有 GNN 选股论文数字都当作【论文自述】。我找到的最接近独立验证的是**负面**结果（中金 2026-08、华泰 AI58 的 +0.42pp）。
9. **华泰 AI42（2021-02）"图神经网络选股年化 35.70% / IR 2.94"我无法核实**——回测截止 2021-02（核心资产顶部），且与 Qlib 官方基准中 GATs 的 4.97%~8.24% 差距过大，**差异来源不明，不建议作为参考**。
10. **东方证券 DFQ-FactorGCL 声称中证全指 IC 12.46% / RankIC 16.14%**（以 HIST 为改进起点）——**这是 Qlib 基准中 HIST IC（0.0522）的 2.4 倍**，且**仅摘要、无代码、数据源未公开**。**我建议高度怀疑，未采信。**
11. **FinGPT 的 HuggingFace 权重是否仍可下载**——本机 `huggingface.co` 不可达，**未能独立确认**。
12. **所有商业舆情模块的单独定价**（iFinD/聚源/数库/朝阳永续/DataYes/天软）均未公开；已知的 Wind/CSMAR 价格都是**打包价，非舆情模块价**。
13. **Anthropic/OpenAI 类闭源模型在 A股因子挖掘上的实测**——未找到任何公开对照；国联民生只对比了 GLM-V5.1 vs DeepSeek-V3.2。

---

## 10. 一页速查表

| 名称 | 链接 | 推荐度 | 接入成本 | A股适配 | 核心风险 |
|---|---|---|---|---|---|
| **DDG-DA** | [qlib 主仓](https://github.com/microsoft/qlib/tree/main/examples/benchmarks_dynamic/DDG-DA) | ⭐⭐⭐ 强烈推荐 | 极低 | 原生 | 必须用众包数据；对强基线增益小 |
| **Alpha360 + HIST/IGMTF/TRA/GATs** | [qlib benchmarks](https://github.com/microsoft/qlib/tree/main/examples/benchmarks) | ⭐⭐⭐ 强烈推荐 | 极低 | 原生 | 需预训练底座；seed 方差大；benchmark 时段偏早 |
| **Kronos** | [shiyu-coder/Kronos](https://github.com/shiyu-coder/Kronos) | ⭐⭐⭐ 强烈推荐 | 中（需 GPU） | 官方 Qlib A股管线 | 官方 demo 非生产；标准版依赖均值回复，2025 趋势市踏空 |
| **MASTER** | [SJTU-DMTai/MASTER](https://github.com/SJTU-DMTai/MASTER) | ⭐⭐ 值得一试 | 高（torch 冲突） | 高（但数据难拿） | 作者失原始数据权限；停更；Qlib 集成是志愿者做的 |
| **DoubleAdapt** | [SJTU-DMTai/qlib](https://github.com/SJTU-DMTai/qlib/tree/main/examples/benchmarks_dynamic/incremental) | ⭐⭐ 值得一试 | 中高 | 高 | 需 `higher`；Alpha158 上 adapter 过参数化；调参敏感 |
| **RD-Agent（LLM 因子挖掘）** | [microsoft/RD-Agent](https://github.com/microsoft/RD-Agent) | ⭐⭐ 值得一试（**谨慎**） | 中（LLM API 成本） | 高（原生 csi300） | token 成本；多重比较陷阱；**第三方实测："ICIR 提升弱于 IC"、"单次运行结果不可复现"；不要用弱模型** |
| **公告事件因子（规则+小模型）** | [巨潮 hisAnnouncement](http://www.cninfo.com.cn/new/hisAnnouncement/query) | ⭐⭐ 值得一试 | 低 | 原生 | PIT 安全、无法律风险；注意 `date` vs `pub_time` 陷阱 |
| **舆情/股吧爬虫** | — | ❌ **不推荐** | — | — | **法律风险（2025 判例判赔 228 万）**；且 A股舆情 IC 符号大概率为负（§4.8） |
| **AGRU 改造（Huber / CVaR / Attention Pooling / Memory）** | [国金](https://stock.finance.sina.com.cn/stock/go.php/vReport_Show/kind/lastest/rptid/820428637580/index.phtml) / [广发](https://stock.finance.sina.com.cn/stock/go.php/vReport_Show/kind/11/rptid/841632221169/index.phtml) | ⭐⭐ 值得一试 | 低 | 原生 | 无官方代码；效果不可交叉验证 |
| **TSLib 系（iTransformer/PatchTST/TimesNet/TimeMixer++）** | [thuml/Time-Series-Library](https://github.com/thuml/Time-Series-Library) | ⭐ 观望 | 低 | 低（范式错配） | 单序列 vs 横截面错配；MAE/MSE 与盈利脱钩；**官方已宣布 2026.04 起停止演进、自认 benchmark 失效**；**TimeMixer++ 无官方代码** |
| **预训练 TSFM（Chronos/TimesFM/Moirai/TimeGPT/TiRex/Sundial）** | [Re(Visiting) TSFMs in Finance](https://arxiv.org/abs/2511.18578) | ⭐ 观望 | 低 | 无证据（且有负面证据） | **横截面日频超额收益上，现成 TSFM 零样本和微调都不行**；只有金融原生从零预训练有效 |
| **STRATA（方法论文，非代码）** | [arXiv:2608.28060](https://arxiv.org/abs/2608.28060) | ⭐⭐ **必读方法论** | 零（只是改口径） | 原生 A股中盘 | 无代码；**但它揭示的口径问题（风格残差化 + 首个可成交价）适用于你现有的一切回测** |
| **损失函数控制实验（方法论文）** | [arXiv:2510.14156](https://arxiv.org/abs/2510.14156) | ⭐⭐ **必读方法论** | 零（只是改 loss） | 方法可迁移（实验为美股） | 110 只美股大盘股、单次切分、无成本假设；ICIR 列量级可疑勿引 |
| **FinGPT / FinRobot** | [FinGPT](https://github.com/AI4Finance-Foundation/FinGPT) | ⭐ 观望 | 中 | 低（错配） | 文本理解非量化管线；A股无端到端实证 |
| **FinWorld** | [DVampire/FinWorld](https://github.com/DVampire/FinWorld) | ⭐ 观望 | — | 声称支持 | preview 版，代码不全；结论基于 MAE/MSE |
| **ACT** | [arXiv:2604.20204](https://ar5iv.labs.arxiv.org/html/2604.20204v1) | ⭐ 观望 | — | 高（CSI300/500） | 未找到开源代码 |
| **RelationalStock / RSR** | [fulifeng/Temporal_Relational_Stock_Ranking](https://github.com/fulifeng/Temporal_Relational_Stock_Ranking) | ⭐ 观望（**偷思想，别用代码**） | — | ❌ 仅美股 | Python 3.6 + TF 1.x，已死；无 A股关系图 |
| **Qlib GATs（作为关系 GNN 用）** | [源码](https://github.com/microsoft/qlib/blob/main/qlib/contrib/model/pytorch_gats.py) | ❌ 认知纠正 | — | — | 它**不是**关系图模型，是当日截面全连接注意力，O(N²) |
| **KRNN / Sandwich** | [源码](https://github.com/microsoft/qlib/blob/main/qlib/contrib/model/pytorch_krnn.py) | ❌ 不推荐 | — | — | 年化 -4.65% / 0.05%；batch 语义结构性错误 |
| **Alpha158 上堆 DL** | — | ❌ 不推荐 | — | — | 官方数据显示无 DL 模型 IC 超 LightGBM |
| **Qlib TFT** | — | ❌ 不推荐 | — | — | 依赖 tensorflow 1.15，仅 Python 3.6–3.7 |

---

*本文档 v4，生成于 2026-09，经多轮交叉核查后修订（勘误与修订记录见 §0 后注）。所有 star 数、push 时间来自 GitHub API 实测；benchmark 数字来自各仓库 README 原文；**Qlib 模型实现层面的判断来自本地源码逐行核对**（`pytorch_gats.py` / `pytorch_krnn.py` / `pytorch_hist.py`）；论文结论来自 arXiv 摘要/全文（[2510.14156](https://arxiv.org/abs/2510.14156)、[2608.28060](https://arxiv.org/abs/2608.28060)、[2511.18578](https://arxiv.org/abs/2511.18578)、[2508.02739](https://arxiv.org/abs/2508.02739) 均已核对原文）；券商结论来自研报公开原文页。凡我未能读取原文的，已在 §9 明确标注。*

> **配套文档**：同目录下 `A_SHARE_LLM_GNN_RESEARCH_REPORT.md`（912 行 / 156 条来源）是本文在 **LLM 因子挖掘、GNN 关系型选股、舆情文本数据**三个方向上的深度展开，含更完整的数据源实测（Tushare/AkShare/巨潮/东财 API）、开源情感模型横向对比、以及"论文强/开源弱"的空壳清单。本报告的 §3.3、§4.3、§4.7、§4.8 已吸收其核心结论。
