"""Results that say whether a calculation means anything.

A financial calculation can fail in ways a number hides: too little history, a
NaN in the input, a zero variance that makes a ratio undefined. Every function in
``sid_trading_firm.quant`` returns one of these instead of a bare float, so a
caller (and, through it, an agent) can tell "the Sharpe ratio is 0.0" from
"there is no Sharpe ratio". Nothing is turned into zero to keep a pipeline going.
"""

from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

import pandas as pd


class Status(StrEnum):
    OK = "ok"
    INSUFFICIENT_DATA = "insufficient_data"   # valid input, too little of it
    INVALID_INPUT = "invalid_input"           # NaN, infinities, non-positive prices, bad parameters
    UNDEFINED = "undefined"                   # mathematically undefined (e.g. zero variance)


class QuantError(ValueError):
    """Raised by ``require()`` when a result has no usable value."""


@dataclass(frozen=True)
class Result:
    """A scalar result. ``value`` is None unless ``status`` is OK."""

    value: float | None
    status: Status
    n_obs: int = 0
    reason: str | None = None
    details: Mapping[str, Any] = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        return self.status is Status.OK

    def require(self) -> float:
        if not self.ok:
            raise QuantError(f"{self.status.value}: {self.reason}")
        return self.value

    @classmethod
    def of(cls, value: float, n_obs: int, **details: Any) -> Result:
        if not math.isfinite(value):
            return cls.invalid(f"calculation produced a non-finite value ({value})", n_obs)
        return cls(float(value), Status.OK, n_obs, None, details)

    @classmethod
    def insufficient(cls, reason: str, n_obs: int = 0) -> Result:
        return cls(None, Status.INSUFFICIENT_DATA, n_obs, reason)

    @classmethod
    def invalid(cls, reason: str, n_obs: int = 0) -> Result:
        return cls(None, Status.INVALID_INPUT, n_obs, reason)

    @classmethod
    def undefined(cls, reason: str, n_obs: int = 0) -> Result:
        return cls(None, Status.UNDEFINED, n_obs, reason)


@dataclass(frozen=True)
class SeriesResult:
    """A series result. ``values`` is None unless ``status`` is OK.

    Within an OK series, NaN marks points where the measure is not yet defined
    (an indicator's warm-up) or undefined (an RSI over a perfectly flat window).
    """

    values: pd.Series | None
    status: Status
    n_obs: int = 0
    reason: str | None = None

    @property
    def ok(self) -> bool:
        return self.status is Status.OK

    def latest(self) -> Result:
        """The last point, as a scalar result."""
        if not self.ok:
            return Result(None, self.status, self.n_obs, self.reason)
        value = self.values.iloc[-1]
        if pd.isna(value):
            return Result.undefined("the latest point is undefined", self.n_obs)
        return Result.of(float(value), self.n_obs)

    @classmethod
    def of(cls, values: pd.Series, n_obs: int) -> SeriesResult:
        finite = values.dropna()
        if not finite.map(math.isfinite).all():
            return cls.invalid("calculation produced non-finite values", n_obs)
        return cls(values, Status.OK, n_obs)

    @classmethod
    def insufficient(cls, reason: str, n_obs: int = 0) -> SeriesResult:
        return cls(None, Status.INSUFFICIENT_DATA, n_obs, reason)

    @classmethod
    def invalid(cls, reason: str, n_obs: int = 0) -> SeriesResult:
        return cls(None, Status.INVALID_INPUT, n_obs, reason)

    @classmethod
    def from_result(cls, result: Result) -> SeriesResult:
        return cls(None, result.status, result.n_obs, result.reason)
