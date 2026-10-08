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
bias, cost assumptions, in-sample versus out-of-sample). Beside it go `results.json`
and equity-curve CSVs (one per segment, and the stitched out-of-sample curve next to
the benchmark held over the same windows). Add `--database` to store the results
first (needs `SID_DATABASE__URL`); the files then carry the database `run_id`, and if
storing fails they are written marked as not stored and the command exits with the
error. Signals use data up to each decision date
and orders fill at the next open; this is simulation only and never places an order.

## Deterministic screening

`sid_trading_firm/screening` reduces a versioned universe file to a short, explainable
list of candidates for later research: explicit filters (price, liquidity, volatility,
history, data freshness), then percentile-ranked factor scores, then a cap. The cap is
the smallest of the requested count, `budgets.max_ai_candidates_per_run` and what the
daily AI budget can pay for at the stated research cost per candidate. No AI model is
called, and a candidate is not a recommendation or a trade signal.

```bash
python -m sid_trading_firm.screening.run docs/sid_trading_firm/examples/screen_large_cap.yaml --out <dir>
```

## AI spending ceiling

Paid AI use is capped at **$30 in total** (owner authorisation, 2026-10-08), alongside
$3 per run and $10 per day. Paid model calls are currently **blocked**:
`research.model_mode` accepts only `"mock"`, and the baseline harness refuses to use
real provider clients.

The $30 is a **software authorisation ceiling based on provider billing assumptions**,
not a limit enforced by any provider. Before each call the budget guard reserves the
call's worst case (estimated prompt and schema tokens plus the full output cap, no cache
discount, at the prices in `sid_trading_firm/config/pricing.yaml`) against lifetime ledger
spend, atomically and across processes on PostgreSQL, and refuses the call if it would
not fit; the first refusal stops all AI work permanently. This holds only while:

- providers bill no call above that worst case, and the price table matches their prices;
- SDK retries stay disabled (`max_retries=0`), so one authorised call is one attempt;
- paid calls are metered through the PostgreSQL ledger (`SqlUsageStore`), which paid
  mode requires, so reservations survive crashes and concurrent processes.

If a provider billed above the worst case, spend could pass $30 by the excess of the calls
already in flight at that moment (one call when calls are sequential); the guard then stops
everything permanently. Provider-side spending limits on the API accounts (set by the owner in
each provider's console) are the recommended backstop against that case.

## Status

Phases 1A (foundation), 2 (deterministic backtesting) and 3 (deterministic screening) are closed with Codex's technical approval after remediation. Phase 1B is authorised only as a **limited, zero-spend build** (`docs/GOVERNANCE.md` section 27): mocked models only, a $30 software ceiling for any later paid measurement, which needs a separate owner instruction, and no brokers, paper trading, cloud deployment or live trading. Gate records: [../PHASES.md](../PHASES.md). See [decisions.md](decisions.md) for the
approved architecture decisions and [development.md](development.md) for the
branch, pull-request and upstream-sync workflow.
