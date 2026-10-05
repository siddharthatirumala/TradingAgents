"""The daily backtest simulator: decide at the close, fill at the next open.

Timeline for each trading date ``t`` in the calendar:

1. Orders decided at the close of the previous rebalance date execute at ``t``'s open:
   sells first (to free cash), then buys. Fill price = the open, moved against the
   trade by the slippage model; commission from the cost model. A buy is cut down to
   what cash can pay for, costs included; cash never goes negative.
2. The portfolio is marked to market at ``t``'s close (a symbol without a bar on ``t``
   is valued at its last close on or before ``t``).
3. If ``t`` is a rebalance date, the strategy receives a point-in-time view at ``t``
   and returns target weights. Shares are sized from ``t``'s closes and equity, and
   execute at the next date's open. The strategy never sees anything after ``t``.

Long-only, no leverage: weights must be finite, non-negative and sum to at most
``1 - cash_buffer``; each is capped at ``max_weight`` (caps are recorded). Whole
shares only. Orders that cannot execute (no bar at the execution date) are recorded
with the reason, never silently dropped.

This is research infrastructure: it simulates fills and never places an order.
"""

from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Literal, Protocol

import pandas as pd

from sid_trading_firm.backtest.data import PanelView, PricePanel
from sid_trading_firm.quant.costs import SlippageModel, TransactionCostModel

Rebalance = Literal["daily", "weekly", "monthly"]
WEIGHT_TOLERANCE = 1e-9


class BacktestError(ValueError):
    """A backtest that cannot run as specified (bad configuration or strategy output)."""


class Strategy(Protocol):
    """A deterministic strategy: target portfolio weights from a point-in-time view."""

    name: str
    version: str

    def target_weights(self, view: PanelView) -> Mapping[str, float]: ...


@dataclass(frozen=True)
class BacktestConfig:
    initial_cash: float
    max_weight: float
    costs: TransactionCostModel = field(default_factory=TransactionCostModel)
    slippage: SlippageModel = field(default_factory=SlippageModel)
    rebalance: Rebalance = "monthly"
    cash_buffer: float = 0.0
    start: str | None = None
    end: str | None = None

    def __post_init__(self) -> None:
        if not (math.isfinite(self.initial_cash) and self.initial_cash > 0):
            raise BacktestError("initial_cash must be a positive number")
        if not (0 < self.max_weight <= 1):
            raise BacktestError("max_weight must be in (0, 1]")
        if not (0 <= self.cash_buffer < 1):
            raise BacktestError("cash_buffer must be in [0, 1)")
        if self.rebalance not in ("daily", "weekly", "monthly"):
            raise BacktestError(f"unknown rebalance frequency {self.rebalance!r}")


@dataclass(frozen=True)
class Fill:
    date: pd.Timestamp
    symbol: str
    side: Literal["buy", "sell"]
    shares: int
    reference_price: float      # the open
    price: float                # after slippage
    commission: float
    slippage_cost: float
    decided_on: pd.Timestamp


@dataclass(frozen=True)
class RejectedOrder:
    date: pd.Timestamp
    symbol: str
    side: Literal["buy", "sell"]
    shares: int
    reason: str


@dataclass(frozen=True)
class Trade:
    """A closed position (or part of one), at average cost. P&L is net of both sides' costs."""

    symbol: str
    entry_date: pd.Timestamp
    exit_date: pd.Timestamp
    shares: int
    entry_cost_basis: float     # per share, including buy-side costs
    exit_price: float           # per share, after slippage
    pnl: float                  # net of sell-side commission

    @property
    def return_pct(self) -> float:
        return self.pnl / (self.entry_cost_basis * self.shares)


@dataclass
class BacktestResult:
    strategy: str
    config: BacktestConfig
    data_fingerprint: str
    equity: pd.Series
    cash: pd.Series
    fills: list[Fill]
    trades: list[Trade]
    rejected: list[RejectedOrder]
    capped: list[tuple[pd.Timestamp, str, float]]
    decisions: list[pd.Timestamp]
    open_positions: dict[str, int]

    @property
    def total_commission(self) -> float:
        return sum(f.commission for f in self.fills)

    @property
    def total_slippage(self) -> float:
        return sum(f.slippage_cost for f in self.fills)

    @property
    def traded_value(self) -> float:
        return sum(f.price * f.shares for f in self.fills)


def rebalance_dates(calendar: pd.DatetimeIndex, frequency: Rebalance) -> set[pd.Timestamp]:
    """Decision dates: the first date, then the last trading date of each period."""
    if len(calendar) == 0:
        return set()
    dates = {calendar[0]}
    if frequency == "daily":
        return set(calendar)
    for today, tomorrow in zip(calendar[:-1], calendar[1:], strict=True):
        if frequency == "monthly" and (today.year, today.month) != (tomorrow.year, tomorrow.month):
            dates.add(today)
        if frequency == "weekly" and today.isocalendar()[:2] != tomorrow.isocalendar()[:2]:
            dates.add(today)
    return dates


def _validate_weights(weights: Mapping[str, float], panel: PricePanel, config: BacktestConfig,
                      date: pd.Timestamp, capped: list) -> dict[str, float]:
    clean: dict[str, float] = {}
    for symbol, weight in weights.items():
        key = str(symbol).upper()
        if key not in panel.frames:
            raise BacktestError(f"{date.date()}: strategy weighted unknown symbol {symbol!r}")
        try:
            w = float(weight)
        except (TypeError, ValueError):
            raise BacktestError(f"{date.date()}: weight for {symbol} is not a number") from None
        if not math.isfinite(w) or w < 0:
            raise BacktestError(f"{date.date()}: weight for {symbol} must be finite and >= 0 (long-only), got {weight!r}")
        if w > config.max_weight + WEIGHT_TOLERANCE:
            capped.append((date, key, w))
            w = config.max_weight
        if w > 0:
            clean[key] = w
    total = sum(clean.values())
    if total > 1 - config.cash_buffer + WEIGHT_TOLERANCE:
        raise BacktestError(f"{date.date()}: weights sum to {total:.6f}, above {1 - config.cash_buffer:.6f} (no leverage)")
    return clean


def run_backtest(panel: PricePanel, strategy: Strategy, config: BacktestConfig) -> BacktestResult:
    calendar = panel.calendar()
    if config.start:
        calendar = calendar[calendar >= pd.Timestamp(config.start)]
    if config.end:
        calendar = calendar[calendar <= pd.Timestamp(config.end)]
    if len(calendar) < 2:
        raise BacktestError("the backtest window needs at least two trading dates")
    decide_on = rebalance_dates(calendar, config.rebalance)

    cash = float(config.initial_cash)
    shares: dict[str, int] = {}
    basis: dict[str, float] = {}              # average cost per share incl. buy costs
    opened: dict[str, pd.Timestamp] = {}
    fills: list[Fill] = []
    trades: list[Trade] = []
    rejected: list[RejectedOrder] = []
    capped: list = []
    decisions: list[pd.Timestamp] = []
    equity_points, cash_points = {}, {}
    pending: dict[str, int] | None = None
    pending_decided: pd.Timestamp | None = None

    for t in calendar:
        # 1. execute yesterday's decision at today's open
        if pending is not None:
            orders = sorted(pending.items(), key=lambda kv: (kv[1] > 0, kv[0]))   # sells first
            for symbol, delta in orders:
                side = "buy" if delta > 0 else "sell"
                bar = panel.bar_on(symbol, t)
                if bar is None:
                    rejected.append(RejectedOrder(t, symbol, side, abs(delta), "no bar at the execution date"))
                    continue
                fill_price = config.slippage.fill_price(float(bar["open"]), side).require()
                qty = abs(delta)
                if side == "buy":
                    # Largest whole number of shares cash can pay for, costs included.
                    while qty > 0 and qty * fill_price + config.costs.cost(qty, fill_price).require() > cash + 1e-9:
                        qty = min(qty - 1, math.floor(cash / fill_price))
                    if qty < abs(delta):
                        rejected.append(RejectedOrder(t, symbol, side, abs(delta) - qty, "insufficient cash"))
                    if qty == 0:
                        continue
                commission = config.costs.cost(qty, fill_price).require()
                slip = abs(fill_price - float(bar["open"])) * qty
                fills.append(Fill(t, symbol, side, qty, float(bar["open"]), fill_price, commission, slip,
                                  pending_decided))
                if side == "buy":
                    held = shares.get(symbol, 0)
                    total_cost = qty * fill_price + commission
                    basis[symbol] = (basis.get(symbol, 0.0) * held + total_cost) / (held + qty)
                    shares[symbol] = held + qty
                    opened.setdefault(symbol, t)
                    cash -= total_cost
                else:
                    held = shares.get(symbol, 0)
                    qty = min(qty, held)
                    proceeds = qty * fill_price - commission
                    trades.append(Trade(symbol, opened[symbol], t, qty, basis[symbol], fill_price,
                                        proceeds - basis[symbol] * qty))
                    cash += proceeds
                    shares[symbol] = held - qty
                    if shares[symbol] == 0:
                        del shares[symbol], basis[symbol], opened[symbol]
            pending = None
        if cash < -1e-6:
            raise BacktestError(f"{t.date()}: cash went negative ({cash:.2f}); this is a simulator bug")

        # 2. mark to market at today's close
        view = panel.view(t)
        closes = {}
        for symbol in shares:
            last = view.last_bar(symbol)
            closes[symbol] = float(last["close"])
        equity = cash + sum(shares[s] * closes[s] for s in shares)
        equity_points[t], cash_points[t] = equity, cash

        # 3. decide at today's close; execute at the next date's open
        if t in decide_on and t != calendar[-1]:
            decisions.append(t)
            weights = _validate_weights(strategy.target_weights(panel.view(t)), panel, config, t, capped)
            targets: dict[str, int] = {}
            for symbol in set(weights) | set(shares):
                bar = view.last_bar(symbol)
                if bar is None:
                    if weights.get(symbol, 0) > 0:
                        rejected.append(RejectedOrder(t, symbol, "buy", 0, "no price at the decision date"))
                    continue
                price = float(bar["close"])
                want = math.floor(weights.get(symbol, 0.0) * equity / price)
                delta = want - shares.get(symbol, 0)
                if delta:
                    targets[symbol] = delta
            pending, pending_decided = (targets or None), t

    return BacktestResult(
        strategy=f"{strategy.name}_{strategy.version}", config=config, data_fingerprint=panel.fingerprint(),
        equity=pd.Series(equity_points, name="equity"), cash=pd.Series(cash_points, name="cash"),
        fills=fills, trades=trades, rejected=rejected, capped=capped, decisions=decisions,
        open_positions=dict(shares),
    )
