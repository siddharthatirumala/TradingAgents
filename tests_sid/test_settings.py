"""Typed settings: defaults, layering, overrides and fail-closed validation."""

from decimal import Decimal

import pytest

from sid_trading_firm.config import ConfigError, Tier, load_settings
from sid_trading_firm.config.agents import AGENTS

pytestmark = pytest.mark.unit


def _load(**kwargs):
    return load_settings(env_file=None, **kwargs)


def test_defaults_load_and_follow_the_approved_model_strategy():
    s = _load()
    assert s.app.environment == "development"
    assert s.app.market_scope == "us_equities"
    assert s.app.live_trading_enabled is False
    assert (s.models.tiers[Tier.FAST].provider, s.models.tiers[Tier.FAST].model) == ("openai", "gpt-6-luna")
    assert s.models.tiers[Tier.STANDARD].model == "claude-sonnet-5-5"
    assert s.models.tiers[Tier.DEEP].model == "claude-sonnet-5-5"
    assert s.models.tier_for("fundamentals_analyst") == Tier.STANDARD
    assert {s.models.tier_for(a) for a in ("research_manager", "portfolio_manager", "cio")} == {Tier.DEEP}


def test_every_known_agent_has_a_tier_by_default():
    assert set(_load().models.agents) == set(AGENTS)


def test_every_default_tier_model_is_priced():
    s = _load()
    for spec in s.models.tiers.values():
        assert s.price_for(spec.provider, spec.model) is not None, spec.key


def test_prices_are_exact_decimals():
    price = _load().price_for("anthropic", "claude-sonnet-5-5")
    assert price.input_per_mtok == Decimal("2.00")
    assert price.output_per_mtok == Decimal("10.00")


def test_risk_limits_are_unset_placeholders():
    risk = _load().risk
    assert not risk.complete
    assert "max_position_pct" in risk.unset


def test_environment_overrides_one_nested_field_and_keeps_the_rest(monkeypatch):
    monkeypatch.setenv("SID_BUDGETS__MAX_AI_COST_PER_RUN_USD", "2.5")
    monkeypatch.setenv("SID_MODELS__TIERS__DEEP__PROVIDER", "openai")
    monkeypatch.setenv("SID_MODELS__TIERS__DEEP__MODEL", "gpt-6-sol")

    s = _load()

    assert s.budgets.max_ai_cost_per_run_usd == Decimal("2.5")
    assert s.budgets.max_ai_cost_per_day_usd == Decimal("10.00")
    assert s.models.spec_for("cio").key == "openai/gpt-6-sol"
    assert s.models.spec_for("bull_researcher").key == "anthropic/claude-sonnet-5-5"


def test_a_config_file_overrides_defaults_and_the_environment_overrides_the_file(tmp_path, monkeypatch):
    cfg = tmp_path / "sid.yaml"
    cfg.write_text("budgets:\n  max_ai_cost_per_run_usd: 1.25\n  max_debate_rounds: 2\n"
                   "logging:\n  level: debug\n", encoding="utf-8")
    monkeypatch.setenv("SID_BUDGETS__MAX_DEBATE_ROUNDS", "3")

    s = _load(config_file=cfg)

    assert s.budgets.max_ai_cost_per_run_usd == Decimal("1.25")
    assert s.budgets.max_debate_rounds == 3
    assert s.logging.level == "DEBUG"


def test_config_file_named_by_environment_variable(tmp_path, monkeypatch):
    cfg = tmp_path / "sid.yaml"
    cfg.write_text("app:\n  environment: paper\n", encoding="utf-8")
    monkeypatch.setenv("SID_CONFIG_FILE", str(cfg))
    assert _load().app.environment == "paper"


def test_a_named_config_file_that_is_missing_is_an_error(tmp_path):
    with pytest.raises(ConfigError, match="not found"):
        _load(config_file=tmp_path / "nope.yaml")


def test_dotenv_file_is_read_and_environment_beats_it(tmp_path, monkeypatch):
    env = tmp_path / ".env"
    env.write_text("SID_LOGGING__FORMAT=text\nSID_LOGGING__LEVEL=WARNING\n", encoding="utf-8")
    monkeypatch.setenv("SID_LOGGING__LEVEL", "ERROR")

    s = load_settings(env_file=env)

    assert s.logging.format == "text"
    assert s.logging.level == "ERROR"


@pytest.mark.parametrize("env, value, message", [
    ("SID_APP__LIVE_TRADING_ENABLED", "true", "live trading"),
    ("SID_BUDGETS__MAX_AI_COST_PER_RUN_USD", "-1", "greater than 0"),
    ("SID_BUDGETS__MAX_AI_COST_PER_RUN_USD", "50", "cannot exceed"),
    ("SID_BUDGETS__MAX_DEBATE_ROUNDS", "0", "greater than or equal to 1"),
    ("SID_MODELS__TIERS__FAST__PROVIDER", "nosuchai", "unsupported provider"),
    ("SID_MODELS__AGENTS__MYSTERY_AGENT", "fast", "unknown agent"),
    ("SID_MODELS__AGENTS__CIO", "turbo", "Input should be"),
    ("SID_APP__MARKET_SCOPE", "crypto", "us_equities"),
    ("SID_RISK__MAX_POSITION_PCT", "150", "less than or equal to 100"),
    ("SID_APP__UNKNOWN_FIELD", "x", "Extra inputs"),
])
def test_invalid_settings_fail_at_load(monkeypatch, env, value, message):
    monkeypatch.setenv(env, value)
    with pytest.raises(ConfigError, match=message):
        _load()


def test_an_unknown_agent_has_no_model():
    with pytest.raises(ConfigError, match="no model tier"):
        _load().models.spec_for("intern")


def test_database_url_is_secret_and_required_when_used(monkeypatch):
    with pytest.raises(ConfigError, match="database.url"):
        _load().database.require_url()

    monkeypatch.setenv("SID_DATABASE__URL", "postgresql+psycopg://sid:hunter2@localhost/sid")
    s = _load()

    assert s.database.require_url().endswith("@localhost/sid")
    assert "hunter2" not in str(s.snapshot())
    assert "hunter2" not in repr(s)


def test_settings_are_immutable():
    s = _load()
    with pytest.raises(ValueError):
        s.budgets.max_debate_rounds = 5
