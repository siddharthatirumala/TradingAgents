"""The run context: which run, agent, instrument and strategy the current code serves.

Held in context variables, not globals, so concurrent runs and threads each see
their own. Threads started through ``contextvars.copy_context().run`` (as
LangGraph's executors do) inherit the context of the code that started them.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
from datetime import UTC, datetime

_run: ContextVar[RunContext | None] = ContextVar("sid_run", default=None)
_agent: ContextVar[str | None] = ContextVar("sid_agent", default=None)


class NoActiveRun(RuntimeError):
    """Code that must belong to a run was called outside one."""


@dataclass(frozen=True)
class RunContext:
    run_id: str
    instrument: str | None = None
    strategy: str | None = None
    environment: str | None = None
    started_at: datetime = field(default_factory=lambda: datetime.now(UTC))


def new_run_id() -> str:
    """A globally unique run id (UUID4, canonical string form)."""
    return str(uuid.uuid4())


@contextmanager
def run_context(
    *,
    instrument: str | None = None,
    strategy: str | None = None,
    environment: str | None = None,
    run_id: str | None = None,
) -> Iterator[RunContext]:
    """Start a run for the duration of the block.

    Runs do not nest: starting one inside another is a bug that would file the
    inner run's costs and records under the wrong id, so it raises.
    """
    if _run.get() is not None:
        raise RuntimeError(f"a run is already active ({_run.get().run_id}); runs do not nest")
    if run_id is not None:
        uuid.UUID(run_id)   # reject a malformed id early
    ctx = RunContext(run_id=run_id or new_run_id(), instrument=instrument,
                     strategy=strategy, environment=environment)
    token = _run.set(ctx)
    try:
        yield ctx
    finally:
        _run.reset(token)


@contextmanager
def agent_context(agent: str) -> Iterator[str]:
    """Attribute the work in this block to ``agent``."""
    token = _agent.set(agent)
    try:
        yield agent
    finally:
        _agent.reset(token)


def current_run() -> RunContext | None:
    return _run.get()


def current_run_id() -> str | None:
    ctx = _run.get()
    return ctx.run_id if ctx else None


def require_run() -> RunContext:
    ctx = _run.get()
    if ctx is None:
        raise NoActiveRun("no active run; wrap the work in run_context()")
    return ctx


def current_agent() -> str | None:
    return _agent.get()


def log_fields() -> dict[str, str | None]:
    """The context fields every structured log line carries."""
    ctx = _run.get()
    return {
        "run_id": ctx.run_id if ctx else None,
        "agent": _agent.get(),
        "instrument": ctx.instrument if ctx else None,
        "strategy": ctx.strategy if ctx else None,
        "environment": ctx.environment if ctx else None,
    }
