"""Persistence on SQLite: the unit-level stand-in for PostgreSQL.

The same checks run against a real PostgreSQL in test_persistence_postgres.py.
"""

import pytest

from sid_trading_firm.persistence import Database, make_engine
from sid_trading_firm.persistence.migrate import downgrade, upgrade
from sid_trading_firm.persistence.models import Base
from tests_sid import persistence_checks as checks

pytestmark = pytest.mark.unit


@pytest.fixture
def db():
    engine = make_engine("sqlite://")
    Base.metadata.create_all(engine)
    yield Database(engine)
    engine.dispose()


@pytest.fixture
def migrated(tmp_path):
    url = f"sqlite:///{(tmp_path / 'sid.db').as_posix()}"
    upgrade(url)
    engine = make_engine(url)
    yield Database(engine), url
    engine.dispose()


def test_migrations_build_exactly_the_modelled_schema(migrated):
    db, _ = migrated
    assert checks.schema_matches_models(db) == []


def test_migrations_downgrade_cleanly(migrated):
    db, url = migrated
    db.engine.dispose()
    downgrade(url, "base")
    from sqlalchemy import inspect
    assert set(inspect(make_engine(url)).get_table_names()) <= {"alembic_version"}


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


def test_call_details_round_trip(db):
    checks.check_call_details_round_trip(db)
