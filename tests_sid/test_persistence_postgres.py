"""Persistence against a real PostgreSQL.

Runs only when ``SID_TEST_DATABASE_URL`` points at a disposable database (CI
starts one; locally, ``docker compose -f compose.sid.yaml up -d`` and a separate
test database). Selected with ``pytest tests_sid -m integration``.
"""

import os
import uuid
from datetime import UTC, datetime
from decimal import Decimal

import pytest
from sqlalchemy import inspect, text

from sid_trading_firm.persistence import (
    AuditLog,
    Database,
    RunRepository,
    SqlUsageStore,
    make_engine,
)
from sid_trading_firm.persistence.migrate import downgrade, upgrade
from sid_trading_firm.runtime import run_context
from tests_sid import persistence_checks as checks
from tests_sid.fakes import settings

URL = os.environ.get("SID_TEST_DATABASE_URL")

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(not URL, reason="SID_TEST_DATABASE_URL is not set"),
]


@pytest.fixture
def db():
    upgrade(URL)
    engine = make_engine(URL)
    yield Database(engine)
    with engine.begin() as connection:
        connection.execute(text("TRUNCATE audit_events, llm_usage, research_runs"))
    engine.dispose()


def test_migrations_build_exactly_the_modelled_schema(db):
    assert db.engine.dialect.name == "postgresql"
    assert checks.schema_matches_models(db) == []


def test_postgres_types(db):
    """JSONB, exact NUMERIC money and timezone-aware times survive a round trip."""
    runs, store, audit = RunRepository(db), SqlUsageStore(db), AuditLog(db)
    with run_context() as run:
        runs.start(run, kind="analysis", settings=settings())
    store.add(checks.record(run.run_id, cost="0.00012345"))
    audit.record("run.note", "typed payload", run_id=run.run_id, payload={"nested": {"n": 1}})

    columns = {c["name"]: c["type"] for c in inspect(db.engine).get_columns("audit_events")}
    assert type(columns["payload"]).__name__ == "JSONB"
    (back,) = store.records(run.run_id)
    assert back.estimated_cost_usd == Decimal("0.00012345")                 # exact, not float
    assert back.started_at.utcoffset() is not None
    assert store.spent_usd(day=datetime.now(UTC).date()) == Decimal("0.00012345")
    assert audit.for_run(run.run_id)[0].payload == {"nested": {"n": 1}}
    assert isinstance(runs.get(run.run_id).run_id, uuid.UUID)


def test_run_lifecycle(db):
    checks.check_run_lifecycle(db)


def test_usage_round_trip_and_sums(db):
    checks.check_usage_round_trip_and_sums(db)


def test_usage_needs_its_run(db):
    checks.check_usage_needs_its_run(db)


def test_metered_calls_land_in_the_database(db):
    checks.check_metered_calls_land_in_the_database(db)


def test_ledger_without_a_run_row_stops_the_run(db):
    checks.check_ledger_without_a_run_row_stops_the_run(db)


def test_secrets_are_not_stored(db, monkeypatch):
    checks.check_secrets_are_not_stored(db, monkeypatch)


def test_downgrade_and_upgrade_round_trip():
    upgrade(URL)
    downgrade(URL, "base")
    engine = make_engine(URL)
    assert set(inspect(engine).get_table_names()) <= {"alembic_version"}
    engine.dispose()
    upgrade(URL)
