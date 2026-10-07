"""Phase 1B configuration: research off by default, zero-spend only, complete before it can
be enabled; new hard-risk limits unset; the lifetime AI budget capped at $30 in code."""

from decimal import Decimal

import pytest

from sid_trading_firm.config import ConfigError, load_settings

pytestmark = pytest.mark.unit

FRESHNESS = {"prices_max_age_trading_days": 1, "fundamentals_max_age_days": 120, "news_window_hours": 72,
             "news_min_items": 0, "macro_max_age_days": 45}


def _load(**kwargs):
    return load_settings(env_file=None, **kwargs)


def test_research_is_off_mock_only_and_unconfigured_by_default():
    r = _load().research
    assert r.enabled is False and r.model_mode == "mock"
    assert r.unset == [f"freshness.{k}" for k in FRESHNESS] + ["max_news_items_per_instrument"]


def test_a_disabled_research_switch_refuses_to_start():
    with pytest.raises(ConfigError, match="research is disabled"):
        _load().require_research_ready()


@pytest.mark.parametrize("missing", [*FRESHNESS, "max_news_items_per_instrument"])
def test_research_cannot_be_enabled_with_any_threshold_unset(missing):
    freshness = {k: v for k, v in FRESHNESS.items() if k != missing}
    research = {"enabled": True, "freshness": freshness}
    if missing != "max_news_items_per_instrument":
        research["max_news_items_per_instrument"] = 20
    with pytest.raises(ConfigError, match=f"research cannot be enabled.*{missing}"):
        _load(research=research)


def test_research_can_be_enabled_once_complete():
    s = _load(research={"enabled": True, "max_news_items_per_instrument": 20, "freshness": FRESHNESS})
    s.require_research_ready()
    assert s.research.unset == []


@pytest.mark.parametrize("env, value, message", [
    ("SID_RESEARCH__MODEL_MODE", "live", "Input should be 'mock'"),        # zero-spend: no paid model mode
    ("SID_RESEARCH__ENABLED", "true", "research cannot be enabled"),
    ("SID_RESEARCH__MAX_NEWS_ITEMS_PER_INSTRUMENT", "0", "greater than 0"),
    ("SID_RESEARCH__FRESHNESS__NEWS_WINDOW_HOURS", "-1", "greater than 0"),
    ("SID_RESEARCH__SURPRISE", "1", "Extra inputs"),
])
def test_invalid_research_settings_fail_at_load(monkeypatch, env, value, message):
    monkeypatch.setenv(env, value)
    with pytest.raises(ConfigError, match=message):
        _load()


def test_new_hard_risk_limits_are_unset_placeholders():
    risk = _load().risk
    assert {"allowed_instruments", "max_order_notional", "policy_version"} <= set(risk.unset)
    assert not risk.complete


@pytest.mark.parametrize("field, value, message", [
    ("allowed_instruments", [], "at least 1"),
    ("allowed_instruments", ["NVDA.L"], "should match pattern"),
    ("allowed_instruments", ["aapl"], "should match pattern"),
    ("max_order_notional", "0", "greater than 0"),
    ("max_order_notional", "NaN", "finite"),
    ("policy_version", "", "at least 1"),
])
def test_invalid_hard_risk_values_are_refused(field, value, message):
    with pytest.raises(ConfigError, match=message):
        _load(risk={field: value})


def test_valid_hard_risk_values_load():
    risk = _load(risk={"allowed_instruments": ["AAPL", "BRK-B"], "max_order_notional": "5000",
                       "policy_version": "draft-1"}).risk
    assert risk.allowed_instruments == ["AAPL", "BRK-B"] and risk.max_order_notional == Decimal("5000")


def test_the_lifetime_budget_is_30_dollars_and_bounds_the_others():
    b = _load().budgets
    assert (b.max_ai_cost_per_run_usd, b.max_ai_cost_per_day_usd, b.max_ai_cost_total_usd) == (
        Decimal("3.00"), Decimal("10.00"), Decimal("30.00"))


@pytest.mark.parametrize("env, value, message", [
    ("SID_BUDGETS__MAX_AI_COST_TOTAL_USD", "30.01", "less than or equal to 30"),   # cannot be raised by config
    ("SID_BUDGETS__MAX_AI_COST_TOTAL_USD", "5", "per_day_usd cannot exceed max_ai_cost_total_usd"),
    ("SID_BUDGETS__MAX_AI_COST_TOTAL_USD", "0", "greater than 0"),
])
def test_the_lifetime_budget_cannot_be_raised_or_undercut(monkeypatch, env, value, message):
    monkeypatch.setenv(env, value)
    with pytest.raises(ConfigError, match=message):
        _load()
