"""Deterministic quantitative calculations. No LLM code may be imported here (tested).

LLMs interpret these numbers; they never produce them.
"""

from sid_trading_firm.quant.costs import SlippageModel, TransactionCostModel
from sid_trading_firm.quant.expectation import expected_value, trade_expectancy
from sid_trading_firm.quant.indicators import atr, ema, rsi, sma
from sid_trading_firm.quant.result import QuantError, Result, SeriesResult, Status
from sid_trading_firm.quant.returns import arithmetic_returns, log_returns
from sid_trading_firm.quant.risk import (
    beta,
    correlation,
    max_drawdown,
    realised_volatility,
    sharpe_ratio,
    sortino_ratio,
)
from sid_trading_firm.quant.sizing import PositionSize, atr_risk_size, volatility_target_size

__all__ = [
    "PositionSize",
    "QuantError",
    "Result",
    "SeriesResult",
    "SlippageModel",
    "Status",
    "TransactionCostModel",
    "arithmetic_returns",
    "atr",
    "atr_risk_size",
    "beta",
    "correlation",
    "ema",
    "expected_value",
    "log_returns",
    "max_drawdown",
    "realised_volatility",
    "rsi",
    "sharpe_ratio",
    "sma",
    "sortino_ratio",
    "trade_expectancy",
    "volatility_target_size",
]
