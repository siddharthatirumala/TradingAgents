"""The usage ledger: what each model call records, and how it is attributed."""

import contextvars
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, date, datetime
from decimal import Decimal

import pytest

from sid_trading_firm.llm import (
    BudgetGuard,
    InMemoryUsageStore,
    JsonlUsageStore,
    NoRunForCall,
    UsageLedger,
)
from sid_trading_firm.llm.ledger import UNATTRIBUTED, resolve_agent
from sid_trading_firm.llm.pricing import CostStatus
from sid_trading_firm.runtime import agent_context, run_context
from tests_sid.fakes import FakeChatModel, settings

pytestmark = pytest.mark.unit


def _ledger(store=None, **budgets):
    s = settings(**budgets)
    store = store if store is not None else InMemoryUsageStore()
    guard = BudgetGuard(s.budgets, s.pricing, store)
    return UsageLedger(guard), guard, store


def test_a_call_is_recorded_with_tokens_cost_latency_and_attribution():
    ledger, guard, store = _ledger()
    model = FakeChatModel(callbacks=[ledger])

    with run_context(instrument="NVDA") as run, agent_context("bull_researcher"):
        model.invoke("make the bull case")

    (rec,) = store.records()
    assert rec.run_id == run.run_id
    assert (rec.agent, rec.provider, rec.model) == ("bull_researcher", "anthropic", "claude-sonnet-5-5")
    assert (rec.input_tokens, rec.output_tokens, rec.total_tokens) == (1000, 200, 1200)
    assert rec.usage_available and rec.success
    assert rec.cost_status == CostStatus.PRICED
    assert rec.estimated_cost_usd == Decimal("0.004")
    assert rec.latency_ms >= 0
    assert rec.started_at <= rec.finished_at
    assert rec.prompt_chars == len("make the bull case")
    assert guard.run_spend(run.run_id) == Decimal("0.004")


def test_cache_usage_is_recorded():
    ledger, _, store = _ledger()
    usage = {"input_tokens": 1000, "output_tokens": 10, "total_tokens": 1010,
             "input_token_details": {"cache_read": 900, "cache_creation": 50}}
    with run_context(), agent_context("cio"):
        FakeChatModel(callbacks=[ledger], usage=usage).invoke("x")
    (rec,) = store.records()
    assert (rec.cache_read_tokens, rec.cache_write_tokens) == (900, 50)


def test_missing_usage_is_recorded_as_unknown_and_budgeted_conservatively():
    ledger, guard, store = _ledger()
    with run_context() as run, agent_context("cio"):
        FakeChatModel(callbacks=[ledger], usage=None).invoke("x")

    (rec,) = store.records()
    assert not rec.usage_available
    assert rec.input_tokens is None and rec.output_tokens is None and rec.total_tokens is None
    assert rec.estimated_cost_usd is None and rec.cost_status == CostStatus.NO_USAGE
    # Unknown is not free: the guard counts the pre-call worst case.
    assert guard.run_spend(run.run_id) > 0


def test_a_failed_call_is_recorded_and_the_error_still_reaches_the_caller():
    ledger, _, store = _ledger()
    with run_context(), agent_context("cio"), pytest.raises(RuntimeError, match="provider down"):
        FakeChatModel(callbacks=[ledger], fail=True).invoke("x")

    (rec,) = store.records()
    assert not rec.success and rec.error_type == "RuntimeError"
    assert "SECRETSECRET" not in rec.error_message
    assert rec.input_tokens is None


def test_a_call_outside_any_run_is_refused_before_reaching_the_model():
    ledger, _, store = _ledger()
    model = FakeChatModel(callbacks=[ledger])
    with pytest.raises(NoRunForCall):
        model.invoke("x")
    assert model.calls == [] and store.records() == []


@pytest.mark.parametrize("metadata, expected", [
    ({"langgraph_node": "Bull Researcher", "checkpoint_ns": "Bull Researcher:abc"}, "bull_researcher"),
    ({"langgraph_node": "agent", "checkpoint_ns": "Market Analyst:123|agent:456"}, "technical_analyst"),
    ({"langgraph_node": "wrap_up", "checkpoint_ns": "News Analyst:1|wrap_up:2"}, "news_analyst"),
    ({"langgraph_node": "Memory Log"}, "reflector"),
    ({"langgraph_node": "Somebody New"}, UNATTRIBUTED),
    ({}, UNATTRIBUTED),
])
def test_upstream_graph_nodes_are_attributed_to_agents(metadata, expected):
    assert resolve_agent(metadata)[0] == expected


def test_an_explicit_agent_context_wins_over_graph_metadata():
    with agent_context("cio"):
        assert resolve_agent({"langgraph_node": "Trader"})[0] == "cio"


def test_concurrent_calls_are_each_recorded_once():
    ledger, _, store = _ledger()
    model = FakeChatModel(callbacks=[ledger])

    def call(i):
        with agent_context("technical_analyst" if i % 2 else "news_analyst"):
            model.invoke(f"call {i}")

    with run_context() as run, ThreadPoolExecutor(8) as pool:
        # Each task gets its own copy of the caller's context, taken here, not in the worker.
        futures = [pool.submit(contextvars.copy_context().run, call, i) for i in range(10)]
        for future in futures:
            future.result()

    records = store.records(run.run_id)
    assert len(records) == 10
    assert len({r.call_id for r in records}) == 10
    assert {r.agent for r in records} == {"technical_analyst", "news_analyst"}


def test_jsonl_store_round_trips_and_sums_by_run_and_day(tmp_path):
    store = JsonlUsageStore(tmp_path / "usage.jsonl")
    ledger, _, _ = _ledger(store=store)
    with run_context() as run, agent_context("cio"):
        FakeChatModel(callbacks=[ledger]).invoke("a")
        FakeChatModel(callbacks=[ledger], usage=None).invoke("b")

    reread = JsonlUsageStore(tmp_path / "usage.jsonl")
    records = reread.records(run.run_id)
    assert [r.usage_available for r in records] == [True, False]
    assert reread.spent_usd(run_id=run.run_id) == Decimal("0.004")
    assert reread.spent_usd(day=datetime.now(UTC).date()) == Decimal("0.004")
    assert reread.spent_usd(day=date(2000, 1, 1)) == 0
