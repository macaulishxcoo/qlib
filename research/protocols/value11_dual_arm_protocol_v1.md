# Value 11 因子假设检验协议 v1（干净微盘域 + 全市场对照，九族收官）

## 1. 状态与授权

状态：`frozen_awaiting_run`（2026-09-10）

前置链与先验（本族是最后一族，先验最重）：
- **主线同源**：五因子主线的 ep（=earnings_to_price 完全同义）与 bm
  （≈book_to_market，分母用 total_mv、分子 bps×share，本质同义）就在
  本族里。主线验证已确认 ep/bm 在域内的价值——**通过市值中性化 +
  composite ≥4/5 门槛后进入选股**，即"价值暴露已被 enhance/等权的
  结构性配置吸收"；
- 本族的增量问题只有一个：**ep/bm 之外的 9 个价值口径**（现金流系
  fcf/ocf/ncf_to_market、ebitda_to_market、sales_to_market、
  earnings_cut_to_market、etp5、dividend_yield_3y_avg、pegh5）在域内
  是否有主线之外的信息；
- Quality 轮教训直接适用：**水平类因子在微盘域集体失效**（价值因子
  全部是水平类）——但价值水平与质量水平不同轴（价值=价格调整后的
  便宜，主线 ep/bm 已证明其域内有效性），所以先验是"分化"：
  与 ep/bm 同构的（earnings_to_price/earnings_cut/book_to_market）
  预期 IC 正且与主线高相关（duplicate 确认）；现金流系是真正未测的。

## 2. 因子集与复现（冻结，11 个）

| 因子 | 公式要点 | 本项目原料 |
|---|---|---|
| earnings_to_price | 归母净利 TTM/市值 | n_income_attr_p TTM + total_share×close（=主线 ep 同义） |
| book_to_market | (归母权益+递延税资产)/市值 | balancesheet total_hldr_eqy_exc_min_int + defer_tax_assets |
| earnings_cut_to_market | 扣非净利 TTM/市值 | profit_dedt TTM（fina_indicator） |
| ocf_to_market | 经营现金流 TTM/市值 | n_cashflow_act TTM |
| fcf_to_market | (经营现金流−投资流出)TTM/市值 | cashflow 需投资流出列——核查后缺失则用 n_cashflow_act 代理并标注 |
| ncf_to_market | 三项净现金流和/市值 | 同上，缺筹资/投资明细则退化为 ocf_to_market（标注） |
| ebitda_to_market | EBITDA TTM/市值 | fina_indicator ebitda |
| sales_to_market | 营收（Q）/市值 | income total_revenue |
| etp5 | 5年平均净利/5年平均市值 | n_income_attr_p 年度 5 年滚动 + 市值 5 年滚动 |
| dividend_yield_3y_avg | 3年平均红利/现价 | **分红数据本项目无**——用 fina_indicator dv_ttm 的 3 年均值近似（dv_ratio/dv_ttm 已有）并标注 |
| pegh5 | -rank(PE/(5年EPS增速×100)) | eps 5 年复合（历史深度不足风险，同 growth 轮 peg 教训——异常率报告） |

数据可得性预检：cashflow 表仅 n_cashflow_act（无筹资/投资明细）→
fcf/ncf 两因子按代理口径实现并标注；分红无原始数据 → dividend 用
dv_ttm 滚动均值代理。

## 3. 双臂与判定（冻结，与前八族同框架）

臂B=干净微盘域、臂A=全市场，月度持有费前，2022-01~2026-08。
门槛同前（|IC|≥0.02 + 价差|t|≥2 + 分年≥4/5）。

**主线冗余判定（本族特有，预注册）**：
- earnings_to_price 与主线 ep 直接同义——它的域内结果作为"主线在
  双臂框架下的对照锚"，不计入新候选；
- book_to_market 与主线 bm 同义，同上；
- 其余 9 个与 ep/bm 相关 ≥0.60 → `mainline_duplicate`；<0.60 且过
  门槛 → `value_increment_candidate`（可进 enhance 池）；
- pegh5 若异常率 >30%（微盘 EPS 增速分母问题，growth 轮教训）→
  单独降级标注。

出口：`value_increment_candidate` = 0 → `value_axis_mainline_covered`
（价值轴被主线 ep/bm 完整覆盖，九族扫描全部闭合）；有增量候选 →
enhance 池第 8 源候选。

## 4. 产物

`output/analysis_static/value11_dual_arm_v1/`：全套（同前各族）。

## 5. 风险预告（预注册的怀疑）

1. 现金流系（fcf/ocf/ncf_to_market）是最有希望的增量：现金流比盈利
   难操纵（与 delta_gpm 的"难操纵才可信"结论同向），且与 ep 的分母
   同分子不同——但 accruals 主线因子本身已含"现金流−利润"信息，
   可能与 accruals 相关 0.4~0.6；
2. sales_to_market 在微盘域可能被低毛利贸易类公司污染（收入大市值小），
   极端值预注册 ±3 MAD 截尾；
3. dividend_yield_3y 代理口径（dv_ttm 均值）与原文（实派红利均值）
   有偏差，结论降级标注；
4. etp5/pegh5 的 5 年窗口在 2022 起点样本不足 ~1.5 年，降级。
