# UPSTREAM ALL-SONNET BASELINE (AFTER PR #9): NVDA on 2026-10-02

Measures what one normal upstream TradingAgents analysis costs. It does not evaluate the investment decision.

> Inherited upstream behaviour: upstream's graph has two model tiers, so every agent here runs on the same model. This is NOT the planned FAST/STANDARD/DEEP mixed-model design, and one run is one sample: do not derive production budgets from it.

| | |
|---|---|
| Run id | `c15b5e77-9b8d-4b56-b58a-0e9479940fa6` |
| Status | **completed** |
| Upstream decision | Overweight |
| Analysts | market, social, news, fundamentals |
| Models | upstream quick tier = anthropic/claude-sonnet-5-5; deep tier = anthropic/claude-sonnet-5-5 |
| Output cap | 8192 tokens per call |
| Budget | $3 per run, $10.0 per day, 300,000 tokens and 12 calls per agent |
| Rounds | debate 1, risk 1, analyst tool rounds 11 |
| Wall time | 278s |
| Total | **16 calls, 154,873 input + 41,494 output tokens, $0.7247** |
| Tool rounds | 4 |
| Structured calls | 4, of which failed and retried as free text: **0** (fallback cost $0.0000) |
| Output cap reached | 0 call(s) |
| Budget guard | consulted for 16 calls; stops: 0; run spend $0.7247 of $3 cap |

## Cost by agent

| Agent | Stage | Calls | Tool rounds | Structured | Fallbacks | Input tok | Output tok | Total tok | Cost | Total latency | Slowest call |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| Technical Analyst | Analysts | 3 | 2 | 0 | 0 | 33,124 | 4,087 | 37,211 | $0.1071 | 31.9s | 25.1s |
| Fundamentals Analyst | Analysts | 2 | 1 | 0 | 0 | 9,505 | 6,923 | 16,428 | $0.0882 | 49.7s | 46.5s |
| News Analyst | Analysts | 2 | 1 | 0 | 0 | 8,579 | 3,114 | 11,693 | $0.0483 | 24.1s | 18.5s |
| Sentiment Analyst | Analysts | 1 | 0 | 1 | 0 | 4,396 | 3,457 | 7,853 | $0.0434 | 26.5s | 26.5s |
| Bear Researcher | Research debate | 1 | 0 | 0 | 0 | 16,869 | 7,908 | 24,777 | $0.1128 | 69.5s | 69.5s |
| Bull Researcher | Research debate | 1 | 0 | 0 | 0 | 12,578 | 2,994 | 15,572 | $0.0551 | 27.1s | 27.1s |
| Research Manager | Research debate | 1 | 0 | 1 | 0 | 5,835 | 1,329 | 7,164 | $0.0250 | 12.4s | 12.4s |
| Neutral Risk Analyst | Decision | 1 | 0 | 0 | 0 | 19,922 | 3,659 | 23,581 | $0.0764 | 32.0s | 32.0s |
| Conservative Risk Analyst | Decision | 1 | 0 | 0 | 0 | 16,196 | 3,955 | 20,151 | $0.0719 | 35.7s | 35.7s |
| Aggressive Risk Analyst | Decision | 1 | 0 | 0 | 0 | 13,252 | 2,296 | 15,548 | $0.0495 | 19.3s | 19.3s |
| Portfolio Manager | Decision | 1 | 0 | 1 | 0 | 8,422 | 1,342 | 9,764 | $0.0303 | 11.1s | 11.1s |
| Trader | Decision | 1 | 0 | 1 | 0 | 6,195 | 430 | 6,625 | $0.0167 | 5.4s | 5.4s |
| **Total run** | | **16** | 4 | 4 | **0** | **154,873** | **41,494** | **196,367** | **$0.7247** | 344.8s | 69.5s |

## Cost by stage

| Stage | Calls | Cost | Share |
|---|---:|---:|---:|
| Analysts | 8 | $0.2870 | 40% |
| Research debate | 3 | $0.1929 | 27% |
| Decision | 5 | $0.2448 | 34% |

## Cost by model

| Model | Calls | Input tok | Output tok | Cost |
|---|---:|---:|---:|---:|
| anthropic/claude-sonnet-5-5 | 16 | 154,873 | 41,494 | $0.7247 |

## Longest calls (top 5)

| Agent | Model | Latency | Input tok | Output tok |
|---|---|---:|---:|---:|
| Bear Researcher | claude-sonnet-5-5 | 69.5s | 16869 | 7908 |
| Fundamentals Analyst | claude-sonnet-5-5 | 46.5s | 7538 | 6594 |
| Conservative Risk Analyst | claude-sonnet-5-5 | 35.7s | 16196 | 3955 |
| Neutral Risk Analyst | claude-sonnet-5-5 | 32.0s | 19922 | 3659 |
| Bull Researcher | claude-sonnet-5-5 | 27.1s | 12578 | 2994 |

## Largest prompts (top 5)

| Agent | Input tok | Prompt chars | Cost |
|---|---:|---:|---:|
| Neutral Risk Analyst | 19922 | 53,071 | $0.0764 |
| Technical Analyst | 16965 | 29,586 | $0.0660 |
| Bear Researcher | 16869 | 43,463 | $0.1128 |
| Conservative Risk Analyst | 16196 | 41,793 | $0.0719 |
| Aggressive Risk Analyst | 13252 | 33,414 | $0.0495 |

## Every call

| # | Agent | Provider / model | Kind | Tools offered | Tool calls | Input tok | Output tok | Cost | Latency | OK |
|---:|---|---|---|---:|---:|---:|---:|---:|---:|---|
| 1 | Technical Analyst | anthropic/claude-sonnet-5-5 | tool round | 3 | 2 | 3009 | 170 | $0.0077 | 2.5s | yes |
| 2 | Fundamentals Analyst | anthropic/claude-sonnet-5-5 | tool round | 5 | 5 | 1967 | 329 | $0.0072 | 3.2s | yes |
| 3 | News Analyst | anthropic/claude-sonnet-5-5 | tool round | 4 | 10 | 2598 | 881 | $0.0140 | 5.6s | yes |
| 4 | Sentiment Analyst | anthropic/claude-sonnet-5-5 | structured (json_schema) | 0 | 0 | 4396 | 3457 | $0.0434 | 26.5s | yes |
| 5 | Technical Analyst | anthropic/claude-sonnet-5-5 | tool round | 3 | 6 | 13150 | 707 | $0.0334 | 4.3s | yes |
| 6 | News Analyst | anthropic/claude-sonnet-5-5 | text | 4 | 0 | 5981 | 2233 | $0.0343 | 18.5s | yes |
| 7 | Technical Analyst | anthropic/claude-sonnet-5-5 | text | 3 | 0 | 16965 | 3210 | $0.0660 | 25.1s | yes |
| 8 | Fundamentals Analyst | anthropic/claude-sonnet-5-5 | text | 5 | 0 | 7538 | 6594 | $0.0810 | 46.5s | yes |
| 9 | Bull Researcher | anthropic/claude-sonnet-5-5 | text | 0 | 0 | 12578 | 2994 | $0.0551 | 27.1s | yes |
| 10 | Bear Researcher | anthropic/claude-sonnet-5-5 | text | 0 | 0 | 16869 | 7908 | $0.1128 | 69.5s | yes |
| 11 | Research Manager | anthropic/claude-sonnet-5-5 | structured (json_schema) | 0 | 0 | 5835 | 1329 | $0.0250 | 12.4s | yes |
| 12 | Trader | anthropic/claude-sonnet-5-5 | structured (json_schema) | 0 | 0 | 6195 | 430 | $0.0167 | 5.4s | yes |
| 13 | Aggressive Risk Analyst | anthropic/claude-sonnet-5-5 | text | 0 | 0 | 13252 | 2296 | $0.0495 | 19.3s | yes |
| 14 | Conservative Risk Analyst | anthropic/claude-sonnet-5-5 | text | 0 | 0 | 16196 | 3955 | $0.0719 | 35.7s | yes |
| 15 | Neutral Risk Analyst | anthropic/claude-sonnet-5-5 | text | 0 | 0 | 19922 | 3659 | $0.0764 | 32.0s | yes |
| 16 | Portfolio Manager | anthropic/claude-sonnet-5-5 | structured (json_schema) | 0 | 0 | 8422 | 1342 | $0.0303 | 11.1s | yes |

## Structured-output fallbacks

Each fallback is a structured call that did not parse, retried by upstream as a second, free-text call. Counted two independent ways: from upstream's own warnings (below) and from the call records (the Fallbacks column above: 0).

None: every structured call parsed on the first attempt.

## Budget stops

None.

## Notes

- Costs are estimates from `sid_trading_firm/config/pricing.yaml` and provider-reported tokens.
- Upstream has two model tiers. Agents SID maps to FAST (sentiment, reflection) ran on the STANDARD model here.
- One sample: LLM output varies between runs, so treat these figures as one observation.
