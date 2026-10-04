# UPSTREAM ALL-SONNET BASELINE (BEFORE PR #9): NVDA on 2026-10-02

Measures what one normal upstream TradingAgents analysis costs. It does not evaluate the investment decision.

> Inherited upstream behaviour: upstream's graph has two model tiers, so every agent here runs on the same model. This is NOT the planned FAST/STANDARD/DEEP mixed-model design, and one run is one sample: do not derive production budgets from it.

| | |
|---|---|
| Run id | `72610e44-1aad-4774-8e25-378f788af323` |
| Status | **completed** |
| Upstream decision | Overweight |
| Analysts | market, social, news, fundamentals |
| Models | upstream quick tier = anthropic/claude-sonnet-5-5; deep tier = anthropic/claude-sonnet-5-5 |
| Output cap | 8192 tokens per call |
| Budget | $3.0 per run, $10.0 per day, 300,000 tokens and 12 calls per agent |
| Rounds | debate 1, risk 1, analyst tool rounds 11 |
| Wall time | 308s |
| Total | **17 calls, 167,672 input + 46,504 output tokens, $0.8004** |
| Tool rounds | 5 |
| Structured calls | 4, of which failed and retried as free text: **0** (fallback cost $0.0000) |
| Output cap reached | 1 call(s) (Bear Researcher) |
| Budget guard | consulted for 17 calls; stops: 0; run spend $0.8004 of $3.0 cap |

## Cost by agent

| Agent | Stage | Calls | Tool rounds | Structured | Fallbacks | Input tok | Output tok | Total tok | Cost | Total latency | Slowest call |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| Technical Analyst | Analysts | 3 | 2 | 0 | 0 | 34,808 | 4,347 | 39,155 | $0.1131 | 32.5s | 25.5s |
| Fundamentals Analyst | Analysts | 2 | 1 | 0 | 0 | 9,505 | 7,833 | 17,338 | $0.0973 | 57.7s | 54.6s |
| News Analyst | Analysts | 3 | 2 | 0 | 0 | 18,592 | 3,279 | 21,871 | $0.0700 | 25.9s | 18.2s |
| Sentiment Analyst | Analysts | 1 | 0 | 1 | 0 | 4,397 | 2,411 | 6,808 | $0.0329 | 18.7s | 18.7s |
| Bear Researcher | Research debate | 1 | 0 | 0 | 0 | 17,370 | 8,192 | 25,562 | $0.1167 | 70.7s | 70.7s |
| Bull Researcher | Research debate | 1 | 0 | 0 | 0 | 12,323 | 3,231 | 15,554 | $0.0570 | 26.5s | 26.5s |
| Research Manager | Research debate | 1 | 0 | 1 | 0 | 5,835 | 1,727 | 7,562 | $0.0289 | 14.2s | 14.2s |
| Neutral Risk Analyst | Decision | 1 | 0 | 0 | 0 | 20,028 | 5,224 | 25,252 | $0.0923 | 45.1s | 45.1s |
| Conservative Risk Analyst | Decision | 1 | 0 | 0 | 0 | 16,282 | 5,166 | 21,448 | $0.0842 | 45.0s | 45.0s |
| Aggressive Risk Analyst | Decision | 1 | 0 | 0 | 0 | 13,052 | 2,576 | 15,628 | $0.0519 | 23.5s | 23.5s |
| Portfolio Manager | Decision | 1 | 0 | 1 | 0 | 8,978 | 1,928 | 10,906 | $0.0372 | 15.4s | 15.4s |
| Trader | Decision | 1 | 0 | 1 | 0 | 6,502 | 590 | 7,092 | $0.0189 | 5.2s | 5.2s |
| **Total run** | | **17** | 5 | 4 | **0** | **167,672** | **46,504** | **214,176** | **$0.8004** | 380.3s | 70.7s |

## Cost by stage

| Stage | Calls | Cost | Share |
|---|---:|---:|---:|
| Analysts | 9 | $0.3133 | 39% |
| Research debate | 3 | $0.2026 | 25% |
| Decision | 5 | $0.2845 | 36% |

## Cost by model

| Model | Calls | Input tok | Output tok | Cost |
|---|---:|---:|---:|---:|
| anthropic/claude-sonnet-5-5 | 17 | 167,672 | 46,504 | $0.8004 |

## Longest calls (top 5)

| Agent | Model | Latency | Input tok | Output tok |
|---|---|---:|---:|---:|
| Bear Researcher | claude-sonnet-5-5 | 70.7s | 17370 | 8192 |
| Fundamentals Analyst | claude-sonnet-5-5 | 54.6s | 7538 | 7504 |
| Neutral Risk Analyst | claude-sonnet-5-5 | 45.1s | 20028 | 5224 |
| Conservative Risk Analyst | claude-sonnet-5-5 | 45.0s | 16282 | 5166 |
| Bull Researcher | claude-sonnet-5-5 | 26.5s | 12323 | 3231 |

## Largest prompts (top 5)

| Agent | Input tok | Prompt chars | Cost |
|---|---:|---:|---:|
| Neutral Risk Analyst | 20028 | 53,196 | $0.0923 |
| Technical Analyst | 19779 | 35,126 | $0.0729 |
| Bear Researcher | 17370 | 44,707 | $0.1167 |
| Conservative Risk Analyst | 16282 | 42,154 | $0.0842 |
| Aggressive Risk Analyst | 13052 | 32,961 | $0.0519 |

## Every call

| # | Agent | Provider / model | Kind | Tools offered | Tool calls | Input tok | Output tok | Cost | Latency | OK |
|---:|---|---|---|---:|---:|---:|---:|---:|---:|---|
| 1 | Fundamentals Analyst | anthropic/claude-sonnet-5-5 | tool round | 5 | 5 | 1967 | 329 | $0.0072 | 3.1s | yes |
| 2 | Technical Analyst | anthropic/claude-sonnet-5-5 | tool round | 3 | 1 | 3009 | 85 | $0.0069 | 2.1s | yes |
| 3 | News Analyst | anthropic/claude-sonnet-5-5 | tool round | 4 | 10 | 2598 | 859 | $0.0138 | 5.3s | yes |
| 4 | Sentiment Analyst | anthropic/claude-sonnet-5-5 | structured (function_calling) | 1 | 1 | 4397 | 2411 | $0.0329 | 18.7s | yes |
| 5 | Technical Analyst | anthropic/claude-sonnet-5-5 | tool round | 3 | 9 | 12020 | 929 | $0.0333 | 4.8s | yes |
| 6 | Fundamentals Analyst | anthropic/claude-sonnet-5-5 | text | 5 | 0 | 7538 | 7504 | $0.0901 | 54.6s | yes |
| 7 | News Analyst | anthropic/claude-sonnet-5-5 | tool round | 4 | 2 | 5959 | 222 | $0.0141 | 2.4s | yes |
| 8 | Technical Analyst | anthropic/claude-sonnet-5-5 | text | 3 | 0 | 19779 | 3333 | $0.0729 | 25.5s | yes |
| 9 | News Analyst | anthropic/claude-sonnet-5-5 | text | 4 | 0 | 10035 | 2198 | $0.0420 | 18.2s | yes |
| 10 | Bull Researcher | anthropic/claude-sonnet-5-5 | text | 0 | 0 | 12323 | 3231 | $0.0570 | 26.5s | yes |
| 11 | Bear Researcher | anthropic/claude-sonnet-5-5 | text **hit output cap** | 0 | 0 | 17370 | 8192 | $0.1167 | 70.7s | yes |
| 12 | Research Manager | anthropic/claude-sonnet-5-5 | structured (function_calling) | 1 | 1 | 5835 | 1727 | $0.0289 | 14.2s | yes |
| 13 | Trader | anthropic/claude-sonnet-5-5 | structured (function_calling) | 1 | 1 | 6502 | 590 | $0.0189 | 5.2s | yes |
| 14 | Aggressive Risk Analyst | anthropic/claude-sonnet-5-5 | text | 0 | 0 | 13052 | 2576 | $0.0519 | 23.5s | yes |
| 15 | Conservative Risk Analyst | anthropic/claude-sonnet-5-5 | text | 0 | 0 | 16282 | 5166 | $0.0842 | 45.0s | yes |
| 16 | Neutral Risk Analyst | anthropic/claude-sonnet-5-5 | text | 0 | 0 | 20028 | 5224 | $0.0923 | 45.1s | yes |
| 17 | Portfolio Manager | anthropic/claude-sonnet-5-5 | structured (function_calling) | 1 | 1 | 8978 | 1928 | $0.0372 | 15.4s | yes |

## Data quality

- 1 call(s) reached the 8192-token output cap and were probably truncated: Bear Researcher.

## Structured-output fallbacks

Each fallback is a structured call that did not parse, retried by upstream as a second, free-text call. Counted two independent ways: from upstream's own warnings (below) and from the call records (the Fallbacks column above: 0).

None: every structured call parsed on the first attempt.

## Budget stops

None.

## Notes

- Costs are estimates from `sid_trading_firm/config/pricing.yaml` and provider-reported tokens.
- Upstream has two model tiers. Agents SID maps to FAST (sentiment, reflection) ran on the STANDARD model here.
- One sample: LLM output varies between runs, so treat these figures as one observation.
