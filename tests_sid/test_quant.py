"""Deterministic quant functions: hand-checked values and every failure mode.

Expected values are worked out by hand (or with the statistics module) in the
test, not copied from the implementation.
"""

import ast
import math
import statistics
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from sid_trading_firm import quant
from sid_trading_firm.quant import (
    QuantError,
    SlippageModel,
    Status,
    TransactionCostModel,
    arithmetic_returns,
    atr,
    atr_risk_size,
    beta,
    correlation,
    ema,
    expected_value,
    log_returns,
    max_drawdown,
    realised_volatility,
    rsi,
    sharpe_ratio,
    sma,
    sortino_ratio,
    trade_expectancy,
    volatility_target_size,
)

pytestmark = pytest.mark.unit
NAN = float("nan")
INF = float("inf")
SQRT252 = math.sqrt(252)


def series(values, start="2026-01-02"):
    return pd.Series(values, index=pd.bdate_range(start, periods=len(values)), dtype=float)


# ------------------------------------------------------------------ result type

def test_a_failed_result_has_no_value_and_require_raises():
    r = sharpe_ratio([0.01, 0.01, 0.01])
    assert r.status is Status.UNDEFINED and r.value is None and not r.ok
    with pytest.raises(QuantError, match="undefined"):
        r.require()


# -------------------------------------------------------------------- returns

def test_arithmetic_and_log_returns():
    prices = series([100, 110, 99])
    simple = arithmetic_returns(prices)
    assert simple.ok and simple.n_obs == 2
    assert simple.values.tolist() == pytest.approx([0.10, -0.10])
    assert list(simple.values.index) == list(prices.index[1:])
    assert log_returns(prices).values.tolist() == pytest.approx([math.log(1.1), math.log(0.9)])


@pytest.mark.parametrize("fn", [arithmetic_returns, log_returns])
@pytest.mark.parametrize("prices, status", [
    ([], Status.INSUFFICIENT_DATA),
    ([100], Status.INSUFFICIENT_DATA),
    ([100, NAN, 102], Status.INVALID_INPUT),
    ([100, INF], Status.INVALID_INPUT),
    ([100, 0, 102], Status.INVALID_INPUT),
    ([100, -5], Status.INVALID_INPUT),
    (["a", "b"], Status.INVALID_INPUT),
])
def test_returns_refuse_unusable_prices(fn, prices, status):
    result = fn(prices)
    assert result.status is status and result.values is None


def test_missing_prices_can_be_dropped_explicitly():
    result = arithmetic_returns([100, NAN, 110], nan_policy="drop")
    assert result.ok and result.values.tolist() == pytest.approx([0.10])
    assert arithmetic_returns([100, 110], nan_policy="ignore").status is Status.INVALID_INPUT


def test_extreme_but_valid_prices():
    assert arithmetic_returns([1e-300, 2e-300]).values.tolist() == pytest.approx([1.0])
    assert arithmetic_returns([1e300, 1.5e300]).values.tolist() == pytest.approx([0.5])


# ----------------------------------------------------------------- volatility

def test_realised_volatility_matches_the_sample_standard_deviation():
    r = [0.01, -0.01, 0.02, 0.0]
    assert realised_volatility(r).value == pytest.approx(statistics.stdev(r) * SQRT252)
    assert realised_volatility(r, annualise=False).value == pytest.approx(statistics.stdev(r))
    assert realised_volatility(r, periods_per_year=52).value == pytest.approx(statistics.stdev(r) * math.sqrt(52))


def test_zero_variance_is_a_true_zero_volatility():
    result = realised_volatility([0.01] * 5)
    assert result.ok and result.value == 0.0


@pytest.mark.parametrize("r, kwargs, status", [
    ([], {}, Status.INSUFFICIENT_DATA),
    ([0.01], {}, Status.INSUFFICIENT_DATA),
    ([0.01, 0.02, 0.03], {"min_obs": 20}, Status.INSUFFICIENT_DATA),
    ([0.01, NAN, 0.02], {}, Status.INVALID_INPUT),
    ([0.01, 0.02], {"periods_per_year": 0}, Status.INVALID_INPUT),
])
def test_volatility_failures(r, kwargs, status):
    assert realised_volatility(r, **kwargs).status is status


def test_overflowing_volatility_is_invalid_not_infinite():
    result = realised_volatility([1e308, -1e308, 1e308])
    assert result.status is Status.INVALID_INPUT and "non-finite" in result.reason


# ---------------------------------------------------------- beta / correlation

def test_beta_and_correlation_of_a_scaled_series():
    bench = series([0.01, -0.02, 0.015, 0.005, -0.01])
    asset = bench * 2
    assert beta(asset, bench).value == pytest.approx(2.0)
    assert correlation(asset, bench).value == pytest.approx(1.0)
    assert correlation(-asset, bench).value == pytest.approx(-1.0)


def test_beta_against_a_hand_computed_covariance():
    a, b = [0.02, 0.01, -0.01, 0.03], [0.01, 0.0, -0.02, 0.01]
    ma, mb = sum(a) / 4, sum(b) / 4
    cov = sum((x - ma) * (y - mb) for x, y in zip(a, b, strict=True)) / 3
    var = sum((y - mb) ** 2 for y in b) / 3
    assert beta(a, b).value == pytest.approx(cov / var)


def test_flat_benchmark_makes_beta_and_correlation_undefined():
    bench = [0.0, 0.0, 0.0, 0.0]
    assert beta([0.01, 0.02, -0.01, 0.0], bench).status is Status.UNDEFINED
    assert correlation([0.01, 0.02, -0.01, 0.0], bench).status is Status.UNDEFINED
    assert correlation([0.01] * 4, [0.01, 0.02, -0.01, 0.0]).status is Status.UNDEFINED


def test_dates_missing_from_the_benchmark_are_left_out_and_counted():
    asset = series([0.01, 0.02, -0.01, 0.03, 0.0])
    bench = (asset / 2).drop(asset.index[2])            # benchmark has no price that day
    result = beta(asset, bench)
    assert result.ok and result.value == pytest.approx(2.0)
    assert result.n_obs == 4 and result.details["unmatched_dates"] == 1


def test_missing_benchmark_values_are_rejected_unless_dropped():
    asset = series([0.01, 0.02, -0.01, 0.03])
    bench = series([0.005, NAN, -0.005, 0.015])
    assert beta(asset, bench).status is Status.INVALID_INPUT
    dropped = beta(asset, bench, nan_policy="drop")
    assert dropped.ok and dropped.value == pytest.approx(2.0) and dropped.details["dropped_missing"] == 1


def test_beta_needs_enough_paired_history_and_matching_lengths():
    assert beta([0.01], [0.02]).status is Status.INSUFFICIENT_DATA
    assert beta([0.01, 0.02, 0.03], [0.01, 0.02, 0.03], min_obs=10).status is Status.INSUFFICIENT_DATA
    assert beta([0.01, 0.02, 0.03], [0.01, 0.02]).status is Status.INVALID_INPUT
    assert beta(series([0.01, 0.02]), series([0.01, 0.02], start="2030-01-01")).status is Status.INSUFFICIENT_DATA


# -------------------------------------------------------------------- drawdown

def test_max_drawdown_finds_the_deepest_fall_and_where_it_happened():
    equity = series([100, 120, 90, 130, 65, 70])
    result = max_drawdown(equity)
    assert result.value == pytest.approx(0.5)               # 130 -> 65
    assert result.details["peak"] == equity.index[3]
    assert result.details["trough"] == equity.index[4]


def test_a_series_that_never_falls_has_zero_drawdown():
    result = max_drawdown([100, 101, 105, 105, 110])
    assert result.ok and result.value == 0.0


@pytest.mark.parametrize("values, status", [
    ([], Status.INSUFFICIENT_DATA), ([100], Status.INSUFFICIENT_DATA),
    ([100, 0], Status.INVALID_INPUT), ([100, -1], Status.INVALID_INPUT), ([100, NAN], Status.INVALID_INPUT),
])
def test_drawdown_failures(values, status):
    assert max_drawdown(values).status is status


# --------------------------------------------------------------- sharpe/sortino

def test_sharpe_ratio_by_hand():
    r = [0.01, 0.02, 0.03]                                  # mean 0.02, sd 0.01
    assert sharpe_ratio(r).value == pytest.approx(2 * SQRT252)
    # 2.52% a year risk-free is 0.0001 a day: (0.02 - 0.0001) / 0.01
    assert sharpe_ratio(r, risk_free_rate=0.0252).value == pytest.approx(1.99 * SQRT252)


def test_sharpe_is_undefined_not_infinite_when_returns_do_not_vary():
    result = sharpe_ratio([0.01] * 10)
    assert result.status is Status.UNDEFINED and "zero variance" in result.reason


def test_sortino_ratio_by_hand():
    r = [0.02, -0.01, 0.03, -0.02]
    downside = math.sqrt((0.01 ** 2 + 0.02 ** 2) / 4)
    assert sortino_ratio(r).value == pytest.approx(0.005 / downside * SQRT252)


def test_sortino_is_undefined_without_downside_deviation():
    result = sortino_ratio([0.01, 0.02, 0.0])
    assert result.status is Status.UNDEFINED and "downside" in result.reason


def test_sortino_target_return_moves_the_threshold():
    # Above 0 every period, but below a 25.2% annual target (0.001 a day) twice.
    result = sortino_ratio([0.0005, 0.002, 0.0008, 0.003], minimum_acceptable_return=0.252)
    assert result.ok


@pytest.mark.parametrize("fn", [sharpe_ratio, sortino_ratio])
def test_ratio_input_failures(fn):
    assert fn([]).status is Status.INSUFFICIENT_DATA
    assert fn([0.01]).status is Status.INSUFFICIENT_DATA
    assert fn([0.01, NAN, -0.02]).status is Status.INVALID_INPUT
    assert fn([0.01, -0.02], periods_per_year=-1).status is Status.INVALID_INPUT


# ------------------------------------------------------------------ indicators

def test_sma():
    result = sma([1, 2, 3, 4, 5], 3)
    assert result.values.tolist()[:2] == [pytest.approx(NAN, nan_ok=True)] * 2
    assert result.values.tolist()[2:] == pytest.approx([2, 3, 4])
    assert sma([1, 2, 3], 1).values.tolist() == pytest.approx([1, 2, 3])
    assert sma([1, 2, 3], 3).latest().value == pytest.approx(2)


def test_ema_is_seeded_with_the_sma_then_smoothed():
    # window 3: alpha 0.5; seed SMA(1,2,3)=2; then 0.5*4+0.5*2=3, 0.5*5+0.5*3=4
    values = ema([1, 2, 3, 4, 5], 3).values.tolist()
    assert np.isnan(values[:2]).all()
    assert values[2:] == pytest.approx([2, 3, 4])


@pytest.mark.parametrize("fn", [sma, ema])
@pytest.mark.parametrize("values, window, status", [
    ([1, 2], 3, Status.INSUFFICIENT_DATA),
    ([], 2, Status.INSUFFICIENT_DATA),
    ([1, 2, 3], 0, Status.INVALID_INPUT),
    ([1, 2, 3], 2.5, Status.INVALID_INPUT),
    ([1, 2, 3], True, Status.INVALID_INPUT),
    ([1, NAN, 3], 2, Status.INVALID_INPUT),
])
def test_moving_average_failures(fn, values, window, status):
    assert fn(values, window).status is status


def test_rsi_by_hand_with_wilder_smoothing():
    # window 2; changes +1, +1, -1.
    # bar 2: avg gain (1+1)/2 = 1, avg loss 0 -> 100
    # bar 3: gain (1*1 + 0)/2 = 0.5, loss (0*1 + 1)/2 = 0.5 -> 50
    values = rsi([1, 2, 3, 2], 2).values.tolist()
    assert np.isnan(values[:2]).all()
    assert values[2:] == pytest.approx([100, 50])


def test_rsi_extremes_and_a_flat_market():
    assert rsi([5, 4, 3, 2, 1], 2).latest().value == pytest.approx(0)
    assert rsi([1, 2, 3, 4, 5], 2).latest().value == pytest.approx(100)
    flat = rsi([10, 10, 10, 10], 2)
    assert flat.ok and flat.latest().status is Status.UNDEFINED


def test_rsi_needs_window_plus_one_prices():
    assert rsi([1, 2, 3], 3).status is Status.INSUFFICIENT_DATA
    assert rsi([1, 2, 3, 4], 3).ok


def test_atr_by_hand():
    high = [10, 11, 12, 11]
    low = [9, 10, 10, 9]
    close = [9.5, 10.5, 11.5, 9.5]
    # true ranges from bar 1: max(1, 1.5, 0.5)=1.5; max(2, 1.5, 0.5)=2; max(2, 0.5, 2.5)=2.5
    # window 2: seed (1.5+2)/2 = 1.75 at bar 2; bar 3: (1.75*1 + 2.5)/2 = 2.125
    values = atr(high, low, close, 2).values.tolist()
    assert np.isnan(values[:2]).all()
    assert values[2:] == pytest.approx([1.75, 2.125])


@pytest.mark.parametrize("high, low, close, status", [
    ([10, 11], [9, 10], [9.5, 10.5], Status.INSUFFICIENT_DATA),           # window 2 needs 3 bars
    ([10, 11, 12], [9, 12, 10], [9.5, 11.5, 11], Status.INVALID_INPUT),   # high below low
    ([10, 11, 12], [9, 10, 10], [9.5, 13, 11], Status.INVALID_INPUT),     # close above high
    ([10, 11, 12], [9, 10], [9.5, 10.5, 11], Status.INVALID_INPUT),       # lengths differ
    ([10, NAN, 12], [9, 10, 10], [9.5, 10.5, 11], Status.INVALID_INPUT),
    ([10, 11, 12], [9, 0, 10], [9.5, 10.5, 11], Status.INVALID_INPUT),
])
def test_atr_refuses_bad_bars(high, low, close, status):
    assert atr(high, low, close, 2).status is status


# ----------------------------------------------------------- expected value

def test_expected_value_and_expectancy():
    assert expected_value([10, -5], [0.6, 0.4]).value == pytest.approx(4.0)
    assert trade_expectancy(0.5, 0.02, 0.01).value == pytest.approx(0.005)
    assert trade_expectancy(0.3, 0.02, 0.01).value == pytest.approx(-0.001)


@pytest.mark.parametrize("payoffs, probs, status", [
    ([], [], Status.INSUFFICIENT_DATA),
    ([1, 2], [0.5], Status.INVALID_INPUT),
    ([1, 2], [0.5, 0.6], Status.INVALID_INPUT),
    ([1, 2], [1.5, -0.5], Status.INVALID_INPUT),
    ([1, NAN], [0.5, 0.5], Status.INVALID_INPUT),
    ([INF, 1], [0.5, 0.5], Status.INVALID_INPUT),
])
def test_expected_value_failures(payoffs, probs, status):
    assert expected_value(payoffs, probs).status is status


@pytest.mark.parametrize("args", [(1.2, 0.02, 0.01), (0.5, -0.02, 0.01), (0.5, 0.02, -0.01), (NAN, 1, 1)])
def test_expectancy_failures(args):
    assert trade_expectancy(*args).status is Status.INVALID_INPUT


# ------------------------------------------------------------ costs/slippage

def test_transaction_costs():
    assert TransactionCostModel(per_share=0.005).cost(100, 50).value == pytest.approx(0.5)
    assert TransactionCostModel(bps_of_notional=1).cost(200, 50).value == pytest.approx(1.0)  # 1bp of 10,000
    minimum = TransactionCostModel(per_share=0.005, minimum_per_order=1).cost(10, 50)
    assert minimum.value == 1 and minimum.details["minimum_applied"]
    assert TransactionCostModel(minimum_per_order=1).cost(0, 50).value == 0.0       # no order, no fee


@pytest.mark.parametrize("model, shares, price", [
    (TransactionCostModel(), -1, 50), (TransactionCostModel(), 10, 0), (TransactionCostModel(), 10, NAN),
    (TransactionCostModel(per_share=-0.01), 10, 50),
])
def test_transaction_cost_failures(model, shares, price):
    assert model.cost(shares, price).status is Status.INVALID_INPUT


def test_slippage_moves_the_price_against_the_trader():
    model = SlippageModel(half_spread_bps=5, impact_bps=5)              # 10bp in total
    assert model.fill_price(100, "buy").value == pytest.approx(100.10)
    assert model.fill_price(100, "sell").value == pytest.approx(99.90)
    assert model.cost(100, 1000, "buy").value == pytest.approx(100.0)
    assert SlippageModel().fill_price(100, "buy").value == 100


@pytest.mark.parametrize("model, price, side", [
    (SlippageModel(), 0, "buy"), (SlippageModel(), 100, "short"),
    (SlippageModel(half_spread_bps=-1), 100, "buy"), (SlippageModel(impact_bps=10_000), 100, "sell"),
])
def test_slippage_failures(model, price, side):
    assert model.fill_price(price, side).status is Status.INVALID_INPUT


# ---------------------------------------------------------------- sizing

def test_volatility_target_size_capped_by_max_weight():
    size = volatility_target_size(100_000, 50, annualised_volatility=0.40, target_volatility=0.10,
                                  max_weight=0.20)
    # raw weight 0.25 > cap 0.20 -> 20,000 notional -> 400 shares
    assert (size.shares, size.notional, size.weight, size.capped_by) == (400, 20_000, 0.2, "max_weight")


def test_volatility_target_size_uncapped_and_whole_shares():
    size = volatility_target_size(100_000, 33, annualised_volatility=0.50, target_volatility=0.05,
                                  max_weight=0.20)
    # weight 0.10 -> 10,000 / 33 = 303.03 -> 303 shares
    assert size.ok and size.shares == 303 and size.capped_by is None
    assert size.notional == pytest.approx(303 * 33)


def test_atr_risk_size():
    size = atr_risk_size(100_000, 50, atr=2, risk_fraction=0.01, atr_multiple=2, max_weight=0.20)
    # risk $1,000 / stop distance $4 = 250 shares = $12,500 (12.5% < 20% cap)
    assert (size.shares, size.notional, size.capped_by) == (250, 12_500, None)
    capped = atr_risk_size(100_000, 50, atr=0.5, risk_fraction=0.01, atr_multiple=1, max_weight=0.20)
    assert capped.shares == 400 and capped.capped_by == "max_weight"


@pytest.mark.parametrize("kwargs, status", [
    ({"annualised_volatility": 0}, Status.UNDEFINED),
    ({"annualised_volatility": -0.1}, Status.INVALID_INPUT),
    ({"equity": 0}, Status.INVALID_INPUT),
    ({"price": NAN}, Status.INVALID_INPUT),
    ({"max_weight": 1.5}, Status.INVALID_INPUT),
    ({"max_weight": 0}, Status.INVALID_INPUT),
    ({"target_volatility": INF}, Status.INVALID_INPUT),
])
def test_volatility_sizing_failures(kwargs, status):
    args = {"equity": 100_000, "price": 50, "annualised_volatility": 0.4, "target_volatility": 0.1,
            "max_weight": 0.2} | kwargs
    size = volatility_target_size(**args)
    assert size.status is status and size.shares is None


@pytest.mark.parametrize("kwargs, status", [
    ({"atr": 0}, Status.UNDEFINED), ({"atr": -1}, Status.INVALID_INPUT),
    ({"risk_fraction": 2}, Status.INVALID_INPUT), ({"atr_multiple": 0}, Status.INVALID_INPUT),
])
def test_atr_sizing_failures(kwargs, status):
    args = {"equity": 100_000, "price": 50, "atr": 2, "risk_fraction": 0.01, "atr_multiple": 2,
            "max_weight": 0.2} | kwargs
    assert atr_risk_size(**args).status is status


# --------------------------------------------------------------- isolation

FORBIDDEN = {"langchain", "langchain_core", "langgraph", "langchain_anthropic", "langchain_openai",
             "anthropic", "openai", "tradingagents"}


def test_the_quant_package_imports_no_llm_or_upstream_code():
    root = Path(quant.__file__).parent
    for path in root.rglob("*.py"):
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            names = []
            if isinstance(node, ast.Import):
                names = [a.name for a in node.names]
            elif isinstance(node, ast.ImportFrom) and node.module:
                names = [node.module]
            for name in names:
                assert name.split(".")[0] not in FORBIDDEN, f"{path.name} imports {name}"
                assert not name.startswith("sid_trading_firm.") or name.startswith("sid_trading_firm.quant"), \
                    f"{path.name} imports {name}"


# ------------------------------------------------------- floating-point noise

@pytest.mark.parametrize("fn", [sharpe_ratio, sortino_ratio])
def test_constant_returns_are_not_turned_into_huge_ratios_by_rounding(fn):
    """std([0.01] * 10) is about 1e-18, not 0; it must still count as no variation."""
    assert fn([0.01] * 10).status is Status.UNDEFINED
    assert fn([0.1 + 0.2] * 7).status is Status.UNDEFINED


def test_rounding_noise_is_zero_volatility_and_undefined_beta():
    assert realised_volatility([0.01] * 10).value == 0.0
    assert beta([0.01, 0.02, 0.03, 0.04], [0.01] * 4).status is Status.UNDEFINED
    assert correlation([0.01] * 4, [0.01, 0.02, 0.03, 0.04]).status is Status.UNDEFINED


def test_genuinely_tiny_variation_is_still_measured():
    r = [1e-6, -1e-6, 2e-6, 0.0]
    assert sharpe_ratio(r).ok and realised_volatility(r).value > 0
