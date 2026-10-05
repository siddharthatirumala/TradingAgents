"""Screening records in the database: SQLite (unit) and PostgreSQL (integration, CI)."""

import os

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from sid_trading_firm.persistence import Database, RunRepository, make_engine
from sid_trading_firm.persistence.migrate import upgrade
from sid_trading_firm.persistence.models import Base
from sid_trading_firm.persistence.screening import ScreeningRepository
from sid_trading_firm.runtime import new_run_id, run_context
from tests_sid.fakes import settings

PG_URL = os.environ.get("SID_TEST_DATABASE_URL")


def result(**over):
    base = {
        "as_of": "2026-09-30", "universe": "t_v1", "universe_fingerprint": "u" * 16, "data_fingerprint": "d" * 16,
        "config_fingerprint": "c" * 16, "inputs_fingerprint": "i" * 16,
        "config": {"filters": {"min_price": 5.0}, "max_candidates": 2},
        "funnel": {"universe": 4, "selected": 2},
        "selected": [{"symbol": "AAA", "composite": 1.0, "ranks": {"momentum": 1.0}, "raw": {"momentum": 0.3}},
                     {"symbol": "BBB", "composite": 0.5, "ranks": {"momentum": 0.5}, "raw": {"momentum": 0.1}}],
        "rejected": {"CCC": ["price 2.00 < 5.0"]}, "excluded": {}, "missing_data": ["DDD"],
        "cost": {"per_candidate_usd": "0.80", "selected": 2, "estimated_total_usd": "1.60", "limit": 2,
                 "limited_by": "max_candidates"},
    }
    base.update(over)
    return base


def started_run(db):
    with run_context() as run:
        RunRepository(db).start(run, kind="screen", settings=settings())
    return run.run_id


def check_round_trip(db):
    run_id = started_run(db)
    repo = ScreeningRepository(db)
    rid = repo.record(run_id=run_id, result=result(), data_source="csv:test")
    (row,) = repo.results_for_run(run_id)
    assert row.id == rid and str(row.as_of) == "2026-09-30" and row.inputs_fingerprint == "i" * 16
    assert row.rejections == {"filters": {"CCC": ["price 2.00 < 5.0"]}, "scoring": {}, "missing_data": ["DDD"]}
    candidates = repo.candidates(rid)
    assert [(c.rank, c.symbol) for c in candidates] == [(1, "AAA"), (2, "BBB")]
    assert candidates[0].factor_values == {"momentum": 0.3}


def check_guards(db):
    repo = ScreeningRepository(db)
    with pytest.raises(IntegrityError):                     # a screen needs its research run
        repo.record(run_id=new_run_id(), result=result(), data_source="x")
    run_id = started_run(db)
    twice = result(selected=[result()["selected"][0]] * 2)
    with pytest.raises(IntegrityError):                     # a symbol appears once per screen
        repo.record(run_id=run_id, result=twice, data_source="x")


def check_text_is_sanitised(db):
    run_id = started_run(db)
    secret = "synth" + "-pw-77"
    ScreeningRepository(db).record(run_id=run_id, result=result(rejected={"X": ["password='" + secret + "'"]}),
                                   data_source="postgresql://u:" + secret + "@h/db")
    with db.engine.connect() as c:
        stored = str(c.execute(text("SELECT data_source, rejections FROM screening_results")).all())
    assert secret not in stored


CHECKS = [check_round_trip, check_guards, check_text_is_sanitised]


@pytest.fixture
def sqlite_db():
    engine = make_engine("sqlite://")
    Base.metadata.create_all(engine)
    yield Database(engine)
    engine.dispose()


@pytest.fixture
def postgres_db():
    upgrade(PG_URL)
    engine = make_engine(PG_URL)
    yield Database(engine)
    with engine.begin() as c:
        c.execute(text("TRUNCATE screening_candidates, screening_results, audit_events, llm_usage, "
                       "research_runs CASCADE"))
    engine.dispose()


@pytest.mark.unit
@pytest.mark.parametrize("check", CHECKS, ids=lambda c: c.__name__)
def test_sqlite(sqlite_db, check):
    check(sqlite_db)


@pytest.mark.integration
@pytest.mark.skipif(not PG_URL, reason="SID_TEST_DATABASE_URL is not set")
@pytest.mark.parametrize("check", CHECKS, ids=lambda c: c.__name__)
def test_postgres(postgres_db, check):
    check(postgres_db)
