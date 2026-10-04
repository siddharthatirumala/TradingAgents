"""Simple transaction-cost and slippage models for research and backtesting.

Parameters are explicit and have no built-in "realistic" values: each strategy's
backtest configuration must state what it assumes.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from sid_trading_firm.quant.inputs import check_positive_number
from sid_trading_firm.quant.result import Result

Side = Literal["buy", "sell"]
BPS = 10_000


@dataclass(frozen=True)
class TransactionCostModel:
    """Commission: per share plus basis points of notional, with an optional minimum per order."""

    per_share: float = 0.0
    bps_of_notional: float = 0.0
    minimum_per_order: float = 0.0

    def cost(self, shares: float, price: float) -> Result:
        """Commission in currency for one order of ``shares`` at ``price``."""
        for value, name in ((self.per_share, "per_share"), (self.bps_of_notional, "bps_of_notional"),
                            (self.minimum_per_order, "minimum_per_order"), (shares, "shares")):
            if problem := check_positive_number(value, name, allow_zero=True):
                return problem
        if problem := check_positive_number(price, "price"):
            return problem
        if shares == 0:
            return Result.of(0.0, 1)
        commission = shares * self.per_share + shares * price * self.bps_of_notional / BPS
        return Result.of(max(commission, self.minimum_per_order), 1,
                         minimum_applied=commission < self.minimum_per_order)


@dataclass(frozen=True)
class SlippageModel:
    """Adverse price move on execution: half the quoted spread plus a market-impact allowance."""

    half_spread_bps: float = 0.0
    impact_bps: float = 0.0

    def fill_price(self, price: float, side: Side) -> Result:
        """The price a market order is assumed to fill at: higher for buys, lower for sells."""
        for value, name in ((self.half_spread_bps, "half_spread_bps"), (self.impact_bps, "impact_bps")):
            if problem := check_positive_number(value, name, allow_zero=True):
                return problem
        if problem := check_positive_number(price, "price"):
            return problem
        if side not in ("buy", "sell"):
            return Result.invalid(f"side must be 'buy' or 'sell', got {side!r}")
        move = (self.half_spread_bps + self.impact_bps) / BPS
        if side == "sell" and move >= 1:
            return Result.invalid("slippage of 100% or more on a sale is not a price")
        return Result.of(price * (1 + move) if side == "buy" else price * (1 - move), 1)

    def cost(self, price: float, shares: float, side: Side) -> Result:
        """Slippage in currency: the gap between quoted and assumed fill price, times shares."""
        if problem := check_positive_number(shares, "shares", allow_zero=True):
            return problem
        fill = self.fill_price(price, side)
        if not fill.ok:
            return fill
        return Result.of(abs(fill.value - price) * shares, 1)
