"""Turning token counts into an estimated cost, from the configured price table.

Prices are never hard-coded here: they come from ``settings.pricing``. A model
with no price, or a call with no token usage, gets no cost and says why, rather
than a made-up number.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from enum import StrEnum

from sid_trading_firm.config.settings import ModelPrice

MILLION = Decimal(1_000_000)


class CostStatus(StrEnum):
    PRICED = "priced"           # provider reported usage and the model has a price
    UNPRICED = "unpriced"       # the model is missing from the price table
    NO_USAGE = "no_usage"       # the provider reported no token usage


@dataclass(frozen=True)
class TokenUsage:
    """Token counts as LangChain reports them.

    ``input_tokens`` is the total prompt, cached parts included; the cache
    counts say how much of it was read from or written to the prompt cache.
    """

    input_tokens: int
    output_tokens: int
    cache_read_tokens: int = 0
    cache_write_tokens: int = 0

    @property
    def total_tokens(self) -> int:
        return self.input_tokens + self.output_tokens


@dataclass(frozen=True)
class CostEstimate:
    usd: Decimal | None
    status: CostStatus


def _rate(per_mtok: Decimal | None, fallback: Decimal) -> Decimal:
    # A cache rate the table does not give is charged at the input rate: an
    # overestimate, never an underestimate.
    return per_mtok if per_mtok is not None else fallback


def cost_of(usage: TokenUsage | None, price: ModelPrice | None) -> CostEstimate:
    """Estimated USD cost of one call."""
    if usage is None:
        return CostEstimate(None, CostStatus.NO_USAGE)
    if price is None:
        return CostEstimate(None, CostStatus.UNPRICED)
    cached = usage.cache_read_tokens + usage.cache_write_tokens
    uncached = max(usage.input_tokens - cached, 0)
    usd = (
        uncached * price.input_per_mtok
        + usage.cache_read_tokens * _rate(price.cache_read_per_mtok, price.input_per_mtok)
        + usage.cache_write_tokens * _rate(price.cache_write_per_mtok, price.input_per_mtok)
        + usage.output_tokens * price.output_per_mtok
    ) / MILLION
    return CostEstimate(usd, CostStatus.PRICED)


def worst_case_cost(input_tokens: int, output_tokens: int, price: ModelPrice) -> Decimal:
    """Upper-bound cost for a call not yet made: no cache discount assumed."""
    return (input_tokens * price.input_per_mtok + output_tokens * price.output_per_mtok) / MILLION
