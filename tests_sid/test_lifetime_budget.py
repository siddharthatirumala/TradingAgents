"""The lifetime AI budget: cumulative ledger spend, a permanent stop at the cap, retries and
concurrent calls accounted for, and no authorised call able to take spend past the cap.

The per-day cap never exceeds the lifetime cap, so the lifetime cap binds across days.
Tests therefore seed earlier days' spend, or use one guard per caller (each process has
its own guard; the ledger is shared), so the lifetime check is what refuses.

Worst case of the test call: 1000 estimated input tokens (3000 chars) and 1000 output tokens
on Sonnet ($2 / $10 per million) = $0.012.
"""

import random
import threading
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from sid_trading_firm.llm import (
    BudgetExceeded,
    BudgetGuard,
    InMemoryUsageStore,
    LedgerUnavailable,
    LifetimeBudgetExhausted,
)
from sid_trading_firm.llm.ledger import _schema_chars
from sid_trading_firm.llm.models import _client_kwargs
from sid_trading_firm.llm.pricing import CostStatus
from sid_trading_firm.llm.usage import JsonlUsageStore, LLMCallRecord
from sid_trading_firm.runtime import new_run_id
from tests_sid.fakes import settings

pytestmark = pytest.mark.unit

NOW = datetime(2026, 10, 8, 15, 0, tzinfo=UTC)
WORST = Decimal("0.012")


def capped(cap="0.05", store=None):
    s = settings(max_ai_cost_per_run_usd=cap, max_ai_cost_per_day_usd=cap, max_ai_cost_total_usd=cap,
                 max_agent_iterations=10_000, max_llm_tokens_per_agent=10**9)
    return BudgetGuard(s.budgets, s.pricing, store if store is not None else InMemoryUsageStore(),
                       clock=lambda: NOW)


def authorize(guard, run=None, agent="cio"):
    return guard.authorize(run_id=run or new_run_id(), agent=agent, provider="anthropic",
                           model="claude-sonnet-5-5", prompt_chars=3000, max_output_tokens=1000)


def record(auth, cost="0.004", success=True, at=NOW):
    return LLMCallRecord(
        run_id=auth.run_id, agent=auth.agent, provider="anthropic", model="claude-sonnet-5-5",
        started_at=at, finished_at=at, latency_ms=1.0, success=success,
        input_tokens=1000 if cost is not None else None, output_tokens=200 if cost is not None else None,
        cache_read_tokens=0, cache_write_tokens=0, usage_available=cost is not None,
        estimated_cost_usd=Decimal(cost) if cost is not None else None,
        cost_status=CostStatus.PRICED if cost is not None else CostStatus.NO_USAGE,
        estimated_input_tokens=auth.estimated_input_tokens, prompt_chars=3000, call_id=auth.call_id)


# ------------------------------------------------------------------ cumulative spend and the cap

def test_the_default_lifetime_cap_is_30_dollars():
    assert settings().budgets.max_ai_cost_total_usd == Decimal("30.00")


def test_spend_already_in_the_ledger_counts_against_the_cap():
    store = InMemoryUsageStore()
    for day in range(3):                                                # $29.985 over three earlier days
        seed = capped("30.00", store)
        a = authorize(seed)
        seed.record(a, record(a, cost="9.995", at=NOW - timedelta(days=3 - day)))
    guard = capped("30.00", store)                                      # a later process, same ledger
    a = authorize(guard)                                                # 29.985 + 0.012 <= 30: allowed
    guard.record(a, record(a, cost="0.01"))
    with pytest.raises(LifetimeBudgetExhausted) as stop:
        authorize(guard)                                                # 29.995 + 0.012 > 30
    assert stop.value.event.reason == "lifetime_cost" and stop.value.event.limit == "max_ai_cost_total_usd"


def test_the_stop_is_permanent_for_every_run_and_every_later_process(tmp_path):
    store = JsonlUsageStore(tmp_path / "usage.jsonl")
    for day in range(4):                                                # $0.048 over four earlier days
        seed = capped(store=store)
        seed.record(a := authorize(seed), record(a, cost="0.012", at=NOW - timedelta(days=4 - day)))
    guard = capped(store=store)
    with pytest.raises(LifetimeBudgetExhausted):
        authorize(guard)                                                # would be $0.060
    with pytest.raises(LifetimeBudgetExhausted):
        authorize(guard, run=new_run_id(), agent="bull_researcher")     # another run: still stopped
    later = capped(store=JsonlUsageStore(tmp_path / "usage.jsonl"))     # a new process reading the file
    with pytest.raises(LifetimeBudgetExhausted, match="already exhausted"):
        later.authorize(run_id=new_run_id(), agent="cio", provider="anthropic", model="claude-sonnet-5-5",
                        prompt_chars=3, max_output_tokens=1)            # even a tiny call
    assert (tmp_path / "usage.jsonl.lifetime-exhausted").is_file()


def test_open_reservations_and_unknown_costs_are_charged_at_their_worst_case():
    store = InMemoryUsageStore()
    guard = capped(store=store)
    in_flight = authorize(guard)                                        # no record yet: open
    assert store.lifetime_spent_usd() == WORST
    failed = authorize(guard)
    guard.record(failed, record(failed, cost=None, success=False))      # unknown cost: worst case kept
    no_usage = authorize(guard)
    guard.record(no_usage, record(no_usage, cost=None, success=True))
    assert store.lifetime_spent_usd() == 3 * WORST
    released = authorize(guard)
    guard.release(released)                                             # never reached the provider
    assert store.lifetime_spent_usd() == 3 * WORST
    guard.record(in_flight, record(in_flight, cost="0.004"))            # actual replaces the reservation
    assert store.lifetime_spent_usd() == 2 * WORST + Decimal("0.004")


def test_a_call_that_never_reports_back_stays_charged_for_later_callers():
    store = InMemoryUsageStore()
    crashed = capped(store=store)
    for _ in range(4):
        authorize(crashed)                                              # 4 x $0.012 open, never recorded
    with pytest.raises(LifetimeBudgetExhausted):
        authorize(capped(store=store))


# ------------------------------------------------------------------ retries

def test_model_clients_are_built_without_sdk_retries():
    s = settings()
    for tier in s.models.tiers.values():
        assert _client_kwargs(tier)["max_retries"] == 0


def test_an_application_retry_is_a_separate_call_and_is_charged_again():
    store = InMemoryUsageStore()
    guard = capped(store=store)
    first = authorize(guard)
    guard.record(first, record(first, cost=None, success=False))        # failed attempt, cost unknown
    retry = authorize(guard)                                            # the retry passes the guard again
    guard.record(retry, record(retry, cost="0.004"))
    assert store.lifetime_spent_usd() == WORST + Decimal("0.004")


def test_tool_and_schema_text_counts_in_the_worst_case():
    kwargs = {"invocation_params": {"tools": [{"name": "get_prices", "description": "x" * 400}]},
              "options": {"ls_structured_output_format": {"schema": {"title": "Decision", "y": "z" * 200}}}}
    assert _schema_chars(kwargs) > 600
    assert _schema_chars({}) == 0


# ------------------------------------------------------------------ concurrency

def test_concurrent_calls_cannot_jointly_pass_the_cap():
    store = InMemoryUsageStore()                                        # one ledger, room for 4 worst cases
    guards = [capped("0.05", store) for _ in range(32)]                 # one guard per caller (process)
    start = threading.Barrier(32)
    allowed, refused = [], []

    def worker(guard):
        start.wait()
        try:
            allowed.append(authorize(guard))
        except LifetimeBudgetExhausted:
            refused.append(1)

    threads = [threading.Thread(target=worker, args=(g,)) for g in guards]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert len(allowed) == 4 and len(refused) == 28
    assert store.lifetime_spent_usd() == 4 * WORST <= Decimal("0.05")


def test_separate_guards_on_one_ledger_share_the_cap():
    store = InMemoryUsageStore()                                        # two guards, one ledger
    a, b = capped(store=store), capped(store=store)
    granted = 0
    for _ in range(10):
        for guard in (a, b):
            try:
                authorize(guard)
                granted += 1
            except LifetimeBudgetExhausted:
                pass
    assert granted == 4 and store.lifetime_spent_usd() <= Decimal("0.05")


# ------------------------------------------------------------------ no call can exceed the cap

@pytest.mark.parametrize("seed", range(12))
def test_no_sequence_of_calls_takes_spend_past_the_cap(seed):
    """Random calls, failures, unknown costs, releases and crashes; actual cost never above the worst case."""
    rng = random.Random(seed)
    cap = Decimal("0.25")
    store = InMemoryUsageStore()
    guards = [capped(str(cap), store) for _ in range(3)]
    stopped = False
    for _ in range(200):
        guard = rng.choice(guards)
        try:
            auth = authorize(guard)
        except BudgetExceeded:                                          # lifetime (or day) cap refused it
            stopped = True
            continue
        outcome = rng.random()
        if outcome < 0.6:
            guard.record(auth, record(auth, cost=str(WORST * Decimal(rng.randint(0, 100)) / 100)))
        elif outcome < 0.75:
            guard.record(auth, record(auth, cost=None, success=rng.random() < 0.5))
        elif outcome < 0.9:
            guard.release(auth)
        # else: the call never reports back (crash); its reservation stays open
        assert store.lifetime_spent_usd() <= cap
    actual = sum((r.estimated_cost_usd or Decimal(0)) for r in store.records())
    assert actual <= cap and stopped


def test_a_provider_billing_above_the_worst_case_stops_everything_at_once():
    store = InMemoryUsageStore()
    guard = capped("0.05", store)
    a = authorize(guard)
    guard.record(a, record(a, cost="0.06"))                             # billed above the worst case
    assert store.lifetime_exhausted()
    with pytest.raises(LifetimeBudgetExhausted):
        authorize(guard, run=new_run_id())


def test_an_unreadable_lifetime_ledger_refuses_the_call():
    class Broken(InMemoryUsageStore):
        def try_reserve(self, **kwargs):
            raise ConnectionError("database is down")

    with pytest.raises(LedgerUnavailable):
        authorize(capped(store=Broken()))
