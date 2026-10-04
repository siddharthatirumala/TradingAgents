"""Technical indicators, computed here rather than described by a model.

Warm-up points (before a full window exists) are NaN in an OK series. EMA, RSI
and ATR are seeded with a simple average of their first window, then smoothed:
EMA with ``alpha = 2 / (window + 1)``, RSI and ATR with Wilder's
``alpha = 1 / window``.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from sid_trading_firm.quant.inputs import (
    NanPolicy,
    Values,
    check_window,
    require_length,
    require_positive,
    to_series,
)
from sid_trading_firm.quant.result import SeriesResult


def _input(values: Values, name: str, window: int, minimum: int, nan_policy: NanPolicy):
    if problem := check_window(window):
        return None, problem
    series, problem, _ = to_series(values, name, nan_policy=nan_policy)
    if problem is None:
        problem = require_length(series, minimum, name)
    return series, problem


def _seeded_smoothing(values: np.ndarray, window: int, alpha: float, start: int) -> np.ndarray:
    """Seed with the mean of ``values[start:start+window]``, then exponentially smooth."""
    out = np.full(len(values), np.nan)
    seed_at = start + window - 1
    out[seed_at] = values[start:seed_at + 1].mean()
    for i in range(seed_at + 1, len(values)):
        out[i] = alpha * values[i] + (1 - alpha) * out[i - 1]
    return out


def sma(values: Values, window: int, *, nan_policy: NanPolicy = "reject") -> SeriesResult:
    """Simple moving average over ``window`` points."""
    series, problem = _input(values, "values", window, window, nan_policy)
    if problem:
        return SeriesResult.from_result(problem)
    return SeriesResult.of(series.rolling(window).mean(), len(series))


def ema(values: Values, window: int, *, nan_policy: NanPolicy = "reject") -> SeriesResult:
    """Exponential moving average, seeded with the SMA of the first ``window`` points."""
    series, problem = _input(values, "values", window, window, nan_policy)
    if problem:
        return SeriesResult.from_result(problem)
    out = _seeded_smoothing(series.to_numpy(), window, 2 / (window + 1), 0)
    return SeriesResult.of(pd.Series(out, index=series.index), len(series))


def rsi(close: Values, window: int = 14, *, nan_policy: NanPolicy = "reject") -> SeriesResult:
    """Wilder's Relative Strength Index, 0-100.

    100 when the window had gains and no losses, 0 for losses and no gains, and
    NaN (undefined) when prices did not move at all.
    """
    series, problem = _input(close, "close", window, window + 1, nan_policy)
    if problem:
        return SeriesResult.from_result(problem)
    change = np.diff(series.to_numpy(), prepend=np.nan)
    gains = np.where(change > 0, change, 0.0)
    losses = np.where(change < 0, -change, 0.0)
    avg_gain = _seeded_smoothing(gains, window, 1 / window, 1)
    avg_loss = _seeded_smoothing(losses, window, 1 / window, 1)
    with np.errstate(divide="ignore", invalid="ignore"):
        out = 100 - 100 / (1 + avg_gain / avg_loss)
    out = np.where((avg_loss == 0) & (avg_gain > 0), 100.0, out)
    out = np.where((avg_loss == 0) & (avg_gain == 0), np.nan, out)
    return SeriesResult.of(pd.Series(out, index=series.index), len(series))


def atr(high: Values, low: Values, close: Values, window: int = 14, *,
        nan_policy: NanPolicy = "reject") -> SeriesResult:
    """Wilder's Average True Range.

    True range uses the previous close, so the first ATR is the mean of the
    true ranges of bars 1..window and needs ``window + 1`` bars.
    """
    if problem := check_window(window):
        return SeriesResult.from_result(problem)
    parts = {}
    for name, values in (("high", high), ("low", low), ("close", close)):
        series, problem, _ = to_series(values, name, nan_policy=nan_policy)
        if problem is None:
            problem = require_positive(series, name)
        if problem:
            return SeriesResult.from_result(problem)
        parts[name] = series
    frame = pd.concat(parts, axis=1, join="inner")
    if len(frame) != len(parts["high"]) or len(frame) != len(parts["close"]):
        return SeriesResult.invalid("high, low and close must cover the same bars")
    if (frame["high"] < frame["low"]).any():
        return SeriesResult.invalid("high is below low on some bars", len(frame))
    if ((frame["close"] > frame["high"]) | (frame["close"] < frame["low"])).any():
        return SeriesResult.invalid("close lies outside the high-low range on some bars", len(frame))
    if problem := require_length(frame["close"], window + 1, "bars"):
        return SeriesResult.from_result(problem)
    prev_close = frame["close"].shift(1)
    true_range = pd.concat([frame["high"] - frame["low"], (frame["high"] - prev_close).abs(),
                            (frame["low"] - prev_close).abs()], axis=1).max(axis=1, skipna=False)
    out = _seeded_smoothing(true_range.to_numpy(), window, 1 / window, 1)
    return SeriesResult.of(pd.Series(out, index=frame.index), len(frame))
