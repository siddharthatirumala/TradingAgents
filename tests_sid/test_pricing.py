"""Cost estimation from the configured price table."""

from decimal import Decimal

import pytest

from sid_trading_firm.llm.pricing import CostStatus, TokenUsage, cost_of, worst_case_cost
from tests_sid.fakes import settings

pytestmark = pytest.mark.unit

SONNET = settings().price_for("anthropic", "claude-sonnet-5-5")   # $2 in, $10 out, $0.20 cache read


def test_plain_call_cost():
    est = cost_of(TokenUsage(1000, 200), SONNET)
    assert est.status == CostStatus.PRICED
    assert est.usd == Decimal("0.004")       # 1000*2/1e6 + 200*10/1e6


def test_cache_reads_and_writes_are_charged_at_their_own_rates():
    # 1000 prompt tokens, of which 800 read from cache and 100 written to it.
    est = cost_of(TokenUsage(1000, 0, cache_read_tokens=800, cache_write_tokens=100), SONNET)
    assert est.usd == (Decimal(100) * 2 + Decimal(800) * Decimal("0.20") + Decimal(100) * Decimal("2.50")) / 10**6


def test_a_missing_cache_rate_is_charged_at_the_input_rate():
    luna = settings().price_for("openai", "gpt-6-luna")      # no cache write rate
    est = cost_of(TokenUsage(1000, 0, cache_write_tokens=1000), luna)
    assert est.usd == Decimal(1000) * luna.input_per_mtok / 10**6


def test_no_usage_and_no_price_give_no_cost_not_zero():
    assert cost_of(None, SONNET).usd is None
    assert cost_of(None, SONNET).status == CostStatus.NO_USAGE
    assert cost_of(TokenUsage(10, 10), None).status == CostStatus.UNPRICED
    assert cost_of(TokenUsage(10, 10), None).usd is None


def test_worst_case_assumes_no_cache_discount():
    assert worst_case_cost(1000, 1000, SONNET) == Decimal("0.012")


def test_cost_is_exact_for_large_counts():
    est = cost_of(TokenUsage(123_456_789, 98_765_432), SONNET)
    assert est.usd == (Decimal(123_456_789) * 2 + Decimal(98_765_432) * 10) / 10**6
