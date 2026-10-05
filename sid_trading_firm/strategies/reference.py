"""Reference strategies: a cross-sectional momentum rule and a buy-and-hold benchmark.

These exist to exercise the backtester and to give later research a baseline. Their
parameters are explicit and have no claimed edge.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from sid_trading_firm.backtest.data import PanelView


@dataclass(frozen=True)
class MomentumV1:
    """Hold the ``top_n`` symbols with the highest trailing return, equally weighted.

    Trailing return runs from ``lookback`` bars ago to ``skip`` bars ago (the classic
    12-1 month momentum skips the most recent month). Only symbols with a bar on the
    decision date and at least ``lookback + 1`` bars of history are eligible; with
    ``require_positive`` only positive trailing returns qualify. Each holding gets
    ``1 / top_n`` (unfilled slots stay in cash). Ties break by symbol, so results are
    deterministic.
    """

    lookback: int = 252
    skip: int = 21
    top_n: int = 5
    require_positive: bool = True
    universe: tuple[str, ...] | None = None
    name: str = "momentum"
    version: str = "v1"

    def __post_init__(self) -> None:
        if not (self.lookback > self.skip >= 0):
            raise ValueError("momentum needs lookback > skip >= 0")
        if self.top_n < 1:
            raise ValueError("top_n must be at least 1")

    def scores(self, view: PanelView) -> dict[str, float]:
        out = {}
        for symbol in self.universe or tuple(view.symbols):
            if not view.has_bar_today(symbol):
                continue
            closes = view.history(symbol, "close", lookback=self.lookback + 1)
            if len(closes) < self.lookback + 1:
                continue
            start, end = float(closes.iloc[0]), float(closes.iloc[-1 - self.skip])
            out[symbol] = end / start - 1
        return out

    def target_weights(self, view: PanelView) -> Mapping[str, float]:
        ranked = sorted(self.scores(view).items(), key=lambda kv: (-kv[1], kv[0]))
        if self.require_positive:
            ranked = [(s, v) for s, v in ranked if v > 0]
        return {symbol: 1.0 / self.top_n for symbol, _ in ranked[: self.top_n]}


@dataclass(frozen=True)
class BuyAndHoldV1:
    """Hold ``symbols`` in equal weight (a benchmark, rebalanced on the backtest schedule)."""

    symbols: Sequence[str] = ("SPY",)
    name: str = "buy_and_hold"
    version: str = "v1"

    def __post_init__(self) -> None:
        if not self.symbols:
            raise ValueError("buy and hold needs at least one symbol")

    def target_weights(self, view: PanelView) -> Mapping[str, float]:
        live = [s for s in self.symbols if view.last_bar(s) is not None]
        return {s: 1.0 / len(self.symbols) for s in live}
