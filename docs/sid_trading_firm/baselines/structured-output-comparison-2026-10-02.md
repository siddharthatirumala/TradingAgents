# Structured-output fix (PR #9): before vs after

**UPSTREAM ALL-SONNET BASELINE**: an engineering measurement of cost, reliability,
structured-output behaviour and call volume. It is **not** an investment-performance
test, and the all-Sonnet setup is temporary: it is the inherited upstream two-tier
graph, not the planned FAST/STANDARD/DEEP routing. Two runs are two samples; do not set
production budgets from them.

## Conditions (identical in both runs)

| | |
|---|---|
| Ticker / trade date | NVDA / 2026-10-02 |
| Graph | upstream TradingAgents v0.6.0, all four analysts, debate 1 round, risk 1 round |
| Models | `anthropic/claude-sonnet-5-5` for both upstream tiers, 8192 output tokens per call |
| Budget | $3.00 per run, $10.00 per day (hard caps) |
| Only code difference | commit `234d8bd`: Sonnet 5.5 structured output via native JSON Schema instead of an unforced tool call |
| Reports | before: [`2026-10-02_NVDA_72610e44`](2026-10-02_NVDA_72610e44/report.md), after: [`2026-10-02_NVDA_c15b5e77`](2026-10-02_NVDA_c15b5e77/report.md) |

## Comparison

| Metric | Before PR #9 | After PR #9 | Difference |
|---|---:|---:|---:|
| LLM calls | 17 | 16 | −1 |
| Input tokens | 167,672 | 154,873 | −12,799 (−7.6%) |
| Output tokens | 46,504 | 41,494 | −5,010 (−10.8%) |
| Total tokens | 214,176 | 196,367 | −17,809 (−8.3%) |
| Total cost | $0.8004 | $0.7247 | −$0.0757 (−9.5%) |
| Structured calls (method) | 4 (function_calling) | 4 (json_schema) | method changed as intended |
| Structured-call cost | $0.1180 | $0.1153 | −$0.0027 |
| Structured failures | 0 | 0 | 0 |
| Fallback calls | 0 | 0 | 0 |
| Fallback cost | $0.0000 | $0.0000 | $0.0000 |
| Tool rounds | 5 | 4 | −1 (News Analyst) |
| Calls at the 8192-token output cap | 1 (Bear Researcher) | 0 | −1 |
| Runtime | 308.1 s | 277.7 s | −30.4 s |
| Successful completion | yes | yes | — |
| Budget guard | 17 calls authorised, no stop, $0.80 of $3 | 16 calls authorised, no stop, $0.72 of $3 | — |

## What the difference does and does not show

- **PR #9 changed what it was meant to change.** All four structured calls (Sentiment,
  Research Manager, Trader, Portfolio Manager) moved from an unforced tool call to native
  JSON-Schema output, and all four validated on the first attempt.
- **No fallback occurred in either run.** In this sample Sonnet 5.5 happened to call the
  unforced schema tool every time, so there was no fallback cost to save. PR #9's benefit
  is removing that failure mode (prose instead of a tool call, then a second paid
  request), not a saving measured here.
- **The −$0.0757 total is mostly run-to-run variation, not PR #9.** Structured calls
  account for −$0.0027 of it. The rest is in calls PR #9 does not touch: the News Analyst
  made one fewer tool round (−$0.0217, −10,013 input tokens), and the risk analysts and
  Bear Researcher wrote shorter outputs. LLM output differs between identical runs.
- **The output cap matters.** Before, the Bear Researcher stopped at exactly 8192 output
  tokens, so its argument was probably cut off; after, it stopped at 7,908. The 8192 cap
  (added to bound cost) can truncate long debate turns. Worth revisiting in Phase 1B.

Raw per-call records are in each run's `llm_calls.jsonl` (no prompts, responses or credentials).
