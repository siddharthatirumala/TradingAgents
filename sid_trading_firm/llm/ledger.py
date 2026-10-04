"""The usage ledger: a LangChain callback that meters and guards every model call.

Attach it to a chat model (``callbacks=[ledger]``), or pass it to upstream's
``TradingAgentsGraph(callbacks=[ledger])``, which hands it to every model it
builds. For each call it:

1. works out the run (the active ``run_context``), the agent and the model;
2. asks the :class:`BudgetGuard` for permission, which may stop the run;
3. on completion, records tokens, latency, cost and success in the usage store.

Agent attribution, in order: an explicit ``agent_context``; else the LangGraph
node the call came from, translated through ``UPSTREAM_NODE_AGENTS``; else
``"unattributed"``. Token counts come only from the provider's reported usage;
when a provider reports none, the record says so instead of guessing.
"""

from __future__ import annotations

import json
import logging
import threading
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from langchain_core.callbacks import BaseCallbackHandler
from langchain_core.outputs import LLMResult

from sid_trading_firm.config.agents import UPSTREAM_NODE_AGENTS
from sid_trading_firm.llm.budget import Authorization, BudgetGuard
from sid_trading_firm.llm.pricing import TokenUsage, cost_of
from sid_trading_firm.llm.usage import LLMCallRecord
from sid_trading_firm.observability.logging import redact
from sid_trading_firm.runtime.context import current_agent, current_run_id

logger = logging.getLogger(__name__)

UNATTRIBUTED = "unattributed"


@dataclass
class _Pending:
    auth: Authorization
    provider: str
    model: str
    node: str | None
    prompt_chars: int
    started_at: datetime
    t0: float


def resolve_agent(metadata: dict[str, Any] | None) -> tuple[str, str | None]:
    """The agent id a call belongs to, and the graph node it came from."""
    metadata = metadata or {}
    node = metadata.get("langgraph_node")
    explicit = current_agent()
    if explicit:
        return explicit, node
    # Inside an analyst's own subgraph the node is "agent" or "wrap_up"; the
    # namespace's first segment names the analyst ("Market Analyst:<task id>|...").
    namespace = metadata.get("checkpoint_ns") or metadata.get("langgraph_checkpoint_ns") or ""
    top = namespace.split("|", 1)[0].split(":", 1)[0] if namespace else None
    for candidate in (top, node):
        if candidate in UPSTREAM_NODE_AGENTS:
            return UPSTREAM_NODE_AGENTS[candidate], node
    return UNATTRIBUTED, node


def _provider_and_model(metadata: dict[str, Any], kwargs: dict[str, Any]) -> tuple[str, str]:
    params = kwargs.get("invocation_params") or {}
    provider = metadata.get("ls_provider") or params.get("_type") or "unknown"
    model = (metadata.get("ls_model_name") or params.get("model") or params.get("model_name")
             or "unknown")
    return str(provider).lower(), str(model)


def _message_chars(message: Any) -> int:
    content = getattr(message, "content", message)
    chars = len(content) if isinstance(content, str) else len(json.dumps(content, default=str))
    tool_calls = getattr(message, "tool_calls", None)
    if tool_calls:
        chars += len(json.dumps(tool_calls, default=str))
    return chars


def _usage(response: LLMResult) -> TokenUsage | None:
    """Provider-reported usage, or None when the provider reported none."""
    try:
        message = response.generations[0][0].message
    except (IndexError, AttributeError, TypeError):
        message = None
    meta = getattr(message, "usage_metadata", None)
    if meta and meta.get("input_tokens") is not None and meta.get("output_tokens") is not None:
        details = meta.get("input_token_details") or {}
        return TokenUsage(
            input_tokens=int(meta["input_tokens"]),
            output_tokens=int(meta["output_tokens"]),
            cache_read_tokens=int(details.get("cache_read") or 0),
            cache_write_tokens=int(details.get("cache_creation") or 0),
        )
    output = response.llm_output or {}
    raw = output.get("token_usage") or output.get("usage") or {}
    prompt = raw.get("prompt_tokens", raw.get("input_tokens"))
    completion = raw.get("completion_tokens", raw.get("output_tokens"))
    if prompt is not None and completion is not None:
        return TokenUsage(int(prompt), int(completion))
    return None


class UsageLedger(BaseCallbackHandler):
    """Meters and guards model calls. One instance can serve many runs and threads."""

    raise_error = True      # a budget stop raised here must stop the call

    def __init__(self, guard: BudgetGuard, *, run_id: str | None = None) -> None:
        super().__init__()
        self.guard = guard
        self._fixed_run_id = run_id
        self._pending: dict[UUID, _Pending] = {}
        self._lock = threading.Lock()

    # ------------------------------------------------------------- callbacks

    def on_chat_model_start(self, serialized, messages, *, run_id: UUID, parent_run_id=None,
                            tags=None, metadata=None, **kwargs: Any) -> None:
        chars = sum(_message_chars(m) for batch in messages for m in batch)
        self._start(run_id, metadata or {}, kwargs, chars)

    def on_llm_start(self, serialized, prompts, *, run_id: UUID, parent_run_id=None,
                     tags=None, metadata=None, **kwargs: Any) -> None:
        self._start(run_id, metadata or {}, kwargs, sum(len(p) for p in prompts))

    def on_llm_end(self, response: LLMResult, *, run_id: UUID, **kwargs: Any) -> None:
        pending = self._pop(run_id)
        if pending is None:
            return
        usage = _usage(response)
        cost = cost_of(usage, self.guard.pricing.get(f"{pending.provider}/{pending.model}"))
        self._finish(pending, success=True, usage=usage, cost=cost)

    def on_llm_error(self, error: BaseException, *, run_id: UUID, **kwargs: Any) -> None:
        pending = self._pop(run_id)
        if pending is None:
            return
        self._finish(pending, success=False, usage=None, cost=cost_of(None, None), error=error)

    # -------------------------------------------------------------- internal

    def _start(self, lc_run_id: UUID, metadata: dict, kwargs: dict, prompt_chars: int) -> None:
        agent, node = resolve_agent(metadata)
        provider, model = _provider_and_model(metadata, kwargs)
        max_out = metadata.get("ls_max_tokens")
        params = kwargs.get("invocation_params") or {}
        max_out = params.get("max_tokens") or params.get("max_output_tokens") or max_out
        auth = self.guard.authorize(
            run_id=current_run_id() or self._fixed_run_id,
            agent=agent, provider=provider, model=model,
            prompt_chars=prompt_chars, max_output_tokens=int(max_out) if max_out else None,
        )
        with self._lock:
            self._pending[lc_run_id] = _Pending(auth, provider, model, node, prompt_chars,
                                                datetime.now(UTC), time.perf_counter())

    def _pop(self, lc_run_id: UUID) -> _Pending | None:
        with self._lock:
            return self._pending.pop(lc_run_id, None)

    def _finish(self, p: _Pending, *, success: bool, usage: TokenUsage | None, cost,
                error: BaseException | None = None) -> None:
        record = LLMCallRecord(
            run_id=p.auth.run_id,
            agent=p.auth.agent,
            provider=p.provider,
            model=p.model,
            node=p.node,
            started_at=p.started_at,
            finished_at=datetime.now(UTC),
            latency_ms=round((time.perf_counter() - p.t0) * 1000, 1),
            success=success,
            input_tokens=usage.input_tokens if usage else None,
            output_tokens=usage.output_tokens if usage else None,
            cache_read_tokens=usage.cache_read_tokens if usage else None,
            cache_write_tokens=usage.cache_write_tokens if usage else None,
            usage_available=usage is not None,
            estimated_cost_usd=cost.usd,
            cost_status=cost.status,
            estimated_input_tokens=p.auth.estimated_input_tokens,
            prompt_chars=p.prompt_chars,
            error_type=type(error).__name__ if error else None,
            error_message=redact(str(error))[:500] if error else None,
            call_id=p.auth.call_id,
        )
        if success and usage is None:
            logger.warning("%s/%s reported no token usage; cost recorded as unknown",
                           p.provider, p.model, extra={"agent": p.auth.agent})
        self.guard.record(p.auth, record)
