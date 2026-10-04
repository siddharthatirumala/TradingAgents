"""Expected value of an outcome distribution, and per-trade expectancy."""

from __future__ import annotations

import math
from collections.abc import Sequence

from sid_trading_firm.quant.inputs import check_positive_number
from sid_trading_firm.quant.result import Result

PROBABILITY_TOLERANCE = 1e-9


def expected_value(payoffs: Sequence[float], probabilities: Sequence[float]) -> Result:
    """``sum(p * x)`` over outcomes. Probabilities must be in [0, 1] and sum to 1."""
    if len(payoffs) != len(probabilities):
        return Result.invalid(f"{len(payoffs)} payoffs but {len(probabilities)} probabilities")
    if not payoffs:
        return Result.insufficient("no outcomes")
    values = [float(x) for x in payoffs]
    probs = [float(p) for p in probabilities]
    if not all(math.isfinite(v) for v in values + probs):
        return Result.invalid("payoffs and probabilities must be finite", len(values))
    if any(p < 0 or p > 1 for p in probs):
        return Result.invalid("probabilities must lie in [0, 1]", len(values))
    total = math.fsum(probs)
    if abs(total - 1) > PROBABILITY_TOLERANCE:
        return Result.invalid(f"probabilities sum to {total}, not 1", len(values))
    return Result.of(math.fsum(p * x for p, x in zip(probs, values, strict=True)), len(values))


def trade_expectancy(win_rate: float, average_win: float, average_loss: float) -> Result:
    """Expected result per trade: ``win_rate * average_win - (1 - win_rate) * average_loss``.

    ``average_loss`` is a positive magnitude (a typical loss of 2% is 0.02).
    """
    try:
        p = float(win_rate)
    except (TypeError, ValueError):
        return Result.invalid(f"win_rate must be a number, got {win_rate!r}")
    if not math.isfinite(p) or not 0 <= p <= 1:
        return Result.invalid(f"win_rate must lie in [0, 1], got {win_rate!r}")
    for value, name in ((average_win, "average_win"), (average_loss, "average_loss")):
        if problem := check_positive_number(value, name, allow_zero=True):
            return problem
    return Result.of(p * float(average_win) - (1 - p) * float(average_loss), 1)
