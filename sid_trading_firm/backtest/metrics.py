"""Performance of a backtest, computed deterministically from its equity curve and trades.

Every figure is a ``quant.Result`` with an explicit status: a ratio that cannot be
computed (no losing trades for a profit factor, a flat equity curve for a Sharpe
ratio) is reported as undefined, never as zero or infinity.

Regime analysis labels each day by the benchmark's position against its own moving
average as known at the *previous* close, so the label never uses the day it
describes.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

import pandas as pd

from sid_trading_firm.backtest.data import PricePanel
from sid_trading_firm.backtest.engine import BacktestResult
from sid_trading_firm.quant import (
    Result,
    arithmetic_returns,
    beta,
    correlation,
    max_drawdown,
    realised_volatility,
    sharpe_ratio,
    sma,
    sortino_ratio,
)

TRADING_DAYS = 252


@dataclass
class PerformanceReport:
    strategy: str
    data_fingerprint: str
    start: pd.Timestamp
    end: pd.Timestamp
    trading_days: int
    metrics: dict[str, Result]
    regimes: dict[str, dict[str, float | int | None]] = field(default_factory=dict)
    benchmark: str | None = None

    def value(self, name: str) -> float | None:
        return self.metrics[name].value

    def as_dict(self) -> dict:
        return {
            "strategy": self.strategy, "data_fingerprint": self.data_fingerprint,
            "start": str(self.start.date()), "end": str(self.end.date()), "trading_days": self.trading_days,
            "benchmark": self.benchmark,
            "metrics": {k: {"value": r.value, "status": r.status.value, "reason": r.reason}
                        for k, r in self.metrics.items()},
            "regimes": self.regimes,
        }


def _total_return(series: pd.Series) -> Result:
    if len(series) < 2:
        return Result.insufficient("needs at least two points", len(series))
    return Result.of(float(series.iloc[-1] / series.iloc[0] - 1), len(series))


def _annualise(total: Result, periods: int, periods_per_year: int) -> Result:
    if not total.ok:
        return total
    years = periods / periods_per_year
    if years <= 0:
        return Result.insufficient("no elapsed periods", periods)
    if total.value <= -1:
        return Result.undefined("the equity was wiped out", periods)
    return Result.of((1 + total.value) ** (1 / years) - 1, periods)


def _trade_stats(result: BacktestResult) -> dict[str, Result]:
    pnls = [t.pnl for t in result.trades]
    n = len(pnls)
    stats: dict[str, Result] = {"trade_count": Result.of(float(n), n)}
    if n == 0:
        reason = "no closed trades"
        for name in ("win_rate", "profit_factor", "expectancy", "average_trade_return"):
            stats[name] = Result.insufficient(reason)
        return stats
    wins = [p for p in pnls if p > 0]
    losses = [-p for p in pnls if p < 0]
    stats["win_rate"] = Result.of(len(wins) / n, n)
    stats["profit_factor"] = (Result.of(sum(wins) / sum(losses), n) if losses
                              else Result.undefined("no losing trades: profit factor has no denominator", n))
    stats["expectancy"] = Result.of(sum(pnls) / n, n, unit="currency per trade")
    stats["average_trade_return"] = Result.of(sum(t.return_pct for t in result.trades) / n, n)
    return stats


def _regimes(strategy_returns: pd.Series, benchmark_close: pd.Series, window: int,
             periods_per_year: int) -> dict[str, dict]:
    trend = sma(benchmark_close, window)
    if not trend.ok:
        return {"unknown": {"days": int(len(strategy_returns)), "note": trend.reason}}
    label = pd.Series("unknown", index=benchmark_close.index)
    known = trend.values.notna()
    label[known & (benchmark_close >= trend.values)] = "above_trend"
    label[known & (benchmark_close < trend.values)] = "below_trend"
    # A day's return belongs to the regime known at the previous close.
    previous = label.shift(1).reindex(strategy_returns.index).fillna("unknown")
    out = {}
    for regime in ("above_trend", "below_trend", "unknown"):
        r = strategy_returns[previous == regime]
        if r.empty:
            continue
        compounded = float((1 + r).prod() - 1)
        out[regime] = {
            "days": int(len(r)),
            "compounded_return": compounded,
            "mean_daily_return": float(r.mean()),
            "annualised_return": (float((1 + compounded) ** (periods_per_year / len(r)) - 1)
                                  if compounded > -1 else None),
        }
    return out


def evaluate(result: BacktestResult, panel: PricePanel, *, benchmark: str | None = None,
             risk_free_rate: float = 0.0, periods_per_year: int = TRADING_DAYS,
             regime_window: int = 200) -> PerformanceReport:
    equity = result.equity.astype(float)
    returns = arithmetic_returns(equity)
    daily = returns.values if returns.ok else pd.Series(dtype=float)
    metrics: dict[str, Result] = {}
    total = _total_return(equity)
    metrics["total_return"] = total
    metrics["annualised_return"] = _annualise(total, len(equity) - 1, periods_per_year)
    metrics["volatility"] = realised_volatility(daily, periods_per_year=periods_per_year)
    metrics["sharpe"] = sharpe_ratio(daily, risk_free_rate=risk_free_rate, periods_per_year=periods_per_year)
    metrics["sortino"] = sortino_ratio(daily, minimum_acceptable_return=risk_free_rate,
                                       periods_per_year=periods_per_year)
    metrics["max_drawdown"] = max_drawdown(equity)
    invested = (equity - result.cash.reindex(equity.index)) / equity
    metrics["average_exposure"] = Result.of(float(invested.mean()), len(invested))
    mean_equity = float(equity.mean())
    years = (len(equity) - 1) / periods_per_year
    metrics["turnover"] = (Result.of(result.traded_value / mean_equity / years, len(equity),
                                     unit="traded value / average equity per year")
                           if years > 0 else Result.insufficient("no elapsed periods"))
    metrics["total_commission"] = Result.of(result.total_commission, len(result.fills))
    metrics["total_slippage"] = Result.of(result.total_slippage, len(result.fills))
    metrics.update(_trade_stats(result))

    regimes: dict = {}
    if benchmark is not None:
        if benchmark.upper() not in panel.frames:
            raise ValueError(f"benchmark {benchmark!r} is not in the price panel")
        bench_all = panel.frames[benchmark.upper()]["close"]
        bench = bench_all.reindex(equity.index).ffill()
        if bench.isna().any():
            metrics["benchmark_return"] = Result.insufficient("benchmark has no price at the start of the window")
        else:
            metrics["benchmark_return"] = _total_return(bench)
            if total.ok and metrics["benchmark_return"].ok:
                metrics["excess_return"] = Result.of(total.value - metrics["benchmark_return"].value, len(equity))
            bench_returns = arithmetic_returns(bench)
            if returns.ok and bench_returns.ok:
                metrics["beta"] = beta(daily, bench_returns.values)
                metrics["correlation"] = correlation(daily, bench_returns.values)
        if returns.ok:
            regimes = _regimes(daily, bench_all.loc[: equity.index[-1]], regime_window, periods_per_year)

    for name, value in list(metrics.items()):
        if value.ok and not math.isfinite(value.value):
            metrics[name] = Result.invalid(f"{name} is not finite")
    return PerformanceReport(result.strategy, result.data_fingerprint, equity.index[0], equity.index[-1],
                             len(equity), metrics, regimes, benchmark.upper() if benchmark else None)
