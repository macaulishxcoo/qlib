# A股横截面选股：LLM/金融大模型 与 图神经网络(GNN) 路线调研报告

**调研日期**：2026-09-11 ｜ **视角**：面向中小团队/个人量化的工程可行性评估
**数据来源**：GitHub 页面与 commits atom feed 实抓、raw README/LICENSE、arXiv 与期刊页、券商研报原文页、Tushare/巨潮/东方财富 API 实测、以及本仓库 qlib 源码逐行审阅。
**核心立场**：本报告优先记录**负面发现**（不存在的仓库、跑不通的代码、复现不出的数字），因为在本主题下，负面信息的价值远高于又一堆"某某大模型选股年化 XX%"的宣传。

---

## 0. 一页纸结论（TL;DR）

| 问题 | 结论 | 证据强度 |
|---|---|---|
| FinGPT 还活着吗？ | **活着且仍高频提交**（最后提交 2026-09-08，21,237★），但 2026 年的提交**几乎全是依赖修复与 Docker 化**，模型发布线停在 2023-11 | 我实抓 GitHub commit feed |
| FinGPT-Forecaster 能用吗？ | **对 A 股无用**。仅 DOW30（2022-12~2023-09）、需 Finnhub（美股）API key | 官方 README |
| FinGPT 被用于 A 股吗？ | **被用过一次，且是券商研报级的工作**：国金证券 2023-10 用 FinGPT（ChatGLM-6B+LoRA）做沪深300论坛舆情因子。但**数据来自付费供应商子长科技，个人无法复现** | 券商研报原文 + 网易转载 |
| FinGPT 那个"A股因子评估器"新提交是什么？ | **是一个 86 行的 JSON schema 校验脚本**，不做任何因子计算。**不要被 commit 标题误导** | 我实抓 PR #274 diff |
| RD-Agent 能用 A 股吗？ | **原生支持**：官方 quant 场景硬编码 `~/.qlib/qlib_data/cn_data` + `csi300` + `SH000300`。但你要自备 qlib 数据 | 官方 readthedocs |
| RD-Agent 真实成本与效果？ | 论文自称"单轮 <$10、2 倍 ARR"；**券商独立实测（国联民生 2026-05）只做到双周 IC 0.07，并明确说"不能替代传统研究流程""结果不保证可再次挖到""运行稳定性差"** | 国联民生研报（一手独立实测） |
| LLM 因子挖掘项目里哪些真能跑？ | QuantaAlpha（数据公开在 HF）、RD-Agent、FactorMiner（可零 API key 跑 mock）。**Alpha-GPT / AlphaLogics / AgonAlpha / FinCon / AlphaEvolve 全是没有代码的论文空壳** | 多源交叉核实 |
| "RelationalStock" 这个仓库存在吗？ | **不存在**。真实资产是 RSR 模型，仓库 `fulifeng/Temporal_Relational_Stock_Ranking`（527★），**2021-03 停更、TF1.x、纯美股** | URL 探测 404 + 多语种检索 |
| Qlib 的 GATs 是真图模型吗？ | **你的判断基本正确**：代码里没有任何邻接矩阵/行业边/供应链边，注意力直接在 batch 内两两计算。**但有一个重要细节需要修正**——batch 确实就是"当日全截面"，所以它不是"无意义的 batch 图"，而是"当日截面的全连接自注意力" | **本仓库源码逐行核实** |
| A 股有免费的产业链图数据吗？ | 有且仅有一个：`liuhuanyong/ChainKnowledgeGraph`（771★，100,718 节点/169,153 边）。**但作者自己说它缺定量权重、无法做定量传导推理** | 作者原文 + 我实抓 |
| 舆情数据能免费搞定吗？ | **不能**。Tushare 无情感接口（¥2500/年只有原文）；AkShare 无股吧、无历史归档；已打分数据只有商业供应商。**唯一健康路线是自己落盘 + 自建 BERT 级打分** | 接口实测 |
| 最重要的单条风险提示 | **A 股新闻舆情因子的 IC 符号大概率是负的**（开源证券实测 ICIR = −2.0~−2.3）。"利好新闻→买入"在 A 股是错的 | 开源证券×通联数据 + JPM 2023 论文 |

---

## 1. 证据分级与方法说明

本报告对每条结论标注证据等级：

- **【实抓】**：我或我的协作代理在 2026-09-11 直接 HTTP 抓取/探测得到（GitHub 页面 `stargazerCount` 属性、commits atom feed、raw 文件、API 响应、本地源码）。
- **【一手文档】**：项目官方 README / 文档 / 论文原文。
- **【论文自述】**：作者自己报告、**无第三方复现**的性能数字。
- **【独立实测】**：非作者方在真实数据上跑出的结果（本报告中最有价值的类别，但**极其稀少**）。
- **【未能验证】**：明确说明查不到。

**关于本机环境的两个硬限制**（影响可验证范围，必须声明）：
1. **GitHub REST API 全程 429/403**（IP 配额耗尽、无 token），因此所有 star 数来自 GitHub HTML 页面属性抓取（`repo-stars-counter-star`），提交日期来自 `/commits/<branch>.atom`。
2. **`huggingface.co` 从本机不可达**（curl 返回 000/超时）。因此**我无法独立验证 FinGPT 的 HuggingFace 权重是否仍可下载**。协作代理通过 `hf-mirror.com` 完成了部分 HF 核查，我会标注哪些是镜像结果。

---

## 2. FinGPT 与 AI4Finance 生态

### 2.1 仓库现状（硬数据，全部【实抓】于 2026-09-11）

| 仓库 | Star | 最后提交 | License | 判断 |
|---|---|---|---|---|
| [AI4Finance-Foundation/FinGPT](https://github.com/AI4Finance-Foundation/FinGPT) | **21,237** | **2026-09-08** | MIT | 高频提交，但**性质是维护而非研究** |
| [AI4Finance-Foundation/FinRobot](https://github.com/AI4Finance-Foundation/FinRobot) | 7,966 | 2026-09-07 | — | 活跃 |
| [AI4Finance-Foundation/FinRL](https://github.com/AI4Finance-Foundation/FinRL) | 16,267 | 2026-07-12 | — | 半活跃 |
| [AI4Finance-Foundation/FinNLP](https://github.com/AI4Finance-Foundation/FinNLP) | 1,482 | **2024-07-01** | — | **已死（2 年+ 无提交）** |

**关键发现：FinGPT 的"活跃"具有欺骗性。** 我拉取了最近 12 条 commit 标题：

```
2026-09-08  feat: add A-share factor report evaluator      ← 见 2.3，是个 schema 校验脚本
2026-09-07  Add Docker support for FinGPT Forecaster
2026-09-03  Fix issue #165: Replace deprecated prepare_model_for_int8_training
2026-09-03  Fix issue #269 Triton runtime import error
2026-08-02  Fix num_rows zero issue by adding API key validation
2026-08-01  Fix issue #186: Add offload_folder parameter to prevent KeyError
```

提交者几乎全是 `jellyfishing2346`（维护者），由项目发起人 `BruceYanghy`（Hongyang Yang）合并。**全部是"修依赖、修报错、加 Docker"的维护工作——2026 年没有任何新模型、新数据集或新论文。**

与之吻合的是：**[FinGPT README](https://github.com/AI4Finance-Foundation/FinGPT) 的 "What's New" 段落最后一条停在 2023-11**。也就是说，项目的**模型发布线已经停了约 3 年**，只剩代码在维护。

### 2.2 FinGPT-Forecaster 的产品线：对 A 股无用

[官方 README](https://github.com/AI4Finance-Foundation/FinGPT/tree/master/fingpt/FinGPT_Forecaster) 明确写着：

- 训练数据是 **DOW30 成分股，2022-12-30 ~ 2023-09-01**（约 8 个月），基座 `Llama-2-7b-chat` + LoRA
- 运行**必须**提供 `FINNHUB_API_KEY`（美股行情/新闻数据源）与 `HF_TOKEN`
- 可选的 `ADANOS_API_KEY` 是美股情绪数据
- Gradio `sdk_version: 3.50.2`（2023 年版本，未升级）

**工程判断**：
1. **数据源锁死美股**。Finnhub 不提供 A 股新闻，把它换成 Tushare/巨潮需要重写整个数据层，而不是改配置。
2. **训练窗口只有 8 个月且已过期 3 年**。金融文本的分布漂移极快，2023 年上半年的美股新闻模式对 2026 年的 A 股没有迁移价值。
3. **架构上它是"新闻 → 文字点评 + 涨跌预测"的生成式机器人**，输出是**自然语言**，不是**可排序的截面因子分数**。要从它拿到 `因子值 ∈ ℝ`，你需要再套一层解析，而且它一次只处理**一个 ticker**——**没有截面能力，无法做横截面排序**。这是它和"选股因子"之间的根本性鸿沟，比数据源问题更难修。

### 2.3 ⚠️ 重要辟谣：那个"A股因子评估器"不是因子工具

我拉取了 [PR #274 的完整 diff](https://github.com/AI4Finance-Foundation/FinGPT/pull/274)。新增文件 `fingpt/FinGPT_Benchmark/benchmarks/ashare_factor.py` 共 **86 行**，它做的事情是：

```python
REQUIRED_FIELDS = {"symbol","as_of","factors","risks","recommendation","confidence"}
# 检查 JSON 里字段全不全；factors 是不是非空 list；recommendation 是否 ∈ {buy,hold,sell}
score = 1.0 - min(len(errors), 5) / 5   # 打分完全由"错误条数"决定
```

它自己的 docstring 就已经说清楚了：

> *"The evaluator intentionally does not claim that a recommendation is correct. It checks whether a report contains the fields needed for reproducible review."*

**这是个 JSON schema linter，不是因子评估器。** 它不读 A 股行情、不算 IC、不回测、不接任何数据源。

**这条发现的工程意义**：如果你只看 commit 标题或 PR 标题（"add A-share factor report evaluator"），会误以为 FinGPT 官方开始支持 A 股因子了。**实际上这只是给一份"研报 JSON"做格式检查。** 这正是我建议对所有"某开源项目支持 A 股了"的说法保持怀疑的典型案例。

### 2.4 FinGPT 在 A 股上唯一一次严肃应用（【一手研报】）

**国金证券金融工程 高智威：《Alpha掘金系列之八：沪深300另类舆情增强因子——FinGPT对金融论坛数据情感的精准识别》，2023-10-18**（[网易财经转载全文](https://m.163.com/dy/article/IHAVJKV305384CKJ.html)、[新浪研报页](https://stock.finance.sina.com.cn/stock/view/paper.php?symbol=sh000001&reportid=750841560774&autocallup=no&isfromsina=no)）

这是回答"FinGPT 有没有被用于 A 股因子提取"的关键证据 —— **有，而且做得相当完整**：

**数据**：来自**子长科技**（商业供应商）的金融论坛股民情绪数据，用其 LKM 知识模型把股民言论**关联定位到具体股票**。2018-01-01 ~ 2023-06-30，**超 1,300 万条主帖 + 480 万条评论**，每周平均覆盖**沪深300 中 260+ 只**股票。

**模型**：报告明确说 FinGPT **"V3.1"版本是在中文能力较强的 ChatGLM-6B 基础上 LoRA 微调**而来，情感打分优于原生 ChatGLM-6B。

**因子体系**：情感表达（乐观情感总和）、情感分歧、情感变化三个维度。

**结果（研报口径）**：
- 乐观情感总和因子**单因子 IC = 3.68%**，分位组合单调性良好，**多空组合年化 12.71%**
- 与基本面因子相关性低；**与市值相关性 0.55**（但为降序因子）
- 实盘策略（前 20% 等权、月频、千三手续费）：**年化 6.69%、Sharpe 0.32**；**超额年化 8.02%、IR 1.58、超额最大回撤 6.94%**

**🔧 我的独立工程判读（研报没强调但很重要）**：
1. **多空因子年化 12.71%，但落地多头策略 Sharpe 只有 0.32。** 这说明因子的区分度主要来自**空头端**，而 A 股个人投资者基本无法有效做空。**对多头投资者，这个因子的实际价值远低于 12.71% 这个数字给人的印象。**
2. **"超额年化 8.02%、IR 1.58" 是在 2018-2023 这个沪深300 大幅下跌的窗口里算的。** 基准跌，超额自然好看。**判断因子必须看绝对 Sharpe（0.32），而不是超额 IR。**
3. **因子与市值相关性 0.55 是重大警示。** 这意味着它有一半以上是**小市值暴露的代理变量**。研报说"区别于市值因子其为降序因子"，但这只说明方向相反，**没有证明它是独立 alpha**。做这类因子**必须先做市值中性化再看 IC**。
4. **数据不可复现。** 子长科技是付费供应商，1,300 万条论坛数据的获取成本未知，个人/小团队基本无法复制。
5. **研报本身的风险提示已写明**："大语言模型基于上下文预测进行回答，不能保证回答准确性。"

**结论**：这是一个**方法论上成立、但工程上对个人封闭**的案例。它证明了"LLM 情感因子在 A 股有信号"，**没有**证明"你能用开源 FinGPT 免费复制它"。

### 2.5 ⚠️ 反面教材：FinGPT Issue #250 是一篇推广帖

[FinGPT Issue #250](https://github.com/AI4Finance-Foundation/FinGPT/issues/250) 标题是《实战经验：将 FinGPT 情感信号融合进多因子 A 股量化框架 + 免费开放 API 接入》，看起来很相关。我拉取了正文，**它实际上是一篇为 `agentpit.io` 付费转化引流的推广帖**：

- 声称"实测 2026 年 3~6 月 A 股震荡市中，融合后信号准确率比单独使用 FinGPT 提升约 **18%**（基于历史回测）"
- **4 个月样本、无代码、无回测细节、无交易成本定义、无 IC/Sharpe**，且"准确率"与"因子收益"之间没有映射关系
- 文末引导注册 `agentpit.io` 并加微信群
- 架构图里混入了 `Kronos`（一个 K 线基础模型），来源是另一个仓库 `hangeaiagent/kronos-free-api`

**不过它提出的三条定性观察是有价值且与学术文献一致的**，我在第 5 节会再次引用：
1. **利好已 price-in**：新闻 positive，但机构早已建仓，消息公布当日反而高位减仓
2. **利空被预期**：负面公告早有预期，真实影响是 neutral
3. **情感与资金背离**：新闻 negative，但主力净流入持续为正

### 2.6 FinGPT 的已知批评（分级说明）

**A. 独立学术评测（【独立实测】，最有价值）**

[Djagba & Odinakachukwu, *Assessing the Capabilities and Limitations of FinGPT Model in Financial NLP Applications*, arXiv:2507.08015, 2025-07](https://arxiv.org/abs/2507.08015)：

> FinGPT 在**分类任务**（情感分析、标题分类）上表现强，常与 GPT-4 相当；但在**推理与生成任务**（金融问答、摘要）上显著更弱，在**数值准确性与复杂推理**上差距明显。结论：**"not yet a comprehensive solution"**。

**对量化的含义**：情感分类恰好是 FinGPT 的强项——这与国金证券能用它做出因子是一致的。**但不要指望它做数值推理（如从财报算比率），那正是它最弱的地方。**

**B. 数据合规（【未能完全验证】，但风险结构清晰）**

- FinGPT 的数据管道依赖 [FinNLP](https://github.com/AI4Finance-Foundation/FinNLP) 抓取互联网金融数据。**FinNLP 最后提交 2024-07-01，已停更 2 年**——意味着其抓取器对上游改版基本已失效。
- **代码 License 是 MIT（我实抓 LICENSE 确认），但 MIT 只覆盖代码，不覆盖数据。** 训练语料（社媒、新闻）的授权状态在仓库中**没有清晰声明**。这是"数据许可"批评的核心，但**我未找到 FinGPT 因此被正式投诉或下架的记录**——这一点我标注为**未验证**。
- **可操作建议**：把 FinGPT 当作**模型架构 + 训练配方**的参考，**不要直接使用其训练数据或发布的权重做商用**，除非你能独立确认数据来源合规。

**C. 基准"挑选"（benchmark cherry-picking）**

我**没有找到**直接指控 FinGPT 论文挑选基准的公开文献。但有一个**结构性观察**值得注意：FinGPT 的论文都发在 **workshop**（[ NeurIPS 2023 Instruction Workshop](https://arxiv.org/abs/2310.04793)、[IJCAI 2023 FinLLM Workshop](https://arxiv.org/abs/2306.06031)、[ICAIF-23](https://arxiv.org/abs/2310.04027)），而非主会。**Workshop 论文的评测标准与主会不同**，且 FinGPT 的评测长期以自建的 FinGPT-Benchmark 为主。**我把它标注为"评测独立性存疑"，而不是"已被证实挑选基准"**。

**D. 可复现性投诉（【实抓】GitHub issue 标题）**

从 commit 修复的 issue 编号可以看出**长期存在的可用性问题**：#165（`prepare_model_for_int8_training` 已废弃）、#186（KeyError，需加 `offload_folder`）、#269（Triton 导入错误）、#179（num_rows 为 0）。这些都是**环境/依赖层面的破窗**，2026 年才被陆续修掉——说明该项目有一段时间处于"能 star 不能跑"的状态。

### 2.7 成本—收益：给个人/小团队的诚实账

**❌ 不推荐路径：自己微调 FinGPT 做 A 股情感**
- Llama-2-7b/13b LoRA 微调需要 16–24GB 显存；**但真正的成本不是 GPU，是标注数据**。要覆盖 A 股需要数万条人工标注的中文金融文本，这才是不可逾越的门槛。
- 而且——**你根本不需要 7B 模型**。情感三分类是 `bert-base` 级别的任务（见第 5 节），用 LLM 做情感打分是**用 100 倍成本换更差的稳定性**。

**✅ 推荐路径：把 FinGPT 当参考实现，把预算花在数据和因子上**
- 直接使用本节的结论：**LLM 情感因子在 A 股确有信号（国金证券已验证），但成败取决于数据覆盖与实体链接，而不是模型大小。**
- 具体方案见第 5.4 节。

**一句话**：FinGPT 值得读代码、不值得部署；它的价值是"证明这条路走得通"，而不是"给你一个能用的工具"。

---

## 3. LLM 自动化因子挖掘

### 3.1 Microsoft RD-Agent / RD-Agent(Q)

**仓库事实【实抓】**：[microsoft/RD-Agent](https://github.com/microsoft/RD-Agent)，**14,582★**，MIT License，最后提交 **2026-09-04**。
**不存在独立的 `microsoft/RD-Agent-Quant` 仓库**（404）；RD-Agent(Q) 是主仓里的 `rdagent/scenarios/qlib` 场景。

**A 股兼容性：【一手文档】确认原生支持。**

[官方 quant 文档](https://rdagent.readthedocs.io/en/latest/scens/quant_agent_fin.html) 的默认配置直接写着：

```yaml
provider_uri: ~/.qlib/qlib_data/cn_data    # 中国A股 qlib 数据
market: csi300                              # 沪深300
benchmark: SH000300
train: 2008-01-01 ~ 2014-12-31
valid: 2015-01-01 ~ 2016-12-31
test:  2017-01-01 ~ 2020-08-01
strategy: TopkDropoutStrategy (topk=50, n_drop=5)
cost: open 0.0005 / close 0.0015 / min 5
```

四个场景：`fin_factor`（只挖因子）、`fin_model`（只搜模型）、`fin_quant`（因子-模型联合优化）、`fin_factor_report`（从财报抽因子）。

**但"原生支持"≠"开箱即用"**：
- **必须自备 qlib `cn_data` bundle**。官方文档**缺失这一步的前置说明**，用户直接踩坑——见 [Issue #1335 "[Docs][Quant] Missing Qlib data prerequisite instructions"](https://github.com/microsoft/RD-Agent/issues/1335)。
- **必须 Linux + Docker**（Windows 需 WSL2），**每个因子在隔离的 Conda 环境里跑**。
- 中文社区反馈：关键补丁被放在**付费知识星球**里。CSDN 教程原文称*"如果直接运行官方代码的话会遇到各种报错……首先从星球获取修改后的 Dockerfile，替换官方的 Dockerfile"*。

**B. 论文自述（【论文自述】，NeurIPS 2025）**

论文：[arXiv:2505.15155](https://arxiv.org/abs/2505.15155)（NeurIPS 2025 Datasets & Benchmarks Track 接收）。
README 自述：*"at a cost under $10, RD-Agent(Q) achieves approximately 2× higher ARR than benchmark factor libraries while using over 70% fewer factors."*

CSI300、2017-01~2020-08 测试期、o3-mini 后端（据 [saulius.io 的论文解读](https://saulius.io/blog/automated-quant-research-ai-agents-rd-agent)）：**IC 0.0532 / ARR 14.21% / IR 1.7382 / MDD −7.42%**，对比 Alpha158+LightGBM 的 IC 0.0420 / ARR 6.80%。多臂老虎机调度器消融：bandit (IC 0.0532/ARR 14.21%) > LLM 选择 (0.0476/10.09%) > 随机 (0.0445/8.97%)。

**⚠️ 我的判读**：测试期截止 **2020-08-01，距今 6 年**。2017–2020 的沪深300 是众所周知的有利窗口。**没有发表后的真样本外验证。**

**C. 🔥 唯一的独立实测（【独立实测】，本报告最有价值的证据之一）**

**国联民生证券 叶尔乐：《AGENT专题报告 RD-AGENT实测：AI驱动的因子挖掘框架》，2026-05-20**
（[新浪财经研报全文](http://stock.finance.sina.com.cn/stock/go.php/vReport_Show/kind/strategy/rptid/832591048933/index.phtml)）

这是**目前公开可查的唯一一份对 RD-Agent 的 A 股独立实测**，且细节充分：

| 维度 | 实测结论 |
|---|---|
| 场景 | `fin_factor`，模型固定 LightGBM，新因子与 Alpha158 的 158 个量价特征合并 |
| 数据 | **Wind A 股 5,792 只、165 字段，财务数据全部按公告日 PIT 对齐**（注意：Wind，非免费 qlib 数据） |
| 结果 | **36 个有效 Loop，组合双周频 IC 提升至 0.07**；触发 11 次 SOTA 更新 |
| 有效因子类型 | 交叉/交互、盈利质量、分析师预期、现金流 四类为主力 |
| **LLM 对比** | **GLM-V5.1 全面优于 DeepSeek-V3.2**。后者**频繁陷入无限重复输出**，行业截面因子**多个提案全部编码失败** |
| **关键结论** | **"在本场景下模型的代码工程能力比单纯推理能力更关键"** |
| **负面发现** | **"组合 ICIR 的提升始终弱于 IC"**；**机器学习类因子在激进参数下过拟合明显** |
| 最终定位 | **"宜定位为'具升级潜力的辅助因子研究工具'，效率可达人工的数十倍，但暂不能替代传统研究流程"** |
| 明列劣势 | **运行稳定性差、LLM 代码质量不稳定、IC 优化目标与实盘收益脱钩、对 A 股特殊机制与前视偏差等细节把握不足** |
| **可复现性风险** | **"LLM 挖掘因子具有一定随机性，报告中得到的因子仅代表单次运行结果，不保证可再次按顺序挖到"** |

**🔧 我的判读**：
1. **"IC 提升至 0.07" 需要正确解读**。这是**双周频** IC，且是**与 Alpha158 合并后**的组合 IC——**不是新增因子的独立 IC**。0.07 的双周 IC 在 A 股属于可用但不惊艳的水平。
2. **"ICIR 提升始终弱于 IC" 是最重要的技术发现**。这意味着新因子提升了**平均预测力**，但没有提升**预测稳定性**。对实盘而言 ICIR 比 IC 重要得多——**收益的稳定性取决于 ICIR，而不是 IC**。这条负面结论比论文的"2 倍 ARR"更有信息量。
3. **"结果不保证可再次按顺序挖到" 直接否定了可复现性**。对研究流程而言这是硬伤：你无法审计、无法回归测试、无法把因子挖掘纳入 CI。
4. **LLM 选择的反直觉结论值得记住**：不是"哪个模型更聪明"，而是"哪个模型更能写出可运行的代码"。**这解释了为什么弱模型省钱是假象——提案大面积编码失败的调试时间成本远超省下的 token 费。**

**D. 第三方横评：与论文自述差一个数量级（【独立实测】但需打折）**

竞品论文 AlphaLogics（[arXiv:2603.20247](https://arxiv.org/abs/2603.20247)）Table 1 把多个方法拉到**统一的 CSI500 + 2021-01~2024-12 窗口**重跑：

| 方法 | CSI500 IC | CSI500 AR | CSI500 IR |
|---|---|---|---|
| LightGBM | 0.0116 | 0.88% | 0.0782 |
| AlphaForge | 0.0111 | 3.15% | 0.3020 |
| **RD-Agent** | **0.0112** | **1.01%** | **0.0930** |
| AlphaAgent | 0.0221 | 12.46% | 1.2230 |
| AlphaLogics（自己） | 0.0251 | 16.72% | 1.5266 |

**RD-Agent 的第三方实测 IC 0.0112 / AR 1.01%，而论文自述是 IC 0.0489 / ARR 14.61% —— 差距接近一个数量级。**

**⚠️ 必须打折看**：AlphaLogics 是**竞品**，且未公开 baseline 的复现配置与代码。市场不同（CSI500 vs CSI300）、窗口不同（2021-2024 vs 2017-2020）也能解释一部分差距。**但无论哪种解释，"论文数字可以直接外推"这个假设都不成立。**

**E. 维护现状的一个观察【实抓】**

我拉了 RD-Agent 近 12 条 commit：2026-09 的全部是 `ci:`、`fix: harden ...`、`docs:`。**并且 2026-05-06 到 2026-08-04 之间有约 3 个月无提交。** 最近与 quant 相关的是 2026-04-28 的 AutoRL-Bench。**项目重心正在从"量化场景"转向通用 R&D/RL benchmark。**

### 3.2 其他 LLM 因子挖掘项目：真能跑的 vs 论文空壳

> 下表的星数与最后提交均由协作代理在 2026-09-11 通过 GitHub 页面直抓。**注意**：ecosyste.ms 等元数据镜像对部分仓库缓存过期甚至误报不存在（例如 `RL-MLDM/alphagen` 被误报 not found，实际 1,228★），因此**不要用二手数据源核对仓库存在性**。

#### ✅ 真能跑，值得上手

| 项目 | 仓库 | Star | 为什么值得试 |
|---|---|---|---|
| **QuantaAlpha** | [QuantaAlpha/QuantaAlpha](https://github.com/QuantaAlpha/QuantaAlpha) | **1,516** | ⭐ **唯一把 qlib A股数据直接放 [HuggingFace](https://huggingface.co/datasets/QuantaAlpha/qlib_csi300) 的项目**（`cn_data.zip` 2016–2025），无需专有数据、无需百度网盘；默认 `deepseek-v3`，兼容任意 OpenAI 端点；有 Web UI 与复现文档。论文 [arXiv:2602.07085](https://arxiv.org/abs/2602.07085) |
| **RD-Agent** | [microsoft/RD-Agent](https://github.com/microsoft/RD-Agent) | 14,582 | 生态最全、有券商独立实测。**但工程门槛最高**（Linux+Docker+自备 qlib 数据） |
| **FactorMiner** | [minihellboy/factorminer](https://github.com/minihellboy/factorminer) | 110 | ⭐ **唯一无需 API key 即可跑 deterministic demo/mock**，可零成本验证。工程契约规范（CPCV/PBO、证据包、MCP server）。**但很可能是第三方复现而非官方实现** |
| **AlphaForge** | [dulyhao/alphaforge](https://github.com/dulyhao/alphaforge) | 427 | AAAI 2025，代码完整，qlib 生态。**注意：非 LLM，是 RL/GP/DSO 路线** |
| **AlphaGen** | [RL-MLDM/alphagen](https://github.com/RL-MLDM/alphagen) | 1,228 | RL 公式化因子挖掘，qlib 数据。**非 LLM** |

**关于 QuantaAlpha 的一个可信度加分项**：它自述 CSI300（2022–2025）**IC 0.0472 / RankIC 0.0459 / ARR 4.68% / IR 0.6453 / MDD 11.80%**。**ARR 只有 4.68%、IR 0.645 —— 这个量级反而比那些动辄 IR 1.5 的项目更可信。** 一个愿意把 IC 0.047 和 ARR 4.68% 一起报出来的团队，比只报超额收益的更值得信任。**但我未找到任何独立复现，仍是【论文自述】。**

#### ⚠️ 有条件能跑（有硬门槛）

| 项目 | 仓库 | Star | 门槛 |
|---|---|---|---|
| **AlphaAgent** | [RndmVariableQ/AlphaAgent](https://github.com/RndmVariableQ/AlphaAgent) | 409 | ⚠️ **论文实现已被作者于 2026-07 整体覆盖重写**（见下） |
| **pwb-alphaevolve** | [paperswithbacktest/pwb-alphaevolve](https://github.com/paperswithbacktest/pwb-alphaevolve) | 127 | README 明确要求 **OpenAI o3 + 付费数据集**，成本双重壁垒 |
| **QuantEvolve** | [tarsyang/quantevolve](https://github.com/tarsyang/quantevolve) | 50 | 币安加密数据 + Gemini，小众 |

**⚠️ AlphaAgent 是一个重要的工程陷阱。**

论文 [arXiv:2502.16789](https://arxiv.org/abs/2502.16789) 的 comment 字段确实指向 `RndmVariableQ/AlphaAgent`，**仓库身份已验证为真**。**但仓库内容在 2026-07-01~03 被整体替换了**：
- **旧实现**（论文那版，commit `4899e68`）：从 RD-Agent 分叉，**qlib + Docker + A股（CSI500）**，含 `prepare_cn_data.py`、`Makefile`、`LICENSE`
- **新 HEAD**：改成 **Tushare + AgentScope + 自研 DSL**，依赖里**没有 qlib、没有 Docker**，且 **HEAD 没有 LICENSE 文件**
- 数据需 `TUSHARE_TOKEN` 或百度网盘包（**再分发受限**）

**你现在 clone 到的不是发论文的那份代码。** 论文实现只能 `git checkout 4899e68` 从历史里捞。

**不过 AlphaAgent 有一个罕见的正面证据**：AlphaLogics 的横评 Table 1 在**同一 CSI500、同一 2021-01~2024-12 窗口**重跑 AlphaAgent，得 **IC 0.0221 / AR 12.46% / IR 1.2230**，与作者自述的 **IC 0.0212 / AR 11.00% / IR 1.5** 高度吻合。**这是本次调研中找到的唯一"论文数字被第三方基本跑出来"的案例。**（仍要打折：来源是竞品。）

#### ❌ 论文空壳 / 无代码（负面清单）

| 项目 | 负面事实 |
|---|---|
| **FinCon**（NeurIPS 2024） | [The-FinAI/FinCon](https://github.com/The-FinAI/FinCon) 68★，**整个仓库只有一个 README**。README 称*"plan to release the code within the next 3–4 months"* —— **该承诺已过期一年多**。同组 [INVESTOR-BENCH](https://github.com/felis33/INVESTOR-BENCH) 仅 1★；宣传的 `The-FinAI/Agent_Market_Arena` **404**。**教材级空壳** |
| **Alpha-GPT / 2.0** | **官方从未开源**。⚠️ **任务描述里的 arXiv 号 2309.07938 是错的**（那是 *"An Assessment of ChatGPT on Log Data"*）；正确的是 [arXiv:2308.00016](https://arxiv.org/abs/2308.00016)（IDEA/港科大）。所有同名仓库均为第三方蹭名，最大的 [parthmodi152/alpha-gpt](https://github.com/parthmodi152/alpha-gpt)（217★）自认 *"Under Development"* |
| **AlphaEvolve（DeepMind）** | ⚠️ **从未开源**。[google-deepmind/alphaevolve](https://github.com/google-deepmind/alphaevolve) **实测 404**。官方只放了两个周边仓库： [alphaevolve_results](https://github.com/google-deepmind/alphaevolve_results)（300★）和 [alphaevolve_repository_of_problems](https://github.com/google-deepmind/alphaevolve_repository_of_problems)（234★）。**前者的 README 白纸黑字写着："This repository does *not* contain the code to run AlphaEvolve."** |
| **AlphaLogics** | **无代码**，候选仓库名均 404。[arXiv:2603.20247](https://arxiv.org/abs/2603.20247)。**但它那份统一横评表格极有价值**（见 3.1 D） |
| **AgonAlpha** | **无代码**，依赖闭源 WorldQuant BRAIN 平台评测 → 理论不可复现。[arXiv:2608.11250](https://arxiv.org/abs/2608.11250)。其自述的 "Fitness 9.50 / Sharpe 3.48" 是**平台内部分级**，**不等于实盘业绩**，且 BRAIN 提交流程本身存在严重的多重检验/幸存者偏差 |
| **SHA888/openevolve** | **0★**，3 天就停更的死副本。**正典是 [algorithmicsuperintelligence/openevolve](https://github.com/algorithmicsuperintelligence/openevolve)（7,348★ Apache-2.0）**，但它是**通用**进化编码 agent，**不含任何金融场景** |
| **QuantAgent (arXiv:2402.03755)** | 未找到官方代码仓库。⚠️ 另外 **QuantAgent 至少有 4 个不同实体**，且 [arXiv:2509.09995](https://arxiv.org/abs/2509.09995) 已被作者改名为 **QuantHarness**，与仓库 [irsath/quantagent](https://github.com/irsath/quantagent)（**1★**）名字脱节。**没有任何一个 QuantAgent 做横截面因子挖掘**（都是日内交易决策） |

**⚠️ 一个必须澄清的命名混淆**：存在**两个完全无关的 "AlphaEvolve"** —— DeepMind 的进化编码 agent（2025，未开源），和 NUS/SUTD 的量化学习框架 *"AlphaEvolve: A Learning Framework to Discover Novel Alphas in Quantitative Investment"*（[arXiv:2103.16196](https://arxiv.org/abs/2103.16196), SIGMOD 2021）。**这是"AlphaEvolve 做量化"这个说法的混淆根源。** DeepMind 公开的 AlphaEvolve 应用领域**全是数学、TPU 内核、调度、生物，零个金融结果**。

### 3.3 成本维度小结

| 档位 | 项目 | 说明 |
|---|---|---|
| **零成本可验证** | FactorMiner | 无需 API key 即可跑 mock workflow |
| **低档可跑** | QuantaAlpha、AlphaAgent 新版 | 默认 deepseek-v3 / 任意 OpenAI 兼容端点 |
| **中高档（实际需求）** | **RD-Agent(Q)** | 论文主结果用 GPT-4o / o3-mini；**券商实测显示 DeepSeek-V3.2 大量编码失败，GLM-V5.1 明显更优** |
| **必须贵模型** | pwb-alphaevolve、irsath/quantagent | 明确要求 o3 / gpt-4o |
| **无 LLM** | AlphaForge、AlphaGen | 纯 RL/GP/DSO，只有算力成本 |

**关于"不到 $10 挖一晚"**：这是 RD-Agent(Q) 论文的成本自述。**应视为乐观下限而非可规划预算** —— 论文未说明是哪一轮规模、哪个模型、是否含失败重试；券商实测 36 个 Loop 的成本未披露。
**隐性成本远大于 token 成本**：Docker 镜像、每因子一个隔离 Conda 环境、qlib 数据准备与 PIT 对齐、CoSTEER 最多 10 轮自调试的算力/时间、以及高失败率导致的重跑。

---

## 4. GNN / 关系型选股

### 4.1 🔬 Qlib 的 GATs 到底是不是真图模型？（本仓库源码逐行核实）

**这是本次调研中我唯一可以给出确定性结论的部分，因为我直接读了本仓库的源码。**

**涉及文件**（本仓库路径）：
- `qlib/contrib/model/pytorch_gats.py`（384 行）
- `qlib/contrib/model/pytorch_gats_ts.py`（393 行，实际被 benchmark 使用的版本）
- `examples/benchmarks/GATs/workflow_config_gats_Alpha158.yaml`

**代码事实：**

```python
# pytorch_gats.py, GATModel.forward()
def forward(self, x):
    x = x.reshape(len(x), self.d_feat, -1)   # [N, F, T]
    x = x.permute(0, 2, 1)                   # [N, T, F]
    out, _ = self.rnn(x)                     # GRU/LSTM 时序编码
    hidden = out[:, -1, :]                   # [N, hidden]
    att_weight = self.cal_attention(hidden, hidden)   # ← 关键
    hidden = att_weight.mm(hidden) + hidden  # 残差聚合
    ...

def cal_attention(self, x, y):
    sample_num = x.shape[0]                            # N = 当日股票数
    e_x = x.expand(sample_num, sample_num, dim)        # [N, N, dim]
    e_y = torch.transpose(e_x, 0, 1)                   # [N, N, dim]
    attention_in = torch.cat((e_x, e_y), 2).view(-1, dim * 2)  # [N*N, 2*dim]
    attention_out = self.a_t.mm(torch.t(attention_in)).view(sample_num, sample_num)
    att_weight = self.softmax(self.leaky_relu(attention_out))
```

**结论 1：没有任何图结构。** 代码中**不存在**邻接矩阵、不存在行业/供应链/相关性边、不存在边特征（edge features）。注意力权重的唯一输入是**节点自身的特征**。它实现的是 **N×N 的稠密自注意力（self-attention）**，数学上等价于一张**完全图**上的 GAT，且边权完全由节点特征导出。

**结论 2：官方 README 自己承认了这一点。** [GATs README](https://github.com/microsoft/qlib/blob/main/examples/benchmarks/GATs/README.md) 原文：

> *"The nodes in stacked layers have different weights and they are able to attend over their neighborhoods' features, **without requiring any kind of costly matrix operation (such as inversion) or depending on knowing the graph structure upfront**."*

**"不依赖预先知道图结构"就是"没有用图结构"的同义表述。**

**结论 3（⚠️ 对用户判断的修正）：batch 不是"随便一个 batch"，它就是当日全截面。**

这是我认为需要修正你的原始判断的地方。两个版本都按**交易日**分组：

```python
# pytorch_gats.py
def get_daily_inter(self, df, shuffle=False):
    daily_count = df.groupby(level=0, group_keys=False).size().values   # level=0 = datetime
    ...
# pytorch_gats_ts.py
class DailyBatchSampler(Sampler):
    self.daily_count = pd.Series(index=..., ).groupby("datetime", ...).size().values
```

每个 batch = **某一个交易日的全部股票**。所以：

- ❌ **它不是"batch 维度的伪图"**（那不是无意义的随机 batch）
- ✅ **它是"当日横截面的全连接自注意力图"** —— 节点在语义上确实是"同一天的股票"，这是一个**合理的截面图**
- ❌ **但它仍然不是"关系型图模型"** —— 没有利用任何**股票之间的先验关系**（行业、供应链、分析师共同覆盖、股东关联）

**准确的表述**：Qlib 的 GATs = **"时序编码器（GRU/LSTM）+ 当日截面的稠密自注意力层"**。叫它 GNN 勉强可以（完全图也是图），但**把它当作"关系型/图结构选股模型"来用是错的**——它学到的关系是每个 batch 现算的、不可跨日复用的、没有语义的注意力权重。

**结论 4：O(N²) 复杂度让它无法扩展到全 A 股。**

我按代码里的张量构造估算了显存（`attention_in` 是 `[N*N, 2*hidden]` 的 float32，hidden=64）：

| 当日股票数 N | `attention_in` 显存 | att_weight |
|---|---|---|
| 300（沪深300） | 0.05 GB | 0.4 MB |
| 800（中证800） | 0.33 GB | 2.6 MB |
| 3,000 | **4.61 GB** | 36 MB |
| **5,000（全 A 股）** | **12.80 GB** | 100 MB |

**这是硬约束**：benchmark 配置用的是 `csi300`（约 300 只/日），所以能跑。**如果你想用全 A 股（约 5,000 只/日），单层注意力就需要 12.8GB 显存，必然 OOM。** 要用必须改成 top-k 稀疏注意力或分块——而 qlib 当前实现**没有提供这个选项**。

**结论 5：它的性能在 qlib 自己的基准里只是中游。**

[qlib benchmarks](https://github.com/microsoft/qlib/blob/main/examples/benchmarks/README.md)（CI 多次运行均值±std）：

| 模型 | 数据集 | IC | ICIR | RankIC | 年化 | IR | MaxDD |
|---|---|---|---|---|---|---|---|
| GATs | Alpha158(选20特征) | 0.0349 | 0.2511 | 0.0462 | 4.97% | 0.7338 | −7.77% |
| GATs | Alpha360 | 0.0476 | 0.3508 | 0.0598 | 8.24% | 1.1079 | −8.94% |
| **HIST** | Alpha360 | **0.0522** | 0.3530 | **0.0667** | **9.87%** | **1.3726** | **−6.81%** |
| IGMTF | Alpha360 | 0.0480 | 0.3589 | 0.0606 | 9.46% | 1.3509 | −7.16% |
| TRA | Alpha360 | 0.0485 | 0.3787 | 0.0587 | 9.20% | 1.2789 | −8.34% |
| GRU | Alpha360 | 0.0493 | 0.3772 | 0.0584 | 7.20% | 0.9730 | −8.21% |
| Transformer | Alpha360 | — | — | — | −2.70% | −0.34 | −16.53% |

**两个关键判读**：
1. **GATs 在 Alpha158 上（IC 0.0349 / ARR 4.97%）甚至不如简单的 GRU（0.0315/3.44%，但它只用了 20 个特征）——更远不如 XGBoost（0.0498/7.80%）和 CatBoost（0.0481/7.65%）。** 在 Alpha360 上 GATs 表现好一些（ARR 8.24%），但**仍然低于 HIST（9.87%）、IGMTF（9.46%）、TRA（9.20%）**。
2. **真正带图结构的 HIST 确实赢了 GATs —— 但优势很小**（Alpha360 RankIC 0.0667 vs 0.0598，约 +11%），而且 **HIST 的 ICIR（0.3530）反而输给 TRA（0.3787）**。

**给上游的直接建议**：**如果你的目标是"在 A 股用图结构建模"，不要从 Qlib 的 GATs 入手**，它是个自注意力 baseline。直接用 **HIST**（有真概念图）或 **IGMTF**（有数据驱动的 top-k 图）。

### 4.2 Qlib 里真正的图模型：HIST 与 IGMTF（本仓库【实抓】+【一手文档】）

我原本以为 qlib 只有 GATs 一个"图"模型，实际上 `qlib/contrib/model/` 下有 **HIST、IGMTF、KRNN、TCTS、TRA** 等多个相关实现，且 `examples/benchmarks/` 下都有对应配置。

**HIST —— 用真实的外部概念图（唯一有真图的）**

```python
# pytorch_hist.py
if not os.path.exists(self.stock2concept):
    url = "https://github.com/SunsetWolf/qlib_dataset/releases/download/v0/qlib_csi300_stock2concept.npy"
    urllib.request.urlretrieve(url, self.stock2concept)
...
stock_to_concept = concept_matrix          # 真实的 股票×概念 二分图关联矩阵
hidden = torch.t(stock_to_concept).mm(x_hidden)     # 股票 → 概念 聚合
concept_to_stock = self.cal_cos_similarity(x_hidden, hidden)  # 概念 → 股票 注意力
```

- **这是真图**：`stock2concept` 是沪深300 的**概念/主题归属矩阵**，来自外部数据文件（自动从 GitHub 下载）。
- **配置**：`examples/benchmarks/HIST/workflow_config_hist_Alpha360.yaml` 里 `stock2concept: "benchmarks/HIST/qlib_csi300_stock2concept.npy"`。
- ⚠️ **三个重要限制**：(1) **只支持 csi300**，文件是固定的，无法直接用于全 A 股；(2) 该 `.npy` 是一个**静态快照**，没有时间维度 → **用它做长周期回测会有前视/幸存者偏差**（概念归属是"现在"的，不是"当时"的）；(3) 官方仓库 [Wentao-Xu/HIST](https://github.com/Wentao-Xu/HIST)（304★）**最后提交 2022-09-05**，qlib 内的实现是重新写的。

**IGMTF —— 数据驱动的实例图**

```python
# pytorch_igmtf.py
def cal_cos_similarity(self, x, y):
    xy = x.mm(torch.t(y)); cos_similarity = xy / (x_norm.mm(torch.t(y_norm)) + 1e-6)
...
agg_out = torch.sparse.mm(cos_similarity, self.project2(sample_train_hidden))
```

IGMTF 通过**隐状态的余弦相似度 + top-k 稀疏化**在股票之间建边。**它也是真图，但边是从数据里学出来的，不是先验知识。** 相比 GATs 的稠密全连接，它的稀疏化让它更可扩展。性能优于 GATs（Alpha360 ARR 9.46% vs 8.24%）。

**KRNN / TCTS / TRA**：都不是图模型（分别是 CNN、样本重加权、时序增强），列在这里是为了说明 **qlib 的"图模型"只有 GATs / HIST / IGMTF 三个**。

### 4.3 「RelationalStock」核查：❌ 该仓库不存在

**三重否定【实抓】**：
- `github.com/RelationalStock/RelationalStock` → **404**
- `github.com/relational-stock/RelationalStock` → **404**
- ecosyste.ms 元数据镜像按 `RelationalStock` 查询 → `Repository not found`
- 多轮中英文检索**从未返回任何以此命名的仓库**

**「RelationalStock」是命名讹传，不是任何真实 GitHub 仓库名。**

**真实资产** = 论文 *Temporal Relational Ranking for Stock Prediction*（Feng et al., TOIS 2019，[arXiv:1809.09441](https://arxiv.org/abs/1809.09441)），模型名 **RSR（Relational Stock Ranking）**，仓库：

**[fulifeng/Temporal_Relational_Stock_Ranking](https://github.com/fulifeng/Temporal_Relational_Stock_Ranking)**

| 项 | 值 |
|---|---|
| Star / Fork | **527 / 181**【实抓】 |
| 最后提交 | **2021-03-04 → 5.5 年无维护** |
| License | AGPL-3.0 |
| 环境 | **Python 3.6 + TensorFlow > 1.3**（TF1 已 EOL） |
| 数据 | **NASDAQ / NYSE**，Google Finance 30 年 EOD，实验集 `data/2013-01-01` |
| 关系图 | **sector_industry（行业）+ wikidata（维基）**，均**美股** |
| 预训练权重 | 需从 **Google Drive** 下载 sequential embedding（**链接腐烂风险**） |

**✅ 可运行性**：代码结构完整（`preprocess/eod.py`、`sector_industry.py`、`wikidata.py`、`training/rank_lstm.py`、`training/relation_rank_lstm.py`），数据随仓库分发（需自己 `tar zxvf relation.tar.gz`）。

**❌ 但对 A 股完全不可用**，且工程上已接近不可用：
1. **硬编码美股**。行业图来自 NASDAQ/NYSE 的 sector/industry，Wiki 图来自英文维基。要换成 A 股需要**重建全部关系数据和标的映射**。
2. **TF1.x + Python 3.6**。2026 年需要容器化或降级环境；TF1 的很多 API 已被移除。
3. **关系类型是"行业 + 维基"**，这两类图**在 A 股都有更好的替代**（申万行业 PIT 成分、产业链图谱——见 4.5）。
4. ⚠️ **一个易误读细节**：README 内的数据链接指向 `hennande/Temporal_Relational_Stock_Ranking`，但访问该 URL **返回的是 fulifeng 仓库页面**（标题与 star 数一致）—— 即 **`hennande` 是原作者改名，不是第三方复刻**。

**「RS-Rank」这个缩写无任何对应论文或代码**（不存在或未验证）。

**相关的第三方实现**：[PEIYUNHUA/DGRCL](https://github.com/PEIYUNHUA/DGRCL)（6★，最后提交 2024-12-09，环境现代：torch 2.0.1 + torch_geometric 2.3.1），对应论文 *Dynamic Graph Representation with Contrastive Learning for Financial Market Prediction*（ICAART 2025，**论文标题我未独立核对**）。

### 4.4 其他 GNN 股票模型仓库（全部【实抓】）

| 仓库 | Star/Fork | 最后提交 | 权重 | 数据 | A股 | 独立复现 |
|---|---|---|---|---|---|---|
| [TongjiFinLab/THGNN](https://github.com/TongjiFinLab/THGNN) | **127**/17 | **2023-08-31** | 无 | **CSI300** | ✅ 原生 | 未验证 |
| [Wentao-Xu/HIST](https://github.com/Wentao-Xu/HIST) | **304**/82 | **2022-09-05** | 无 | Qlib cn_data | ✅ 原生 | ✅ 见 4.1 |
| [SJTU-DMTai/MASTER](https://github.com/SJTU-DMTai/MASTER) | **533**/126 | **2025-06-26** | **✅ 4 个 .pkl** | CSI300/800 | ✅ 原生 | 部分 |
| [dmis-lab/hats](https://github.com/dmis-lab/hats) | 170/62 | **2019-12-02** | 无 | S&P500 | ❌ | 未验证 |
| **MGRN** | — | — | — | STOXX600 | ❌ | **❌ 无代码** |

**THGNN —— 唯一"原生 A 股"的官方开源 GNN 股票模型（论文 CIKM 2022，[DOI](https://doi.org/10.1145/3511808.3557089)）**
- ✅ README 完整可跑：`generate_relation.py` → `generate_data.py` → `sh train.sh`，超参齐全
- ⚠️ **但数据是骨架**：`data/csi300.pkl` **仅 11,878 字节**，只是成分股代码清单（首行日期 2022-11-01）；`daily_stock/` 只有 **2022-11-01 ~ 2022-12-26 约 40 个交易日**的 csv
- ⚠️ **数据来源未说明**（Tushare？Wind？私有？）→ **这是它能否被第三方复现的决定性未知数**
- ⚠️ 命名冲突：[WenZhihao666/THGNN](https://github.com/WenZhihao666/THGNN) 是**完全无关**的"设备剩余寿命预测"论文

**MASTER —— 维护最好，但有公开的数据缺陷自述**
- AAAI-2024，[arXiv:2312.15235](https://arxiv.org/abs/2312.15235)，**533★，最后提交 2025-06-26**（唯一 2025 年仍活跃的），**唯一提供预训练权重**（`model/csi300_original_0.pkl` 等 4 个）
- ⚠️⚠️ **README 2025-06-26 公告（严重）**：先前发布的 valid & test 数据**有误** —— 误用 training processor，导致每日样本仅含 **95% 股票**，而原实验用全市场。**原作者访问权限已过期，无法重新导出正确数据**，改用 [chenditc/investment_data](https://github.com/chenditc/investment_data/releases)。作者称若用**训练损失阈值**早停则不影响结果，但这是**作者自述**。
- ⚠️ 同时声明 *"the linked Qlib version is not under the authors' maintenance"*

**HATS —— 已死**
- [dmis-lab/hats](https://github.com/dmis-lab/hats)，170★，**最后提交 2019-12-02（近 7 年无更新）**，无 LICENSE、无权重
- ⚠️ 环境 **Numpy 1.15.1 + TensorFlow 1.11.0**
- ⚠️ 数据 S&P500，`bash download.sh` 从 Yahoo Finance 拉取 —— **未验证脚本是否仍存活**（Yahoo 接口已多次变更，大概率失效）
- 注：README 标题是 "Hierarchical Graph **Attention** Network"，与常见的 "Graph Neural Network" 说法有出入

**MGRN —— 无代码 + 私有数据，不可复现**
- ⚠️ **"MGRN" 不是 "Multi-Graph Relation Network"，而是 "Multi-Graph Recurrent Network"**，出自 Qinkai Chen & Christian-Yann Robert, *Graph-Based Learning for Stock Movement Prediction with Textual and Relational Data*, **Journal of Financial Data Science**（[arXiv:2107.10941](https://arxiv.org/abs/2107.10941)）
- 三张图 = 股价相关系数 + **FactSet 供应链** + GICS 行业；底座 LSTM
- ❌ **无任何官方或第三方代码**
- ❌ **数据私有**：STOXX Europe 600 + **Bloomberg 新闻** + **FactSet 供应链** → **彻底不可复现**，且非 A 股

**⚠️ 一个总体性的重要发现**：**没有任何一个 GNN 股票模型存在"独立第三方在相同数据上复现出论文数字"的公开证据。** Qlib Model Zoo 里的 HIST 是唯一的第三方横向数字，但那是**重新实现**，不是复现原论文。**请把所有 GNN 选股论文的数字都当作【论文自述】。**

### 4.5 A 股图数据源（已验证）

#### 4.5.1 行业分类图 ✅ 关键好消息：申万 PIT 历史成分可低价获得

| 来源 | 接口 | 明细 | 费用 |
|---|---|---|---|
| **Tushare** | [`index_classify`](https://tushare.pro/document/2?doc_id=181) | 申万 **2014版**（28/104/227）与 **2021版**（31/134/346）**双版本** | **2000 积分（≈¥200/年）** |
| **Tushare** | [`index_member_all`](https://tushare.pro/document/2?doc_id=335) | ⭐ **含 `in_date`/`out_date`/`is_new` → 真正的 point-in-time 历史成分** | 2000 积分 |
| **Tushare** | [`ci_index_member`](https://tushare.pro/document/2?doc_id=373) 中信行业 | 中信三级，含 in/out_date | 5000 积分（≈¥500/年） |
| 申万宏源官方 | [下载中心](https://www.swsresearch.com/institute_sw/allIndex/downloadCenter/industryType) | 官方口径源头 | 免费（页面 JS 渲染，**未提取到实际文件链接**） |
| AKShare | [行业分类接口](https://akshare.akfamily.xyz/data/stock/stock.html) | 申万三级/巨潮/同花顺 | 免费 |
| Baostock | `query_stock_industry` | [Python API](http://baostock.com/mainContent?file=pythonAPI.md) | 免费 |

⭐ **最重要的工程结论**：**申万行业分类的 point-in-time 历史成分（含纳入/剔除日期）可以 ≈¥200/年 获得。** `index_member_all` 的 `in_date`/`out_date` 正是为无未来函数的回测设计的。**这是做行业图回测的前提，且成本极低——我建议所有 A 股图模型项目都从这里开始。**

#### 4.5.2 产业链图谱：唯一免费开源集，但有严重局限

✅ **[liuhuanyong/ChainKnowledgeGraph](https://github.com/liuhuanyong/ChainKnowledgeGraph)** —— **771★，最后提交 2025-12-22**（相对活跃）

实测规模（据[作者在 BAAI 智源社区的发布文](https://hub.baai.ac.cn/view/32674)）：

| 实体/关系 | 数量 |
|---|---|
| 图谱总量 | **100,718 节点 / 169,153 边** |
| A股上市公司 | 4,654 家 |
| 行业（申万 2021 版） | 511 个 |
| 产品 | 95,559 条 |
| 上游原材料关系 | 56,824 条 |
| 下游产品关系 | 390 条 |
| 产品小类关系 | 52,937 条 |
| 所属行业关系 | 3,946 条 |

数据来源：申万（swsindex.com）、深交所、上交所、百科/资讯/年报的非结构化抽取。

**⚠️⚠️ 作者自己列出的三条致命局限（我强烈建议在采用前认真读）**：

1. **产业链的主观性与标准性** —— "不同的人对产业链的构建、节点、关系的类型、颗粒度都有不同的理解。不同的设定会直接导致不同的应用结果。"
2. **产业链的动态性与全面性** —— 图谱是**静态快照**（2021 版申万行业分类 + 截至构建时的公司/产品）。**用它做 2023 年之前的回测会引入前视偏差**（你知道的是"现在"的产业链）。作者明确说"产业本身是动态的……如何捕捉这种行业的变化，使得整个图谱与时俱进，也是需要考量的点"。
3. ⭐ **产业链的定量推理特性（最关键）** —— 作者原文：*"单纯定性的构建产业链知识图谱，如果没有足够的参数，仅有知识表达是无法进行推理的，推理要求知识图谱 Schema 具备节点间推理传导的必备参数……从公司到产品必须有主营占比、市场占比、产能占比等数据，从产品到产品必须有成本占比和消耗占比等数据。"*

**🔧 我的工程判读**：**这个图谱能做"图结构"（谁和谁相连），但不能直接做"图传播"（涨多少传导多少）。** 对 GNN 而言这意味着**边是 0/1 无权重的**，你只能做结构聚合，做不了加权传导。要让它产生 alpha，你得**自己从年报附注/主营构成里补出权重**——那才是真正的工作量所在。

**其他（均为 demo 级或商业）**：
- [ciuyity-lgtm/brainmap-pandora](https://github.com/ciuyity-lgtm/brainmap-pandora) —— **0★**，仅 565 只股票 / 1,807 条关系，单 HTML 可视化，**demo 级**
- 商业：[Wind 产业链&供应链数据库](https://www.wind.com.cn/portal/zh/PDB/index.html)、企查查/天眼查/启信宝、同花顺 iFinD、Choice、通联数据、恒生聚源、数库科技。**定价均未验证**
- 学术：[CSMAR 供应链研究数据库](https://iarsrc.sufe.edu.cn/71/60/c1870a225632/page.htm)（高校订阅，非免费）、CNRDS

#### 4.5.3 分析师共同覆盖图：可自建，无现成数据集

**✅ 最便宜的可行路径：Tushare [`report_rc`](https://tushare.pro/document/2?doc_id=292)**
- 字段含 `ts_code / report_date / report_title / org_name / author_name / rating / eps / imp_dg`
- **数据从 2010 年开始**
- ⚠️ **2000 积分仅试用（每天 10 次），正式权限需 8000 积分（≈¥1000/年）**
- **有 `author_name` + `ts_code` + `report_date` 就可以自建共同覆盖网络**——这正是华泰和中金的做法（见 4.6）

其他：AKShare 免费的"分析师指数/排行/详情/盈利预测"；商业有 CSMAR 分析师库、CNRDS、Wind 一致预期、朝阳永续。

❌ **无任何开放的分析师共同覆盖网络数据集**（必须自建）。

### 4.6 中文券商研报关于 GNN 选股（已核实）

| # | 标题 | 机构 |  analyst | 日期 | 链接 | 可读性 |
|---|---|---|---|---|---|---|
| 1 | **《金工：图神经网络选股与 Qlib 实践》(人工智能42)** | **华泰证券** | 林晓明/李子钰/何康/王晨宇 | 2021-02-21 | [新浪](http://stock.finance.sina.com.cn/stock/go.php/vReport_Show/kind/lastest/rptid/667325990900/index.phtml)｜[手机版全文](https://finance.sina.cn/2021-02-23/detail-ikftpnny9226595.d.html) | ✅ |
| 2 | **《金工深度研究：分析师共同覆盖因子和图神经网络》(人工智能58)** | **华泰证券** | 林晓明/李子钰/何康 | 2022-07-07 | [新浪](https://stock.finance.sina.com.cn/stock/go.php/vReport_Show/kind/lastest/rptid/710528976980/index.phtml)｜[悟空智库](http://yanbao.us/wechatreport/115220.html) | ✅ 近全文 |
| 3 | **《基本面量化系列：如何利用关联图谱信息进行选股？》** | **中金公司** | — | **2026-08-11** | [手机版全文](https://finance.sina.cn/2026-08-11/detail-inimwyqr0745269.d.html) | ✅ |
| 4 | **《因子选股系列之一一七：DFQ~FactorGCL——基于超图卷积神经网络和时间残差对比学习》** | **东方证券** | 刘静涵/杨怡玲 | 2025-07-21 | [慧博投研](http://m.hibor.com.cn/wap_detail.aspx?id=335e99fa72a39257e6d8df5a67834d1b) | ⚠️ 仅摘要 |
| 5 | 《AGENT专题报告 RD-AGENT实测》 | **国联民生证券** | 叶尔乐 | 2026-05-20 | [新浪全文](http://stock.finance.sina.com.cn/stock/go.php/vReport_Show/kind/strategy/rptid/832591048933/index.phtml) | ✅ |
| 6 | 《Alpha掘金系列之八：沪深300另类舆情增强因子》 | **国金证券** | 高智威 | 2023-10-18 | [网易转载](https://m.163.com/dy/article/IHAVJKV305384CKJ.html) | ✅ |

#### ⭐ 华泰 AI42（2021-02-21）：Qlib GATs 的券商测试

回测期 **2010-01-04 ~ 2021-02-02**，沪深300 成分股，Qlib **Alpha158vwap**，TopkDropout 日频：

| 模型 | 年化 | Sharpe | 年化超额 | IR | 超额 MaxDD |
|---|---|---|---|---|---|
| **一层 GATs_ts** | **35.70%** | 1.42 | **28.89%** | **2.94** | −16.92% |
| LSTM（基准） | — | — | 25.7% | 2.64 | — |

**🔧 我的判读**：**28.89% 的年化超额、IR 2.94 高得不像真的。** 必须注意：(1) 回测期截止 **2021-02**，正是核心资产泡沫顶部，之后沪深300 经历了 2021-2024 的长期下跌，**这个窗口极度有利**；(2) 这是**券商研报口径**，无第三方复现；(3) 华泰自己在风险提示里写明 **"Qlib 仍在开发中，部分功能未加完善和验证"**。**结合 4.1 里 qlib 官方基准中 GATs 只有 ARR 4.97%~8.24%，我对 35.70% 这个数字持保留态度**——两者差距过大，可能源于回测期、特征处理或成本假设的差异，**但我无法核实**。

华泰同时明确指出 **RSR 属于"图时空网络"范畴**（顺序嵌入层 LSTM + 关系嵌入层动态时间图卷积）——这是券商对 4.3 中 RSR 的准确定性。

#### ⭐ 中金 2026-08-11：一份罕见的"诚实负面结果"

[中金《如何利用关联图谱信息进行选股？》](https://finance.sina.cn/2026-08-11/detail-inimwyqr0745269.d.html) 用了两张图：**分析师共同覆盖网络**（过去 12 个月共同覆盖建边）和**研报标题主题相似网络**（TF-IDF 字符片段 + 余弦，每股保留相似度 ≥0.08 的前 30 只）。

**⭐ 极重要的诚实负面结果**：SC 加权关联收益因子 `CFRet_SC` 的多空月均收益**仅 0.89%（等权）/ 0.92%（市值加权）**，**Newey-West t 值仅 1.64 / 1.59 —— 统计显著性有限**，且**组间收益非严格单调**。中金明确写 **"分析师共同覆盖关联动量因子 IC 并不高"**。

**改进后**（用基本面惊喜替代单纯股价上涨信号）：关联图谱因子 2017-01~2026-06 **IC 均值 2.36%、IC_IR 0.389**；Top10 年化净收益 **12.90% → 22.80%**，Sharpe **0.61 → 0.92**。数据源 **Wind + 朝阳永续（付费）**。

**🔧 我的判读**：**这份研报的价值在于它说了实话。** 单纯的"关联股票涨了 → 买目标股"在 A 股**统计上不显著**（t 值 1.6）。中金是靠**基本面惊喜的外溢**才做到 IC 2.36%。**这与英文论文里"relational graph 大幅提升预测力"的宣传形成鲜明对比。** 如果你要复现，注意：(1) 数据要付费的 Wind + 朝阳永续；(2) 因子做的是**行业市值中性化后**的 IC；(3) Top10 组合的 Sharpe 0.92 仍不算高。

#### 华泰 AI58（2022-07-07）：分析师共同覆盖 + GAT

- 方法：季度末取过去 6 个月全部分析师报告 → 每个分析师覆盖的股票两两连边 → 邻接矩阵（边权 = 共同覆盖分析师数，取 `log(1+x)`），每季度更新；**Louvain 社区发现**验证关联的基本面含义
- 因子：`CF_RET`（关联动量）、`CF_REV`、`CF_TURN`、`CF_STD`
- **GNN 部分**：分析师共同覆盖图输入 **GAT** vs 全连接网络 → **RankIC 6.87% → 7.29%，IC_IR 0.46 → 0.55，分 5 层 TOP 组合年化超额 +3.17%**
- ⚠️ **作者自述限制**：**"本文测试的股票池仅包含有分析师覆盖的 A 股，测试结论不能推广到全 A 股。"**

**🔧 判读**：GAT 相比全连接的提升是 **RankIC +0.42pp**。**这是"图结构带来的真实增量"最诚实的量化——很小。** 而且它只在有分析师覆盖的股票上成立，而 A 股约一半股票无覆盖。**不要期待"加上图结构"能带来数量级提升。**

#### 东方证券 DFQ-FactorGCL（2025-07-21）：⚠️ 仅摘要，无代码

- 明确以 **HIST 为改进起点**，指出 HIST 四缺陷：①隐藏概念构建机制粗糙 ②关联权重计算生成失真 ③概念信息聚合缺乏结构化传播 ④个股残差未充分剥离
- 改进：**HyperGCN**（预定义概念改静态 0-1 结构、隐藏概念用可学习因子原型）+ **TRCL**（时间残差对比学习）
- 声称：**中证全指 IC 12.46% / RankIC 16.14% / 多头年化超额 32.65%**；沪深300 IC 8.71% / RankIC 10.61%；指增 IR 2.20
- ⚠️ **全文需慧博 App；数据源未公开；无代码。** 这些数字**远高于** qlib 基准里 HIST 的 IC 0.0522，**差距达 2.4 倍**。**我无法验证，建议保持高度怀疑**——尤其是"IC 12.46%"这种量级在 A 股横截面上极为罕见。

#### ⚠️ `bigdata-s3.wmcloud.com` 核查（重要负面发现）

- ✅ **域名与 S3 结构真实存在**，路径规律：`/researchreport/YYYY-MM/<32位MD5>.pdf`
- ❌ **本机直接抓取 403**：阿里云 CDN 防盗链页 `403 Forbidden ... The access control configuration prevents your request at this time.`
- ❌ 目录探测全失败；未找到任何搜索/索引接口；**未成功下载任何一份 PDF**
- **判读：该桶确实存放研报，但做了 Referer/IP 防盗链，不应作为可靠数据源规划。**

#### ✅ 开源替代：东方财富研报 API（协作代理实测可用）

- `https://reportapi.eastmoney.com/report/list?industryCode=*&pageSize=N&industry=*&beginTime=&endTime=&pageNo=1&qType=1&code=*` → **免登录 JSON**
- PDF 直链实测 HTTP 200 + `application/pdf`：`https://pdf.dfcfw.com/pdf/H3_{infoCode}_1.pdf`
- ⚠️ **重大局限**：`hits` 恒为 130,988，**不支持关键词检索**（测"图神经网络/知识图谱/图卷积/关联网络"均 0 命中），只能按时间/行业/机构翻页

---

## 5. 舆情 / 新闻 / 文本数据

### 5.1 数据源速查表

| 来源 | 类型 | 覆盖/历史 | 费用 | A股可用 |
|---|---|---|---|---|
| **Tushare** 新闻 [`news`](https://tushare.pro/document/2?doc_id=143) / [`major_news`](https://tushare.pro/document/2?doc_id=195) / [`cctv_news`](https://tushare.pro/document/2?doc_id=154) | FREEMIUM | 快讯 6 年+、长篇 8 年+、联播 2017 起 | **¥1000/年**（独立权限） | ✅ |
| **Tushare** 公告 [`anns_d`](https://tushare.pro/document/2?doc_id=176) | FREEMIUM | **10 年+**，含 PDF 链接与 `rec_time` | **¥1000/年** | ✅ |
| **Tushare** 互动易 [`irm_qa_sz`](https://tushare.pro/document/2?doc_id=367) / [`irm_qa_sh`](https://tushare.pro/document/2?doc_id=366) | FREEMIUM | 深 2010-10 起 / 沪 2023-06 起 | **¥500/年** | ✅ |
| **AkShare** | FREE | **新闻只有"最近 20–200 条"，无历史归档** | ¥0 | ✅ |
| **巨潮 cninfo** | FREE | 法定披露，历史完整 | ¥0 | ✅ |
| **同花顺 iFinD** | COMMERCIAL | 高校采购价 ≈¥9,800/终端/年 | 未公开 | ✅ |
| **东方财富** | FREE(网页) | 股吧无 robots.txt | ¥0 | ⚠️ **法律风险** |
| **CSMAR** | ACADEMIC | 全校授权 ¥10–28 万/年 | 个人不可购 | ✅ |
| **CNRDS** | ACADEMIC | **需已采购高校账号** | 未公开 | ✅ |
| **Wind** | COMMERCIAL | **基础终端 ¥39,800/年**（实测采购公告） | 舆情另加购 | ✅ |
| **通联数据 DataYes** | COMMERCIAL | 新闻自 2013 年，日 8 万+篇 | 未公开 | ✅ |

### 5.2 ⚠️ 四个必须知道的负面结论

**① Tushare 没有任何情感打分接口。**
我把"大模型语料"整栏（[doc_id=142](https://tushare.pro/document/2?doc_id=142)）逐个查过：国家政策库、券商研报、央行报告、新闻快讯、新闻通讯、新闻联播、上市公司公告、上证e互动、深证互动易——**全是原文，没有分数**。而且 Tushare 自研的[量化因子库](https://tushare.pro/document/2?doc_id=486)（202 个因子）里**一个舆情因子都没有**（全部是量价+财务）。

**② AkShare 没有股吧数据，也没有历史新闻归档。**
[akshare](https://github.com/akfamily/akshare)（**22,529★**，活跃）相关接口实测：`stock_news_em` **仅返回个股最近 100 条**；`stock_info_global_*` 只返回最近 20–200 条；**没有任何接口支持按日期区间拉取历史新闻**。它只有"热度/人气榜/千股千评关注指数"这类**关注度代理变量**。

> ⚠️ **这条决定了整个项目的架构**：**你今天不落盘，明天的历史就永远拿不到了。**

**③ 没有任何开源仓库是真正跑通的"新闻抓取 → LLM 情感 → 日频截面因子 → Qlib 回测"全流水线。**
- [qusong0627/QuantMind](https://github.com/qusong0627/QuantMind)（1,429★，极活跃）README 宣称"实时舆情情绪分析 + 深度集成 Qlib"，但**舆情与 Qlib 在 README 里是并列的两个功能，没有任何一处说明舆情分数被写进了 Qlib 特征矩阵**。营销密度极高（"零门槛无限制""全面支持 A股/港股/美股/期货/区块链"），**典型的"功能清单式"描述**。
- [You-lie/a-share-research-workbench](https://github.com/You-lie/a-share-research-workbench)（StockFish）**是本次最诚实的项目**（明确声明"不连接券商、不执行自动交易"），**但它把舆情用于单股分析，把 Qlib 用于模型训练/回测，两者是平行的**。而且它用 **Tavily 做新闻搜索**，不是自建抓取。
- [cn-vhql/qlib_factor_platform](https://github.com/cn-vhql/qlib_factor_platform)（76★）**无舆情模块**。

**④ ⚠️ 法律风险被严重低估：`robots.txt: Allow: /` 不是法律许可。**

[中国知识产权报 2025-11-27 报道](https://iprchn.com/cipnews/news_content.aspx?newsId=144569)：福建高院审理腾讯诉某金融舆情平台（"战鹰"）案，被告抗辩"腾讯 robots 协议明确允许爬取"，**福州中院一审、福建高院二审维持，判赔 228 万余元**。审判长核心说理：

> *"robots 协议针对的是搜索引擎的爬虫软件，而被告的使用场景不属于搜索引擎，对海量数据的抓取超出了 robots 协议的设立目的和允许限度……造成对腾讯公司服务的实质性替代。"*

实测 robots.txt：`eastmoney.com` → `Allow: /`；`guba.eastmoney.com` → **404（无 robots）**；**`xueqiu.com` → 明文禁止**将其内容用于 AI 训练/RAG 及"creating or providing archival or cache datasets"。

**工程判断**：个人小规模、低频、不对外提供服务，实际风险低；但**一旦商业化、对外提供舆情服务、或大规模归档，就精确落入"战鹰案"的事实模型**。

### 5.3 ⭐ 最重要的领域知识：A 股舆情因子的 IC 符号大概率是负的

**这是新手最容易踩、也最致命的坑。**

**开源证券 × 通联数据**（[投资界转载](https://news.pedaily.cn/20210716/19358.shtml)）：每日 3 万多条新闻，**有新闻数据的个股 3,848 只，A 股覆盖率 99.86%，日均约 1,600 只有舆情数据**。因子 = 过去 N 天舆情分数均值的**变化量**，20 日回看：

| 频率 | 多空对冲年化 | **年化 ICIR** |
|---|---|---|
| 双周频 | 12.00% | **−2.3** |
| 月频 | 11.92% | **−2.00** |

**ICIR 是负的** —— 即舆情分数越高，未来收益越**低**。他们靠**反号**做多空才拿到正收益。

**学术印证**：Qin Yu & Bing Zhang, *The Media Reinforcement Effect in Chinese Stock Market*, **Journal of Portfolio Management**（中文精读见 [QIML Insight](https://cloud.tencent.com.cn/developer/article/2269135)）。数据：**2004-01~2017-06，331 个媒体网站，约 1,500 万篇新闻**。核心结论：**新闻情绪应当用于"增强反转"而非动量** —— 做多"前期低收益 + 低情绪"，做空"前期高收益 + 高情绪"，该组合**年化 8.38%**，而标准反转组合年化 **−0.53%**。**国有媒体的情绪增强效应显著，民营媒体不显著。**

**🔧 工程结论**：
1. **不要预设"利好新闻 → 买入"。** 回测里**先看 IC 符号再决定方向**。
2. **用"变化量"而不是"水平值"。** 水平值会被"新闻数量"污染。
3. **新闻情绪在 A 股更像"注意力/过度反应的代理"，而非基本面信号。**
4. **注意与 FinGPT Issue #250 里那三条定性观察的一致性**——"利好已 price-in""情感与资金背离"都指向同一个机制。

### 5.4 中文金融情感模型：可用的开源资产

> ⚠️ **环境前提**：`huggingface.co` 从本机不可达。国内部署需 `export HF_ENDPOINT=https://hf-mirror.com`。（以下 HF 数据由协作代理经 hf-mirror 获取，**我未与 HF 主站交叉核对**。）

| 模型 | 下载量 | License | 判读 |
|---|---|---|---|
| [yiyanghkust/finbert-tone-chinese](https://huggingface.co/yiyanghkust/finbert-tone-chinese) | 33,231 | apache-2.0 | 基于 `bert-base-chinese`，**私有数据集（约 8k 条券商研报句子）**，Test Acc 0.88。⚠️ **训练在研报句子上，不是新闻/股吧**；数据私有 → 不可复现 |
| [bardsai/finance-sentiment-zh-base](https://huggingface.co/bardsai/finance-sentiment-zh-base) | 3,288 | apache-2.0 | 基座 `bert-base-chinese`，**但训练集是 Financial PhraseBank 的机器翻译版**。⚠️ **自报 Acc 0.973 是在"翻译腔"测试集上的，不能外推到真实中文新闻**。**许可证最干净的可商用起点** |
| [hw2942/bert-base-chinese-finetuning-financial-news-sentiment-v2](https://huggingface.co/hw2942/bert-base-chinese-finetuning-financial-news-sentiment-v2) | 1,985 | ⚠️ **未标注** | 社区里**最贴题**的中文**新闻**情感模型（示例全是真新闻），但**训练集仅 2,000 条**且**无 license** → 商用有法律不确定性 |
| [Langboat/mengzi-bert-base-fin](https://huggingface.co/Langboat/mengzi-bert-base-fin) | 253 | apache-2.0 | **不是分类器，是 `fill-mask` 领域自适应基座**（20G 金融新闻+研报 MLM 继续训练）。⭐ **正确用法是拿它做底座再自己微调**，而非直接打分 |
| [IDEA-CCNL/Erlangshen-Roberta-110M-Sentiment](https://huggingface.co/IDEA-CCNL/Erlangshen-Roberta-110M-Sentiment) | 4,173 | apache-2.0 | **通用中文情感**（非金融），可作弱基线 |

**❌ 不存在的东西（网上流传的错误 ID）**：
- **`valuesimplex/FinBERT-zh` 不存在**（该 HF 组织下没有任何模型）
- **`FudanDISC/*` 在 HF 上不存在** —— DISC-FinLLM 只走 GitHub
- 正确 ID 是 `Langboat/mengzi-bert-base-fin`（带前缀）

**中文金融情感数据集**：
- [Ya-dongLi/CFSC](https://github.com/Ya-dongLi/CFSC) —— 含 **CFSC-ABSA**（15,446 条中文金融新闻语句 / 41,496 个方面词，**方面级**情感）与 **CFSC-NER**（10,667 句 / 29,181 个金融实体，分 Corporate/Stock/Market/Economy）。⭐ **"方面级 + 实体级"标注对"把新闻正确关联到个股"这一步极有价值**
- [hw2942/financial-news-sentiment](https://huggingface.co/datasets/hw2942/financial-news-sentiment)

**中文金融大模型现状（多数已停更）**：

| 项目 | 状态【实抓】 | 判断 |
|---|---|---|
| [FudanDISC/DISC-FinLLM](https://github.com/FudanDISC/DISC-FinLLM) | 896★，**最后提交 2023-11-01** | ⚠️ **停更近 3 年，不建议作为新项目基座** |
| [Duxiaoman-DI/XuanYuan](https://github.com/Duxiaoman-DI/XuanYuan) | 1,325★，**最后提交 2025-01-07** | 权重可下载非 gated，但**停更约 20 个月**；13B-Chat 是唯一现实选项 |
| [TongjiFinLab/CFBenchmark](https://github.com/TongjiFinLab/CFBenchmark) | **最后提交 2025-07-30**，活跃 | ⭐ **做模型选型应优先用 CFBenchmark 而非英文基准** |
| [SUFE-AILAB/BBT-Fin](https://github.com/SUFE-AILAB/BBT-Fin) | atom 取不到 | BBT-FinCorpus / BBT-FinT5 / CFLEB，学术价值高，**工程可用性未验证** |

⭐ **最重要的判断**：**没有任何一个中文金融大模型是"为了产出日频选股因子"设计的。** 它们全是问答/生成/分类模型。**把它们接到因子上，中间那层（文章→个股映射、时间对齐、截面归一、衰减加权）必须你自己写，而这一层才是决定因子有效性的关键——模型本身不是瓶颈。**

### 5.5 建议的因子构造口径（我的工程判断）

综合上述文献，能落地的因子构造应该这样：

1. **时间戳对齐（最关键）**：用新闻的 **`pub_time`（秒级）**，**不要用 `date`**。切分窗口用 `[前一日收盘 15:00, 当日开盘 9:25]` → 当日**开盘**可交易。任何用当日 `date` 字段做的对齐都会引入前视偏差。
   > ⚠️ 实证：Tushare `irm_qa_sz` 的 `trade_date=20250212` 而 `pub_time=2025-02-12 21:46:32` —— **"当天晚上"，此时 A 股已收盘**。按 `trade_date` 对齐并在当天收盘成交 = 彻头彻尾的未来函数。
2. **实体链接**：新闻必须映射到 `ts_code`。需 NER（可用 [CFSC-NER](https://github.com/Ya-dongLi/CFSC) 微调）+ 股票简称/曾用名/代码词典。⭐ **这一步的召回率直接决定因子覆盖率。**
3. **相关性加权**：给每条新闻一个 ∈[0,1] 的"与个股相关度"，过滤只被"提及"的噪声新闻。
4. **情感打分**：`score = p_pos − p_neg ∈ [−1,1]`。**用 BERT 级模型，不要用 LLM** —— 情感三分类是 `bert-base` 的活。
5. **聚合与衰减**：`Senti_d = Σ_j w_rel_j · score_j · exp(−Δhours_j / τ)`，τ 取 6–24 小时；再对过去 N 日取**均值的变化量**（照抄开源证券）。
6. **两个辅助因子**：① **新闻关注度**（当日相关新闻条数）；② **情感分歧度**（同日新闻情感标准差）。学术结论显示异质信念越强，效应越显著。
7. **截面处理**：winsorize(1%/99%) → **行业 + 市值中性化** → z-score。**必须先中性化再看 IC**，否则你测到的是小市值效应（回想国金证券那个 0.55 的市值相关性）。
8. **符号**：先假定负相关，**回测里看 IC 符号再定方向**。

### 5.6 三个必踩的陷阱

**① 回填与修订（让回测失效的头号杀手）**
- 免费源普遍"回填/修订"历史。`stock_news_em` 只有最近 100 条 → **你根本拿不到"历史上的当时快照"，无法验证是否被修订**。
- **唯一可靠做法：从第一天起 append-only 落盘，带 `fetch_ts` 和内容 hash 做去重与变更检测。**
- 对比：**Tushare 的新闻是按 `pub_time` 归档的，修订风险显著低于网页抓取**——这是它 ¥1000/年 的主要价值。

**② 幸存者偏差**
- AkShare/Tushare 的**新闻接口按 `ts_code` 查询，退市股的历史新闻还在**（相对好）。
- **但行情/财务侧的退市股是缺失的**。AkShare 专门提供了 `stock_*_sheet_by_report_delisted_em` 系列退市股接口——**说明默认接口确实不含退市股**。
- ⚠️ **Qlib 的 `csi300`/`csi500` 是当前成分股，直接回测会引入严重的成分股幸存者偏差。必须用历史成分股快照**（Tushare `index_member_all` 的 `in_date`/`out_date`，见 4.5.1）。

**③ 覆盖率陷阱**
- 通联数据（商业，全 A 覆盖最好的之一）**日均也只有约 1,600 只股票有舆情数据**（不到全 A 一半）。
- **任何自建免费舆情因子的日覆盖率大概率显著低于此**，截面 IC 会非常不稳定。
- **必须记录每日覆盖率，并把"无新闻"和"中性新闻"区分开**（前者应该 NaN 而不是 0）。

### 5.7 务实预算方案

| 项目 | 年成本 | 说明 |
|---|---|---|
| Tushare 新闻资讯权限 | ¥1,000 | 9 个新闻源 + 8 年长篇 + 新闻联播 |
| Tushare 公告权限 | ¥1,000 | 10 年历史 + PDF + `rec_time` |
| Tushare 互动易权限 | ¥500 | 深证 2010 起 |
| Tushare 2000 积分（基础行情+申万 PIT 行业） | ¥200 | 200 次/分 |
| Tushare `report_rc`（分析师共同覆盖，可选） | ¥1,000 | 需 8000 积分 |
| 巨潮 cninfo 公告 | ¥0 | 官方免费，[`hisAnnouncement/query`](http://www.cninfo.com.cn/new/hisAnnouncement/query) **实测返回规整 JSON** |
| AkShare | ¥0 | 无 SLA，仅供原型 |
| HF 情感模型 | ¥0 | apache-2.0 |
| **合计** | **≈ ¥2,700–3,700/年** | 主要成本是你的时间 |

**最省起点（我的推荐）**：**只买 ¥1000 公告权限 + ¥200 基础积分 = ¥1,200/年**，**先做纯公告事件因子，暂时不碰新闻情感**。理由：
- 公告**结构化程度高、有法定发布时间（PIT 安全）、免费/低价、无法律风险、历史完整**
- "减持/增持/回购/诉讼/问询函/业绩预告修正/解禁"这些类别**本身就是强因子，用规则 + 小模型就能做，不需要 LLM**
- 相比之下股吧情感**信噪比和法律风险都更差**

**⚡ 第 0 步（零成本、1–2 天）：先验证回测框架，再碰 LLM。**

在花钱买任何文本数据、写任何 LLM 代码之前，先用 AkShare 的**免费关注度类接口**搭一个代理因子，跑通 Qlib 全流程：

| 接口 | 内容 | 特点 |
|---|---|---|
| `stock_comment_detail_scrd_focus_em` | 东财用户关注指数 | **有时间序列**，免费 |
| `stock_hot_rank_detail_em` | 人气榜历史趋势 | 有时间序列 |
| `stock_comment_detail_scrd_desire_em` | 市场参与意愿 | 有时间序列 |

这些接口**免费、有历史、不需要任何 NLP**，能在两天内暴露**时间对齐、股票池、中性化、覆盖率**这些真正的坑。

**⭐ 判断标准：如果这一步都跑不出 IC，加 LLM 也救不回来。** 因为 LLM 只是在"文本 → 分数"这一步替换掉规则，而**从分数到因子的那一层才是决定成败的地方**（见 5.5）。这是我在本报告里给出的最高性价比建议。

---

## 6. 综合工程判断

### 6.1 三条路线的投入产出排序（我的判断）

| 优先级 | 路线 | 理由 |
|---|---|---|
| 🥇 **1** | **公告事件因子（规则 + 小模型）** | 数据免费/低价、PIT 安全、无法律风险、可解释、可复现。**唯一一个"个人能完整掌控"的方向** |
| 🥈 **2** | **申万 PIT 行业图 + HIST/IGMTF（qlib 内置）** | ¥200/年 拿 PIT 行业图；qlib 已有可用实现与官方基准；HIST 是 qlib 内表现最好的图模型（Alpha360 ARR 9.87%）。⚠️ 但 HIST 的概念图是静态快照，有前视风险 |
| 🥉 **3** | **LLM 因子挖掘（RD-Agent / QuantaAlpha）** | 定位是**辅助研究工具**，不是替代方案。工程门槛高、稳定性差、结果不可复现。**QuantaAlpha 因为数据公开在 HF，是唯一"零数据门槛"的入口** |
| ❌ | FinGPT 自建 A 股情感 | 需要标注数据（不可逾越），且**用 7B LLM 做三分类在成本与稳定性上都不如 BERT** |
| ❌ | 股吧/雪球爬虫 | 法律风险（福建高院 228 万判例、雪球明文禁止 AI 训练） |

### 6.2 五个反直觉但重要的结论

1. **"图结构"带来的增量比宣传的小得多。** 华泰实测 GAT vs 全连接：RankIC 6.87% → 7.29%（+0.42pp）。qlib 基准里 HIST vs GATs：RankIC 0.0598 → 0.0667（+11%）。**不要期待数量级提升。**

2. **最诚实的信号来自券商的负面自述，而不是论文的正面宣传。** 中金说"分析师共同覆盖关联动量因子 IC 并不高"（t=1.6，不显著）；国联民生说 RD-Agent"ICIR 提升始终弱于 IC""不能替代传统研究流程""不保证可再次挖到"。**这些才是决策依据。**

3. **A 股舆情因子是反转因子，不是动量因子。** ICIR = −2.0~−2.3。**"利好→买入"是错的。**

4. **LLM 选型的决定因素不是推理能力，是代码工程能力。** GLM-V5.1 > DeepSeek-V3.2（后者无限重复输出、提案大面积编码失败）。**弱模型省钱是假象。**

5. **可复现性在 LLM 因子挖掘里是结构性缺失的。** 券商原文："报告中得到的因子仅代表单次运行结果，不保证可再次按顺序挖到。" **这意味着你无法把因子挖掘纳入 CI、无法审计、无法回归测试。** 对严肃的量化研究流程，这是一个根本性的方法论问题。

### 6.3 明确不要做的事

- ❌ 不要相信任何"A股 + 大模型 + 高年化"的标题（尤其是"不到10美元""4.6万星""提升18%"这类数字——后者是推广帖，前者的星数实测是 14,582）
- ❌ 不要买 Wind 舆情（基础终端就 ¥39,800/年）
- ❌ 不要爬股吧/雪球（有判例）
- ❌ 不要用 `valuesimplex/FinBERT-zh`（不存在）或 `FudanDISC/*`（HF 上不存在）
- ❌ 不要把"关注度/热度"和"情感"混为一个因子（前者是 attention proxy，后者是 sentiment，相关性可能很低甚至反向）
- ❌ 不要用 `csi300`/`csi500` 当前成分股做长周期回测
- ❌ 不要预设因子方向，先看 IC 符号

---

## 7. 我明确未能验证的事项

**环境限制导致的未验证**：
1. **FinGPT 的 HuggingFace 权重是否仍可下载** —— 本机 `huggingface.co` 不可达（HTTP 000/超时），我无法独立确认 `FinGPT/fingpt-forecaster_dow30_llama2-7b_lora` 等模型页面的存活状态。仅能引述官方 README 的引用。
2. **HF 上各中文情感模型的元数据（下载量/最后更新）** 由协作代理经 `hf-mirror.com` 获取，**未与 HF 主站交叉核对**，可能略有滞后。
3. **GitHub star 数为 HTML 属性快照**（`repo-stars-counter-star`），非 API 值；可能有分钟级延迟。

**内容层面的未验证**：
4. **所有商业供应商的舆情模块单价** —— 同花顺 iFinD 舆情、恒生聚源、数库、朝阳永续、通联数据、天软、RESSET 的**舆情模块单独定价全部未公开**。我找到的（Wind ¥39,800/终端/年、iFinD ≈¥9,800/终端/年、CSMAR 全校 ¥10–28 万/年）都是**打包价，不是舆情模块价**。
5. **CSMAR/CNRDS 是否提供"已打分的日频个股情感因子表"** —— CSMAR 数研通宣传页提到"新闻舆情分析"，但**拿不到字段级文档**；CNRDS 因未采购无法登录。
6. **FinGPT 是否因数据许可被正式投诉或下架** —— 未找到记录。批评主要停留在"数据来源未清晰声明"的结构性层面。
7. **FinGPT "benchmark cherry-picking" 的指控** —— **我没有找到直接指控的公开文献**。我只观察到其论文均发表于 workshop 且长期使用自建 benchmark，标注为"评测独立性存疑"，**不等于"已被证实挑选基准"**。
8. **THGNN 官方实验数据来源** —— 仓库未说明，这直接决定它能否被第三方复现。
9. **东方证券 DFQ-FactorGCL 全文** —— 仅摘要，其"中证全指 IC 12.46%"**无法验证**，且与 qlib 基准差距达 2.4 倍。
10. **华泰 AI42 的"年化 35.70%/IR 2.94"** —— 与 qlib 官方基准中 GATs 的 ARR 4.97%~8.24% 差距过大，**我无法核实差异来源**（回测期？特征处理？成本假设？）。
11. **QuantaAlpha / FactorMiner / AlphaEvo 的任何独立复现** —— 均未找到，只有作者自述。
12. **RD-Agent 单轮真实 token 花费** —— 论文只给 "under $10"，券商实测报告未披露成本。
13. **`minihellboy/factorminer` 与论文作者的从属关系** —— 未能确认是官方实现还是第三方复现（README 措辞是 *"follows the system described in [paper] and extends it"*，倾向第三方；而 AgonAlpha 论文称 FactorMiner "keeps code and prompts closed"，两说不一致）。
14. **`quantskills/skill-dl-gnn-stock-graph`（2★）是否真实现 MF-IAMGCN** —— 未验证。该仓库与 [aifinlab/finclaw](https://github.com/aifinlab/finclaw)（242★，上财 AIFinLab，但内容是"1000+ Skills"的 prompt 模板库）里的 `a-share-graph-network/SKILL.md` 都只是**描述性模板**（示例数字如"图增强IC=0.048 vs 无图0.040"是**说明性举例，非实测结果**）。**零第三方验证，请勿当作可信实现。**
15. **申万宏源官方下载中心的实际文件链接** —— 页面 JS 渲染，未提取到。
16. **`bigdata-s3.wmcloud.com` 的研报内容** —— 本机 403 防盗链，未成功下载任何 PDF。
17. **各仓库精确的最后 commit 日期** —— 来自 commits atom feed（对默认分支可靠），但对多分支/重命名仓库可能有偏差。

---

## 附录：核心资源链接速查

**FinGPT 生态**
- [FinGPT](https://github.com/AI4Finance-Foundation/FinGPT)（21,237★ MIT）｜[FinRobot](https://github.com/AI4Finance-Foundation/FinRobot)（7,966★）｜[FinRL](https://github.com/AI4Finance-Foundation/FinRL)（16,267★）｜[FinNLP](https://github.com/AI4Finance-Foundation/FinNLP)（已死）
- [FinGPT-Forecaster README](https://github.com/AI4Finance-Foundation/FinGPT/tree/master/fingpt/FinGPT_Forecaster)｜[A股因子评估器 PR #274](https://github.com/AI4Finance-Foundation/FinGPT/pull/274)
- 独立评测：[arXiv:2507.08015](https://arxiv.org/abs/2507.08015)

**LLM 因子挖掘**
- [microsoft/RD-Agent](https://github.com/microsoft/RD-Agent)（14,582★ MIT）｜[quant 文档](https://rdagent.readthedocs.io/en/latest/scens/quant_agent_fin.html)｜[论文 arXiv:2505.15155](https://arxiv.org/abs/2505.15155)
- ⭐ [国联民生 RD-Agent 独立实测](http://stock.finance.sina.com.cn/stock/go.php/vReport_Show/kind/strategy/rptid/832591048933/index.phtml)
- [QuantaAlpha](https://github.com/QuantaAlpha/QuantaAlpha)（1,516★）+ [数据 HF](https://huggingface.co/datasets/QuantaAlpha/qlib_csi300)
- [FactorMiner](https://github.com/minihellboy/factorminer)（110★）｜[AlphaForge](https://github.com/dulyhao/alphaforge)（427★）｜[AlphaGen](https://github.com/RL-MLDM/alphagen)（1,228★）
- 空壳：[FinCon](https://github.com/The-FinAI/FinCon)｜[Alpha-GPT arXiv:2308.00016](https://arxiv.org/abs/2308.00016)｜[AlphaLogics arXiv:2603.20247](https://arxiv.org/abs/2603.20247)｜[AgonAlpha arXiv:2608.11250](https://arxiv.org/abs/2608.11250)

**GNN**
- [Qlib benchmarks](https://github.com/microsoft/qlib/blob/main/examples/benchmarks/README.md)｜[GATs README](https://github.com/microsoft/qlib/blob/main/examples/benchmarks/GATs/README.md)
- 本仓库源码：`qlib/contrib/model/pytorch_gats.py`、`qlib/contrib/model/pytorch_gats_ts.py`、`qlib/contrib/model/pytorch_hist.py`、`qlib/contrib/model/pytorch_igmtf.py`
- [fulifeng/Temporal_Relational_Stock_Ranking](https://github.com/fulifeng/Temporal_Relational_Stock_Ranking)（527★，已停更）｜[HIST](https://github.com/Wentao-Xu/HIST)（304★）｜[MASTER](https://github.com/SJTU-DMTai/MASTER)（533★）｜[THGNN](https://github.com/TongjiFinLab/THGNN)（127★）｜[HATS](https://github.com/dmis-lab/hats)（已死）
- [ChainKnowledgeGraph](https://github.com/liuhuanyong/ChainKnowledgeGraph)（771★）｜[BAAI 发布文](https://hub.baai.ac.cn/view/32674)

**券商研报**
- [华泰 AI42 图神经网络选股与 Qlib 实践](https://finance.sina.cn/2021-02-23/detail-ikftpnny9226595.d.html)
- [华泰 AI58 分析师共同覆盖因子和图神经网络](http://yanbao.us/wechatreport/115220.html)
- ⭐ [中金 如何利用关联图谱信息进行选股（2026-08）](https://finance.sina.cn/2026-08-11/detail-inimwyqr0745269.d.html)
- ⭐ [国金证券 FinGPT 沪深300 舆情因子](https://m.163.com/dy/article/IHAVJKV305384CKJ.html)
- [东方证券 DFQ-FactorGCL（仅摘要）](http://m.hibor.com.cn/wap_detail.aspx?id=335e99fa72a39257e6d8df5a67834d1b)

**数据源**
- [Tushare 积分权限表](https://tushare.pro/document/2?doc_id=290)｜[申万分类](https://tushare.pro/document/2?doc_id=181)｜[申万 PIT 成分](https://tushare.pro/document/2?doc_id=335)｜[研报 report_rc](https://tushare.pro/document/2?doc_id=292)
- [AkShare](https://github.com/akfamily/akshare)（22,529★）｜[巨潮公告 API](http://www.cninfo.com.cn/new/hisAnnouncement/query)｜[use_cninfo 封装](https://github.com/rollysys/use_cninfo)
- [CFSC 中文金融情感数据集](https://github.com/Ya-dongLi/CFSC)｜[CFBenchmark](https://github.com/TongjiFinLab/CFBenchmark)
- 法律风险：[福建高院"战鹰案"判赔 228 万](https://iprchn.com/cipnews/news_content.aspx?newsId=144569)

---

*本报告由多源交叉核实生成。所有标注【实抓】的内容均在 2026-09-11 通过直接 HTTP 请求或本地源码审阅获得。凡属作者自述、券商研报或社区文章的内容，均已在文中标注证据等级。*
