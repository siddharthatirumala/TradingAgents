"""The screening runner: specification, end-to-end run, report, storage."""

import json
import uuid

import numpy as np
import pandas as pd
import pytest
import yaml
from pydantic import ValidationError

from sid_trading_firm.screening import run as runner
from tests_sid.fakes import settings

pytestmark = pytest.mark.unit

DRIFTS = {"AAA": 0.003, "BBB": 0.002, "CCC": 0.001, "DDD": -0.001, "PENNY": 0.002, "SPY": 0.001}


def write_synthetic_csvs(directory, n=300):
    """Seeded synthetic prices (not market data)."""
    rng = np.random.default_rng(11)
    dates = pd.bdate_range("2025-01-01", periods=n)
    for symbol, mu in DRIFTS.items():
        start = 2.0 if symbol == "PENNY" else 100.0
        close = start * np.cumprod(1 + rng.normal(mu, 0.01, n))
        pd.DataFrame({"Date": dates, "Open": close, "High": close * 1.01, "Low": close * 0.99, "Close": close,
                      "Volume": 2_000_000}).to_csv(directory / f"{symbol}.csv", index=False)


UNIVERSE = {"name": "synthetic", "version": "v1", "source": "test", "as_of": "2026-01-01",
            "survivorship_note": "Survivorship bias: synthetic list.",
            "members": [{"symbol": s, "asset_type": "common_stock"} for s in ("AAA", "BBB", "CCC", "DDD", "PENNY",
                                                                               "GONE")]
            + [{"symbol": "SPY", "asset_type": "etf"}]}


def spec_dict(**over):
    base = {"name": "synthetic_screen", "universe": "universe.yaml",
            "data": {"source": "csv", "path": "data", "symbols": ["AAA", "BBB", "CCC", "DDD", "PENNY", "SPY"]},
            "as_of": "2026-02-13",
            "filters": {"min_price": 5, "min_avg_dollar_volume": 1_000_000, "min_history_days": 252,
                        "max_data_age_days": 5},
            "scoring": {"factors": {"momentum": {"weight": 2}, "low_volatility": {"weight": 1}}},
            "max_candidates": 3, "research_cost_per_candidate_usd": "0.80"}
    base.update(over)
    return base


@pytest.fixture
def workspace(tmp_path):
    (tmp_path / "data").mkdir()
    write_synthetic_csvs(tmp_path / "data")
    (tmp_path / "universe.yaml").write_text(yaml.safe_dump(UNIVERSE), encoding="utf-8")
    spec_file = tmp_path / "screen.yaml"
    spec_file.write_text(yaml.safe_dump(spec_dict()), encoding="utf-8")
    return tmp_path, spec_file


def test_end_to_end_screen(workspace):
    tmp, spec_file = workspace
    result = runner.run(runner.load_spec(spec_file), base=tmp, budgets=settings().budgets)
    assert result["funnel"] == {"universe": 7, "eligible_common_stocks": 6, "with_data": 5,
                                "passed_filters": 4, "scored": 4, "selected": 3}
    assert len(result["selected"]) == 3 and "SPY" not in {c["symbol"] for c in result["selected"]}
    assert list(result["rejected"]) == ["PENNY"] and result["missing_data"] == ["GONE"]
    assert result["cost"]["estimated_total_usd"] == "2.40"
    json.dumps(result, default=str)


def test_screens_are_reproducible(workspace):
    tmp, spec_file = workspace
    a = runner.run(runner.load_spec(spec_file), base=tmp, budgets=settings().budgets)
    b = runner.run(runner.load_spec(spec_file), base=tmp, budgets=settings().budgets)
    assert a["inputs_fingerprint"] == b["inputs_fingerprint"] and a["selected"] == b["selected"]


def test_report_states_what_the_screen_is_and_is_not(workspace):
    tmp, spec_file = workspace
    text = runner.render_report(runner.run(runner.load_spec(spec_file), base=tmp, budgets=settings().budgets))
    for phrase in ("no AI model", "not recommendations or trade signals", "Survivorship bias", "## Funnel",
                   "limit 3 set by max_candidates", "PENNY", "GONE | no price data"):
        assert phrase in text, phrase
    for forbidden in ("buy", "sell", "guaranteed"):
        assert forbidden not in text.lower()


@pytest.mark.parametrize("change, message", [
    ({"max_candidates": 0}, "greater than or equal to 1"),
    ({"research_cost_per_candidate_usd": "0"}, "greater than 0"),
    ({"scoring": {"factors": {"vibes": {"weight": 1}}}}, "unknown factors"),
    ({"filters": {"min_price": -1}}, "greater than 0"),
    ({"extra": True}, "Extra inputs"),
])
def test_invalid_specifications_are_refused(change, message):
    with pytest.raises(ValidationError, match=message):
        runner.ScreenSpec.model_validate(spec_dict(**change))


def test_cli_writes_report_and_stores_the_screen(workspace, monkeypatch):
    tmp, spec_file = workspace
    from sqlalchemy import text

    from sid_trading_firm.persistence import Database, make_engine
    from sid_trading_firm.persistence.migrate import upgrade
    from sid_trading_firm.persistence.screening import ScreeningRepository

    url = f"sqlite:///{(tmp / 'sid.db').as_posix()}"
    upgrade(url)
    monkeypatch.setenv("SID_DATABASE__URL", url)
    out = tmp / "out"
    assert runner.main([str(spec_file), "--out", str(out), "--database"]) == 0
    assert (out / "report.md").is_file() and (out / "results.json").is_file()
    engine = make_engine(url)
    with engine.connect() as c:
        run_id, kind, status = c.execute(text("SELECT run_id, kind, status FROM research_runs")).one()
    assert (kind, status) == ("screen", "completed")
    repo = ScreeningRepository(Database(engine))
    (row,) = repo.results_for_run(str(uuid.UUID(str(run_id))))
    saved = json.loads((out / "results.json").read_text(encoding="utf-8"))
    assert [c.symbol for c in repo.candidates(row.id)] == [c["symbol"] for c in saved["selected"]]
    engine.dispose()


def test_a_storage_failure_marks_the_run_failed(workspace, monkeypatch):
    tmp, spec_file = workspace
    from sqlalchemy import text

    from sid_trading_firm.persistence import make_engine
    from sid_trading_firm.persistence.migrate import upgrade
    from sid_trading_firm.persistence.screening import ScreeningRepository

    url = f"sqlite:///{(tmp / 'sid.db').as_posix()}"
    upgrade(url)
    monkeypatch.setenv("SID_DATABASE__URL", url)

    def broken(self, **kwargs):
        raise RuntimeError("disk full")

    monkeypatch.setattr(ScreeningRepository, "record", broken)
    with pytest.raises(RuntimeError, match="disk full"):
        runner.main([str(spec_file), "--out", str(tmp / "out"), "--database"])
    engine = make_engine(url)
    with engine.connect() as c:
        status, error = c.execute(text("SELECT status, error FROM research_runs")).one()
    engine.dispose()
    assert status == "failed" and "disk full" in error


def test_the_example_specification_in_the_repository_is_valid():
    from pathlib import Path

    from sid_trading_firm.screening.universe import load_universe

    example = Path(__file__).resolve().parents[1] / "docs" / "sid_trading_firm" / "examples" / "screen_large_cap.yaml"
    spec = runner.load_spec(example)
    universe = load_universe(example.parent / spec.universe)
    assert set(universe.candidates) | set(universe.etfs) == set(spec.data.symbols)
    assert spec.research_cost_per_candidate_usd <= settings().budgets.max_ai_cost_per_run_usd
