"""Train/validation/test splits and walk-forward: separation and leakage guarantees."""

import numpy as np
import pandas as pd
import pytest

from sid_trading_firm.backtest.data import PricePanel
from sid_trading_firm.backtest.engine import BacktestConfig, BacktestError
from sid_trading_firm.backtest.splits import (
    Period,
    WalkForwardError,
    Window,
    chronological_split,
    validate_windows,
    walk_forward,
    walk_forward_windows,
)

pytestmark = pytest.mark.unit


def frame(closes, start="2025-01-01"):
    dates = pd.bdate_range(start, periods=len(closes))
    return pd.DataFrame({"date": dates, "open": closes, "high": [c * 1.01 for c in closes],
                         "low": [c * 0.99 for c in closes], "close": closes, "volume": 1e6})


def trending_panel(n=120):
    rng = np.random.default_rng(7)                 # fixed seed: deterministic synthetic data
    a = 100 * np.cumprod(1 + rng.normal(0.001, 0.01, n))
    b = 100 * np.cumprod(1 + rng.normal(-0.0005, 0.01, n))
    return PricePanel.from_frames({"A": frame(list(a)), "B": frame(list(b))})


class Spy:
    """Holds one symbol; records the last date each view could serve."""

    seen: list = []

    def __init__(self, params):
        self.symbol = params["symbol"]
        self.name, self.version = "spy", "v1"

    def target_weights(self, view):
        Spy.seen.append((view.as_of, max(view.history(s).index.max() for s in view.symbols)))
        return {self.symbol: 1.0}


CFG = BacktestConfig(initial_cash=10_000.0, max_weight=1.0, rebalance="weekly")


def test_chronological_split_is_ordered_and_non_overlapping():
    cal = pd.bdate_range("2025-01-01", periods=100)
    s = chronological_split(cal, 0.6, 0.2)
    assert s.train.start == cal[0] and s.test.end == cal[-1]
    assert s.train.end < s.validation.start <= s.validation.end < s.test.start
    assert (s.train.end, s.validation.end) == (cal[59], cal[79])


@pytest.mark.parametrize("train, validation", [(0.9, 0.2), (0, 0.2), (0.5, 0.0), (1.0, 0.1)])
def test_split_fractions_must_leave_a_test_period(train, validation):
    with pytest.raises(BacktestError):
        chronological_split(pd.bdate_range("2025-01-01", periods=100), train, validation)


def test_split_needs_enough_dates():
    with pytest.raises(BacktestError, match="too few"):
        chronological_split(pd.bdate_range("2025-01-01", periods=5))


def test_walk_forward_windows_roll_without_overlapping_tests():
    cal = pd.bdate_range("2025-01-01", periods=100)
    windows = walk_forward_windows(cal, train_days=40, test_days=20)
    assert len(windows) == 3
    for w in windows:
        assert w.train.end < w.test.start
    for earlier, later in zip(windows, windows[1:], strict=False):
        assert earlier.test.end < later.test.start


def test_overlapping_or_impossible_windows_are_refused():
    cal = pd.bdate_range("2025-01-01", periods=50)
    with pytest.raises(BacktestError, match="overlap"):
        walk_forward_windows(cal, 20, 10, step_days=5)
    with pytest.raises(BacktestError, match="cannot hold"):
        walk_forward_windows(cal, 40, 20)


def test_parameter_selection_never_sees_the_test_period():
    panel = trending_panel()
    windows = walk_forward_windows(panel.calendar(), train_days=40, test_days=20)
    Spy.seen = []
    result = walk_forward(panel, Spy, [{"symbol": "A"}, {"symbol": "B"}], CFG, windows)
    train_ends = {w.train.end for w in windows}
    # Selection runs come first in each window; every view during them is at or before train end.
    for w in windows:
        selection = [seen for as_of, seen in Spy.seen if w.train.start <= as_of <= w.train.end]
        assert selection and max(selection) <= w.train.end
    assert all(o.chosen_params is not None for o in result.outcomes)
    assert train_ends


def test_best_training_score_is_chosen_and_ties_keep_grid_order():
    panel = trending_panel()
    windows = walk_forward_windows(panel.calendar(), train_days=40, test_days=20)
    assert len(windows) == 4                                        # 120 dates: windows start at 0, 20, 40, 60
    scores = iter([1.0, 2.0, 3.0, 3.0, None, 0.2, 0.5, 0.1])

    def objective(report):
        return next(scores)

    result = walk_forward(panel, Spy, [{"symbol": "A"}, {"symbol": "B"}], CFG, windows, objective=objective)
    assert result.outcomes[0].chosen_params == {"symbol": "B"}        # 2.0 beats 1.0
    assert result.outcomes[1].chosen_params == {"symbol": "A"}        # tie at 3.0: first in grid
    assert result.outcomes[2].chosen_params == {"symbol": "B"}        # the only defined score
    assert result.outcomes[3].chosen_params == {"symbol": "A"}        # 0.5 beats 0.1


@pytest.mark.parametrize("undefined", [None, float("nan"), float("inf"), float("-inf"), "1.0", True])
def test_a_window_with_no_finite_objective_refuses_the_whole_walk_forward(undefined):
    panel = trending_panel()
    windows = walk_forward_windows(panel.calendar(), train_days=40, test_days=20)
    scores = iter([1.0, 2.0, undefined, undefined])        # window 2: neither parameter set is usable

    def objective(report):
        return next(scores)

    with pytest.raises(WalkForwardError, match="no parameter set had a finite objective"):
        walk_forward(panel, Spy, [{"symbol": "A"}, {"symbol": "B"}], CFG, windows, objective=objective)


def test_a_non_finite_score_never_beats_a_finite_one():
    panel = trending_panel()
    windows = walk_forward_windows(panel.calendar(), train_days=40, test_days=20)[:1]
    scores = iter([float("nan"), 0.1])

    result = walk_forward(panel, Spy, [{"symbol": "A"}, {"symbol": "B"}], CFG, windows,
                          objective=lambda report: next(scores))
    assert result.outcomes[0].chosen_params == {"symbol": "B"}


def _w(cal, train, test):
    return Window(Period(cal[train[0]], cal[train[1]]), Period(cal[test[0]], cal[test[1]]))


@pytest.mark.parametrize("make, message", [
    (lambda c: [], "no walk-forward windows"),
    (lambda c: [_w(c, (0, 39), (39, 59))], "training ending before testing starts"),          # shares a date
    (lambda c: [_w(c, (0, 39), (30, 59))], "training ending before testing starts"),          # test inside train
    (lambda c: [_w(c, (20, 10), (40, 59))], "training ending before testing starts"),         # reversed train
    (lambda c: [_w(c, (0, 39), (59, 40))], "training ending before testing starts"),          # reversed test
    (lambda c: [_w(c, (0, 39), (40, 59)), _w(c, (10, 49), (55, 74))], "overlaps"),
    (lambda c: [_w(c, (20, 59), (60, 79)), _w(c, (0, 39), (40, 59))], "chronological order"),
    (lambda c: [_w(c, (0, 39), (40, 40))], "fewer than two trading dates"),
    (lambda c: [Window(Period(c[0], c[39]), Period(c[40] + pd.Timedelta(hours=1), c[59]))], "trading dates"),
    (lambda c: [Window(Period(c[0], c[39]), Period(c[40], c[-1] + pd.Timedelta(days=30)))], "trading dates"),
])
def test_invalid_windows_are_refused_at_the_evaluation_boundary(make, message):
    panel = trending_panel()
    windows = make(panel.calendar())
    with pytest.raises(WalkForwardError, match=message):
        validate_windows(windows, panel.calendar())
    if windows:
        with pytest.raises(WalkForwardError, match=message):
            walk_forward(panel, Spy, [{"symbol": "A"}], CFG, windows)


def test_windows_built_by_walk_forward_windows_are_valid():
    panel = trending_panel()
    for step in (20, 25, 40):
        validate_windows(walk_forward_windows(panel.calendar(), 40, 20, step), panel.calendar())


def test_out_of_sample_curve_contains_test_windows_only_and_compounds():
    panel = trending_panel()
    windows = walk_forward_windows(panel.calendar(), train_days=40, test_days=20)
    result = walk_forward(panel, Spy, [{"symbol": "A"}], CFG, windows)
    test_dates = set().union(*(set(pd.bdate_range(w.test.start, w.test.end)) for w in windows))
    assert set(result.oos_equity.index) <= test_dates
    assert result.oos_equity.iloc[0] == pytest.approx(CFG.initial_cash)
    expected = CFG.initial_cash
    for outcome in result.outcomes:
        r = outcome.test_report
        expected *= 1 + r.value("total_return")
    assert result.oos_equity.iloc[-1] == pytest.approx(expected)
    assert result.oos_metrics["total_return"].ok


def test_an_empty_grid_is_refused():
    panel = trending_panel()
    with pytest.raises(BacktestError, match="empty parameter grid"):
        walk_forward(panel, Spy, [], CFG, walk_forward_windows(panel.calendar(), 40, 20))
