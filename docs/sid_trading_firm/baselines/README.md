# Baseline measurements

One folder per metered run of upstream TradingAgents, written by:

```bash
python -m sid_trading_firm.measurement.baseline --ticker NVDA --date 2026-10-02
```

Each folder holds `report.md` (cost by agent, stage and model; longest calls;
largest prompts; structured-output fallbacks; budget stops), `summary.json` and
`llm_calls.jsonl` (one record per model call, no prompts or keys).

These measure cost and behaviour, not investment quality. Every run is capped by
`budgets.max_ai_cost_per_run_usd` (override with `--budget-usd`) and the daily
cap, counted from the shared ledger at `~/.sid_trading_firm/llm_usage.jsonl`.
