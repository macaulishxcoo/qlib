#!/usr/bin/env python
"""qdata 因子本地复现 —— 第二批：**Liquidity（35）+ Risk（25）**。

公式来源：``output/qdata_factor_repro/factor_formulas.json``（逐条读，勿凭记忆）。
输入来源：``ts_env.load_panel``（个股 daily/daily_basic/adj_factor）
          + ``ts_index.load_index``（指数 index_daily，**本批新增**）。
比对引擎：``jqdata.facsim.compare``（EXACT/GOOD/APPROX/FAIL + verdict_med）。

════════════════════════════════════════════════════════════════════════
本批实测标定的口径（证据见报告 ``output/qdata_factor_repro/LIQUIDITY_RISK.md``）
════════════════════════════════════════════════════════════════════════
L1. ⚠⚠ **``ts_env`` 的 ``AMOUNT``/``V`` 已被乘上复权因子**（``ts_env.py`` 把
    ``open/high/low/close/vol/amount`` 统一 ``× adj_factor``）。
    因此 **原始成交额 = ``panel.AMOUNT / panel.ADJ``（单位千元）**，
    原始成交量 = ``panel.V / panel.ADJ``（单位手）。
    直接使用 ``panel.AMOUNT`` 会带来 ``adj_factor`` 倍（本样本 ~6.9×）的系统性偏差 ——
    这是 ``amount_ma_20d`` 从 rel 1.18 ✗ 变成 rel 2e-16 ✓ 的唯一原因。

L2. ✅ **``TurnoverAmount`` 的单位是「元」**（Tushare ``amount`` 千元 ×1000）。
    验证：``amount_ma_20d = MA(AMT_RAW_千元 × 1000, 20)`` → maxerr 9.5e-07（rel 3e-16）。
    ``sum_abs_rtn_amount_20d = Σ|ret,20| / Σ(amt_元,20) × 1e8`` → rel 1e-12。

L3. ✅ **``DailyTurnoverRate = Volume / AShares`` 中的 ``AShares`` = 流通股本**，
    且官方**直接取 Tushare ``daily_basic.turnover_rate`` 字段再 /100**（不是自算
    ``vol/float_share``）、返回**小数**（不是百分数）。该定义被 29 条换手率因子验证：

    | 换手率口径 | ``avg_turnover_5d`` | ``std_turnover_21d`` | ``bias_turn_21d_252d`` |
    |---|---|---|---|
    | **``turnover_rate``/100（本实现）** | **2.1e-16 EXACT** | **9.8e-09 EXACT** | **~1e-08 EXACT** |
    | 自算 ``vol(股)/float_share(股)`` | 1.08e-05 | 1.59e-05 | ~2e-05 |
    | ``turnover_rate_f``/100（自由流通） | 7.4e-01 ❌ | 6.2e-01 ❌ | ❌ |
    | ``vol/total_share`` | ❌ | ❌ | ❌ |
    | ×100（百分数量纲） | 81.6 ❌ | 65.4 ❌ | ❌ |
    | ``std`` 用 ddof=0 | — | 1.6e-02 ❌ | — |

    ⚠ 二者在数值上仅差 ~1e-5 相对（``turnover_rate`` 被供应商四舍五入到 4 位小数），
    **肉眼比对看不出来** —— 只有逐位比对才暴露。这是一条"看起来等价、其实不等价"的口径。

L4. ✅ ``turnover_ma_20d`` 的 ``VolCapRatio = Volume / FloatMarketCap``，
    其中 ``FloatMarketCap = ClosePrice × FloatShares``（**原始收盘价**，单位「元」），
    ``Volume`` 用原始成交量（股）。官方结果**取负**（``-MA(·, short)``）。
    注意该因子的量级 ~1e-6 —— 它**不是**换手率，而是「成交额换手」再除以价格。

L5. ✅ ``bias_turn_{s}d_{l}d`` / ``bias_std_turn_{s}d_{l}d`` 名字里的两个数字
    分别对应 ``params`` 中的短窗口 ``s*21`` 与长窗口 ``l*21``（如 ``21d_252d``
    → ``MA(turn, 1*21) / MA(turn, 12*21) − 1``），**不是**「绝对窗口 21 / 252」。

L6. ✅ ``high_low_{n}d`` = 窗口内 ``Max(NetValue)/Min(NetValue)``。
    因 ``NetValue_t = CumulativeProduct(1+DailyReturn)`` 而
    ``DailyReturn = 后复权 close`` 的日收益 ⇒ NetValue 与 ``Close_hfq`` 仅差一个
    常数因子，**Max/Min 完全等价于 ``Close_hfq`` 窗口极值比**。

L7. ✅ 滚动回归族（``beta_*`` / ``sigma_*`` / ``beta_consistency_*`` /
    ``volume_alpha_*`` / ``volume_beta_*``）：
    - 收益用**简单收益** ``pct_change()``（G4）；
    - 指数用 ``index_daily`` 的 **close，不复权**；``000001`` 后缀 = **上证指数
      ``000001.SH``，不是平安银行**；
    - ``beta = Cov/Var``，滚动窗口**含当日**（G3）；
    - ✅ **``sigma`` / ``beta_consistency`` 都是"日频残差序列"的再滚动，不是
      窗口内残差的 std** —— 这是本批最费时的一条标定（见 L7a）。

L7a. ⚠⚠ **残差类因子的"双层窗口"口径**（``sigma_1320d_*`` / ``beta_consistency_1320d_*``）

    公式 ``Sigma = StdDev(Residual) over 1320 days`` 里的 ``Residual`` 是
    **日频残差序列** ``Residual_t = r_t − α_t − β_t·R_t``（α/β 取自**以 t 结尾**的
    滚动 1320 日回归），``StdDev`` 是**对该序列再做一次 1320 日滚动标准差**。
    ⇒ 有效回看 = **2 × 1320 = 2640 个交易日**（约 10.5 年）。

    实测变体对照（verdict_med 口径，n=306）：

    | 实现 | ``sigma_1320d_000001`` | ``sigma_1320d_000300`` | ``beta_consistency_1320d_000300`` |
    |---|---|---|---|
    | **日频残差再滚动（本实现）** | **2.85e-07 GOOD** | **3.44e-07 GOOD** | **1.20e-06 GOOD** |
    | 窗口内残差 std（常见错解） | 2.11e-03 APPROX | 1.53e-03 APPROX | 1.33e-01 **FAIL** |
    | 日频残差再滚动 ddof=0 | 3.50e-04 APPROX | 3.44e-04 APPROX | 3.41e-04 APPROX |

    ``beta_consistency`` 同理 = ``StdDev(β_t × Residual_t)``（**逐日相乘后再滚动**），
    而不是 ``|β| × sigma``（后者偏离 13%，见上表"常见错解"行）。

    ⚠ 实现陷阱：``scripts/factorlib/ops.py::rolling_beta`` 返回的第三个值 ``resid``
    在 ``x`` 为 ``Series`` 时**是错的** —— 该行写作 ``y - (alpha + beta * x)``，
    缺少 ``.mul(x, axis=0)``，pandas 会把 ``x`` 按**列**（股票代码）对齐 ⇒ 全 NaN。
    本模块因此**自己算残差**（``ret - alpha - beta.mul(iret, axis=0)``），
    不复用该返回值。**该 bug 未修改 factorlib（不属于本批职责），仅在此记录。**

L8. ⚠ ``adjusted_sharpe_750d`` = ``Mean(ret,750)/Std(ret,750)**4``（四次方！），
    ``sharpe_{60,750}d`` = ``Mean/Std``（一次方）。

════════════════════════════════════════════════════════════════════════
⚠ qdata 尾部「未沉淀窗口」（G2，见 CONVENTIONS.md）
════════════════════════════════════════════════════════════════════════
官方因子在数据末端约 20~25 个交易日内结构性不可复现（供给侧噪声）。
判定必须用 ``--settle-days 30`` 截断（默认区间 2026-06-01~2026-09-10 → 截到 2026-08-11）。
尾部不匹配、截断后精确匹配 = 已知问题，**不是**实现错误。
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

_SCRIPTS = Path(__file__).resolve().parents[1]
for p in (str(_SCRIPTS), str(_SCRIPTS / "jqdata"), str(_SCRIPTS / "qdata")):
    if p not in sys.path:
        sys.path.insert(0, p)

from factorlib.ops import rolling_beta  # noqa: E402
from jqdata.facsim import ops as O  # noqa: E402
from jqdata.facsim.compare import compare_family, summarize  # noqa: E402
from qdata_env import QDataClient  # noqa: E402
from ts_env import TSPanel  # noqa: E402

FAMILY = "qdata_liquidity_risk"
SETTLE_DAYS_DEFAULT = 30

# ── 因子清单（从 factor_formulas.json 筛出：factor_type ∈ {Liquidity, Risk} 且
#    名字不含 _old_）────────────────────────────────────────────────────────
LIQUIDITY = [
    "amount_ma_20d",
    "avg_turnover_5d", "avg_turnover_10d", "avg_turnover_20d", "avg_turnover_21d",
    "avg_turnover_42d", "avg_turnover_63d", "avg_turnover_126d", "avg_turnover_252d",
    "std_turnover_21d", "std_turnover_42d", "std_turnover_63d",
    "std_turnover_126d", "std_turnover_252d",
    "bias_turn_21d_252d", "bias_turn_21d_504d", "bias_turn_42d_252d", "bias_turn_42d_504d",
    "bias_turn_63d_252d", "bias_turn_63d_504d", "bias_turn_126d_252d", "bias_turn_126d_504d",
    "bias_std_turn_21d_252d", "bias_std_turn_21d_504d",
    "bias_std_turn_42d_252d", "bias_std_turn_42d_504d",
    "bias_std_turn_63d_252d", "bias_std_turn_63d_504d",
    "bias_std_turn_126d_252d", "bias_std_turn_126d_504d",
    "turnover_ma_20d", "turnover_ma_20d_120d",
    "sum_abs_rtn_amount_20d",
    "volume_alpha_300d_000001", "volume_alpha_300d_000300",
]
RISK = [
    "adjusted_sharpe_750d",
    "beta_60d_000300", "beta_125d_000300", "beta_250d_000300",
    "beta_500d_000300", "beta_1000d_000300", "beta_1320d_000001",
    "beta_consistency_1320d_000300",
    "days_beyond_upper_lower_21d",
    "high_low_21d", "high_low_42d", "high_low_63d", "high_low_126d", "high_low_252d",
    "log_price",
    "return_std_21d", "return_std_42d", "return_std_63d",
    "return_std_126d", "return_std_252d",
    "sharpe_60d", "sharpe_750d",
    "sigma_1320d_000001", "sigma_1320d_000300",
    "volume_beta_120d_000300",
]
ALL_FACTORS = LIQUIDITY + RISK

#: 需要指数行情的因子 → 指数后缀
NEEDS_INDEX = {
    **{f"beta_{n}d_{k}": k for n, k in
       [(60, "000300"), (125, "000300"), (250, "000300"),
        (500, "000300"), (1000, "000300"), (1320, "000001")]},
    "beta_consistency_1320d_000300": "000300",
    "sigma_1320d_000001": "000001",
    "sigma_1320d_000300": "000300",
    "volume_alpha_300d_000001": "000001",
    "volume_alpha_300d_000300": "000300",
    "volume_beta_120d_000300": "000300",
}

# ── 默认口径 ────────────────────────────────────────────────────────────────
DEFAULT_CFG: dict[str, object] = {
    # ✅ 官方直接取 Tushare daily_basic.turnover_rate（四舍五入后的字段）再 /100；
    #    自算 vol/float_share 差 ~1e-5 相对、肉眼不可辨，只有逐位比对才暴露（L3）。
    "turnover_src": "turnover_rate",  # turnover_rate / vol_float / vol_free / vol_total
    "turnover_scale": 1.0,           # 1.0 = 小数（官方口径，L3）；100.0 = 百分数
    "ddof": 1,                       # 样本标准差（G5）
    "ret_kind": "simple",            # simple / log（G4）
    "hl_price": "hfq",               # high_low 用 C（后复权）还是 C_RAW
    "volcap_price": "raw",           # turnover_ma_* 的 FloatMarketCap 用原始收盘价
    "amount_mode": "raw_yuan",       # raw_yuan（官方，L2）/ raw_qian / adj_qian
    "volmom_vol": "raw",             # volume_alpha/beta 的成交量：raw / adj
    "sigma_mode": "std_ddof1",       # 已由 L7a 固定；保留仅供变体对照
    "db_mode": "double_rolling",     # days_beyond: double_rolling / z_only
    "db_thresh": 1.0,
}

RISK_OVERLAP_BATCH1 = ["log_price", "return_std_21d", "return_std_42d",
                       "return_std_63d", "sharpe_60d"]


# ════════════════════════════════════════════════════════════════════════════
# 算子
# ════════════════════════════════════════════════════════════════════════════
def rolling_ols(y: pd.DataFrame, x: pd.Series, w: int,
                sigma_mode: str = "std_ddof1"):
    """滚动 OLS ``y ~ a + b·x``（窗口 ``w``，含当日）。

    返回 ``(beta, resid_std)``；均为 ``index=date, columns=code`` 的宽表。

    ``resid_std`` 是**窗口内**残差向量的标准差（不是「日频残差序列再滚动」——
    后者才是 qdata 的官方口径，见 :func:`rolling_reg_series` 与模块 docstring L7a）。
    仅用于变体对照，**不用于最终实现**。三种自由度口径：
        ``ols_se``    → ``sqrt(SSR/(w-2))``（回归标准误）
        ``std_ddof1`` → ``sqrt(SSR/(w-1))``（残差向量的样本标准差）
        ``std_ddof0`` → ``sqrt(SSR/w)``（残差向量的总体标准差）
    """
    from numpy.lib.stride_tricks import sliding_window_view

    xv = x.reindex(y.index).to_numpy(dtype="float64")
    T = len(y)
    beta = pd.DataFrame(np.nan, index=y.index, columns=y.columns)
    rstd = pd.DataFrame(np.nan, index=y.index, columns=y.columns)
    if T < w:
        return beta, rstd
    X = sliding_window_view(xv, w)                       # (T-w+1, w)
    Xc = X - X.mean(axis=1, keepdims=True)
    Sxx = (Xc * Xc).sum(axis=1)
    dof = {"ols_se": w - 2, "std_ddof1": w - 1, "std_ddof0": w}[sigma_mode]
    for c in y.columns:
        yv = y[c].to_numpy(dtype="float64")
        Y = sliding_window_view(yv, w)
        Yc = Y - Y.mean(axis=1, keepdims=True)
        Sxy = (Xc * Yc).sum(axis=1)
        Syy = (Yc * Yc).sum(axis=1)
        b = Sxy / Sxx
        ssr = np.clip(Syy - b * Sxy, 0, None)
        beta.iloc[w - 1:, beta.columns.get_loc(c)] = b
        rstd.iloc[w - 1:, rstd.columns.get_loc(c)] = np.sqrt(ssr / dof)
    return beta, rstd


def rolling_reg_series(y: pd.DataFrame, x: pd.Series, w: int):
    """滚动 OLS ``y ~ a + b·x``，返回 ``(beta_t, Residual_t)`` —— **日频序列**。

    ``Residual_t = y_t − a_t − b_t·x_t``，其中 ``a_t / b_t`` 来自**以 t 结尾**的
    滚动 ``w`` 日窗口。这是 qdata ``sigma_*`` / ``beta_consistency_*`` 的真实输入
    （模块 docstring L7a）。

    ⚠ 不复用 ``factorlib.ops.rolling_beta`` 的 ``resid`` —— 该返回值在 ``x`` 为
    ``Series`` 时缺少 ``axis=0``，会得到全 NaN（见 L7a 陷阱说明）。
    """
    b, a, _ = rolling_beta(y, x, w)
    resid = y - a - b.mul(x, axis=0)
    return b, resid


def _volcap_ratio(panel: TSPanel, price: str) -> pd.DataFrame:
    """``VolCapRatio = Volume(股) / (ClosePrice × FloatShares)(元)``。"""
    px = panel.C_RAW if price == "raw" else panel.C
    fmc = px * (panel.FLOAT_SHARE * 1e4)             # 万股 → 股
    v_sh = (panel.V / panel.ADJ) * 100               # 手 → 股
    return v_sh / fmc.replace(0, np.nan)


def _turnover(panel: TSPanel, cfg: dict) -> pd.DataFrame:
    """``DailyTurnoverRate = TurnoverVolume / AShares``（小数）。见 L3。"""
    src = cfg["turnover_src"]
    if src == "turnover_rate":
        t = panel.TURNOVER_RATE / 100.0
    else:
        sh = {"vol_float": panel.FLOAT_SHARE,
              "vol_free": panel.FREE_SHARE,
              "vol_total": panel.TOTAL_SHARE}[src]
        t = (panel.V / panel.ADJ) * 100 / (sh * 1e4)   # 手→股, 万股→股
    return t * float(cfg["turnover_scale"])


def _amount_yuan(panel: TSPanel, cfg: dict) -> pd.DataFrame:
    """成交额（元）。L1+L2。"""
    m = cfg["amount_mode"]
    if m == "raw_yuan":
        return (panel.AMOUNT / panel.ADJ) * 1000.0
    if m == "raw_qian":
        return panel.AMOUNT / panel.ADJ
    return panel.AMOUNT                              # adj_qian（错误口径，仅供对照）


def _volmom(panel: TSPanel, cfg: dict, w_sum: int = 5) -> pd.DataFrame:
    """成交量动量 = ``RollingSum(Volume, w_sum)`` 的一阶变化率（日频序列）。

    ``(RollingSum(V,5) − Lag(RollingSum(V,5),1)) / Lag(·,1)`` = ``pct_change()``。
    比值型 ⇒ 成交量的**单位无关**；但用「复权后」还是「原始」成交量在除权日会不同。
    """
    v = panel.V / panel.ADJ if cfg.get("volmom_vol", "raw") == "raw" else panel.V
    return v.rolling(w_sum).sum().pct_change()


cfg_global: dict = dict(DEFAULT_CFG)


def build(panel: TSPanel, idx: dict[str, pd.DataFrame],
          cfg: dict | None = None) -> dict[str, pd.DataFrame]:
    """按 factor_list 公式实现 Liquidity / Risk 两族。"""
    global cfg_global
    c = dict(DEFAULT_CFG)
    if cfg:
        c.update(cfg)
    cfg_global = c

    C, C_RAW = panel.C, panel.C_RAW
    # 停牌日 ``close`` 缺失 ⇒ 日收益按 0 处理（官方口径未知，但在比对窗口内无差异，
    # 且能让 2640 日双层窗口良定义）。见模块 docstring L7a。
    ret = np.log(C).diff() if c["ret_kind"] == "log" else C.pct_change()
    ret = ret.fillna(0.0)
    turn = _turnover(panel, c)
    amt = _amount_yuan(panel, c)
    ddof = int(c["ddof"])
    out: dict[str, pd.DataFrame] = {}

    # ══════════════════ Liquidity ══════════════════════════════════════════
    # 1) 成交额均线
    out["amount_ma_20d"] = amt.rolling(20).mean()

    # 2) 平均换手率 / 换手率标准差
    for n in (5, 10, 20, 21, 42, 63, 126, 252):
        out[f"avg_turnover_{n}d"] = turn.rolling(n).mean()
    for n in (21, 42, 63, 126, 252):
        out[f"std_turnover_{n}d"] = turn.rolling(n).std(ddof=ddof)

    # 3) 换手率乖离（短/长 − 1）—— 名字里的数字 = 月数 × 21（L5）
    for s in (21, 42, 63, 126):
        for l in (252, 504):
            out[f"bias_turn_{s}d_{l}d"] = (
                turn.rolling(s).mean() / turn.rolling(l).mean() - 1.0)
            out[f"bias_std_turn_{s}d_{l}d"] = (
                turn.rolling(s).std(ddof=ddof) / turn.rolling(l).std(ddof=ddof) - 1.0)

    # 4) 量额比均线（取负）
    vcr = _volcap_ratio(panel, c["volcap_price"])
    out["turnover_ma_20d"] = -vcr.rolling(20).mean()
    out["turnover_ma_20d_120d"] = -vcr.rolling(20).mean() / vcr.rolling(120).mean()

    # 5) 单位成交额波动
    out["sum_abs_rtn_amount_20d"] = (
        ret.abs().rolling(20).sum() / amt.rolling(20).sum() * 1e8)

    # 6) 成交量 Alpha（对指数成交量动量的滚动回归截距 alpha = ȳ − β·x̄）
    smom = _volmom(panel, c)
    for k in ("000001", "000300"):
        if k not in idx:
            continue
        imom = idx[k]["V"].rolling(5).sum().pct_change()
        out[f"volume_alpha_300d_{k}"] = rolling_beta(smom, imom, 300)[1]

    # ══════════════════ Risk ══════════════════════════════════════════════
    out["adjusted_sharpe_750d"] = (
        ret.rolling(750).mean() / ret.rolling(750).std(ddof=ddof) ** 4)
    out["sharpe_60d"] = ret.rolling(60).mean() / ret.rolling(60).std(ddof=ddof)
    out["sharpe_750d"] = ret.rolling(750).mean() / ret.rolling(750).std(ddof=ddof)

    for n in (21, 42, 63, 126, 252):
        out[f"return_std_{n}d"] = ret.rolling(n).std(ddof=ddof)
    out["log_price"] = np.log(C)

    # 净值曲线极值比（L6）
    hlp = C if c["hl_price"] == "hfq" else C_RAW
    for n in (21, 42, 63, 126, 252):
        out[f"high_low_{n}d"] = hlp.rolling(n).max() / hlp.rolling(n).min()

    # Z 超越天数
    z = (C - C.rolling(21).mean()) / C.rolling(21).std(ddof=ddof)
    if c["db_mode"] == "double_rolling":
        up = (z > c["db_thresh"]).astype(float).rolling(21).sum()
        lo = (z < -c["db_thresh"]).astype(float).rolling(21).sum()
        out["days_beyond_upper_lower_21d"] = up - lo
    else:  # z_only：直接用当日的 Z 与阈值比较
        out["days_beyond_upper_lower_21d"] = (
            (z > c["db_thresh"]).astype(float) - (z < -c["db_thresh"]).astype(float))

    # 滚动 Beta / Sigma / BetaConsistency
    beta_specs = [(60, "000300"), (125, "000300"), (250, "000300"),
                  (500, "000300"), (1000, "000300"), (1320, "000001")]
    for n, k in beta_specs:
        if k not in idx:
            continue
        iret = idx[k]["C"].pct_change()
        b = rolling_beta(ret, iret, n)[0]
        out[f"beta_{n}d_{k}"] = b
    # sigma / beta_consistency：日频残差序列的**再滚动**（L7a，需 2×1320 日回看）
    for k in ("000001", "000300"):
        if k not in idx:
            continue
        iret = idx[k]["C"].pct_change()
        b, resid = rolling_reg_series(ret, iret, 1320)
        out[f"sigma_1320d_{k}"] = resid.rolling(1320).std(ddof=ddof)
        if k == "000300":
            out["beta_consistency_1320d_000300"] = (
                (b * resid).rolling(1320).std(ddof=ddof))

    # 成交量 Beta
    if "000300" in idx:
        imom = idx["000300"]["V"].rolling(5).sum().pct_change()
        out["volume_beta_120d_000300"] = rolling_beta(_volmom(panel, c), imom, 120)[0]

    return {k: v for k, v in out.items() if k in ALL_FACTORS}


# ════════════════════════════════════════════════════════════════════════════
# 官方数据
# ════════════════════════════════════════════════════════════════════════════
def official_panel(codes: list[str], factors: list[str], start: str, end: str,
                   use_cache: bool = True) -> dict[str, pd.DataFrame]:
    """取 qdata ``factor_value`` 官方值 → ``dict[factor -> DataFrame(date × code)]``。

    ⚠ 不用 offset 分页（G7：分页返回重复行）；按 ``(factor, ts_code)`` 单取，
    每次 ≤ 交易日数行，远低于 6000 行上限。
    """
    import pickle
    cache = Path("output/qdata_factor_repro/cache")
    cache.mkdir(parents=True, exist_ok=True)
    s_c, e_c = start.replace("-", ""), end.replace("-", "")
    cname = cache / f"official_liqrisk_{s_c}_{e_c}.pkl"
    if use_cache and cname.is_file():
        print("  [qdata] 官方因子缓存命中")
        got = pickle.load(open(cname, "rb"))
        if all(f in got for f in factors):
            return got
    cli = QDataClient(qps=6)
    rec: dict[str, dict[str, pd.Series]] = {f: {} for f in factors}
    n = 0
    for cd in codes:
        for f in factors:
            for att in range(5):
                try:
                    rows = cli.factor_value(factor_name=f, ts_code=cd,
                                            start_date=s_c, end_date=e_c)
                    break
                except Exception as exc:                    # noqa: BLE001
                    print(f"    !! 重试 {f}/{cd}: {exc}")
                    import time
                    time.sleep(3 * (att + 1))
            else:
                rows = []
            n += 1
            if not rows:
                continue
            d = pd.DataFrame(rows).drop_duplicates(subset=["trade_date"])
            d["trade_date"] = pd.to_datetime(d["trade_date"])
            rec[f][cd] = d.set_index("trade_date")["factor_value"].astype(float)
        print(f"    …官方 {cd} 完成（累计 {n} 次调用）")
    out = {f: pd.DataFrame(v).sort_index() for f, v in rec.items() if v}
    if use_cache:
        pickle.dump(out, open(cname, "wb"))
    print(f"  [qdata] 官方因子已取回并缓存（{len(out)} 个）")
    return out


# ════════════════════════════════════════════════════════════════════════════
# 主流程
# ════════════════════════════════════════════════════════════════════════════
COLS = ["factor", "verdict_med", "verdict", "n_overlap", "coverage",
        "max_abs_err", "med_rel_err", "corr"]


def _show(title: str, local: dict, off: dict, tag: str, families: dict) -> pd.DataFrame:
    print(f"\n===== {title} =====")
    exp = [f for f in ALL_FACTORS]
    d = compare_family(FAMILY, local, off, exp)
    d["family"] = d["factor"].map(lambda x: families.get(x, "?"))
    with pd.option_context("display.width", 220, "display.max_rows", 200):
        print(d[COLS].to_string(index=False, float_format=lambda x: f"{x:.4g}"))
    print("\n" + summarize(d))
    for fam in ("Liquidity", "Risk"):
        sub = d[d["family"] == fam]
        print(f"  [{fam}] {summarize(sub)}")
    out = Path("output/qdata_factor_repro") / f"liquidity_risk_compare{tag}.csv"
    d.to_csv(out, index=False)
    print(f"报告: {out}")
    return d


def main() -> int:
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--codes", nargs="*", default=[
        "600519.SH", "000001.SZ", "000002.SZ", "600036.SH", "002415.SZ", "000651.SZ"])
    ap.add_argument("--start", default="2026-06-01")
    ap.add_argument("--end", default="2026-09-10")
    ap.add_argument("--lookback", default="2013-01-01",
                    help="面板起点。⚠ sigma_1320d_* / beta_consistency_1320d_* 需要 "
                         "2×1320=2640 个交易日回看（约 10.5 年），必须早于 2014-01-01")
    ap.add_argument("--settle-days", type=int, default=SETTLE_DAYS_DEFAULT)
    ap.add_argument("--variant", nargs="*", default=[],
                    help="口径覆盖，形如 turnover_scale=100 ddof=0")
    ap.add_argument("--fetch-only", action="store_true")
    args = ap.parse_args()

    from ts_env import load_panel
    from ts_index import load_indices

    cfg = dict(DEFAULT_CFG)
    for kv in args.variant:
        k, v = kv.split("=", 1)
        try:
            v = int(v)
        except ValueError:
            try:
                v = float(v)
            except ValueError:
                pass
        cfg[k] = v
    print("口径:", {k: cfg[k] for k in ("turnover_src", "turnover_scale", "ddof",
                                        "ret_kind", "amount_mode", "sigma_mode",
                                        "db_mode", "hl_price")})

    off = official_panel(args.codes, ALL_FACTORS, args.start, args.end)
    if args.fetch_only:
        return 0

    panel = load_panel(args.codes, args.lookback, args.end)
    idxt = load_indices(sorted(set(NEEDS_INDEX.values())), args.lookback, args.end)
    print(f"  指数: " + ", ".join(f"{k}({len(v)}日)" for k, v in idxt.items()))
    local = build(panel, idxt, cfg)
    print(f"  本地实现 {len(local)}/{len(ALL_FACTORS)} 个")
    missing = [f for f in ALL_FACTORS if f not in local]
    if missing:
        print(f"  ⚠ 未实现: {missing}")

    fam_map = {f: "Liquidity" for f in LIQUIDITY}
    fam_map.update({f: "Risk" for f in RISK})

    _show("全窗口（含 qdata 未沉淀尾部）", local, off, "", fam_map)
    if args.settle_days > 0:
        cut = pd.Timestamp(args.end) - pd.Timedelta(days=args.settle_days)
        print(f"\n[settle] 排除 {cut.date()} 之后的 {args.settle_days} 个自然日")
        loc_s = {k: v.loc[:cut] for k, v in local.items()}
        off_s = {k: v.loc[:cut] for k, v in off.items()}
        _show(f"已沉淀窗口（--settle-days {args.settle_days}，判定口径）",
              loc_s, off_s, "_settled", fam_map)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
