"""The backtest simulator: timing, fills, costs, cash, caps, rejections and determinism.

Expected figures are worked out by hand in each test.
"""

import pandas as pd
import pytest

from sid_trading_firm.backtest.data import PricePanel
from sid_trading_firm.backtest.engine import (
    BacktestConfig,
    BacktestError,
    rebalance_dates,
    run_backtest,
)
from sid_trading_firm.quant.costs import SlippageModel, TransactionCostModel

pytestmark = pytest.mark.unit


def frame(opens, closes, start="2026-01-02"):
    dates = pd.bdate_range(start, periods=len(closes))
    highs = [max(o, c) * 1.01 for o, c in zip(opens, closes, strict=True)]
    lows = [min(o, c) * 0.99 for o, c in zip(opens, closes, strict=True)]
    return pd.DataFrame({"date": dates, "open": opens, "high": highs, "low": lows, "close": closes, "volume": 1e6})


class Fixed:
    """Holds constant target weights; records every view it is given."""

    name, version = "fixed", "v1"

    def __init__(self, weights):
        self.weights = weights
        self.views = []

    def target_weights(self, view):
        self.views.append((view.as_of, [view.history(s).index.max() for s in view.symbols]))
        return self.weights


def cfg(**kw):
    return BacktestConfig(**({"initial_cash": 10_000.0, "max_weight": 1.0, "rebalance": "daily"} | kw))


def one_symbol(opens=(100, 102, 104, 106), closes=(101, 103, 105, 107)):
    return PricePanel.from_frames({"A": frame(list(opens), list(closes))})


def test_decide_at_close_fill_at_next_open_without_costs():
    panel = one_symbol()
    result = run_backtest(panel, Fixed({"A": 1.0}), cfg(rebalance="monthly"))
    # Decided at the close of 2026-01-02: equity 10,000 / close 101 -> 99 shares wanted.
    # The price gaps up to 102 at the next open: 99 * 102 = 10,098 > cash, so 98 fill.
    (fill,) = result.fills
    assert (fill.date, fill.decided_on) == (pd.Timestamp("2026-01-05"), pd.Timestamp("2026-01-02"))
    assert (fill.shares, fill.price, fill.reference_price) == (98, 102.0, 102.0)
    assert [(r.shares, r.reason) for r in result.rejected] == [(1, "insufficient cash")]
    cash = 10_000 - 98 * 102
    assert result.cash.iloc[-1] == pytest.approx(cash)
    assert result.equity.iloc[0] == 10_000                       # day one: still all cash
    assert result.equity.iloc[1] == pytest.approx(cash + 98 * 103)
    assert result.equity.iloc[-1] == pytest.approx(cash + 98 * 107)


def test_slippage_and_commission_are_charged_on_the_fill():
    model = cfg(rebalance="monthly", slippage=SlippageModel(half_spread_bps=10),
                costs=TransactionCostModel(per_share=0.01, minimum_per_order=1.0))
    result = run_backtest(one_symbol(), Fixed({"A": 1.0}), model)
    (fill,) = result.fills
    # Fill price 102.102; 98 shares would cost 10,006 + 1 commission > cash, so 97.
    assert fill.price == pytest.approx(102 * 1.001)
    assert fill.shares == 97
    assert fill.commission == pytest.approx(max(97 * 0.01, 1.0))
    assert fill.slippage_cost == pytest.approx(97 * 102 * 0.001)
    assert result.cash.iloc[-1] == pytest.approx(10_000 - 97 * 102 * 1.001 - 1.0)


def test_the_strategy_only_ever_sees_data_up_to_its_decision_date():
    strategy = Fixed({"A": 0.5})
    run_backtest(one_symbol(), strategy, cfg())
    assert strategy.views
    for as_of, last_seen in strategy.views:
        assert all(d <= as_of for d in last_seen)


def test_every_fill_happens_after_its_decision():
    result = run_backtest(one_symbol(), Fixed({"A": 0.5}), cfg())
    assert result.fills and all(f.date > f.decided_on for f in result.fills)


def test_no_decision_is_taken_on_the_last_date():
    result = run_backtest(one_symbol(), Fixed({"A": 0.5}), cfg())
    assert result.decisions[-1] < result.equity.index[-1]


def test_cash_limits_buys_and_is_never_negative():
    # Commission makes 99 shares unaffordable: 99*102 + 10 > 10,000 -> 97 shares (97*102+10 = 9904).
    model = cfg(rebalance="monthly", costs=TransactionCostModel(minimum_per_order=10.0))
    result = run_backtest(one_symbol(), Fixed({"A": 1.0}), model)
    (fill,) = result.fills
    assert fill.shares == 97
    assert all(c >= 0 for c in result.cash)
    assert any(r.reason == "insufficient cash" and r.shares == 2 for r in result.rejected)


def test_sells_execute_before_buys_so_the_switch_is_funded():
    a = frame([100] * 4, [100] * 4)
    b = frame([50] * 4, [50] * 4)
    panel = PricePanel.from_frames({"A": a, "B": b})

    class Switch:
        name, version = "switch", "v1"

        def target_weights(self, view):
            return {"A": 1.0} if view.as_of == pd.Timestamp("2026-01-02") else {"B": 1.0}

    result = run_backtest(panel, Switch(), cfg())
    day3 = [f for f in result.fills if f.date == pd.Timestamp("2026-01-06")]
    assert [(f.side, f.symbol, f.shares) for f in day3] == [("sell", "A", 100), ("buy", "B", 200)]
    assert not [r for r in result.rejected if r.reason == "insufficient cash"]


def test_weights_above_the_cap_are_capped_and_recorded():
    result = run_backtest(one_symbol(), Fixed({"A": 0.9}), cfg(rebalance="monthly", max_weight=0.25))
    assert result.fills[0].shares == 24                              # floor(0.25 * 10,000 / 101)
    assert result.capped == [(pd.Timestamp("2026-01-02"), "A", 0.9)]


@pytest.mark.parametrize("weights, message", [
    ({"A": -0.1}, "long-only"), ({"A": float("nan")}, "finite"), ({"A": "lots"}, "not a number"),
    ({"ZZZ": 0.5}, "unknown symbol"),
])
def test_invalid_strategy_output_stops_the_backtest(weights, message):
    with pytest.raises(BacktestError, match=message):
        run_backtest(one_symbol(), Fixed(weights), cfg())


def test_leverage_is_refused():
    panel = PricePanel.from_frames({"A": frame([100] * 3, [100] * 3), "B": frame([100] * 3, [100] * 3)})
    with pytest.raises(BacktestError, match="no leverage"):
        run_backtest(panel, Fixed({"A": 0.6, "B": 0.6}), cfg())
    with pytest.raises(BacktestError, match="no leverage"):
        run_backtest(panel, Fixed({"A": 0.95}), cfg(cash_buffer=0.1))


def test_an_order_with_no_bar_at_execution_is_recorded_not_filled():
    a = frame([100] * 4, [100] * 4)
    b = frame([50, 50], [50, 50])                                    # B stops trading after 2026-01-05
    panel = PricePanel.from_frames({"A": a, "B": b})

    class LateB:
        name, version = "late", "v1"

        def target_weights(self, view):
            return {"B": 0.5} if view.as_of == pd.Timestamp("2026-01-05") else {}

    result = run_backtest(panel, LateB(), cfg())
    assert any(r.symbol == "B" and r.reason == "no bar at the execution date" for r in result.rejected)
    assert not [f for f in result.fills if f.symbol == "B"]


def test_round_trip_trade_pnl_is_net_of_costs():
    model = cfg(costs=TransactionCostModel(minimum_per_order=1.0))

    class InOut:
        name, version = "inout", "v1"

        def target_weights(self, view):
            return {"A": 1.0} if view.as_of == pd.Timestamp("2026-01-02") else {}

    result = run_backtest(one_symbol(), InOut(), model)
    (trade,) = result.trades
    # Bought 97 at 102 (+1 commission) on 01-05, sold 97 at 104 (-1 commission) on 01-06.
    shares = trade.shares
    assert trade.pnl == pytest.approx(shares * 104 - 1 - (shares * 102 + 1))
    assert result.open_positions == {}


def test_rebalance_schedules():
    cal = pd.bdate_range("2026-01-26", "2026-02-10")
    assert rebalance_dates(cal, "daily") == set(cal)
    assert sorted(d.strftime("%m-%d") for d in rebalance_dates(cal, "monthly")) == ["01-26", "01-30"]
    weekly = sorted(d.strftime("%m-%d") for d in rebalance_dates(cal, "weekly"))
    assert weekly == ["01-26", "01-30", "02-06"]


def test_the_backtest_is_deterministic():
    a = run_backtest(one_symbol(), Fixed({"A": 0.7}), cfg())
    b = run_backtest(one_symbol(), Fixed({"A": 0.7}), cfg())
    assert a.equity.equals(b.equity) and a.fills == b.fills and a.data_fingerprint == b.data_fingerprint


@pytest.mark.parametrize("kw, message", [
    ({"initial_cash": 0}, "initial_cash"), ({"max_weight": 0}, "max_weight"), ({"max_weight": 1.5}, "max_weight"),
    ({"cash_buffer": 1.0}, "cash_buffer"), ({"rebalance": "hourly"}, "rebalance"),
])
def test_invalid_configuration_is_refused(kw, message):
    with pytest.raises(BacktestError, match=message):
        cfg(**kw)


def test_a_window_with_fewer_than_two_dates_is_refused():
    with pytest.raises(BacktestError, match="two trading dates"):
        run_backtest(one_symbol(), Fixed({}), cfg(start="2026-01-07"))

