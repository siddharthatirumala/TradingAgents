"""Backtest price data: validation, point-in-time views, fingerprints and sources."""

import ast
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from sid_trading_firm import backtest
from sid_trading_firm.backtest.data import (
    DataError,
    PricePanel,
    load_csv_directory,
    load_upstream_yahoo,
)

pytestmark = pytest.mark.unit


def bars(closes, start="2026-01-02", volume=1_000_000):
    closes = np.asarray(closes, dtype=float)
    return pd.DataFrame({"Date": pd.bdate_range(start, periods=len(closes)), "Open": closes,
                         "High": closes * 1.01, "Low": closes * 0.99, "Close": closes, "Volume": volume})


def panel(**symbols):
    return PricePanel.from_frames({k: bars(v) for k, v in symbols.items()})


# ------------------------------------------------------------------ validation

def test_valid_frames_are_normalised():
    p = panel(nvda=[100, 101, 102])
    frame = p.frames["NVDA"]
    assert list(frame.columns) == ["open", "high", "low", "close", "volume"]
    assert frame.index.name == "date" and frame.index.is_monotonic_increasing
    assert p.symbols == ["NVDA"]


def test_unsorted_dates_are_sorted_but_duplicates_are_refused():
    df = bars([100, 101, 102]).iloc[[2, 0, 1]]
    assert PricePanel.from_frames({"A": df}).frames["A"]["close"].tolist() == [100, 101, 102]
    dup = pd.concat([bars([100, 101]), bars([100], start="2026-01-02")])
    with pytest.raises(DataError, match="duplicate dates"):
        PricePanel.from_frames({"A": dup})


@pytest.mark.parametrize("mutate, message", [
    (lambda d: d.drop(columns=["Volume"]), "missing columns"),
    (lambda d: d.assign(Close=[100.0, -1.0, 102.0]), "non-positive"),
    (lambda d: d.assign(Close=[100.0, 0.0, 102.0]), "non-positive"),
    (lambda d: d.assign(Volume=[1, -5, 1]), "negative volume"),
    (lambda d: d.assign(High=[90.0, 90.0, 90.0]), "high below low"),
    (lambda d: d.assign(Close=[100.0, 500.0, 102.0], High=[101.0, 102.0, 103.0]), "outside the high-low"),
    (lambda d: d.assign(Close=[100.0, np.inf, 102.0], High=np.inf), "infinite"),
    (lambda d: d.assign(Close=["a", "b", "c"]), "non-numeric"),
    (lambda d: d.assign(Close=[100.0, np.nan, 102.0]), "missing values"),
    (lambda d: d.iloc[0:0], "no complete bars"),
])
def test_invalid_data_is_refused(mutate, message):
    with pytest.raises(DataError, match=message):
        PricePanel.from_frames({"A": mutate(bars([100, 101, 102]))})


def test_incomplete_bars_can_be_dropped_explicitly_and_are_counted():
    df = bars([100, 101, 102]).assign(Close=[100.0, np.nan, 102.0])
    p = PricePanel.from_frames({"A": df}, on_missing="drop")
    assert len(p.frames["A"]) == 2 and p.dropped_bars["A"] == 1


def test_empty_panel_and_bad_policy_are_refused():
    with pytest.raises(DataError):
        PricePanel.from_frames({})
    with pytest.raises(DataError, match="policy"):
        PricePanel.from_frames({"A": bars([1, 2])}, on_missing="fill")


def test_timezone_aware_dates_become_plain_dates():
    df = bars([100, 101]).assign(Date=pd.date_range("2026-01-02 16:00", periods=2, freq="D", tz="America/New_York"))
    assert PricePanel.from_frames({"A": df}).frames["A"].index[0] == pd.Timestamp("2026-01-02")


# ------------------------------------------------------- point-in-time views

def test_a_view_never_returns_a_later_bar():
    p = panel(A=list(range(100, 120)))
    dates = p.calendar()
    for as_of in dates:
        view = p.view(as_of)
        assert view.history("A").index.max() <= as_of
        assert view.bars("A").index.max() <= as_of
        assert view.last_bar("A").name <= as_of
        assert view.max_date_served <= as_of


def test_a_view_on_a_non_trading_day_sees_the_previous_bar():
    p = panel(A=[100, 101, 102, 103])          # Fri 2026-01-02 .. Wed 2026-01-07
    view = p.view("2026-01-04")                # Sunday
    assert view.last_bar("A")["close"] == 100.0
    assert not view.has_bar_today("A")


def test_history_lookback_and_unknown_inputs():
    view = panel(A=[100, 101, 102, 103]).view("2026-01-07")
    assert view.history("A", lookback=2).tolist() == [102.0, 103.0]
    with pytest.raises(KeyError):
        view.history("ZZZ")
    with pytest.raises(KeyError):
        view.history("A", field="adj_close")
    with pytest.raises(ValueError):
        view.history("A", lookback=0)


def test_history_is_a_copy_so_strategies_cannot_alter_the_data():
    p = panel(A=[100, 101, 102])
    view = p.view("2026-01-06")
    series = view.history("A")
    series.iloc[0] = -1
    assert p.frames["A"]["close"].iloc[0] == 100.0


def test_a_view_before_the_first_bar_sees_nothing():
    view = panel(A=[100, 101]).view("2025-12-31")
    assert view.history("A").empty and view.last_bar("A") is None and view.max_date_served is None


def test_a_truncated_panel_holds_no_later_data():
    panel = PricePanel.from_frames({"A": bars(range(100, 110)), "B": bars(range(50, 55), start="2026-01-09")})
    cut = panel.calendar()[3]
    short = panel.truncated(cut)
    assert all(f.index.max() <= cut for f in short.frames.values())
    assert short.symbols == ["A"]                 # B has no bar by the cut, so it does not exist
    with pytest.raises(DataError, match="no data"):
        panel.truncated("2000-01-01")


def test_calendar_is_the_union_of_trading_dates():
    p = PricePanel.from_frames({"A": bars([1, 2, 3]), "B": bars([1, 2], start="2026-01-06")})
    assert list(p.calendar().strftime("%Y-%m-%d")) == ["2026-01-02", "2026-01-05", "2026-01-06", "2026-01-07"]


def test_bar_on_is_exact_date_only():
    p = panel(A=[100, 101])
    assert p.bar_on("A", "2026-01-05")["close"] == 101.0
    assert p.bar_on("A", "2026-01-04") is None
    assert p.bar_on("ZZZ", "2026-01-05") is None


# ------------------------------------------------------------- fingerprints

def test_fingerprint_is_stable_and_sensitive_to_any_change():
    a, b = panel(A=[100, 101, 102]), panel(A=[100, 101, 102])
    assert a.fingerprint() == b.fingerprint()
    assert a.fingerprint() != panel(A=[100, 101, 102.0001]).fingerprint()
    assert a.fingerprint() != panel(B=[100, 101, 102]).fingerprint()


# ------------------------------------------------------------------ sources

def test_csv_directory_round_trip(tmp_path):
    bars([100, 101, 102]).to_csv(tmp_path / "AAPL.csv", index=False)
    bars([50, 51, 52]).to_csv(tmp_path / "MSFT.csv", index=False)
    p = load_csv_directory(tmp_path)
    assert p.symbols == ["AAPL", "MSFT"] and p.source == "csv:" + tmp_path.name
    assert load_csv_directory(tmp_path, ["msft"]).symbols == ["MSFT"]
    with pytest.raises(DataError, match="no file"):
        load_csv_directory(tmp_path, ["TSLA"])


def test_upstream_yahoo_adapter_requests_unfilled_bars(monkeypatch):
    from tradingagents.dataflows.vendors.yahoo import ohlcv

    calls = []

    def fake(symbol, as_of, fill_gaps=True):
        calls.append((symbol, as_of, fill_gaps))
        return bars([100, 101, 102])

    monkeypatch.setattr(ohlcv, "load_ohlcv", fake)
    p = load_upstream_yahoo(["nvda", "aapl"], "2026-01-07")
    assert p.symbols == ["AAPL", "NVDA"] and p.source == "yahoo (adjusted)"
    assert calls == [("nvda", "2026-01-07", False), ("aapl", "2026-01-07", False)]


def test_the_backtest_package_imports_no_llm_or_upstream_agent_code():
    forbidden = {"langchain", "langchain_core", "langgraph", "langchain_anthropic", "langchain_openai",
                 "anthropic", "openai"}
    for path in Path(backtest.__file__).parent.rglob("*.py"):
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            modules = ([a.name for a in node.names] if isinstance(node, ast.Import)
                       else [node.module] if isinstance(node, ast.ImportFrom) and node.module else [])
            for module in modules:
                assert module.split(".")[0] not in forbidden, f"{path.name} imports {module}"
                assert not module.startswith("tradingagents.agents"), f"{path.name} imports {module}"
                assert not module.startswith("sid_trading_firm.llm"), f"{path.name} imports {module}"
