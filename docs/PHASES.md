# Phase gate records

Gate records per `docs/GOVERNANCE.md` section 21. A record states evidence; it does not by
itself authorise the next phase. Work merged under delegated authority (section 26) is
**not independently reviewed by Codex** until the consolidated review after Phase 3.

---

## Phase 0: Repository audit

| Field | Record |
|---|---|
| Phase | 0, repository audit |
| Approved scope and acceptance criteria | Audit TradingAgents v0.6.0: architecture, agents, data, providers, tests, backtesting, memory, risk, persistence, gaps; propose architecture and Phase 1 plan. No code changes. |
| Repository / reviewed commit | `siddharthatirumala/TradingAgents` at upstream `1394a3f` (v0.6.0) |
| Tests and CI evidence | Upstream suite run locally: 1258 passed, 4 skipped, 1 Windows-only failure |
| Security and cost evidence | None incurred |
| Known issues | Recorded in the audit (LLM future-knowledge contamination of historical runs; non point-in-time text feeds; fail-open fallbacks upstream) |
| Rollback or recovery | Not applicable (no changes) |
| Codex decision and reasons | Audit reviewed by the owner; decisions recorded in `docs/sid_trading_firm/decisions.md` (D1-D8) |
| Owner authorisation | Owner approved Phase 1A on 2026-10-04 |
| Next phase and exact authorised scope | Phase 1A foundation (P1.1-P1.6) |

---

## Phase 1A: Engineering foundation

| Field | Record |
|---|---|
| Phase | 1A, engineering foundation |
| Approved scope and acceptance criteria | SID package separation; typed configuration; run_id and structured logging; FAST/STANDARD/DEEP model tiers; LLM usage ledger and fail-closed budget guard; PostgreSQL with migrations; deterministic quant library; typed contracts; baseline engineering measurement; Sonnet 5.5 structured-output compatibility. No broker, no live trading. |
| Repository / PR links | PRs [#1](https://github.com/siddharthatirumala/TradingAgents/pull/1)-[#9](https://github.com/siddharthatirumala/TradingAgents/pull/9) (foundation), [#10](https://github.com/siddharthatirumala/TradingAgents/pull/10) (governance: delegated merge authority), and this gate-record PR |
| Merge commits on `main` | #1 `b0320c9`, #2 `35dd01b`, #3 `3b42234`, owner governance commits `08a643e` `5307185`, #4 `059b9ff`, #10 `e09d8e4`, #5 `4ab215f`, #6 `0b79489`, #7 `1d02032`, #8 `20d788e`, #9 `a66753d` |
| Reviewed commit | `a66753d` (final Phase 1A code on `main`) |
| Tests and CI evidence | Every PR: CI on its exact head commit (upstream suite on Python 3.11, 3.12 New York, 3.13, 3.14; ruff; clean install; SID suite on 3.11 and 3.13; PostgreSQL 17 integration; PR-scoped gitleaks), and CI on `main` after each merge of #5-#10, all green. Final `main` locally: upstream 1258 passed / 4 skipped / 1 failed (recorded Windows exception, accepted by the checker), SID 323 passed, ruff clean, migrations upgrade/downgrade/upgrade OK, clean non-editable install of `.[sid]` with `pip check` clean. Logs: `docs/sid_trading_firm/merge-recovery/logs/`. |
| Security and cost evidence | No credential-shaped strings in the tree or in lines added by the 27 Phase 1A commits; `.env` ignored and untracked; PR-scoped gitleaks green on every PR. PR #5 persistence redaction corrected twice after Codex review (`e0e485b`, `c783be7`). Paid API cost: two baseline runs, $0.8004 + $0.7247 = $1.53 (`docs/sid_trading_firm/baselines/`). |
| Known issues, exceptions, owners and expiry | (1) Windows exception `WIN-YF-CACHE-UNDER-HOME`, (2) Windows exception `WIN-MEMLOG-CONCURRENT-PERMERROR13`: both owner-approved, owner siddharthatirumala, expire 2026-10-31 or at this gate (proposed; owner to confirm), Linux CI must pass both (`docs/sid_trading_firm/merge-recovery/windows_exceptions.json`). (3) Unexplained intermittent `tests/test_backtest.py::test_a_bullish_call_is_scored_the_same_way_as_before` on Windows (2 in about 145 runs, signature not captured): **not exempted**, a blocker if it recurs. (4) Known upstream repository finding: full-history gitleaks flags two fake test credentials in upstream commit `b20c8e6` (`AVKEY1234567890XYZ`, `abcdef0123456789abcdef0123456789`); accepted by the owner as pre-existing false positives; handled separately as repository hardening. (5) Baseline is all-Sonnet through upstream's two-tier graph, not the planned FAST/STANDARD/DEEP routing; about $0.72-$0.80 per analysis in two runs; not a production estimate. |
| Rollback or recovery | Each PR is a merge commit and can be reverted individually (`git revert -m 1 <merge>`); schema: `python -m sid_trading_firm.persistence.migrate downgrade base`. The 2026-10-04 merge incident (PR #2 closed by branch deletion, governance commits landing mid-sequence) was recovered without history rewrite; procedure and evidence in `docs/sid_trading_firm/merge-recovery/`. |
| Codex decision and reasons | Codex reviewed PR #5 twice (CHANGE REQUIRED: unredacted persisted diagnostics; then quoted credentials); both corrected before merge. Final Phase 1A decision: **pending consolidated review** (section 26). PRs #5-#10 were merged under delegated authority and are not independently reviewed by Codex. |
| Owner authorisation | Phase 1A approved for merge by the owner (2026-10-04); delegated merge authority for remaining Phase 1A, Phase 2 and Phase 3 (2026-10-05, `docs/GOVERNANCE.md` section 26). |
| Next phase and exact authorised scope | Phase 2, deterministic strategy backtesting, under section 26. Phase 1B remains unauthorised. No paid API runs, cloud spending, broker or real money. |
