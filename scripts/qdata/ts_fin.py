#!/usr/bin/env python
"""财务报表面板数据层（Quality / Growth 因子复现的输入）。

设计
----
Tushare 四大报表接口（``income`` / ``balancesheet`` / ``cashflow`` /
``fina_indicator``）都含 ``ann_date``（公告日）与 ``end_date``（报告期）。
本模块把它们整理成**按披露顺序排列的 FinMatrix**（每只股票一张），
再按 ``ann_date`` 前向填充到交易日，构成 PIT 面板（无前视偏差）。

口径约定（由 passthrough 因子实测标定，见 repro_quality.py 报告）
----------------------------------------------------------------
- ``_Q``   单季值：利润表/现金流量表是**年初至今累计值**，需做差分；资产负债表是时点值，单季=期末值
- ``_TTM`` 滚动四季 = ``本期累计 + 上年年报 − 上年同期累计``（缺上年同期时报 NaN）
- ``_y``   年度值：取 ``end_date`` 为 12-31 的报告
- 时点量（总资产/存货/应收…）一律取**报告期末值**，不做平均（实测更优，见报告）

Tushare 接口限制
----------------
``income`` 等**不支持按报告期批量取全市场**（必填 ``ts_code``），
所以：
1. 小样本（6 只股票）走 API 逐股取，全列可用；
2. 全市场横截面验证走本地离线镜像 ``data/external/tushare/a_share_financial_pit_v1/``。
"""
from __future__ import annotations

import pickle
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

_SCRIPTS = Path(__file__).resolve().parents[1]
for p in (str(_SCRIPTS), str(_SCRIPTS / "qdata")):
    if p not in sys.path:
        sys.path.insert(0, p)

REPO_ROOT = Path(__file__).resolve().parents[2]
CACHE = REPO_ROOT / "output" / "qdata_factor_repro" / "cache" / "fin"
CACHE.mkdir(parents=True, exist_ok=True)
MIRROR = REPO_ROOT / "data" / "external" / "tushare" / "a_share_financial_pit_v1"

TABLES = ("income", "balancesheet", "cashflow", "fina_indicator")

#: 需要做「累计 → 单季」差分的报表（利润表 / 现金流量表）
_CUMULATIVE = {"income", "cashflow"}


# ============================================================ 取数（逐股 API） ====
def _cache_path(code: str, table: str, start: str, end: str) -> Path:
    return CACHE / f"{table}__{code}__{start}_{end}.pkl"


def load_table(code: str, table: str, start: str = "20150101",
               end: str = "20260917", use_cache: bool = True) -> pd.DataFrame:
    p = _cache_path(code, table, start, end)
    if use_cache and p.is_file():
        return pd.read_pickle(p)
    from ts_env import pro
    pr = pro()
    for att in range(5):
        try:
            df = getattr(pr, table)(ts_code=code, start_date=start, end_date=end)
            break
        except Exception as exc:                       # noqa: BLE001
            print(f"    !! {table} {code} 失败({exc}) → 退避")
            time.sleep(1.5 ** att)
    else:
        raise RuntimeError(f"{table} {code} 取数失败")
    if df is None:
        df = pd.DataFrame()
    df = df.copy()
    for c in ("ann_date", "f_ann_date", "end_date"):
        if c in df.columns:
            df[c] = pd.to_datetime(df[c], format="%Y%m%d", errors="coerce")
    if use_cache:
        df.to_pickle(p)
    time.sleep(0.35)
    return df


def load_all(codes: list[str], start: str = "20150101", end: str = "20260917",
             tables: tuple[str, ...] = TABLES) -> dict[str, dict[str, pd.DataFrame]]:
    """``{table: {code: long_df}}``。"""
    out: dict[str, dict[str, pd.DataFrame]] = {t: {} for t in tables}
    for c in codes:
        for t in tables:
            out[t][c] = load_table(c, t, start, end)
    return out


# ============================================================ FinMatrix =========
class FinMatrix:
    """一只股票的「按披露顺序」财报矩阵。

    ``df``：index = 披露序号（0 = 最早），列 = 四表合并后的字段，
    额外列 ``end_date`` / ``ann_date`` / ``_seq``。
    """

    def __init__(self, tables: dict[str, pd.DataFrame]):
        rows = []
        # ---- 以各表 end_date 的并集为报告期全集 ---------------------------------
        all_end = sorted({pd.Timestamp(d) for t in tables.values()
                          if t is not None and not t.empty
                          for d in t["end_date"].dropna().unique()})
        if not all_end:
            self.df = pd.DataFrame()
            return
        merged = pd.DataFrame(index=pd.DatetimeIndex(all_end, name="end_date"))
        ann = pd.Series(pd.NaT, index=merged.index)
        for name, t in tables.items():
            if t is None or t.empty:
                continue
            d = t.dropna(subset=["end_date"]).copy()
            # 同一报告期可能有多个版本（原始披露 / 追溯重述）→ 取**最早可得的那一版**
            # ⚠ 本地镜像用 ``available_date`` 区分重述版本（同 ann_date 不同 available_date），
            #   若只按 ann_date 去重会随机取到重述版，导致 _y 口径大面积错位（实测）。
            sort_cols = ["ann_date"] + (["available_date"] if "available_date" in d.columns else [])
            d = (d.sort_values(sort_cols, na_position="last")
                   .drop_duplicates(subset=["end_date"], keep="first"))
            d = d.set_index("end_date")
            cols = [c for c in d.columns if c not in ("ts_code", "ann_date",
                                                      "f_ann_date", "end_date")]
            sub = d[cols].reindex(merged.index)
            dup = [c for c in sub.columns if c in merged.columns]
            sub = sub.drop(columns=dup)
            merged = merged.join(sub)
            a = d["ann_date"].reindex(merged.index)
            ann = ann.where(ann.notna(), a) if ann.notna().any() else a
            # ann_date 若同报告期缺，用任意表的最早公告日兜底
            ann = ann.combine_first(a)
        # fina_indicator 的字段名与三表重名时加前缀
        merged["ann_date"] = ann
        # 报告期必须有公告日才可用
        # 同一公告日可能同时披露年报 + 一季报 → 必须按 end_date 次序稳定排序，
        # 否则「后一期报告」与「前一期报告」的相对顺序随机，_y/_q 口径会串期。
        merged = (merged.loc[merged["ann_date"].notna()]
                        .sort_values(["ann_date", "end_date"], kind="stable"))
        merged = merged.reset_index()
        merged["_seq"] = np.arange(len(merged))
        self.df = merged
        self._cum_cache: dict[tuple[str, str], pd.Series] = {}

    # ---- 基础访问 -------------------------------------------------------------
    @property
    def empty(self) -> bool:
        return self.df.empty

    def raw(self, field: str) -> pd.Series:
        """报告期原始值（index = ``_seq``）。"""
        if field not in self.df.columns:
            return pd.Series(np.nan, index=self.df.index)
        return pd.to_numeric(self.df[field], errors="coerce")

    def _keys(self) -> tuple[np.ndarray, np.ndarray]:
        ed = self.df["end_date"]
        return ed.dt.year.to_numpy(), (ed.dt.month.to_numpy() // 3).astype(int)

    def _qcol(self, field: str, cumulative: bool) -> pd.Series:
        """单季值。``cumulative`` 的表需差分（Q1 直接用累计值）。"""
        v = self.raw(field)
        if not cumulative:
            return v
        vv = v.to_numpy(dtype=float)
        yr, q = self._keys()
        pos = {(int(y), int(qq)): i for i, (y, qq) in enumerate(zip(yr, q))}
        prev = np.array([pos.get((int(y), int(qq) - 1), -1) if qq > 1 else -1
                         for y, qq in zip(yr, q)])
        pv = np.where(prev >= 0, vv[np.clip(prev, 0, None)], np.nan)
        out = np.where(q > 1, vv - pv, vv)
        out = np.where(np.isfinite(vv) & (q > 1) & ~np.isfinite(pv), np.nan, out)
        return pd.Series(out, index=self.df.index)

    def _fy(self, field: str, cumulative: bool) -> dict:
        """{年份: 年报值}。"""
        ed = self.df["end_date"]
        v = self.raw(field)
        return {int(ed.iloc[i].year): v.iloc[i] for i in range(len(self.df))
                if ed.iloc[i].month == 12}

    # 「是否累计」取决于字段所属报表，故由调用方显式传参（income/cashflow=True）
    def q(self, field: str, cumulative: bool) -> pd.Series:
        return self._qcol(field, cumulative)

    def ttm(self, field: str, cumulative: bool) -> pd.Series:
        """``本期累计 + 上年年报 − 上年同期累计``（Q4 即年报本身）。"""
        v = self.raw(field)
        vv = v.to_numpy(dtype=float)
        yr, q = self._keys()
        fy = self._fy(field, cumulative)
        cum = {(int(y), int(qq)): i for i, (y, qq) in enumerate(zip(yr, q))}
        f = np.array([fy.get(int(y) - 1, np.nan) for y in yr], dtype=float)
        pidx = np.array([cum.get((int(y) - 1, int(qq)), -1) for y, qq in zip(yr, q)])
        p = np.where(pidx >= 0, vv[np.clip(pidx, 0, None)], np.nan)
        out = np.where(q == 4, vv, vv + f - p)
        bad = (q != 4) & ~(np.isfinite(vv) & np.isfinite(f) & np.isfinite(p))
        out = np.where(bad, np.nan, out)
        return pd.Series(out, index=self.df.index)

    def y(self, field: str) -> pd.Series:
        """年报值（其他报告期为 NaN）。"""
        ed = self.df["end_date"]
        v = self.raw(field)
        return v.where(ed.dt.month == 12)

    # ---- 衍生时序操作（在披露序列上做） --------------------------------------
    def prev(self, s: pd.Series, n: int = 1) -> pd.Series:
        """披露序列上前 n 个报告期的值（公式里的 ``prev_report`` / ``4披露前``）。"""
        return s.shift(n)

    def yoy4(self, s: pd.Series) -> pd.Series:
        """``s_t / s_{前4个披露日} - 1``。"""
        p = s.shift(4)
        return s / p.where(p != 0) - 1

    def delta4(self, s: pd.Series) -> pd.Series:
        """``s_t - s_{前4个披露日}``。"""
        return s - s.shift(4)


def build_matrices(tables: dict[str, dict[str, pd.DataFrame]], codes: list[str]) -> dict[str, FinMatrix]:
    return {c: FinMatrix({t: tables[t].get(c) for t in tables}) for c in codes}


# ============================================================ PIT → 交易日 ========
def to_panel(mats: dict[str, FinMatrix], series_fn, dates: pd.DatetimeIndex,
             codes: list[str]) -> pd.DataFrame:
    """把「每报告期一个值」的序列按 ``ann_date`` 前向填充成 ``date × code`` 面板。"""
    cols = {}
    for c in codes:
        m = mats[c]
        if m.empty:
            continue
        s = series_fn(m)
        s = pd.Series(np.asarray(s, dtype=float), index=pd.DatetimeIndex(m.df["ann_date"]))
        # 同一公告日的多期报告：**非空值优先**（NaN 排前，稳定排序保留报告期次序），
        # 否则 `_y` 口径在「年报+一季报同日披露」时会被 NaN 覆盖，fFill 到上上年报。
        if s.index.has_duplicates:
            ordr = np.argsort(np.isfinite(s.to_numpy(dtype=float)), kind="stable")
            s = pd.Series(s.to_numpy(dtype=float)[ordr], index=s.index[ordr])
            s = s[~s.index.duplicated(keep="last")]
        s = s.sort_index()
        cols[c] = s.reindex(s.index.union(dates)).ffill().reindex(dates)
    out = pd.DataFrame(cols)
    return out.reindex(columns=codes)


# ============================================================ 本地全市场镜像 =====
_MIRROR_TABLES = {
    "income": ["revenue", "total_revenue", "oper_cost", "total_cogs", "operate_profit",
               "total_profit", "n_income", "n_income_attr_p", "income_tax", "basic_eps",
               "biz_tax_surchg", "sell_exp", "admin_exp", "fin_exp", "int_exp",
               "ebit", "ebitda", "rd_exp", "invest_income", "fin_exp_int_exp"],
    "balancesheet": ["total_assets", "total_liab", "total_cur_assets",
                     "total_cur_liab", "inventories", "accounts_receiv",
                     "money_cap", "trad_asset", "fix_assets", "cip",
                     "defer_tax_assets", "lt_rec", "prepayment",
                     "adv_receipts", "total_hldr_eqy_exc_min_int",
                     "total_hldr_eqy_inc_min_int", "total_share",
                     "minority_int", "accounts_receiv_bill", "oth_receiv",
                     "total_ncl", "fix_assets_total"],
    "cashflow": ["n_cashflow_act", "c_fr_sale_sg", "n_cashflow_inv_act",
                 "free_cashflow", "c_pay_dist_dpcp_int_exp", "depr_fa_coga_dpba",
                 "c_inf_fr_operate_a", "stot_inflows_inv_act", "c_paid_to_for_empl"],
}


def load_mirror_full(codes: list[str] | None = None,
                     tables: dict[str, list[str]] | None = None) -> dict[str, pd.DataFrame]:
    """读本地离线镜像 ``full/normalized/batch_*``（2009~2024，全列可用）。

    返回 ``{table: DataFrame}``（长表，仅保留需要的列）。
    """
    tables = tables or _MIRROR_TABLES
    key = CACHE / ("mirror_full_" + str(abs(hash(tuple((t, tuple(c)) for t, c in sorted(tables.items())))) % 10**12)
                   + f"_{codes is None and 'all' or len(codes)}.pkl")
    if key.is_file():
        return pd.read_pickle(key)
    out: dict[str, list[pd.DataFrame]] = {t: [] for t in tables}
    for t, cols in tables.items():
        if t == "balancesheet":
            files = sorted((MIRROR / "balancesheet_v1" / "normalized").glob("batch_*/balancesheet.csv.gz"))
        else:
            files = sorted((MIRROR / "full" / "normalized").glob(f"batch_*/{t}.csv.gz"))
        for f in files:
            head = pd.read_csv(f, nrows=0)
            use = [c for c in ["ts_code", "ann_date", "end_date"] + cols if c in head.columns]
            df = pd.read_csv(f, usecols=use)
            for c in ("ann_date", "end_date", "f_ann_date"):
                if c in df.columns:
                    df[c] = pd.to_datetime(df[c].astype("Int64").astype(str),
                                           format="%Y%m%d", errors="coerce")
            if codes is not None:
                df = df[df["ts_code"].isin(codes)]
            if not df.empty:
                out[t].append(df)
    res = {t: pd.concat(v, ignore_index=True) if v else pd.DataFrame() for t, v in out.items()}
    if codes is None:
        try:
            pd.to_pickle(res, key)
        except Exception:                              # noqa: BLE001
            pass
    return res


def load_mirror_recent(codes: list[str] | None = None) -> dict[str, pd.DataFrame]:
    """读 ``recent_3tables``（2025~2026，仅 revenue / n_income_attr_p / total_assets / OCF）。"""
    base = MIRROR / "recent_3tables"
    files = {"income": sorted(base.glob("income_*.csv.gz")),
             "balancesheet": sorted(base.glob("balancesheet_*.csv.gz")),
             "cashflow": sorted(base.glob("cashflow_*.csv.gz"))}
    out = {}
    for t, fs in files.items():
        frames = []
        want = set(codes) if codes is not None else None
        for f in fs:
            code = f.name.split("_", 1)[1][: -len(".csv.gz")].replace("_", ".")
            if want is not None and code not in want:
                continue
            frames.append(pd.read_csv(f))
        df = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()
        for c in ("ann_date", "end_date"):
            if c in df.columns:
                df[c] = pd.to_datetime(df[c].astype("Int64").astype(str),
                                       format="%Y%m%d", errors="coerce")
        out[t] = df
    return out


if __name__ == "__main__":
    t = load_all(["600519.SH"], "20200101", "20260917")
    m = FinMatrix({k: v["600519.SH"] for k, v in t.items()})
    print(m.df[["end_date", "ann_date", "revenue", "n_income_attr_p",
                "total_assets", "total_hldr_eqy_exc_min_int"]].tail(8).to_string())
