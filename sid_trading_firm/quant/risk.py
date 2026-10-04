"""Risk and performance statistics on return series.

Conventions: returns are per period (daily by default, ``periods_per_year=252``);
sample statistics use ``ddof=1``; annual rates passed in (risk-free rate,
minimum acceptable return) are converted to per-period rates by simple division.
"""

from __future__ import annotations

import math

import numpy as np

from sid_trading_firm.quant.inputs import (
    NanPolicy,
    Values,
    align,
    check_positive_number,
    negligible,
    require_length,
    require_positive,
    to_series,
)
from sid_trading_firm.quant.result import Result

TRADING_DAYS = 252


def _returns(values: Values, name: str, nan_policy: NanPolicy, min_obs: int):
    series, problem, dropped = to_series(values, name, nan_policy=nan_policy)
    if problem is None:
        problem = require_length(series, max(2, min_obs), name)
    return series, problem, dropped


def realised_volatility(returns: Values, *, periods_per_year: int = TRADING_DAYS, annualise: bool = True,
                        min_obs: int = 2, nan_policy: NanPolicy = "reject") -> Result:
    """Sample standard deviation of returns, annualised by ``sqrt(periods_per_year)``.

    A series with no variation has a volatility of exactly zero; that is a valid
    answer, not a failure.
    """
    if problem := check_positive_number(periods_per_year, "periods_per_year"):
        return problem
    series, problem, dropped = _returns(returns, "returns", nan_policy, min_obs)
    if problem:
        return problem
    vol = float(series.std(ddof=1))
    if negligible(vol, series.abs().max()):
        vol = 0.0
    if annualise:
        vol *= math.sqrt(periods_per_year)
    return Result.of(vol, len(series), dropped=dropped, annualised=annualise)


def _paired(asset: Values, benchmark: Values, nan_policy: NanPolicy, min_obs: int):
    a, problem, dropped_a = to_series(asset, "asset returns", nan_policy=nan_policy)
    if problem:
        return None, problem, {}
    b, problem, dropped_b = to_series(benchmark, "benchmark returns", nan_policy=nan_policy)
    if problem:
        return None, problem, {}
    frame, problem, unmatched = align(a, b, ("asset returns", "benchmark returns"))
    if problem:
        return None, problem, {}
    details = {"dropped_missing": dropped_a + dropped_b, "unmatched_dates": unmatched}
    if len(frame) < max(2, min_obs):
        return None, Result.insufficient(
            f"needs at least {max(2, min_obs)} paired observations, got {len(frame)}", len(frame)), details
    return frame, None, details


def beta(asset_returns: Values, benchmark_returns: Values, *, min_obs: int = 2,
         nan_policy: NanPolicy = "reject") -> Result:
    """Sensitivity of the asset to the benchmark: ``cov(a, b) / var(b)``.

    Series with an index (dates) are paired on it; dates present in only one are
    left out and counted in ``details["unmatched_dates"]``. A benchmark with no
    variance makes beta undefined.
    """
    frame, problem, details = _paired(asset_returns, benchmark_returns, nan_policy, min_obs)
    if problem:
        return problem
    var_b = float(frame["b"].var(ddof=1))
    if negligible(var_b ** 0.5, frame["b"].abs().max()):
        return Result.undefined("benchmark returns have zero variance", len(frame))
    cov = float(frame["a"].cov(frame["b"], ddof=1))
    return Result.of(cov / var_b, len(frame), **details)


def correlation(asset_returns: Values, benchmark_returns: Values, *, min_obs: int = 2,
                nan_policy: NanPolicy = "reject") -> Result:
    """Pearson correlation; undefined when either series has zero variance."""
    frame, problem, details = _paired(asset_returns, benchmark_returns, nan_policy, min_obs)
    if problem:
        return problem
    if any(negligible(float(frame[c].std(ddof=1)), frame[c].abs().max()) for c in ("a", "b")):
        return Result.undefined("a series with zero variance has no correlation", len(frame))
    return Result.of(float(np.corrcoef(frame["a"], frame["b"])[0, 1]), len(frame), **details)


def max_drawdown(values: Values, *, nan_policy: NanPolicy = "reject") -> Result:
    """Largest peak-to-trough fall of a price or equity series, as a positive fraction.

    0.25 means a 25% fall from the running peak. ``details`` names the peak and
    trough positions (index labels).
    """
    series, problem, dropped = to_series(values, "values", nan_policy=nan_policy)
    if problem is None:
        problem = require_positive(series, "values") or require_length(series, 2, "values")
    if problem:
        return problem
    peaks = series.cummax()
    drawdowns = 1 - series / peaks
    trough = drawdowns.idxmax()
    depth = float(drawdowns.loc[trough])
    peak = series.loc[:trough].idxmax() if depth > 0 else trough
    return Result.of(depth, len(series), peak=peak, trough=trough, dropped=dropped)


def sharpe_ratio(returns: Values, *, risk_free_rate: float = 0.0, periods_per_year: int = TRADING_DAYS,
                 min_obs: int = 2, nan_policy: NanPolicy = "reject") -> Result:
    """Annualised Sharpe ratio: mean excess return over its standard deviation.

    Undefined (not infinite, not zero) when excess returns do not vary.
    """
    if problem := check_positive_number(periods_per_year, "periods_per_year"):
        return problem
    series, problem, dropped = _returns(returns, "returns", nan_policy, min_obs)
    if problem:
        return problem
    excess = series - risk_free_rate / periods_per_year
    sd = float(excess.std(ddof=1))
    if negligible(sd, excess.abs().max()):
        return Result.undefined("excess returns have zero variance", len(series))
    return Result.of(float(excess.mean()) / sd * math.sqrt(periods_per_year), len(series), dropped=dropped)


def sortino_ratio(returns: Values, *, minimum_acceptable_return: float = 0.0,
                  periods_per_year: int = TRADING_DAYS, min_obs: int = 2,
                  nan_policy: NanPolicy = "reject") -> Result:
    """Annualised Sortino ratio: mean return above the target over downside deviation.

    Downside deviation is ``sqrt(mean(min(r - target, 0)^2))`` over all periods.
    Undefined when no period fell below the target.
    """
    if problem := check_positive_number(periods_per_year, "periods_per_year"):
        return problem
    series, problem, dropped = _returns(returns, "returns", nan_policy, min_obs)
    if problem:
        return problem
    target = minimum_acceptable_return / periods_per_year
    shortfall = np.minimum(series.to_numpy() - target, 0.0)
    downside = math.sqrt(float(np.mean(shortfall ** 2)))
    if negligible(downside, series.abs().max(), target):
        return Result.undefined("no period fell below the target return (zero downside deviation)",
                                len(series))
    excess = float(series.mean()) - target
    return Result.of(excess / downside * math.sqrt(periods_per_year), len(series), dropped=dropped)
