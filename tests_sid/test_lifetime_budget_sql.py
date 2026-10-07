"""The lifetime budget in the database ledger: SQLite (unit) and PostgreSQL (integration, CI).

On PostgreSQL, concurrent reservations from separate connections (separate processes in
practice) are serialised by a transaction-scoped advisory lock, so they cannot jointly
pass the cap.
"""

import os
import threading
import uuid
from datetime import UTC, datetime
from decimal import Decimal

import pytest
from sqlalchemy import text

from sid_trading_firm.llm import BudgetGuard, LifetimeBudgetExhausted
from sid_trading_firm.llm.pricing import CostStatus
from sid_trading_firm.llm.usage import LLMCallRecord
from sid_trading_firm.persistence import Database, RunRepository, SqlUsageStore, make_engine
from sid_trading_firm.persistence.migrate import upgrade
from sid_trading_firm.persistence.models import Base
from sid_trading_firm.runtime import run_context
from tests_sid.fakes import settings

PG_URL = os.environ.get("SID_TEST_DATABASE_URL")
CAP = Decimal("0.05")
WORST = Decimal("0.012")


def started_run(db) -> str:
    with run_context() as run:
        RunRepository(db).start(run, kind="research", settings=settings())
    return run.run_id


def usage(run_id, call_id, cost):
    now = datetime.now(UTC)
    return LLMCallRecord(
        run_id=run_id, agent="cio", provider="anthropic", model="claude-sonnet-5-5", started_at=now,
        finished_at=now, latency_ms=1.0, success=True, input_tokens=1, output_tokens=1, cache_read_tokens=0,
        cache_write_tokens=0, usage_available=True, estimated_cost_usd=Decimal(cost),
        cost_status=CostStatus.PRICED, estimated_input_tokens=1, prompt_chars=3, call_id=call_id)


def check_reservations_and_lifetime_spend(db):
    store, run = SqlUsageStore(db), started_run(db)
    legacy = str(uuid.uuid4())
    store.add(usage(run, legacy, "0.01"))                                # spend already in the ledger
    ids = [str(uuid.uuid4()) for _ in range(4)]
    assert store.try_reserve(call_id=ids[0], run_id=run, agent="cio", amount=WORST, cap=CAP) == (True, Decimal("0.01"))
    assert store.lifetime_spent_usd() == Decimal("0.022")               # recorded + open reservation
    store.add(usage(run, ids[0], "0.004"))
    store.settle_reservation(ids[0], assumed_usd=None)                  # actual cost replaces the reservation
    assert store.lifetime_spent_usd() == Decimal("0.014")
    store.try_reserve(call_id=ids[1], run_id=run, agent="cio", amount=WORST, cap=CAP)
    store.settle_reservation(ids[1], assumed_usd=WORST)                 # unknown cost: worst case kept
    store.try_reserve(call_id=ids[2], run_id=run, agent="cio", amount=WORST, cap=CAP)
    store.release_reservation(ids[2])                                   # never reached the provider
    assert store.lifetime_spent_usd() == Decimal("0.026")
    ok, spent = store.try_reserve(call_id=ids[3], run_id=run, agent="cio", amount=Decimal("0.025"), cap=CAP)
    assert (ok, spent) == (False, Decimal("0.026"))                     # 0.026 + 0.025 > 0.05
    with db.engine.connect() as c:
        assert c.execute(text("SELECT count(*) FROM budget_reservations")).scalar() == 3
    with pytest.raises(ValueError, match="already settled"):
        store.settle_reservation(ids[0], assumed_usd=None)


def check_the_exhausted_marker_is_permanent_and_shared(db):
    store = SqlUsageStore(db)
    assert not store.lifetime_exhausted()
    store.mark_lifetime_exhausted("cap reached in test")
    store.mark_lifetime_exhausted("again")
    assert SqlUsageStore(db).lifetime_exhausted()                        # another process, same database
    with db.engine.connect() as c:
        assert c.execute(text("SELECT count(*) FROM audit_events WHERE event_type = 'ai_lifetime_budget_exhausted'")
                         ).scalar() == 1


def check_the_guard_stops_at_the_cap_on_the_database_ledger(db):
    s = settings(max_ai_cost_per_run_usd=str(CAP), max_ai_cost_per_day_usd=str(CAP), max_ai_cost_total_usd=str(CAP))
    store = SqlUsageStore(db)
    granted = 0
    for _ in range(6):
        guard = BudgetGuard(s.budgets, s.pricing, store)                 # a fresh guard (process) per call
        try:
            guard.authorize(run_id=started_run(db), agent="cio", provider="anthropic", model="claude-sonnet-5-5",
                            prompt_chars=3000, max_output_tokens=1000)
            granted += 1
        except LifetimeBudgetExhausted:
            pass
    assert granted == 4 and store.lifetime_spent_usd() == 4 * WORST and store.lifetime_exhausted()


CHECKS = [check_reservations_and_lifetime_spend, check_the_exhausted_marker_is_permanent_and_shared,
          check_the_guard_stops_at_the_cap_on_the_database_ledger]


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
        c.execute(text("TRUNCATE budget_reservations, audit_events, llm_usage, research_runs CASCADE"))
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


@pytest.mark.integration
@pytest.mark.skipif(not PG_URL, reason="SID_TEST_DATABASE_URL is not set")
def test_postgres_concurrent_connections_cannot_jointly_pass_the_cap(postgres_db):
    run = started_run(postgres_db)
    engines = [make_engine(PG_URL) for _ in range(16)]                  # separate pools: separate connections
    start = threading.Barrier(16)
    results = []

    def reserve(engine):
        store = SqlUsageStore(Database(engine))
        start.wait()
        results.append(store.try_reserve(call_id=str(uuid.uuid4()), run_id=run, agent="cio", amount=WORST, cap=CAP)[0])

    threads = [threading.Thread(target=reserve, args=(e,)) for e in engines]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    for e in engines:
        e.dispose()
    assert results.count(True) == 4 and results.count(False) == 12
    assert SqlUsageStore(postgres_db).lifetime_spent_usd() == 4 * WORST <= CAP
