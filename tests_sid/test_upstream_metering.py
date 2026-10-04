"""The ledger and guard around upstream TradingAgents' real graph, offline.

Reuses upstream's own end-to-end harness (scripted model, offline vendors), so
these tests exercise the same graph wiring a real run does. If an upstream sync
changes that harness, these tests will say so.
"""

import copy
from decimal import Decimal

import pytest

import tradingagents.dataflows.config as dataflows_config
from sid_trading_firm.llm import BudgetExceeded, BudgetGuard, InMemoryUsageStore, UsageLedger
from sid_trading_firm.llm.ledger import UNATTRIBUTED
from sid_trading_firm.llm.report import render_markdown, summarize
from sid_trading_firm.runtime import run_context
from tests.test_graph_end_to_end import TRADE_DATE, ScriptedModel, _graph, offline  # noqa: F401
from tests_sid.fakes import settings

pytestmark = pytest.mark.unit

USAGE = {"input_tokens": 1000, "output_tokens": 100, "total_tokens": 1100}


class MeteredScriptedModel(ScriptedModel):
    """Upstream's scripted model, reporting Sonnet-style usage."""

    def _get_ls_params(self, stop=None, **kwargs):
        return {"ls_provider": "anthropic", "ls_model_name": "claude-sonnet-5-5",
                "ls_model_type": "chat", "ls_max_tokens": 1000}

    def _generate(self, messages, stop=None, run_manager=None, **kwargs):
        result = super()._generate(messages, stop, run_manager, **kwargs)
        result.generations[0].message.usage_metadata = dict(USAGE)
        return result


@pytest.fixture(autouse=True)
def _restore_upstream_config():
    saved = copy.deepcopy(dataflows_config._config)
    yield
    dataflows_config._config = saved


def _metered(**budgets):
    s = settings(**budgets)
    store = InMemoryUsageStore()
    guard = BudgetGuard(s.budgets, s.pricing, store)
    return UsageLedger(guard), guard, store


@pytest.mark.usefixtures("offline")
def test_every_call_of_an_upstream_run_is_metered_and_attributed(tmp_path, monkeypatch):
    ledger, guard, store = _metered()
    model = MeteredScriptedModel(callbacks=[ledger])
    graph = _graph(tmp_path, monkeypatch, model)

    with run_context(instrument="NVDA", strategy="baseline") as run:
        _, signal = graph.propagate("NVDA", TRADE_DATE)

    assert signal == "Overweight"
    records = store.records(run.run_id)
    assert len(records) == len(model.calls)
    assert UNATTRIBUTED not in {r.agent for r in records}
    calls = {agent: line.calls for agent, line in summarize(records).by_agent.items()}
    assert calls == {
        "technical_analyst": 2, "fundamentals_analyst": 2, "news_analyst": 2, "sentiment_analyst": 1,
        "bull_researcher": 1, "bear_researcher": 1, "research_manager": 1, "trader": 1,
        "aggressive_risk_analyst": 1, "conservative_risk_analyst": 1, "neutral_risk_analyst": 1,
        "portfolio_manager": 1,
    }
    per_call = Decimal(1000 * 2 + 100 * 10) / 10**6
    assert summarize(records).total.cost_usd == per_call * len(records)
    assert guard.run_spend(run.run_id) == per_call * len(records)


@pytest.mark.usefixtures("offline")
def test_a_run_over_budget_stops_mid_graph_and_makes_no_further_calls(tmp_path, monkeypatch):
    # Each call reserves about $0.01 worst case and costs $0.003; $0.03 allows a handful.
    ledger, guard, store = _metered(max_ai_cost_per_run_usd="0.03")
    model = MeteredScriptedModel(callbacks=[ledger])
    graph = _graph(tmp_path, monkeypatch, model)

    with run_context() as run, pytest.raises(BudgetExceeded) as stop:
        graph.propagate("NVDA", TRADE_DATE)

    assert stop.value.event.reason == "run_cost"
    assert guard.stopped(run.run_id) is stop.value.event
    assert len(model.calls) == len(store.records(run.run_id)) < 15   # stopped before the end
    assert guard.run_spend(run.run_id) <= Decimal("0.03")
    assert not graph.memory_log.load_entries()                       # no decision was recorded


def test_a_stop_inside_upstreams_structured_fallback_is_not_swallowed():
    """invoke_structured_or_freetext catches Exception to retry as free text."""
    from tradingagents.agents.structured import invoke_structured_or_freetext

    ledger, _, _ = _metered(max_agent_iterations=1)
    model = MeteredScriptedModel(callbacks=[ledger])
    with run_context():
        model.invoke("first call uses the only iteration")
        with pytest.raises(BudgetExceeded):
            invoke_structured_or_freetext(model, model, "decide", str, "Portfolio Manager")


@pytest.mark.usefixtures("offline")
def test_the_usage_report_renders_per_agent_costs(tmp_path, monkeypatch):
    ledger, _, store = _metered()
    graph = _graph(tmp_path, monkeypatch, MeteredScriptedModel(callbacks=[ledger]))
    with run_context() as run:
        graph.propagate("NVDA", TRADE_DATE)

    text = render_markdown(summarize(store.records(run.run_id)))
    assert "| Technical Analyst | Analysts | 2 |" in text
    assert "**Total run**" in text and "$0.0450" in text      # 15 calls x $0.003
    assert "Data quality" not in text
