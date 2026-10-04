"""Model tiers resolve to chat models through upstream's factory, provider-independently."""

import pytest

from sid_trading_firm.config import ConfigError
from sid_trading_firm.llm import (
    BudgetGuard,
    InMemoryUsageStore,
    UsageLedger,
    chat_model_for,
    upstream_config,
)
from tests_sid.fakes import settings

pytestmark = pytest.mark.unit


@pytest.fixture(autouse=True)
def _placeholder_keys(monkeypatch):
    # Building a client needs a key to be present, not valid; nothing is called.
    monkeypatch.setenv("ANTHROPIC_API_KEY", "placeholder")
    monkeypatch.setenv("OPENAI_API_KEY", "placeholder")


def _ledger(s):
    return UsageLedger(BudgetGuard(s.budgets, s.pricing, InMemoryUsageStore()))


def test_each_agent_gets_its_tiers_provider_and_model_with_the_ledger_attached():
    s = settings()
    ledger = _ledger(s)

    analyst = chat_model_for(s, "fundamentals_analyst", [ledger])
    cio = chat_model_for(s, "cio", [ledger])
    extractor = chat_model_for(s, "extractor", [ledger])

    assert analyst._get_ls_params()["ls_provider"] == "anthropic"
    assert analyst._get_ls_params()["ls_model_name"] == "claude-sonnet-5-5"
    assert cio._get_ls_params()["ls_model_name"] == "claude-sonnet-5-5"
    assert extractor._get_ls_params()["ls_provider"] == "openai"
    assert extractor._get_ls_params()["ls_model_name"] == "gpt-6-luna"
    assert ledger in analyst.callbacks and ledger in extractor.callbacks
    assert analyst.max_tokens == 8192


def test_switching_a_tier_provider_is_configuration_only(monkeypatch):
    monkeypatch.setenv("SID_MODELS__TIERS__DEEP__PROVIDER", "openai")
    monkeypatch.setenv("SID_MODELS__TIERS__DEEP__MODEL", "gpt-6-sol")
    cio = chat_model_for(settings(), "cio")
    assert cio._get_ls_params()["ls_provider"] == "openai"
    assert cio._get_ls_params()["ls_model_name"] == "gpt-6-sol"


def test_upstream_config_maps_standard_and_deep_tiers_and_effort_caps():
    s = settings(max_debate_rounds=2, max_agent_iterations=6)
    cfg = upstream_config(s)
    assert (cfg["llm_provider"], cfg["quick_think_provider"], cfg["deep_think_provider"]) == (
        "anthropic", "anthropic", "anthropic")
    assert cfg["quick_think_llm"] == cfg["deep_think_llm"] == "claude-sonnet-5-5"
    assert cfg["max_tokens"] == 8192
    assert cfg["max_debate_rounds"] == 2
    assert cfg["max_risk_discuss_rounds"] == 1
    assert cfg["max_tool_rounds"] == 5
    assert 2 * cfg["max_tool_rounds"] + 2 < cfg["max_recur_limit"]


def test_upstream_graph_built_from_sid_settings_carries_the_ledger(monkeypatch, tmp_path):
    from tradingagents.graph.trading_graph import TradingAgentsGraph

    s = settings()
    ledger = _ledger(s)
    cfg = upstream_config(s) | {"results_dir": str(tmp_path / "r"), "data_cache_dir": str(tmp_path / "c"),
                               "memory_log_path": str(tmp_path / "m.md")}
    graph = TradingAgentsGraph(config=cfg, callbacks=[ledger])
    assert ledger in graph.quick_thinking_llm.callbacks
    assert ledger in graph.deep_thinking_llm.callbacks
    assert graph.deep_thinking_llm._get_ls_params()["ls_model_name"] == "claude-sonnet-5-5"


def test_settings_upstream_cannot_express_are_refused(monkeypatch):
    monkeypatch.setenv("SID_MODELS__TIERS__DEEP__MAX_OUTPUT_TOKENS", "16000")
    with pytest.raises(ConfigError, match="one max_output_tokens"):
        upstream_config(settings())
