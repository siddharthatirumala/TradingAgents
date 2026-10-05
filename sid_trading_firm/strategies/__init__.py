"""Versioned deterministic strategies (Phase 2).

A strategy is identified by ``<name>_<version>`` and its parameters; a parameter
change is a different parameter hash, and a logic change is a new version. Strategies
compute target weights from a point-in-time view only. No LLM code may be imported here.
"""

from sid_trading_firm.strategies.registry import (
    REGISTRY,
    StrategySpec,
    StrategyStatus,
    create,
    spec_for,
)

__all__ = ["REGISTRY", "StrategySpec", "StrategyStatus", "create", "spec_for"]
