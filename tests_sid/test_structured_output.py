"""Structured output on Claude: native JSON Schema where forced tool use is unavailable.

The model under test is upstream's real ``NormalizedChatAnthropic`` with only its
network call replaced, so LangChain's binding, request shaping and parsing all run.
"""

import json
import warnings

import pytest
from langchain_core.messages import AIMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from pydantic import Field

from sid_trading_firm.llm import BudgetGuard, InMemoryUsageStore, UsageLedger
from sid_trading_firm.llm.report import summarize
from sid_trading_firm.llm.structured import (
    StructuredOutputError,
    invoke_structured,
    native_structured_output_method,
)
from sid_trading_firm.runtime import agent_context, run_context
from tests_sid.fakes import FakeChatModel, settings
from tradingagents.agents import schemas
from tradingagents.agents.structured import invoke_structured_or_freetext
from tradingagents.llm_clients import anthropic_client
from tradingagents.llm_clients.anthropic_client import (
    NormalizedChatAnthropic,
    structured_output_method,
    supports_forced_tool_choice,
)

pytestmark = pytest.mark.unit

DECISION = {"rating": "Overweight", "executive_summary": "Add gradually.",
            "investment_thesis": "Trend and earnings agree.", "price_target": 210.0, "time_horizon": "3-6 months"}
USAGE = {"input_tokens": 1000, "output_tokens": 200, "total_tokens": 1200}


class ScriptedClaude(NormalizedChatAnthropic):
    """Upstream's Anthropic chat model with the HTTP call replaced by scripted replies."""

    replies: list = Field(default_factory=list)
    requests: list = Field(default_factory=list)

    def _generate(self, messages, stop=None, run_manager=None, **kwargs):
        self.requests.append(kwargs)
        reply = self.replies.pop(0)
        message = reply if isinstance(reply, AIMessage) else AIMessage(content=reply)
        message.usage_metadata = dict(USAGE)
        return ChatResult(generations=[ChatGeneration(message=message)])


def claude(model="claude-sonnet-5-5", replies=(), callbacks=None):
    return ScriptedClaude(model=model, api_key="placeholder", max_tokens=8192,
                          replies=list(replies), callbacks=callbacks)


def _metered(model_name="claude-sonnet-5-5", replies=()):
    s = settings()
    store = InMemoryUsageStore()
    ledger = UsageLedger(BudgetGuard(s.budgets, s.pricing, store))
    return claude(model_name, replies, callbacks=[ledger]), store


# ------------------------------------------------------- one capability table

@pytest.mark.parametrize("model, forced, method", [
    ("claude-sonnet-5-5", False, "json_schema"),
    ("claude-opus-5-5", False, "json_schema"),
    ("claude-fable-5-1", False, "json_schema"),
    ("claude-sonnet-5", True, "function_calling"),
    ("claude-haiku-4-5", True, "function_calling"),
    ("claude-opus-5", True, "function_calling"),
])
def test_one_function_decides_the_structured_output_method(model, forced, method):
    assert supports_forced_tool_choice(model) is forced
    assert structured_output_method(model) == method


def test_the_fallback_table_agrees_when_langchain_stops_exposing_its_check(monkeypatch):
    monkeypatch.setattr(anthropic_client, "_langchain_anthropic", object())
    assert structured_output_method("claude-sonnet-5-5") == "json_schema"
    assert structured_output_method("claude-sonnet-5") == "function_calling"


# ------------------------------------------------ what the adapter now sends

def _binding_kwargs(runnable):
    """The keyword arguments bound onto the chat model inside a structured-output runnable."""
    first = runnable.first if hasattr(runnable, "first") else runnable
    return first.kwargs


def test_sonnet_5_5_binds_native_json_schema_and_no_forced_tool():
    with warnings.catch_warnings():
        warnings.simplefilter("error")      # the forced-tool-calling warning must not fire
        bound = claude().with_structured_output(schemas.PortfolioDecision)
    kwargs = _binding_kwargs(bound)
    assert kwargs["output_config"]["format"]["type"] == "json_schema"
    assert "tools" not in kwargs and "tool_choice" not in kwargs


def test_models_with_forced_tool_choice_keep_their_existing_behaviour():
    kwargs = _binding_kwargs(claude("claude-sonnet-5").with_structured_output(schemas.PortfolioDecision))
    assert kwargs["tool_choice"]["type"] == "tool"
    assert "output_config" not in kwargs


def test_an_explicit_method_is_still_honoured():
    kwargs = _binding_kwargs(claude().with_structured_output(schemas.PortfolioDecision, method="json_schema"))
    assert kwargs["output_config"]["format"]["type"] == "json_schema"


@pytest.mark.parametrize("schema", [schemas.ResearchPlan, schemas.TraderProposal,
                                    schemas.PortfolioDecision, schemas.SentimentReport])
def test_every_upstream_structured_schema_converts_to_a_native_json_schema(schema):
    fmt = _binding_kwargs(claude().with_structured_output(schema))["output_config"]["format"]
    assert fmt["schema"]["type"] == "object"
    assert set(schema.model_json_schema()["required"]) <= set(fmt["schema"]["properties"])


# ------------------------------------------------- upstream's agent path, metered

def test_upstream_structured_call_on_sonnet_5_5_is_one_native_call():
    model, store = _metered(replies=[json.dumps(DECISION)])
    with run_context(), agent_context("portfolio_manager"):
        text = invoke_structured_or_freetext(model.with_structured_output(schemas.PortfolioDecision), model,
                                             "decide", schemas.render_pm_decision, "Portfolio Manager")
    assert "**Rating**: Overweight" in text
    (record,) = store.records()
    assert record.structured_method == "json_schema"
    assert "output_config" in model.requests[0]
    assert summarize(store.records()).total.fallback_calls == 0


def test_a_malformed_reply_in_upstreams_path_shows_up_in_the_ledger_as_a_fallback():
    """Upstream retries as free text (its own behaviour); the second call must be visible."""
    model, store = _metered(replies=["this is not json", "**Rating**: Hold\n\nToo uncertain."])
    with run_context(), agent_context("portfolio_manager"):
        invoke_structured_or_freetext(model.with_structured_output(schemas.PortfolioDecision), model,
                                      "decide", schemas.render_pm_decision, "Portfolio Manager")
    records = store.records()
    assert [r.structured_method for r in records] == ["json_schema", None]
    summary = summarize(records)
    assert summary.total.fallback_calls == 1
    assert summary.total.fallback_cost_usd == records[1].estimated_cost_usd


# ------------------------------------------------------------ SID strict helper

def test_strict_helper_returns_a_validated_instance_from_one_metered_call():
    model, store = _metered(replies=[json.dumps(DECISION)])
    with run_context():
        decision = invoke_structured(model, schemas.PortfolioDecision, "decide", agent="cio")
    assert isinstance(decision, schemas.PortfolioDecision) and decision.price_target == 210.0
    (record,) = store.records()
    assert (record.agent, record.structured_method) == ("cio", "json_schema")
    assert len(model.requests) == 1


@pytest.mark.parametrize("reply", [
    "not json at all",
    json.dumps({"rating": "Moon", "executive_summary": "x", "investment_thesis": "y"}),   # invalid enum
    json.dumps({"rating": "Buy"}),                                                         # missing fields
])
def test_strict_helper_fails_closed_after_exactly_one_call(reply):
    model, store = _metered(replies=[reply, json.dumps(DECISION)])   # a second reply exists but must not be used
    with run_context(), pytest.raises(StructuredOutputError) as err:
        invoke_structured(model, schemas.PortfolioDecision, "decide", agent="cio")
    assert err.value.agent == "cio" and err.value.schema == "PortfolioDecision"
    assert len(model.requests) == 1                  # no hidden retry
    assert len(store.records()) == 1                 # and the one call is in the ledger
    assert summarize(store.records()).total.fallback_calls == 0


def test_strict_helper_uses_native_schema_even_on_models_that_could_force_tools():
    model, store = _metered("claude-haiku-4-5", replies=[json.dumps(DECISION)])   # priced; forced tools supported
    with run_context():
        invoke_structured(model, schemas.PortfolioDecision, "decide", agent="cio")
    assert "output_config" in model.requests[0] and "tool_choice" not in model.requests[0]


def test_strict_helper_refuses_a_provider_without_native_structured_output():
    model = FakeChatModel(provider="ollama", model_name="llama")
    with pytest.raises(StructuredOutputError, match="no native structured output"):
        invoke_structured(model, schemas.PortfolioDecision, "decide", agent="cio")
    assert model.calls == []
    assert native_structured_output_method("openai") == "json_schema"
