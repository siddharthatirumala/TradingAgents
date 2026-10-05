"""Reference strategies and the strategy registry."""

import ast
from pathlib import Path

import pandas as pd
import pytest

from sid_trading_firm import strategies
from sid_trading_firm.backtest.data import PricePanel
from sid_trading_firm.backtest.engine import BacktestConfig, run_backtest
from sid_trading_firm.strategies import StrategySpec, StrategyStatus, create, spec_for
from sid_trading_firm.strategies.reference import BuyAndHoldV1, MomentumV1

pytestmark = pytest.mark.unit


def frame(closes, start="2026-01-02"):
    dates = pd.bdate_range(start, periods=len(closes))
    return pd.DataFrame({"date": dates, "open": closes, "high": [c * 1.01 for c in closes],
                         "low": [c * 0.99 for c in closes], "close": closes, "volume": 1e6})


def panel():
    n = 12
    return PricePanel.from_frames({
        "UP": frame([100 + 10 * i for i in range(n)]),           # strongest
        "MID": frame([100 + 2 * i for i in range(n)]),
        "DOWN": frame([200 - 5 * i for i in range(n)]),          # negative
        "NEW": frame([50 + i for i in range(4)], start="2026-01-13"),   # too little history
    })


def test_momentum_ranks_by_lookback_skip_return():
    view = panel().view(pd.bdate_range("2026-01-02", periods=12)[-1])
    m = MomentumV1(lookback=5, skip=1, top_n=2)
    scores = m.scores(view)
    # UP: last six closes 160..210; from 5 bars ago (160) to 1 bar ago (200) -> 200/160 - 1
    assert scores["UP"] == pytest.approx(200 / 160 - 1)
    assert "NEW" not in scores                                     # not enough history
    assert m.target_weights(view) == {"UP": 0.5, "MID": 0.5}


def test_momentum_excludes_negative_returns_unless_allowed():
    view = panel().view(pd.bdate_range("2026-01-02", periods=12)[-1])
    assert "DOWN" not in MomentumV1(lookback=5, skip=1, top_n=3).target_weights(view)
    assert "DOWN" in MomentumV1(lookback=5, skip=1, top_n=3, require_positive=False).target_weights(view)


def test_unfilled_slots_stay_in_cash():
    view = panel().view(pd.bdate_range("2026-01-02", periods=12)[-1])
    weights = MomentumV1(lookback=5, skip=1, top_n=4).target_weights(view)
    assert sum(weights.values()) == pytest.approx(0.5)            # 2 eligible positive of 4 slots


def test_momentum_ties_break_by_symbol():
    flat = PricePanel.from_frames({"B": frame([100 + i for i in range(8)]), "A": frame([100 + i for i in range(8)])})
    view = flat.view(pd.bdate_range("2026-01-02", periods=8)[-1])
    assert list(MomentumV1(lookback=5, skip=0, top_n=1).target_weights(view)) == ["A"]


def test_momentum_parameters_are_validated():
    with pytest.raises(ValueError):
        MomentumV1(lookback=5, skip=5)
    with pytest.raises(ValueError):
        MomentumV1(top_n=0)


def test_buy_and_hold_weights_live_symbols_only():
    view = panel().view("2026-01-05")
    assert BuyAndHoldV1(("UP", "NEW")).target_weights(view) == {"UP": 0.5}
    with pytest.raises(ValueError):
        BuyAndHoldV1(())


def test_registry_creates_validates_and_hashes():
    m = create("momentum_v1", {"lookback": 60, "skip": 5, "top_n": 3, "universe": ["A", "B"]})
    assert isinstance(m, MomentumV1) and m.universe == ("A", "B")
    spec = spec_for(m)
    assert spec.identifier == "momentum_v1"
    assert spec.params["require_positive"] is True                 # defaults are part of the identity
    assert spec.params_hash == spec_for(create("momentum_v1", {"lookback": 60, "skip": 5, "top_n": 3,
                                                               "universe": ["A", "B"]})).params_hash
    assert spec.params_hash != spec_for(create("momentum_v1", {"lookback": 61, "skip": 5})).params_hash
    assert (StrategySpec("x_v1", {"u": ["A", "B"]}).params_hash
            == StrategySpec("x_v1", {"u": ("A", "B")}).params_hash)     # list or tuple: same identity
    with pytest.raises(KeyError, match="unknown strategy"):
        create("magic_v9")
    with pytest.raises(ValueError, match="unknown parameters"):
        create("momentum_v1", {"leverage": 3})


def test_lifecycle_states_match_governance():
    assert [s.value for s in StrategyStatus] == ["PROPOSED", "BACKTESTED", "VALIDATED", "PAPER_APPROVED",
                                                 "PAPER_ACTIVE", "RETIRED"]


def test_momentum_runs_end_to_end_in_the_backtester():
    result = run_backtest(panel(), MomentumV1(lookback=5, skip=1, top_n=2),
                          BacktestConfig(initial_cash=10_000.0, max_weight=0.5, rebalance="daily"))
    assert result.strategy == "momentum_v1"
    assert {f.symbol for f in result.fills} <= {"UP", "MID"}
    assert all(c >= 0 for c in result.cash)


def test_strategies_import_no_llm_code():
    forbidden = {"langchain", "langchain_core", "langgraph", "langchain_anthropic", "langchain_openai",
                 "anthropic", "openai", "tradingagents"}
    for path in Path(strategies.__file__).parent.rglob("*.py"):
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            modules = ([a.name for a in node.names] if isinstance(node, ast.Import)
                       else [node.module] if isinstance(node, ast.ImportFrom) and node.module else [])
            for module in modules:
                assert module.split(".")[0] not in forbidden, f"{path.name} imports {module}"
                assert not module.startswith("sid_trading_firm.llm"), f"{path.name} imports {module}"
