"""Cross-sectional factor scores and the bounded candidate list.

Factors are computed point-in-time for the symbols that passed the filters, converted
to percentile ranks within that set (0 worst .. 1 best), and combined with configured
weights. A symbol whose required factor cannot be computed is excluded with the
reason, never scored as zero. Ties break by symbol, so the ranking is deterministic.

Weights must be finite and positive and their total finite; every rank and composite
must be a finite number in [0, 1]. Anything else raises :class:`ScoringError` rather
than producing a ranking from undefined numbers.
"""

from __future__ import annotations

import inspect
import math
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field

import pandas as pd
from pydantic import BaseModel, ConfigDict, Field, field_validator

from sid_trading_firm.backtest.data import PanelView
from sid_trading_firm.quant import arithmetic_returns, realised_volatility


def momentum(view: PanelView, symbol: str, lookback: int = 252, skip: int = 21) -> float | None:
    """Return from ``lookback`` bars ago to ``skip`` bars ago (the most recent month is skipped)."""
    if not 0 <= skip < lookback:
        raise ValueError("momentum needs 0 <= skip < lookback")
    closes = view.history(symbol, "close", lookback=lookback + 1)
    if len(closes) < lookback + 1:
        return None
    return float(closes.iloc[-1 - skip] / closes.iloc[0] - 1)


def low_volatility(view: PanelView, symbol: str, window: int = 60) -> float | None:
    closes = view.history(symbol, "close", lookback=window + 1)
    if len(closes) < window + 1:
        return None
    r = arithmetic_returns(closes)
    v = realised_volatility(r.values) if r.ok else None
    return -v.value if v is not None and v.ok else None        # higher is better


def trend(view: PanelView, symbol: str, window: int = 200) -> float | None:
    closes = view.history(symbol, "close", lookback=window)
    if len(closes) < window:
        return None
    return float(closes.iloc[-1] / closes.mean() - 1)


def liquidity(view: PanelView, symbol: str, window: int = 20) -> float | None:
    bars = view.bars(symbol, lookback=window)
    if len(bars) < window:
        return None
    adv = float((bars["close"] * bars["volume"]).mean())
    return math.log(adv) if adv > 0 else None


def unusual_volume(view: PanelView, symbol: str, window: int = 20) -> float | None:
    vols = view.history(symbol, "volume", lookback=window + 1)
    if len(vols) < window + 1:
        return None
    base = float(vols.iloc[:-1].mean())
    return float(vols.iloc[-1] / base) if base > 0 else None


FACTORS: dict[str, Callable[..., float | None]] = {
    "momentum": momentum,
    "low_volatility": low_volatility,
    "trend": trend,
    "liquidity": liquidity,
    "unusual_volume": unusual_volume,
}


class ScoringError(ValueError):
    """Scores that cannot be trusted (non-finite or out-of-range weights, ranks or composites)."""


class FactorSpec(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    weight: float = Field(gt=0, allow_inf_nan=False)
    params: dict[str, int] = Field(default_factory=dict)


class ScoringConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    factors: dict[str, FactorSpec]

    @field_validator("factors")
    @classmethod
    def _known(cls, value: dict) -> dict:
        if not value:
            raise ValueError("at least one factor is required")
        unknown = set(value) - set(FACTORS)
        if unknown:
            raise ValueError(f"unknown factors {sorted(unknown)}; known: {sorted(FACTORS)}")
        for name, spec in value.items():
            accepted = set(inspect.signature(FACTORS[name]).parameters) - {"view", "symbol"}
            extra = set(spec.params) - accepted
            if extra:
                raise ValueError(f"factor '{name}' has no parameter(s) {sorted(extra)}; accepted: {sorted(accepted)}")
            if any(v < 1 for k, v in spec.params.items() if k != "skip"):
                raise ValueError(f"factor '{name}' windows must be positive")
            if name == "momentum":
                lookback, skip = spec.params.get("lookback", 252), spec.params.get("skip", 21)
                if not 0 <= skip < lookback:
                    raise ValueError("momentum needs 0 <= skip < lookback")
        if not math.isfinite(sum(spec.weight for spec in value.values())):
            raise ValueError("the total factor weight must be finite")
        return value


@dataclass
class ScoredSymbol:
    symbol: str
    composite: float
    ranks: dict[str, float]
    raw: dict[str, float]


@dataclass
class ScoringResult:
    scored: list[ScoredSymbol]
    excluded: dict[str, str] = field(default_factory=dict)


def percentile_ranks(values: Mapping[str, float]) -> dict[str, float]:
    """0 for the lowest value, 1 for the highest; equal values share their average rank."""
    if len(values) == 1:
        return {next(iter(values)): 1.0}
    series = pd.Series(values, dtype=float)
    return ((series.rank(method="average") - 1) / (len(series) - 1)).to_dict()


def _weighted_mean(weights: Mapping[str, float], ranks: Mapping[str, float], total: float) -> float:
    return sum(weights[n] * ranks[n] for n in weights) / total


def score(view: PanelView, symbols: Sequence[str], cfg: ScoringConfig) -> ScoringResult:
    raw: dict[str, dict[str, float]] = {}
    excluded: dict[str, str] = {}
    for symbol in symbols:
        values = {}
        for name, spec in cfg.factors.items():
            v = FACTORS[name](view, symbol, **spec.params)
            if v is None or not math.isfinite(v):
                excluded[symbol] = f"factor '{name}' could not be computed"
                break
            values[name] = v
        else:
            raw[symbol] = values
    if not raw:
        return ScoringResult([], excluded)
    weights = {name: spec.weight for name, spec in cfg.factors.items()}
    total_weight = sum(weights.values())
    bad = {n: w for n, w in weights.items() if not (math.isfinite(w) and w > 0)}
    if bad or not (math.isfinite(total_weight) and total_weight > 0):
        raise ScoringError(f"factor weights must be finite and positive with a finite total; got {weights}")
    ranks = {name: percentile_ranks({s: raw[s][name] for s in raw}) for name in cfg.factors}
    scored = []
    for s in raw:
        symbol_ranks = {n: ranks[n][s] for n in cfg.factors}
        for n, r in symbol_ranks.items():
            if not (math.isfinite(r) and 0.0 <= r <= 1.0):
                raise ScoringError(f"{s}: rank for factor '{n}' is {r!r}, not a finite number in [0, 1]")
        composite = _weighted_mean(weights, symbol_ranks, total_weight)
        if not (math.isfinite(composite) and -1e-12 <= composite <= 1.0 + 1e-12):
            raise ScoringError(f"{s}: composite score is {composite!r}, not a finite number in [0, 1]")
        scored.append(ScoredSymbol(s, composite, symbol_ranks, raw[s]))
    scored.sort(key=lambda x: (-x.composite, x.symbol))
    return ScoringResult(scored, excluded)
