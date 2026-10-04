"""Reading and writing runs, model-call records and audit events."""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime, time, timedelta
from decimal import Decimal
from typing import Any

from sqlalchemy import func, select

import tradingagents
from sid_trading_firm.config.settings import Settings
from sid_trading_firm.llm.budget import BudgetStopEvent
from sid_trading_firm.llm.pricing import CostStatus
from sid_trading_firm.llm.usage import LLMCallRecord
from sid_trading_firm.persistence.db import Database
from sid_trading_firm.persistence.models import RUN_STATUSES, AuditEvent, LLMUsage, ResearchRun
from sid_trading_firm.runtime.context import RunContext


def _utc(value: datetime | None) -> datetime | None:
    """SQLite hands back naive datetimes; everything stored is UTC."""
    if value is None or value.tzinfo is not None:
        return value
    return value.replace(tzinfo=UTC)


class RunRepository:
    def __init__(self, db: Database) -> None:
        self.db = db

    def start(self, run: RunContext, *, kind: str, settings: Settings,
              trade_date: date | None = None, code_version: str | None = None) -> None:
        with self.db.session() as s:
            s.add(ResearchRun(
                run_id=uuid.UUID(run.run_id), kind=kind, status="running",
                environment=run.environment or settings.app.environment.value,
                instrument=run.instrument, trade_date=trade_date, strategy=run.strategy,
                started_at=run.started_at, upstream_version=tradingagents.__version__,
                code_version=code_version, config_snapshot=settings.snapshot(),
            ))

    def finish(self, run_id: str, *, status: str, summary: dict[str, Any] | None = None,
               error: str | None = None) -> None:
        if status not in RUN_STATUSES or status == "running":
            raise ValueError(f"not a final run status: {status!r}")
        with self.db.session() as s:
            row = s.get(ResearchRun, uuid.UUID(run_id))
            if row is None:
                raise LookupError(f"no research run {run_id}")
            row.status, row.summary, row.error = status, summary, error
            row.finished_at = datetime.now(UTC)

    def get(self, run_id: str) -> ResearchRun | None:
        with self.db.session() as s:
            return s.get(ResearchRun, uuid.UUID(run_id))


class AuditLog:
    def __init__(self, db: Database) -> None:
        self.db = db

    def record(self, event_type: str, message: str, *, run_id: str | None = None,
               severity: str = "info", actor: str = "system",
               payload: dict[str, Any] | None = None) -> None:
        with self.db.session() as s:
            s.add(AuditEvent(
                run_id=uuid.UUID(run_id) if run_id else None, occurred_at=datetime.now(UTC),
                event_type=event_type, severity=severity, actor=actor, message=message,
                payload=payload,
            ))

    def for_run(self, run_id: str) -> list[AuditEvent]:
        with self.db.session() as s:
            return list(s.scalars(select(AuditEvent).where(AuditEvent.run_id == uuid.UUID(run_id))
                                  .order_by(AuditEvent.occurred_at)))

    def budget_stop_listener(self):
        """A :class:`BudgetGuard` listener that writes each stop as an audit event."""
        def listen(event: BudgetStopEvent) -> None:
            self.record("budget.stop", event.detail or event.reason, run_id=event.run_id,
                        severity="error", actor=event.agent or "budget_guard", payload=event.to_dict())
        return listen


class SqlUsageStore:
    """The usage ledger in the database (the ``UsageStore`` protocol).

    A record for a run with no ``research_runs`` row fails the foreign key: the
    guard then stops the run, because spend it cannot record cannot be budgeted.
    """

    def __init__(self, db: Database) -> None:
        self.db = db

    def add(self, record: LLMCallRecord) -> None:
        with self.db.session() as s:
            s.add(LLMUsage(
                call_id=uuid.UUID(record.call_id), run_id=uuid.UUID(record.run_id),
                agent=record.agent, node=record.node, provider=record.provider, model=record.model,
                started_at=record.started_at, finished_at=record.finished_at,
                latency_ms=record.latency_ms, success=record.success,
                input_tokens=record.input_tokens, output_tokens=record.output_tokens,
                cache_read_tokens=record.cache_read_tokens, cache_write_tokens=record.cache_write_tokens,
                usage_available=record.usage_available, estimated_cost_usd=record.estimated_cost_usd,
                cost_status=record.cost_status.value, estimated_input_tokens=record.estimated_input_tokens,
                prompt_chars=record.prompt_chars, error_type=record.error_type,
                error_message=record.error_message,
            ))

    def spent_usd(self, *, run_id: str | None = None, day: date | None = None) -> Decimal:
        query = select(func.coalesce(func.sum(LLMUsage.estimated_cost_usd), 0))
        if run_id is not None:
            query = query.where(LLMUsage.run_id == uuid.UUID(run_id))
        if day is not None:
            start = datetime.combine(day, time.min, tzinfo=UTC)
            query = query.where(LLMUsage.started_at >= start, LLMUsage.started_at < start + timedelta(days=1))
        with self.db.session() as s:
            return Decimal(str(s.scalar(query)))

    def records(self, run_id: str | None = None) -> list[LLMCallRecord]:
        query = select(LLMUsage).order_by(LLMUsage.started_at)
        if run_id is not None:
            query = query.where(LLMUsage.run_id == uuid.UUID(run_id))
        with self.db.session() as s:
            return [_to_record(row) for row in s.scalars(query)]


def _to_record(row: LLMUsage) -> LLMCallRecord:
    return LLMCallRecord(
        run_id=str(row.run_id), agent=row.agent, provider=row.provider, model=row.model,
        node=row.node, started_at=_utc(row.started_at), finished_at=_utc(row.finished_at),
        latency_ms=row.latency_ms, success=row.success, input_tokens=row.input_tokens,
        output_tokens=row.output_tokens, cache_read_tokens=row.cache_read_tokens,
        cache_write_tokens=row.cache_write_tokens, usage_available=row.usage_available,
        estimated_cost_usd=row.estimated_cost_usd, cost_status=CostStatus(row.cost_status),
        estimated_input_tokens=row.estimated_input_tokens, prompt_chars=row.prompt_chars,
        error_type=row.error_type, error_message=row.error_message, call_id=str(row.call_id),
    )
