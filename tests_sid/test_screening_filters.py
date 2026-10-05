"""Screening filters: explicit thresholds, point-in-time, every rejection explained."""

import numpy as np
import pandas as pd
import pytest
from pydantic import ValidationError

from sid_trading_firm.screening.filters import FilterConfig, evaluate_filters, screen_date_is_valid
from tests_sid.screening_data import frame, panel, walk

pytestmark = pytest.mark.unit


def view_of(closes, volume=1_000_000, as_of=None, start="2025-01-01"):
    p = panel(X=frame(closes, volume, start))
    return p.view(as_of or p.calendar()[-1])


def test_with_no_thresholds_everything_passes_and_every_filter_is_reported_disabled():
    cfg = FilterConfig()
    out = evaluate_filters(view_of([10.0] * 30), "X", cfg)
    assert out.passed and out.reasons == []
    assert cfg.disabled() == ["min_price", "min_avg_dollar_volume", "max_annualised_volatility",
                              "min_history_days", "max_data_age_days"]


def test_price_liquidity_and_history_thresholds():
    # 30 bars at $4 with 100k shares a day: ADV = $400k.
    v = view_of([4.0] * 30, volume=100_000)
    out = evaluate_filters(v, "X", FilterConfig(min_price=5, min_avg_dollar_volume=1_000_000, min_history_days=60))
    assert not out.passed
    assert out.measures["price"] == 4.0 and out.measures["avg_dollar_volume"] == 400_000
    assert len(out.reasons) == 3
    assert any("price 4.00 < 5" in r for r in out.reasons)
    assert any("average dollar volume 400,000" in r for r in out.reasons)
    assert any("history 30 bars < 60" in r for r in out.reasons)
    assert evaluate_filters(v, "X", FilterConfig(min_price=3, min_avg_dollar_volume=300_000,
                                                 min_history_days=30)).passed


def test_volatility_threshold_uses_the_configured_window():
    calm = view_of(walk(100, 0.0, 0.002, seed=1))
    wild = view_of(walk(100, 0.0, 0.05, seed=2))
    cfg = FilterConfig(max_annualised_volatility=0.30)
    assert evaluate_filters(calm, "X", cfg).passed
    out = evaluate_filters(wild, "X", cfg)
    assert not out.passed and "annualised volatility" in out.reasons[0]
    assert out.measures["annualised_volatility"] > 0.30


def test_too_little_data_to_measure_fails_an_enabled_filter_but_not_a_disabled_one():
    short = view_of([10.0] * 10)
    assert evaluate_filters(short, "X", FilterConfig()).passed
    out = evaluate_filters(short, "X", FilterConfig(min_avg_dollar_volume=1, max_annualised_volatility=1))
    assert not out.passed
    assert any("liquidity" in r for r in out.reasons) and any("volatility" in r for r in out.reasons)


def test_stale_data_is_rejected():
    p = panel(X=frame([10.0] * 30))
    last = p.calendar()[-1]
    later = last + pd.Timedelta(days=10)
    out = evaluate_filters(p.view(later), "X", FilterConfig(max_data_age_days=5))
    assert not out.passed and out.measures["data_age_days"] == 10 and "stale" in out.reasons[0]
    assert evaluate_filters(p.view(last), "X", FilterConfig(max_data_age_days=0)).passed


def test_filters_never_read_past_the_screening_date():
    # A crash after the screening date must not affect the outcome.
    closes = np.r_[np.full(40, 10.0), np.full(20, 0.5)]
    p = panel(X=frame(closes))
    view = p.view(p.calendar()[39])
    out = evaluate_filters(view, "X", FilterConfig(min_price=5))
    assert out.passed and out.measures["price"] == 10.0
    assert view.max_date_served == p.calendar()[39]


def test_no_data_before_the_screening_date():
    p = panel(X=frame([10.0] * 5, start="2026-01-05"))
    out = evaluate_filters(p.view("2025-12-31"), "X", FilterConfig())
    assert not out.passed and "no price data" in out.reasons[0]


@pytest.mark.parametrize("field, value", [("min_price", 0), ("min_avg_dollar_volume", -1),
                                          ("min_history_days", 1), ("liquidity_window", 1),
                                          ("unknown", 3)])
def test_invalid_thresholds_are_refused(field, value):
    with pytest.raises(ValidationError):
        FilterConfig(**{field: value})


def test_a_future_screening_date_is_refused():
    with pytest.raises(ValueError, match="future"):
        screen_date_is_valid(pd.Timestamp.today() + pd.Timedelta(days=3))
