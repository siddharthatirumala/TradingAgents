"""Period returns from a price series."""

from __future__ import annotations

import numpy as np

from sid_trading_firm.quant.inputs import (
    NanPolicy,
    Values,
    require_length,
    require_positive,
    to_series,
)
from sid_trading_firm.quant.result import SeriesResult


def _prices(prices: Values, nan_policy: NanPolicy):
    series, problem, _ = to_series(prices, "prices", nan_policy=nan_policy)
    if problem is None:
        problem = require_positive(series, "prices") or require_length(series, 2, "prices")
    return series, problem


def arithmetic_returns(prices: Values, *, nan_policy: NanPolicy = "reject") -> SeriesResult:
    """Simple returns ``p[t] / p[t-1] - 1``, one fewer than the prices, indexed by the later date."""
    series, problem = _prices(prices, nan_policy)
    if problem:
        return SeriesResult.from_result(problem)
    returns = (series / series.shift(1) - 1).iloc[1:]
    return SeriesResult.of(returns, len(returns))


def log_returns(prices: Values, *, nan_policy: NanPolicy = "reject") -> SeriesResult:
    """Continuously compounded returns ``ln(p[t] / p[t-1])``."""
    series, problem = _prices(prices, nan_policy)
    if problem:
        return SeriesResult.from_result(problem)
    returns = np.log(series / series.shift(1)).iloc[1:]
    return SeriesResult.of(returns, len(returns))
