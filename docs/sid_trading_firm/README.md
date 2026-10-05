# SID Trading Firm

A multi-agent investment research and **paper-trading** platform built on top of
[TauricResearch/TradingAgents](https://github.com/TauricResearch/TradingAgents).

The purpose is to test whether a disciplined, measured, multi-agent research
process develops a genuine trading edge. Profitability is not assumed: every
decision, cost and outcome is recorded so the question can be answered with data.

## Safety rules (non-negotiable)

- Research, backtesting and paper trading only. There is no live-trading code
  path, and `live_trading_enabled` cannot be switched on by configuration.
- LLMs interpret; Python calculates. Returns, volatility, indicators, exposure,
  P&L, sizing and costs come from deterministic code in `sid_trading_firm/quant`.
- A deterministic hard risk engine (later phase) has the final word. No LLM can
  override it. When in doubt, the system rejects.
- AI spend is metered per call and capped per run and per day. Exceeding a
  budget stops further AI analysis; it never continues silently.

## Layout

| Path | Owner | Purpose |
|---|---|---|
| `tradingagents/`, `cli/`, `tests/` | upstream | Research engine, kept as close to upstream as possible |
| `sid_trading_firm/` | SID Trading Firm | Our platform code, composed around upstream |
| `tests_sid/` | SID Trading Firm | Our test suite |
| `docs/sid_trading_firm/` | SID Trading Firm | Decisions, workflow and reports |

## Install and test

```bash
python -m venv .venv
.venv/Scripts/activate        # Windows; use .venv/bin/activate elsewhere
pip install -e ".[dev,sid]"
pytest                        # upstream TradingAgents suite
pytest tests_sid              # SID Trading Firm suite
ruff check .
```

## Deterministic backtesting

Strategies are evaluated with deterministic Python only (`sid_trading_firm/backtest`,
`sid_trading_firm/strategies`); no AI model is involved, because an LLM analysing a past
date may already know what happened. A YAML specification names the data, the strategy
and its parameters, costs, slippage and the evaluation (train/validation/test split
and walk-forward):

```bash
python -m sid_trading_firm.backtest.run docs/sid_trading_firm/examples/backtest_momentum.yaml --out <dir>
```

The report states its assumptions and limitations (adjusted prices, survivorship
bias, cost assumptions, in-sample versus out-of-sample). Add `--database` to store
the results (needs `SID_DATABASE__URL`). Signals use data up to each decision date
and orders fill at the next open; this is simulation only and never places an order.

## Status

Phase 1A (foundation) and Phase 2 (deterministic backtesting) are merged; Phase 3
(screening) is in progress. Gate records: [../PHASES.md](../PHASES.md). See [decisions.md](decisions.md) for the
approved architecture decisions and [development.md](development.md) for the
branch, pull-request and upstream-sync workflow.
