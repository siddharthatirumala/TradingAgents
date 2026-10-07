"""Building chat models from configured tiers, through upstream's provider factory.

Business code asks for an agent's model; which provider serves it is
configuration. Construction is delegated to upstream TradingAgents'
``create_llm_client`` (20 providers, their quirks handled there), so nothing
here knows about any one provider.
"""

from __future__ import annotations

import copy
from collections.abc import Sequence
from typing import Any

from sid_trading_firm.config.settings import ConfigError, ModelSpec, Settings, Tier


def _client_kwargs(spec: ModelSpec) -> dict[str, Any]:
    """Upstream's keyword arguments for one spec, via upstream's own translator.

    SDK retries are switched off: each budget authorisation covers exactly one attempt,
    and a retry made by the application is a new call that passes the budget guard.
    """
    from tradingagents.llm_clients.factory import build_llm_kwargs

    return {**build_llm_kwargs({
        "llm_provider": spec.provider,
        "temperature": spec.temperature,
        "max_tokens": spec.max_output_tokens,
        # Only the key matching the provider is read.
        "openai_reasoning_effort": spec.reasoning_effort,
        "anthropic_effort": spec.reasoning_effort,
        "google_thinking_level": spec.reasoning_effort,
    }), "max_retries": 0}


def chat_model(spec: ModelSpec, callbacks: Sequence[Any] = ()) -> Any:
    """A LangChain chat model for ``spec``, with ``callbacks`` attached."""
    from tradingagents.llm_clients.factory import create_llm_client

    kwargs = _client_kwargs(spec)
    if callbacks:
        kwargs["callbacks"] = list(callbacks)
    return create_llm_client(spec.provider, spec.model, spec.base_url, **kwargs).get_llm()


def chat_model_for(settings: Settings, agent: str, callbacks: Sequence[Any] = ()) -> Any:
    """The chat model configured for ``agent`` (an id from ``config.agents``)."""
    return chat_model(settings.models.spec_for(agent), callbacks)


def _shared(name: str, quick: Any, deep: Any) -> Any:
    if quick is not None and deep is not None and quick != deep:
        raise ConfigError(
            f"upstream TradingAgents applies one {name} to both of its model tiers; "
            f"the standard tier sets {quick!r} and the deep tier {deep!r}"
        )
    return quick if quick is not None else deep


def upstream_config(settings: Settings, base: dict | None = None) -> dict:
    """An upstream TradingAgents config that follows SID settings.

    Upstream has two tiers, not one model per agent: its quick tier serves the
    analysts, researchers, trader and risk debaters, its deep tier the Research
    Manager and Portfolio Manager. They take our STANDARD and DEEP tiers. Agents
    we map to FAST (sentiment, reflection) therefore run on STANDARD when driven
    through upstream's graph; per-agent models need SID's own graph.

    Effort caps come from the budgets: debate and risk rounds, and an analyst's
    tool rounds (one fewer than its call limit, leaving a call for its report).
    """
    from tradingagents.default_config import DEFAULT_CONFIG

    quick = settings.models.tiers[Tier.STANDARD]
    deep = settings.models.tiers[Tier.DEEP]
    b = settings.budgets
    cfg = copy.deepcopy(base if base is not None else DEFAULT_CONFIG)
    tool_rounds = max(1, b.max_agent_iterations - 1)
    effort = _shared("reasoning effort", quick.reasoning_effort, deep.reasoning_effort)
    cfg.update(
        llm_provider=quick.provider,
        quick_think_provider=quick.provider,
        deep_think_provider=deep.provider,
        quick_think_llm=quick.model,
        deep_think_llm=deep.model,
        backend_url=None,
        quick_think_backend_url=quick.base_url,
        deep_think_backend_url=deep.base_url,
        temperature=_shared("temperature", quick.temperature, deep.temperature),
        max_tokens=_shared("max_output_tokens", quick.max_output_tokens, deep.max_output_tokens),
        openai_reasoning_effort=effort,
        anthropic_effort=effort,
        google_thinking_level=effort,
        max_debate_rounds=b.max_debate_rounds,
        max_risk_discuss_rounds=b.max_risk_discuss_rounds,
        max_tool_rounds=tool_rounds,
        max_recur_limit=max(cfg.get("max_recur_limit", 100), 2 * tool_rounds + 10),
    )
    return cfg
