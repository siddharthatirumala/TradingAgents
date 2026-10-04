"""The baseline harness, run offline against upstream's real graph with scripted models."""

import copy
import json
from datetime import date

import pytest

import tradingagents.dataflows.config as dataflows_config
from sid_trading_firm.measurement import baseline
from tests.test_graph_end_to_end import TRADE_DATE, _Client, offline  # noqa: F401
from tests_sid.fakes import settings
from tests_sid.test_upstream_metering import MeteredScriptedModel

pytestmark = pytest.mark.unit


@pytest.fixture(autouse=True)
def _restore_upstream_config():
    saved = copy.deepcopy(dataflows_config._config)
    yield
    dataflows_config._config = saved


@pytest.fixture
def scripted(monkeypatch):
    """Upstream builds its models from our config; give it scripted ones carrying our callbacks."""
    from tradingagents.graph import trading_graph

    models = []

    def fake_client(config, tier, **kwargs):
        # Free text: the scripted structured path answers without calling the model,
        # which would leave those calls unmetered.
        model = MeteredScriptedModel(structured=False, callbacks=kwargs.get("callbacks"))
        models.append((tier, config[f"{tier}_think_llm"], model))
        return _Client(model)

    monkeypatch.setattr(trading_graph, "create_tier_client", fake_client)
    return models


@pytest.mark.usefixtures("offline")
def test_a_completed_baseline_writes_a_full_report(tmp_path, scripted):
    result = baseline.run_baseline("nvda", TRADE_DATE, settings=settings(),
                                   out_root=tmp_path / "out", ledger_path=tmp_path / "ledger.jsonl")

    assert result.status == "completed" and result.signal == "Overweight"
    assert {(tier, model) for tier, model, _ in scripted} == {("quick", "claude-sonnet-5-5"),
                                                               ("deep", "claude-sonnet-5-5")}
    summary = json.loads((result.out_dir / "summary.json").read_text())
    assert summary["ticker"] == "NVDA" and summary["status"] == "completed"
    assert summary["calls"] == 15
    assert summary["calls"] == len((result.out_dir / "llm_calls.jsonl").read_text().splitlines())
    assert "unattributed" not in summary["by_agent"]
    report = (result.out_dir / "report.md").read_text()
    for heading in ("Cost by agent", "Cost by stage", "Longest calls", "Largest prompts",
                    "Structured-output fallbacks", "Budget stops"):
        assert heading in report
    # The shared ledger keeps the records for the daily budget.
    assert len((tmp_path / "ledger.jsonl").read_text().splitlines()) == summary["calls"]


@pytest.mark.usefixtures("offline")
def test_a_baseline_stopped_by_its_budget_is_still_reported(tmp_path, scripted):
    s = settings(max_ai_cost_per_run_usd="0.03")
    result = baseline.run_baseline("NVDA", TRADE_DATE, settings=s, out_root=tmp_path / "out",
                                   ledger_path=tmp_path / "ledger.jsonl")

    assert result.status == "budget_stopped"
    assert [stop.reason for stop in result.stops] == ["run_cost"]
    summary = json.loads((result.out_dir / "summary.json").read_text())
    assert summary["budget_stops"][0]["limit"] == "max_ai_cost_per_run_usd"
    assert "run_cost" in (result.out_dir / "report.md").read_text()


@pytest.mark.usefixtures("offline")
def test_structured_output_fallbacks_are_counted(tmp_path, monkeypatch):
    """A structured call that fails is retried by upstream as free text; the report counts it."""
    from tradingagents.graph import trading_graph

    def fake_client(config, tier, **kwargs):
        # structured=False: binding fails, so upstream uses free text from the start (no
        # fallback). Force a failure inside the structured call instead.
        model = MeteredScriptedModel(structured=True, callbacks=kwargs.get("callbacks"))
        object.__setattr__(model, "with_structured_output", lambda schema, **k: _Broken())
        return _Client(model)

    class _Broken:
        def invoke(self, prompt):
            raise ValueError("tool not called")

    monkeypatch.setattr(trading_graph, "create_tier_client", fake_client)
    result = baseline.run_baseline("NVDA", TRADE_DATE, settings=settings(), out_root=tmp_path / "out",
                                   ledger_path=tmp_path / "ledger.jsonl")

    assert result.status == "completed"
    assert result.fallbacks == {"research_manager": 1, "trader": 1, "portfolio_manager": 1,
                                "sentiment_analyst": 1}
    assert "| Research Manager | 1 |" in (result.out_dir / "report.md").read_text()


@pytest.mark.parametrize("ticker", ["BTC-USD", "0700.HK", "EURUSD=X", "ES=F", "nvda.l", "BRK.B", "TOOLONG", ""])
def test_only_us_equities_are_measured(ticker):
    with pytest.raises(baseline.BaselineError, match="US equities"):
        baseline.check_us_equity(ticker)


@pytest.mark.parametrize("ticker", ["NVDA", "brk-b", "BF-B", "F"])
def test_us_equity_symbols_are_accepted(ticker):
    assert baseline.check_us_equity(ticker) == ticker.upper()


def test_missing_api_keys_stop_before_any_call(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    with pytest.raises(baseline.BaselineError, match="ANTHROPIC_API_KEY") as err:
        baseline.check_api_keys(settings())
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-real-looking-value")
    assert baseline.check_api_keys(settings()) == ["ANTHROPIC_API_KEY"]
    assert "sk-ant" not in str(err.value)


def test_main_exits_cleanly_without_keys(monkeypatch, capsys):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    assert baseline.main(["--ticker", "NVDA", "--date", TRADE_DATE]) == 2
    assert "missing API key" in capsys.readouterr().err


def test_default_date_is_the_previous_weekday():
    assert baseline.previous_weekday(date(2026, 10, 5)) == "2026-10-02"   # Monday -> Friday
    assert baseline.previous_weekday(date(2026, 10, 7)) == "2026-10-06"


@pytest.mark.usefixtures("offline")
def test_a_report_can_be_rebuilt_from_saved_records_without_calling_a_model(tmp_path, scripted):
    s = settings()
    result = baseline.run_baseline("NVDA", TRADE_DATE, settings=s, out_root=tmp_path / "out",
                                   ledger_path=tmp_path / "ledger.jsonl")
    original = json.loads((result.out_dir / "summary.json").read_text())
    (result.out_dir / "report.md").unlink()
    calls_before = sum(len(model.calls) for _, _, model in scripted)

    baseline.rerender_report(result.out_dir, s)

    assert sum(len(model.calls) for _, _, model in scripted) == calls_before
    rebuilt = json.loads((result.out_dir / "summary.json").read_text())
    for key in ("run_id", "status", "calls", "cost_usd", "wall_seconds", "budget_guard"):
        assert rebuilt[key] == original[key], key
    assert "UPSTREAM ALL-SONNET BASELINE" in (result.out_dir / "report.md").read_text()
