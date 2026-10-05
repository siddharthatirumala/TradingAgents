"""Deterministic screening filters, evaluated point-in-time.

Each threshold is explicit configuration; there are no built-in values. A threshold
left as None disables that filter and the report lists it as disabled. Every symbol
gets an outcome with the measures used and each reason it failed, so a rejection can
be explained without rerunning anything.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

import pandas as pd
from pydantic import BaseModel, ConfigDict, Field

from sid_trading_firm.backtest.data import PanelView
from sid_trading_firm.quant import arithmetic_returns, realised_volatility


class FilterConfig(BaseModel):
    """Screening thresholds. None disables a filter (and is reported as disabled)."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    min_price: float | None = Field(default=None, gt=0)
    min_avg_dollar_volume: float | None = Field(default=None, gt=0)
    max_annualised_volatility: float | None = Field(default=None, gt=0)
    min_history_days: int | None = Field(default=None, gt=1)
    max_data_age_days: int | None = Field(default=None, ge=0)
    liquidity_window: int = Field(default=20, gt=1)
    volatility_window: int = Field(default=60, gt=2)

    def disabled(self) -> list[str]:
        names = ("min_price", "min_avg_dollar_volume", "max_annualised_volatility", "min_history_days",
                 "max_data_age_days")
        return [n for n in names if getattr(self, n) is None]


@dataclass
class FilterOutcome:
    symbol: str
    passed: bool
    reasons: list[str] = field(default_factory=list)
    measures: dict[str, float | int | str | None] = field(default_factory=dict)


def evaluate_filters(view: PanelView, symbol: str, cfg: FilterConfig) -> FilterOutcome:
    out = FilterOutcome(symbol, passed=True)
    bars = view.bars(symbol)
    if bars.empty:
        out.passed, out.reasons = False, ["no price data on or before the screening date"]
        return out
    last_date = bars.index[-1]
    age = int((view.as_of - last_date).days)
    out.measures.update(last_bar=str(last_date.date()), data_age_days=age, history_days=len(bars),
                        price=float(bars["close"].iloc[-1]))

    def fail(reason: str) -> None:
        out.passed = False
        out.reasons.append(reason)

    if cfg.max_data_age_days is not None and age > cfg.max_data_age_days:
        fail(f"stale data: last bar {age} day(s) before the screening date (max {cfg.max_data_age_days})")
    if cfg.min_history_days is not None and len(bars) < cfg.min_history_days:
        fail(f"history {len(bars)} bars < {cfg.min_history_days}")
    if cfg.min_price is not None and out.measures["price"] < cfg.min_price:
        fail(f"price {out.measures['price']:.2f} < {cfg.min_price}")

    window = bars.iloc[-cfg.liquidity_window:]
    if len(window) < cfg.liquidity_window:
        adv = None
        if cfg.min_avg_dollar_volume is not None:
            fail(f"fewer than {cfg.liquidity_window} bars to measure liquidity")
    else:
        adv = float((window["close"] * window["volume"]).mean())
        if cfg.min_avg_dollar_volume is not None and adv < cfg.min_avg_dollar_volume:
            fail(f"average dollar volume {adv:,.0f} < {cfg.min_avg_dollar_volume:,.0f}")
    out.measures["avg_dollar_volume"] = adv

    closes = bars["close"].iloc[-(cfg.volatility_window + 1):]
    vol = None
    if len(closes) >= cfg.volatility_window + 1:
        r = arithmetic_returns(closes)
        v = realised_volatility(r.values) if r.ok else r.latest()
        vol = v.value if v.ok else None
        if not v.ok and cfg.max_annualised_volatility is not None:
            fail(f"volatility not measurable ({v.status.value})")
    elif cfg.max_annualised_volatility is not None:
        fail(f"fewer than {cfg.volatility_window + 1} bars to measure volatility")
    if vol is not None and cfg.max_annualised_volatility is not None and vol > cfg.max_annualised_volatility:
        fail(f"annualised volatility {vol:.2%} > {cfg.max_annualised_volatility:.2%}")
    out.measures["annualised_volatility"] = vol
    for key, value in list(out.measures.items()):
        if isinstance(value, float) and not math.isfinite(value):
            fail(f"{key} is not finite")
    return out


def screen_date_is_valid(as_of) -> pd.Timestamp:
    ts = pd.Timestamp(as_of).normalize()
    if ts > pd.Timestamp.today().normalize():
        raise ValueError(f"screening date {ts.date()} is in the future")
    return ts
