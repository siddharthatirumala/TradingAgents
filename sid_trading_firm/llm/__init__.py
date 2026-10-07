"""Model tiers, LLM usage metering and the AI budget guard."""

from sid_trading_firm.llm.budget import (
    AIBudgetStop,
    BudgetExceeded,
    BudgetGuard,
    BudgetStopEvent,
    LedgerUnavailable,
    LifetimeBudgetExhausted,
    NoRunForCall,
    UnpricedModel,
)
from sid_trading_firm.llm.ledger import UsageLedger
from sid_trading_firm.llm.models import chat_model, chat_model_for, upstream_config
from sid_trading_firm.llm.usage import (
    InMemoryUsageStore,
    JsonlUsageStore,
    LLMCallRecord,
    UsageStore,
)

__all__ = [
    "AIBudgetStop",
    "BudgetExceeded",
    "BudgetGuard",
    "BudgetStopEvent",
    "InMemoryUsageStore",
    "JsonlUsageStore",
    "LLMCallRecord",
    "LedgerUnavailable",
    "NoRunForCall",
    "LifetimeBudgetExhausted",
    "UnpricedModel",
    "UsageLedger",
    "UsageStore",
    "chat_model",
    "chat_model_for",
    "upstream_config",
]
