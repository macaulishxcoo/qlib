"""Configuration for the CN daily-frequency quant research track.

Everything that encodes a *decision* (universe rules, cost model, acceptance
thresholds, date ranges) lives here so it can be audited and changed in one place.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

# --------------------------------------------------------------------------- #
# paths
# --------------------------------------------------------------------------- #

RESEARCH_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = RESEARCH_ROOT / "data"
REPORT_DIR = RESEARCH_ROOT / "reports"
CACHE_DIR = DATA_DIR / "raw_baostock"
PANEL_DIR = DATA_DIR / "panel"

for _directory in (DATA_DIR, REPORT_DIR, CACHE_DIR, PANEL_DIR):
    _directory.mkdir(parents=True, exist_ok=True)


# --------------------------------------------------------------------------- #
# universe
# --------------------------------------------------------------------------- #

#: Prefixes kept in the tradable universe, keyed by the baostock exchange prefix.
#: 沪深主板 = SH 600/601/603/605 + SZ 000/001/002/003.
MAIN_BOARD_PREFIXES: tuple[str, ...] = (
    "sh.600",
    "sh.601",
    "sh.603",
    "sh.605",
    "sz.000",
    "sz.001",
    "sz.002",
    "sz.003",
)

#: Explicitly excluded boards, kept here so the exclusion is documented, not implied.
EXCLUDED_PREFIXES: tuple[str, ...] = (
    "sh.688",  # 科创板 STAR
    "sh.689",  # 科创板 CDR
    "sz.300",  # 创业板 ChiNext
    "sz.301",  # 创业板 ChiNext
    "bj.",     # 北交所 BSE
    "sh.900",  # B 股
    "sz.200",  # B 股
)

#: ChiNext is not 科创板/北交所, so it is a separate opt-in rather than a silent default.
CHINEXT_PREFIXES: tuple[str, ...] = ("sz.300", "sz.301")


@dataclass(frozen=True)
class UniverseRules:
    """Filters applied when building the investable set for a given date."""

    include_chinext: bool = False
    exclude_st: bool = True
    exclude_suspended: bool = True
    min_listing_days: int = 60
    #: Names whose average daily amount (CNY) over the lookback is below this are dropped.
    #: ¥5,000,000 ADV keeps a ¥500,000 book's per-name order under 1% of ADV at 60 names.
    min_avg_amount: float = 5_000_000.0
    amount_lookback_days: int = 20


# --------------------------------------------------------------------------- #
# cost model
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class CostModel:
    """Realistic A-share main-board trading costs.

    Defaults reflect the 2025 rule set: commission at the common quantitative
    channel rate, stamp duty halved to 0.05% on the sell side since 2023-08-28,
    and the unified 0.001% transfer fee.
    """

    commission_rate: float = 0.00025
    commission_min: float = 5.0
    stamp_duty_sell: float = 0.0005
    transfer_fee: float = 0.00001
    slippage_one_way: float = 0.0005

    @property
    def one_way(self) -> float:
        """Baseline one-way cost used for quick estimates (excludes the ¥5 floor)."""
        return self.commission_rate + self.transfer_fee + self.slippage_one_way

    @property
    def round_trip(self) -> float:
        """Baseline round-trip cost used for quick estimates."""
        return 2 * self.one_way + self.stamp_duty_sell

    def scaled(self, factor: float) -> "CostModel":
        """Return a copy with every rate multiplied by ``factor`` (for stress tests)."""
        return CostModel(
            commission_rate=self.commission_rate * factor,
            commission_min=self.commission_min,
            stamp_duty_sell=self.stamp_duty_sell * factor,
            transfer_fee=self.transfer_fee * factor,
            slippage_one_way=self.slippage_one_way * factor,
        )


DEFAULT_COST = CostModel()

#: Cost multipliers every result must survive. 2x is the acceptance bar.
COST_STRESS_FACTORS: tuple[float, ...] = (1.0, 2.0, 3.0)


# --------------------------------------------------------------------------- #
# backtest / validation
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class BacktestConfig:
    """Execution assumptions. These encode the A-share trading frictions."""

    initial_capital: float = 500_000.0
    #: "open" or "vwap". Signals are formed on T's close and executed on T+1.
    execution_price: str = "open"
    #: Limit bands used to decide whether an order could actually fill.
    limit_pct_main: float = 0.10
    limit_pct_st: float = 0.05
    #: T+1: shares bought today cannot be sold today.
    t_plus_one: bool = True
    #: A name trading below this fraction of its limit price cannot be bought.
    limit_tolerance: float = 0.002


@dataclass(frozen=True)
class ValidationConfig:
    """Walk-forward windows and the acceptance gates."""

    start_date: str = "2010-01-01"
    end_date: str = "2025-12-31"
    train_years: int = 3
    test_years: int = 1
    #: Fraction of a training window dropped between train and test to kill leakage.
    embargo_days: int = 10

    min_annualized_excess: float = 0.10
    min_information_ratio: float = 0.80
    max_excess_drawdown: float = 0.15
    max_absolute_drawdown: float = 0.25
    min_positive_rolling_12m_share: float = 0.70
    min_t_stat: float = 2.0
    max_annual_one_way_turnover: float = 25.0


BACKTEST = BacktestConfig()
VALIDATION = ValidationConfig()
RULES = UniverseRules()

#: Benchmark used for excess return. 000300 = 沪深300. Use the total-return series
#: when available; otherwise the price index understates the bar we must clear.
BENCHMARK_CODE = "sh.000300"
BENCHMARK_ALTERNATIVES: tuple[str, ...] = ("sh.000905", "sz.399006")

#: Horizons (in trading days) this project targets, per the objective.
TARGET_HORIZONS: tuple[int, ...] = (1, 5, 10)


# --------------------------------------------------------------------------- #
# baostock field sets
# --------------------------------------------------------------------------- #

#: Full daily field set. Only valid for unadjusted queries (``adjustflag="3"``).
DAILY_FIELDS_UNADJUSTED: tuple[str, ...] = (
    "date",
    "code",
    "open",
    "high",
    "low",
    "close",
    "preclose",
    "volume",
    "amount",
    "turn",
    "pctChg",
    "tradestatus",
    "isST",
    "peTTM",
    "pbMRQ",
    "psTTM",
    "pcfNcfTTM",
)

#: Reduced set that adjusted (前/后复权) queries support.
DAILY_FIELDS_ADJUSTED: tuple[str, ...] = (
    "date",
    "code",
    "open",
    "high",
    "low",
    "close",
    "preclose",
    "volume",
    "amount",
)

#: Fallback ladder: baostock rejects the whole request when one field is invalid,
#: so each rung drops more of the optional fundamental columns.
DAILY_FIELD_LADDER: tuple[tuple[str, ...], ...] = (
    DAILY_FIELDS_UNADJUSTED,
    tuple(f for f in DAILY_FIELDS_UNADJUSTED if f not in {"pcfNcfTTM", "psTTM", "peTTM", "pbMRQ"}),
    tuple(f for f in DAILY_FIELDS_UNADJUSTED if f not in {"pcfNcfTTM", "psTTM", "peTTM", "pbMRQ", "isST"}),
    ("date", "code", "open", "high", "low", "close", "preclose", "volume", "amount"),
    ("date", "code", "open", "high", "low", "close", "volume"),
)

ADJUST_BACKWARD = "1"  # 后复权 -- the mode used for return computation
ADJUST_FORWARD = "2"   # 前复权
ADJUST_NONE = "3"      # 不复权 -- the mode used for limit/price-level checks
