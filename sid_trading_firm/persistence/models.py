"""Database schema: the record of every run, its model calls and its audit trail.

Every row produced by an analysis carries the run's ``run_id`` so a decision can
be reconstructed from the database alone. Later phases add decision, order and
strategy tables alongside these, keyed the same way.

Portable SQL only (PostgreSQL in development and production; SQLite in unit
tests): JSON becomes JSONB on PostgreSQL, money is NUMERIC, times are
timezone-aware.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    JSON,
    BigInteger,
    CheckConstraint,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    MetaData,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    Uuid,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

# Stable constraint names, so migrations can refer to them.
NAMING = {
    "ix": "ix_%(table_name)s_%(column_0_N_name)s",
    "uq": "uq_%(table_name)s_%(column_0_N_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}

JSONType = JSON().with_variant(JSONB(), "postgresql")
UTCDateTime = DateTime(timezone=True)

RUN_STATUSES = ("running", "completed", "budget_stopped", "failed")
SEVERITIES = ("debug", "info", "warning", "error", "critical")


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING)


class ResearchRun(Base):
    """One execution: an analysis, a measurement, later a backtest or paper-trading cycle."""

    __tablename__ = "research_runs"
    __table_args__ = (
        CheckConstraint(f"status IN {RUN_STATUSES}", name="status"),
        Index(None, "started_at"),
        Index(None, "instrument", "trade_date"),
    )

    run_id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True)
    kind: Mapped[str] = mapped_column(String(32))
    status: Mapped[str] = mapped_column(String(20))
    environment: Mapped[str] = mapped_column(String(16))
    instrument: Mapped[str | None] = mapped_column(String(16))
    trade_date: Mapped[date | None] = mapped_column(Date)
    strategy: Mapped[str | None] = mapped_column(String(64))
    started_at: Mapped[datetime] = mapped_column(UTCDateTime)
    finished_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    upstream_version: Mapped[str] = mapped_column(String(32))
    code_version: Mapped[str | None] = mapped_column(String(64))
    # Settings in force, secrets masked.
    config_snapshot: Mapped[dict[str, Any]] = mapped_column(JSONType)
    summary: Mapped[dict[str, Any] | None] = mapped_column(JSONType)
    error: Mapped[str | None] = mapped_column(Text)


class LLMUsage(Base):
    """One model call. Token counts are NULL when the provider reported none."""

    __tablename__ = "llm_usage"
    __table_args__ = (
        Index(None, "run_id"),
        Index(None, "started_at"),
        Index(None, "agent"),
    )

    call_id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True)
    run_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("research_runs.run_id", ondelete="RESTRICT"))
    agent: Mapped[str] = mapped_column(String(64))
    node: Mapped[str | None] = mapped_column(String(128))
    provider: Mapped[str] = mapped_column(String(32))
    model: Mapped[str] = mapped_column(String(128))
    started_at: Mapped[datetime] = mapped_column(UTCDateTime)
    finished_at: Mapped[datetime] = mapped_column(UTCDateTime)
    latency_ms: Mapped[float] = mapped_column(Float)
    success: Mapped[bool]
    input_tokens: Mapped[int | None] = mapped_column(BigInteger)
    output_tokens: Mapped[int | None] = mapped_column(BigInteger)
    cache_read_tokens: Mapped[int | None] = mapped_column(BigInteger)
    cache_write_tokens: Mapped[int | None] = mapped_column(BigInteger)
    usage_available: Mapped[bool]
    estimated_cost_usd: Mapped[Decimal | None] = mapped_column(Numeric(14, 8))
    cost_status: Mapped[str] = mapped_column(String(16))
    estimated_input_tokens: Mapped[int] = mapped_column(Integer)
    prompt_chars: Mapped[int] = mapped_column(Integer)
    error_type: Mapped[str | None] = mapped_column(String(128))
    error_message: Mapped[str | None] = mapped_column(Text)
    structured_method: Mapped[str | None] = mapped_column(String(32))
    tools_offered: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    tool_calls: Mapped[int] = mapped_column(Integer, default=0, server_default="0")


RESERVATION_STATUSES = ("open", "settled", "released")


class BudgetReservation(Base):
    """A model call's worst-case cost, held against the lifetime AI budget from before the call."""

    __tablename__ = "budget_reservations"
    __table_args__ = (
        CheckConstraint(f"status IN {RESERVATION_STATUSES}", name="status"),
        Index(None, "status"),
    )

    call_id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True)
    run_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("research_runs.run_id", ondelete="RESTRICT"))
    agent: Mapped[str] = mapped_column(String(64))
    reserved_usd: Mapped[Decimal] = mapped_column(Numeric(14, 8))
    # Set when the call settled without a known cost: its worst case stays charged.
    assumed_usd: Mapped[Decimal | None] = mapped_column(Numeric(14, 8))
    status: Mapped[str] = mapped_column(String(10))
    created_at: Mapped[datetime] = mapped_column(UTCDateTime)
    settled_at: Mapped[datetime | None] = mapped_column(UTCDateTime)


class AuditEvent(Base):
    """Something worth reconstructing later: a run starting or ending, a budget stop, a rejection."""

    __tablename__ = "audit_events"
    __table_args__ = (
        CheckConstraint(f"severity IN {SEVERITIES}", name="severity"),
        Index(None, "run_id"),
        Index(None, "event_type", "occurred_at"),
    )

    event_id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    # Null only for events outside any run (for example a configuration error at start-up).
    run_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("research_runs.run_id", ondelete="RESTRICT"))
    occurred_at: Mapped[datetime] = mapped_column(UTCDateTime)
    event_type: Mapped[str] = mapped_column(String(64))
    severity: Mapped[str] = mapped_column(String(16))
    actor: Mapped[str] = mapped_column(String(64))
    message: Mapped[str] = mapped_column(Text)
    payload: Mapped[dict[str, Any] | None] = mapped_column(JSONType)


STRATEGY_STATUSES = ("PROPOSED", "BACKTESTED", "VALIDATED", "PAPER_APPROVED", "PAPER_ACTIVE", "RETIRED")
BACKTEST_SEGMENTS = ("full", "train", "validation", "test", "walk_forward_window", "walk_forward_oos")


class StrategyVersion(Base):
    """One strategy identity with one exact parameter set (GOVERNANCE.md section 15)."""

    __tablename__ = "strategy_versions"
    __table_args__ = (
        CheckConstraint(f"status IN {STRATEGY_STATUSES}", name="status"),
        UniqueConstraint("identifier", "params_hash"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    identifier: Mapped[str] = mapped_column(String(64))
    params: Mapped[dict[str, Any]] = mapped_column(JSONType)
    params_hash: Mapped[str] = mapped_column(String(32))
    status: Mapped[str] = mapped_column(String(20))
    description: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime)


class BacktestResultRow(Base):
    """One evaluated segment of a backtest run (full, train, validation, test, walk-forward)."""

    __tablename__ = "backtest_results"
    __table_args__ = (
        CheckConstraint(f"segment IN {BACKTEST_SEGMENTS}", name="segment"),
        Index(None, "run_id"),
        Index(None, "strategy_version_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    run_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("research_runs.run_id", ondelete="RESTRICT"))
    strategy_version_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("strategy_versions.id", ondelete="RESTRICT"))
    segment: Mapped[str] = mapped_column(String(24))
    period_start: Mapped[date] = mapped_column(Date)
    period_end: Mapped[date] = mapped_column(Date)
    data_fingerprint: Mapped[str] = mapped_column(String(32))
    data_source: Mapped[str] = mapped_column(String(128))
    config: Mapped[dict[str, Any]] = mapped_column(JSONType)
    metrics: Mapped[dict[str, Any]] = mapped_column(JSONType)
    regimes: Mapped[dict[str, Any] | None] = mapped_column(JSONType)
    # Equity curve of the segment: {"dates": [...ISO dates], "values": [...]} (migration 0005).
    equity: Mapped[dict[str, Any] | None] = mapped_column(JSONType)
    notes: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime)


class ScreeningResultRow(Base):
    """One deterministic screen: its inputs (by fingerprint), funnel, rejections and cost limit."""

    __tablename__ = "screening_results"
    __table_args__ = (Index(None, "run_id"), Index(None, "as_of"))

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    run_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("research_runs.run_id", ondelete="RESTRICT"))
    as_of: Mapped[date] = mapped_column(Date)
    universe: Mapped[str] = mapped_column(String(128))
    universe_fingerprint: Mapped[str] = mapped_column(String(32))
    data_fingerprint: Mapped[str] = mapped_column(String(32))
    config_fingerprint: Mapped[str] = mapped_column(String(32))
    inputs_fingerprint: Mapped[str] = mapped_column(String(32))
    data_source: Mapped[str] = mapped_column(String(128))
    config: Mapped[dict[str, Any]] = mapped_column(JSONType)
    funnel: Mapped[dict[str, Any]] = mapped_column(JSONType)
    rejections: Mapped[dict[str, Any]] = mapped_column(JSONType)
    cost: Mapped[dict[str, Any]] = mapped_column(JSONType)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime)


class ScreeningCandidate(Base):
    """A symbol a screen selected for later research, in rank order. Not a trade signal."""

    __tablename__ = "screening_candidates"
    __table_args__ = (
        CheckConstraint("rank >= 1", name="rank"),
        UniqueConstraint("screening_result_id", "rank"),
        UniqueConstraint("screening_result_id", "symbol"),
        Index(None, "symbol"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    screening_result_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("screening_results.id", ondelete="CASCADE"))
    rank: Mapped[int] = mapped_column(Integer)
    symbol: Mapped[str] = mapped_column(String(16))
    composite: Mapped[float] = mapped_column(Float)
    factor_ranks: Mapped[dict[str, Any]] = mapped_column(JSONType)
    factor_values: Mapped[dict[str, Any]] = mapped_column(JSONType)
