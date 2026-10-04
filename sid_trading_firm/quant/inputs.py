"""Input checks shared by the quant functions.

NaN policy: ``"reject"`` (the default) treats any missing value as invalid input,
because silently skipping gaps changes what a statistic means. ``"drop"`` removes
missing values first and reports how many were dropped. Infinities are always
invalid.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from typing import Literal

import numpy as np
import pandas as pd

from sid_trading_firm.quant.result import Result

NanPolicy = Literal["reject", "drop"]
Values = Sequence[float] | pd.Series | np.ndarray


def to_series(values: Values, name: str, *, nan_policy: NanPolicy = "reject") -> tuple[pd.Series | None, Result | None, int]:
    """``(series, problem, dropped)``: a float series, or the reason it cannot be used."""
    if nan_policy not in ("reject", "drop"):
        return None, Result.invalid(f"unknown nan_policy {nan_policy!r}"), 0
    try:
        series = values.astype(float) if isinstance(values, pd.Series) else pd.Series(values, dtype=float)
    except (TypeError, ValueError) as exc:
        return None, Result.invalid(f"{name} must be numeric ({exc})"), 0
    if np.isinf(series.to_numpy()).any():
        return None, Result.invalid(f"{name} contains infinite values", len(series)), 0
    missing = int(series.isna().sum())
    if missing:
        if nan_policy == "reject":
            return None, Result.invalid(f"{name} contains {missing} missing value(s)", len(series)), 0
        series = series.dropna()
    if series.empty:
        return None, Result.insufficient(f"{name} is empty"), missing
    return series, None, missing


def require_positive(series: pd.Series, name: str) -> Result | None:
    if (series <= 0).any():
        return Result.invalid(f"{name} must be positive; found {int((series <= 0).sum())} value(s) <= 0",
                              len(series))
    return None


def require_length(series: pd.Series, minimum: int, name: str) -> Result | None:
    if len(series) < minimum:
        return Result.insufficient(f"{name} needs at least {minimum} observations, got {len(series)}",
                                   len(series))
    return None


def check_window(window: int) -> Result | None:
    if isinstance(window, bool) or not isinstance(window, int) or window < 1:
        return Result.invalid(f"window must be a positive integer, got {window!r}")
    return None


def check_positive_number(value: float, name: str, *, allow_zero: bool = False) -> Result | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return Result.invalid(f"{name} must be a number, got {value!r}")
    if not math.isfinite(number):
        return Result.invalid(f"{name} must be finite, got {value!r}")
    if number < 0 or (number == 0 and not allow_zero):
        return Result.invalid(f"{name} must be {'non-negative' if allow_zero else 'positive'}, got {value!r}")
    return None


def align(a: pd.Series, b: pd.Series, names: tuple[str, str]) -> tuple[pd.DataFrame | None, Result | None, int]:
    """Pair two series: by index when both have one that matters, else by position.

    Returns ``(frame, problem, unmatched)`` where ``unmatched`` counts rows present
    in only one series (for example a date with no benchmark price).
    """
    positional = isinstance(a.index, pd.RangeIndex) and isinstance(b.index, pd.RangeIndex)
    if positional and len(a) != len(b):
        return None, Result.invalid(f"{names[0]} and {names[1]} have different lengths "
                                    f"({len(a)} vs {len(b)}) and no index to align them"), 0
    frame = pd.concat([a.rename("a"), b.rename("b")], axis=1, join="inner")
    unmatched = len(a) + len(b) - 2 * len(frame)
    return frame, None, unmatched


# Spreads this small relative to the data are floating-point noise, not variation:
# the standard deviation of ten identical returns of 0.01 comes out near 1e-18, and
# dividing by it would report a Sharpe ratio of about 1e17.
RELATIVE_ZERO = 1e-12


def negligible(spread: float, *scales: float) -> bool:
    """Whether ``spread`` is zero for practical purposes, relative to the data's magnitude."""
    scale = max((abs(x) for x in scales), default=0.0)
    return spread <= RELATIVE_ZERO * scale if scale > 0 else spread == 0
