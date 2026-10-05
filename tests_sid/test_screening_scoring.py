"""Factor scores: hand-checked factor values, percentile ranks, exclusions and determinism."""

import math

import numpy as np
import pytest
from pydantic import ValidationError

from sid_trading_firm.screening import scoring
from sid_trading_firm.screening.scoring import (
    ScoringConfig,
    ScoringError,
    liquidity,
    momentum,
    percentile_ranks,
    score,
    trend,
    unusual_volume,
)
from tests_sid.screening_data import frame, panel, walk

pytestmark = pytest.mark.unit


def last_view(p):
    return p.view(p.calendar()[-1])


def test_momentum_skips_the_most_recent_bars():
    # closes 100..110 (11 bars); lookback 10, skip 2: close[-3] / close[0] - 1 = 108/100 - 1
    p = panel(X=frame(np.arange(100.0, 111.0)))
    assert momentum(last_view(p), "X", lookback=10, skip=2) == pytest.approx(0.08)
    assert momentum(last_view(p), "X", lookback=20, skip=2) is None
    with pytest.raises(ValueError, match="skip"):
        momentum(last_view(p), "X", lookback=5, skip=5)


def test_trend_liquidity_and_unusual_volume_by_hand():
    p = panel(X=frame([10.0, 10.0, 10.0, 14.0], volume=[100, 100, 100, 400]))
    v = last_view(p)
    assert trend(v, "X", window=4) == pytest.approx(14.0 / 11.0 - 1)
    assert liquidity(v, "X", window=4) == pytest.approx(math.log((3 * 1000 + 14 * 400) / 4))
    assert unusual_volume(v, "X", window=3) == pytest.approx(4.0)
    assert unusual_volume(v, "X", window=10) is None


def test_percentile_ranks_and_ties():
    assert percentile_ranks({"A": 1.0, "B": 2.0, "C": 3.0}) == {"A": 0.0, "B": 0.5, "C": 1.0}
    assert percentile_ranks({"A": 1.0, "B": 1.0}) == {"A": 0.5, "B": 0.5}
    assert percentile_ranks({"A": -5.0}) == {"A": 1.0}


def test_composite_ranking_and_deterministic_ties():
    up = walk(80, 0.004, 0.005, seed=1)
    flat = walk(80, 0.0, 0.005, seed=2)
    down = walk(80, -0.004, 0.005, seed=3)
    p = panel(UP=frame(up), FLAT=frame(flat), DOWN=frame(down), TWIN=frame(up))
    cfg = ScoringConfig(factors={"momentum": {"weight": 1.0, "params": {"lookback": 60, "skip": 5}}})
    result = score(last_view(p), ["UP", "FLAT", "DOWN", "TWIN"], cfg)
    order = [s.symbol for s in result.scored]
    assert order == ["TWIN", "UP", "FLAT", "DOWN"]     # TWIN and UP have equal scores: ties break by symbol
    assert result.scored[0].composite == result.scored[1].composite
    assert result.scored[-1].composite == 0.0


def test_weights_combine_ranks():
    p = panel(A=frame(np.linspace(100, 130, 80), volume=1_000),
              B=frame(np.linspace(100, 110, 80), volume=1_000_000))
    cfg = ScoringConfig(factors={"momentum": {"weight": 3.0, "params": {"lookback": 60, "skip": 5}},
                                 "liquidity": {"weight": 1.0}})
    result = score(last_view(p), ["A", "B"], cfg)
    by = {s.symbol: s for s in result.scored}
    assert by["A"].composite == pytest.approx(0.75) and by["B"].composite == pytest.approx(0.25)
    assert by["A"].ranks == {"momentum": 1.0, "liquidity": 0.0}


def test_a_symbol_whose_factor_cannot_be_computed_is_excluded_not_scored_as_zero():
    p = panel(LONG=frame(np.linspace(100, 120, 300)), SHORT=frame(np.linspace(100, 120, 30)))
    cfg = ScoringConfig(factors={"momentum": {"weight": 1.0}})
    result = score(last_view(p), ["LONG", "SHORT"], cfg)
    assert [s.symbol for s in result.scored] == ["LONG"]
    assert result.excluded == {"SHORT": "factor 'momentum' could not be computed"}


@pytest.mark.parametrize("factors, message", [
    ({}, "at least one factor"),
    ({"astrology": {"weight": 1}}, "unknown factors"),
    ({"momentum": {"weight": 0}}, "greater than 0"),
    ({"momentum": {"weight": 1, "params": {"window": 5}}}, "no parameter"),
    ({"momentum": {"weight": 1, "params": {"lookback": 10, "skip": 10}}}, "skip < lookback"),
    ({"trend": {"weight": 1, "params": {"window": 0}}}, "positive"),
])
def test_invalid_scoring_configuration_is_refused(factors, message):
    with pytest.raises(ValidationError, match=message):
        ScoringConfig(factors=factors)


@pytest.mark.parametrize("weights, message", [
    ({"momentum": float("inf")}, "finite number"),
    ({"momentum": float("-inf")}, "finite number"),
    ({"momentum": float("nan")}, "finite number"),
    ({"momentum": 1e308, "trend": 1e308}, "total factor weight must be finite"),
])
def test_non_finite_weights_and_totals_are_refused(weights, message):
    with pytest.raises(ValidationError, match=message):
        ScoringConfig(factors={n: {"weight": w} for n, w in weights.items()})


def _two_symbols():
    return panel(A=frame(np.linspace(100, 130, 300)), B=frame(np.linspace(100, 110, 300)))


@pytest.mark.parametrize("weights", [{"momentum": float("inf")}, {"momentum": 1e308, "trend": 1e308},
                                     {"momentum": 0.0}])
def test_scoring_refuses_unvalidated_bad_weights(weights):
    # model_construct skips validation, standing in for any path that bypasses ScoringConfig checks.
    from sid_trading_firm.screening.scoring import FactorSpec

    cfg = ScoringConfig.model_construct(factors={n: FactorSpec.model_construct(weight=w, params={})
                                                 for n, w in weights.items()})
    with pytest.raises(ScoringError, match="finite and positive"):
        score(last_view(_two_symbols()), ["A", "B"], cfg)


@pytest.mark.parametrize("bad_rank", [float("nan"), float("inf"), -0.5, 1.5])
def test_non_finite_or_out_of_range_ranks_are_refused(monkeypatch, bad_rank):
    monkeypatch.setattr(scoring, "percentile_ranks", lambda values: dict.fromkeys(values, bad_rank))
    cfg = ScoringConfig(factors={"momentum": {"weight": 1.0}})
    with pytest.raises(ScoringError, match="rank for factor 'momentum'"):
        score(last_view(_two_symbols()), ["A", "B"], cfg)


@pytest.mark.parametrize("bad_composite", [float("nan"), float("inf"), 1.5, -0.1])
def test_a_non_finite_or_out_of_range_composite_is_refused(monkeypatch, bad_composite):
    # Finite positive weights with a finite total and ranks in [0, 1] cannot produce this; the
    # guard is defensive, so the weighted mean is replaced to reach it.
    monkeypatch.setattr(scoring, "_weighted_mean", lambda weights, ranks, total: bad_composite)
    cfg = ScoringConfig(factors={"momentum": {"weight": 1.0}})
    with pytest.raises(ScoringError, match="composite score"):
        score(last_view(_two_symbols()), ["A", "B"], cfg)
