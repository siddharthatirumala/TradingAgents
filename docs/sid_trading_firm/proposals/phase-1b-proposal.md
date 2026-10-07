# Phase 1B proposal: controlled research organisation

**Status: PROPOSAL FOR OWNER AND CODEX REVIEW. NOT AUTHORISED.** Nothing in this document
starts Phase 1B. No implementation, paid AI call, broker connection or cloud deployment
follows from it until the owner records an explicit authorisation and Codex approves the
scope. The project remains research and backtesting only.

Baseline: `main` `56b8d67` (Phases 1A, 2 and 3 closed; `docs/PHASES.md`). Governance:
`docs/GOVERNANCE.md` sections 5 (Phase 1B), 7-13, 21 and 22.

---

## 1. Purpose

Turn the upstream TradingAgents graph into a controlled research organisation whose output
is a **validated, evidence-referenced, persisted research decision** per candidate symbol.
Every number it relies on comes from deterministic code, every claim cites stored evidence,
every input is a dated snapshot, every model call is metered and capped, and a deterministic
hard-risk engine has the last word on whether a decision could ever become a trade proposal.

Phase 1B does **not** place, simulate or route orders. Its decisions are research records.
Paper trading is Phase 4 and stays unauthorised.

## 2. Scope

**In scope** (each item one or more small PRs, merged only with per-PR owner approval
unless the owner records a delegation):

1. **Data snapshot**: a frozen, fingerprinted bundle per run and symbol (prices,
   fundamentals, news items, macro series) with source and retrieval timestamps; agents read
   the snapshot, never the live vendors.
2. **Freshness validation**: deterministic checks on every snapshot component before any AI
   work starts (section 5).
3. **Evidence registry**: every snapshot item and every deterministic calculation becomes an
   Evidence record with an id; claims must cite ids that exist in the run (section 6).
4. **Per-agent model routing**: agents get the tier assigned in configuration
   (FAST/STANDARD/DEEP), through the existing ledger and budget guard (section 7).
5. **Structured analysts**: technical, fundamentals, news and sentiment analysts emit the
   existing typed contracts (`sid_trading_firm/contracts`) with native structured output;
   invalid output fails the run step, never passes silently.
6. **Quantitative validator**: deterministic metrics (quant library and Phase 2 backtests
   of a candidate's reference strategy) delivered as `QuantValidation`; the LLM may only
   interpret them.
7. **Macro and market-regime analysts**: only if they pass the section 7 GOVERNANCE test
   (unique information, decision influence, measurable benefit, cost); otherwise dropped.
8. **Structured risk reviewer, portfolio manager and CIO**: `RiskReview`, `PortfolioFit`,
   `CIODecision`, preserving supporting and dissenting evidence and unresolved questions.
9. **Deterministic hard-risk engine**: no LLM dependency; evaluates every CIO decision
   against owner-approved limits and returns approve/reject with reasons (section 8).
10. **Decision persistence**: every artefact of a run stored and traceable by `run_id`
    (section 9).
11. **Candidate intake** from the Phase 3 screen: at most the screen's budget-bounded
    candidate list.

**Out of scope** (unchanged prohibitions): order placement or simulation of fills from AI
decisions, any broker or paper-broker connection, live trading, cloud deployment,
organisational memory (Phase 5), autonomous scheduling of runs, leverage, options, futures,
crypto, forex, non-US instruments, and AI-generated financial numbers where deterministic
computation is practical.

**Evaluation boundary.** AI decisions are evaluated **forward only** (dates after the run).
An LLM analysis of a past date is not a clean experiment and is never used as evidence of
an edge; historical evaluation stays with the Phase 2 backtester.

## 3. Acceptance criteria (Phase 1B gate)

Matching GOVERNANCE section 21 ("1B: evidence references and structured outputs validated;
stale/missing/invalid data and risk violations rejected; decisions persisted and traceable"):

1. A run on a candidate produces a persisted `CIODecision` and a hard-risk verdict, or a
   persisted refusal with a reason, for every candidate; nothing is dropped silently.
2. Every claim in every persisted decision references evidence ids that exist in that run's
   registry; a reference to a missing id fails validation (tested).
3. Every agent output validates against its contract; invalid structured output fails that
   step and is recorded (the existing `invoke_structured` makes one call and raises; no
   silent fallback to free text).
4. Stale, missing or invalid snapshot data stops the run for that symbol before any paid
   call (tested per component).
5. The hard-risk engine rejects when any limit is missing, malformed or unapproved, when any
   input is non-finite or stale, and when any policy limit is breached; it has no LLM import
   (AST test) and no override path.
6. Every model call is in the ledger with run, agent, provider, model, tokens, latency, cost
   and outcome; no call exceeds the per-run, per-day or per-agent caps; budget exhaustion
   stops new AI work without disabling risk evaluation or persistence (tested).
7. A full decision can be reconstructed from the database alone (snapshot fingerprint,
   evidence, every agent output, risk verdict, policy version, costs).
8. All tests use mocked models; the owner-authorised measurement runs (section 10) are
   recorded with costs.
9. CI green on every PR head and on `main` after every merge; PostgreSQL integration covers
   the new tables; gitleaks clean.

## 4. Data snapshots

- **Unit**: one snapshot per (run, symbol), created before any AI call, immutable after
  creation, stored with a content fingerprint (same hashing approach as Phase 2's
  `PricePanel.fingerprint`).
- **Contents**: daily OHLCV (Phase 2 data layer), fundamentals as reported with their
  filing/period dates, news items with publication timestamps and source, macro series with
  release dates. Each item records vendor, retrieval time and the as-of time it represents.
- **As-of rule**: a snapshot has one `as_of` timestamp; any item dated after it is excluded
  (point-in-time), and items without a trustworthy timestamp are excluded and counted.
- **Size bound**: news items per symbol capped by `MAX_NEWS_ITEMS_PER_INSTRUMENT` (new
  setting, owner-set) to bound tokens.
- **Known limitation**: some upstream news and social feeds are not historically
  point-in-time; that is acceptable only because Phase 1B runs are forward-dated (section 2).

## 5. Freshness rules

Deterministic, evaluated before any paid call; failure stops AI work for that symbol and is
persisted with the reason.

| Component | Rule (thresholds owner-approved; no defaults supplied here) |
|---|---|
| Prices | last bar no older than the configured maximum age in trading days relative to `as_of`; no gaps filled; validation as in the Phase 2 data layer |
| Fundamentals | latest filing period within the configured maximum age; missing required fields refuse the fundamentals analyst |
| News | at least the configured minimum number of items within the configured window, or the news analyst is skipped and the gap is recorded (never invented) |
| Macro | each required series' latest release within its configured maximum age |
| Snapshot as a whole | `as_of` not in the future; vendor errors and partial downloads refuse the snapshot |

`risk.max_data_age_seconds` (already present, unset) applies to the hard-risk engine's own
inputs and must also be set before any decision can pass it.

## 6. Evidence

- Evidence records follow GOVERNANCE section 9 (id, source, timestamp, category, value or
  quote, instrument, as-of) and are created by deterministic code from snapshot items and
  quant results; agents cannot create evidence.
- The existing `Claim` contract already requires at least one evidence id; Phase 1B adds
  run-level validation that every cited id exists in the run's registry and belongs to the
  same instrument and snapshot.
- Quotes from news are stored verbatim with source; LLM paraphrases are claims, not evidence.
- Dissenting evidence and unresolved questions are kept in `CIODecision` and never collapsed
  into a vote; agents on the same provider are not treated as independent (section 8).

## 7. Model routing

- Tiers and per-agent assignments stay in configuration (`sid_trading_firm/config`), routed
  through the existing ledger, budget guard and native structured output (Phase 1A).
- Current configured assignments are placeholders: FAST `openai/gpt-6-luna`; STANDARD and
  DEEP `anthropic/claude-sonnet-5-5`. Provider model ids and prices must be re-verified
  before any paid run; unpriced models stay refused (`allow_unpriced_models: false`).
- Routing changes are configuration PRs with a cost estimate, not code changes.
- Model choices are confirmed by the benchmarking procedure in GOVERNANCE section 12 on
  stored cases (validity, consistency, evidence use, hallucination, latency, cost), never by
  recency or price.

## 8. Hard-risk limits

- **Values**: the owner supplies every numeric limit; this proposal sets none (GOVERNANCE
  section 22). Existing unset placeholders: `max_position_pct`, `max_daily_loss_pct`,
  `max_drawdown_pct`, `max_sector_exposure_pct`, `max_open_positions`, `max_trades_per_day`,
  `min_avg_daily_volume`, `max_data_age_seconds`. Phase 1B adds, still unset: allowed
  instrument list (US common stocks from an approved universe), maximum order notional, and a
  policy version identifier.
- **Behaviour**: any limit missing, malformed or unapproved rejects every decision;
  non-finite values, invalid prices, stale inputs and unavailable required calculations
  reject; every verdict records inputs, policy version and each rejection reason.
- **Authority**: AI approval is advisory; the hard-risk verdict is mandatory. There is no
  override route and no LLM dependency (AST test). In Phase 1B the engine evaluates research
  decisions only; the final order-boundary re-validation of section 22 belongs to Phase 4.

## 9. Decision persistence

New tables keyed by `run_id` (migrations 0006 onwards, each reversible):

| Table | Holds |
|---|---|
| `data_snapshots` | run, symbol, as_of, fingerprint, per-component freshness result, vendor and retrieval metadata |
| `evidence` | id, run, snapshot, category, source, timestamp, as_of, instrument, value or quote |
| `agent_outputs` | run, agent, contract type, validated payload (JSON), validation status, ledger call ids |
| `research_decisions` | run, symbol, CIO action, confidence, supporting and dissenting claim ids, status |
| `risk_verdicts` | decision, policy version, approved flag, each rejection reason, input values |

Free text and payloads pass through the existing credential sanitiser; rows are never
updated after the run completes (append-only), and every decision links back to its
snapshot, evidence, outputs, ledger rows and verdict.

## 10. Cost limits

- Existing caps remain enforced before every call: per run (currently $3.00), per day
  ($10.00), tokens per agent (300 000), agent iterations (12), debate rounds (1), risk rounds
  (1), candidates per run (5). These are placeholders and need owner confirmation before any
  paid run; a new `MAX_NEWS_ITEMS_PER_INSTRUMENT` is added unset.
- Reference: the Phase 1A all-Sonnet baselines cost about $0.72-$0.80 per full analysis
  (engineering measurement, not a production estimate).
- **No paid AI call in development or CI**: all tests use mocked models.
- **Measurement runs** (to calibrate routing and caps) only under a separate, explicit owner
  authorisation stating symbols, number of runs and a hard spend ceiling; each run's ledger
  report is committed as evidence. Proposed first ceiling for owner decision: a small number
  of single-symbol runs within the existing per-run cap.
- Budget exhaustion stops new AI work and records the stop; it never disables freshness
  checks, the hard-risk engine or persistence.

## 11. Tests

- Unit (mocked models, SQLite) and integration (PostgreSQL in CI) for every PR.
- Required cases: snapshot immutability and fingerprint; each freshness rule failing closed;
  evidence references to missing or foreign ids rejected; every contract's invalid-output
  path; routing uses configured tiers and refuses unpriced models; each budget cap stops work
  at the right point; hard-risk engine rejects each missing limit, each breach, non-finite and
  stale inputs, with no LLM imports and no override; end-to-end mocked run persisting a
  complete, reconstructable decision; migrations upgrade, downgrade and schema equality on
  PostgreSQL.
- Existing suites stay green; no test makes network or paid calls.
- Windows local-test limitation unchanged: upstream-suite evidence comes from Linux CI;
  no exception created or extended.

## 12. Rollback

- Every PR is a merge commit and can be reverted individually (`git revert -m 1`).
- Every migration has a tested downgrade; schema rollback by
  `python -m sid_trading_firm.persistence.migrate downgrade <revision>`.
- Phase 1B code paths are only reachable through an explicit research command; with them
  reverted or unused, Phases 1A-3 behave as today.

## 13. Shutdown

- **Configuration switch**: a `research.enabled` setting, default false; when false every
  Phase 1B entry point refuses to start.
- **Budget stop**: lowering the per-run or per-day cap to the minimum stops further calls at
  the next pre-call check; in-flight runs end at their next call and record the stop.
- **Key removal**: unsetting provider API keys makes every model call fail (keys are read
  from the environment, never stored by the project).
- **No scheduler**: runs start only when a person starts them, so there is nothing to
  disable remotely.
- Shutdown never deletes data: snapshots, evidence, decisions, verdicts and ledger rows stay
  for audit.

## 14. Proposed PR sequence (for review, not authorised)

1. `research.enabled` switch, new unset settings and their validation.
2. Data snapshot model, builder and migration.
3. Freshness validator.
4. Evidence registry and run-level reference validation.
5. Hard-risk engine (deterministic, limits unset means reject everything).
6. Decision persistence tables and repository.
7. Structured analysts on the existing contracts (one PR per analyst or pair).
8. Quantitative validator.
9. Risk reviewer, portfolio manager and CIO with dissent preserved.
10. End-to-end mocked research run and report.
11. Phase 1B gate record.

## 15. Decisions requested from the owner

1. Authorise Phase 1B at all, and on what scope (all of section 2, or a subset).
2. Merge cadence: per-PR owner approval, or a new recorded delegation.
3. Every numeric hard-risk limit and the allowed-instrument list (section 8).
4. Freshness thresholds (section 5) and `MAX_NEWS_ITEMS_PER_INSTRUMENT`.
5. Confirmation or change of the budget caps (section 10) and of model routing (section 7).
6. Whether, when and within what ceiling any paid measurement run may happen.
7. Whether the macro and market-regime analysts are included before they are benchmarked.
