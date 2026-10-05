"""Backtest artifacts: equity curves exported and stored, benchmark-relative out-of-sample
metrics, the database run_id in the files, and files marked when storage fails."""

import csv
import json
import uuid

import pandas as pd
import pytest
import yaml
from sqlalchemy import text

from sid_trading_firm.backtest import run as runner
from sid_trading_firm.backtest.data import PricePanel
from sid_trading_firm.backtest.oos import (
    relative_metrics,
    stitched_benchmark,
    window_equity,
    window_slices,
)
from sid_trading_firm.backtest.splits import Period
from sid_trading_firm.persistence import Database, make_engine
from sid_trading_firm.persistence.backtests import BacktestRepository
from sid_trading_firm.persistence.migrate import upgrade
from tests_sid.test_backtest_run import spec_dict, write_synthetic_csvs

pytestmark = pytest.mark.unit


@pytest.fixture
def workspace(tmp_path):
    (tmp_path / "data").mkdir()
    write_synthetic_csvs(tmp_path / "data")
    spec_file = tmp_path / "spec.yaml"
    spec_file.write_text(yaml.safe_dump(spec_dict()), encoding="utf-8")
    return tmp_path, spec_file


@pytest.fixture
def database(workspace, monkeypatch):
    tmp, _ = workspace
    url = f"sqlite:///{(tmp / 'sid.db').as_posix()}"
    upgrade(url)
    monkeypatch.setenv("SID_DATABASE__URL", url)
    engine = make_engine(url)
    yield engine
    engine.dispose()


def read_csv(path):
    with open(path, encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


# ------------------------------------------------------------------ stitched benchmark, by hand

def _panel():
    dates = pd.bdate_range("2026-01-05", periods=8)
    closes = [100, 110, 121, 100, 50, 55, 60, 66]
    frame = pd.DataFrame({"date": dates, "open": closes, "high": closes, "low": closes, "close": closes,
                          "volume": 1e6})
    return PricePanel.from_frames({"SPY": frame}), dates


def test_the_benchmark_is_stitched_over_the_same_windows_by_hand():
    panel, d = _panel()
    periods = [Period(d[0], d[2]), Period(d[4], d[6])]
    # Strategy: +10% then +10% in window 1; flat then +20% in window 2 (each window starts from cash).
    oos = pd.Series([1000.0, 1100.0, 1210.0, 1210.0, 1210.0, 1452.0], index=[d[0], d[1], d[2], d[4], d[5], d[6]])
    bench = stitched_benchmark(panel, "SPY", oos, periods)
    # Window 1: 100 -> 110 -> 121 (x1.21). Window 2 starts at 1210: 50 -> 55 -> 60 (x1.2). Day 3 (100) is not tested.
    assert list(bench.round(6)) == [1000.0, 1100.0, 1210.0, 1210.0, 1331.0, 1452.0]
    metrics = relative_metrics(oos, bench)
    assert metrics["benchmark_return"].value == pytest.approx(0.452)
    assert metrics["excess_return"].value == pytest.approx(0.0)
    assert metrics["correlation"].ok and metrics["beta"].ok


def test_window_equity_is_recovered_from_the_stitched_curve():
    _, d = _panel()
    oos = pd.Series([1000.0, 1100.0, 1210.0, 1210.0, 1210.0, 1452.0], index=[d[0], d[1], d[2], d[4], d[5], d[6]])
    w1, w2 = window_slices(oos, [Period(d[0], d[2]), Period(d[4], d[6])])
    assert list(window_equity(w2, 1000.0)) == pytest.approx([1000.0, 1000.0, 1200.0])
    assert list(window_equity(w1, 1000.0)) == pytest.approx([1000.0, 1100.0, 1210.0])


def test_an_unpriced_benchmark_makes_relative_metrics_insufficient_not_zero():
    panel, d = _panel()
    oos = pd.Series([1000.0, 1010.0], index=[d[0] - pd.Timedelta(days=7), d[0]])
    assert stitched_benchmark(panel, "SPY", oos, [Period(oos.index[0], oos.index[1])]) is None
    metrics = relative_metrics(oos, None)
    assert {m.status.value for m in metrics.values()} == {"insufficient_data"}


# ------------------------------------------------------------------ end to end

def test_equity_curves_are_exported_and_stored_and_files_carry_the_run_id(workspace, database):
    tmp, spec_file = workspace
    out = tmp / "out"
    assert runner.main([str(spec_file), "--out", str(out), "--database"]) == 0
    result = json.loads((out / "results.json").read_text(encoding="utf-8"))

    with database.connect() as c:
        (run_id,) = c.execute(text("SELECT run_id FROM research_runs")).one()
    run_id = str(uuid.UUID(str(run_id)))
    assert result["persistence"] == {"status": "stored", "run_id": run_id}
    assert f"research run `{run_id}`" in (out / "report.md").read_text(encoding="utf-8")

    for segment, report in result["segments"].items():
        rows = read_csv(out / f"equity_{segment}.csv")
        assert len(rows) == report["trading_days"] and rows[0]["date"] == report["start"]
        assert float(rows[0]["equity"]) == pytest.approx(100_000)
    oos_rows = read_csv(out / "equity_walk_forward_oos.csv")
    assert len(oos_rows) == result["walk_forward"]["oos_days"]
    assert all(r["strategy"] and r["benchmark"] for r in oos_rows)

    stored = BacktestRepository(Database(database)).results_for_run(run_id)
    by_segment = {}
    for row in stored:
        by_segment.setdefault(row.segment, []).append(row)
        assert row.equity and len(row.equity["dates"]) == len(row.equity["values"])
    for segment, report in result["segments"].items():
        (row,) = by_segment[segment]
        assert len(row.equity["values"]) == report["trading_days"]
    windows = [w for w in result["walk_forward"]["windows"] if w["test_report"]]
    for row, w in zip(by_segment["walk_forward_window"], windows, strict=True):
        assert row.equity["values"][0] == pytest.approx(100_000)          # each window starts from cash
        total = w["test_report"]["metrics"]["total_return"]["value"]
        assert row.equity["values"][-1] / row.equity["values"][0] - 1 == pytest.approx(total)
    (oos,) = by_segment["walk_forward_oos"]
    assert len(oos.equity["values"]) == result["walk_forward"]["oos_days"]
    assert not list(out.glob("*.tmp"))


def test_out_of_sample_metrics_are_benchmark_relative(workspace):
    tmp, spec_file = workspace
    result = runner.run(runner.load_spec(spec_file), base=tmp)
    m = result["walk_forward"]["oos_metrics"]
    for key in ("benchmark_return", "excess_return", "beta", "correlation"):
        assert m[key]["status"] == "ok", key
    assert m["excess_return"]["value"] == pytest.approx(m["total_return"]["value"] - m["benchmark_return"]["value"])
    oos, bench = result["equity"]["walk_forward_oos"], result["equity"]["walk_forward_benchmark"]
    assert oos["dates"] == bench["dates"] and oos["values"][0] == bench["values"][0]
    text_ = runner.render_report(result)
    assert "excess_return" in text_ and "held over the same test windows" in text_


def test_without_database_the_files_say_they_are_not_stored(workspace):
    tmp, spec_file = workspace
    out = tmp / "out"
    assert runner.main([str(spec_file), "--out", str(out)]) == 0
    result = json.loads((out / "results.json").read_text(encoding="utf-8"))
    assert result["persistence"] == {"status": "not_requested", "run_id": None}
    assert "Not stored in the database" in (out / "report.md").read_text(encoding="utf-8")


def test_a_storage_failure_writes_files_marked_failed_and_masks_the_error(workspace, database, monkeypatch):
    tmp, spec_file = workspace
    secret = "synth" + "-store-pw-23"

    def broken(self, **kwargs):
        raise RuntimeError(f"connection lost: password='{secret}'")

    monkeypatch.setattr(BacktestRepository, "record", broken)
    out = tmp / "out"
    with pytest.raises(runner.StorageError, match="connection lost"):
        runner.main([str(spec_file), "--out", str(out), "--database"])

    with database.connect() as c:
        run_id, status = c.execute(text("SELECT run_id, status FROM research_runs")).one()
    assert status == "failed"
    result = json.loads((out / "results.json").read_text(encoding="utf-8"))
    assert result["persistence"]["status"] == "failed"
    assert result["persistence"]["run_id"] == str(uuid.UUID(str(run_id)))
    report = (out / "report.md").read_text(encoding="utf-8")
    assert report.splitlines()[2].startswith("> **STORAGE FAILED.")
    assert secret not in report and secret not in (out / "results.json").read_text(encoding="utf-8")
    assert not list(out.glob("*.tmp"))


def test_invalid_equity_is_refused_by_the_repository(database):
    repo = BacktestRepository(Database(database))
    for bad in ({"dates": ["2026-01-02"], "values": []}, {"dates": [], "values": []}, {"values": [1.0]}):
        with pytest.raises(ValueError, match="equity must hold"):
            repo.record(run_id=str(uuid.uuid4()), version_id=uuid.uuid4(), segment="full",
                        report={"start": "2026-01-02", "end": "2026-01-05", "data_fingerprint": "x", "metrics": {}},
                        config={}, data_source="x", equity=bad)
