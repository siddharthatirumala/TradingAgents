"""The budget guard fails closed: limits are checked before each call and stops are sticky."""

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from sid_trading_firm.config import ConfigError
from sid_trading_firm.llm import (
    AIBudgetStop,
    BudgetExceeded,
    BudgetGuard,
    InMemoryUsageStore,
    LedgerUnavailable,
    UnpricedModel,
    UsageLedger,
)
from sid_trading_firm.llm.pricing import CostStatus
from sid_trading_firm.llm.usage import LLMCallRecord
from sid_trading_firm.runtime import agent_context, new_run_id, run_context
from tests_sid.fakes import FakeChatModel, settings

pytestmark = pytest.mark.unit

NOW = datetime(2026, 10, 5, 15, 0, tzinfo=UTC)


def _guard(store=None, **budgets):
    s = settings(**budgets)
    return BudgetGuard(s.budgets, s.pricing, store if store is not None else InMemoryUsageStore(),
                       clock=lambda: NOW)


def _authorize(guard, run_id, agent="cio", chars=3000, out=1000, model="claude-sonnet-5-5",
               provider="anthropic"):
    # 3000 chars -> 1000 estimated input tokens; worst case on Sonnet = 1000*2 + 1000*10 per 1e6 = $0.012
    return guard.authorize(run_id=run_id, agent=agent, provider=provider, model=model,
                           prompt_chars=chars, max_output_tokens=out)


def _record(auth, cost="0.004", at=NOW, tokens=(1000, 200), success=True):
    return LLMCallRecord(
        run_id=auth.run_id, agent=auth.agent, provider="anthropic", model="claude-sonnet-5-5",
        started_at=at, finished_at=at, latency_ms=1.0, success=success,
        input_tokens=tokens[0] if tokens else None, output_tokens=tokens[1] if tokens else None,
        cache_read_tokens=0, cache_write_tokens=0, usage_available=tokens is not None,
        estimated_cost_usd=Decimal(cost) if cost is not None else None,
        cost_status=CostStatus.PRICED if cost is not None else CostStatus.NO_USAGE,
        estimated_input_tokens=auth.estimated_input_tokens, prompt_chars=3000, call_id=auth.call_id)


def test_the_worst_case_is_reserved_before_the_call():
    guard = _guard()
    auth = _authorize(guard, new_run_id())
    assert (auth.estimated_input_tokens, auth.estimated_output_tokens) == (1000, 1000)
    assert auth.reserved_usd == Decimal("0.012")


def test_a_call_that_could_exceed_the_run_budget_is_refused_and_says_why():
    guard = _guard(max_ai_cost_per_run_usd="0.02")
    run = new_run_id()
    first = _authorize(guard, run)
    guard.record(first, _record(first, cost="0.010"))

    with pytest.raises(BudgetExceeded) as stop:
        _authorize(guard, run)             # 0.010 spent + 0.012 worst case > 0.02

    event = stop.value.event
    assert (event.reason, event.limit, event.run_id) == ("run_cost", "max_ai_cost_per_run_usd", run)
    assert Decimal(event.limit_value) == Decimal("0.02")
    assert guard.stopped(run) == event
    assert guard.stops == [event]


def test_parallel_reservations_count_against_the_budget():
    guard = _guard(max_ai_cost_per_run_usd="0.02")
    run = new_run_id()
    _authorize(guard, run)                 # in flight, nothing recorded yet
    with pytest.raises(BudgetExceeded):
        _authorize(guard, run)


def test_a_stop_is_sticky_for_the_whole_run():
    guard = _guard(max_ai_cost_per_run_usd="0.02")
    run = new_run_id()
    guard.record(a := _authorize(guard, run), _record(a, cost="0.015"))
    with pytest.raises(BudgetExceeded):
        _authorize(guard, run)
    with pytest.raises(BudgetExceeded):
        _authorize(guard, run, agent="trader", chars=3, out=1)   # even a tiny call
    # Another run is unaffected.
    _authorize(guard, new_run_id())


def test_the_day_budget_counts_other_runs_today_but_not_yesterday():
    store = InMemoryUsageStore()
    guard = _guard(store=store, max_ai_cost_per_run_usd="1", max_ai_cost_per_day_usd="1")
    old = _authorize(guard, new_run_id())
    guard.record(old, _record(old, cost="0.995", at=NOW - timedelta(days=1)))
    _authorize(guard, new_run_id())        # yesterday's spend does not count

    earlier = _authorize(guard, new_run_id())
    guard.record(earlier, _record(earlier, cost="0.990"))
    with pytest.raises(BudgetExceeded) as stop:
        _authorize(guard, new_run_id())
    assert stop.value.event.reason == "day_cost"


def test_iterations_per_agent_are_capped():
    guard = _guard(max_agent_iterations=2)
    run = new_run_id()
    for _ in range(2):
        guard.record(a := _authorize(guard, run, agent="news_analyst"), _record(a))
    with pytest.raises(BudgetExceeded) as stop:
        _authorize(guard, run, agent="news_analyst")
    assert stop.value.event.reason == "agent_iterations"
    assert stop.value.event.agent == "news_analyst"


def test_tokens_per_agent_are_capped_using_actual_usage():
    guard = _guard(max_llm_tokens_per_agent=5000)
    run = new_run_id()
    guard.record(a := _authorize(guard, run), _record(a, tokens=(3000, 500)))   # 3500 used
    with pytest.raises(BudgetExceeded) as stop:
        _authorize(guard, run)                                                  # +2000 estimated
    assert stop.value.event.reason == "agent_tokens"


def test_an_unpriced_model_is_refused_and_cannot_be_allowed():
    with pytest.raises(UnpricedModel):
        _authorize(_guard(), new_run_id(), model="mystery-model")
    # An unpriced call cannot be held to the lifetime budget, so allowing one is refused at load.
    with pytest.raises(ConfigError, match="allow_unpriced_models cannot be true"):
        settings(allow_unpriced_models=True)


def test_an_unreadable_ledger_stops_the_call():
    class Broken(InMemoryUsageStore):
        def spent_usd(self, **kwargs):
            raise ConnectionError("database is down")

    with pytest.raises(LedgerUnavailable):
        _authorize(_guard(store=Broken()), new_run_id())


def test_a_call_that_cannot_be_recorded_stops_the_run():
    class ReadOnly(InMemoryUsageStore):
        def add(self, record):
            raise ConnectionError("database is down")

    guard = _guard(store=ReadOnly())
    run = new_run_id()
    auth = _authorize(guard, run)
    with pytest.raises(LedgerUnavailable):
        guard.record(auth, _record(auth))
    with pytest.raises(BudgetExceeded):
        _authorize(guard, run)


def test_overshoot_after_a_call_stops_the_next_one():
    guard = _guard(max_ai_cost_per_run_usd="0.02")
    run = new_run_id()
    auth = _authorize(guard, run)
    guard.record(auth, _record(auth, cost="0.05"))     # provider used more than estimated
    assert guard.stopped(run).reason == "run_cost"
    with pytest.raises(BudgetExceeded):
        _authorize(guard, run, chars=3, out=1)


def test_stop_listeners_are_told_and_a_failing_listener_does_not_hide_the_stop():
    guard = _guard(max_agent_iterations=1)
    heard = []
    guard.add_stop_listener(heard.append)
    guard.add_stop_listener(lambda e: 1 / 0)
    run = new_run_id()
    _authorize(guard, run)
    with pytest.raises(BudgetExceeded):
        _authorize(guard, run)
    assert [e.reason for e in heard] == ["agent_iterations"]


def test_a_budget_stop_is_not_swallowed_by_except_exception():
    guard = _guard(max_agent_iterations=1)
    run = new_run_id()
    _authorize(guard, run)
    with pytest.raises(AIBudgetStop):
        try:
            _authorize(guard, run)
        except Exception:                  # what upstream fallbacks do
            pytest.fail("budget stop was caught as an ordinary error")


def test_through_the_ledger_a_refused_call_never_reaches_the_model():
    s = settings(max_agent_iterations=1)
    guard = BudgetGuard(s.budgets, s.pricing, InMemoryUsageStore())
    model = FakeChatModel(callbacks=[UsageLedger(guard)])
    with run_context(), agent_context("cio"):
        model.invoke("first")
        with pytest.raises(BudgetExceeded):
            model.invoke("second")
    assert len(model.calls) == 1
