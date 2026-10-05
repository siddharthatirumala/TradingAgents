"""Backtest records in the database: SQLite (unit) and PostgreSQL (integration, CI)."""

import os

import pandas as pd
import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from sid_trading_firm.backtest.data import PricePanel
from sid_trading_firm.backtest.engine import BacktestConfig, run_backtest
from sid_trading_firm.backtest.metrics import evaluate
from sid_trading_firm.persistence import Database, RunRepository, make_engine
from sid_trading_firm.persistence.backtests import BacktestRepository
from sid_trading_firm.persistence.migrate import upgrade
from sid_trading_firm.persistence.models import STRATEGY_STATUSES, Base
from sid_trading_firm.runtime import new_run_id, run_context
from sid_trading_firm.strategies import StrategyStatus, create, spec_for
from tests_sid.fakes import settings

PG_URL = os.environ.get("SID_TEST_DATABASE_URL")


def frame(closes):
    dates = pd.bdate_range("2026-01-02", periods=len(closes))
    return pd.DataFrame({"date": dates, "open": closes, "high": [c * 1.01 for c in closes],
                         "low": [c * 0.99 for c in closes], "close": closes, "volume": 1e6})


def _backtest():
    panel = PricePanel.from_frames({"SPY": frame([100 + i for i in range(30)])})
    strategy = create("buy_and_hold_v1", {"symbols": ["SPY"]})
    config = BacktestConfig(initial_cash=10_000.0, max_weight=1.0)
    return strategy, config, evaluate(run_backtest(panel, strategy, config), panel, benchmark="SPY")


def check_round_trip(db):
    with run_context() as run:
        RunRepository(db).start(run, kind="backtest", settings=settings())
    repo = BacktestRepository(db)
    strategy, config, report = _backtest()
    spec = spec_for(strategy)
    vid = repo.strategy_version(spec.identifier, spec.params, spec.params_hash, description="benchmark")
    assert repo.strategy_version(spec.identifier, spec.params, spec.params_hash) == vid      # idempotent
    repo.record(run_id=run.run_id, version_id=vid, segment="full", report=report.as_dict(),
                config={"initial_cash": config.initial_cash, "max_weight": config.max_weight},
                data_source="frames (synthetic)")
    (row,) = repo.results_for_run(run.run_id)
    assert row.segment == "full" and row.data_fingerprint == report.data_fingerprint
    assert row.metrics["total_return"]["value"] == pytest.approx(report.value("total_return"))
    assert str(row.period_start) == "2026-01-02"
    assert repo.get_version(vid).status == "PROPOSED"
    repo.set_status(vid, "BACKTESTED")
    assert repo.get_version(vid).status == "BACKTESTED"


def check_guards(db):
    repo = BacktestRepository(db)
    strategy, _, report = _backtest()
    spec = spec_for(strategy)
    vid = repo.strategy_version(spec.identifier, spec.params, spec.params_hash)
    for status in ("PAPER_APPROVED", "PAPER_ACTIVE"):
        with pytest.raises(PermissionError, match="not authorised"):
            repo.set_status(vid, status)
    with pytest.raises(ValueError, match="unknown strategy status"):
        repo.set_status(vid, "LIVE")
    with pytest.raises(ValueError, match="different params"):
        repo.strategy_version(spec.identifier, {"symbols": ["QQQ"]}, spec.params_hash)
    with pytest.raises(IntegrityError):                       # a result needs its research run
        repo.record(run_id=new_run_id(), version_id=vid, segment="full", report=report.as_dict(),
                    config={}, data_source="x")


def check_notes_are_sanitised(db):
    with run_context() as run:
        RunRepository(db).start(run, kind="backtest", settings=settings())
    repo = BacktestRepository(db)
    strategy, _, report = _backtest()
    spec = spec_for(strategy)
    vid = repo.strategy_version(spec.identifier, spec.params, spec.params_hash)
    secret = "synth" + "-pw-55"
    repo.record(run_id=run.run_id, version_id=vid, segment="test", report=report.as_dict(), config={},
                data_source="postgresql://u:" + secret + "@h/db", notes="password='" + secret + "'")
    with db.engine.connect() as c:
        stored = str(c.execute(text("SELECT notes, data_source FROM backtest_results")).all())
    assert secret not in stored


CHECKS = [check_round_trip, check_guards, check_notes_are_sanitised]


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
@pytest.mark.parametrize("check", CHECKS, ids=lambda c: c.__name__)
def test_sqlite(sqlite_db, check):
    check(sqlite_db)


@pytest.mark.integration
@pytest.mark.skipif(not PG_URL, reason="SID_TEST_DATABASE_URL is not set")
@pytest.mark.parametrize("check", CHECKS, ids=lambda c: c.__name__)
def test_postgres(postgres_db, check):
    check(postgres_db)


@pytest.mark.unit
def test_database_statuses_match_the_strategy_lifecycle():
    assert tuple(s.value for s in StrategyStatus) == STRATEGY_STATUSES
