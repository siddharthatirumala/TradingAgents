"""Volatility-based position sizing, as research infrastructure.

These functions compute what a position *would* be under a sizing rule. They
never create, submit or imply an order: nothing here knows about brokers, and a
size only becomes a trade after the approval pipeline and the hard risk engine
(later phases). The cap (``max_weight``) is a required argument because no
default risk limit has been chosen.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from sid_trading_firm.quant.inputs import check_positive_number
from sid_trading_firm.quant.result import Result, Status


@dataclass(frozen=True)
class PositionSize:
    status: Status
    shares: int | None = None
    notional: float | None = None
    weight: float | None = None          # notional / equity
    capped_by: str | None = None         # "max_weight" when the cap bound the size
    method: str | None = None
    reason: str | None = None

    @property
    def ok(self) -> bool:
        return self.status is Status.OK


def _fail(result: Result) -> PositionSize:
    return PositionSize(result.status, reason=result.reason)


def _check(equity: float, price: float, max_weight: float) -> PositionSize | None:
    for value, name in ((equity, "equity"), (price, "price"), (max_weight, "max_weight")):
        if problem := check_positive_number(value, name):
            return _fail(problem)
    if max_weight > 1:
        return _fail(Result.invalid(f"max_weight is a fraction of equity (0-1], got {max_weight}"))
    return None


def _size(equity: float, price: float, weight: float, max_weight: float, method: str) -> PositionSize:
    capped = weight > max_weight
    weight = min(weight, max_weight)
    shares = math.floor(equity * weight / price)
    notional = shares * price
    return PositionSize(Status.OK, shares, notional, notional / equity,
                        "max_weight" if capped else None, method)


def volatility_target_size(equity: float, price: float, annualised_volatility: float,
                           target_volatility: float, max_weight: float) -> PositionSize:
    """Weight = target volatility / asset volatility, capped at ``max_weight``; whole shares."""
    if failed := _check(equity, price, max_weight):
        return failed
    if problem := check_positive_number(target_volatility, "target_volatility"):
        return _fail(problem)
    if problem := check_positive_number(annualised_volatility, "annualised_volatility", allow_zero=True):
        return _fail(problem)
    if annualised_volatility == 0:
        return _fail(Result.undefined("asset volatility is zero; a volatility target cannot size it"))
    return _size(equity, price, target_volatility / annualised_volatility, max_weight, "volatility_target")


def atr_risk_size(equity: float, price: float, atr: float, risk_fraction: float, atr_multiple: float,
                  max_weight: float) -> PositionSize:
    """Size so a stop ``atr_multiple`` ATRs away loses ``risk_fraction`` of equity; capped; whole shares."""
    if failed := _check(equity, price, max_weight):
        return failed
    for value, name in ((risk_fraction, "risk_fraction"), (atr_multiple, "atr_multiple")):
        if problem := check_positive_number(value, name):
            return _fail(problem)
    if risk_fraction > 1:
        return _fail(Result.invalid(f"risk_fraction is a fraction of equity (0-1], got {risk_fraction}"))
    if problem := check_positive_number(atr, "atr", allow_zero=True):
        return _fail(problem)
    if atr == 0:
        return _fail(Result.undefined("ATR is zero; stop distance would be zero"))
    stop_distance = atr * atr_multiple
    weight = (equity * risk_fraction / stop_distance) * price / equity
    return _size(equity, price, weight, max_weight, "atr_risk")
