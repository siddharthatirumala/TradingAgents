"""Backtest performance metrics: hand-checked figures and explicit undefined states."""

import pandas as pd
import pytest

from sid_trading_firm.backtest.data import PricePanel
from sid_trading_firm.backtest.engine import BacktestConfig, BacktestResult, Trade
from sid_trading_firm.backtest.metrics import evaluate
from sid_trading_firm.quant import Status

pytestmark = pytest.mark.unit


def frame(closes, start="2026-01-02"):
    dates = pd.bdate_range(start, periods=len(closes))
    return pd.DataFrame({"date": dates, "open": closes, "high": [c * 1.01 for c in closes],
                         "low": [c * 0.99 for c in closes], "close": closes, "volume": 1e6})


def result(equity, cash=None, trades=(), fills=()):
    idx = pd.bdate_range("2026-01-02", periods=len(equity))
    eq = pd.Series(equity, index=idx, dtype=float)
    cash = pd.Series(cash if cash is not None else [0.0] * len(equity), index=idx, dtype=float)
    return BacktestResult("s_v1", BacktestConfig(initial_cash=equity[0], max_weight=1.0), "fp", eq, cash,
                          list(fills), list(trades), [], [], [], {})


def trade(pnl, basis=100.0, shares=10):
    d = pd.Timestamp("2026-01-05")
    return Trade("A", d, d, shares, basis, basis + pnl / shares, pnl)


def panel(closes):
    return PricePanel.from_frames({"SPY": frame(closes)})


def test_returns_drawdown_and_exposure_by_hand():
    r = result([100, 110, 99, 121], cash=[100, 55, 49.5, 0])
    rep = evaluate(r, panel([1, 1, 1, 1]))
    assert rep.value("total_return") == pytest.approx(0.21)
    assert rep.value("annualised_return") == pytest.approx(1.21 ** (252 / 3) - 1)
    assert rep.value("max_drawdown") == pytest.approx(0.1)                  # 110 -> 99
    assert rep.value("average_exposure") == pytest.approx((0 + 0.5 + 0.5 + 1) / 4)
    assert rep.trading_days == 4


def test_trade_statistics_by_hand():
    r = result([100, 101, 102], trades=[trade(30), trade(-10), trade(20)])
    rep = evaluate(r, panel([1, 1, 1]))
    assert rep.value("trade_count") == 3
    assert rep.value("win_rate") == pytest.approx(2 / 3)
    assert rep.value("profit_factor") == pytest.approx(50 / 10)
    assert rep.value("expectancy") == pytest.approx(40 / 3)
    assert rep.value("average_trade_return") == pytest.approx((0.03 - 0.01 + 0.02) / 3)


def test_undefined_and_insufficient_states_are_explicit():
    flat = evaluate(result([100, 100, 100, 100]), panel([1, 1, 1, 1]))
    assert flat.metrics["sharpe"].status is Status.UNDEFINED
    assert flat.metrics["win_rate"].status is Status.INSUFFICIENT_DATA
    winners_only = evaluate(result([100, 101, 102], trades=[trade(5)]), panel([1, 1, 1]))
    assert winners_only.metrics["profit_factor"].status is Status.UNDEFINED
    assert winners_only.metrics["profit_factor"].value is None


def test_benchmark_comparison_beta_and_correlation():
    bench = [100, 102, 101, 104, 103]
    strategy = [1000 * b / 100 for b in bench]                 # exactly the benchmark
    rep = evaluate(result(strategy, cash=[0] * 5), panel(bench), benchmark="spy")
    assert rep.benchmark == "SPY"
    assert rep.value("benchmark_return") == pytest.approx(0.03)
    assert rep.value("excess_return") == pytest.approx(0.0, abs=1e-12)
    assert rep.value("beta") == pytest.approx(1.0)
    assert rep.value("correlation") == pytest.approx(1.0)


def test_an_unknown_benchmark_is_an_error():
    with pytest.raises(ValueError, match="not in the price panel"):
        evaluate(result([100, 101]), panel([1, 1]), benchmark="QQQ")


def test_regimes_are_labelled_by_the_previous_close():
    # Benchmark rises for 4 days then falls; with a 3-day SMA the first two labels are unknown.
    bench = [100, 101, 102, 103, 99, 95]
    strategy = [100, 101, 102, 103, 104, 105]
    rep = evaluate(result(strategy), panel(bench), benchmark="SPY", regime_window=3)
    # SMA3 known from day 3: day3 102>=101 above, day4 103>=102 above, day5 99<101.33 below, day6 95<99 below.
    # Returns on days 2..6 take the label of days 1..5: unknown, unknown, above, above, below.
    assert rep.regimes["unknown"]["days"] == 2
    assert rep.regimes["above_trend"]["days"] == 2
    assert rep.regimes["below_trend"]["days"] == 1
    assert rep.regimes["below_trend"]["compounded_return"] == pytest.approx(105 / 104 - 1)


def test_report_serialises_with_statuses():
    data = evaluate(result([100, 100, 101]), panel([1, 1, 1])).as_dict()
    assert data["metrics"]["profit_factor"]["status"] == "insufficient_data"
    assert data["metrics"]["total_return"]["value"] == pytest.approx(0.01)
    assert data["start"] == "2026-01-02"
