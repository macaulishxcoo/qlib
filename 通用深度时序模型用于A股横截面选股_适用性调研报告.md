# 通用深度时序预测模型用于 A 股横截面选股的适用性调研

> **调研时点**：2026 年 9 月
> **调研视角**：量化工程（已有一套 Qlib + LightGBM + Alpha158 的人工因子生产线，评估是否值得引入 TSLib / TSFM 线路）
> **方法**：中英文合计 100+ 次检索，50+ 次页面/PDF 抓取；TSLib/qlib 仓库做本地克隆核查
> **标注约定**：
> - **[论文自述]** = 原文作者报告的数字，无第三方复现
> - **[官方基准]** = 项目官方发布的基准表（可复现性中等）
> - **[本地核实]** = 我在本机 qlib 克隆中直接读到的代码/文件事实
> - **[无法验证]** = 明确说明未能确认，绝不猜测

---

## 0. 结论先行（TL;DR）

**一句话判断：TSLib 里的模型（iTransformer / PatchTST / TimesNet / TimeMixer / DLinear / FreTS / Mamba 系）是为"单条（或少量）序列外推"设计的，与"A 股 5000 只股票的每日横截面排序"存在结构性错配。现有全部证据（官方基准、券商研报、学术论文）都指向同一个结论——在 A 股日频量价上，这类模型相对 GRU/LightGBM 的增量很小，甚至为负；真正能带来增益的是"换输入表征 + 换成横截面/排序目标 + 换成金融原生预训练"，而不是"换一个更强的时序骨干网络"。**

六条支撑性结论：

1. **TSLib 已于 2026.04 官方宣布停止新增功能**，且维护者自己写明"其基准可能已不再对评估当前研究的意义"（原文见 §1.2）。把它当作"现成可用、持续演进的模型库"来选型是误判。
2. **TimeMixer++ 是真实存在的论文（ICLR 2025）**，用户怀疑的"混淆"部分不成立；但**它没有官方开源代码**，且**未被 TSLib 收录**——这才是真正的工程陷阱（见 §2）。
3. **Qlib（微软，约 4.8 万 star）的官方模型库里一个 TSLib 模型都没有**。我用 `grep` 在整个 qlib 仓库搜索 `iTransformer|PatchTST|TimesNet|TimeMixer|DLinear|FreTS|S-Mamba|TimeMachine`，**零命中** [本地核实]。这是业界最主流的 A 股开源量化框架用脚投票的结果。
4. **Qlib 官方 20-seed 基准显示：在人工因子表（Alpha158）上，原生 Transformer 的 IC 0.0264 远低于 LightGBM 的 0.0448；而在原始量价序列（Alpha360）上，Transformer 年化收益 −2.70%、IR −0.34，是全场倒数第一。** 但同时 TCN/HIST 等序列模型又能超过 LightGBM——所以正确结论不是"深度模型无用"，而是"**输入表征决定成败**"（见 §3.3）。
5. **时序基础模型（TSFM）在金融上的实证结果是"负面到中性"**。最权威的大规模横截面研究（Rahimikia et al., 2B 观测 / 94 国 / next-day 横截面超额收益）发现 **Chronos、TimesFM 零样本与微调表现都很差，跑不赢 CatBoost**；有正面效果的是**在金融数据上从零预训练**（见 §5.2）。
6. **A 股券商研报中，"TSFM 做横截面选股"截至调研时点是空白**；已有的 Kronos 应用全部是**指数择时**，不是选股。券商用 TSFM/深度时序模型做选股的回测里，**没有一份披露实盘业绩**（见 §4.3）。
7. ⭐ **最被低估的杠杆是损失函数与标签，不是骨干网络。** 一篇固定架构、只换损失函数的对照实验显示：测试集 MSE 最低的模型 Sharpe 反而最差；排序损失让 Sharpe 从 0.6637 升到 0.7529、回撤从 −19.58% 改善到 −15.77%，**而 IC 几乎没变**（0.0733–0.0767）。**用 MSE 做模型选择会系统性选错模型**（见 §3.4）。

---

## 1. Time-Series-Library (TSLib) 仓库核查

### 1.1 仓库基本事实

| 项目 | 事实 |
|---|---|
| 仓库 | [thuml/Time-Series-Library](https://github.com/thuml/Time-Series-Library) |
| Star | **约 1.28 万**（12,843） |
| 最后提交 | **2026-04-18** |
| 维护机构 | 清华 THUML（[THUML 主页](https://github.com/thuml)） |
| 定位 | "a library for deep learning researchers, especially for deep time series analysis" |
| 覆盖任务 | 长期/短期预测、插补（imputation）、异常检测、分类 **——共 5 类，全部是单序列/多变量序列任务，没有任何横截面/排序任务** |

### 1.2 ⚠️ 最重要的发现：官方已宣布停止演进

README 的 News 区第一条（2026.04）原文：

> "Due to the limited bandwidth of the current maintainers, we will not be actively adding new features to this library. Since the library was originally released three years ago, **many of its benchmarks may no longer be meaningful for evaluating the effectiveness or progress of current research.** However, the baseline implementations remain correct. **We therefore recommend seeking out newer benchmarks.**"

来源：[TSLib README](https://raw.githubusercontent.com/thuml/Time-Series-Library/main/README.md)

**工程含义**：这不是一个"停止更新但基准仍权威"的库，而是维护者**主动承认基准已失效**的库。选型时把它当"参考实现集合"可以，当"benchmark 权威来源"不行。

### 1.3 模型清单：有哪些、**没有**哪些

**TSLib 确实收录的**（[README 模型列表](https://github.com/thuml/Time-Series-Library#leaderboard-for-time-series-analysis)）：

- Transformer 系：iTransformer (ICLR 2024)、PatchTST (ICLR 2023)、TimesNet (ICLR 2023)、TimeXer (NeurIPS 2024)、Crossformer、FEDformer、Autoformer、Informer、Non-stationary Transformer、Pyraformer、Reformer、ETSformer、TimeFilter (ICML 2025)
- MLP/线性系：**DLinear (AAAI 2023)**、TSMixer、LightTS、TiDE、FreTS (NeurIPS 2023)、SegRNN、Koopa、WPMixer、MultiPatchFormer
- 多尺度/混合：**TimeMixer (ICLR 2024)**、TimeMixer 的官方代码在 [kwuking/TimeMixer](https://github.com/kwuking/TimeMixer)（约 1,983 star，最后提交 2025-10-05）
- Mamba/SSM：Mamba、**MambaSL (ICLR 2026)**
- TSFM（2025.11 新增零样本评估）：Chronos、Chronos2、Moirai、TimesFM、Sundial、Time-MoE、Toto、TiRex

**TSLib 明确没有的**（README 全文 grep，命中数 = 0）[本地核实]：

- ❌ **TimeMixer++**（0 命中）
- ❌ **S-Mamba / TimeMachine / SimMTM / Mamba4Cast**
- ❌ **Lag-Llama / Timer**

> 用户提到的 S-Mamba、TimeMachine 均**不在 TSLib 中**。S-Mamba 的官方代码在 [Youplusss/S-D-Mamba](https://github.com/Youplusss/S-D-Mamba)（"Is Mamba Effective for Time Series Forecasting?"）。

### 1.4 ❌ A 股 / 选股支持：不存在

TSLib 的数据加载器、评估指标、脚本全部面向 ETT / Weather / Electricity / Traffic / Exchange / PEMS 等标准学术数据集。**没有任何股票池、截面中性化、IC/RankIC、多空组合回测的代码或接口。** 要用于 A 股选股，需要自行改造的至少包括：数据管线、标签构造（截面标准化收益）、损失函数（排序损失）、评估（RankIC/ICIR）、回测（含涨跌停/停牌/交易成本）。这不是"接一下数据集"的工作量。

---

## 2. TimeMixer++ 核查（用户重点质疑项）

### 2.1 结论：论文是真的，代码是没有的

用户怀疑"TimeMixer ICLR 2024 与某个号称的 TimeMixer++ 之间存在混淆"。**核查结果：不是混淆，TimeMixer++ 是真实存在的独立论文。**

| 项目 | TimeMixer（第一代） | **TimeMixer++** |
|---|---|---|
| 标题 | TimeMixer: Decomposable Multiscale Mixing for Time Series Forecasting | **TimeMixer++: A General Time Series Pattern Machine for Universal Predictive Analysis** |
| 会议 | **ICLR 2024** | **ICLR 2025** |
| 作者 | Shiyu Wang 等 | Shiyu Wang, Jiawei Li, Xiaoming Shi, Zhou Ye, Baichuan Mo, Wenze Lin, Ju Shengtong, Zhixuan Chu, **Ming Jin** |
| 单位 | 蚂蚁集团 + 清华（推断，作者群重合） | 同上（作者群高度重合） |
| 链接 | [OpenReview](https://openreview.net/pdf?id=7oLshfEIC2) | [ICLR 2025 OpenReview](https://openreview.net/forum?id=1CLzLXSFNn) · [ML Anthology 著录](https://mlanthology.org/iclr/2025/wang2025iclr-timemixer/) · [PDF](https://openreview.net/pdf/6de8153acf0c7175730f8022e49df3a7183b6900.pdf) |
| **官方代码** | ✅ [kwuking/TimeMixer](https://github.com/kwuking/TimeMixer)（约 1,983 star，2025-10 最后提交） | ❌ **未找到任何官方仓库** |

**TimeMixer++ 的技术主张** [论文自述]：提出 TSPM（time series pattern machine），用 4 个组件——多分辨率时间成像（MRTI，把多尺度序列转成"时间图像"）、时间图像分解（TID，双轴注意力分离季节/趋势）、多尺度混合（MCM）、多分辨率混合（MRM）——声称在 **8 个时序分析任务**上同时达到 SOTA。

### 2.2 我做的代码存在性核查（这是关键）

我逐一验证了候选仓库：

| 候选 | 结果 |
|---|---|
| `kwuking/TimeMixerPlusPlus` | **HTTP 404** |
| `thuml/TimeMixerPlusPlus` | **HTTP 404** |
| `ShiyuWang-Ant/TimeMixerPlusPlus` | **HTTP 404** |
| GitHub 仓库搜索 "TimeMixer++" | 仅找到第三方/个人仓库：[linye157/TimeMixerpp](https://github.com/linye157/TimeMixerpp)（**5 star**，"TimeMixer++ Agent"）、[frostyalce000/Timeseries-Forecasting-TimeMixerPlus](https://github.com/frostyalce000/Timeseries-Forecasting-TimeMixerPlus)（**0 star**） |

**判断**：这些第三方仓库 star 数极低、命名可疑（一个有 "Agent" 后缀）、无可信来源，**不能作为生产实现的依赖**。截至调研时点，**TimeMixer++ 没有一个可信的官方或高星社区实现**。

### 2.3 给下游的实操结论

- ✅ 可以引用 TimeMixer++ 作为"学术前沿方向"的证据
- ❌ **不要把它列入"可落地的候选模型"**——没有代码，且未被 TSLib 收录，复现成本 = 从论文重写
- ⚠️ 如果团队里有人看到"TimeMixer++ (ICLR 2025)"就想直接跑，请明确指出：**ICLR 2025 的接收 ≠ 有可用代码**。相比之下 TimeMixer (ICLR 2024) 有官方代码、被 TSLib 收录，是唯一可低成本试用的一代
- ⚠️ 另外注意：TimeMixer++ 是"8 任务通用模型"，而**通用性正是它在金融场景的弱点**——§5 的 TSFM 证据表明，跨域通用表征在金融上迁移效果差

---

## 3. 核心矛盾：单序列外推 vs 横截面排序

### 3.1 任务定义的结构性差异

| 维度 | TSLib 的设定 | A 股选股的实际需求 |
|---|---|---|
| 输入 | 单条序列 (L,) 或少量协变量 (L, C) | 5000 只股票 × 每日特征截面 |
| 输出 | 未来 H 步的**数值** | 全市场股票的**相对排序** |
| 损失 | MSE / MAE | 排序损失 / IC 最大化 |
| 评估 | MSE、MAE、RMSE | IC、RankIC、ICIR、多空收益、IR、换手 |
| 关键结构 | 时间维相关性 | **截面维相关性**（同一天的股票之间） |

**最关键的一点**：股票收益的 MSE 极难降低，因为信噪比极低。学术上，"横截面收益预测的样本外 R² 通常在 **1% 以下**"是公认量级（Rahimikia et al. 引述）。一个把 MSE 降 5% 的模型，其信息系数（IC）可能只有 0.01，扣掉买卖价差后毫无价值。**MSE 的改进与 IC 的改进之间没有可靠映射。**

**工程判断**：iTransformer 的"倒置注意力"（把每个变量的整条时间序列作为一个 token 做注意力）在概念上确实比原生 Transformer 更接近截面建模——如果把"变量"理解为"股票"，它就是在做股票间的注意力。**但这需要把数据的组织方式从"L 长序列"改成"N 只股票"**，此时输入维度是 (N, L)，注意力在 N 维上做。TSLib 的实现是按 (L, C) 组织的，直接拿来用并不是这个语义。**这是一次实质性改造，不是调参。**

### 3.2 简单基线批判文献（用户重点质疑项）

**(a) DLinear / LTSF-Linear——用户提到的经典批判**

- 论文：**Are Transformers Effective for Time Series Forecasting?**
- 作者：**Ailing Zeng, Muxi Chen, Lei Zhang, Qiang Xu**（用户简报未给作者，此处更正）—— 香港中文大学 + 上海 AI Lab
- 发表：**AAAI 2023**；arXiv:2205.13504（2022-05-26 提交）
- 链接：[arXiv](https://arxiv.org/abs/2205.13504) · [AAAI 官方](https://ojs.aaai.org/index.php/AAAI/article/view/26317) · 代码 [cure-lab/LTSF-Linear](https://github.com/cure-lab/LTSF-Linear)（约 2,515 star，最后提交 **2024-01-28**）
- 核心主张 [论文自述]：self-attention 的**排列不变性**必然导致时序信息损失；一个**单层线性模型**（LTSF-Linear / DLinear）在 **9 个真实数据集上全部优于**当时最复杂的 Transformer 类 LTSF 模型，"often by a large margin"

**(b) 稳健性/容量权衡批判——用户简报归属有误**

用户简报写"The Capacity and Robustness Trade-off (Tan et al.)"。**核查结果：该论文并非 Tan 等所著**，实际作者为 **Lu Han, Han-Jia Ye, De-Chuan Zhan**，arXiv:2304.05206。⚠️ 本报告未能独立抓取该论文全文，此条为据检索结果的更正，建议下游引用前自行复核。

**(c) TSLib 维护者自己的"精度定律"（Accuracy Law）**

- 论文：arXiv:2510.02729（2025-10 发布）
- 来源：[TSLib README News 2025.10](https://raw.githubusercontent.com/thuml/Time-Series-Library/main/README.md) 明确写道："Given the recent confusion among researchers regarding **minor improvements on standard benchmarks**, we propose the Accuracy Law to characterize the objectives of deep time series forecasting tasks, **which can be used to identify saturated datasets.**"
- 中文解读见：[AI论文速读 | 深度时间序列预测的未来走向：精度定律的发现与应用](https://cloud.tencent.cn/developer/article/2575439)
- **含义**：连 TSLib 团队自己都在说"标准基准上的微小提升已经没有意义"。这与 §1.2 的停更声明互相印证。

**(d) "语言模型对时序预测其实没用"**

- 论文：**Are Language Models Actually Useful for Time Series Forecasting?**，NeurIPS 2024，arXiv:2406.16964
- TSLib 已收录其方法 PAttn（[models/PAttn.py](https://github.com/thuml/Time-Series-Library/blob/main/models/PAttn.py)）
- **含义**：LLM 组件在时序预测中可被简单注意力替代而不损失性能——对"把 LLM/TSFM 搬到金融"的路线是直接的反证

> **[无法验证]** 我**没有找到**任何经过同行评审、证明"TSLib 基准数字不可复现"的论文。用户简报中假设存在这样一篇，实际未找到。我找到的是维护者自认基准失效（§1.2）和自研的精度定律（§3.2c），性质不同，不应混淆。

### 3.3 ⭐ 最有说服力的实证：Qlib 官方基准（硬数据）

这是本次调研中**最贴近用户实际场景**的证据：微软 Qlib 是 A 股开源量化的事实标准，其官方的 20-seed 基准直接回答"深度时序模型 vs LightGBM"。

来源：[microsoft/qlib `examples/benchmarks/README.md`](https://github.com/microsoft/qlib/blob/main/examples/benchmarks/README.md)（[本地核实]，我直接读取了工作区内的 qlib 克隆）

**CSI300 / Alpha158（人工因子表）**——与用户现有生产线同构：

| 模型 | IC | RankIC | 年化收益 | IR |
|---|---|---|---|---|
| **DoubleEnsemble** | **0.0521** | 0.0502 | **0.1158** | **1.3432** |
| XGBoost | 0.0498 | 0.0505 | 0.0780 | 0.9070 |
| CatBoost | 0.0481 | 0.0454 | 0.0765 | 0.8032 |
| **LightGBM** | **0.0448** | **0.0469** | **0.0901** | **1.0164** |
| TRA (sel-20) | 0.0440 | 0.0540 | 0.0718 | 1.0835 |
| Linear | 0.0397 | 0.0472 | 0.0692 | 0.9209 |
| MLP | 0.0376 | 0.0429 | 0.0895 | 1.1408 |
| SFM | 0.0379 | 0.0464 | 0.0465 | 0.5672 |
| ALSTM (sel-20) | 0.0362 | 0.0463 | 0.0470 | 0.6992 |
| **TFT (sel-20)** | 0.0358 | **0.0116** ⚠️ | 0.0847 | 0.8131 |
| Localformer | 0.0356 | 0.0468 | 0.0438 | 0.6600 |
| GATs (sel-20) | 0.0349 | 0.0462 | 0.0497 | 0.7338 |
| LSTM (sel-20) | 0.0318 | 0.0435 | 0.0381 | 0.5561 |
| GRU (sel-20) | 0.0315 | 0.0428 | 0.0344 | 0.5160 |
| TCN | 0.0279 | 0.0421 | 0.0262 | 0.4133 |
| **Transformer** | **0.0264** | 0.0407 | 0.0273 | 0.3970 |
| TabNet | 0.0204 | 0.0333 | 0.0227 | 0.3676 |

**读数**：在人工因子表上，所有深度序列模型（含 Transformer、TCN、LSTM、GRU、TFT）**IC 全面低于 LightGBM / XGBoost / CatBoost**。原生 Transformer 的 IC 只有 LightGBM 的 **59%**。TFT 的 RankIC **0.0116** 是全场最差之一（注意其 IC 0.0358 正常但 RankIC 崩塌——说明它学到了绝对水平而非截面排序，这正是"用 MSE 训练去做排序任务"的典型病症）。

**CSI300 / Alpha360（原始 360 维量价序列）**——这才是与 TSLib 场景最接近的设定：

| 模型 | IC | RankIC | 年化收益 | IR |
|---|---|---|---|---|
| **HIST** | **0.0522** | **0.0667** | **0.0987** | **1.3726** |
| TCTS | 0.0508 | 0.0599 | 0.0893 | 1.2256 |
| ALSTM | 0.0497 | 0.0599 | 0.0626 | 0.8651 |
| GRU | 0.0493 | 0.0584 | 0.0720 | 0.9730 |
| TRA | 0.0485 | 0.0587 | 0.0920 | 1.2789 |
| IGMTF | 0.0480 | 0.0606 | 0.0946 | 1.3509 |
| GATs | 0.0476 | 0.0598 | 0.0824 | 1.1079 |
| AdaRNN | 0.0464 | 0.0539 | 0.0753 | 1.0200 |
| LSTM | 0.0448 | 0.0549 | 0.0647 | 0.8963 |
| TCN | 0.0441 | 0.0519 | 0.0604 | 0.8295 |
| ADD | 0.0430 | 0.0559 | 0.0667 | 0.8992 |
| Localformer | 0.0404 | 0.0542 | 0.0246 | 0.3211 |
| **LightGBM** | **0.0400** | **0.0499** | **0.0558** | **0.7632** |
| XGBoost | 0.0394 | 0.0448 | 0.0344 | 0.4527 |
| DoubleEnsemble | 0.0390 | 0.0486 | 0.0462 | 0.6151 |
| CatBoost | 0.0378 | 0.0467 | 0.0292 | 0.3781 |
| MLP | 0.0273 | 0.0396 | 0.0029 | 0.0274 |
| Sandwich | 0.0258 | 0.0337 | 0.0005 | 0.0001 |
| KRNN | 0.0173 | 0.0270 | **−0.0465** | **−0.5415** |
| **Transformer** | **0.0114** | **0.0327** | **−0.0270** | **−0.3378** |
| TabNet | 0.0099 | 0.0290 | **−0.0369** | **−0.3892** |

**读数（这段最重要）**：

1. **LightGBM 在 Alpha360 上被多个序列模型反超**（HIST 0.0522 vs 0.0400）。所以"深度模型一律打不过 GBDT"是错的。
2. **但反超的不是 Transformer。** 原生 Transformer 在 Alpha360 上 **年化 −2.70%、IR −0.34，全场倒数第二**（仅好于 KRNN）；TabNet 年化 −3.69%。而 HIST / IGMTF / TRA / TCTS / ALSTM 这些**为股票任务专门设计**的架构才是赢家。
3. **赢得比赛的模型，没有一个来自 TSLib。** HIST、IGMTF、TRA、TCTS、AdaRNN、SFM 都是股票/时序任务专用架构，输入输出按截面组织。
4. **本机 `grep` 验证**：在整个 qlib 仓库（排除 .git）搜索 `iTransformer|PatchTST|TimesNet|TimeMixer|DLinear|FreTS|S-Mamba|TimeMachine`，**零命中** [本地核实]。qlib 有约 **4.84 万 star**、最后提交 2026-07-23，社区活跃，但它**一个 TSLib 模型都没收**。

**工程判断**：这三条合起来给出的信号极其清楚——**"把 TSLib 的模型接到 qlib 上"这条路，业界最主流的开源项目已经用四年时间投票否决了。真正起作用的是(a)换输入表征（Alpha158→Alpha360）、(b)用为截面排序专门设计的架构。**

**CSI500 / Alpha158**（补充读数，验证稳定性）：

| 模型 | IC | RankIC | 年化收益 | IR |
|---|---|---|---|---|
| LightGBM | 0.0399 | 0.0482 | **0.1284** | **1.5650** |
| DoubleEnsemble | 0.0380 | 0.0442 | 0.0382 | 0.1723 |
| CatBoost | 0.0345 | 0.0417 | 0.0496 | 0.5977 |
| Linear | 0.0332 | 0.0462 | 0.0382 | 0.1723 |
| MLP | 0.0229 | 0.0360 | 0.0043 | 0.0602 |

LightGBM 在 CSI500 上同样领先（IR 1.565 vs 次优 0.598）。

> ⚠️ **关于 Linear 的注记**：qlib 的 `Linear` 在 CSI300/Alpha158 上 IC 0.0397、年化 0.0692、IR 0.9209，**优于全部 Transformer 系模型**。这是 DLinear 批判在 A 股场景的直接复现——**线性模型就是一个必须认真对待的强基线**。任何新模型若打不过 qlib 的 `Linear`，就不值得继续投入。

### 3.4 ⭐⭐ 直接实验证据：损失函数比架构更重要

**这是本次调研中唯一一篇"控制架构不变、只改损失函数"的对照实验**，直接量化了 §3.1 的论点。

- 论文：**On Evaluating Loss Functions for Stock Ranking: An Empirical Analysis with Transformer Model**
- 作者：**Jan Kwiatkowski, Jarosław A. Chudziak**（华沙理工大学）—— ⚠️ **与 §6 中那份付费墙后的 MDAI 2025 论文《Comparing Transformer Models for Stock Selection in Quantitative Trading》是同一批作者**
- 时间：2025-10-15；[arXiv:2510.14156](https://arxiv.org/abs/2510.14156)
- 设定：PortfolioMASTER（Transformer）架构**固定不变**，仅替换 8 种损失函数；S&P 500 中 110 只股票（11 个 GICS 行业各取市值前 10），2015-01-03 至 2024-12-03；Top-5 等权、日频再平衡多头组合

| 损失函数 | 累计收益% | **年化收益%** | 年化波动% | **Sharpe** | **最大回撤%** | **Spearman IC** | ICIR | **测试集 MSE** |
|---|---|---|---|---|---|---|---|---|
| **MSE（基线）** | 79.28 | 14.78 | 15.79 | 0.6637 | −19.58 | 0.0754 | 8.8076 | **0.00286** |
| Hinge | 82.90 | 15.33 | 15.79 | 0.6984 | −19.58 | 0.0762 | 8.8432 | 0.00301 |
| **Margin（最优）** | **89.07** | **16.23** | 15.85 | **0.7529** | −18.33 | 0.0758 | **8.8520** | **0.00632** ⚠️ |
| **BPR** | 85.68 | 15.74 | 15.89 | 0.7200 | **−15.77** | 0.0733 | 8.6915 | **0.01145** ⚠️ |
| RankNet | 80.78 | 15.01 | 15.82 | 0.6771 | −18.97 | **0.0767** | 8.8422 | **0.01909** ⚠️ |
| WHR1 | 82.40 | 15.25 | 15.78 | 0.6938 | −19.54 | 0.0763 | 8.8448 | 0.00352 |
| WHR2 | 81.84 | 15.17 | 15.83 | 0.6866 | −19.74 | 0.0764 | 8.8470 | 0.00300 |
| ListNet | 87.41 | 16.00 | **15.79** | 0.7407 | — | — | — | — |

*（数字为我从论文 PDF 提取的 Table 2 [论文自述]；ListNet 行的 MDD/IC 在提取文本中缺失，以"—"标注，不做推测）*

**三个极其重要的读数**：

1. **测试集 MSE 与组合表现几乎反向**：MSE 基线的测试 MSE 最低（0.00286），但其 Sharpe（0.6637）**低于全部 7 种排序损失**。**RankNet 的 MSE 是基线的 6.7 倍（0.01909），IC 却最高（0.0767）、Sharpe 更高（0.6771）。** → **用 MSE 做模型选择，会系统性地选错模型。** 这是对 §3.1 "MSE→IC 无映射"最直接的实验证明。
2. **IC 对损失函数几乎不敏感，但经济结果敏感**：8 种损失的 Spearman IC 全部落在 **0.0733–0.0767**（极差仅 0.0034），而年化收益跨度 **14.78% → 16.23%**、Sharpe **0.6637 → 0.7529**、最大回撤 **−19.58% → −15.77%**。 → **IC 相近不等于策略相近；只报 IC 的论文掩盖了真正重要的差异。**
3. **BPR 的回撤优势最突出**（−15.77% vs MSE 的 −19.58%），尽管其 IC 最低（0.0733）。 → 风险控制与排序精度是**不同的目标**，需要分开优化。

**工程判断**：这篇论文的方法论意义大于其数字（S&P 500 ≠ A 股）。它证明了 **"换损失函数"这个零架构成本的改动，能带来与"换骨干网络"同量级甚至更大的经济收益**。下游若还在用 MSE/IC 做模型选择，这是最低成本、最高确定性的改进点。

**另一条佐证（标签设计）**：

- 论文：**The Label Horizon Paradox: Rethinking Supervision Targets in Financial Forecasting**
- 作者：Chen-Hui Song, Shuoling Liu, Liyuan Chen —— **易方达基金管理有限公司**（广州）
- 主张 [论文自述]：挑战"训练标签必须严格等于推理目标"这一默认假设，发现**最优监督信号往往偏离预测目标**，并在中间期限上随市场动态漂移；用双层优化框架在单次训练内自动寻找最优代理标签，"在大规模金融数据集上相对常规基线取得一致提升"
- **[无法验证]**：该论文的 arXiv 编号与具体提升幅度我**未能确认**（仅得 PDF 文本，未见编号；数字在提取文本中碎裂）。引用前请自行核实出处。

**含义**：与损失函数论文相互印证——**"预测什么"（标签）和"怎么优化"（损失）比"用什么网络"更值得投入**。这与 TSLib 的默认设定（MSE + 单序列标签）恰好是两个都不匹配。

---

## 4. 经验证据汇总

### 4.1 学术论文（A 股 / 横截面）

**(a) TRS 会议论文——A 股实证**

- 我抓到一篇 OpenReview 论文片段，提到"curate a dataset comprising **1.5 million instances of A-share daily trading time series**"（[OpenReview PDF](https://openreview.net/pdf?id=KgqI1PlmxR)）
- **[无法验证]**：该 PDF 未能完整抓取（OpenReview 有浏览器验证），模型清单与 IC/RankIC 数字**均未确认**。仅记录线索供下游跟进。

**(b) ⭐ STRATA（arXiv:2608.28060）——A 股横截面的最新严肃工作**

- 标题：**A Compact Selective State-Space Model for Cross-Sectional Stock Return Ranking from Raw Intraday Bars**
- 作者：Mingju Chen, Enze Zhang, Annan Li, Yui Lo, Xiaomin Yuan, Kaiming Yu, Jinhui Ren, Yuanhang Liu
- 2026-08-28 提交，2026-09-08 修订 v3；[arXiv](https://arxiv.org/abs/2608.28060)
- 方法：**244,633 参数**的 SSM（Mamba 类）模型，直接把 5 天原始 5 分钟 bar + 订单簿数据映射到次日横截面收益排序，**无人工特征**
- 数据：约 **1000 只 A 股中盘股**，4 年训练 / 1 年留出测试

**关键数字** [论文自述]：

| 指标 | 数值 |
|---|---|
| **风格残差化后的 RankIC** | **0.0728** |
| 信息比（IR） | 1.128 |
| 信号多空 Sharpe | 12.85 |
| 相对 6 个参数对齐的序列基线 | 在全部 4 个指标上领先，RankIC 的日度配对差 p < 0.001 |
| **⚠️ 改用"首个可成交价"计价后** | **decile 多空价差"与零无法区分"（indistinguishable from zero）** |

**这篇论文的两个方法论贡献比它的数字更重要**（作者的自我批判非常诚实）：

1. **必须做风格残差化**：论文原文指出"a score that merely tilts toward common style factors scores well on raw rank correlations"——一个只是倾向小市值/低波动的分数，在原始 RankIC 上会很好看。**所以作者在算任何指标前，先对 8 个量价风格因子做残差化。** 下游若看到没有做这一步的 A 股 IC 数字，应当高度警惕。
2. **必须用可成交价计价**：close-to-close 标签在信号产生之前就已经开盘了（"The close-to-close target opens before the score exists"）。改用首个可成交价后，**多空收益直接归零**。注意：**架构排序不变、STRATA 的优势甚至扩大**——这说明模型确实学到了排序信息，但**该信息无法变现**。

**工程判断**：STRATA 是本次调研中最值得下游精读的一篇。它同时给出了"怎么做对（风格残差化 + 可成交价）"和"做对之后会看到什么（alpha 消失）"。如果用户的回测没做这两步，很可能在自欺。

**(c) Rahimikia, Ni & Wang (arXiv:2511.18578)——见 §5.2，是 TSFM 部分的核心**

### 4.2 ⭐ 中国券商研报（2024–2026）

> **访问性说明**：绝大多数研报正文在慧博投研/迈博汇金/东方财富研报中心付费墙后。以下数字来自可访问的摘要页（主要为迈博汇金镜像），**已标注核实程度**。**全部为回测，无一份披露实盘业绩。**

**(a) ⭐ 东方证券《因子选股系列之一一八：DFQ-TimesNet》——最直接的目标文献**

| 项目 | 内容 |
|---|---|
| 机构 / 日期 | 东方证券，**2026-04-16** |
| 分析师 | 刘静涵 |
| 模型 | **TimesNet** 二维时序建模 |
| 关键工程细节 | **5 日 + 60 日双周期硬设定，明确放弃 FFT 自动周期识别**（因为不稳定）；TokenEmbedding + 两层 Inception 卷积 + 直接平均周期融合 + 残差连接 |
| 样本 | 中证全指；2014–2025 分段，设隔离间隙防信息泄露 |
| 标签 | 未来 20 日收益率标准化 |
| 来源 | [迈博汇金摘要页](http://m.microbell.com/wap_detail.aspx?id=87becf8be3bbd934854e69c8141605be)（✅ 已抓取核实） |

**已核实数字** [论文自述 / 回测]：中证全指 **IC 12.50%**；**多头超额年化 30.05%**；中证 1000 表现最突出；风格暴露为小市值/高 Beta/低波动/反转，价值与流动性中性；**中证 1000 增强年化对冲 15.80%，信息比 1.90**。

> ⚠️ **最大缺口**：摘要中**没有给出与 LightGBM/GBDT 的对比数字**。对比缺失使这份研报无法回答"TimesNet 比现有 GBDT 好在哪"。
> ⚠️ 任务指定的另一个 URL（[upchina 研报详情](https://zx.upchina.com/report/details/7000846885)）经探测为 **SPA 空壳**，4 个候选 API 端点全部 404，**该页无任何可验证数字**。

**(b) ⭐ 招商证券——最干净的"GRU vs LightGBM"横向对照**

| 模型 | RankIC | 多头超额/对冲 |
|---|---|---|
| **LightGBM（截面 GBDT）** | **10.66%** | 对冲年化 **29.84%** |
| GRU（时序） | 11.3% | 对冲年化 28.83% |
| AGRU（GRU + Attention） | — | **"引入 Attention 后表现没有明显提高"** |
| ICIR 加权集成 | 11.9% | **33.11%** |

**原文结论（最有价值的一句）**："引入截面特征序列后，**截面模型与时序模型的学习能力基本处于同一水平**。"

**(c) 国金证券——TimeMixer / Mamba-2**

| 模型 | 多空年化 | 备注 |
|---|---|---|
| GRU（基线） | **76.35%** | 回撤 11.06% |
| **TimeMixer（原生）** | **57.87%** | **跑输 GRU**；回撤更优 10.64% |
| TSGRU（TimeMixer 分解 + GRU） | 77.95% | IC 11.96% vs GRU 11.75%（微幅） |
| + LightGBM 集成隐向量与因子 | **88.41%** | IC 12.86%（提升显著） |
| Mamba-2 | 沪深300/500/1000 指增 9.99%/12.20%/20.65% | **"只有在日频数据上明显优于 GRU；60 分钟不分伯仲"** |

**这是对用户问题最直接的回答**：**原生 TimeMixer 在 A 股跑输一个普通 GRU**（57.87% vs 76.35%）。增益来自"把时序模型的隐向量喂给 LightGBM 做集成"，而不是时序模型本身。

**(d) 华泰证券——iTransformer / PatchTST 的券商应用**

| 报告 | 模型 | 数字 |
|---|---|---|
| [人工智能 89](https://www.sdyanbao.com/detail/866746)（2025-03-21） | **iTransformer + Crossformer** | 集成后周度 **RankIC 11.64%**、全 A 多头 25.94%、中证 1000 指增 20.25%(IR 3.60) / 21.31%(IR 3.18) |
| 人工智能 75（2024-03-14） | **PatchTST 思想** | 周度 RankIC **8.86% → 9.58%**，TOP 超额 21.15% → 24.65% |
| 人工智能 86（2025-02-21） | 数据漂移 | 综合因子 RankIC 14.5%、RankICIR 1.43 ⚠️（摘要中 IR 自相矛盾，写 3.24 与 3.29 两处） |
| 人工智能 93（2025-07-14） | 双层 Transformer | 融合因子 RankIC 10.96%，中证 1000 增强 19.92%(IR 4.04) |
| **人工智能 100（2026-01-23）** | **综述** | **明确把"时序大模型/金融原生大模型"列为未来方向**；参考文献含 Chronos / Time-LLM / Kronos / CoRA / MASTER |
| 人工智能 105（2026-06-05） | CNN + GRU（筹码龄因子） | RankIC 12.3%、多头超额 32.5% |

**(e) 其他可核实报告**

| 机构 / 日期 | 模型 | 数字 |
|---|---|---|
| 国泰君安 2025 春季策略（2025-02-16） | **TCN / TimesNet / MASTER + GRU** | 全市场周度 rankIC **≈10%**、多头组年化超额 **30%**、最大回撤 14~17%。**这是除东方外唯一点名 TimesNet 的券商报告** |
| 中金 大模型系列(5)（2025-10-15） | **Kronos（TSFM）** | 较通用 TSFM **RankIC +93%**；微调版择时 2025 收益 33.9%、年化超额 9%。**⚠️ 是指数择时，不是横截面选股** |
| 国信 AI 赋能资产配置(22)（2025-11-10） | **Kronos** | 年化超额 21.9%、IR 1.42。⚠️ **该数字来自 Kronos 原论文，非国信自研 A 股回测** |
| 西南证券 PINN-MTICG（2025-04-07） | Multi-Transformer / GAT 消融 | Multi-Transformer 月 IC 10.95%/多头 32.88%；GAT 8.77%/32.77%；融合 **11.41%/37.51%**、多空 44.67% |
| 广发证券（2025-07-01） | agru_dailyquote（GRU+Attention） | 历史 RankIC **14.22%**、胜率 91.97%；中证 1000 指增 17.48% |
| 财通证券 知识蒸馏（2026-05-27） | 时序 LSTM + 截面图注意力 | 2021 以来 5 日 IC 13.0%、多头年化 50.0% |
| 中信建投（2026-06-04） | 13 个高频因子 + **GRU 非线性合成** | 中证 1000 增强**样本外**（2023–2026.4）年化超额 9.68%、IR 2.74 |
| 开源证券 DBD-GRU（2025-07-26） | DBD-GRU | 三因子 RankIC −10.33%/−10.31%/−9.81%；中证 1000 指增超额 11.8%、IR 2.21 |

**(f) 行业共识（定性）**

2026 陆家嘴沙龙圆桌，**国泰海通明确表态"投资领域现阶段不能让大模型直接输出投资信号"**。

### 4.3 券商路线图的共同结论

跨机构横向对照高度一致：

1. **A 股日频量价上，新一代时序深度模型相对 GRU/LightGBM 的增量非常有限**（招商："基本处于同一水平"；国金：TimeMixer 原生跑输 GRU）
2. **主要价值在低相关带来的集成增益，不在单模型替换**（国金：时序隐向量 + LightGBM = 88.41% 多空）
3. **加注意力不一定有用**（招商：AGRU "没有明显提高"）
4. **Mamba 类的优势有频率依赖性**（国金：Mamba-2 仅日频明显优于 GRU）
5. **TSFM（Chronos/TimesFM/Moirai）做 A 股横截面选股 = 券商公开研报空白**。华泰仅在综述的参考文献里提到，且定位为**未来**方向。已有的 Kronos 应用（中金、国信）**全部是择时，不是选股**。

> ❌ **重要澄清**：用户简报中假设存在的"DFQ-Transformer / DFQ-GRU / DFQ-LSTM"系列**不存在**。多轮检索无任何证据。东方 DFQ 系列实际覆盖 TimesNet(118)、FactorGCL(117)、Neural ODE(116)、diversify(115)、TRA(97)、强化学习(95)、XGB(107)、FactorVAE(103/111)、HIST(100)。**不要在下游文档中引用不存在的报告。**

---

## 5. 时序基础模型（TSFM）路线

### 5.1 仓库现状

| 模型 | 仓库 | Star | 最后提交 |
|---|---|---|---|
| **TimesFM** (Google) | [google-research/timesfm](https://github.com/google-research/timesfm) | **约 3.2 万** | 2026-09-09 |
| **Chronos** (Amazon) | [amazon-science/chronos-forecasting](https://github.com/amazon-science/chronos-forecasting) | 约 5,842 | 2026-09-08 |
| **Lag-Llama** | [time-series-foundation-models/lag-llama](https://github.com/time-series-foundation-models/lag-llama) | 1,603 | 2025-06-06 |
| **Moirai / uni2ts** (Salesforce) | [SalesforceAIResearch/uni2ts](https://github.com/SalesforceAIResearch/uni2ts) | 1,588 | 2026-06-02 |
| **Sundial** (清华, ICML 2025 Oral) | [thuml/Sundial](https://github.com/thuml/Sundial) | 228 | 2025-09-12 |
| **Timer-XL** (清华) | [thuml/Timer-XL](https://github.com/thuml/Timer-XL) | 147 | 2025-07-21 |
| **Kronos** (清华, 金融专用) | 论文：[AAAI 官方](https://ojs.aaai.org/index.php/AAAI/article/view/39730)；权重 HF: [NeoQuasar/Kronos-base](https://huggingface.co/NeoQuasar/Kronos-base)、[Kronos-Tokenizer-base](https://huggingface.co/NeoQuasar/Kronos-Tokenizer-base) | — | ⚠️ 官方 GitHub 仓库未定位到（403/404）；存在多个同名第三方镜像仓库 |
| 参考：**Qlib** | [microsoft/qlib](https://github.com/microsoft/qlib) | **约 4.85 万** | 2026-07-23 |

**Kronos 论文摘要（✅ 我已抓到原文并核实）**：

> 作者：**Yu Shi, Zongliang Fu, Shuo Chen, Bohan Zhao, Wei Xu, Changshui Zhang, Jian Li**（清华大学 IIIS + 自动化系）
> "We pre-train Kronos using an autoregressive objective on a massive, multi-market corpus of **over 12 billion K-line records from 45 global exchanges**... On benchmark datasets, **Kronos boosts price series forecasting RankIC by 93% over the leading TSFM and 87% over the best non-pre-trained baseline.** It also achieves a **9% lower MAE in volatility forecasting** and a **22% improvement in generative fidelity** for synthetic K-line sequences."

**这段摘要极其重要，因为它同时印证了两件事**：

1. ✅ **§4.2(e) 中金报告引用的"较通用 TSFM RankIC +93%"，来源就是 Kronos 原论文摘要**（不是中金自研 A 股回测）——国信证券引用的 21.9%/IR 1.42 同理
2. ⚠️ **Kronos 自己的动机陈述印证了 §5.2**：论文开篇即写 "their application to financial candlestick (K-line) data remains limited, **often underperforming non-pre-trained architectures**"——**连金融原生 TSFM 的作者都承认通用 TSFM 在金融上跑输非预训练模型**
3. ⚠️ **注意基准的性质**：+93% 是 **RankIC 的相对提升**，不是绝对 RankIC 值，且对照是"leading TSFM"（一个很弱的基线）。**相对提升 +93% 从一个很低的基数出发，绝对值可能仍然很小。** 摘要未给绝对数字

> ⚠️ **Kronos 代码来源需谨慎**：检索中出现 [hixuco/Kronos](https://github.com/hixuco/Kronos)、[justin1991to2023-rgb/Kronos](https://github.com/justin1991to2023-rgb/Kronos) 等多个非官方同名仓库。**我未能定位到官方 GitHub 仓库**，HF 上的 `NeoQuasar/*` 权重是更可信的入口。下载权重时请核对 HF 组织名。

> **[无法验证]**：Kronos 论文发表于 AAAI（[AAAI 官方页面](https://ojs.aaai.org/index.php/AAAI/article/view/39730)），但**我未能抓取全文核对具体数字**。

### 5.2 ⭐ 核心实证：Rahimikia, Ni & Wang (arXiv:2511.18578)

**这是本次调研中对用户问题最直接、最重要的一篇论文。**

| 项目 | 内容 |
|---|---|
| 标题 | **Re(Visiting) Time Series Foundation Models in Finance** |
| 作者 | Eghbal Rahimikia（曼彻斯特大学）、Hao Ni（UCL）、Weiguan Wang（上海大学） |
| 时间 | 2025-11-23 |
| 链接 | [arXiv:2511.18578](https://arxiv.org/abs/2511.18578) |
| 数据 | 日度**超额**收益，**34 年、94 国、约 20 亿观测**；目标为**次日横截面超额收益**；评估期 2001–2023 |
| 对照 | 线性（OLS/Lasso/Ridge/ElasticNet/PCR）、**树模型（CatBoost/XGBoost/LightGBM）**、神经网络 |
| 公开产出 | 模型权重发布于 [FinText.ai](https://FinText.ai) / [HuggingFace FinText](https://huggingface.co/FinText) |

**摘要原文（我已独立抓取核实）**：

> "We find that **off-the-shelf pre-trained TSFMs perform poorly in zero-shot and fine-tuning settings**, whereas models **pre-trained from scratch on financial data achieve substantial forecasting and economic improvements**, underscoring the value of domain-specific adaptation."

**关键数字** [论文自述]：

| 设定 | 指标 | 数值 |
|---|---|---|
| CatBoost（US 全市场） | 样本外 R² | **−0.10%** |
| OLS 线性 | 样本外 R² | −0.47% |
| **Chronos (large)，零样本** | R² / 方向准确率 / 年化 | **−1.37% / 略高于 51% / 20.17%** |
| **TimesFM (500M)，零样本** | R² / 方向准确率 / 年化 | **−2.80% / 略低于 50% / −1.47%** ⚠️ |
| CatBoost（window 252，无交易成本） | 年化 / Sharpe | **46.50% / 6.79** |
| Chronos (small) **从零金融预训练**，w=5 | R²（前→后） | **−77.07% → −3.18%** |
| Chronos (small) 从零金融预训练，w=512 | 年化 / Sharpe | **36.84% / 5.42** |

**核心结论**：

1. **现成 TSFM 零样本 + 微调都差**，跑不赢 CatBoost；**且微调往往让大多数 TSFM 变得更差**（唯一例外是 Chronos-large，但改进"未转化为经济收益"）
2. **唯一稳健的正面发现是"金融原生从零预训练"**——这恰恰说明**通用时序预训练学到的表征不能迁移到金融**
3. **注意方向准确率**：TimesFM 零样本的次日方向准确率**低于 50%**（比抛硬币还差），年化 −1.47%
4. 小市值股票可预测性高于大市值；多头端持续优于空头端

> ⚠️ 所有数字均为 **[论文自述]**，无第三方复现。且该研究**未单独报告中国 A 股**（94 国样本中含部分亚洲市场，但未见 A 股单独结果）。

### 5.3 TSFM 评估的方法论批判（这组文献很关键）

**(a) 预训练污染 / 数据泄漏**

- **Meyer et al., arXiv:2510.13654**：形式化了两类 TSFM 泄漏模式
- **Hyndman 博客（2026-08-25）**：[robjhyndman.com/hyndsight/foundation_models.html](https://robjhyndman.com/hyndsight/foundation_models.html)——统计了 **22 个已发布 TSFM 的 401 个数据集，只有 6% 从未出现在任何模型的预训练/微调语料中**
- **TSFMAudit, arXiv:2605.26161**：首个专门的 TSFM 污染审计器（6 个模型 / 187 个数据集）
- **Moghadasi & Ghaderi, arXiv:2609.10357**：证明**即使做了无污染的时间留出，仍然不够**——语料"熟悉度"本身就能驱动胜负；在日频外汇上，模型表现与季节朴素基线无法区分；TimesFM 系的优势与其 Wikipedia 语料熟悉度相关（Mann-Whitney p < 1e-5）

**工程含义**：TSFM 论文里"零样本超越专用模型"的结果，有相当大的比例可能来自**测试集在预训练语料里**。金融数据（尤其公开价格序列）被大规模爬取的概率很高。**用户若要在 A 股上验证 TSFM，必须严格控制预训练截止时间，且最好用模型发布日期之后的数据。**

**(b) 其他批判**

- **Bergmeir (2024), Foresight**：TSFM "not (yet) as good as hoped"
- **Brini, arXiv:2607.05291**：9 个 TSFM vs 8 个计量模型（含 HAR），50 个资产——只有 TinyTimeMixers 在每个期限上都勉强胜过 Log-HAR；短期限优势主要来自更好的**尺度**（scaling），而非信息

**(c) Chronos 用于股指预测的独立评估**

- **Łaniewski & Ślepaczuk (2025)**，"Evaluating the Chronos Foundation Model for Daily Stock Index Forecasting"，ISD 2025，[AISeL](https://aisel.aisnet.org/isd2014/proceedings2025/datascience/18/)，DOI [10.62036/ISD.2025.48](https://doi.org/10.62036/ISD.2025.48)
- 数据：Nasdaq-100 / S&P 500，1995–2025 初，滚动窗口
- 对照：AutoARIMA、ETS、DeepAR、**DLinear**、SimpleFeedForward、**PatchTST**、集成方法
- 结论 [论文自述]：**零样本 Chronos 预测精度有竞争力**（与最佳传统方法统计上可比），**但其衍生的交易表现落后于顶级基准**；**微调版 Chronos 在预测精度上统计显著地劣于零样本版**——"underscores the significant challenges in effective fine-tuning"

**注意最后一条**：微调**反而变差**，与 Rahimikia et al. 的发现一致。这是 TSFM 在金融上反复出现的模式。

**(d) ⭐ 量化从业者的工程批判（Jonathan Kinlay, 2026-02-22）**

- 标题：**Time Series Foundation Models for Financial Markets: Kronos and the Rise of Pre-Trained Market Models**
- 链接：[jonathankinlay.com](https://jonathankinlay.com/2026/02/time-series-foundation-models-for-financial-markets-kronos-and-the-rise-of-pre-trained-market-models/)
- 作者有 25 年量化从业经验。其"空方论证"（Bear Case）原文要点：

> "The paper benchmarks on **MSE and CRPS — statistical metrics, not economic ones**. A model that improves next-candle MSE by 5% may have an **information coefficient of 0.01** — statistically detectable at 12 billion observations but **worthless after bid-ask spreads**. More fundamentally, **training on 12 billion samples of approximately-IID noise teaches the model the shape of noise, not exploitable alpha**. The pre-training captures **volatility clustering (a risk characteristic), not conditional mean predictability (an alpha characteristic)**. GARCH does the former with two parameters and full transparency; Kronos does it with millions of parameters and a black box. **Show me a backtest with realistic execution costs before calling this a trading signal.**"

他同时列出：样本外稳健性、对历史模式过拟合、可解释性、**执行可行性（论文未处理交易成本）**、基准缺失、算力成本、监管不确定性。

**但他也给出了多方论证**：合成数据生成、跨资产学习、新市场进入的数据效率——**其"最可辩护的近期价值是压力测试用的合成数据增强，而非信号源"**。

**(e) 通用 TSFM 对金融的不适用性（Kronos 团队的动机）**

Kinlay 转述：Kronos 团队自己识别的问题就是——**"generic time series foundation models, despite their scale, often underperform dedicated domain-specific architectures when evaluated on financial data"**。

**工程判断**：这句话值得下游高度重视。**连要做金融 TSFM 的团队，其立论前提都是"通用 TSFM 在金融上不行"。**

### 5.4 A 股应用现状

**(a) 券商侧**

- **中金《大模型系列(5)：大语言时序模型 Kronos 的 A 股择时应用》**（2025-10-15）：[新浪财经转载](http://stockfinance.sina.cn/stock/go.php/paper/reportid/813487920250/index.phtml)。用途是**指数择时**，不是横截面选股。报告中 Kronos 较通用 TSFM 的 RankIC **+93%**（即：**金融原生预训练 > 通用预训练**，与 §5.2 结论一致）
- **国信证券**：引用 Kronos 原论文数字（年化超额 21.9%、IR 1.42），**非自研 A 股回测**
- ❌ **Chronos / TimesFM / Moirai 在 A 股的券商回测 = 空白**。华泰《人工智能 100》（2026-01-23）仅在**参考文献列表**中提及，明确定位为**未来方向**

**(b) 开源侧**

- **Kronos + Qlib A 股微调管线**：[leeroopedia/workflow-shiyu-coder-kronos-qlib-finetuning](https://github.com/leeroopedia/workflow-shiyu-coder-kronos-qlib-finetuning)——支持 CSI300/800/1000、`TopkDropoutStrategy`，可直接在 qlib 中运行。⚠️ **但不发布任何性能数字**，只能当作测量脚手架，不是解决方案
- 社区复现显示：**零样本 Chronos-Bolt 在 A 股 RMSE 上输给 ARIMA（15.24 vs 11.64）**（来源为社区仓库，**[无法验证]** 具体链接与实验设置，仅记录线索）

> ⚠️ **[无法验证]** 我**未能找到** TimesFM / Moirai / Moirai-MoE / Lag-Llama / Sundial / Timer / Toto / MOMENT / UniTS / TinyTimeMixers 在**任何 A 股横截面上**的 IC 或 RankIC 数字。这个空白本身就是一个结论：**这条路线在 A 股尚无公开的量化验证**。

---

## 6. 无法验证 / 明确未能确认的内容

为避免下游误用，以下逐条列出**我没能确认**的事项。**这些都不应被当作"大概是这样"。**

**关于用户简报中的假设（三处需要更正）**：

1. ❌ 用户简报写"The Capacity and Robustness Trade-off (Tan et al.)"——**作者归属有误**，实际为 Lu Han, Han-Jia Ye, De-Chuan Zhan（[arXiv:2304.05206](https://arxiv.org/abs/2304.05206)）。⚠️ 该论文全文**我未能独立抓取**，建议引用前自行复核
2. ❌ 用户简报提到 TimesURGE——**作为时序基础模型不存在**，检索只命中一款日本护发产品
3. ❌ "DFQ-Transformer / DFQ-GRU / DFQ-LSTM"——**不存在**

**未能验证的具体条目**：

| 条目 | 原因 |
|---|---|
| Finance Research Letters 论文的摘要与全部数字（[Zhong, Fu & Zhu, FRL 110:110606](https://doi.org/10.1016/j.frl.2026.110606)） | ScienceDirect 403（两种 URL 形式均失败）；OpenAlex 摘要为 null；Semantic Scholar 429。**⚠️ 且该论文主题是波动率，不是收益/横截面**——用户简报的表述需要更正 |
| [upchina 东方证券研报页](https://zx.upchina.com/report/details/7000846885) | SPA 空壳，正文由 JS 加载，4 个候选 API 端点全部 404 |
| OpenReview 论文 [KgqI1PlmxR](https://openreview.net/pdf?id=KgqI1PlmxR)（150 万条 A 股日频样本） | OpenReview 浏览器验证拦截，模型清单与 IC/RankIC 未确认 |
| Kronos 官方 GitHub 仓库 | 未能定位（多个同名第三方仓库，无法区分官方） |
| Kronos 论文的**绝对** RankIC / MAE 数值 | ✅ 摘要已核实（+93% / −9% / +22%），但均为**相对提升**，论文正文的绝对数值未提取 |
| Kwiatkowski & Chudziak 的 MDAI 2025 论文正文 | Springer 付费墙（[ACM DL](https://dl.acm.org/doi/10.1007/978-3-032-00891-6_19)）。⚠️ **但其同作者的 arXiv 版本已获取**，见 §3.4 |
| The Label Horizon Paradox 的 arXiv 编号与提升幅度 | 仅得 PDF 文本，编号未确认；数字在提取中碎裂 |
| TimeMixer++ 官方代码 | 候选仓库全部 404；搜索仅得 5 star / 0 star 的第三方仓库 |
| 华泰人工智能 99/91/92/94/96 | 仅标题，正文付费墙 |
| 中金大模型系列 (1)-(4)(6)(7) | 未定位 |
| 天风/方正/海通/东吴 | 未发现相关报告 |
| 微信公众号来源 | 全部被风控拦截 |
| 任何 TSFM 在 A 股横截面的 IC/RankIC | 未找到 |
| "证明 TSLib 数字不可复现"的同行评审论文 | **不存在**（用户简报假设其存在） |
| "Are Time Series Foundation Models Ready for Financial Forecasting?" | **未找到该标题的论文** |

**两处原文摘要自相矛盾（疑似原文错误，非我方误读）**：
- 华泰《人工智能 86》：IR 在同一摘要中写成 3.24 与 3.29
- 招商证券：中性化后 RankIC "0.77" 疑为 "10.77" 笔误

---

## 7. 工程判断与建议

### 7.1 对"是否引入 TSLib"的直接回答

**不建议以"接入 TSLib 模型"作为提升选股效果的手段。** 理由按重要性排序：

1. **库已停止演进，维护者自认基准失效**（§1.2）
2. **Qlib 官方模型库零收录**，且 qlib 官方基准显示原生 Transformer 在 Alpha360 上**年化为负**（§3.3）
3. **所有券商横向对照都指向"增量有限"**：招商"基本处于同一水平"、国金 TimeMixer 跑输 GRU（§4.2）
4. **任务错配**：TSLib 无截面排序的目标函数/评估/回测，改造量被严重低估（§3.1）
5. **最强的 TSFM 证据是负面的**（§5.2）

### 7.2 如果一定要做，按 ROI 排序的路径

**第一优先——不换模型，换输入表征。**
Qlib 官方数据显示同一批模型在 Alpha158 → Alpha360 上表现排序完全翻转（LightGBM IR 从 1.0164 降到 0.7632，而 HIST 达到 1.3726）。**在现有 LightGBM 上换成序列型输入，比换任何骨干网络的期望收益都高。** 并且 `Linear` 基线（§3.3 注记）必须先跑通——打不过它就没有继续的意义。

**第二优先——引入为截面排序设计的架构，而不是通用时序骨干。**
Qlib 已内置且被官方基准验证的：HIST、IGMTF、TRA、TCTS、ALSTM、AdaRNN、SFM、GATs。**这些是"股票任务专用"架构，且已在 qlib 里可直接跑。** 用户已有 qlib 环境，接入成本接近零。

**第三优先——排序目标 + 风格残差化 + 可成交价评估。**
STRATA 的两个方法论要求（§4.1b）是**必要条件**：先对风格因子做残差化再算 IC，并用首个可成交价而非收盘价计价。**不做这两步的回测结论不可信。** 同时把损失函数从 MSE 改成排序损失——**§3.4 的对照实验给出了直接证据：架构不变、只换损失函数，Sharpe 从 0.6637 升到 0.7529、最大回撤从 −19.58% 改善到 −15.77%，而测试集 MSE 反而变差。用 MSE 做模型选择会系统性选错模型。** 这也是 TFT 在 qlib 上 IC 0.0358 但 RankIC 0.0116 崩塌的成因。

> 💡 **这是全部建议中成本最低、确定性最高的一条**：不需要新模型、不需要新数据、不需要 GPU，只需要改损失函数和评估口径。§3.4 证明其经济收益与"换骨干网络"同量级。**建议优先于任何模型引入动作。**

**第四优先——若要走 TSFM，只走"金融原生预训练"或"自建小模型"。**
Rahimikia et al. 的结论非常明确：**通用预训练的现成 TSFM 不行，金融数据从零预训练才行**（Chronos-small R² 从 −77.07% 改善到 −3.18%）。所以正确的动作不是"下载 Chronos 跑零样本"，而是"用金融数据自己预训练"——这对大多数团队不现实。**更务实的替代是 Kronos + Qlib 微调管线**（§5.4b），但要注意它不发布任何性能数字。

### 7.3 风险清单

| 风险 | 说明 | 缓解 |
|---|---|---|
| **预训练污染** | 22 个 TSFM 的 401 个数据集中仅 6% 未被见过（§5.3a）。公开 A 股价格序列几乎必然在语料内 | 只用在模型发布日期之后的数据上验证 |
| **MSE→IC 无映射** | MSE 降 5% 可能对应 IC 0.01，扣成本后归零（§5.3d） | 直接用 IC/RankIC/多空净值做模型选择 |
| **风格暴露伪装成 alpha** | 未残差化的 RankIC 会被小市值/低波动倾斜抬高（§4.1b） | 强制风格残差化 |
| **不可成交价计价** | STRATA 用可成交价后多空收益归零（§4.1b） | 用首个可成交价，含涨跌停/停牌 |
| **回测↔实盘 gap** | **本次调研的全部券商报告无一份披露实盘**（§4.2） | 任何新模型先小资金实盘验证 |
| **无人复现** | 本报告引用的**全部数字都是论文/研报自述**，无第三方复现 | 内部复现优先于引用 |
| **TimeMixer++ 无代码** | 见 §2.3 | 不要列入候选 |
| **Kronos 仓库来源不明** | 多个同名第三方仓库（§5.1） | 只用 HF `NeoQuasar/*` |

### 7.4 一句话总结

> **问题不在于"哪个时序模型更强"，而在于"预测什么目标"。** TSLib 解决的是"给定一条序列预测它的未来数值"，A 股选股解决的是"给定今天的全市场预测明天的相对排序"。这两件事共享的只是"时间"这个词。Qlib 四年的实践、券商的一致回测、以及 20 亿观测的学术研究，都指向同一个答案：**换表征、换目标函数、换评估口径，比换骨干网络重要一个数量级。**

---

## 附录：核心链接速查

**代码仓库**
- [thuml/Time-Series-Library](https://github.com/thuml/Time-Series-Library) — 约 1.28 万 star，2026-04 停更
- [microsoft/qlib](https://github.com/microsoft/qlib) — 约 4.85 万 star
- [kwuking/TimeMixer](https://github.com/kwuking/TimeMixer) — TimeMixer ICLR 2024 官方，约 1,983 star
- [thuml/iTransformer](https://github.com/thuml/iTransformer) — 约 2,212 star
- [cure-lab/LTSF-Linear](https://github.com/cure-lab/LTSF-Linear) — DLinear 官方，约 2,515 star
- [google-research/timesfm](https://github.com/google-research/timesfm) — 约 3.2 万 star
- [amazon-science/chronos-forecasting](https://github.com/amazon-science/chronos-forecasting) — 约 5,842 star
- [SalesforceAIResearch/uni2ts](https://github.com/SalesforceAIResearch/uni2ts)（Moirai）— 1,588 star
- [thuml/Sundial](https://github.com/thuml/Sundial) — 228 star

**核心文献**
- [DLinear / Are Transformers Effective for TSF?](https://arxiv.org/abs/2205.13504) — AAAI 2023
- [Rahimikia et al., Re(Visiting) TSFMs in Finance](https://arxiv.org/abs/2511.18578) — **最重要**
- [Kwiatkowski & Chudziak, 股票排序的损失函数对照实验](https://arxiv.org/abs/2510.14156) — **§3.4，成本最低的改进点**
- [STRATA, A 股横截面排序](https://arxiv.org/abs/2608.28060) — 2026-08
- [TimeMixer++ (ICLR 2025)](https://openreview.net/forum?id=1CLzLXSFNn) — 无官方代码
- [Kronos (AAAI) — 金融 K 线基础模型](https://ojs.aaai.org/index.php/AAAI/article/view/39730) — 摘要已核实
- [Noguer i Alonso & Pereira Franklin, TSFMs for Financial Return Forecasting](https://arxiv.org/abs/2606.27100)
- [Łaniewski & Ślepaczuk, Chronos for Stock Index Forecasting](https://aisel.aisnet.org/isd2014/proceedings2025/datascience/18/) — ISD 2025
- [Comparing Transformer Models for Stock Selection（MDAI 2025，付费墙）](https://dl.acm.org/doi/10.1007/978-3-032-00891-6_19)
- [Kinlay, TSFMs for Financial Markets（工程批判）](https://jonathankinlay.com/2026/02/time-series-foundation-models-for-financial-markets-kronos-and-the-rise-of-pre-trained-market-models/)
- [Hyndman, TSFM 污染统计](https://robjhyndman.com/hyndsight/foundation_models.html)
- [Qlib 官方基准表](https://github.com/microsoft/qlib/blob/main/examples/benchmarks/README.md)

**中文研报**
- [东方证券 DFQ-TimesNet 摘要（迈博汇金）](http://m.microbell.com/wap_detail.aspx?id=87becf8be3bbd934854e69c8141605be)
- [华泰人工智能 89（iTransformer + Crossformer）](https://www.sdyanbao.com/detail/866746)
- [中金 Kronos A 股择时（新浪转载）](http://stockfinance.sina.cn/stock/go.php/paper/reportid/813487920250/index.phtml)
