"""Phase A data layer: clean, survivorship-bias-aware daily panels from baostock.

Design notes
------------
* **Two price modes.** Returns and factor computation use the *backward-adjusted*
  series (``adjustflag="1"``, 后复权). Limit-up/limit-down detection, price-level
  filters and "can this order fill?" logic use the *unadjusted* series
  (``adjustflag="3"``, 不复权) together with ``preclose``. Mixing them is the
  single most common source of silently wrong A-share backtests.
* **Survivorship bias.** ``query_stock_basic()`` carries ``ipoDate``/``outDate``/
  ``status`` for delisted names too, so point-in-time membership is reconstructed
  from date ranges rather than from today's listing.
* **Resumable.** Every (code, mode) pair is cached as its own parquet file, so an
  interrupted multi-hour download resumes instead of restarting.

Nothing here is imported by qlib; this is a standalone track.
"""

from __future__ import annotations

import contextlib
import time
from collections.abc import Iterable, Iterator, Sequence
from dataclasses import dataclass
from pathlib import Path

import pandas as pd

from .config import (
    ADJUST_BACKWARD,
    ADJUST_NONE,
    CACHE_DIR,
    DAILY_FIELD_LADDER,
    MAIN_BOARD_PREFIXES,
    CHINEXT_PREFIXES,
    EXCLUDED_PREFIXES,
    UniverseRules,
)

# --------------------------------------------------------------------------- #
# low-level baostock plumbing
# --------------------------------------------------------------------------- #


def _require_baostock():
    try:
        import baostock as bs  # noqa: PLC0415 - optional heavy import
    except ImportError as exc:  # pragma: no cover - environment problem
        raise RuntimeError(
            "baostock is not installed. Run research/scripts/bootstrap_env.ps1 first."
        ) from exc
    return bs


@contextlib.contextmanager
def baostock_session(max_attempts: int = 3) -> Iterator[object]:
    """Log in for the duration of the block, retrying transient login failures."""
    bs = _require_baostock()
    last_error = "unknown"
    for attempt in range(1, max_attempts + 1):
        result = bs.login()
        if result.error_code == "0":
            break
        last_error = f"{result.error_code}: {result.error_msg}"
        time.sleep(min(2 ** attempt, 10))
    else:
        raise RuntimeError(f"baostock login failed after {max_attempts} attempts ({last_error})")
    try:
        yield bs
    finally:
        with contextlib.suppress(Exception):
            bs.logout()


class BaostockQueryError(RuntimeError):
    """A baostock ResultData came back with a non-zero error code."""

    def __init__(self, code: str, message: str, context: str) -> None:
        super().__init__(f"baostock query failed for {context} ({code}: {message})")
        self.code = code
        self.message = message
        self.context = context

    @property
    def is_no_data(self) -> bool:
        """True when the failure just means the window holds no rows for this name."""
        text = self.message.lower()
        return "no data" in text or "无数据" in self.message or self.code in {"10001004", "10002007"}


def _result_to_frame(result, *, context: str) -> pd.DataFrame:
    """Drain a baostock ResultData into a DataFrame, or raise on a non-zero code.

    Retrying is deliberately *not* attempted here: a baostock ResultData is a
    consumed cursor, so re-reading it cannot produce a different answer. Field
    fallback and re-issue happen one level up, in :func:`fetch_daily`.
    """
    if result.error_code != "0":
        raise BaostockQueryError(result.error_code, result.error_msg, context)
    rows: list[list[str]] = []
    while result.next():
        rows.append(result.get_row_data())
    return pd.DataFrame(rows, columns=result.fields)


def _query_history(bs, code: str, fields: Sequence[str], start: str, end: str, adjustflag: str):
    return bs.query_history_k_data_plus(
        code,
        ",".join(fields),
        start_date=start,
        end_date=end,
        frequency="d",
        adjustflag=adjustflag,
    )


# --------------------------------------------------------------------------- #
# reference data
# --------------------------------------------------------------------------- #


def fetch_stock_basic(bs) -> pd.DataFrame:
    """All securities baostock knows about, delisted ones included.

    Returns columns: ``code``, ``code_name``, ``ipo_date``, ``out_date``,
    ``sec_type``, ``status``. ``status`` is 1 for listed and 0 for delisted.
    """
    frame = _result_to_frame(bs.query_stock_basic(), context="query_stock_basic")
    frame = frame.rename(
        columns={
            "code": "code",
            "code_name": "code_name",
            "ipoDate": "ipo_date",
            "outDate": "out_date",
            "type": "sec_type",
            "status": "status",
        }
    )
    for column in ("ipo_date", "out_date"):
        if column in frame.columns:
            frame[column] = pd.to_datetime(frame[column], errors="coerce")
    if "status" in frame.columns:
        frame["status"] = pd.to_numeric(frame["status"], errors="coerce")
    return frame


def fetch_industry(bs) -> pd.DataFrame:
    """CSRC industry mapping, one row per security."""
    frame = _result_to_frame(bs.query_stock_industry(), context="query_stock_industry")
    keep = [c for c in ("code", "code_name", "industry", "industryClassification") if c in frame.columns]
    return frame[keep].drop_duplicates(subset=["code"])


def classify_board(code: str) -> str:
    """Map a baostock code to a coarse board label."""
    for prefix in CHINEXT_PREFIXES:
        if code.startswith(prefix):
            return "chinext"
    for prefix in EXCLUDED_PREFIXES:
        if code.startswith(prefix):
            return "excluded"
    for prefix in MAIN_BOARD_PREFIXES:
        if code.startswith(prefix):
            return "main"
    return "other"


def select_universe_codes(basic: pd.DataFrame, rules: UniverseRules | None = None) -> pd.DataFrame:
    """Filter ``fetch_stock_basic`` output down to the researched universe.

    Delisted names are **kept**: they are exactly what a naive universe drops and
    what makes a backtest look better than reality.
    """
    rules = rules or UniverseRules()
    frame = basic.copy()
    if "sec_type" in frame.columns:
        frame = frame[frame["sec_type"].astype(str) == "1"]  # 1 = 股票
    frame["board"] = frame["code"].map(classify_board)

    allowed = {"main"} | ({"chinext"} if rules.include_chinext else set())
    frame = frame[frame["board"].isin(allowed)]
    return frame.reset_index(drop=True)


# --------------------------------------------------------------------------- #
# daily history
# --------------------------------------------------------------------------- #


def _cache_path(code: str, mode: str) -> Path:
    return CACHE_DIR / f"{code.replace('.', '_')}__{mode}.parquet"


def fetch_daily(
    bs,
    code: str,
    start: str,
    end: str,
    *,
    use_cache: bool = True,
    sleep_seconds: float = 0.0,
) -> dict[str, pd.DataFrame]:
    """Fetch both price modes for one security.

    Returns ``{"none": <unadjusted frame>, "back": <backward-adjusted frame>}``.
    An empty frame means the security had no trading days in the window.
    """
    frames: dict[str, pd.DataFrame] = {}
    modes = {"none": ADJUST_NONE, "back": ADJUST_BACKWARD}

    for mode, adjustflag in modes.items():
        path = _cache_path(code, mode)
        if use_cache and path.exists():
            frames[mode] = pd.read_parquet(path)
            continue

        ladder = DAILY_FIELD_LADDER if mode == "none" else (
            ("date", "code", "open", "high", "low", "close", "preclose", "volume", "amount"),
            ("date", "code", "open", "high", "low", "close", "volume"),
        )

        frame: pd.DataFrame | None = None
        last_error: BaostockQueryError | None = None
        for fields in ladder:
            try:
                result = _query_history(bs, code, fields, start, end, adjustflag)
                frame = _result_to_frame(result, context=f"{code} adj={adjustflag}")
                break
            except BaostockQueryError as exc:
                last_error = exc
                if exc.is_no_data:
                    # Nothing in this window; further rungs cannot help.
                    break
                # An unknown field makes baostock reject the whole request, so
                # fall through to the next (shorter) rung.
                continue
        if frame is None:
            if last_error is not None and not last_error.is_no_data:
                raise last_error
            frame = pd.DataFrame(columns=["date", "code"])

        frame = _coerce_daily(frame)
        if use_cache:
            frame.to_parquet(path, index=False)
        if sleep_seconds:
            time.sleep(sleep_seconds)
        frames[mode] = frame

    return frames


def _coerce_daily(frame: pd.DataFrame) -> pd.DataFrame:
    """Normalize dtypes: dates to datetime64, everything numeric to float."""
    if frame.empty:
        return frame
    out = frame.copy()
    if "date" in out.columns:
        out["date"] = pd.to_datetime(out["date"], errors="coerce")
    for column in out.columns:
        if column in {"date", "code"}:
            continue
        out[column] = pd.to_numeric(out[column], errors="coerce")
    if "tradestatus" in out.columns:
        out["tradestatus"] = out["tradestatus"].fillna(0).astype("int8")
    if "isST" in out.columns:
        out["isST"] = out["isST"].fillna(0).astype("int8")
    out = out.dropna(subset=["date"]).sort_values("date").reset_index(drop=True)
    return out


def merge_price_modes(unadjusted: pd.DataFrame, adjusted: pd.DataFrame) -> pd.DataFrame:
    """Merge the two price modes into one per-security frame.

    Unadjusted columns keep their names; adjusted OHLCV columns get an ``adj_``
    prefix so a caller can never confuse the two by accident.
    """
    if unadjusted.empty and adjusted.empty:
        return pd.DataFrame()

    if adjusted.empty:
        out = unadjusted.copy()
    elif unadjusted.empty:
        out = adjusted.rename(
            columns={c: f"adj_{c}" for c in adjusted.columns if c not in {"date", "code"}}
        )
    else:
        renamed = adjusted.rename(
            columns={c: f"adj_{c}" for c in adjusted.columns if c not in {"date", "code"}}
        )
        out = unadjusted.merge(renamed, on=["date", "code"], how="outer")

    out = out.sort_values("date").reset_index(drop=True)
    if "adj_close" not in out.columns and "close" in out.columns:
        # No adjusted series available for this name; fall back to raw with a marker
        # column so downstream code can exclude it from return computations.
        out["adj_close"] = out["close"]
        out["adj_is_fallback"] = True
    else:
        out["adj_is_fallback"] = False
    return out


# --------------------------------------------------------------------------- #
# panel assembly
# --------------------------------------------------------------------------- #


@dataclass
class DownloadReport:
    """Bookkeeping for one ingestion run."""

    requested: int = 0
    succeeded: int = 0
    empty: int = 0
    failed: list[tuple[str, str]] = None  # type: ignore[assignment]

    def __post_init__(self) -> None:
        if self.failed is None:
            self.failed = []

    def summary(self) -> str:
        lines = [
            f"requested : {self.requested}",
            f"succeeded : {self.succeeded}",
            f"no data   : {self.empty}",
            f"failed    : {len(self.failed)}",
        ]
        for code, error in self.failed[:10]:
            lines.append(f"  - {code}: {error}")
        if len(self.failed) > 10:
            lines.append(f"  ... and {len(self.failed) - 10} more")
        return "\n".join(lines)


def download_universe(
    codes: Iterable[str],
    start: str,
    end: str,
    *,
    use_cache: bool = True,
    sleep_seconds: float = 0.0,
    progress: bool = True,
) -> DownloadReport:
    """Download and cache both price modes for every code. Resumable."""
    code_list = list(codes)
    report = DownloadReport(requested=len(code_list))

    iterator: Iterable[str] = code_list
    if progress:
        try:
            from tqdm import tqdm  # noqa: PLC0415

            iterator = tqdm(code_list, desc="baostock daily", unit="stock")
        except ImportError:  # pragma: no cover
            iterator = code_list

    with baostock_session() as bs:
        for code in iterator:
            try:
                frames = fetch_daily(
                    bs, code, start, end, use_cache=use_cache, sleep_seconds=sleep_seconds
                )
            except Exception as exc:  # noqa: BLE001 - one bad name must not kill the run
                report.failed.append((code, f"{type(exc).__name__}: {exc}"))
                continue
            if frames["none"].empty and frames["back"].empty:
                report.empty += 1
            else:
                report.succeeded += 1
    return report


def load_cached_panel(codes: Sequence[str]) -> pd.DataFrame:
    """Assemble the cached per-security files into one long panel."""
    frames: list[pd.DataFrame] = []
    for code in codes:
        none_path = _cache_path(code, "none")
        back_path = _cache_path(code, "back")
        if not none_path.exists() and not back_path.exists():
            continue
        unadjusted = pd.read_parquet(none_path) if none_path.exists() else pd.DataFrame()
        adjusted = pd.read_parquet(back_path) if back_path.exists() else pd.DataFrame()
        merged = merge_price_modes(unadjusted, adjusted)
        if merged.empty:
            continue
        merged["code"] = code
        frames.append(merged)
    if not frames:
        return pd.DataFrame()
    panel = pd.concat(frames, ignore_index=True)
    return panel.sort_values(["date", "code"]).reset_index(drop=True)
