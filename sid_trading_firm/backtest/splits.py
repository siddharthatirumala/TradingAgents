"""Train / validation / test separation and walk-forward evaluation.

Rules enforced here:
- Periods are chronological and never overlap; the test period comes last.
- In walk-forward, parameters for each window are chosen using a panel truncated at
  the end of that window's training period: test-period data does not exist during
  the choice. The chosen parameters then run, unchanged, on the following test window.
- The stitched out-of-sample record contains test windows only. In-sample results are
  reported separately and are never evidence of an edge on their own.
- Each test window starts from cash (no positions carried between windows), so one
  window's outcome cannot leak into the next; the stitched curve compounds them.
- Windows are validated where they enter the evaluation, whoever built them: each
  trains strictly before it tests, windows are in chronological order, test periods
  never overlap, and every period holds trading dates of the panel.
- If no parameter set has a finite objective on a window's training data, the whole
  walk-forward is refused (:class:`WalkForwardError`). Skipping that window would
  leave a gap in the out-of-sample record that hides exactly the periods where the
  selection failed, so no partial result is returned.
"""

from __future__ import annotations

import math
import numbers
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field, replace

import pandas as pd

from sid_trading_firm.backtest.data import PricePanel
from sid_trading_firm.backtest.engine import BacktestConfig, BacktestError, Strategy, run_backtest
from sid_trading_firm.backtest.metrics import PerformanceReport, evaluate
from sid_trading_firm.quant import (
    Result,
    arithmetic_returns,
    max_drawdown,
    realised_volatility,
    sharpe_ratio,
)


@dataclass(frozen=True)
class Period:
    start: pd.Timestamp
    end: pd.Timestamp

    def label(self) -> str:
        return f"{self.start.date()}..{self.end.date()}"


@dataclass(frozen=True)
class DateSplit:
    train: Period
    validation: Period
    test: Period


def chronological_split(calendar: pd.DatetimeIndex, train: float = 0.6, validation: float = 0.2) -> DateSplit:
    """Split trading dates by count into consecutive train, validation and test periods."""
    if not (0 < train < 1 and 0 < validation < 1 and train + validation < 1):
        raise BacktestError("train and validation must be fractions leaving room for a test period")
    n = len(calendar)
    a, b = int(n * train), int(n * (train + validation))
    if a < 2 or b - a < 2 or n - b < 2:
        raise BacktestError(f"{n} trading dates are too few for a {train}/{validation}/rest split")
    return DateSplit(Period(calendar[0], calendar[a - 1]), Period(calendar[a], calendar[b - 1]),
                     Period(calendar[b], calendar[-1]))


@dataclass(frozen=True)
class Window:
    train: Period
    test: Period


def walk_forward_windows(calendar: pd.DatetimeIndex, train_days: int, test_days: int,
                         step_days: int | None = None) -> list[Window]:
    """Rolling windows: train on ``train_days`` dates, then test on the next ``test_days``.

    The step defaults to ``test_days``, so test windows are consecutive and never overlap.
    """
    step = step_days or test_days
    if train_days < 2 or test_days < 2 or step < 1:
        raise BacktestError("train_days and test_days must be at least 2, step at least 1")
    if step < test_days:
        raise BacktestError("step_days shorter than test_days would make test windows overlap")
    windows, i = [], 0
    while i + train_days + test_days <= len(calendar):
        train = Period(calendar[i], calendar[i + train_days - 1])
        test = Period(calendar[i + train_days], calendar[i + train_days + test_days - 1])
        windows.append(Window(train, test))
        i += step
    if not windows:
        raise BacktestError(f"{len(calendar)} trading dates cannot hold one {train_days}+{test_days} window")
    return windows


class WalkForwardError(BacktestError):
    """A walk-forward evaluation that cannot produce a complete out-of-sample record."""


def validate_windows(windows: Sequence[Window], calendar: pd.DatetimeIndex) -> None:
    """Refuse windows that could leak test data into selection or double-count a period."""
    if not windows:
        raise WalkForwardError("no walk-forward windows")
    dates = set(calendar)
    previous: Window | None = None
    for i, w in enumerate(windows, start=1):
        label = f"window {i} (train {w.train.label()}, test {w.test.label()})"
        if not (w.train.start <= w.train.end < w.test.start <= w.test.end):
            raise WalkForwardError(f"{label}: periods must be ordered with training ending before testing starts")
        for name, period in (("train", w.train), ("test", w.test)):
            if period.start not in dates or period.end not in dates:
                raise WalkForwardError(f"{label}: {name} period does not start and end on trading dates of the panel")
            if len(calendar[(calendar >= period.start) & (calendar <= period.end)]) < 2:
                raise WalkForwardError(f"{label}: {name} period holds fewer than two trading dates")
        if previous is not None:
            if w.train.start < previous.train.start or w.test.start < previous.test.start:
                raise WalkForwardError(f"{label}: windows are not in chronological order")
            if w.test.start <= previous.test.end:
                raise WalkForwardError(f"{label}: test period overlaps the previous window's test period")
        previous = w


Objective = Callable[[PerformanceReport], float | None]


def sharpe_objective(report: PerformanceReport) -> float | None:
    return report.metrics["sharpe"].value


@dataclass
class WindowOutcome:
    window: Window
    chosen_params: Mapping | None
    train_scores: list[tuple[Mapping, float | None]]
    test_report: PerformanceReport | None
    note: str | None = None


@dataclass
class WalkForwardResult:
    outcomes: list[WindowOutcome]
    oos_equity: pd.Series
    oos_metrics: dict[str, Result] = field(default_factory=dict)


def walk_forward(panel: PricePanel, make_strategy: Callable[[Mapping], Strategy], param_grid: Sequence[Mapping],
                 config: BacktestConfig, windows: Sequence[Window], *, objective: Objective = sharpe_objective,
                 benchmark: str | None = None) -> WalkForwardResult:
    """Choose parameters on each training window, run them on its test window, stitch the tests."""
    if not param_grid:
        raise BacktestError("empty parameter grid")
    validate_windows(windows, panel.calendar())
    outcomes: list[WindowOutcome] = []
    pieces: list[pd.Series] = []
    for window in windows:
        visible = panel.truncated(window.train.end)          # test data does not exist here
        scores = []
        for params in param_grid:
            train_cfg = replace(config, start=str(window.train.start.date()), end=str(window.train.end.date()))
            report = evaluate(run_backtest(visible, make_strategy(params), train_cfg), visible, benchmark=benchmark)
            scores.append((dict(params), objective(report)))
        valid = [(p, float(s)) for p, s in scores if _finite_number(s)]
        if not valid:
            raise WalkForwardError(
                f"window train {window.train.label()} / test {window.test.label()}: no parameter set had a finite "
                f"objective on the training data (scores {[s for _, s in scores]}); refusing a walk-forward "
                "with a gap in its out-of-sample record")
        best_score = max(s for _, s in valid)
        chosen = next(p for p, s in valid if s == best_score)    # ties: first in grid order
        test_panel = panel.truncated(window.test.end)
        test_cfg = replace(config, start=str(window.test.start.date()), end=str(window.test.end.date()))
        test_result = run_backtest(test_panel, make_strategy(chosen), test_cfg)
        outcomes.append(WindowOutcome(window, chosen, scores,
                                      evaluate(test_result, test_panel, benchmark=benchmark)))
        pieces.append(test_result.equity / test_result.equity.iloc[0])

    oos = _stitch(pieces, config.initial_cash)
    metrics: dict[str, Result] = {}
    if len(oos) >= 2:
        r = arithmetic_returns(oos)
        metrics["total_return"] = Result.of(float(oos.iloc[-1] / oos.iloc[0] - 1), len(oos))
        metrics["volatility"] = realised_volatility(r.values) if r.ok else Result.insufficient("no returns")
        metrics["sharpe"] = sharpe_ratio(r.values) if r.ok else Result.insufficient("no returns")
        metrics["max_drawdown"] = max_drawdown(oos)
    else:
        metrics["total_return"] = Result.insufficient("no test window produced results")
    return WalkForwardResult(outcomes, oos, metrics)


def _finite_number(value) -> bool:
    if isinstance(value, bool) or not isinstance(value, numbers.Real):
        return False
    return math.isfinite(value)


def _stitch(pieces: list[pd.Series], start_value: float) -> pd.Series:
    level, parts = start_value, []
    for piece in pieces:
        scaled = piece * level
        parts.append(scaled)
        level = float(scaled.iloc[-1])
    return pd.concat(parts) if parts else pd.Series(dtype=float)
