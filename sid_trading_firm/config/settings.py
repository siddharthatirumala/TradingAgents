"""Typed application settings.

Sources, highest priority first:

1. keyword arguments to :func:`load_settings` (tests, scripts)
2. environment variables ``SID_<GROUP>__<FIELD>``
3. a ``.env`` file
4. a YAML file (``config_file`` argument or ``SID_CONFIG_FILE``)
5. the package defaults (``defaults.yaml`` and ``pricing.yaml``)

Sources are deep-merged, so overriding one nested field keeps the rest. Invalid
settings raise at load time: a misconfigured unattended run should fail at
start, not halfway through spending money.
"""

from __future__ import annotations

import os
from contextvars import ContextVar
from datetime import date
from decimal import Decimal
from enum import StrEnum
from functools import cache
from pathlib import Path
from typing import Annotated, Any, Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    SecretStr,
    StringConstraints,
    field_validator,
    model_validator,
)
from pydantic_settings import (
    BaseSettings,
    PydanticBaseSettingsSource,
    SettingsConfigDict,
    YamlConfigSettingsSource,
)

from sid_trading_firm.config.agents import AGENTS

_PACKAGE_DIR = Path(__file__).resolve().parent
DEFAULTS_FILE = _PACKAGE_DIR / "defaults.yaml"
PRICING_FILE = _PACKAGE_DIR / "pricing.yaml"

# The user config file for the load in progress; read by settings_customise_sources.
_config_file: ContextVar[Path | None] = ContextVar("sid_config_file", default=None)


class ConfigError(ValueError):
    """Settings that cannot be used."""


class Strict(BaseModel):
    """Base for settings groups: unknown keys are errors, not silently ignored."""

    model_config = ConfigDict(extra="forbid", frozen=True)


# --------------------------------------------------------------------------- app


class Environment(StrEnum):
    DEVELOPMENT = "development"
    TEST = "test"
    PAPER = "paper"


class AppSettings(Strict):
    name: str = "SID Trading Firm"
    environment: Environment = Environment.DEVELOPMENT
    market_scope: Literal["us_equities"] = "us_equities"
    live_trading_enabled: bool = False

    @field_validator("live_trading_enabled")
    @classmethod
    def _never_live(cls, value: bool) -> bool:
        if value:
            raise ValueError(
                "live trading is not implemented and cannot be enabled by configuration; "
                "SID Trading Firm is research and paper trading only"
            )
        return value


# ------------------------------------------------------------------------ models


class Tier(StrEnum):
    FAST = "fast"
    STANDARD = "standard"
    DEEP = "deep"


@cache
def supported_providers() -> frozenset[str]:
    """Provider names upstream TradingAgents can build a chat model for."""
    from tradingagents.llm_clients.openai_client import OPENAI_COMPATIBLE_PROVIDERS

    return frozenset({"anthropic", "google", "azure", "bedrock", *OPENAI_COMPATIBLE_PROVIDERS})


class ModelSpec(Strict):
    """One provider and model, plus the knobs every provider shares."""

    provider: str
    model: Annotated[str, Field(min_length=1)]
    base_url: str | None = None
    temperature: Annotated[float, Field(ge=0, le=2)] | None = None
    max_output_tokens: Annotated[int, Field(gt=0)] | None = None
    # Provider-specific reasoning depth (OpenAI reasoning effort, Anthropic
    # effort, Google thinking level). None leaves the provider default.
    reasoning_effort: str | None = None

    @field_validator("provider")
    @classmethod
    def _known_provider(cls, value: str) -> str:
        value = value.strip().lower()
        if value not in supported_providers():
            raise ValueError(f"unsupported provider {value!r}; known: {sorted(supported_providers())}")
        return value

    @property
    def key(self) -> str:
        """The pricing key for this model: ``provider/model``."""
        return f"{self.provider}/{self.model}"


class ModelSettings(Strict):
    tiers: dict[Tier, ModelSpec]
    agents: dict[str, Tier]

    @model_validator(mode="after")
    def _complete(self) -> ModelSettings:
        missing = set(Tier) - set(self.tiers)
        if missing:
            raise ValueError(f"model tiers missing: {sorted(t.value for t in missing)}")
        unknown = set(self.agents) - set(AGENTS)
        if unknown:
            raise ValueError(f"unknown agent ids in models.agents: {sorted(unknown)}")
        return self

    def tier_for(self, agent: str) -> Tier:
        try:
            return self.agents[agent]
        except KeyError:
            raise ConfigError(f"agent {agent!r} has no model tier in models.agents") from None

    def spec_for(self, agent: str) -> ModelSpec:
        """The model an agent runs on. Unknown agents are an error, never a default."""
        return self.tiers[self.tier_for(agent)]


# ----------------------------------------------------------------------- pricing


class ModelPrice(Strict):
    """USD per million tokens."""

    input_per_mtok: Annotated[Decimal, Field(ge=0)]
    output_per_mtok: Annotated[Decimal, Field(ge=0)]
    cache_read_per_mtok: Annotated[Decimal, Field(ge=0)] | None = None
    cache_write_per_mtok: Annotated[Decimal, Field(ge=0)] | None = None
    source: str
    as_of: date
    verified: bool = False


# ----------------------------------------------------------------------- budgets


class BudgetSettings(Strict):
    max_ai_cost_per_run_usd: Annotated[Decimal, Field(gt=0)]
    max_ai_cost_per_day_usd: Annotated[Decimal, Field(gt=0)]
    # Lifetime ceiling on all paid AI spend for Phase 1B measurement (owner, 2026-10-08:
    # "hard maximum ... $30 total"). The bound is in code so configuration cannot raise it.
    max_ai_cost_total_usd: Annotated[Decimal, Field(gt=0, le=Decimal("30.00"))]
    max_llm_tokens_per_agent: Annotated[int, Field(gt=0)]
    max_agent_iterations: Annotated[int, Field(gt=0)]
    max_debate_rounds: Annotated[int, Field(ge=1)]
    max_risk_discuss_rounds: Annotated[int, Field(ge=1)]
    # Most candidates one screening run may hand to AI research.
    max_ai_candidates_per_run: Annotated[int, Field(ge=1, le=50)] = 5
    # Output tokens assumed for a call's pre-call cost estimate when its model
    # sets no max_output_tokens.
    output_token_reserve: Annotated[int, Field(gt=0)] = 4096
    # A model with no price cannot be held to a budget; refuse it unless allowed.
    allow_unpriced_models: bool = False

    @model_validator(mode="after")
    def _run_within_day(self) -> BudgetSettings:
        if self.max_ai_cost_per_run_usd > self.max_ai_cost_per_day_usd:
            raise ValueError("max_ai_cost_per_run_usd cannot exceed max_ai_cost_per_day_usd")
        if self.max_ai_cost_per_day_usd > self.max_ai_cost_total_usd:
            raise ValueError("max_ai_cost_per_day_usd cannot exceed max_ai_cost_total_usd")
        return self


# -------------------------------------------------------------------------- risk

Percent = Annotated[float, Field(gt=0, le=100)]
# US-listed symbol as written by the Yahoo data layer (share classes as BRK-B).
UsSymbol = Annotated[str, StringConstraints(pattern=r"^[A-Z]{1,5}(-[A-Z])?$")]


class RiskSettings(Strict):
    """Hard-risk limit placeholders. Percentages are 0-100, not fractions.

    Unset (None) is deliberate: no final values have been chosen. The hard risk
    engine must reject every proposal while any limit is unset.
    """

    max_position_pct: Percent | None = None
    max_daily_loss_pct: Percent | None = None
    max_drawdown_pct: Percent | None = None
    max_sector_exposure_pct: Percent | None = None
    max_open_positions: Annotated[int, Field(gt=0)] | None = None
    max_trades_per_day: Annotated[int, Field(gt=0)] | None = None
    min_avg_daily_volume: Annotated[float, Field(gt=0)] | None = None
    max_data_age_seconds: Annotated[int, Field(gt=0)] | None = None
    # Phase 1B additions, equally unset until the owner approves values.
    allowed_instruments: Annotated[list[UsSymbol], Field(min_length=1)] | None = None
    max_order_notional: Annotated[Decimal, Field(gt=0)] | None = None
    policy_version: Annotated[str, Field(min_length=1, max_length=64)] | None = None

    @property
    def unset(self) -> list[str]:
        return [name for name, value in self.model_dump().items() if value is None]

    @property
    def complete(self) -> bool:
        return not self.unset


# ---------------------------------------------------------------------- research


class FreshnessSettings(Strict):
    """Snapshot freshness thresholds for Phase 1B research. No defaults: the owner sets them."""

    prices_max_age_trading_days: Annotated[int, Field(ge=0)] | None = None
    fundamentals_max_age_days: Annotated[int, Field(gt=0)] | None = None
    news_window_hours: Annotated[int, Field(gt=0)] | None = None
    news_min_items: Annotated[int, Field(ge=0)] | None = None
    macro_max_age_days: Annotated[int, Field(gt=0)] | None = None


class ResearchSettings(Strict):
    """Phase 1B research switch. Off by default; zero-spend (mocked models) is the only mode.

    Turning research on with any freshness threshold or the news cap unset is refused
    at load, so a run can never start with an undefined data rule.
    """

    enabled: bool = False
    model_mode: Literal["mock"] = "mock"
    max_news_items_per_instrument: Annotated[int, Field(gt=0)] | None = None
    freshness: FreshnessSettings = Field(default_factory=FreshnessSettings)

    @property
    def unset(self) -> list[str]:
        missing = [f"freshness.{k}" for k, v in self.freshness.model_dump().items() if v is None]
        return missing + (["max_news_items_per_instrument"] if self.max_news_items_per_instrument is None else [])

    @model_validator(mode="after")
    def _complete_when_enabled(self) -> ResearchSettings:
        if self.enabled and self.unset:
            raise ValueError(f"research cannot be enabled while these are unset: {', '.join(self.unset)}")
        return self


# ---------------------------------------------------------------- db and logging


class DatabaseSettings(Strict):
    url: SecretStr | None = None
    echo: bool = False

    def require_url(self) -> str:
        if self.url is None or not self.url.get_secret_value():
            raise ConfigError("database.url is not set (SID_DATABASE__URL)")
        return self.url.get_secret_value()


class LoggingSettings(Strict):
    level: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] = "INFO"
    format: Literal["json", "text"] = "json"

    @field_validator("level", mode="before")
    @classmethod
    def _upper(cls, value: Any) -> Any:
        return value.upper() if isinstance(value, str) else value


# -------------------------------------------------------------------------- root


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="SID_",
        env_nested_delimiter="__",
        env_file=None,
        extra="forbid",
        frozen=True,
    )

    app: AppSettings
    models: ModelSettings
    pricing: dict[str, ModelPrice]
    budgets: BudgetSettings
    risk: RiskSettings
    research: ResearchSettings
    database: DatabaseSettings
    logging: LoggingSettings

    @classmethod
    def settings_customise_sources(
        cls,
        settings_cls: type[BaseSettings],
        init_settings: PydanticBaseSettingsSource,
        env_settings: PydanticBaseSettingsSource,
        dotenv_settings: PydanticBaseSettingsSource,
        file_secret_settings: PydanticBaseSettingsSource,
    ) -> tuple[PydanticBaseSettingsSource, ...]:
        sources = [init_settings, env_settings, dotenv_settings]
        user_file = _config_file.get()
        if user_file is not None:
            sources.append(YamlConfigSettingsSource(settings_cls, yaml_file=user_file))
        sources.append(YamlConfigSettingsSource(settings_cls, yaml_file=DEFAULTS_FILE))
        sources.append(YamlConfigSettingsSource(settings_cls, yaml_file=PRICING_FILE))
        return tuple(sources)

    def price_for(self, provider: str, model: str) -> ModelPrice | None:
        return self.pricing.get(f"{provider.lower()}/{model}")

    def require_research_ready(self) -> None:
        """Raise :class:`ConfigError` unless Phase 1B research is switched on (and therefore complete)."""
        if not self.research.enabled:
            raise ConfigError("research is disabled (research.enabled is false)")

    def snapshot(self) -> dict[str, Any]:
        """The settings as plain data with secrets masked, for run records."""
        return self.model_dump(mode="json")


def load_settings(
    config_file: str | Path | None = None,
    env_file: str | Path | None = ".env",
    **overrides: Any,
) -> Settings:
    """Load and validate settings; raise :class:`ConfigError` when they are unusable.

    ``config_file`` defaults to ``SID_CONFIG_FILE``. A config file that is named
    but missing is an error: a run must not quietly fall back to defaults.
    ``env_file=None`` skips the .env file (tests do).
    """
    path = config_file or os.environ.get("SID_CONFIG_FILE") or None
    if path is not None:
        path = Path(path)
        if not path.is_file():
            raise ConfigError(f"config file not found: {path}")
    token = _config_file.set(path)
    try:
        return Settings(_env_file=env_file, **overrides)
    except ValueError as exc:   # pydantic ValidationError is a ValueError
        raise ConfigError(f"invalid SID Trading Firm settings:\n{exc}") from exc
    finally:
        _config_file.reset(token)
