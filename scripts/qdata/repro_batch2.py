#!/usr/bin/env python
"""qdata 因子本地复现 —— 第二批（Momentum / Reversal / Size / Value 四族）。

公式来源：``output/qdata_factor_repro/factor_formulas.json``（从 ``factor_list`` 抽取）。
输入来源：``ts_env.load_panel``（Tushare 官方 daily/daily_basic/adj_factor）
         + ``ts_env.pro().index_daily``（alpha_* 族所需的指数收益）。
判定引擎：``scripts/jqdata/facsim/compare.py``（三口径判定，主判据 ``verdict_med``）。

沿用批次一（``repro.py``）已标定的口径（见 ``output/qdata_factor_repro/CONVENTIONS.md``）：
- G1 ``Close`` = **后复权价** ``C = C_RAW × ADJ``；
- G2 qdata 尾部 ~20~25 个交易日「未沉淀窗口」→ 用 ``--settle-days 30`` 截断判定；
- G3 滚动窗口**含当日**；
- G4 ``DailyReturn`` = **简单收益**（``pct_change``），非对数收益；
- G5 ``StdDev`` = **样本标准差**（``ddof=1``）；
- G6 比较区间取 qdata 与 Tushare ``daily`` 的交集（2026-06-01 ~ 2026-09-10）；
- G7 取数纪律：按 ``(factor_name, ts_code)`` 单取、禁用 offset 分页、日期 ``YYYYMMDD``。

════════════════════════════════════════════════════════════════════════
本批新增的实测标定结论（详见 ``batch2_variants.csv``）
════════════════════════════════════════════════════════════════════════
G8  ``days_down_up`` = ``|ConsecutiveUp - ConsecutiveDown - 1|``：
    连续计数基于 ``Close.diff()`` 的**严格正/负**符号，当前笔连续长度，另一侧清零。
    （vs ``>0 / >=0``、简单收益符号等变体，见 variants 表）
G9  ``rsrs`` 用**后复权** High/Low 计算 18 日 OLS 斜率，
    z-score 的 ``StdDev`` 为**样本标准差 ddof=1**（ddof=0 判 APPROX，raw 价判 FAIL）。
G10 ``price_dist`` 的「价格」是**后复权价** ``C``（不是原始价）——与直觉相反，实测标定。
    ``dist = ceil(scale(price)) - scale(price)``，``price<10`` 不缩放、``<100`` 除以 10、
    否则除以 100；``window=0`` 时不做移动平均。
G11 ``price_position_ir_60d`` = ``Mean(Ratio,60)/StdDev(Ratio,60)``，Ratio 在复权/不复权下
    **恒等**（比值对共同尺度不变），``StdDev`` 用 ddof=1。
G12 ``rsi`` 的 Wilder 平滑 = ``ewm(com=period-1, adjust=False)``（α=1/period），
    不是 ``span=period``（α=2/(period+1)）；价格用后复权 ``C``。
G13 ``size`` / ``float_size`` = ``-log(总市值 / 1e6)``，其中 Tushare ``total_mv`` 单位为
    **万元** ⇒ ``-log(total_mv / 100)``（即市值以**百万元**计）。符号为**负对数**。
G14 ``earnings_to_price`` = ``1 / pe_ttm``；``book_to_market`` = ``1 / pb``（纯 daily_basic）。
G15 ``alpha_{N}d_*`` = 个股**简单**日收益对指数**简单**日收益的滚动 OLS **截距**，
    窗口 N 含当日；个股用后复权收益。
G16 ⚠ 接口行为：``factor_value`` 在**服务端压力/限流**时会返回 ``code=0`` 但 **items 为空**
    （不是报错也不是 429）。必须把「空结果」也当作**可重试**状态，否则会静默丢数据。
G17 ``CrossSectionalRank(x) = rank(x) / N``（升序平均秩，N=当日非空股票数）；
    ``small_cap_reversal_21d`` 的 ``CumReturn`` 用**后复权**价，外层判据必须用
    ``xs_compare.compare_xs`` 的**全市场逐日 Spearman**，而不是 6 只股票的绝对误差。
    ``nl_size`` 是**全市场**截面 ``Residual(Size³ ~ Size)``，同样只能全市场判定。
"""
from __future__ import annotations

import sys
import time
from collections import deque
from pathlib import Path

import numpy as np
import pandas as pd

_SCRIPTS = Path(__file__).resolve().parents[1]
for p in (str(_SCRIPTS), str(_SCRIPTS / "jqdata"), str(_SCRIPTS / "qdata")):
    if p not in sys.path:
        sys.path.insert(0, p)

from jqdata.facsim import ops as O  # noqa: E402
from jqdata.facsim.compare import compare_family, summarize  # noqa: E402
from qdata_env import QDataClient  # noqa: E402
from ts_env import TSPanel  # noqa: E402

FAMILY = "qdata_batch2"
OUT_DIR = Path("output/qdata_factor_repro")
CACHE_DIR = OUT_DIR / "cache"

#: qdata 尾部未沉淀窗口（自然日）——见 CONVENTIONS.md G2。
SETTLE_DAYS_DEFAULT = 30

# ---------------------------------------------------------------------------
# 因子清单（来自 factor_formulas.json，已剔除名字含 ``_old_`` 的历史快照）
# ---------------------------------------------------------------------------
#: Momentum 20 个（全部纯时序）
MOMENTUM = [
    "dif", "dea", "MACD", "ma_20d",
    "return_5d", "return_21d", "return_42d", "return_63d", "return_126d", "return_252d",
    "days_down_up", "rsrs", "price_position_ir_60d",
    "alpha_125d_000300", "alpha_250d_000300", "alpha_500d_000300",
    "alpha_792d_000001", "alpha_1000d_000300", "alpha_1320d_000001", "alpha_528d_000001",
]
#: Reversal 剔除 2 个 ``_old_`` 后剩 3 个：rsi / price_dist 纯时序，small_cap 含截面
REVERSAL = ["rsi", "price_dist"]
#: Size 3 个：size / float_size 逐股时序；nl_size 含截面回归
SIZE = ["size", "float_size"]
#: Value 11 个：仅 earnings_to_price / book_to_market 为逐股 daily_basic 比值
VALUE = ["earnings_to_price", "book_to_market"]

#: 本批实际本地实现并比对的因子
IMPLEMENTED = MOMENTUM + REVERSAL + SIZE + VALUE

#: alpha_* 因子的（窗口, 指数代码）
ALPHA_SPEC = {
    "alpha_125d_000300": (125, "000300.SH"),
    "alpha_250d_000300": (250, "000300.SH"),
    "alpha_500d_000300": (500, "000300.SH"),
    "alpha_1000d_000300": (1000, "000300.SH"),
    "alpha_792d_000001": (792, "000001.SH"),
    "alpha_1320d_000001": (1320, "000001.SH"),
    "alpha_528d_000001": (528, "000001.SH"),
}

#: 跳过实现/比对的因子及原因（写入 batch2_skipped.csv）。
#: 注：``nl_size`` / ``small_cap_reversal_21d`` 见 ``FM_FACTORS``——
#: 它们在 ``--full-market`` 模式下会用全市场横截面验证，不再列在这里。
SKIPPED = {
    # --- Value ---
    "fcf_to_market":
        "公式 = (NOCF_TTM − SICO_TTM)/(ClosePrice×TotalShares)，需要现金流量表 TTM；"
        "本地仅有 fina_indicator（无现金流量表/利润表原始科目），本批未做。",
    "ncf_to_market":
        "含 CrossSectionalRank + 需要现金流量表 TTM（筹资+投资+经营净现金流）。",
    "ocf_to_market":
        "含 CrossSectionalRank + 需要现金流量表 TTM（经营现金流净额）。",
    "ebitda_to_market":
        "含 CrossSectionalRank + 需要利润表 EBITDA。",
    "earnings_cut_to_market":
        "含 CrossSectionalRank + 需要扣非净利润 TTM。"
        "（副产品：已实测其**内层** = profit_dedt_TTM/(ClosePrice×TotalShares)，见报告）",
    "sales_to_market":
        "含 CrossSectionalRank + 公式用单季营业总收入 Q（非 PS_TTM 的 TTM 口径）。",
    "pegh5":
        "含 CrossSectionalRank + 需要 5 年 EPS 与 EPS_TTM（财务）。",
    "etp5":
        "含 CrossSectionalRank + 需要 5 年净利润与市值滚动均值（财务）。",
    "dividend_yield_3y_avg":
        "含 CrossSectionalRank + 需要 3 年每股实派分红（分红表）。",
}


# ===========================================================================
# 局部算子（**不改 ops.py**，避免与并行任务冲突）
# ===========================================================================
def _masked_rolling_ols(y: pd.DataFrame, x, n: int,
                        kind: str = "intercept") -> pd.DataFrame:
    """滚动 OLS ``y ~ x``：返回 ``intercept`` 或 ``slope``（向量化，含当日，窗口 n）。

    ``x`` 可以是 DataFrame（同形）或 Series（按 index 对齐后广播到 ``y`` 的每一列），
    避免了 ``DataFrame * DataFrame`` 在列名不同时对齐成 NaN 的陷阱。

    最小二乘闭式解（避免逐窗口 ``np.polyfit`` 的开销）::

        beta  = (Σxy − Σx·Σy/n) / (Σx² − (Σx)²/n)
        alpha = ȳ − beta·x̄
    """
    if isinstance(x, pd.Series):
        x = pd.DataFrame({c: x for c in y.columns}, index=y.index)
    elif x.shape[1] != y.shape[1] or set(x.columns) != set(y.columns):
        x = pd.DataFrame({c: x.iloc[:, 0] for c in y.columns}, index=x.index)
    x = x.reindex(index=y.index, columns=y.columns)
    Sx = x.rolling(n).sum()
    Sy = y.rolling(n).sum()
    Sxy = (x * y).rolling(n).sum()
    Sxx = (x * x).rolling(n).sum()
    den = Sxx - Sx * Sx / n
    beta = (Sxy - Sx * Sy / n) / den
    if kind == "slope":
        return beta
    return Sy / n - beta * (Sx / n)


def consec_true(mask: pd.DataFrame) -> pd.DataFrame:
    """截止当日的**连续 True** 长度（逐列独立；False 处清零）。"""
    m = mask.values
    out = np.zeros(m.shape, dtype=float)
    cnt = np.zeros(m.shape[1], dtype=float)
    for i in range(m.shape[0]):
        cnt = np.where(m[i], cnt + 1.0, 0.0)
        out[i] = cnt
    return pd.DataFrame(out, index=mask.index, columns=mask.columns)


def days_down_up(close: pd.DataFrame, strict: bool = True) -> pd.DataFrame:
    """``|ConsecutiveUp − ConsecutiveDown − 1|``（G8）。

    ``strict=True`` 用 ``diff() > 0 / < 0``；``False`` 用 ``>= 0 / <= 0``。
    """
    d = close.diff()
    if strict:
        up, dn = d > 0, d < 0
    else:
        up, dn = d >= 0, d <= 0
    return (consec_true(up) - consec_true(dn) - 1).abs()


def rsi(close: pd.DataFrame, period: int = 14, mode: str = "wilder") -> pd.DataFrame:
    """RSI（G12）。``mode``：``wilder``=α=1/period；``span``=α=2/(period+1)。"""
    d = close.diff()
    gain = d.clip(lower=0)
    loss = (-d).clip(lower=0)
    if mode == "wilder":
        ag = gain.ewm(com=period - 1, adjust=False).mean()
        al = loss.ewm(com=period - 1, adjust=False).mean()
    elif mode == "span":
        ag = gain.ewm(span=period, adjust=False).mean()
        al = loss.ewm(span=period, adjust=False).mean()
    elif mode == "sma_mean":                       # 官方文档另一种常见写法
        ag = gain.rolling(period).mean()
        al = loss.rolling(period).mean()
    else:
        raise ValueError(mode)
    rs = ag / al                                    # x/0 → inf；0/0 → NaN
    return 100 - 100 / (1 + rs)


def price_dist(price: pd.DataFrame, mode: str = "ceil") -> pd.DataFrame:
    """股价到「下一个整数关口」的距离（G10）。

    ``price<10`` 不缩放；``10<=price<100`` 除以 10；``price>=100`` 除以 100。
    ``mode='ceil'`` → ``ceil(y)-y``；``mode='nearest'`` → 到最近整数距离。
    """
    v = price.values
    y = np.where(v < 10, v, np.where(v < 100, v / 10.0, v / 100.0))
    if mode == "ceil":
        dd = np.ceil(y) - y
    elif mode == "nearest":
        dd = np.abs(y - np.round(y))
    else:
        raise ValueError(mode)
    return pd.DataFrame(dd, index=price.index, columns=price.columns)


def price_position_ir(panel: TSPanel, n: int = 60, ddof: int = 1,
                      use_hfq: bool = True) -> pd.DataFrame:
    """``Mean((C−O)/(H−L), n) / StdDev(..., n)``（G11）。"""
    if use_hfq:
        C, Op, H, L = panel.C, panel.O, panel.H, panel.L
    else:
        adj = panel.ADJ
        C, Op, H, L = panel.C_RAW, panel.O / adj, panel.H / adj, panel.L / adj
    ratio = (C - Op) / (H - L)
    r = ratio.rolling(n)
    return r.mean() / r.std(ddof=ddof)


def alpha_intercept(panel: TSPanel, idx_ret: pd.Series, window: int,
                    ret_source: str = "C") -> pd.DataFrame:
    """``alpha = Intercept of OLS(stock_ret ~ index_ret)``（G15）。"""
    y = panel.C.pct_change() if ret_source == "C" else panel.C_RAW.pct_change()
    x = idx_ret.reindex(y.index)
    return _masked_rolling_ols(y, x, window, kind="intercept")


# ===========================================================================
# 面板构建
# ===========================================================================
def index_returns(index_codes: list[str], start: str, end: str,
                  use_cache: bool = True) -> dict[str, pd.Series]:
    """取指数日线收盘 → 简单日收益（``index_daily``，不需要复权）。"""
    import hashlib
    import pickle
    from ts_env import pro

    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    key = hashlib.sha1(f"{sorted(index_codes)}|{start}|{end}".encode()).hexdigest()[:12]
    cname = CACHE_DIR / f"index_daily_b2_{key}.pkl"
    if use_cache and cname.is_file():
        return pickle.loads(cname.read_bytes())
    pr = pro()
    out: dict[str, pd.Series] = {}
    for c in index_codes:
        d = pr.index_daily(ts_code=c, start_date=start.replace("-", ""),
                           end_date=end.replace("-", ""))
        d["trade_date"] = pd.to_datetime(d["trade_date"])
        s = d.set_index("trade_date").sort_index()["close"]
        out[c] = s.pct_change()
    if use_cache:
        cname.write_bytes(pickle.dumps(out))
    return out


def build(panel: TSPanel, idx_ret: dict[str, pd.Series] | None = None) -> dict[str, pd.DataFrame]:
    """按公式实现本批全部因子。默认口径：后复权价、窗口含当日、样本标准差、简单收益。"""
    C = panel.C
    ret = C.pct_change()
    out: dict[str, pd.DataFrame] = {}

    # ---- MACD 组（与批次一一致）--------------------------------------------
    dif = O.ema(C, 12) - O.ema(C, 26)
    dea = O.ema(dif, 9)
    out["dif"], out["dea"] = dif, dea
    out["MACD"] = 2 * (dif - dea)

    # ---- 均线 / 区间收益 ---------------------------------------------------
    out["ma_20d"] = O.ma(C, 20)
    for n in (5, 21, 42, 63, 126, 252):
        out[f"return_{n}d"] = (1 + ret).rolling(n).apply(np.prod, raw=True) - 1

    # ---- 连续涨跌天数 ------------------------------------------------------
    out["days_down_up"] = days_down_up(C)

    # ---- RSRS：OLS(Low ~ High, 18) → Z-Score(200, ddof=1) ------------------
    slope = _masked_rolling_ols(panel.L, panel.H, 18, kind="slope")
    out["rsrs"] = (slope - slope.rolling(200).mean()) / slope.rolling(200).std(ddof=1)

    # ---- 价格位置信息比率 --------------------------------------------------
    out["price_position_ir_60d"] = price_position_ir(panel, 60, ddof=1)

    # ---- 指数 alpha（滚动 OLS 截距）----------------------------------------
    if idx_ret:
        for name, (win, icode) in ALPHA_SPEC.items():
            if icode in idx_ret:
                out[name] = alpha_intercept(panel, idx_ret[icode], win)

    # ---- Reversal ----------------------------------------------------------
    out["rsi"] = rsi(C, 14, mode="wilder")
    out["price_dist"] = price_dist(C, mode="ceil")

    # ---- Size（负对数，市值以百万元计；total_mv 单位=万元）-----------------
    out["size"] = -np.log(panel.TOTAL_MV / 100.0)
    out["float_size"] = -np.log(panel.CIRC_MV / 100.0)

    # ---- Value（daily_basic 直接可得）-------------------------------------
    out["earnings_to_price"] = 1.0 / panel.PE_TTM
    out["book_to_market"] = 1.0 / panel.PB

    return {k: v for k, v in out.items() if k in IMPLEMENTED}


# ===========================================================================
# 校准变体（记录「哪个变体对、哪个错」）
# ===========================================================================
def variants(panel: TSPanel, idx_ret: dict[str, pd.Series] | None = None) -> dict[str, list]:
    """返回 ``因子名 -> [(变体名, DataFrame), …]``，用于口径标定。"""
    C, CRAW = panel.C, panel.C_RAW
    v: dict[str, list] = {}

    v["days_down_up"] = [
        ("strict(diff>0/<0)[HFQ]", days_down_up(C, strict=True)),
        ("nonstrict(diff>=0/<=0)[HFQ]", days_down_up(C, strict=False)),
        ("strict(raw)", days_down_up(CRAW, strict=True)),
    ]

    slope = _masked_rolling_ols(panel.L, panel.H, 18, kind="slope")
    slope_raw = _masked_rolling_ols(panel.L / panel.ADJ, panel.H / panel.ADJ, 18, kind="slope")
    v["rsrs"] = [
        ("HFQ+ddof1", (slope - slope.rolling(200).mean()) / slope.rolling(200).std(ddof=1)),
        ("HFQ+ddof0", (slope - slope.rolling(200).mean()) / slope.rolling(200).std(ddof=0)),
        ("raw+ddof1", (slope_raw - slope_raw.rolling(200).mean()) / slope_raw.rolling(200).std(ddof=1)),
    ]

    v["rsi"] = [
        ("wilder(com=13)", rsi(C, 14, "wilder")),
        ("span=14", rsi(C, 14, "span")),
        ("rolling SMA 14", rsi(C, 14, "sma_mean")),
        ("wilder(raw price)", rsi(CRAW, 14, "wilder")),
    ]

    v["price_dist"] = [
        ("HFQ+ceil", price_dist(C, "ceil")),
        ("raw+ceil", price_dist(CRAW, "ceil")),
        ("HFQ+nearest", price_dist(C, "nearest")),
    ]

    v["price_position_ir_60d"] = [
        ("HFQ+ddof1", price_position_ir(panel, 60, 1, True)),
        ("HFQ+ddof0", price_position_ir(panel, 60, 0, True)),
        ("raw+ddof1", price_position_ir(panel, 60, 1, False)),
    ]

    v["size"] = [
        ("-log(total_mv/100)", -np.log(panel.TOTAL_MV / 100.0)),
        ("-log(total_mv/1e6)", -np.log(panel.TOTAL_MV / 1e6)),
        ("-log(total_share*C_raw/1e6)", -np.log(panel.TOTAL_SHARE * CRAW / 1e6)),
        ("-log(total_share*C_hfq/1e6)", -np.log(panel.TOTAL_SHARE * C / 1e6)),
        ("+log(total_mv/100)", np.log(panel.TOTAL_MV / 100.0)),
    ]
    v["float_size"] = [
        ("-log(circ_mv/100)", -np.log(panel.CIRC_MV / 100.0)),
        ("-log(float_share*C_raw/1e6)", -np.log(panel.FLOAT_SHARE * CRAW / 1e6)),
        ("-log(float_share*C_hfq/1e6)", -np.log(panel.FLOAT_SHARE * C / 1e6)),
        ("+log(circ_mv/100)", np.log(panel.CIRC_MV / 100.0)),
    ]

    # Value：daily_basic 只有 pe_ttm / pb 两个现成口径，变体意义有限，
    # 用「TTM 倒数」与「市值口径重算」对照，验证官方是否就是 1/pe_ttm、1/pb。
    v["earnings_to_price"] = [
        ("1/pe_ttm", 1.0 / panel.PE_TTM),
        ("total_share*C_raw/total_mv 口径 = 1/pe_ttm", 1.0 / panel.PE_TTM),
    ]
    v["book_to_market"] = [
        ("1/pb", 1.0 / panel.PB),
    ]

    if idx_ret:
        for name, (win, icode) in ALPHA_SPEC.items():
            if icode in idx_ret:
                xr = idx_ret[icode]
                v[name] = [
                    ("HFQ simple ret", alpha_intercept(panel, xr, win, "C")),
                    ("raw simple ret", alpha_intercept(panel, xr, win, "C_RAW")),
                ]
    return v


# ===========================================================================
# 全市场横截面补充验证（--full-market）
# ===========================================================================
#: 需要**全市场**股票池才能判定的横截面因子。
#: 6 只股票池下 CrossSectionalRank 只有 6 档，绝对误差判定无意义，
#: 必须用全市场截面 + 秩相关（``xs_compare.compare_xs``）。
FM_FACTORS = ["nl_size", "small_cap_reversal_21d"]

#: 全市场 daily_basic 本地离线镜像（total_mv/circ_mv 单位 = 万元）
LOCAL_DAILY_BASIC = Path(
    "data/external/tushare/a_share_daily_basic_pit_v1/normalized/daily_basic.csv.gz")


def _local_daily_basic_field(dates, field: str) -> pd.DataFrame:
    """从本地 daily_basic 镜像取某字段的全市场宽表（index=date, columns=ts_code）。"""
    want = set(pd.DatetimeIndex(dates).strftime("%Y%m%d"))
    parts = []
    for ch in pd.read_csv(LOCAL_DAILY_BASIC, usecols=["ts_code", "trade_date", field],
                          dtype={"trade_date": str}, chunksize=2_000_000):
        parts.append(ch[ch["trade_date"].isin(want)])
    df = pd.concat(parts, ignore_index=True)
    df["trade_date"] = pd.to_datetime(df["trade_date"])
    return df.pivot(index="trade_date", columns="ts_code", values=field).sort_index()


def full_market_panel(lookback: str, end: str, use_cache: bool = True) -> dict:
    """全市场行情 + 市值面板。

    ⚠ 本地 ``market_daily_v1`` 镜像每只股票只有 36 行（2026-07-24~09-10），
    **不能用于 21 日窗口**，因此价格走 Tushare ``daily`` + ``adj_factor``（按 ``trade_date``
    单日全市场各 1 次调用）；市值走本地 daily_basic 镜像（净值为万元，换算见 G13）。
    """
    import pickle
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    cname = CACHE_DIR / f"fm_panel_b2_{lookback}_{end}.pkl".replace(":", "")
    if use_cache and cname.is_file():
        print("  [fm] 全市场面板缓存命中")
        return pickle.loads(cname.read_bytes())

    from ts_env import pro
    pr = pro()
    cal = pr.trade_cal(exchange="SSE", start_date=lookback.replace("-", ""),
                       end_date=end.replace("-", ""), is_open="1")
    dates = pd.DatetimeIndex(sorted(pd.to_datetime(cal["cal_date"])))
    px, af = [], []
    for i, d in enumerate(dates):
        ds = d.strftime("%Y%m%d")
        px.append(pr.daily(trade_date=ds))
        af.append(pr.adj_factor(trade_date=ds))
        if (i + 1) % 20 == 0:
            print(f"    …全市场行情 {i+1}/{len(dates)}")
    dl = pd.concat(px, ignore_index=True)
    al = pd.concat(af, ignore_index=True)
    m = dl.merge(al[["ts_code", "trade_date", "adj_factor"]],
                 on=["ts_code", "trade_date"], how="left")
    m["trade_date"] = pd.to_datetime(m["trade_date"])
    m["hfq"] = m["close"] * m["adj_factor"]
    out = {
        "hfq": m.pivot(index="trade_date", columns="ts_code", values="hfq").sort_index(),
        "raw": m.pivot(index="trade_date", columns="ts_code", values="close").sort_index(),
        "total_mv": _local_daily_basic_field(dates, "total_mv"),
    }
    if use_cache:
        cname.write_bytes(pickle.dumps(out))
    print(f"  [fm] 全市场面板 {out['hfq'].shape}（{dates[0].date()}~{dates[-1].date()}）")
    return out


def build_full_market(fm: dict) -> dict[str, pd.DataFrame]:
    """全市场横截面因子：``nl_size`` 与 ``small_cap_reversal_21d`` 的**内层+外层**实现。"""
    mv = fm["total_mv"]
    # ---- nl_size：Size³ 对 Size 做截面回归的残差 ---------------------------
    size = -np.log(mv / 100.0)
    xm = size.sub(size.mean(axis=1), axis=0)
    y = size ** 3
    ym = y.sub(y.mean(axis=1), axis=0)
    nl_size = ym.sub(xm.mul((xm * ym).sum(axis=1) / (xm * xm).sum(axis=1), axis=0))

    # ---- small_cap_reversal_21d：rank(-CumReturn) × rank(-MarketCap) -------
    # G17：CumReturn 用**后复权**价；``CrossSectionalRank(x) = rank(x)/N``。
    # ⚠️ 并列取**最大名次**（``method="max"``），不是 ``average`` —— 见 CONVENTIONS §3.4：
    #    算术证据 = 并列块的值恰好等于块内最大名次（`yoy_ocf` 1875 只在下 + 1767 只并列
    #    ⇒ 值 3642/4927 = 块内最大名次）。此前用 ``rank(axis=1)``（默认 average）是错的。
    cum = (1 + fm["hfq"].pct_change(fill_method=None)).rolling(21).apply(np.prod, raw=True) - 1
    rev = -cum
    rr = rev.rank(axis=1, method="max").div(rev.notna().sum(axis=1), axis=0)
    ss = (-mv).rank(axis=1, method="max").div(mv.notna().sum(axis=1), axis=0)
    return {"nl_size": nl_size, "small_cap_reversal_21d": rr.mul(ss, axis=0)}


def official_xs_panel(factors: list[str], dates, use_cache: bool = True,
                      guard: RateGuard | None = None) -> dict[str, pd.DataFrame]:
    """按 ``trade_date`` 取**单日全市场**官方因子值（~5500 行/次 < 6000 上限，G7）。"""
    import pickle
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    guard = guard or RateGuard()
    cli = QDataClient()
    d0, d1 = dates[0].strftime("%Y%m%d"), dates[-1].strftime("%Y%m%d")
    out: dict[str, pd.DataFrame] = {}
    for f in factors:
        cname = CACHE_DIR / f"official_xs_b2_{f}_{d0}_{d1}.pkl"
        if use_cache and cname.is_file():
            out[f] = pickle.loads(cname.read_bytes())
            print(f"    [cache] xs {f}")
            continue
        rec: dict[pd.Timestamp, pd.Series] = {}
        for d in dates:
            rows = []
            for attempt in range(5):
                guard.wait()
                try:
                    rows = cli.factor_value(factor_name=f, trade_date=d.strftime("%Y%m%d"))
                except Exception:
                    pass
                if rows:
                    break
                time.sleep(1.2 * (attempt + 1))
            if rows:
                df = pd.DataFrame(rows).drop_duplicates(subset=["ts_code"])
                rec[d] = df.set_index("ts_code")["factor_value"].astype(float)
        out[f] = pd.DataFrame(rec).T.sort_index()
        print(f"    …xs 官方 {f}：{len(out[f])} 日 × {out[f].shape[1]} 只")
        if use_cache:
            cname.write_bytes(pickle.dumps(out[f]))
    return out


# ===========================================================================
# 官方因子取数
# ===========================================================================
class RateGuard:
    """QPM 限流保护：60 秒窗口内不超过 ``qpm`` 次调用（G7）。"""

    def __init__(self, qpm: int = 190):
        self.qpm = qpm
        self.times: deque[float] = deque()

    def wait(self) -> None:
        now = time.monotonic()
        while self.times and now - self.times[0] > 60.0:
            self.times.popleft()
        if len(self.times) >= self.qpm:
            time.sleep(max(0.0, 60.0 - (now - self.times[0]) + 0.5))
        self.times.append(time.monotonic())


def _merge_cached_official(factors: list[str]) -> dict[str, pd.DataFrame]:
    """从 cache 里已有的 ``official_*.pkl`` 复用因子值，减少 API 调用。"""
    import pickle
    got: dict[str, pd.DataFrame] = {}
    want = set(factors)
    for f in sorted(CACHE_DIR.glob("official_*.pkl")):
        try:
            d = pickle.loads(f.read_bytes())
        except Exception:
            continue
        if not isinstance(d, dict):
            continue
        for k, v in d.items():
            if k in want and k not in got and isinstance(v, pd.DataFrame):
                got[k] = v
    return got


def _factor_cache_path(factor: str, start: str, end: str) -> Path:
    import re
    safe = re.sub(r"[^A-Za-z0-9_.-]", "_", factor)
    return CACHE_DIR / f"official_b2_f_{safe}_{start}_{end}.pkl".replace(":", "")


def _seed_factor_cache(factors: list[str], codes: list[str],
                       s_c: str, e_c: str) -> None:
    """把旧的「整包」官方缓存（批次一 ``official_<hash>.pkl``）转成按因子的增量缓存。

    这样重跑 batch2 不会重复调用已经取过的因子/股票。
    """
    import pickle
    legacy = _merge_cached_official(factors)
    if not legacy:
        return
    seeded = 0
    for f, df in legacy.items():
        cpath = _factor_cache_path(f, s_c, e_c)
        if cpath.is_file():
            continue
        series = {c: df[c].dropna() for c in df.columns if c in codes}
        if series:
            cpath.write_bytes(pickle.dumps(series))
            seeded += 1
    if seeded:
        print(f"  [qdata] 从旧缓存预置 {seeded} 个因子的按因子缓存")


def official_panel(codes: list[str], factors: list[str], start: str, end: str,
                   use_cache: bool = True, guard: RateGuard | None = None
                   ) -> dict[str, pd.DataFrame]:
    """取 qdata ``factor_value`` 官方值 → ``dict[factor -> DataFrame(date × code)]``。

    ⚠ 按 ``(factor_name, ts_code)`` 单取（禁用 offset 分页，G7）；
    ⚠ **空结果视为可重试**（G16：服务端压力下会返回 code=0 + 空 items）。

    缓存按**因子**分文件、**按 (因子, 股票) 增量落盘**，中断/重跑不会丢已取数据。
    """
    import pickle

    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    s_c, e_c = start.replace("-", ""), end.replace("-", "")
    if use_cache:
        _seed_factor_cache(factors, codes, s_c, e_c)
    cli = QDataClient()
    guard = guard or RateGuard()
    out: dict[str, pd.DataFrame] = {}
    for f in factors:
        cpath = _factor_cache_path(f, s_c, e_c)
        series: dict[str, pd.Series] = {}
        if use_cache and cpath.is_file():
            try:
                series = pickle.loads(cpath.read_bytes())
            except Exception:
                series = {}
        todo = [c for c in codes if c not in series]
        if not todo:
            print(f"    [cache] {f}（{len(series)} 只）")
            out[f] = pd.DataFrame(series).sort_index()
            continue
        n_ok = 0
        for c in todo:
            rows: list[dict] = []
            for attempt in range(6):
                guard.wait()
                try:
                    rows = cli.factor_value(factor_name=f, ts_code=c,
                                            start_date=s_c, end_date=e_c)
                except Exception as exc:                    # 网络/限流
                    print(f"    [retry {attempt+1}] {f}/{c}: {type(exc).__name__}")
                if rows:
                    break
                time.sleep(1.2 * (attempt + 1))             # G16 空结果退避
            if not rows:
                print(f"    !! {f}/{c} 无数据（重试后仍为空）")
                continue
            d = pd.DataFrame(rows).drop_duplicates(subset=["trade_date"])
            d["trade_date"] = pd.to_datetime(d["trade_date"])
            series[c] = d.set_index("trade_date")["factor_value"].astype(float)
            n_ok += 1
        if use_cache:
            cpath.write_bytes(pickle.dumps(series))
        print(f"    …{f} 完成（新取 {n_ok}/{len(todo)} 只）")
        if series:
            out[f] = pd.DataFrame(series).sort_index()
    print(f"  [qdata] 官方因子就绪（{len(out)} 个因子）")
    return out


# ===========================================================================
# 主流程
# ===========================================================================
COLS = ["factor", "verdict_med", "verdict", "n_overlap", "coverage",
        "max_abs_err", "med_rel_err", "corr"]


def _report(title: str, loc: dict, offi: dict, expected: list[str], tag: str) -> pd.DataFrame:
    print(f"\n===== {title} =====")
    d = compare_family(FAMILY, loc, offi, expected)
    with pd.option_context("display.width", 220):
        print(d[COLS].to_string(index=False, float_format=lambda x: f"{x:.4g}"))
    print("\n" + summarize(d))
    vc = d["verdict_med"].value_counts()
    print("verdict_med: " + "  ".join(f"{k}={vc.get(k, 0)}"
                                      for k in ("EXACT", "GOOD", "APPROX", "FAIL", "NO_DATA")))
    out = OUT_DIR / f"batch2_compare{tag}.csv"
    d.to_csv(out, index=False)
    print(f"报告: {out}")
    return d


def write_skipped() -> None:
    rows = [{"factor": k, "reason": v} for k, v in SKIPPED.items()]
    df = pd.DataFrame(rows)
    out = OUT_DIR / "batch2_skipped.csv"
    df.to_csv(out, index=False)
    print(f"跳过清单: {out}（{len(df)} 个）")


def _full_market_section(args, local: dict, off: dict, settle_days: int) -> None:
    """全市场横截面因子验证：``nl_size`` + ``small_cap_reversal_21d``。

    - **6 只股票池绝对误差**：对全市场算出的因子值取 6 只股票与官方比（诊断口径）；
    - **全市场横截面 Spearman**（`xs_compare.compare_xs`，判定口径）：
      横截面因子的本质是排序，绝对误差判据会把「名次几乎全对」误判为 FAIL。
    """
    from xs_compare import compare_xs, summarize_xs

    start, end = args.start, args.end
    cut = pd.Timestamp(end) - pd.Timedelta(days=settle_days) if settle_days > 0 else pd.Timestamp(end)
    fm_lookback = (pd.Timestamp(start) - pd.Timedelta(days=45)).strftime("%Y-%m-%d")

    print("\n" + "=" * 72)
    print("全市场横截面补充验证（nl_size / small_cap_reversal_21d）")
    print("=" * 72)
    fm = full_market_panel(fm_lookback, end, use_cache=not args.no_cache)
    fm_loc_all = build_full_market(fm)
    fm_loc = {k: v.loc[:cut] for k, v in fm_loc_all.items()}

    dates = pd.DatetimeIndex([d for d in fm_loc["nl_size"].index if d >= pd.Timestamp(start)])
    if args.xs_days > 0:
        dates = dates[-args.xs_days:]
    guard = RateGuard()
    fm_off = official_xs_panel(FM_FACTORS, dates, use_cache=not args.no_cache, guard=guard)

    # ---- 1) 6 只股票池：绝对误差（仅诊断，不是判定口径）------------------
    idx6 = pd.DatetimeIndex([d for d in dates if d <= cut])
    off6 = {f: v.reindex(idx6, columns=args.codes) for f, v in fm_off.items()}
    loc6 = {f: fm_loc[f].reindex(idx6, columns=args.codes) for f in FM_FACTORS}
    d6 = compare_family(FAMILY + "_fm6", loc6, off6, FM_FACTORS)
    with pd.option_context("display.width", 220):
        print("\n[6 只股票池 · 绝对误差 · 仅诊断]")
        print(d6[COLS].to_string(index=False, float_format=lambda x: f"{x:.4g}"))
    print(summarize(d6))
    d6.to_csv(OUT_DIR / "batch2_fullmarket_compare_settled.csv", index=False)

    # ---- 2) 全市场横截面 Spearman（判定口径）------------------------------
    dx = compare_xs(FAMILY + "_xs", fm_loc, fm_off, FM_FACTORS)
    with pd.option_context("display.width", 220):
        print("\n[全市场横截面 · 逐日 Spearman · 判定口径]")
        print(dx[["factor", "verdict_xs", "n_days", "n_stocks_med",
                  "spearman_med", "spearman_min"]].to_string(index=False))
    print(summarize_xs(dx))
    dx.to_csv(OUT_DIR / "batch2_xs_compare_settled.csv", index=False)
    print(f"报告: {OUT_DIR / 'batch2_fullmarket_compare_settled.csv'}")
    print(f"报告: {OUT_DIR / 'batch2_xs_compare_settled.csv'}")


def main() -> int:
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--codes", nargs="*",
                    default=["600519.SH", "000001.SZ", "000002.SZ",
                             "600036.SH", "002415.SZ", "000651.SZ"])
    ap.add_argument("--start", default="2026-06-01")
    ap.add_argument("--end", default="2026-09-10")
    ap.add_argument("--lookback", default="2020-01-01",
                    help="面板起点；alpha_1320d_000001 需要 ~1320 交易日回看，故默认 2020-01-01")
    ap.add_argument("--settle-days", type=int, default=SETTLE_DAYS_DEFAULT)
    ap.add_argument("--variants", action="store_true", help="额外跑口径变体标定表")
    ap.add_argument("--full-market", action="store_true",
                    help="额外用全市场面板验证 nl_size / small_cap_reversal_21d（横截面秩相关）")
    ap.add_argument("--xs-days", type=int, default=0,
                    help="全市场秩相关最多取多少天（0=全部已沉淀交易日）")
    ap.add_argument("--no-cache", action="store_true")
    args = ap.parse_args()

    from ts_env import load_panel

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    print(f"加载面板 {args.lookback} ~ {args.end} …")
    panel = load_panel(args.codes, args.lookback, args.end, use_cache=not args.no_cache)

    idx_codes = sorted({c for _, c in ALPHA_SPEC.values()})
    idx_ret = index_returns(idx_codes, args.lookback, args.end, use_cache=not args.no_cache)
    print(f"  指数收益: {idx_codes}")

    local = build(panel, idx_ret)
    missing = [f for f in IMPLEMENTED if f not in local]
    if missing:
        print(f"  ⚠ 本地缺少 {missing}")
    print(f"  本地实现 {len(local)} 个因子")

    off = official_panel(args.codes, IMPLEMENTED, args.start, args.end,
                         use_cache=not args.no_cache)

    df = _report("全窗口（含 qdata 未沉淀尾部）", local, off, IMPLEMENTED, "")

    if args.settle_days > 0:
        cut = pd.Timestamp(args.end) - pd.Timedelta(days=args.settle_days)
        print(f"\n[settle] 排除 {cut.date()} 之后的 {args.settle_days} 个自然日")
        loc_s = {k: v.loc[:cut] for k, v in local.items()}
        off_s = {k: v.loc[:cut] for k, v in off.items()}
        _report(f"已沉淀窗口（--settle-days {args.settle_days}，判定口径）",
                loc_s, off_s, IMPLEMENTED, "_settled")

    write_skipped()

    if args.full_market:
        _full_market_section(args, local, off, settle_days=args.settle_days)

    if args.variants:
        print("\n===== 口径变体标定（全窗口 verdict_med）=====")
        vr = variants(panel, idx_ret)
        canon = {
            "days_down_up": "strict(diff>0/<0)[HFQ]",
            "rsrs": "HFQ+ddof1", "rsi": "wilder(com=13)", "price_dist": "HFQ+ceil",
            "price_position_ir_60d": "HFQ+ddof1",
            "size": "-log(total_mv/100)", "float_size": "-log(circ_mv/100)",
            "earnings_to_price": "1/pe_ttm", "book_to_market": "1/pb",
        }
        rows = []
        for f, cands in vr.items():
            o = off.get(f)
            if o is None or o.empty:
                continue
            for vname, vdf in cands:
                r = compare_family(FAMILY, {f: vdf}, {f: o}, [f]).iloc[0]
                mark = "  <== canonical" if vname == canon.get(f) else ""
                rows.append({"factor": f, "variant": vname,
                             "verdict_med": r["verdict_med"], "verdict": r["verdict"],
                             "max_abs_err": r["max_abs_err"], "med_rel_err": r["med_rel_err"],
                             "n_overlap": r["n_overlap"], "corr": r["corr"]})
                print(f"  {f:26s} {vname:32s} med={r['verdict_med']:7s} "
                      f"max={r['max_abs_err']:.3e} rel={r['med_rel_err']:.3e}{mark}")
        vdf = pd.DataFrame(rows).sort_values(["factor", "med_rel_err"])
        vout = OUT_DIR / "batch2_variants.csv"
        vdf.to_csv(vout, index=False)
        print(f"变体表: {vout}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
