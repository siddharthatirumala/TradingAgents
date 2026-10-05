"""The walk-forward out-of-sample record against a benchmark, and its equity curves.

The stitched out-of-sample curve compounds test windows, each starting from cash. The
benchmark is stitched the same way: over each test window it is held from that
window's first date, normalised, and compounded across windows. Strategy and
benchmark therefore cover exactly the same dates and the same window boundaries, and
the relative metrics compare like with like.
"""

from __future__ import annotations

from collections.abc import Sequence

import pandas as pd

from sid_trading_firm.backtest.data import PricePanel
from sid_trading_firm.backtest.splits import Period
from sid_trading_firm.quant import Result, arithmetic_returns, beta, correlation


def window_slices(oos_equity: pd.Series, periods: Sequence[Period]) -> list[pd.Series]:
    """The stitched curve cut back into its test windows (in order, non-empty)."""
    pieces = [oos_equity[(oos_equity.index >= p.start) & (oos_equity.index <= p.end)] for p in periods]
    return [p for p in pieces if not p.empty]


def window_equity(oos_slice: pd.Series, initial_cash: float) -> pd.Series:
    """A test window's own equity curve, recovered from its slice of the stitched curve.

    Each window starts from cash, so its first point is ``initial_cash``; the stitched
    slice is the same curve scaled by the level reached before the window.
    """
    return oos_slice / float(oos_slice.iloc[0]) * initial_cash


def stitched_benchmark(panel: PricePanel, benchmark: str, oos_equity: pd.Series,
                       periods: Sequence[Period]) -> pd.Series | None:
    """The benchmark held over the same test windows and compounded like the strategy; None if unpriced."""
    closes = panel.frames[benchmark.upper()]["close"]
    level, parts = float(oos_equity.iloc[0]), []
    for piece in window_slices(oos_equity, periods):
        bench = closes.reindex(piece.index).ffill()
        if bench.isna().any():
            return None
        scaled = bench / float(bench.iloc[0]) * level
        parts.append(scaled)
        level = float(scaled.iloc[-1])
    return pd.concat(parts) if parts else None


def relative_metrics(oos_equity: pd.Series, bench_equity: pd.Series | None) -> dict[str, Result]:
    """Benchmark return, excess return, beta and correlation of the stitched out-of-sample record."""
    n = len(oos_equity)
    if bench_equity is None:
        reason = "the benchmark has no price at the start of a test window"
        return {k: Result.insufficient(reason, n) for k in ("benchmark_return", "excess_return", "beta",
                                                             "correlation")}
    if len(oos_equity) < 2:
        return {k: Result.insufficient("needs at least two out-of-sample points", n)
                for k in ("benchmark_return", "excess_return", "beta", "correlation")}
    strategy_total = float(oos_equity.iloc[-1] / oos_equity.iloc[0] - 1)
    bench_total = float(bench_equity.iloc[-1] / bench_equity.iloc[0] - 1)
    out = {"benchmark_return": Result.of(bench_total, n), "excess_return": Result.of(strategy_total - bench_total, n)}
    s, b = arithmetic_returns(oos_equity), arithmetic_returns(bench_equity)
    if s.ok and b.ok:
        out["beta"] = beta(s.values, b.values)
        out["correlation"] = correlation(s.values, b.values)
    else:
        out["beta"] = out["correlation"] = Result.insufficient("returns could not be computed", n)
    return out


def curve_dict(series: pd.Series) -> dict[str, list]:
    """A JSON-serialisable equity curve: ISO dates and values."""
    return {"dates": [str(d.date()) for d in series.index], "values": [float(v) for v in series.to_numpy()]}
