"""Run context: unique ids, scoping, nesting and propagation into threads."""

import contextvars
import uuid
from concurrent.futures import ThreadPoolExecutor

import pytest

from sid_trading_firm.runtime import (
    NoActiveRun,
    agent_context,
    current_agent,
    current_run_id,
    new_run_id,
    require_run,
    run_context,
)
from sid_trading_firm.runtime.context import log_fields

pytestmark = pytest.mark.unit


def test_run_ids_are_unique_uuids():
    ids = {new_run_id() for _ in range(1000)}
    assert len(ids) == 1000
    assert all(uuid.UUID(i).version == 4 for i in ids)


def test_a_run_is_visible_inside_its_block_only():
    assert current_run_id() is None
    with run_context(instrument="NVDA", strategy="baseline", environment="test") as run:
        assert current_run_id() == run.run_id
        assert require_run().instrument == "NVDA"
    assert current_run_id() is None
    with pytest.raises(NoActiveRun):
        require_run()


def test_the_run_ends_even_when_the_block_raises():
    with pytest.raises(ZeroDivisionError), run_context():
        1 / 0  # noqa: B018
    assert current_run_id() is None


def test_runs_do_not_nest():
    with run_context(), pytest.raises(RuntimeError, match="do not nest"), run_context():
        pass


def test_a_malformed_explicit_run_id_is_rejected():
    with pytest.raises(ValueError), run_context(run_id="not-a-uuid"):
        pass


def test_agent_attribution_is_scoped():
    with run_context(), agent_context("bull_researcher"):
        assert current_agent() == "bull_researcher"
        with agent_context("bear_researcher"):
            assert current_agent() == "bear_researcher"
        assert current_agent() == "bull_researcher"
    assert current_agent() is None


def test_threads_started_with_a_copied_context_see_the_run():
    with run_context(instrument="AAPL") as run, ThreadPoolExecutor(4) as pool:
        futures = [pool.submit(contextvars.copy_context().run, current_run_id) for _ in range(4)]
        assert {f.result() for f in futures} == {run.run_id}


def test_concurrent_runs_in_separate_contexts_stay_separate():
    def one_run():
        with run_context() as run:
            return run.run_id, current_run_id()

    with ThreadPoolExecutor(8) as pool:
        results = [pool.submit(contextvars.copy_context().run, one_run).result() for _ in range(8)]
    assert all(started == seen for started, seen in results)
    assert len({started for started, _ in results}) == 8


def test_log_fields_carry_the_whole_context():
    with run_context(instrument="MSFT", strategy="s1", environment="test") as run, agent_context("cio"):
        assert log_fields() == {"run_id": run.run_id, "agent": "cio", "instrument": "MSFT",
                                "strategy": "s1", "environment": "test"}
