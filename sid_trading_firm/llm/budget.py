"""The AI budget guard: every model call is authorised before it is made.

Before a call the guard projects its worst-case cost (prompt size, the model's
output cap, no cache discount) and refuses it when it would break a limit: cost
per run, cost per UTC day, tokens per agent, or calls per agent. A refusal raises
:class:`AIBudgetStop` and records why; the run stops there. After a call the
actual usage is recorded and counted, so the next call sees the real spend.

``AIBudgetStop`` derives from ``BaseException`` on purpose. Upstream
TradingAgents catches ``Exception`` in several places to keep a run going (a
failed structured call retried as free text, a failed memory step). A budget stop
must not be absorbed by those fallbacks; like ``KeyboardInterrupt``, it ends the
work instead of being treated as one more recoverable error.

Fail closed: a model with no price, a ledger that cannot be read or written, or a
call outside any run is refused too.

Lifetime budget (``max_ai_cost_total_usd``, at most $30). After every other check
passes, the call's worst case is reserved in the ledger by the store's atomic
``try_reserve``: lifetime spend (recorded costs, the worst case of calls whose cost
is unknown, and every open reservation from any process) plus this call must stay
within the cap. The first refusal writes a permanent marker; from then on every
call, in any process, is refused. Model clients are built without SDK retries, so
one authorised call is one attempt; an application-level retry is a new call that
passes the guard again. After a call, if its recorded cost has taken lifetime spend
past the cap (possible only if the provider billed more than the worst case), the
permanent stop is written at once.
"""

from __future__ import annotations

import logging
import math
import threading
import uuid
from collections import Counter
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from decimal import Decimal

from sid_trading_firm.config.settings import BudgetSettings, ModelPrice
from sid_trading_firm.llm.pricing import worst_case_cost
from sid_trading_firm.llm.usage import LLMCallRecord, UsageStore

logger = logging.getLogger(__name__)

# Characters per token used to estimate a prompt before it is sent. English text
# averages about four; three overestimates on purpose.
CHARS_PER_TOKEN_ESTIMATE = 3


@dataclass(frozen=True)
class BudgetStopEvent:
    """Why AI work was stopped. Kept by the guard and logged; persisted by a listener."""

    reason: str
    run_id: str | None
    agent: str | None
    limit: str | None = None
    limit_value: str | None = None
    observed_value: str | None = None
    detail: str | None = None
    at: datetime = field(default_factory=lambda: datetime.now(UTC))

    def to_dict(self) -> dict:
        data = asdict(self)
        data["at"] = self.at.isoformat()
        return data


class AIBudgetStop(BaseException):  # noqa: N818 - a stop signal, not an error to recover from
    """Further AI work must stop. Not an ``Exception``: see the module docstring."""

    def __init__(self, event: BudgetStopEvent) -> None:
        super().__init__(f"AI work stopped ({event.reason}): {event.detail or ''}".strip())
        self.event = event


class BudgetExceeded(AIBudgetStop):
    """A call would break a configured limit."""


class LedgerUnavailable(AIBudgetStop):
    """Spend could not be read or recorded, so no budget can be enforced."""


class UnpricedModel(AIBudgetStop):
    """The model has no price, so its cost cannot be held to a budget."""


class LifetimeBudgetExhausted(BudgetExceeded):
    """The lifetime AI budget cannot take this call; AI work stops permanently."""


class NoRunForCall(AIBudgetStop):
    """A model call happened outside any run; it cannot be attributed or budgeted."""


@dataclass(frozen=True)
class Authorization:
    call_id: str
    run_id: str
    agent: str
    estimated_input_tokens: int
    estimated_output_tokens: int
    reserved_usd: Decimal


@dataclass
class _RunState:
    committed_usd: Decimal = Decimal(0)
    assumed_usd: Decimal = Decimal(0)   # estimates counted for calls with unknown cost
    reserved: dict[str, Decimal] = field(default_factory=dict)
    agent_tokens: Counter = field(default_factory=Counter)
    agent_calls: Counter = field(default_factory=Counter)
    stop: BudgetStopEvent | None = None


class BudgetGuard:
    """Authorises calls against the budgets and records their outcome. Thread-safe."""

    def __init__(
        self,
        budgets: BudgetSettings,
        pricing: dict[str, ModelPrice],
        store: UsageStore,
        *,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self.budgets = budgets
        self.pricing = pricing
        self.store = store
        self._clock = clock
        self._lock = threading.RLock()   # listeners may read the guard
        self._runs: dict[str, _RunState] = {}
        self._assumed_by_day: Counter = Counter()
        self.stops: list[BudgetStopEvent] = []
        self.authorized_calls = 0          # calls the guard allowed, across runs
        self._listeners: list[Callable[[BudgetStopEvent], None]] = []
        self._lifetime_stop: BudgetStopEvent | None = None

    # ------------------------------------------------------------------ public

    def add_stop_listener(self, listener: Callable[[BudgetStopEvent], None]) -> None:
        """Called with each stop event, e.g. to write an audit record."""
        self._listeners.append(listener)

    def stopped(self, run_id: str) -> BudgetStopEvent | None:
        with self._lock:
            state = self._runs.get(run_id)
            return state.stop if state else None

    def run_spend(self, run_id: str) -> Decimal:
        """Recorded spend for the run, plus estimates counted for calls of unknown cost."""
        with self._lock:
            state = self._runs.get(run_id)
            return state.committed_usd + state.assumed_usd if state else Decimal(0)

    def authorize(
        self,
        *,
        run_id: str | None,
        agent: str,
        provider: str,
        model: str,
        prompt_chars: int,
        max_output_tokens: int | None,
    ) -> Authorization:
        """Allow one call or raise :class:`AIBudgetStop`. Reserves the call's worst case."""
        if run_id is None:
            self._stop(NoRunForCall, BudgetStopEvent(
                reason="no_active_run", run_id=None, agent=agent,
                detail="model call made outside run_context(); refusing an unattributable call"))
        with self._lock:
            if self._lifetime_stop is not None:
                raise LifetimeBudgetExhausted(self._lifetime_stop)
            state = self._runs.setdefault(run_id, _RunState())
            if state.stop is not None:
                raise BudgetExceeded(state.stop)

            price = self.pricing.get(f"{provider.lower()}/{model}")
            est_in = math.ceil(prompt_chars / CHARS_PER_TOKEN_ESTIMATE)
            est_out = max_output_tokens or self.budgets.output_token_reserve
            if price is None:
                if not self.budgets.allow_unpriced_models:
                    self._trip(state, UnpricedModel, BudgetStopEvent(
                        reason="unpriced_model", run_id=run_id, agent=agent,
                        detail=f"{provider}/{model} has no entry in the price table"))
                reserve = Decimal(0)
            else:
                reserve = worst_case_cost(est_in, est_out, price)

            b = self.budgets
            calls = state.agent_calls[agent] + 1
            if calls > b.max_agent_iterations:
                self._trip(state, BudgetExceeded, BudgetStopEvent(
                    reason="agent_iterations", run_id=run_id, agent=agent,
                    limit="max_agent_iterations", limit_value=str(b.max_agent_iterations),
                    observed_value=str(calls), detail=f"{agent} would make call {calls}"))

            tokens = state.agent_tokens[agent] + est_in + est_out
            if tokens > b.max_llm_tokens_per_agent:
                self._trip(state, BudgetExceeded, BudgetStopEvent(
                    reason="agent_tokens", run_id=run_id, agent=agent,
                    limit="max_llm_tokens_per_agent", limit_value=str(b.max_llm_tokens_per_agent),
                    observed_value=str(tokens), detail=f"{agent} would reach about {tokens} tokens"))

            run_projected = (state.committed_usd + state.assumed_usd
                             + sum(state.reserved.values(), Decimal(0)) + reserve)
            if run_projected > b.max_ai_cost_per_run_usd:
                self._trip(state, BudgetExceeded, BudgetStopEvent(
                    reason="run_cost", run_id=run_id, agent=agent,
                    limit="max_ai_cost_per_run_usd", limit_value=str(b.max_ai_cost_per_run_usd),
                    observed_value=f"{run_projected:.6f}",
                    detail=f"next {agent} call could bring this run to ${run_projected:.4f}"))

            today = self._clock().astimezone(UTC).date()
            try:
                day_spent = self.store.spent_usd(day=today)
            except Exception as exc:
                self._trip(state, LedgerUnavailable, BudgetStopEvent(
                    reason="ledger_unavailable", run_id=run_id, agent=agent,
                    detail=f"could not read today's spend: {type(exc).__name__}"))
            day_projected = (day_spent + self._assumed_by_day[today]
                             + self._all_reserved() + reserve)
            if day_projected > b.max_ai_cost_per_day_usd:
                self._trip(state, BudgetExceeded, BudgetStopEvent(
                    reason="day_cost", run_id=run_id, agent=agent,
                    limit="max_ai_cost_per_day_usd", limit_value=str(b.max_ai_cost_per_day_usd),
                    observed_value=f"{day_projected:.6f}",
                    detail=f"next {agent} call could bring today's spend to ${day_projected:.4f}"))

            call_id = str(uuid.uuid4())
            self._reserve_lifetime(state, call_id, run_id, agent, reserve)
            self.authorized_calls += 1
            state.reserved[call_id] = reserve
            state.agent_calls[agent] = calls
            return Authorization(call_id, run_id, agent, est_in, est_out, reserve)

    def record(self, auth: Authorization, record: LLMCallRecord) -> None:
        """Count a finished call (success or failure) and store its record.

        A record that cannot be stored stops the run: spend that was not
        recorded cannot be budgeted.
        """
        with self._lock:
            state = self._runs.setdefault(auth.run_id, _RunState())
            state.reserved.pop(auth.call_id, None)
            if record.input_tokens is not None and record.output_tokens is not None:
                state.agent_tokens[auth.agent] += record.input_tokens + record.output_tokens
            elif record.success:
                state.agent_tokens[auth.agent] += auth.estimated_input_tokens + auth.estimated_output_tokens
            if record.estimated_cost_usd is not None:
                state.committed_usd += record.estimated_cost_usd
            elif record.success:
                # Cost unknown (no usage reported, or unpriced and allowed): count the
                # pre-call worst case so the budget stays conservative.
                state.assumed_usd += auth.reserved_usd
                self._assumed_by_day[record.started_at.astimezone(UTC).date()] += auth.reserved_usd
            try:
                self.store.add(record)
                # A call whose cost is unknown (success or not) stays charged at its worst case.
                self.store.settle_reservation(
                    auth.call_id, assumed_usd=None if record.estimated_cost_usd is not None else auth.reserved_usd)
                lifetime = self.store.lifetime_spent_usd()
            except Exception as exc:
                self._trip(state, LedgerUnavailable, BudgetStopEvent(
                    reason="ledger_unavailable", run_id=auth.run_id, agent=auth.agent,
                    detail=f"could not record a call: {type(exc).__name__}"))
            if lifetime > self.budgets.max_ai_cost_total_usd and self._lifetime_stop is None:
                self._exhaust(auth.run_id, auth.agent, lifetime, "lifetime spend passed its cap after a call")
            spent = state.committed_usd + state.assumed_usd
            if state.stop is None and spent > self.budgets.max_ai_cost_per_run_usd:
                # The call already happened; refuse every later one.
                event = BudgetStopEvent(
                    reason="run_cost", run_id=auth.run_id, agent=auth.agent,
                    limit="max_ai_cost_per_run_usd", limit_value=str(self.budgets.max_ai_cost_per_run_usd),
                    observed_value=f"{spent:.6f}", detail="run spend passed its limit after a call")
                state.stop = event
                self._publish(event)

    def release(self, auth: Authorization) -> None:
        """Drop a reservation for a call that never reached the provider."""
        with self._lock:
            state = self._runs.get(auth.run_id)
            if state:
                state.reserved.pop(auth.call_id, None)
            try:
                self.store.release_reservation(auth.call_id)
            except Exception:
                # The reservation stays open and keeps counting at its worst case: conservative.
                logger.exception("could not release a lifetime-budget reservation")

    # ---------------------------------------------------------------- internal

    def _reserve_lifetime(self, state: _RunState, call_id: str, run_id: str, agent: str,
                          reserve: Decimal) -> None:
        cap = self.budgets.max_ai_cost_total_usd
        try:
            exhausted = self.store.lifetime_exhausted()
            ok, spent = (False, None) if exhausted else self.store.try_reserve(
                call_id=call_id, run_id=run_id, agent=agent, amount=reserve, cap=cap)
        except Exception as exc:
            self._trip(state, LedgerUnavailable, BudgetStopEvent(
                reason="ledger_unavailable", run_id=run_id, agent=agent,
                detail=f"could not check the lifetime budget: {type(exc).__name__}"))
        if not ok:
            detail = ("the lifetime AI budget was already exhausted" if exhausted
                      else f"next {agent} call could bring lifetime spend to ${spent + reserve:.4f}")
            self._exhaust(run_id, agent, None if exhausted else spent + reserve, detail, state=state)

    def _exhaust(self, run_id: str, agent: str, observed: Decimal | None, detail: str,
                 state: _RunState | None = None) -> None:
        """Stop all AI work permanently: in this guard, and (via the store) in every process."""
        event = BudgetStopEvent(
            reason="lifetime_cost", run_id=run_id, agent=agent, limit="max_ai_cost_total_usd",
            limit_value=str(self.budgets.max_ai_cost_total_usd),
            observed_value=f"{observed:.6f}" if observed is not None else None, detail=detail)
        self._lifetime_stop = event
        if state is not None:
            state.stop = event
        try:
            self.store.mark_lifetime_exhausted(detail)
        except Exception:
            logger.exception("could not persist the lifetime-budget stop; it still holds in this process")
        if state is not None:
            self._stop(LifetimeBudgetExhausted, event)
        self._publish(event)

    def _all_reserved(self) -> Decimal:
        return sum((sum(s.reserved.values(), Decimal(0)) for s in self._runs.values()), Decimal(0))

    def _trip(self, state: _RunState, kind: type[AIBudgetStop], event: BudgetStopEvent):
        state.stop = event
        self._stop(kind, event)

    def _stop(self, kind: type[AIBudgetStop], event: BudgetStopEvent):
        self._publish(event)
        raise kind(event)

    def _publish(self, event: BudgetStopEvent) -> None:
        self.stops.append(event)
        logger.error("AI budget stop: %s", event.detail or event.reason,
                     extra={"budget_stop": event.to_dict()})
        for listener in self._listeners:
            try:
                listener(event)
            except Exception:
                logger.exception("budget stop listener failed")
