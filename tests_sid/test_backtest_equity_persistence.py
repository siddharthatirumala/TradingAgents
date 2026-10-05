"""A complete equity curve round-trips exactly through BacktestRepository:
SQLite (unit) and PostgreSQL (integration, CI)."""

import os

import pandas as pd
import pytest
from sqlalchemy import text

from sid_trading_firm.backtest.oos import curve_dict
from sid_trading_firm.persistence import Database, RunRepository, make_engine
from sid_trading_firm.persistence.backtests import BacktestRepository, equity_from_storage
from sid_trading_firm.persistence.migrate import upgrade
from sid_trading_firm.persistence.models import Base
from sid_trading_firm.runtime import run_context
from sid_trading_firm.strategies import create, spec_for
from tests_sid.fakes import settings

PG_URL = os.environ.get("SID_TEST_DATABASE_URL")


def awkward_curve() -> dict:
    """Five years of business days with values chosen to expose any float or date drift."""
    dates = pd.bdate_range("2021-01-04", "2025-12-31")
    specials = [100_000.0, 0.1 + 0.2, 1e-300, 123456789.12345679, 99_999.99999999999, 5e-324, 1.7976931348623157e308]
    values = [specials[i] if i < len(specials) else 100_000.0 * (1 + (i % 97) / 1e7) + i / 3
              for i in range(len(dates))]
    return curve_dict(pd.Series(values, index=dates))


def check_equity_round_trips_exactly(db):
    with run_context() as run:
        RunRepository(db).start(run, kind="backtest", settings=settings())
    repo = BacktestRepository(db)
    spec = spec_for(create("buy_and_hold_v1", {"symbols": ["SPY"]}))
    vid = repo.strategy_version(spec.identifier, spec.params, spec.params_hash)
    curve = awkward_curve()
    report = {"start": curve["dates"][0], "end": curve["dates"][-1], "data_fingerprint": "f" * 16,
              "metrics": {"total_return": {"value": 0.1, "status": "ok", "reason": None}}}
    rid = repo.record(run_id=run.run_id, version_id=vid, segment="full", report=report, config={},
                      data_source="synthetic", equity=curve)

    (row,) = repo.results_for_run(run.run_id)
    assert row.id == rid
    stored = repo.equity_curve(rid)
    assert stored["dates"] == curve["dates"]                           # every date, in order
    assert all(type(v) is float for v in stored["values"])
    assert [v.hex() for v in stored["values"]] == [v.hex() for v in curve["values"]]   # bit-exact
    assert len(stored["dates"]) == len(pd.bdate_range("2021-01-04", "2025-12-31"))

    # Read back with raw SQL too, not just through the ORM (on PostgreSQL over a fresh connection;
    # an in-memory SQLite database lives only as long as its single pooled connection).
    if db.engine.dialect.name != "sqlite":
        db.engine.dispose()
    with db.engine.connect() as c:
        raw = c.execute(text("SELECT equity FROM backtest_results WHERE segment = 'full'")).scalar_one()
    if isinstance(raw, str):                                           # SQLite returns JSON text
        import json

        raw = json.loads(raw)
    # The raw JSON keeps each value's exact decimal; on PostgreSQL a very large magnitude may
    # decode as int, which equity_from_storage turns back into the identical float.
    restored = equity_from_storage(raw)
    assert raw["dates"] == curve["dates"]
    assert [v.hex() for v in restored["values"]] == [v.hex() for v in curve["values"]]


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
        c.execute(text("TRUNCATE backtest_results, strategy_versions, audit_events, llm_usage, research_runs CASCADE"))
    engine.dispose()


@pytest.mark.unit
def test_sqlite(sqlite_db):
    check_equity_round_trips_exactly(sqlite_db)


@pytest.mark.integration
@pytest.mark.skipif(not PG_URL, reason="SID_TEST_DATABASE_URL is not set")
def test_postgres(postgres_db):
    check_equity_round_trips_exactly(postgres_db)



@pytest.mark.unit
@pytest.mark.parametrize("bad, message", [
    ({"dates": ["2026-01-02"], "values": [float("nan")]}, "finite real numbers"),
    ({"dates": ["2026-01-02"], "values": [float("inf")]}, "finite real numbers"),
    ({"dates": ["2026-01-02"], "values": [True]}, "finite real numbers"),
    ({"dates": ["2026-01-02"], "values": ["100.0"]}, "finite real numbers"),
    ({"dates": ["02/01/2026"], "values": [1.0]}, "Invalid isoformat"),
    ({"dates": [20260102], "values": [1.0]}, "ISO date strings"),
])
def test_malformed_equity_is_refused_before_storage(sqlite_db, bad, message):
    with run_context() as run:
        RunRepository(sqlite_db).start(run, kind="backtest", settings=settings())
    repo = BacktestRepository(sqlite_db)
    spec = spec_for(create("buy_and_hold_v1", {"symbols": ["SPY"]}))
    vid = repo.strategy_version(spec.identifier, spec.params, spec.params_hash)
    with pytest.raises(ValueError, match=message):
        repo.record(run_id=run.run_id, version_id=vid, segment="full",
                    report={"start": "2026-01-02", "end": "2026-01-02", "data_fingerprint": "x", "metrics": {}},
                    config={}, data_source="x", equity=bad)
    assert repo.results_for_run(run.run_id) == []


@pytest.mark.unit
def test_postgres_style_integer_rendering_is_restored_to_the_exact_float():
    big = 1.7976931348623157e308
    as_postgres_returns_it = int("17976931348623157" + "0" * 292)     # JSONB numeric without exponent
    restored = equity_from_storage({"dates": ["2026-01-02", "2026-01-05"], "values": [as_postgres_returns_it, 100000]})
    assert restored["values"][0].hex() == big.hex() and type(restored["values"][1]) is float
