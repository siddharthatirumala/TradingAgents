"""SID Trading Firm: a research and paper-trading platform built on TradingAgents.

Upstream TradingAgents (``tradingagents/``) is the research engine; this package
composes it and adds what a trading organisation needs around it: typed
configuration, run tracking, LLM cost accounting and budgets, persistence,
deterministic quantitative calculations and typed decision contracts.

Research, backtesting and paper trading only. Nothing in this package places a
live order, and no code path may enable one.
"""

__version__ = "0.1.0"
