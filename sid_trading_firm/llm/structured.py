"""Strict structured output for SID Trading Firm's decision-critical calls.

One model call, using the provider's native structured output (a JSON Schema
the model must follow), validated against the Pydantic schema. The result is
either a valid instance or a :class:`StructuredOutputError`. There is no retry
and no free-text fallback: a decision that cannot be read is no decision, and
the caller fails closed. The single call is metered by the usage ledger like any
other.

Upstream TradingAgents keeps its own behaviour (retry as free text); this helper
is for SID's own agents, wired in from Phase 1B.
"""

from __future__ import annotations

import logging
from contextlib import nullcontext
from typing import Any, TypeVar

from pydantic import BaseModel, ValidationError

from sid_trading_firm.runtime.context import agent_context

logger = logging.getLogger(__name__)

T = TypeVar("T", bound=BaseModel)

# Providers whose LangChain integration offers native schema-constrained output
# under method="json_schema". A provider missing here is refused, not served by
# a weaker method.
_NATIVE_JSON_SCHEMA_PROVIDERS = frozenset({"anthropic", "openai", "azure"})


class StructuredOutputError(RuntimeError):
    """A structured call produced no valid result. Decision-critical callers must fail closed."""

    def __init__(self, message: str, *, agent: str | None, schema: str) -> None:
        super().__init__(message)
        self.agent = agent
        self.schema = schema


def native_structured_output_method(provider: str) -> str:
    """The native structured-output method for ``provider``, or raise if it has none."""
    if provider.lower() not in _NATIVE_JSON_SCHEMA_PROVIDERS:
        raise StructuredOutputError(f"provider {provider!r} has no native structured output configured",
                                    agent=None, schema="")
    return "json_schema"


def _provider(model: Any) -> str:
    try:
        return str(model._get_ls_params().get("ls_provider") or "unknown")
    except Exception:  # a model that cannot say who it is cannot be trusted here
        return "unknown"


def invoke_structured(model: Any, schema: type[T], prompt: Any, *, agent: str | None = None) -> T:
    """Exactly one model call returning a validated ``schema`` instance, or raise.

    ``agent`` attributes the call in the usage ledger (``agent_context``).
    """
    name = schema.__name__
    try:
        method = native_structured_output_method(_provider(model))
    except StructuredOutputError as exc:
        raise StructuredOutputError(str(exc), agent=agent, schema=name) from None
    runnable = model.with_structured_output(schema, method=method, include_raw=True)
    with agent_context(agent) if agent else nullcontext():
        output = runnable.invoke(prompt)

    parsed, error = output.get("parsed"), output.get("parsing_error")
    if error is None and parsed is not None and not isinstance(parsed, schema):
        try:
            parsed = schema.model_validate(parsed)
        except ValidationError as exc:
            error = exc
    if error is not None or parsed is None:
        reason = type(error).__name__ if error is not None else "no parsed result"
        logger.warning("structured output failed validation; failing closed",
                       extra={"schema": name, "reason": reason, "agent": agent})
        raise StructuredOutputError(f"{name}: model output did not validate ({reason})",
                                    agent=agent, schema=name)
    return parsed
