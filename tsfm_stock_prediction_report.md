# Time-Series Foundation Models (TSFMs) for Stock Return Prediction — Applications and Critiques

**Research report — compiled ~September 2026**
**Scope:** application of TSFMs to stock return prediction (especially cross-sectional stock selection), plus the critical literature. Literature cut-off: September 2026.

**Reading conventions used throughout:**
- **[PAPER CLAIM]** = the number/statement is what the authors report; nobody independent has reproduced it.
- **[INDEPENDENT]** = reproduced or cross-checked by a separate party (another paper, a third-party benchmark, or a public leaderboard).
- **[UNVERIFIED — secondary source]** = I could only reach a summary/blog/aggregator, not the primary text.
- Every claim has a hyperlink. Where I failed to find something, I say **NOT FOUND** explicitly.

---

## 0. Executive summary

1. **There is now a real, peer-reviewed empirical literature on TSFMs in finance, and its dominant finding is negative-to-neutral.** The most comprehensive study ([Rahimikia, Ni & Wang, arXiv:2511.18578](https://arxiv.org/abs/2511.18578)) finds that **off-the-shelf Chronos and TimesFM "perform poorly" in both zero-shot and fine-tuned settings** on a ~2-billion-observation global daily excess-return panel, underperforming CatBoost/XGBoost/LightGBM ensembles. **[PAPER CLAIM]**

2. **The most-cited positive result is smaller than it sounds.** [Noguer i Alonso & Pereira Franklin, arXiv:2606.27100](https://arxiv.org/abs/2606.27100) report TSFMs winning **8 of 10 task-level wins** on five US mega-caps — but also that **gains over a zero-return random walk are "small and sparse"**, that a Diebold–Mariano test rejects the random walk for **only 2 of 10 tasks**, and that reported skill scores are of order **10⁻³**. The paper's own conclusion is that TSFMs are "useful practical priors… **but not universal engines of statistically reliable alpha generation**." **[PAPER CLAIM]**

3. **Generic TSFM pretraining does not transfer to finance; finance-native pretraining does.** This is the one robust positive finding in the literature. Rahimikia et al. show that pretraining Chronos from scratch on financial data lifts Chronos-small's out-of-sample R² from **−77.07% to −3.18%** (window 5) and from **−1.27% to −0.59%** (window 512). **All models released at [FinText.ai](https://FinText.ai) / [HuggingFace FinText](https://huggingface.co/FinText).** **[PAPER CLAIM, code+weights public]**

4. **The evaluation-integrity problem is severe and now documented.** [Meyer et al., arXiv:2510.13654](https://arxiv.org/abs/2510.13654) formalise two leakage modes; per [Hyndman's summary](https://robjhyndman.com/hyndsight/foundation_models.html), of **401 datasets across 22 published TSFMs, only 6% had never appeared in any model's pre-training or fine-tuning corpus**. [TSFMAudit, arXiv:2605.26161](https://arxiv.org/abs/2605.26161) is the first dedicated contamination auditor for TSFMs. [Moghadasi & Ghaderi, arXiv:2609.10357](https://arxiv.org/abs/2609.10357) show even a **contamination-free temporal hold-out is not enough** — corpus *familiarity* still drives wins.

5. **The DLinear thread is real, but the paper the user named has the wrong authors.** "Are Transformers Effective for Time Series Forecasting?" is by **Zeng, Chen, Zhang & Xu** ([AAAI 2023 / arXiv:2205.13504](https://arxiv.org/abs/2205.13504)) — see §3.1. **"The Capacity and Robustness Trade-off" is NOT by Tan et al.** — it is by **Lu Han, Han-Jia Ye & De-Chuan Zhan** ([arXiv:2304.05206](https://arxiv.org/abs/2304.05206)) — see §3.2.

6. **For A-shares specifically:** the only peer-reviewed TSFM paper I found is about **volatility**, not returns — [Zhong, Fu & Zhu, *Finance Research Letters* 110:110606 (2026)](https://doi.org/10.1016/j.frl.2026.110606). I could **not** obtain its abstract or numbers (see §6). The most interesting A-share cross-sectional work I found is **not** a TSFM paper: [STRATA, arXiv:2608.28060](https://arxiv.org/abs/2608.28060) reports a style-residualised rank IC of **0.0728** but also that **once the target is measured from the first executable price, the decile spread is "indistinguishable from zero."**

---

## 1. Cross-sectional / portfolio-level TSFM applications

### 1.1 Rahimikia, Ni & Wang (2025) — *Re(Visiting) Time Series Foundation Models in Finance* — **the single most important paper for this question**

- **Title:** Re(Visiting) Time Series Foundation Models in Finance
- **Authors:** Eghbal Rahimikia (Alliance Manchester Business School, Univ. of Manchester); Hao Ni (Dept. of Mathematics, UCL); Weiguan Wang (School of Economics, Shanghai University)
- **Venue/date:** arXiv:2511.18578, submitted 23 Nov 2025. q-fin.CP (cross-listed cs.AI, cs.LG, q-fin.PM, q-fin.PR). Related DOI listed as [10.2139/ssrn.577056](https://doi.org/10.2139/ssrn.577056). License CC-BY-4.0.
- **Links:** [arXiv abstract](https://arxiv.org/abs/2511.18578) · [ar5iv full text](https://ar5iv.labs.arxiv.org/html/2511.18578) · [Semantic Scholar](https://www.semanticscholar.org/paper/Re(Visiting)-Time-Series-Foundation-Models-in-Rahimikia-Ni/af8d9a72cf46dd49eac97b200719cb1609527662)

**Design.** "the first comprehensive empirical study of TSFMs in global financial markets". Daily **excess** returns, **34 years**, **94 countries**, **~2 billion observations**. Test markets include the US, Hong Kong, Taiwan, South Korea, Germany, UK, India, Australia. Rolling/expanding windows of **5, 21, 252 and 512** trading days, evaluation over **2001–2023**. Target: **next-day cross-sectional excess return**. Three regimes evaluated: (i) zero-shot, (ii) fine-tuned on financial data, (iii) pretrained **from scratch** on finance data (year-by-year, so no future information).

**Models:** focal models **Chronos** and **TimesFM**, plus **twelve additional TSFM architectures** in the appendix. Benchmarks: linear (OLS, Lasso, Ridge, Elastic Net, PCR), **tree ensembles (CatBoost, XGBoost, LightGBM)**, and neural networks.

**Headline numbers [PAPER CLAIM]:**

| Setting | Metric | Value |
|---|---|---|
| OLS linear, US (avg. across windows) | out-of-sample R² | **−0.47%** |
| CatBoost, all US stocks | out-of-sample R² | **−0.10%** |
| All four windows, benchmarks | directional accuracy | **just above 51%** |
| CatBoost best (window 252), L/S, daily rebalance, **no transaction costs** | annualised return / Sharpe | **46.50% / 6.79** |
| **Chronos (large), zero-shot, window 512** | R² / dir. acc. / ann. return | **−1.37% / just above 51% / 20.17%** |
| **TimesFM (500M), zero-shot, window 512** | R² / dir. acc. / ann. return | **−2.80% / just below 50% / −1.47%** |
| Chronos (small), **pretrained from scratch**, window 5 | R² (from → to) | **−77.07% → −3.18%** |
| Chronos (small), pretrained from scratch, window 512 | R² (from → to) | **−1.27% → −0.59%** |
| Chronos (small), from scratch, window 512 | ann. return / Sharpe | **36.84% / 5.42** |
| TimesFM (20M), from scratch, window 512 | ann. return / Sharpe | **30.36% / 3.66** |
| Chronos (small) + financial factors + synthetic augmentation | dir. acc. / ann. ret. / Sharpe | **51.74% / 41.89% / 6.78** |
| CatBoost, same setting, window 512 | dir. acc. / ann. ret. / Sharpe | **51.16% / 47.25% / 6.46** |

**Other findings:**
- Fine-tuning off-the-shelf TSFMs on financial data "yields limited improvements and fails to close the performance gap". Most fine-tuned TSFM performance **deteriorates**, except Chronos (large) — and that improvement "does not translate into economic gains".
- Small-capitalisation firms exhibit greater predictability than large-caps.
- The **long leg consistently outperforms the short leg** across all model classes.
- Hyperparameter tuning matters enormously: "with appropriate optimization, TSFMs are capable of outperforming benchmark models even without scaling the dataset."
- Performance degrades over time for all models, but "the decline is markedly slower and less severe for TSFMs."
- Non-US markets (seven major non-US markets) show broadly consistent results.

**Why this paper matters for leakage:** the authors explicitly state they pretrain from scratch **per year using only data available up to that point** "to ensure that the models are not exposed to information from future periods, **thereby preventing look-ahead bias, an issue that may arise when employing off-the-shelf TSFMs**." This is the clearest statement in the literature that off-the-shelf TSFM evaluations in finance carry a look-ahead problem. **[PAPER CLAIM + explicit methodological warning]**

**Reproducibility:** the authors state all models are public ([FinText.ai](https://FinText.ai), [huggingface.co/FinText](https://huggingface.co/FinText)). I did **not** independently reproduce these numbers. **[PAPER CLAIM]**

**Caveats I flag:** the Sharpe ratios (5–6.8) are computed **without transaction costs** on a daily-rebalanced long–short portfolio. Daily-rebalanced L/S equity portfolios at these turnover levels would be severely degraded by realistic costs. The paper says this explicitly.

---

### 1.2 Other cross-sectional work found

| Paper | Venue/date | What it does | Status |
|---|---|---|---|
| [Behavioral-Memory-Augmented Sparse Mixture-of-Experts Time-Series Foundation Model for Cross-Market Financial Return Forecasting](https://ieeexplore.ieee.org/document/11666474/) | IEEE Xplore, doc. 11666474 | A TSFM with MoE + behavioural memory for cross-market return forecasting | **[COULD NOT VERIFY]** — IEEE page surfaced in search but I could not retrieve abstract/authors/venue/year. Treat as unconfirmed. |
| [A Compact Selective State-Space Model for Cross-Sectional Stock Return Ranking from Raw Intraday Bars](https://arxiv.org/abs/2608.28060) | arXiv:2608.28060, v1 28 Aug 2026, v3 8 Sep 2026 | **Not a TSFM.** Deep SSM for A-share cross-section — see §4 | Verified, full abstract retrieved |
| [Foundational Transformer Models for Financial Time Series Forecasting](https://amslaurea.unibo.it/id/eprint/39602/) | MSc thesis, Univ. of Bologna | Thesis, not peer-reviewed | **[COULD NOT VERIFY]** content |
| [ACM DL 10.1145/3785706.3785728](https://dlnext.acm.org/doi/pdf/10.1145/3785706.3785728) | ACM DL | Title/source not established; snippet mentions "TSFMs are moving from conceptual promise to deployable instruments across financial forecasting" | **[COULD NOT VERIFY]** — search snippet only |
| [BForTFin: A Financial Domain-Aware Multiscale Evaluation Method for Time-Series Foundation Models](https://dl.acm.org/doi/full/10.1145/3768292.3770402) — Cheong & Hsuen | ICAIF '25 (ACM), DOI 10.1145/3768292.3770402 | A finance-specific **evaluation methodology** for TSFMs | Metadata verified via [Semantic Scholar](https://www.semanticscholar.org/paper/BForTFin%3A-A-Financial-Domain-Aware-Multiscale-for-Cheong-Hsuen/176457c0ee1b99a720fe2b4e228333bc768f5a8b); **full text blocked (HTTP 403)** — results NOT VERIFIED |

---

## 2. Single-asset / time-series TSFM applications to equity returns

### 2.1 Noguer i Alonso & Pereira Franklin (2026) — the paper the user asked about

> **Title correction:** the user referred to *"Pretrained Time-Series Foundation Models for Financial Returns."* The actual title is **"Pretrained Time-Series Foundation Models for Financial Return Forecasting."** The RePEc handle the user gave ([ideas.repec.org/p/arx/papers/2606.27100.html](https://ideas.repec.org/p/arx/papers/2606.27100.html)) is correct.

- **Authors:** Miquel Noguer i Alonso; Rodolfo Pereira Franklin — both at the **Artificial Intelligence Finance Institute** (per the arXiv HTML).
- **Venue/date:** [arXiv:2606.27100](https://arxiv.org/abs/2606.27100) [q-fin.MF], submitted **25 June 2026** (v1 only). License: arXiv perpetual non-exclusive. The HTML version is dated **August 24, 2026**.
- **Links:** [arXiv abstract](https://arxiv.org/abs/2606.27100) · [arXiv HTML](https://arxiv.org/html/2606.27100v1) · [RePEc/IDEAS](https://ideas.repec.org/p/arx/papers/2606.27100.html) · [PDF](https://arxiv.org/pdf/2606.27100)

**Design.** Five liquid US equities: **AAPL, AMZN, GOOG, JPM, META**. Both **linear and log returns**. Per-asset (univariate) 20-business-day-ahead forecast (**H = 20**), context **L = 512**, rolling-origin protocol, equalised context budget across all models.

**Models compared:**
- **TSFMs:** TimeGPT / TimeGPT-LH, **TimesFM-2.5**, **Moirai-2.0**, **Chronos**, **Chronos-2**
- **Train-from-scratch baselines:** NBEATS, NHITS, PatchTST, iTransformer, KAN

**Results [PAPER CLAIM]:**
- **8 of 10 task-level wins** go to pretrained TSFMs.
- **Moirai-2.0** and **TimesFM-2.5** achieve the strongest average ranks.
- Task winners: **TimesFM-2.5** → AAPL and JPM; **Moirai-2.0** → GOOG and one AMZN task; **Chronos** → the remaining AMZN task; **iTransformer** wins **both META tasks**.
- "**gains over the random-walk benchmark are small and sparse**".
- A **one-sided Diebold–Mariano test rejects equal or inferior predictive accuracy only for Chronos on AMZN and Moirai-2.0 on GOOG.** ⇒ **8 of 10 tasks are NOT statistically distinguishable from a zero-return random walk.**
- Skill scores reported in Section 5 are "**of order 10⁻³**".
- The paper states the population upper bound on R² is small, noting that "reported out-of-sample R² values in the cross-sectional return-prediction literature are typically **below 1%**" (citing Rahimikia et al.).
- KAN is noted as "the only train-from-scratch model that consistently breaks into the top tier."

**Authors' own conclusion (verbatim from abstract):** TSFMs "serve as useful practical priors that reduce model-development costs in low-data financial forecasting, but are **not universal engines for statistically reliable alpha generation** in realistic empirical deployment."

**Theory contribution:** the paper frames pretraining as an **inductive prior** (Bayesian reading π_pre(θ) ∝ π₀(θ)exp(−n_pre·ℛ̂_pre(θ))), with a PAC-Bayes bound for zero-shot transfer, information-theoretic predictability bounds, an operator-theoretic view of attention, spectral-gap/mixing-time analysis, and information geometry of pretrained forecasters. It also includes a section on **Cross-Modality Reprogramming (Time-LLM)**.

**Status:** **[PAPER CLAIM]** — single-author-team working paper, not peer-reviewed, not independently reproduced. It is a **per-asset** study, **not** cross-sectional selection, and n = 5 assets. Do **not** generalise the "8 of 10 wins" headline to cross-sectional stock selection.

---

### 2.2 Other single-asset / applied finance TSFM work

| Paper | Venue/date | Models | Finding | Status |
|---|---|---|---|---|
| [Kronos: A Foundation Model for the Language of Financial Markets](https://arxiv.org/abs/2508.02739) — Shi, Fu, Chen, Zhao, Xu, Zhang & Li | arXiv:2508.02739 (2 Aug 2025); **AAAI 2026** ([DOI 10.1609/aaai.v40i30.39730](https://dl.acm.org/doi/10.1609/aaai.v40i30.39730), [AAAI OJS](https://ojs.aaai.org/index.php/AAAI/article/view/39730)); also listed at [NeurIPS 2025](https://neurips.cc/virtual/2025/loc/san-diego/130441) | Kronos (finance-native TSFM) | **Zero-shot RankIC +93% vs leading TSFM; +87% vs best non-pre-trained baseline; −9% MAE in volatility forecasting; +22% generative fidelity.** Trained on **12B K-line records, 45 global exchanges** | **[PAPER CLAIM]** — not independently reproduced |
| [Foundation Time-Series AI Model for Realized Volatility Forecasting](https://arxiv.org/abs/2505.11163) — Goel, Pasricha, Magris & Kanniainen | arXiv:2505.11163, 16 May 2025 | **TimesFM** | Pretrained (zero-shot) TimesFM gives "a reasonable baseline"; **incremental fine-tuning is essential**; fine-tuned variants **statistically outperform** traditional models via Diebold–Mariano and Giacomini–White tests | **[PAPER CLAIM]** |
| [Kronos Chinese guide (A-share)](https://github.com/Vincentwei1021/kronos-guide-cn) / [AICHINA.news write-up](https://aichina.news/blog/kronos-the-chinese-foundation-model-reimagining-stock-market-8wscsf/) | GitHub / blog, June 2026 | Kronos | Claims A-share integration via AKShare/Tushare/Baostock and that Kronos "significantly outperform[s] general-purpose models like Google's TimesFM and Meta's Chronos" | **[UNVERIFIED — secondary source; auto-generated from GitHub]** |
| [中金 (CICC) 大模型系列（5）：大语言时序模型Kronos的A股择时应用](https://reportify.ai/social-media/730544331169394) | Sell-side report (CICC), surfaced via aggregator | Kronos | A-share market-timing application | **[COULD NOT VERIFY]** — aggregator only, no numbers retrieved |

**A useful critique that is *inside* an application paper:** the Kronos abstract itself states that TSFMs' "application to financial candlestick (K-line) data **remains limited, often underperforming non-pre-trained architectures**." ([arXiv:2508.02739](https://arxiv.org/abs/2508.02739)) That is a finance-native TSFM team conceding that generic TSFMs lose to non-pretrained models on financial data.

---

## 3. The DLinear thread and the deep-model-vs-simple-baseline critique

### 3.1 The core paper (user asked for exact authors + link — note the correction)

- **Exact title:** *Are Transformers Effective for Time Series Forecasting?*
- **Authors:** **Ailing Zeng, Muxi Chen, Lei Zhang, Qiang Xu** — **NOT** "Zhou et al." or similar. (The user's prompt did not name authors, but this is the canonical attribution and it is frequently mis-cited.)
- **Venue/year:** **AAAI 2023** ([AAAI OJS record](https://ojs.aaai.org/index.php/AAAI/article/view/26317)); preprint [arXiv:2205.13504](https://arxiv.org/abs/2205.13504), v1 **26 May 2022**, v3 **17 Aug 2022**.
- **Code:** [github.com/cure-lab/LTSF-Linear](https://github.com/cure-lab/LTSF-Linear)

**What it claimed [PAPER CLAIM]:**
1. Transformers are arguably the best tool for extracting *semantic* correlations in a long sequence, but time-series modelling requires extracting *temporal* relations in an **ordered** set of continuous points.
2. Positional encoding + sub-series tokenisation preserve *some* ordering, but "the nature of the **permutation-invariant self-attention** mechanism inevitably results in **temporal information loss**."
3. They introduce **LTSF-Linear**, "a set of embarrassingly simple **one-layer linear models**", and report that on **nine real-life datasets** it "**surprisingly outperforms existing sophisticated Transformer-based LTSF models in all cases, and often by a large margin**."
4. They advocate "revisiting the validity of Transformer-based solutions for other time series analysis tasks (e.g., anomaly detection)."

**Why it matters for TSFMs:** DLinear is the origin of the "a linear layer beats your Transformer" critique that every TSFM evaluation now has to answer. The DLinear result is about **long-term multivariate forecasting benchmarks (LTSF)**, *not* about foundation models and *not* about finance. Do not over-extend it.

**Independently reproduced?** The result has been widely re-run in follow-up work and is generally treated as credible **for the LTSF benchmarks**, though see §3.3 — I could **not** find a peer-reviewed paper establishing that the underlying LTSF benchmark numbers are non-reproducible.

---

### 3.2 "The Capacity and Robustness Trade-off" — **the user's attribution is wrong**

- **Exact title:** *The Capacity and Robustness Trade-off: Revisiting the Channel Independent Strategy for Multivariate Time Series Forecasting*
- **Authors:** **Lu Han, Han-Jia Ye, De-Chuan Zhan** (Nanjing University) — **NOT Tan et al.**
- **Venue/date:** [arXiv:2304.05206](https://arxiv.org/abs/2304.05206), 11 Apr 2023. Also published in **IEEE TKDE** (per [Peeref record](https://www.peeref.com/works/84117913)).

**What it claims [PAPER CLAIM]:** Channel-Independent (CI) training — treating multivariate series as separate univariate series and ignoring cross-channel correlation — "outperform[s] those trained with the Channel Dependent (CD) strategy, usually by a significant margin." Their explanation: **CD has higher capacity but often lacks robustness** to distributionally-drifted series; **CI trades capacity for robustness**. They propose Predict Residuals with Regularization (PRReg).

**Relevance:** this is the theoretical backbone of the "simplicity wins under distribution shift" argument, and distribution shift is exactly the regime of financial returns. The Rahimikia et al. finance paper independently echoes this logic (longer context ⟹ better for TSFMs, shorter windows ⟹ better for benchmarks).

---

### 3.3 Follow-up critiques and the benchmark-integrity literature

| Item | Link | What it says | Status |
|---|---|---|---|
| **TiDE** — *Long-term Forecasting with TiDE: Time-series Dense Encoder* (Das, Kong, Leach, Mathur, Sen, Yu) | [arXiv:2304.08424](https://arxiv.org/abs/2304.08424) | A **pure MLP** encoder-decoder that is competitive with or better than Transformer LTSF models — reinforcing the DLinear argument that attention is not the source of the gains | Verified (abstract retrieved via arXiv HTML mirror) |
| **What Matters in Deep Learning for Time Series Forecasting?** | [arXiv:2512.22702](https://arxiv.org/abs/2512.22702) | Ablation-style study; sections on "Exogenous variables and preprocessing" | **[COULD NOT VERIFY]** — surfaced in search, abstract not retrieved |
| **Noise or Signal? Deconstructing Contradictions and an Adaptive Remedy for Reversible Normalization in Time Series Forecasting** | [arXiv:2510.04667](https://arxiv.org/abs/2510.04667) | Directly about **reversible-instance-normalisation** pathologies in TSF evaluation — i.e. the normalisation step that can leak/alter difficulty | **[COULD NOT VERIFY]** — full text not retrieved |
| **TSLib** (thuml/Time-Series-Library) | [github.com/thuml/Time-Series-Library](https://github.com/thuml/Time-Series-Library) | The de-facto standard LTSF benchmark harness used by DLinear, iTransformer, PatchTST and others | Verified as existing; **no paper found asserting its numbers are non-reproducible** |
| **"Are Transformers Really Effective…" (follow-up by that name)** | — | **NOT FOUND.** I could not locate a paper with this title. | **NOT FOUND** |
| **A peer-reviewed paper showing TSLib benchmark numbers are not reproducible** | — | **NOT FOUND.** This is a widely-repeated claim in blog posts and paper introductions, but I could not locate a formal, peer-reviewed reproducibility audit of TSLib. | **NOT FOUND** |
| **A peer-reviewed paper showing naive baselines (last-value / seasonal-naive / mean) beat deep models on LTSF benchmarks** | — | **NOT FOUND** as a dedicated paper. The closest verified evidence is in *adjacent* domains: [arXiv:2506.08113](https://arxiv.org/abs/2506.08113) (electricity) and [arXiv:2609.10357](https://arxiv.org/abs/2609.10357) (seasonal-naive ties pretrained models on daily FX). | **NOT FOUND** |

### 3.4 The "virtue of complexity" debate — the finance analogue of DLinear

This is the finance-native version of "does complexity beat a linear model?" and it is directly relevant.

- **The complexity claim:** Kelly, Malamud & Zhou (2024), *The Virtue of Complexity in Return Prediction*, **Journal of Finance** — [DOI 10.1111/jofi.13298](https://onlinelibrary.wiley.com/doi/full/10.1111/jofi.13298). Argues models with thousands of parameters trained on a short span of financial data can outperform simpler benchmarks when appropriately regularised.
- **The rebuttal with numbers:** **Daniel Buncic** (Stockholm Business School), *Simplified: A Closer Look at the Virtue of Complexity* — [SSRN 5239006](https://papers.ssrn.com/sol3/papers.cfm?abstract_id=5239006). Per the [Stockholm University news release](https://www.okc.albanova.se/english/divisions/stockholm-business-school/news/articles/2025-09-25-new-research-debunks-the-virtue-of-complexity-in-return-prediction-in-finance): the "virtue of complexity" is an artefact of **(i)** KMZ restricting the model intercept to zero and **(ii)** a "paradoxical aggregation scheme". A **simple expanding-window linear regression with mild shrinkage achieves a Sharpe ratio of 0.699, vs 0.485 for KMZ's most complex model.** **[PAPER CLAIM]**
- **Press coverage:** [Financial Times — "Are bigger AI models better stock pickers? Maybe, but probably not"](https://www.ft.com/content/89d88cbf-a92c-43d2-b8af-88ae26529be0) · [Bloomberg — "AQR's Hard-to-Believe Study Spurs Clash Over AI Use for Quants"](https://www.bloomberg.com/news/articles/2025-08-20/aqr-s-hard-to-believe-study-spurs-clash-over-ai-use-for-quants)
- **What Rahimikia et al. say about it:** their related-work section explicitly reviews this debate, noting a critique that high-complexity ridgeless Random Fourier Feature models "effectively reproduce a **volatility-timed momentum strategy** rather than uncovering genuine predictive signals", and a "**limited virtue of complexity**" result whereby noise in predictive features causes out-of-sample R² and Sharpe to *degrade* with complexity. ([ar5iv full text](https://ar5iv.labs.arxiv.org/html/2511.18578), §1.1) **[The exact identities of the critiques cited as refs [7],[9],[10],[35],[51] in that paper are NOT VERIFIED — I read the discussion but not the bibliography entries.]**

---

## 4. Critiques of TSFMs generally

### 4.1 Leakage and contamination — the strongest, best-documented critique

| Paper | Authors | Venue/date | Core claim |
|---|---|---|---|
| [**Rethinking Evaluation in the Era of Time Series Foundation Models: (Un)known Information Leakage Challenges**](https://arxiv.org/abs/2510.13654) | Marcel Meyer, Sascha Kaltenpoth, Kevin Zalipski, Oliver Müller | arXiv:2510.13654, v1 **15 Oct 2025**, v3 **25 Feb 2026** | Identifies **two leakage kinds**: (1) **train–test sample overlaps** from multi-purpose dataset reuse; (2) **temporal overlap of correlated train and test series**. Warns benchmarks "risks producing overly optimistic performance estimates that fail to generalize to real-world settings." Calls for new evaluation methodologies. |
| [**TSFMAudit: Data Contamination Auditing in Forecasting Time Series Foundation Models**](https://arxiv.org/abs/2605.26161) | Hongkai Li, Shifeng Xie, Lefei Shen, Zhuo Li, Mouxiang Chen, Xiaobin Zhang, Han Fu, Jianling Sun, Xiaoxue Ren, Chenghao Liu | arXiv:2605.26161, **24 May 2026** | "**the first work to study pretraining contamination auditing for TSFMs**". Method: probe-adaptation dynamics — contamination manifests as "unusually efficient adaptation… faster loss reduction with **smaller backbone movement**". Evaluated on **6 TSFMs and 187 datasets**, vs **10 baselines** adapted from the LLM literature. |
| [**A Later Test Set Is Not a New Domain: Pretraining Familiarity Survives a Contamination-Free Hold-Out**](https://arxiv.org/abs/2609.10357) | Mahdi Naser Moghadasi (BrightMind AI), Faezeh Ghaderi (UT Arlington) | arXiv:2609.10357, **9 Sep 2026** | Builds a hold-out where **every observation postdates the last model release**. **13 forecasters** (4 classical, 3 per-dataset, 6 pretrained), **7 groups**, 5 domains. |
| [**LLMs and foundational models: Not (yet) as good as hoped**](https://cbergmeir.com/papers/Bergmeir2024LLMs.pdf) | Christoph Bergmeir | *Foresight: The International Journal of Applied Forecasting*, **73**, 33–38, 2024 | The strongest independent critique: "when you check the reported empirical results, the performance is often **nowhere near as good as claimed**. Often the statistical benchmarks are **implemented poorly, or missing altogether, or highly selective**." |
| [**Evaluating time series foundation model claims**](https://robjhyndman.com/hyndsight/foundation_models.html) | Rob J. Hyndman | Hyndsight blog, **25 Aug 2026** | Practitioner-facing synthesis. States public benchmark scores are "**increasingly unreliable**"; cites Meyer et al.: of **401 datasets across 22 published TSFMs, only 6% had never appeared in any model's pre-training or fine-tuning corpus**; adds the **indirect-leakage** point (series not in training data can be correlated with series that are, e.g. via COVID). Also warns about inference cost, latency, vendor dependency. |
| [**TSFM-Bench**](https://arxiv.org/abs/2410.11802) | Zhe Li, Xiangfei Qiu, Peng Chen, Yihang Wang, Hanyin Cheng, Yang Shu, Jilin Hu, Chenjuan Guo, Aoying Zhou, Christian S. Jensen, Bin Yang | arXiv:2410.11802, 15 Oct 2024 (v6) | The reference unified benchmark; standardises dataset splitting, loading, **normalisation**, few-shot sampling. "we identify pros and cons and **inherent limitations** of existing TSFMs." |
| [**Context parroting: A simple but tough-to-beat baseline for foundation models in scientific machine learning**](https://proceedings.iclr.cc/paper_files/paper/2026/hash/5fbdcd4d2190682b913c6b39b58e95f0-Abstract-Conference.html) | — | **ICLR 2026** proceedings | Argues a trivially simple baseline is hard to beat for foundation models in SciML | **[PAPER CLAIM]** — abstract-level only |

### 4.2 The strongest single result: contamination-free hold-out still doesn't isolate skill

[Moghadasi & Ghaderi, arXiv:2609.10357](https://arxiv.org/abs/2609.10357) is worth stating in full because it is the cleanest experimental design I found:

- **Result 1:** Under a genuinely post-training hold-out, "**pretrained models win 5 of 7 groups, lose one to a Theta baseline, and on daily exchange rates are indistinguishable from a seasonal naive forecast, along with every other method tested.**"
- **Result 2 (a negative result):** "the two intrinsic properties one would reach for — **seasonal strength and spectral entropy** … do not account for the pattern, and **seasonal strength is if anything negatively associated with the advantage**."
- **Result 3:** "What does track it is **corpus familiarity**." Their largest gain — **28% lower MASE than the best classical method** — falls on **weekly Wikipedia pageviews**, "the domain TimesFM's authors describe as the bulk of its pretraining corpus."
- **Result 4:** "Within the pretrained family, where every model forecasts identical series so that series difficulty cancels, the **TimesFM family outranks the Chronos family by −0.53 ranks on Wikipedia against −0.09 everywhere else** (**1,500 vs. 754 series, Mann-Whitney p < 1e-5**)."
- **Conclusion:** "a temporal hold-out removes memorisation of a window but **not familiarity with a domain**," and "the practitioner's question is less which model is better than **whether their domain is one the model was raised on**."
- **Code/data:** [github.com/mahdinaser/tsfm-bench](https://github.com/mahdinaser/tsfm-bench)

**Direct implication for finance:** financial time series used as TSFM benchmarks (e.g. exchange rates, equity indices) are exactly the kind of data that sits in public pretraining corpora. Note in particular the **daily exchange rate** result — indistinguishable from seasonal naive.

### 4.3 Benchmarks outside finance where TSFMs lose

| Paper | Venue | Finding |
|---|---|---|
| [Benchmarking Pre-Trained Time Series Models for Electricity Price Forecasting](https://arxiv.org/abs/2506.08113) — Hornek Amir Sartipi, Tchappi & Fridgen | arXiv:2506.08113, 9 Jun 2025 | Chronos-Bolt, Chronos-T5, TimesFM, Moirai, Time-MoE, TimeGPT vs statistical/ML. Chronos-Bolt and Time-MoE are the strongest TSFMs, "**performing on par with traditional models**". But the **biseasonal MSTL model is consistently best, with no TSFM statistically outperforming it.** |
| [Evaluating Time-Series Foundation Models and Multimodal Dietary Context for CGM Forecasting](https://arxiv.org/abs/2609.11872) | arXiv:2609.11872, 10 Sep 2026 | 8 public CGM datasets. "**zero-shot foundation models did not consistently outperform strong task-specific baselines such as Elastic Net and PatchTST**." Lightweight fine-tuning helped substantially. |
| [Empirical evaluation of TSFMs for Day-ahead and Imbalance Electricity Price Forecasting in Belgium](https://arxiv.org/abs/2605.17045) | arXiv:2605.17045, 16 May 2026 | Counter-example: **Chronos-2 in ARX mode** most accurate; MAE **5% lower** than the best ML ensemble for day-ahead. |
| [Probabilistic Low-Voltage Peak Load Forecasting with TSFMs](https://arxiv.org/abs/2607.01966) | arXiv:2607.01966, 2 Jul 2026 | Counter-example: Chronos-2 superior on 200 real low-voltage feeders. |

**Note the pattern:** TSFMs win on observability/sensor/load data (Toto's and Chronos's home turf), and lose or tie on markets and noisy biological signals. That is consistent with the corpus-familiarity story of §4.2.

### 4.4 Deflationary results *within* the TSFM papers themselves

- **Chronos** ([arXiv:2403.07815](https://arxiv.org/abs/2403.07815), Ansari et al.): by the authors' own framing, Chronos "**significantly outperform[s] other methods on datasets that were part of the training corpus**" and only has "**comparable and occasionally superior**" zero-shot performance on new datasets. That is an admission that the headline results are partly in-distribution.
- **MOMENT** ([arXiv:2402.03885](https://arxiv.org/abs/2402.03885)): the authors state that "**experimental benchmarks to evaluate time series foundation models, especially in scenarios with limited resources, time, and supervision, are still in their nascent stages**."
- **Moirai-MoE** ([arXiv:2410.10469](https://arxiv.org/abs/2410.10469)) explicitly criticises the frequency-based specialisation heuristics of **Moirai** and **TimesFM**, calling frequency "**not a reliable indicator of the underlying patterns**".
- **UniTS** ([arXiv:2403.00131](https://arxiv.org/abs/2403.00131)): "the best-performing architectures **vary widely across tasks**."

### 4.5 Look-ahead bias in the LLM analogue

- **Sarkar, S. K. & Vafa, K. (2024), *Lookahead Bias in Pretrained Language Models*** — SSRN 4754678, [DOI 10.2139/ssrn.4754678](https://doi.org/10.2139/ssrn.4754678); presented at [ICML 2025](https://icml.cc/virtual/2025/48685). This is the canonical reference for pretraining-induced look-ahead bias in finance, and it is **cited by the FRL Chinese-stocks paper** (see §6).
- **Evaluating LLMs in Finance Requires Explicit Bias Consideration** — [arXiv:2602.14233](https://ar5iv.labs.arxiv.org/html/2602.14233). **[COULD NOT VERIFY]** in detail.
- **Cerqua et al. (2026), *On the (mis)use of machine learning with panel data***, *Oxford Bulletin of Economics and Statistics* 88:506, [DOI 10.1111/obes.70019](https://doi.org/10.1111/obes.70019) — also cited by the FRL paper. Relevant to panel-data leakage in cross-sectional finance ML.

---

## 5. Finance-specific critiques — consolidated

| Paper | Venue/date | Verdict on TSFMs | Verdict type |
|---|---|---|---|
| [Re(Visiting) TSFMs in Finance](https://arxiv.org/abs/2511.18578) — Rahimikia, Ni & Wang | arXiv:2511.18578, 23 Nov 2025 | Off-the-shelf TSFMs "**perform poorly**" zero-shot **and** after fine-tuning; finance-native pretraining is essential; look-ahead bias is an explicit hazard for off-the-shelf models | **The flagship critique** |
| [Pretrained TSFMs for Financial Return Forecasting](https://arxiv.org/abs/2606.27100) — Noguer i Alonso & Pereira Franklin | arXiv:2606.27100, 25 Jun 2026 | TSFMs are a useful **prior**, not an alpha engine; only **2/10** tasks beat random walk at DM significance | Neutral / deflationary |
| [Forecasting Realized Volatility with TSFMs: A Comparison with Econometric Benchmarks](https://arxiv.org/abs/2607.05291) — Alessio Brini | arXiv:2607.05291 [q-fin.ST], 6 Jul 2026 | 9 zero-shot TSFMs vs 8 econometric specs (incl. HAR family), [VOLARE dataset](https://arxiv.org/abs/2607.05291), 50 assets (equities/FX/futures), 3 horizons. Pooled losses favour TSFMs **but the advantage is concentrated in a few outlier assets**. Averaging per-asset loss ratios to a Log-HAR benchmark, **only Tiny Time Mixers (TTM) beats the benchmark at every horizon, and by a narrow margin**. A Mincer–Zarnowitz recalibration shows much of the short-horizon advantage is **better-scaled forecasts rather than better prediction of volatility dynamics**; only the **monthly** horizon retains a genuine informational gain. Equal-weight TTM+Log-HAR is in the **Model Confidence Set for 98–100% of assets**. Conclusion: "**choosing the right architecture matters more than the broader choice between foundation and econometric models**." | **Strong, well-designed critique** |
| [Foundation models do not beat simple volatility benchmarks: Evidence from 5000 Chinese stocks](https://doi.org/10.1016/j.frl.2026.110606) — Zhong, Fu & Zhu | *Finance Research Letters* **110**:110606, Nov 2026 issue | Title asserts the finding | See §6 — **numbers NOT VERIFIED** |
| [Kronos](https://arxiv.org/abs/2508.02739) — Shi et al. | AAAI 2026 | Generic TSFMs "often underperform non-pre-trained architectures" on K-line data | Finance-native team conceding generic TSFMs fail |
| [Can transformers transform financial forecasting?](https://www.emerald.com/cfri/article-abstract/doi/10.1108/CFRI-01-2024-0032/1249263/Can-transformers-transform-financial-forecasting) — Souto | *China Finance Review International*, 2024, [DOI 10.1108/CFRI-01-2024-0032](https://doi.org/10.1108/CFRI-01-2024-0032) | Cited by the FRL paper as part of the skeptical finance literature | **[COULD NOT VERIFY]** abstract — Emerald paywall |

---

## 6. A-share (China) cross-section specifically

### 6.1 The peer-reviewed A-share TSFM paper — metadata verified, **numbers NOT VERIFIED**

- **Exact title:** *Foundation models do not beat simple volatility benchmarks: Evidence from 5000 Chinese stocks*
- **Authors:** **Yilin Zhong** (first), **Yuqi Fu** (corresponding; ORCID [0009-0001-6443-695X](https://orcid.org/0009-0001-6443-695X)), **Sixuan Zhu** (ORCID [0009-0008-6970-2138](https://orcid.org/0009-0008-6970-2138))
- **Venue/bibliographic:** ***Finance Research Letters*, volume 110, article 110606**, print issue **November 2026**; online creation record **2 Aug 2026**; indexed **11 Aug 2026**
- **DOI:** [10.1016/j.frl.2026.110606](https://doi.org/10.1016/j.frl.2026.110606)
- **PII (as the user supplied):** [S1544612326011347](https://www.sciencedirect.com/science/article/abs/pii/S1544612326011347)
- **Links:** [ScienceDirect (403 for automated fetch)](https://www.sciencedirect.com/science/article/abs/pii/S1544612326011347) · [OpenAlex record W7172221594](https://openalex.org/W7172221594) · [Crossref metadata](https://api.crossref.org/works/10.1016/j.frl.2026.110606) · [EconPapers listing](https://econpapers.repec.org/article/eeefinlet/v_3a106_3ay_3a2026_3ai_3ac_3as1544612326008214.htm)

**⚠️ Important scope correction:** despite the generic word "foundation models" in the title, **this paper is about VOLATILITY forecasting, not return prediction or cross-sectional stock selection.** The user's framing ("A-share cross-section") does not match the title. Its reference list is unambiguously a volatility-forecasting bibliography (GARCH, HAR/Corsi, GAS, Markov-switching GARCH, realized measures, Patton's imperfect-proxy problem, Hansen's "does anything beat GARCH(1,1)").

**What I verified from the Crossref reference list** (this tells us exactly what was benchmarked, even without the abstract):
Chronos; TimesFM (`A decoder-only foundation model for time-series forecasting`); Moirai (`Unified training of universal time series forecasting transformers`); **Moirai-MoE**; **Lag-Llama**; **Kronos**; TSFM-Bench; **BForTFin**; ProbTS; Rahimikia et al. (2025); **Sarkar & Vafa (2024), Lookahead Bias in Pretrained Language Models**; Cerqua et al. (2026); Souto (2024); plus GARCH/HAR/GAS/Markov-switching baselines. Reference count: **40**.

**What I could NOT verify — and will not guess:**
- The abstract text.
- The exact TSFMs' MSE/MAE/QLIKE numbers.
- Whether the "5000 stocks" are the full A-share universe or a filtered panel.
- The sample period.
- Whether the conclusion is about zero-shot, fine-tuned, or both.

**Status: [METADATA VERIFIED] / [FINDINGS NOT VERIFIED].** ScienceDirect returns HTTP 403 to automated retrieval; OpenAlex stores `abstract_inverted_index: null`; Semantic Scholar API returned HTTP 429. I tried ScienceDirect (two URL forms), OpenAlex (fulltext + title search), Crossref, X-MOL, scilit, r.jina.ai, and Semantic Scholar. **If you need the numbers, this paper must be obtained through an institutional subscription or interlibrary loan.**

### 6.2 The most informative A-share cross-sectional result I found is NOT a TSFM paper

[**A Compact Selective State-Space Model for Cross-Sectional Stock Return Ranking from Raw Intraday Bars**](https://arxiv.org/abs/2608.28060) — Mingju Chen, Enze Zhang, Annan Li, Yui Lo, Xiaomin Yuan, Kaiming Yu, Jinhui Ren, Yuanhang Liu — arXiv:2608.28060 [cs.CE], v1 28 Aug 2026, v3 8 Sep 2026.

**Design:** "STRATA" (Staggered-Timescale Residual Architecture), **244,633 parameters**. Input: five trading days of **raw 5-minute bars and order-book data**, no hand-crafted features. Target: **next-day cross-sectional return ranking**. Universe: **~1,000 mid-capitalisation Chinese A-shares**, **4 years train / 1 held-out year**, evaluated **once**.

**Numbers [PAPER CLAIM]:**
- Style-residualised rank IC: **0.0728**
- Information ratio: **1.128**
- Signal long–short Sharpe: **12.85**
- Ahead of **six parameter-matched sequence baselines** on all four reported metrics; day-level paired rank-IC gap vs every baseline significant at **p < 0.001**.

**The critical part — and the reason I include it:**

1. **Style-residualisation is mandatory.** "Because a score that merely tilts toward common style factors scores well on raw rank correlations, **every model's scores are residualised against eight price-volume style factors before any metric is computed**." This is the single most important methodological warning for anyone building an A-share cross-sectional model: raw rank IC is contaminated by style exposure.
2. **The close-to-close target is not executable.** "**The close-to-close target opens before the score exists: measured instead from the first executable price, the decile spread is indistinguishable from zero**, while the ordering of the seven architectures is unchanged and STRATA's margin widens."

Point 2 is a devastating, generalisable finding: a headline Sharpe of 12.85 collapses to zero once you use an executable entry price. **[PAPER CLAIM]** — not independently reproduced, and the tension between "Sharpe 12.85" and "decile spread indistinguishable from zero" is itself a red flag about how such metrics are reported.

### 6.3 Other A-share / China TSFM evidence

| Item | Link | Evidence | Status |
|---|---|---|---|
| **Kronos** — Chinese finance-native TSFM | [arXiv:2508.02739](https://arxiv.org/abs/2508.02739) · [AAAI 2026](https://ojs.aaai.org/index.php/AAAI/article/view/39730) · [GitHub](https://github.com/shiyu-coder/Kronos) · [HF weights](https://huggingface.co/NeoQuasar/Kronos-base) | 12B K-line records across **45 global exchanges** (stocks, crypto, FX); explicitly designed for A-share microstructure such as price limits and T+1 (per [AICHINA summary](https://aichina.news/blog/kronos-the-chinese-foundation-model-reimagining-stock-market-8wscsf/)) | Model + paper verified; **A-share-specific numbers not independently reproduced** |
| **Kronos + Qlib A-share fine-tuning pipeline** | [github.com/leeroopedia/workflow-shiyu-coder-kronos-qlib-finetuning](https://github.com/leeroopedia/workflow-shiyu-coder-kronos-qlib-finetuning) | End-to-end: finetune Kronos tokenizer + predictor on **CSI300/CSI800/CSI1000** via Microsoft Qlib, then `TopkDropoutStrategy` backtest. Config: lookback **90**, predict **10**, epochs **30**, batch **50**, tokenizer LR **2e-4**, predictor LR **4e-5**, inference T **0.6**, sample_count **5**, hold **50**. Splits: train **2011-01-01→2022-12-31**; val **2022-09-01→2024-06-30**; test **2024-04-01→2025-06-05**; backtest **2024-07-01→2025-06-05** | **Community repo, not peer-reviewed. NO PERFORMANCE NUMBERS REPORTED in the README.** Note the val split overlaps the train end and the test split overlaps the val end (README explains this is "to account for lookback"). **This is directly runnable in your qlib workspace.** |
| **Zero-shot A-share stock prediction repo** | [github.com/chenking2020/zeroshot-astock-predict](https://github.com/chenking2020/zeroshot-astock-predict) | Chinese repo collecting ARIMA, time-series foundation models, and vision foundation models for **zero-shot, no-training** A-share price prediction. Benchmark: **225 series** (major indices + individual stocks across industries, mkt caps, P/Es). Results table: **ARIMA RMSE 11.64** vs **chronos_bolt_model RMSE 15.24**; trend accuracy ACC listed as "**待评测**" (to be evaluated) for both | **Community repo, unvetted, incomplete.** But it is the only direct A-share Chronos-Bolt-vs-ARIMA number I found, and **zero-shot Chronos-Bolt loses to ARIMA on RMSE (15.24 vs 11.64)** |
| **CICC (中金) Kronos A-share timing report** | [aggregator link](https://reportify.ai/social-media/730544331169394) | Sell-side application of Kronos to A-share market timing | **[COULD NOT VERIFY]** — no primary source reached |
| **Eastmoney report: 大模型如何征服K线图？** | [data.eastmoney.com](https://data.eastmoney.com/report/zw_macresearch.jshtml?encodeUrl=DSlDEcPhQg9YUtRjTVcp/SXHXDN+JhqE56kaNQbeOjk=) | Chinese sell-side research on LLMs/large models for K-line prediction | **[COULD NOT VERIFY]** |
| **Hexun article: 让每个人都变成量化机构，AI大模型预测股价是否靠谱？** | [news.hexun.com](https://news.hexun.com/2025-09-05/221239000.html) | Chinese financial media piece questioning whether LLM/TSFM stock prediction is reliable; discusses alpha decay and reports that Kronos's prediction for Moutai (SH600519) was **opposite** to the realized move | **[UNVERIFIED — secondary source]**; the page is behind a JS anti-bot challenge (I attempted GB18030 decoding and hit the challenge script). **Treat the Moutai claim as unverified.** |
| **Index/factor attempts with Moirai/TimesFM on A-shares** | — | **NOT FOUND.** I could not locate an arXiv paper applying **TimesFM, Moirai, Moirai-MoE, Lag-Llama, Sundial, Timer, TimeGPT, Toto, MOMENT, UniTS or TTM** to the **A-share cross-section** with reported IC/RankIC. | **NOT FOUND** |

---

## 7. Model-by-model coverage

Canonical citations verified via the arXiv API unless noted.

| Model | Owner | Canonical reference | Notes / finance evidence |
|---|---|---|---|
| **Chronos** | Amazon | [arXiv:2403.07815](https://arxiv.org/abs/2403.07815) — Ansari et al., 12 Mar 2024. T5-based (20M–710M), scaling + quantisation tokenisation, cross-entropy. 42-dataset benchmark. Authors themselves note strongest gains are **on training-corpus datasets** | Evaluated in [Rahimikia et al.](https://arxiv.org/abs/2511.18578) (zero-shot R² **−1.37%** at 512 window; L/S ann. return **20.17%**; from-scratch pretraining → R² **−0.59%**, Sharpe **5.42**) and [Noguer i Alonso & Franklin](https://arxiv.org/abs/2606.27100) (wins 1 AMZN task; **only asset where DM rejects the random walk**) |
| **Chronos-Bolt** | Amazon | **No standalone arXiv paper found.** Documented via the [HuggingFace model card `autogluon/chronos-bolt-base`](https://huggingface.co/autogluon/chronos-bolt-base) and referenced in [Chronos-2, arXiv:2510.15821](https://arxiv.org/html/2510.15821v1). The Chinese A-share repo describes it as a T5-based model trained on ~100B time-series observations, **250× faster** and **20× more memory-efficient** than original Chronos | Used in [electricity benchmark arXiv:2506.08113](https://arxiv.org/abs/2506.08113) (strongest TSFM, but MSTL still best); [Belgium EPF arXiv:2605.17045](https://arxiv.org/abs/2605.17045); [LV load arXiv:2607.01966](https://arxiv.org/abs/2607.01966); **lost to ARIMA on A-share RMSE** in [chenking2020 repo](https://github.com/chenking2020/zeroshot-astock-predict). **⚠️ There is no separate Chronos-Bolt paper — cite the model card or Chronos-2.** |
| **TimesFM** | Google | [arXiv:2310.10688](https://arxiv.org/abs/2310.10688) — Das, Kong, Sen & Zhou, 14 Oct 2023. Patched-decoder attention; zero-shot "comes close to" per-dataset SOTA | **The most-examined TSFM in finance.** [Rahimikia et al.](https://arxiv.org/abs/2511.18578): zero-shot R² **−2.80%**, dir. acc. **just below 50%**, L/S ann. return **−1.47%**; from-scratch (20M) → **30.36%**, Sharpe **3.66**. [Noguer i Alonso & Franklin](https://arxiv.org/abs/2606.27100): **TimesFM-2.5** top-2 average rank, wins AAPL + JPM. [Goel et al.](https://arxiv.org/abs/2505.11163): fine-tuned TimesFM beats econometric benchmarks. [Moghadasi & Ghaderi](https://arxiv.org/abs/2609.10357): TimesFM family advantage tracks Wikipedia-corpus familiarity |
| **Moirai** | Salesforce | [arXiv:2402.02592](https://arxiv.org/abs/2402.02592) — Woo, Liu, Kumar, Xiong, Savarese & Sahoo, 4 Feb 2024. Masked encoder; **LOTSA**, 27B observations, 9 domains | [Moirai-MoE](https://arxiv.org/abs/2410.10469) criticises Moirai's frequency-based projection layers as "not a reliable indicator" of underlying patterns. Evaluated in [Noguer i Alonso & Franklin](https://arxiv.org/abs/2606.27100) (**Moirai-2.0** top average rank; wins GOOG + 1 AMZN; **one of only two DM-significant beats of the random walk**). Also in the [FRL A-share paper](https://doi.org/10.1016/j.frl.2026.110606). |
| **Moirai-MoE** | Salesforce | [arXiv:2410.10469](https://arxiv.org/abs/2410.10469) — Liu, Liu, Woo, Aksu, Liang, Zimmermann, Liu, Savarese, Xiong & Sahoo, 14 Oct 2024. Single projection layer + sparse MoE; token-level specialisation; **39 datasets** | **Cited in the FRL A-share volatility paper.** No independent finance-specific evaluation found. |
| **Lag-Llama** | ServiceNow / Mila et al. | [arXiv:2310.08278](https://arxiv.org/abs/2310.08278) — Rasul, Ashok, Williams, Ghonia, Bhagwatkar, Khorasani, Darvishi Bayazi, Adamopoulos, Riachi, Hassen, Biloš, Garg, Schneider, Chapados, Drouin, Zantedeschi, Nevmyvaka & Rish, 12 Oct 2023. Decoder-only, **lags as covariates**, univariate probabilistic | **Cited in the FRL A-share volatility paper.** Referenced sceptically in a [quant blog](https://jonathankinlay.com/category/quantitative-research/). **No peer-reviewed stock-return application found.** |
| **Timer** | Tsinghua (THUML) | [arXiv:2402.02368](https://arxiv.org/abs/2402.02368) — Liu, Zhang, Li, Huang, Wang & Long, 4 Feb 2024. GPT-style, **1B time points**, S3 format, unified generative task | Also [Timer-XL, arXiv:2410.04803](https://ar5iv.labs.arxiv.org/html/2410.04803). **No finance application found.** [GitHub](https://github.com/thuml/Large-Time-Series-Model) |
| **Sundial** | Tsinghua (THUML) | [arXiv:2502.00816](https://arxiv.org/abs/2502.00816) — Liu, Qin, Shi, Chen, Yang, Huang, Wang & Long, 2 Feb 2025. **TimeFlow Loss** (flow-matching), no discrete tokenisation; **TimeBench, 1 trillion time points** | Chinese coverage: [36Kr](https://www.36kr.com/p/3344470922576771), [36Kr EN](https://eu.36kr.com/en/p/3344470922576771). **No finance application found.** |
| **TimeGPT** | Nixtla | [arXiv:2310.03589](https://arxiv.org/abs/2310.03589) — Garza, Challu & Mergenthaler. First commercial TSFM | Evaluated in [Noguer i Alonso & Franklin](https://arxiv.org/abs/2606.27100) (TimeGPT / TimeGPT-LH) and in [electricity benchmark](https://arxiv.org/abs/2506.08113). **No reported IC/Sharpe in a cross-sectional finance setting found.** |
| **Toto** | Datadog | [arXiv:2407.07874](https://arxiv.org/abs/2407.07874) — Cohen, Khwaja, Wang, Masson, Ramé, Doubli & Abou-Amal, 10 Jul 2024. **1 trillion data points**, 75% of which are anonymous Datadog observability metrics | [Toto 2 released with up to 2.5B parameters](https://en.theblockbeats.news/flash/346149); [GitHub](https://github.com/DataDog/toto). **No stock-return application found.** Note the training corpus is observability metrics — i.e. **not** a finance-familiar domain. |
| **TinyTimeMixers (TTM)** | IBM | [arXiv:2401.03955](https://arxiv.org/abs/2401.03955) — Ekambaram, Jati, Dayama, Mukherjee, Nguyen, Gifford, Reddy & Kalagnanam, 8 Jan 2024. **From 1M parameters**, TSMixer-based | **The only TSFM to beat a well-specified Log-HAR benchmark at every horizon in [Brini (2026)](https://arxiv.org/abs/2607.05291)** — and only by a narrow margin. Also released as [IBM Granite TTM r1/r2](https://huggingface.co/ibm-granite/granite-timeseries-ttm-r1). |
| **MOMENT** | CMU | [arXiv:2402.03885](https://arxiv.org/abs/2402.03885) — Goswami, Szafer, Choudhry, Cai, Li & Dubrawski, 6 Feb 2024. "Time series Pile"; multi-task (forecasting, classification, anomaly detection, imputation). Authors state limited-supervision benchmarks are "still in their nascent stages" | **No stock-return application found.** |
| **UniTS** | MIT/Harvard | [arXiv:2403.00131](https://arxiv.org/abs/2403.00131) — Gao, Koker, Queen, Hartvigsen, Tsiligkaridis & Zitnik, 29 Feb 2024. Unified multi-task, task tokenisation; 38 datasets **including finance** | Evaluated on finance datasets as part of its 38, but **no reported cross-sectional stock-selection IC/Sharpe found**. |
| **TimesURGE** | — | **NOT FOUND.** I searched for "TimesURGE" as a time-series foundation model and found **no such model**. The only search hits were an unrelated Japanese hair-care product ("Aujua TIMESURGE", [milbon.co.jp](https://www.milbon.co.jp/ir/pdf/20130222_aujua-timesurge-e.pdf)). | **⚠️ Almost certainly a non-existent / mis-remembered model name. Do not cite it.** If you meant a specific paper, please re-check the name. |

---

## 8. Synthesis — what a practitioner should actually conclude

1. **Do not expect a generic, off-the-shelf TSFM to produce alpha in a cross-sectional equity setting.** The best-designed study on the question ([Rahimikia et al.](https://arxiv.org/abs/2511.18578)) finds off-the-shelf Chronos/TimesFM underperform CatBoost/XGBoost/LightGBM in zero-shot, degrade further under naive fine-tuning, and only become competitive after **finance-native pretraining from scratch**. Even then they do not beat the ensembles on goodness-of-fit.

2. **The wins that are reported are mostly not statistically distinguishable from a random walk.** [Noguer i Alonso & Franklin](https://arxiv.org/abs/2606.27100): 8/10 task wins, but Diebold–Mariano rejects the random walk for only **2/10**. Skill scores ~10⁻³.

3. **Fine-tuning on your own domain is the single highest-value intervention** — but it is a *data* intervention, not a *model* intervention. Three independent papers converge: [Rahimikia et al.](https://arxiv.org/abs/2511.18578) (from-scratch finance pretraining fixes Chronos's R² gap), [Goel et al.](https://arxiv.org/abs/2505.11163) (incremental fine-tuning essential for TimesFM on RV), [Brini](https://arxiv.org/abs/2607.05291) ("choosing the right architecture matters more than the broader choice between foundation and econometric models").

4. **Assume contamination until proven otherwise.** [Meyer et al.](https://arxiv.org/abs/2510.13654) + [TSFMAudit](https://arxiv.org/abs/2605.26161) + [Moghadasi & Ghaderi](https://arxiv.org/abs/2609.10357) + [Hyndman](https://robjhyndman.com/hyndsight/foundation_models.html): 94% of benchmark datasets have appeared in some TSFM's training corpus, and even a post-release temporal hold-out does not remove **domain familiarity**. For equity data specifically — indices, FX, major US names — this is a first-order problem.

5. **For A-shares, the two hard methodological lessons are (a) residualise against style factors and (b) use an executable entry price.** Both come from [STRATA, arXiv:2608.28060](https://arxiv.org/abs/2608.28060), where rank IC 0.0728 / Sharpe 12.85 becomes a **decile spread indistinguishable from zero** under an executable entry. Raw A-share rank IC is inflated by style tilt.

6. **The cheapest legitimate experiment for you** (given the qlib workspace): the [Kronos + Qlib A-share fine-tuning pipeline](https://github.com/leeroopedia/workflow-shiyu-coder-kronos-qlib-finetuning) is ready-made for CSI300/800/1000 with `TopkDropoutStrategy`. But **it publishes no performance numbers** — so run it as a *measurement*, not a *solution*, and benchmark it against CatBoost/XGBoost and a plain linear model, which is what the literature says you actually have to beat.

---

## 9. COULD NOT VERIFY

Explicit list of everything I could not confirm. **Nothing in this section should be cited as fact.**

### 9.1 Numbers I could not obtain
1. **Any number from Zhong, Fu & Zhu (2026), *Finance Research Letters* 110:110606.** Abstract, sample period, metric values — all unretrieved. ScienceDirect returned **HTTP 403** on two URL forms; the Elsevier text-mining links in the Crossref record require an API key; OpenAlex stores a null abstract; Semantic Scholar returned **HTTP 429**; X-MOL and scilit returned empty/403; r.jina.ai proxy failed. **The paper's title-only claim ("foundation models do not beat simple volatility benchmarks") is all I can report.** Also note: it is a **volatility** paper, not a return/cross-section paper.
2. **BForTFin results** (Cheong & Hsuen, ICAIF '25, DOI 10.1145/3768292.3770402). ACM DL returned **HTTP 403**.
3. **"Behavioral-Memory-Augmented Sparse Mixture-of-Experts Time-Series Foundation Model for Cross-Market Financial Return Forecasting"** (IEEE Xplore doc. 11666474). Authors, venue, year and results all unverified.
4. **ACM DL 10.1145/3785706.3785728** — title, authors and venue not established; only a search snippet.
5. **Souto (2024), *Can transformers transform financial forecasting?*** — Emerald paywall; only the citation is verified.
6. **`Foundational Transformer Models for Financial Time Series Forecasting`** (Univ. of Bologna MSc thesis) — content unretrieved; it is a thesis, not peer-reviewed.
7. **The exact identities of the "virtue of complexity" critiques cited as references [7], [9], [10], [35], [51] in Rahimikia et al.** I read the discussion text but did not resolve the bibliography entries. Treat the described positions as accurate, the attributions as unverified.
8. **The Moutai (SH600519) claim in the Hexun article** — the page is behind a JS anti-bot challenge; I could not read the body text.
9. **CICC (中金) Kronos A-share timing report** and the **Eastmoney 大模型如何征服K线图 report** — aggregator/paywall only.
10. **Any IC / RankIC / Sharpe for TimesFM, Moirai, Moirai-MoE, Lag-Llama, Sundial, Timer, Toto, MOMENT, UniTS or TTM on an A-share cross-section.** **NOT FOUND.**

### 9.2 Papers/artifacts I could not find at all
11. **"TimesURGE"** as a time-series foundation model — **NOT FOUND**. The only hits are an unrelated Japanese hair-care product. **This name is very likely erroneous.**
12. **A dedicated Chronos-Bolt paper** — **NOT FOUND**. Cite the [HuggingFace model card](https://huggingface.co/autogluon/chronos-bolt-base) or [Chronos-2, arXiv:2510.15821](https://arxiv.org/html/2510.15821v1) instead.
13. **A paper titled "Are Transformers Really Effective…"** — **NOT FOUND.**
14. **A peer-reviewed paper demonstrating that TSLib benchmark numbers are non-reproducible.** **NOT FOUND.** The claim is widely repeated but I found no formal audit.
15. **A peer-reviewed paper showing naive baselines (last-value / seasonal-naive / mean) beat deep models on the standard LTSF benchmarks.** **NOT FOUND** as a dedicated paper. The nearest verified evidence is from adjacent domains ([electricity](https://arxiv.org/abs/2506.08113), [daily FX](https://arxiv.org/abs/2609.10357)).
16. **"Are Time Series Foundation Models Ready for Financial Forecasting?"** — I searched this exact phrasing. **NOT FOUND.** The closest actual papers are [Rahimikia et al. (2511.18578)](https://arxiv.org/abs/2511.18578), [Brini (2607.05291)](https://arxiv.org/abs/2607.05291), and [Zhong et al. (FRL 2026)](https://doi.org/10.1016/j.frl.2026.110606).
17. **A paper specifically on pretraining contamination *in finance* for TSFMs.** [TSFMAudit](https://arxiv.org/abs/2605.26161) covers TSFMs generally (not finance-specific); [Sarkar & Vafa](https://doi.org/10.2139/ssrn.4754678) covers LLMs, not TSFMs. **The finance-specific TSFM contamination paper appears NOT to exist yet.**

### 9.3 Attribution corrections
18. **"The Capacity and Robustness Trade-off" (Tan et al.)** — the user's attribution is **incorrect**. The paper is by **Lu Han, Han-Jia Ye & De-Chuan Zhan**, [arXiv:2304.05206](https://arxiv.org/abs/2304.05206).
19. The RePEc paper the user named is titled *"Pretrained Time-Series Foundation Models for Financial **Return Forecasting**"* — not "...Financial **Returns**." Only a truncation difference, but the exact title matters for citation.
20. **The FRL A-share paper is about volatility, not cross-sectional stock selection**, despite the generic "foundation models" framing.

### 9.4 Reproducibility status summary
- **[INDEPENDENTLY REPRODUCED]:** **nothing in this report.** Every performance number I report is a **paper claim**. DLinear's core result is widely treated as credible *for the LTSF benchmarks* but I found no formal third-party reproduction paper either.
- The strongest *cross-checks* available are: (a) multiple independent papers converging on the same qualitative conclusion (off-the-shelf TSFMs ≈ or worse than strong benchmarks outside their pretraining domain); (b) [Moghadasi & Ghaderi](https://arxiv.org/abs/2609.10357), which reproduces the *pattern* of TSFM advantage tracking corpus familiarity rather than intrinsic series properties.

---

## 10. Search log

Distinct search queries executed (via `web_search`), plus direct fetch/API probes:

1. "Pretrained Time-Series Foundation Models for Financial Returns" arXiv
2. time series foundation model stock returns cross-sectional stock selection 2026
3. Chronos TimesFM Moirai A-share stock return prediction paper arXiv
4. foundation model cross-sectional stock ranking zero-shot
5. "Foundation models do not beat simple volatility benchmarks" Chinese stocks Finance Research Letters
6. Sciencedirect S1544612326011347 foundation models volatility benchmarks
7. "Are Transformers Effective for Time Series Forecasting" DLinear AAAI 2023 authors arXiv
8. time series foundation models fail simple baselines zero-shot evaluation critique 2026
9. "When Foundation Models are One-Liners" ICLR 2026 time series limitations
10. "Foundation models do not beat simple volatility benchmarks" 5000 Chinese stocks abstract
11. "Are Time Series Foundation Models Ready for Financial Forecasting"
12. TSLib benchmark evaluation issues reproducibility deep learning time series forecasting critique
13. "Capacity and Robustness Trade-off" Tan time series forecasting efficient transformer
14. TiDE long-term forecasting linear model dense encoder arXiv
15. Chronos foundation model zero-shot stock return prediction China A-share empirical
16. data leakage pretraining contamination time series foundation models evaluation look-ahead bias
17. Toto Datadog time series foundation model finance evaluation
18. TimesURGE time series foundation model universal representation finance
19. TSFMAudit data contamination auditing forecasting time series foundation models arXiv
20. "S1544612326011347" OR "Foundation models do not beat simple volatility benchmarks" authors
21. time series foundation model A-share China stock cross-section IC RankIC 2026
22. Lag-Llama TimesFM Moirai fine-tune stock return ranking portfolio Sharpe
23. LTSF benchmark test set contamination leakage "Are Transformers Effective" follow-up critique
24. "Are Transformers Really Effective" time series forecasting follow-up paper
25. time series forecasting benchmark evaluation protocol flawed scaling normalization leakage DLinear criticism
26. A-share stock return prediction timeseries foundation model Chronos TimesFM Chinese market empirical study
27. Kronos foundation model financial candlestick arXiv "Kronos" K-line tokenizer AAAI 2026
28. Sundial time series foundation model arXiv 2502 Tsinghua generative
29. Moirai-MoE Salesforce sparse mixture of experts time series arXiv
30. Lag-Llama probabilistic foundation model time series arXiv 2310
31. "Foundation models do not beat simple volatility benchmarks" doi 10.1016/j.frl
32. colab.ws OR ouci.dntb.gov.ua OR scite "Foundation models do not beat..."
33. Kronos foundation model language of financial markets arXiv 2508 K-line
34. "volatility" "foundation model" Chinese A-share 5000 stocks zero-shot HAR benchmark 2026 results
35. A股 时序大模型 选股 Chronos TimesFM 实证 超额收益
36. cross-sectional stock selection pretrained time series model A-share China IC rank IC foundation model 2026
37. BForTFin financial domain-aware multiscale evaluation time-series foundation models ICAIF 2025
38. Souto "Can transformers transform financial forecasting" China Finance Review International
39. Goel "Foundation time-series AI model for realized volatility forecasting" arXiv 2505.11163
40. Sarkar Vafa lookahead bias pretrained language models finance
41. Chronos-Bolt arXiv paper "Chronos-Bolt" accurate efficient zero-shot forecasting Ansari
42. "TimesURGE" time series foundation model arXiv
43. TimeGPT-1 Garza arXiv 2310.03589 zero-shot inference time series
44. TSFM-Bench comprehensive unified benchmark foundation models time series forecasting findings
45. "BForTFin" Cheong Hsuen financial domain-aware multiscale evaluation results
46. A-share 沪深300 时序基础模型 Chronos 因子 选股 实证 2026
47. "The Capacity and Robustness Trade-off" Tan channel independence multivariate time series authors arXiv
48. "virtue of complexity" return prediction critique Kelly Malamud Zhou rebuttal
49. FT "Are bigger AI models better stock pickers" time series foundation models finance
50. "time series foundation model" China A-share finetune alpha factor mining arXiv 2026
51. "Chronos-Bolt" paper arXiv 2024 direct multi-step quantile forecasting T5
52. Chronos-2 arXiv 2025 universal forecasting Ansari

Plus: 11 direct `web_fetch` retrievals of arXiv abstract/HTML pages, 6 arXiv API batch queries, 2 OpenAlex API queries, 2 Crossref API queries, and 1 raw-HTTP + iconv attempt on a Chinese-language source.
