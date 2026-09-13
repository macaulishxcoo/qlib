"""Phase B: an explicit daily A-share portfolio backtest engine.

Why not qlib's default backtester
---------------------------------
The prior experiments in this workspace ran on qlib's default execution and cost
assumptions. Three of those defaults are hostile to an honest answer on a
¥500,000 book:

1. **No minimum commission.** A-share commission has a ¥5 floor per order. With
   ¥500k spread over 60 names, a typical rebalancing order is ~¥1,700, so the
   floor makes the effective commission rate ~0.3% per side instead of the
   nominal 0.025% -- a 12x difference on that component. Any backtest without the
   floor understates costs badly.
2. **Optimistic fills.** A name that opens limit-up cannot be bought and one that
   opens limit-down cannot be sold. Ignoring this quietly turns losing trades
   into impossible ones.
3. **Turnover is a result, not a constraint.** At daily frequency, cost is the
   dominant term, so the engine reports turnover and its cost decomposition on
   every run.

Execution model
---------------
Signals formed at the close of day ``T`` are executed at the open of ``T+1``.
Shares bought on day ``d`` cannot be sold until day ``d+1`` (:term:`T+1`).
Valuation and fills use *backward-adjusted* prices so corporate actions are
neutral; limit detection uses *unadjusted* prices, which is what the exchange's
price band is actually defined on.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from .config import BACKTEST, DEFAULT_COST, BacktestConfig, CostModel
from .metrics import summarize

LOT_SIZE = 100


class PanelError(ValueError):
    """The panel is missing a column the engine needs."""


REQUIRED_FIELDS = (
    "adj_open",
    "adj_close",
    "open",
    "limit_up_price",
    "limit_down_price",
    "is_suspended",
    "investable",
)


@dataclass
class BacktestResult:
    """Everything a research decision needs from one simulation."""

    nav: pd.Series
    daily_returns: pd.Series
    benchmark_returns: pd.Series | None = None
    excess_returns: pd.Series | None = None
    benchmark_nav: pd.Series | None = None
    turnover: pd.Series = field(default_factory=lambda: pd.Series(dtype="float64"))
    costs: pd.DataFrame = field(default_factory=pd.DataFrame)
    trades: pd.DataFrame = field(default_factory=pd.DataFrame)
    weight_history: pd.DataFrame = field(default_factory=pd.DataFrame)
    stats: dict[str, float] = field(default_factory=dict)
    blocked: pd.DataFrame = field(default_factory=pd.DataFrame)

    @property
    def annual_turnover(self) -> float:
        """One-way turnover expressed as a multiple of NAV per year."""
        if self.turnover.empty:
            return float("nan")
        return float(self.turnover.sum() / len(self.turnover) * 244)

    def cost_summary(self) -> pd.Series:
        """Total CNY paid per cost component over the whole simulation."""
        if self.costs.empty:
            return pd.Series(dtype="float64")
        return self.costs.sum()


def prepare_wide(panel: pd.DataFrame) -> dict[str, pd.DataFrame]:
    """Pivot the long panel into per-field wide frames indexed by date."""
    missing = [name for name in REQUIRED_FIELDS if name not in panel.columns]
    if missing:
        raise PanelError(
            "panel is missing required columns: " + ", ".join(missing)
            + "\n  build it with cnquant.universe.prepare_panel() first"
        )

    frame = panel.drop_duplicates(subset=["date", "code"])
    wide: dict[str, pd.DataFrame] = {}
    for name in REQUIRED_FIELDS:
        wide[name] = frame.pivot(index="date", columns="code", values=name).sort_index()

    # Suspended names still need a valuation price; carry the last observation.
    wide["adj_open"] = wide["adj_open"].ffill()
    wide["adj_close"] = wide["adj_close"].ffill()
    return wide


def _commission(notional: float, cost: CostModel) -> float:
    if notional <= 0:
        return 0.0
    return max(notional * cost.commission_rate, cost.commission_min)


def _trade_cost(notional: float, side: str, cost: CostModel) -> dict[str, float]:
    """Per-order cost breakdown for one side of a trade."""
    if notional <= 0:
        return {"commission": 0.0, "stamp_duty": 0.0, "transfer_fee": 0.0, "total": 0.0}
    commission = _commission(notional, cost)
    stamp = notional * cost.stamp_duty_sell if side == "sell" else 0.0
    transfer = notional * cost.transfer_fee
    return {
        "commission": commission,
        "stamp_duty": stamp,
        "transfer_fee": transfer,
        "total": commission + stamp + transfer,
    }


def _affordable_shares(cash: float, price: float, cost: CostModel) -> int:
    """Largest whole-lot buy affordable from ``cash`` at ``price``, costs included."""
    if price <= 0 or cash <= 0:
        return 0
    effective = price * (1.0 + cost.slippage_one_way)
    # Solve for notional n such that n + commission(n) + transfer(n) <= cash.
    rate = cost.commission_rate + cost.transfer_fee
    # Try with the percentage commission first, then verify the ¥5 floor case.
    approx = cash / (effective * (1.0 + rate))
    lots = int(approx // LOT_SIZE)
    while lots > 0:
        notional = lots * LOT_SIZE * effective
        needed = notional + _commission(notional, cost) + notional * cost.transfer_fee
        if needed <= cash + 1e-9:
            return lots * LOT_SIZE
        lots -= 1
    return 0


def run_backtest(
    panel: pd.DataFrame,
    target_weights: pd.DataFrame,
    *,
    config: BacktestConfig = BACKTEST,
    cost: CostModel = DEFAULT_COST,
    benchmark_returns: pd.Series | None = None,
    rebalance_every: int = 1,
    wide: dict[str, pd.DataFrame] | None = None,
    collect_trades: bool = True,
) -> BacktestResult:
    """Simulate a long-only book that rebalances toward ``target_weights``.

    Parameters
    ----------
    panel
        Long panel from :func:`cnquant.universe.prepare_panel`.
    target_weights
        Wide frame (index = signal date, columns = code, values = target weight).
        A row is consumed on the *next* trading day's open. Rows summing to less
        than 1 leave the remainder in cash.

        Missing-data contract: ``NaN`` means "no opinion" and the whole row is
        skipped when it contains no valid entries; an explicit ``0.0`` means
        "exit this name". Conflating the two silently liquidates the book
        whenever a signal row comes back empty.
    rebalance_every
        Rebalance only every N trading days. A holding period of 5 or 10 is the
        single most effective turnover lever available and is applied on top of
        whatever the weight builder already does.
    """
    if rebalance_every < 1:
        raise ValueError("rebalance_every must be >= 1")

    wide = wide or prepare_wide(panel)
    dates = wide["adj_open"].index
    codes = wide["adj_open"].columns

    adj_open = wide["adj_open"].to_numpy(dtype="float64", copy=False)
    adj_close = wide["adj_close"].to_numpy(dtype="float64", copy=False)
    raw_open = wide["open"].to_numpy(dtype="float64", copy=False)
    limit_up = wide["limit_up_price"].to_numpy(dtype="float64", copy=False)
    limit_down = wide["limit_down_price"].to_numpy(dtype="float64", copy=False)
    suspended = wide["is_suspended"].fillna(True).to_numpy(dtype=bool)
    investable = wide["investable"].fillna(False).to_numpy(dtype=bool)

    weights_reindexed = target_weights.reindex(index=dates, columns=codes).astype("float64")
    weight_values = weights_reindexed.to_numpy(dtype="float64", copy=False)

    tolerance = config.limit_tolerance
    n_dates = len(dates)
    n_codes = len(codes)

    cash = float(config.initial_capital)
    shares = np.zeros(n_codes, dtype="float64")
    locked = np.zeros(n_codes, dtype="float64")  # bought on the previous day (T+1)

    nav_values = np.full(n_dates, np.nan)
    turnover_values = np.zeros(n_dates)
    cost_records: list[dict[str, float]] = []
    trade_records: list[dict[str, object]] = []
    blocked_records: list[dict[str, object]] = []
    weight_history = np.full((n_dates, n_codes), np.nan)

    for i in range(n_dates):
        price_open = adj_open[i]
        price_close = adj_close[i]

        # T+1: yesterday's purchases become sellable today.
        sellable = np.maximum(shares - locked, 0.0)
        locked = np.zeros(n_codes, dtype="float64")

        position_value_open = np.nansum(shares * np.nan_to_num(price_open, nan=0.0))
        portfolio_value_open = cash + position_value_open

        do_rebalance = (
            i > 0
            and portfolio_value_open > 0
            and (i % rebalance_every == 0)
        )

        day_costs = {"commission": 0.0, "stamp_duty": 0.0, "transfer_fee": 0.0, "total": 0.0}
        bought_notional = 0.0
        sold_notional = 0.0

        if do_rebalance:
            signal = weight_values[i - 1]
            valid_signal = np.isfinite(signal) & np.isfinite(price_open) & (price_open > 0)
            # An all-NaN row means "no opinion today": hold instead of liquidating.
            do_rebalance = bool(np.any(valid_signal))

        if do_rebalance:
            target_value = np.where(valid_signal, signal * portfolio_value_open, 0.0)
            target_shares = np.where(valid_signal, target_value / np.where(price_open > 0, price_open, np.nan), 0.0)
            target_shares = np.nan_to_num(target_shares, nan=0.0)
            # Only open or add to names inside the investable universe; existing
            # positions in names that fell out of it are still sold.
            target_shares = np.where(target_shares > shares, np.where(investable[i], target_shares, shares), target_shares)

            delta = target_shares - shares

            # ---- sells first, so the proceeds can fund the buys -------------
            sell_order = np.argsort(delta)  # most negative first
            for j in sell_order:
                want = -delta[j]
                if want <= 0:
                    break
                if not np.isfinite(price_open[j]) or price_open[j] <= 0:
                    continue
                if suspended[i, j]:
                    blocked_records.append({"date": dates[i], "code": codes[j], "side": "sell", "reason": "suspended"})
                    continue
                if np.isfinite(limit_down[i, j]) and raw_open[i, j] <= limit_down[i, j] * (1.0 + tolerance):
                    blocked_records.append({"date": dates[i], "code": codes[j], "side": "sell", "reason": "limit_down"})
                    continue
                quantity = min(want, sellable[j])
                # Selling down to a residual odd lot is allowed, but a partial
                # sell is done in whole lots.
                if quantity < shares[j] - 1e-9:
                    quantity = np.floor(quantity / LOT_SIZE) * LOT_SIZE
                if quantity <= 0:
                    continue
                price = price_open[j] * (1.0 - cost.slippage_one_way)
                notional = quantity * price
                fees = _trade_cost(notional, "sell", cost)
                cash += notional - fees["total"]
                shares[j] -= quantity
                for key in day_costs:
                    day_costs[key] += fees[key]
                sold_notional += notional
                if collect_trades:
                    trade_records.append(
                        {"date": dates[i], "code": codes[j], "side": "sell", "shares": -quantity,
                         "price": price, "notional": notional, "cost": fees["total"]}
                    )

            # ---- then buys, largest desired increase first ------------------
            buy_priority = np.argsort(-np.where(np.isfinite(delta), delta, 0.0))
            for j in buy_priority:
                want = delta[j]
                if want <= 0:
                    # Names are ordered by desired increase, but a name that is
                    # already at or above target can still appear here, so this
                    # must skip rather than stop scanning.
                    continue
                if not np.isfinite(price_open[j]) or price_open[j] <= 0:
                    continue
                if not investable[i, j]:
                    continue
                if suspended[i, j]:
                    blocked_records.append({"date": dates[i], "code": codes[j], "side": "buy", "reason": "suspended"})
                    continue
                if np.isfinite(limit_up[i, j]) and raw_open[i, j] >= limit_up[i, j] * (1.0 - tolerance):
                    blocked_records.append({"date": dates[i], "code": codes[j], "side": "buy", "reason": "limit_up"})
                    continue
                price = price_open[j] * (1.0 + cost.slippage_one_way)
                affordable = _affordable_shares(cash, price_open[j], cost)
                quantity = int(min(np.floor(want / LOT_SIZE) * LOT_SIZE, affordable))
                if quantity <= 0:
                    continue
                notional = quantity * price
                fees = _trade_cost(notional, "buy", cost)
                cash -= notional + fees["total"]
                shares[j] += quantity
                locked[j] += quantity
                for key in day_costs:
                    day_costs[key] += fees[key]
                bought_notional += notional
                if collect_trades:
                    trade_records.append(
                        {"date": dates[i], "code": codes[j], "side": "buy", "shares": quantity,
                         "price": price, "notional": notional, "cost": fees["total"]}
                    )

        position_value_close = np.nansum(shares * np.nan_to_num(price_close, nan=0.0))
        total_value = cash + position_value_close
        nav_values[i] = total_value

        # One-way turnover: half of the traded notional over the opening NAV.
        turnover_values[i] = (
            (bought_notional + sold_notional) / 2.0 / portfolio_value_open
            if portfolio_value_open > 0 else 0.0
        )
        cost_records.append({"date": dates[i], **day_costs})
        if total_value > 0:
            weight_history[i] = np.where(np.isfinite(price_close), shares * np.nan_to_num(price_close, nan=0.0) / total_value, np.nan)

    nav = pd.Series(nav_values, index=dates, name="nav")
    daily_returns = nav.pct_change().fillna(0.0)
    daily_returns.iloc[0] = nav.iloc[0] / config.initial_capital - 1.0
    daily_returns.name = "return"

    result = BacktestResult(
        nav=nav,
        daily_returns=daily_returns,
        turnover=pd.Series(turnover_values, index=dates, name="turnover"),
        costs=pd.DataFrame(cost_records).set_index("date"),
        trades=pd.DataFrame(trade_records) if trade_records else pd.DataFrame(
            columns=["date", "code", "side", "shares", "price", "notional", "cost"]
        ),
        weight_history=pd.DataFrame(weight_history, index=dates, columns=codes),
        blocked=pd.DataFrame(blocked_records) if blocked_records else pd.DataFrame(
            columns=["date", "code", "side", "reason"]
        ),
    )

    if benchmark_returns is not None:
        benchmark = pd.Series(benchmark_returns).reindex(dates)
        benchmark = benchmark.ffill().fillna(0.0)
        benchmark.name = "benchmark"
        result.benchmark_returns = benchmark
        result.benchmark_nav = (1.0 + benchmark).cumprod()
        result.excess_returns = (daily_returns - benchmark).rename("excess")

    result.stats = summarize(daily_returns, benchmark_returns=result.benchmark_returns)
    result.stats["annual_one_way_turnover"] = result.annual_turnover
    result.stats["total_cost_cny"] = float(result.costs["total"].sum())
    result.stats["total_cost_share_of_capital"] = (
        float(result.costs["total"].sum()) / config.initial_capital
    )
    return result
