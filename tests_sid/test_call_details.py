"""Per-call details in the ledger: structured method, tools, tool calls, and fallback detection."""

import copy
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from langchain_core.messages import AIMessage
from langchain_core.outputs import ChatGeneration, LLMResult

import tradingagents.dataflows.config as dataflows_config
from sid_trading_firm.llm import BudgetGuard, InMemoryUsageStore, UsageLedger
from sid_trading_firm.llm.pricing import CostStatus
from sid_trading_firm.llm.report import fallback_call_ids, render_markdown, summarize
from sid_trading_firm.llm.usage import LLMCallRecord
from sid_trading_firm.runtime import agent_context, new_run_id, run_context
from tests.test_graph_end_to_end import TRADE_DATE, _graph, offline  # noqa: F401
from tests_sid.fakes import FakeChatModel, settings
from tests_sid.test_upstream_metering import MeteredScriptedModel

pytestmark = pytest.mark.unit
T0 = datetime(2026, 10, 2, 14, 0, tzinfo=UTC)


def _ledger():
    s = settings()
    store = InMemoryUsageStore()
    return UsageLedger(BudgetGuard(s.budgets, s.pricing, store)), store


class StructuredFake(FakeChatModel):
    """Binds structured output the way langchain-anthropic's json_schema method does."""

    def with_structured_output(self, schema, **kwargs):
        return self.bind(ls_structured_output_format={"kwargs": {"method": "json_schema"},
                                                      "schema": {"title": "Decision"}})


def test_langchain_delivers_the_structured_method_to_the_ledger():
    ledger, store = _ledger()
    with run_context(), agent_context("portfolio_manager"):
        StructuredFake(callbacks=[ledger]).with_structured_output(dict).invoke("decide")
        FakeChatModel(callbacks=[ledger]).invoke("plain")
    structured, plain = store.records()
    assert structured.structured_method == "json_schema"
    assert plain.structured_method is None


def test_tools_offered_and_tool_calls_are_recorded():
    ledger, store = _ledger()
    lc_run = __import__("uuid").uuid4()
    with run_context(), agent_context("news_analyst"):
        ledger.on_chat_model_start({}, [[]], run_id=lc_run,
                                   metadata={"ls_provider": "anthropic", "ls_model_name": "claude-sonnet-5-5"},
                                   invocation_params={"tools": [{"name": "a"}, {"name": "b"}], "max_tokens": 100})
        message = AIMessage(content="", tool_calls=[{"name": "a", "args": {}, "id": "1"}],
                            usage_metadata={"input_tokens": 10, "output_tokens": 5, "total_tokens": 15})
        ledger.on_llm_end(LLMResult(generations=[[ChatGeneration(message=message)]]), run_id=lc_run)
    (rec,) = store.records()
    assert (rec.tools_offered, rec.tool_calls, rec.structured_method) == (2, 1, None)


def _rec(agent, minute, *, structured=None, tools=0, tool_calls=0, run=None, cost="0.01"):
    at = T0 + timedelta(minutes=minute)
    return LLMCallRecord(
        run_id=run or RUN, agent=agent, provider="anthropic", model="claude-sonnet-5-5", started_at=at,
        finished_at=at, latency_ms=1.0, success=True, input_tokens=100, output_tokens=10,
        cache_read_tokens=0, cache_write_tokens=0, usage_available=True, estimated_cost_usd=Decimal(cost),
        cost_status=CostStatus.PRICED, estimated_input_tokens=100, prompt_chars=300,
        structured_method=structured, tools_offered=tools, tool_calls=tool_calls)


RUN = new_run_id()


def test_a_plain_call_after_a_structured_call_by_the_same_agent_is_a_fallback():
    structured = _rec("trader", 1, structured="function_calling")
    retry = _rec("trader", 2, cost="0.02")
    other = _rec("bull_researcher", 3)
    assert fallback_call_ids([retry, structured, other]) == {retry.call_id}

    summary = summarize([structured, retry, other])
    assert summary.total.fallback_calls == 1
    assert summary.total.fallback_cost_usd == Decimal("0.02")
    assert summary.by_agent["trader"].structured_calls == 1
    assert "fallback (free text)" in render_markdown(summary)


def test_tool_rounds_text_only_agents_and_other_runs_are_not_fallbacks():
    records = [
        _rec("trader", 1, structured="json_schema"),
        _rec("trader", 2, tools=3, tool_calls=1),           # a tool round, not a retry
        _rec("news_analyst", 3), _rec("news_analyst", 4),    # never structured
        _rec("trader", 5, run=new_run_id()),                 # another run
    ]
    assert fallback_call_ids(records) == set()
    assert summarize(records).total.tool_rounds == 1


@pytest.fixture
def _restore_upstream_config():
    saved = copy.deepcopy(dataflows_config._config)
    yield
    dataflows_config._config = saved


@pytest.mark.usefixtures("offline", "_restore_upstream_config")
def test_an_upstream_run_reports_its_tool_rounds(tmp_path, monkeypatch):
    ledger, store = _ledger()
    graph = _graph(tmp_path, monkeypatch, MeteredScriptedModel(callbacks=[ledger]))
    with run_context() as run:
        graph.propagate("NVDA", TRADE_DATE)
    summary = summarize(store.records(run.run_id))
    # The scripted model calls every tool in one round per tool-using analyst.
    assert {a: line.tool_rounds for a, line in summary.by_agent.items() if line.tool_rounds} == {
        "technical_analyst": 1, "news_analyst": 1, "fundamentals_analyst": 1}
    assert summary.total.fallback_calls == 0


def test_a_structured_call_is_not_a_tool_round_even_though_it_calls_its_schema_tool():
    records = [_rec("trader", 1, structured="function_calling", tools=1, tool_calls=1),
               _rec("news_analyst", 2, tools=4, tool_calls=2)]
    summary = summarize(records)
    assert summary.total.tool_rounds == 1
    assert summary.by_agent["trader"].tool_rounds == 0


def test_calls_that_reach_the_output_cap_are_flagged():
    capped = _rec("bear_researcher", 1)
    capped = capped.__class__(**{**capped.__dict__, "output_tokens": 8192})
    summary = summarize([capped, _rec("bull_researcher", 2)])
    text = render_markdown(summary, output_cap=8192)
    assert "hit output cap" in text
    assert "1 call(s) reached the 8192-token output cap" in text
    assert "hit output cap" not in render_markdown(summary)          # no cap given, no flag
