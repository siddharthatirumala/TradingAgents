"""Persistence behaviour checked identically on SQLite (unit) and PostgreSQL (integration)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from sqlalchemy.exc import IntegrityError

from sid_trading_firm.llm import BudgetExceeded, BudgetGuard, LedgerUnavailable, UsageLedger
from sid_trading_firm.llm.pricing import CostStatus
from sid_trading_firm.llm.usage import LLMCallRecord
from sid_trading_firm.persistence import AuditLog, RunRepository, SqlUsageStore
from sid_trading_firm.persistence.models import Base
from sid_trading_firm.runtime import agent_context, new_run_id, run_context
from tests_sid.fakes import FakeChatModel, settings


def schema_matches_models(db) -> list:
    with db.engine.connect() as connection:
        return compare_metadata(MigrationContext.configure(connection), Base.metadata)


def record(run_id, cost="0.004", at=None, agent="cio", tokens=(1000, 200)) -> LLMCallRecord:
    at = at or datetime.now(UTC)
    return LLMCallRecord(
        run_id=run_id, agent=agent, provider="anthropic", model="claude-sonnet-5-5",
        started_at=at, finished_at=at + timedelta(seconds=2), latency_ms=2000.0, success=True,
        input_tokens=tokens[0] if tokens else None, output_tokens=tokens[1] if tokens else None,
        cache_read_tokens=0 if tokens else None, cache_write_tokens=0 if tokens else None,
        usage_available=tokens is not None,
        estimated_cost_usd=Decimal(cost) if cost is not None else None,
        cost_status=CostStatus.PRICED if cost is not None else CostStatus.NO_USAGE,
        estimated_input_tokens=1000, prompt_chars=3000, node="Portfolio Manager")


def check_run_lifecycle(db):
    runs = RunRepository(db)
    s = settings()
    with run_context(instrument="NVDA", strategy="baseline", environment="test") as run:
        runs.start(run, kind="baseline_measurement", settings=s)
    row = runs.get(run.run_id)
    assert (row.status, row.instrument, row.strategy, row.kind) == (
        "running", "NVDA", "baseline", "baseline_measurement")
    assert row.config_snapshot["budgets"]["max_debate_rounds"] == 1

    runs.finish(run.run_id, status="completed", summary={"calls": 15})
    row = runs.get(run.run_id)
    assert row.status == "completed" and row.summary == {"calls": 15} and row.finished_at

    with pytest.raises(ValueError):
        runs.finish(run.run_id, status="running")
    with pytest.raises(LookupError):
        runs.finish(new_run_id(), status="failed")


def check_usage_round_trip_and_sums(db):
    runs, store = RunRepository(db), SqlUsageStore(db)
    with run_context() as run:
        runs.start(run, kind="analysis", settings=settings())
    with run_context() as other:
        runs.start(other, kind="analysis", settings=settings())

    now = datetime.now(UTC)
    store.add(record(run.run_id, "0.004", now))
    store.add(record(run.run_id, None, now, tokens=None))          # usage unknown
    store.add(record(other.run_id, "0.010", now))
    store.add(record(other.run_id, "0.500", now - timedelta(days=1)))

    back = store.records(run.run_id)
    assert [r.usage_available for r in back] in ([True, False], [False, True])
    known = next(r for r in back if r.usage_available)
    assert (known.input_tokens, known.output_tokens, known.agent, known.node) == (
        1000, 200, "cio", "Portfolio Manager")
    assert known.started_at.tzinfo is not None
    unknown = next(r for r in back if not r.usage_available)
    assert unknown.input_tokens is None and unknown.estimated_cost_usd is None
    assert unknown.cost_status == CostStatus.NO_USAGE

    assert store.spent_usd(run_id=run.run_id) == pytest.approx(Decimal("0.004"))
    assert store.spent_usd(day=now.date()) == pytest.approx(Decimal("0.014"))
    assert store.spent_usd(day=(now - timedelta(days=1)).date()) == pytest.approx(Decimal("0.5"))


def check_usage_needs_its_run(db):
    with pytest.raises(IntegrityError):
        SqlUsageStore(db).add(record(new_run_id()))


def check_metered_calls_land_in_the_database(db):
    runs, store, audit = RunRepository(db), SqlUsageStore(db), AuditLog(db)
    s = settings(max_agent_iterations=1)
    guard = BudgetGuard(s.budgets, s.pricing, store)
    guard.add_stop_listener(audit.budget_stop_listener())
    model = FakeChatModel(callbacks=[UsageLedger(guard)])

    with run_context(instrument="AAPL") as run, agent_context("cio"):
        runs.start(run, kind="analysis", settings=s)
        model.invoke("first")
        with pytest.raises(BudgetExceeded):
            model.invoke("second")

    assert len(store.records(run.run_id)) == 1
    (event,) = audit.for_run(run.run_id)
    assert (event.event_type, event.severity, event.actor) == ("budget.stop", "error", "cio")
    assert event.payload["reason"] == "agent_iterations"


def check_ledger_without_a_run_row_stops_the_run(db):
    s = settings()
    guard = BudgetGuard(s.budgets, s.pricing, SqlUsageStore(db))
    model = FakeChatModel(callbacks=[UsageLedger(guard)])
    with run_context(), agent_context("cio"), pytest.raises(LedgerUnavailable):
        model.invoke("no research_runs row for this run")


def check_secrets_are_not_stored(db, monkeypatch):
    monkeypatch.setenv("SID_DATABASE__URL", "postgresql+psycopg://sid:hunter2@db/sid")
    runs = RunRepository(db)
    with run_context() as run:
        runs.start(run, kind="analysis", settings=settings())
    assert "hunter2" not in str(runs.get(run.run_id).config_snapshot)
