"""The backtest runner: specification, end-to-end run, report disclosures, storage."""

import json

import numpy as np
import pandas as pd
import pytest
import yaml
from pydantic import ValidationError

from sid_trading_firm.backtest import run as runner

pytestmark = pytest.mark.unit


def write_synthetic_csvs(directory, n=320):
    """Seeded synthetic prices (not market data) for three symbols and a benchmark."""
    rng = np.random.default_rng(42)
    dates = pd.bdate_range("2024-01-01", periods=n)
    drifts = {"AAA": 0.0008, "BBB": 0.0002, "CCC": -0.0003, "SPY": 0.0004}
    for symbol, mu in drifts.items():
        close = 100 * np.cumprod(1 + rng.normal(mu, 0.012, n))
        opens = close * (1 + rng.normal(0, 0.002, n))
        pd.DataFrame({"Date": dates, "Open": opens, "High": np.maximum(opens, close) * 1.005,
                      "Low": np.minimum(opens, close) * 0.995, "Close": close,
                      "Volume": 1_000_000}).to_csv(directory / f"{symbol}.csv", index=False)


def spec_dict(path="data", **over):
    base = {
        "name": "momentum_synthetic",
        "data": {"source": "csv", "path": path, "symbols": ["AAA", "BBB", "CCC", "SPY"]},
        "benchmark": "SPY",
        "strategy": {"id": "momentum_v1", "params": {"lookback": 60, "skip": 5, "top_n": 2,
                                                     "universe": ["AAA", "BBB", "CCC"]},
                     "grid": [{"lookback": 40, "skip": 5, "top_n": 2, "universe": ["AAA", "BBB", "CCC"]},
                              {"lookback": 60, "skip": 5, "top_n": 2, "universe": ["AAA", "BBB", "CCC"]}]},
        "engine": {"initial_cash": 100_000, "max_weight": 0.5, "rebalance": "monthly",
                   "costs": {"per_share": 0.005, "minimum_per_order": 1.0},
                   "slippage": {"half_spread_bps": 2, "impact_bps": 3}},
        "evaluation": {"split": {"train": 0.6, "validation": 0.2},
                       "walk_forward": {"train_days": 120, "test_days": 60}},
    }
    base.update(over)
    return base


@pytest.fixture
def workspace(tmp_path):
    (tmp_path / "data").mkdir()
    write_synthetic_csvs(tmp_path / "data")
    spec_file = tmp_path / "spec.yaml"
    spec_file.write_text(yaml.safe_dump(spec_dict()), encoding="utf-8")
    return tmp_path, spec_file


def test_end_to_end_run_produces_segments_and_walk_forward(workspace):
    tmp, spec_file = workspace
    result = runner.run(runner.load_spec(spec_file), base=tmp)
    assert set(result["segments"]) == {"train", "validation", "test"}
    train, test = result["segments"]["train"], result["segments"]["test"]
    assert train["end"] < result["segments"]["validation"]["start"] <= result["segments"]["validation"]["end"] < test["start"]
    assert result["strategy"]["id"] == "momentum_v1" and len(result["strategy"]["params_hash"]) == 16
    assert result["walk_forward"]["windows"] and result["walk_forward"]["oos_days"] > 0
    assert all(w["chosen_params"]["lookback"] in (40, 60) for w in result["walk_forward"]["windows"])
    json.dumps(result, default=str)                                   # serialisable


def test_runs_are_reproducible(workspace):
    tmp, spec_file = workspace
    a = runner.run(runner.load_spec(spec_file), base=tmp)
    b = runner.run(runner.load_spec(spec_file), base=tmp)
    assert a["data"]["fingerprint"] == b["data"]["fingerprint"]
    assert a["segments"] == b["segments"] and a["walk_forward"] == b["walk_forward"]


def test_report_carries_disclosures_and_assumptions(workspace):
    tmp, spec_file = workspace
    text = runner.render_report(runner.run(runner.load_spec(spec_file), base=tmp))
    for phrase in ("no AI model", "survivorship", "adjusted", "In-sample (train) results are not evidence",
                   "do not establish future profitability", '"half_spread_bps": 2.0', "Walk-forward (out of sample)",
                   "Train / validation / test", "no exit costs"):
        assert phrase in text, phrase
    for forbidden in ("profitable strategy", "robust", "guaranteed"):
        assert forbidden not in text.lower()


@pytest.mark.parametrize("change, message", [
    ({"benchmark": "QQQ"}, "benchmark must be one of"),
    ({"data": {"source": "csv", "symbols": ["AAA"]}}, "needs a path"),
    ({"data": {"source": "yahoo", "symbols": ["AAA"]}}, "needs as_of"),
    ({"evaluation": {"split": None, "walk_forward": None}}, "choose a split"),
    ({"surprise": 1}, "Extra inputs"),
])
def test_invalid_specifications_are_refused(change, message):
    with pytest.raises(ValidationError, match=message):
        runner.BacktestSpec.model_validate(spec_dict(**change))


def test_cli_writes_report_and_stores_results(workspace, monkeypatch):
    tmp, spec_file = workspace
    from sid_trading_firm.persistence import Database, make_engine
    from sid_trading_firm.persistence.backtests import BacktestRepository
    from sid_trading_firm.persistence.migrate import upgrade

    url = f"sqlite:///{(tmp / 'sid.db').as_posix()}"
    upgrade(url)
    monkeypatch.setenv("SID_DATABASE__URL", url)
    out = tmp / "out"
    assert runner.main([str(spec_file), "--out", str(out), "--database"]) == 0
    assert (out / "report.md").is_file() and (out / "results.json").is_file()
    engine = make_engine(url)
    from sqlalchemy import text
    with engine.connect() as c:
        (run_id, kind, status) = c.execute(text("SELECT run_id, kind, status FROM research_runs")).one()
    assert (kind, status) == ("backtest", "completed")
    import uuid
    rows = BacktestRepository(Database(engine)).results_for_run(str(uuid.UUID(str(run_id))))
    result = json.loads((out / "results.json").read_text(encoding="utf-8"))
    windows = [w for w in result["walk_forward"]["windows"] if w["test_report"]]
    segments = sorted(r.segment for r in rows)
    assert segments == sorted(["test", "train", "validation", "walk_forward_oos"]
                              + ["walk_forward_window"] * len(windows))
    oos = next(r for r in rows if r.segment == "walk_forward_oos")
    assert str(oos.period_start) == result["walk_forward"]["oos_start"]
    with engine.connect() as c:
        versions = c.execute(text("SELECT params_hash, status FROM strategy_versions")).all()
    chosen = {w["chosen_params_hash"] for w in windows} | {result["strategy"]["params_hash"]}
    assert {h for h, _ in versions} == chosen and {st for _, st in versions} == {"PROPOSED"}
    engine.dispose()


def test_a_storage_failure_marks_the_run_failed(workspace, monkeypatch):
    tmp, spec_file = workspace
    from sqlalchemy import text

    from sid_trading_firm.persistence import make_engine
    from sid_trading_firm.persistence.backtests import BacktestRepository
    from sid_trading_firm.persistence.migrate import upgrade

    url = f"sqlite:///{(tmp / 'sid.db').as_posix()}"
    upgrade(url)
    monkeypatch.setenv("SID_DATABASE__URL", url)

    def broken(self, **kwargs):
        raise RuntimeError("disk full")

    monkeypatch.setattr(BacktestRepository, "record", broken)
    with pytest.raises(RuntimeError, match="disk full"):
        runner.main([str(spec_file), "--out", str(tmp / "out"), "--database"])
    engine = make_engine(url)
    with engine.connect() as c:
        status, error = c.execute(text("SELECT status, error FROM research_runs")).one()
    engine.dispose()
    assert status == "failed" and "disk full" in error


def test_the_example_specification_in_the_repository_is_valid():
    from pathlib import Path

    example = Path(__file__).resolve().parents[1] / "docs" / "sid_trading_firm" / "examples" / "backtest_momentum.yaml"
    spec = runner.load_spec(example)
    assert spec.data.source == "yahoo" and spec.benchmark == "SPY"
    runner.engine_config(spec.engine)                           # assumptions pass engine validation
    from sid_trading_firm.strategies import create

    create(spec.strategy.id, spec.strategy.params)
    for params in spec.strategy.grid:
        create(spec.strategy.id, params)
