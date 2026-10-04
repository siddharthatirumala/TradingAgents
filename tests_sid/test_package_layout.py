"""The boundary between upstream TradingAgents and SID Trading Firm."""

import ast
from pathlib import Path

import pytest

import tradingagents
from sid_trading_firm import upstream

ROOT = Path(__file__).resolve().parents[1]


def _imported_modules(path: Path) -> set[str]:
    names = set()
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(node, ast.Import):
            names |= {alias.name.split(".")[0] for alias in node.names}
        elif isinstance(node, ast.ImportFrom) and node.module and not node.level:
            names.add(node.module.split(".")[0])
    return names


@pytest.mark.unit
def test_installed_upstream_is_the_pinned_release():
    """An upstream sync moves the pin in the same pull request, after both suites pass."""
    assert tradingagents.__version__ == upstream.PINNED_UPSTREAM_VERSION, (
        f"tradingagents {tradingagents.__version__} is installed but SID Trading Firm is pinned to "
        f"{upstream.PINNED_UPSTREAM_VERSION}; review the upstream changes, run both suites, then "
        "update sid_trading_firm/upstream.py"
    )


@pytest.mark.unit
def test_upstream_code_never_imports_sid_trading_firm():
    """Upstream must stay mergeable as-is: the dependency only points one way."""
    offenders = sorted(
        str(path.relative_to(ROOT))
        for package in ("tradingagents", "cli")
        for path in (ROOT / package).rglob("*.py")
        if "sid_trading_firm" in _imported_modules(path)
    )
    assert offenders == []
