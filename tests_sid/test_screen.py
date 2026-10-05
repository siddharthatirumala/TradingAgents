"""The screening funnel: bounded, budget-aware, explainable and reproducible."""

from decimal import Decimal

import numpy as np
import pytest

from sid_trading_firm.screening.filters import FilterConfig
from sid_trading_firm.screening.scoring import ScoringConfig
from sid_trading_firm.screening.screen import ScreenRefused, run_screen
from sid_trading_firm.screening.universe import Universe
from tests_sid.fakes import settings
from tests_sid.screening_data import frame, panel

pytestmark = pytest.mark.unit

N = 80
SYMBOLS = ["AAA", "BBB", "CCC", "DDD", "EEE", "FFF", "GGG"]


def universe(symbols=SYMBOLS, etfs=("SPY",)):
    members = [{"symbol": s, "asset_type": "common_stock"} for s in symbols]
    members += [{"symbol": e, "asset_type": "etf"} for e in etfs]
    return Universe.model_validate({"name": "t", "version": "v1", "source": "test", "as_of": "2026-01-01",
                                    "survivorship_note": "survivorship: test list", "members": members})


def data(with_missing=("GGG",)):
    """AAA strongest trend ... FFF weakest; FFF is also a penny stock; GGG has no data; SPY an ETF."""
    frames = {s: frame(np.linspace(100, 100 + 10 * (6 - i), N)) for i, s in enumerate(SYMBOLS)
              if s not in with_missing}
    frames["FFF"] = frame(np.linspace(2, 2.1, N))
    frames["SPY"] = frame(np.linspace(100, 200, N))   # would rank first if ETFs were candidates
    return panel(**frames)


FILTERS = FilterConfig(min_price=5)
SCORING = ScoringConfig(factors={"momentum": {"weight": 1.0, "params": {"lookback": 60, "skip": 5}}})


def screen(**kw):
    p = kw.pop("panel", None) or data()
    args = {"max_candidates": 10, "research_cost_per_candidate_usd": Decimal("0.80"),
            "budgets": settings().budgets}
    args.update(kw)
    return run_screen(universe(), p, p.calendar()[-1], FILTERS, SCORING, **args)


def test_the_funnel_is_counted_and_etfs_are_never_candidates():
    r = screen()
    assert r.funnel == {"universe": 8, "eligible_common_stocks": 7, "with_data": 6, "passed_filters": 5,
                        "scored": 5, "selected": 5}
    assert [s.symbol for s in r.selected] == ["AAA", "BBB", "CCC", "DDD", "EEE"]
    assert "SPY" not in {o.symbol for o in r.outcomes}
    assert r.missing_data == ["GGG"]
    rejected = {o.symbol: o.reasons for o in r.outcomes if not o.passed}
    assert list(rejected) == ["FFF"] and "price" in rejected["FFF"][0]
    assert "min_avg_dollar_volume" in r.disabled_filters
    assert "survivorship" in r.survivorship_note


def test_candidates_are_capped_by_the_smallest_limit_and_the_binding_limit_is_named():
    by_request = screen(max_candidates=2)
    assert len(by_request.selected) == 2 and by_request.cost["limited_by"] == "max_candidates"

    by_setting = screen(budgets=settings(max_ai_candidates_per_run=3).budgets)
    assert len(by_setting.selected) == 3 and by_setting.cost["limited_by"] == "budgets.max_ai_candidates_per_run"

    # The default $10/day budget covers four candidates at $2.50 and three at $2.99.
    by_budget = screen(research_cost_per_candidate_usd=Decimal("2.50"),
                       budgets=settings(max_ai_cost_per_run_usd=Decimal("3")).budgets)
    assert by_budget.cost["limit"] == 4
    by_budget = screen(research_cost_per_candidate_usd=Decimal("2.99"),
                       budgets=settings(max_ai_cost_per_run_usd=Decimal("3")).budgets)
    assert len(by_budget.selected) == 3
    assert by_budget.cost["limited_by"] == "daily AI budget / cost per candidate"
    assert by_budget.cost["estimated_total_usd"] == "8.97"


def test_a_candidate_costing_more_than_the_run_budget_refuses_the_screen():
    with pytest.raises(ScreenRefused, match="exceeds max_ai_cost_per_run_usd"):
        screen(research_cost_per_candidate_usd=Decimal("3.01"))


def test_a_daily_budget_below_one_candidate_refuses_the_screen():
    # Settings validation already keeps the run budget within the daily one, so this is the
    # screen's own defensive check; model_copy skips validation to reach it.
    budgets = settings().budgets.model_copy(update={"max_ai_cost_per_day_usd": Decimal("1")})
    with pytest.raises(ScreenRefused, match="cannot cover a single candidate"):
        screen(research_cost_per_candidate_usd=Decimal("2"), budgets=budgets)


@pytest.mark.parametrize("kw, message", [({"max_candidates": 0}, "at least 1"),
                                         ({"research_cost_per_candidate_usd": Decimal("0")}, "positive")])
def test_invalid_requests_are_refused(kw, message):
    with pytest.raises(ScreenRefused, match=message):
        screen(**kw)


def test_the_screen_is_reproducible_and_fingerprints_track_every_input():
    a, b = screen(), screen()
    assert [s.symbol for s in a.selected] == [s.symbol for s in b.selected]
    assert a.inputs_fingerprint == b.inputs_fingerprint
    assert screen(max_candidates=3).config_fingerprint != a.config_fingerprint
    assert screen(panel=data(with_missing=())).data_fingerprint != a.data_fingerprint


def test_a_screen_on_an_earlier_date_ignores_later_data():
    p = data()
    early = run_screen(universe(), p, p.calendar()[N - 10], FILTERS, SCORING, max_candidates=10,
                       research_cost_per_candidate_usd=Decimal("0.80"), budgets=settings().budgets)
    late_crash = {s: f.copy() for s, f in p.frames.items()}
    for f in late_crash.values():
        f.iloc[-5:] = f.iloc[-5:] * 0.01                   # only after the early screening date
    p2 = panel(**{s: f.reset_index() for s, f in late_crash.items()})
    early2 = run_screen(universe(), p2, p2.calendar()[N - 10], FILTERS, SCORING, max_candidates=10,
                        research_cost_per_candidate_usd=Decimal("0.80"), budgets=settings().budgets)
    assert [s.symbol for s in early.selected] == [s.symbol for s in early2.selected]
    assert [o.measures for o in early.outcomes] == [o.measures for o in early2.outcomes]
