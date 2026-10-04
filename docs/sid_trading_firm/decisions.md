# Architecture decisions

Approved 2026-10-04 after the Phase 0 audit. Each entry records the decision
and the reason; change one only with a new entry that says why.

## D1. Names and separation
- Display name **SID Trading Firm**; Python package `sid_trading_firm`.
- The GitHub repository keeps its fork name for now, so the fork relationship
  with upstream stays simple.
- Upstream code (`tradingagents/`, `cli/`, `tests/`) stays as close to upstream
  as practical. Our code lives in `sid_trading_firm/` and `tests_sid/`, and
  extends upstream by composition. Upstream never imports our package (tested).

## D2. Database
- PostgreSQL from Phase 1, local development through Docker Compose.
- SQLite only for isolated unit tests.
- All access goes through SQLAlchemy with a configured connection URL; nothing
  depends on a hosting provider.
- Before cloud deployment, compare Fly.io, Azure Database for PostgreSQL, Neon,
  Supabase and others on reliability, backup and recovery, cost, connection
  limits, workload fit and scaling. Phase 0 research (2026-10-04): Fly.io Managed
  Postgres starts at $38/month; Neon's free tier scales to zero.

## D3. Model strategy
- Three logical tiers, each with its own provider and model, set in config:
  - **FAST**: OpenAI GPT-6 Luna. Extraction, preprocessing, summaries, classification.
  - **STANDARD**: Claude Sonnet 5.5. Analyst reasoning, bull/bear research.
  - **DEEP**: Claude Sonnet 5.5 (or GPT-6 Sol). Research Manager, Portfolio Manager, CIO.
- Each agent maps to a tier in config; business logic never names a provider.
- Measure before optimising: a baseline run is metered per agent first.
- Later, benchmark Sonnet 5.5, Opus 5.5, GPT-6 Sol and others on the same stored
  research cases (quality, consistency, structured-output reliability, error rate,
  latency, cost per decision). Model diversity across stages is a later option.

## D4. Market scope
- Phase 1: US-listed common stocks. ETFs only as benchmarks and regime/sector
  context. No crypto, forex, options or futures.
- The design must not prevent adding markets later (UK equities first candidate).

## D5. Upstream TradingAgents
- Pinned to a known-good release (`sid_trading_firm/upstream.py`, currently v0.6.0).
- The `upstream` remote stays configured; a weekly workflow opens an issue when
  a newer upstream release exists.
- Syncing is a dedicated branch and PR, reviewed, with both suites green; the pin
  moves in the same PR. Never merged automatically.

## D6. Frameworks
- No Qlib, FinRL, LEAN or FinRobot at this stage. Add a framework only when it
  solves a specific problem materially better than a small implementation.

## D7. Execution and hardware
- No broker integration yet; no live trading ever without a future, deliberate decision.
- Hosted model APIs only. The development laptop runs Python, Docker, a local
  database, orchestration and tests; no GPU or local LLM.

## D8. Workflow
- No direct pushes to `main`. One branch and one small PR per logical change,
  each described with: purpose, changes, architecture, files, testing, security,
  cost, technical debt and next step. PRs are merged by the owner, never silently.
