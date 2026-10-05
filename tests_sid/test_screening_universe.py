"""Universe files: US-listed symbols only, provenance required, ETFs never candidates."""

import ast
from datetime import date
from pathlib import Path

import pytest
import yaml
from pydantic import ValidationError

from sid_trading_firm import screening
from sid_trading_firm.screening.universe import Universe, load_universe

pytestmark = pytest.mark.unit


def spec(**overrides):
    base = {"name": "test", "version": "v1", "source": "hand-written test list", "as_of": "2026-10-01",
            "survivorship_note": "today's symbols; delisted names are missing",
            "members": [{"symbol": "nvda", "asset_type": "common_stock", "sector": "Technology"},
                        {"symbol": "BRK-B", "asset_type": "common_stock"},
                        {"symbol": "SPY", "asset_type": "etf"}]}
    base.update(overrides)
    return base


def test_a_valid_universe_normalises_symbols_and_separates_etfs():
    u = Universe.model_validate(spec())
    assert u.identifier == "test_v1"
    assert u.as_of == date(2026, 10, 1)
    assert u.candidates == ["BRK-B", "NVDA"]
    assert u.etfs == ["SPY"]


@pytest.mark.parametrize("symbol", ["NVDA.L", "TOOLONG", "BRK.B", "7203", "", "AB-CD"])
def test_non_us_or_malformed_symbols_are_refused(symbol):
    with pytest.raises(ValidationError, match="US-listed"):
        Universe.model_validate(spec(members=[{"symbol": symbol, "asset_type": "common_stock"}]))


@pytest.mark.parametrize("change, message", [
    ({"source": ""}, "at least 1"),
    ({"survivorship_note": ""}, "at least 1"),
    ({"members": []}, "at least 1"),
    ({"members": [{"symbol": "AAPL", "asset_type": "common_stock"},
                  {"symbol": "aapl", "asset_type": "common_stock"}]}, "duplicate"),
    ({"members": [{"symbol": "BTC", "asset_type": "crypto"}]}, "common_stock"),
    ({"region": "EU"}, "Extra inputs"),
])
def test_incomplete_or_out_of_scope_universes_are_refused(change, message):
    with pytest.raises(ValidationError, match=message):
        Universe.model_validate(spec(**change))


def test_fingerprint_is_stable_and_changes_with_membership():
    a, b = Universe.model_validate(spec()), Universe.model_validate(spec())
    assert a.fingerprint() == b.fingerprint()
    c = Universe.model_validate(spec(members=[{"symbol": "NVDA", "asset_type": "common_stock"}]))
    assert c.fingerprint() != a.fingerprint()


def test_load_universe_from_yaml(tmp_path):
    path = tmp_path / "u.yaml"
    path.write_text(yaml.safe_dump(spec()), encoding="utf-8")
    assert load_universe(path).candidates == ["BRK-B", "NVDA"]


def test_the_seed_universe_in_the_repository_is_valid():
    root = Path(__file__).resolve().parents[1] / "docs" / "sid_trading_firm" / "universes"
    files = sorted(root.glob("*.yaml"))
    assert files, "no seed universe found"
    for path in files:
        u = load_universe(path)
        assert u.candidates and "survivorship" in u.survivorship_note.lower()


def test_the_screening_package_imports_no_llm_code():
    forbidden = {"langchain", "langchain_core", "langgraph", "langchain_anthropic", "langchain_openai",
                 "anthropic", "openai"}
    for path in Path(screening.__file__).parent.rglob("*.py"):
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            modules = ([a.name for a in node.names] if isinstance(node, ast.Import)
                       else [node.module] if isinstance(node, ast.ImportFrom) and node.module else [])
            for module in modules:
                assert module.split(".")[0] not in forbidden, f"{path.name} imports {module}"
                assert not module.startswith("tradingagents.agents"), f"{path.name} imports {module}"
                assert not module.startswith("sid_trading_firm.llm"), f"{path.name} imports {module}"
