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
| Codex decision and reasons | Codex reviewed PR #5 twice (CHANGE REQUIRED: unredacted persisted diagnostics; then quoted credentials); both corrected before merge. PRs #5-#10 were merged under delegated authority and reviewed afterwards in the consolidated review. Final Phase 1A decision: **APPROVE (technical)**, recorded 2026-10-05 after remediation: the consolidated review of the section 26 work returned CHANGE REQUIRED; remediation PRs #27-#31 were reviewed and approved by Codex and merged by explicit owner instruction; final `main` `69c3ab5` (see Gate closure below). |
| Owner authorisation | Phase 1A approved for merge by the owner (2026-10-04); delegated merge authority for remaining Phase 1A, Phase 2 and Phase 3 (2026-10-05, `docs/GOVERNANCE.md` section 26). |
| Next phase and exact authorised scope | Phase 2, deterministic strategy backtesting, under section 26. Phase 1B remains unauthorised. No paid API runs, cloud spending, broker or real money. |

---

## Phase 2: Deterministic strategy backtesting

| Field | Record |
|---|---|
| Phase | 2, deterministic strategy backtesting |
| Approved scope and acceptance criteria | Point-in-time price data; daily simulator (decide at close, fill at next open, costs and slippage, cash and weight limits, long-only, no leverage); deterministic performance metrics with explicit undefined states; chronological train/validation/test and walk-forward without leakage; versioned strategies with the section 15 lifecycle; persistence of strategy versions and results; a reproducible runner whose report states its assumptions. No AI in historical evaluation, no broker, no paper or live trading. |
| Repository / PR links | [#12](https://github.com/siddharthatirumala/TradingAgents/pull/12) data, [#13](https://github.com/siddharthatirumala/TradingAgents/pull/13) simulator, [#14](https://github.com/siddharthatirumala/TradingAgents/pull/14) metrics, [#15](https://github.com/siddharthatirumala/TradingAgents/pull/15) splits and walk-forward, [#16](https://github.com/siddharthatirumala/TradingAgents/pull/16) strategies, [#17](https://github.com/siddharthatirumala/TradingAgents/pull/17) persistence, [#18](https://github.com/siddharthatirumala/TradingAgents/pull/18) runner, and this gate-record PR. Phase 1A gate record: [#11](https://github.com/siddharthatirumala/TradingAgents/pull/11) (`de36afd`). |
| Merge commits on `main` | #12 `27969b1`, #13 `dc93133`, #14 `e6bb9e6`, #15 `2f1de8d`, #16 `46ca48a`, #17 `9058caf`, #18 `87936cf` |
| Reviewed commit | `87936cf` (final Phase 2 code on `main`) |
| Tests and CI evidence | Each PR merged by `merge_pr.sh`: head and commits as expected, GitHub Files Changed equal to the PR's own patch, merged tree equal to main plus the patch, local upstream suite through the exception checker (only the recorded Windows exception), SID suite, migrations upgrade/downgrade/upgrade, ruff, both CI workflows green on the exact head (including PostgreSQL 17 integration and PR-scoped gitleaks), merge commit, both workflows green on `main`. SID unit suite grew from 323 to 417 tests; Phase 2 integration tests run against PostgreSQL in CI. Logs: `docs/sid_trading_firm/evidence/phase2/merge_pr12.txt` to `merge_pr18.txt`. |
| Security and cost evidence | Phase 2 diff (`de36afd..87936cf`): 24 files, all under `sid_trading_firm/`, `tests_sid/` and `docs/`; no upstream file changed; no credential-shaped strings in added lines; gitleaks green on every PR. New free-text and configuration columns pass through the credential sanitiser (tested on SQLite and PostgreSQL). Paid API cost: **none**. One pipeline smoke test of the example specification used free Yahoo data (no AI): `docs/sid_trading_firm/evidence/phase2/smoke_backtest_report.md`, labelled as not evidence of an edge. |
| Known issues, exceptions, owners and expiry | (1) Phase 1A Windows exceptions unchanged (expire 2026-10-31, proposed). (2) Unexempted intermittent upstream `tests/test_backtest.py` failure: did not recur in the seven Phase 2 merges. (3) Limitations stated in every report: adjusted prices, survivorship bias of a today's-symbols list, assumed costs, unsold positions at period end valued at the close, each walk-forward test window starting from cash. (4) A strategy with a long lookback spends its first period in cash (warm-up), which lowers train-segment figures; visible in the smoke test (199 days of zero return in the train segment). (5) Walk-forward ignores trailing days that cannot fill a whole test window. (6) Report formatting: counts print with decimals; regimes print as raw JSON; the stitched out-of-sample record has no benchmark comparison. (7) No volume or liquidity limit on simulated fills. |
| Rollback or recovery | Revert merge commits individually (`git revert -m 1`); schema: `python -m sid_trading_firm.persistence.migrate downgrade 0002_llm_usage_call_details` removes `strategy_versions` and `backtest_results`. |
| Codex decision and reasons | **APPROVE (technical)**, recorded 2026-10-05 after remediation: the consolidated review of the section 26 work returned CHANGE REQUIRED; remediation PRs #27-#31 were reviewed and approved by Codex and merged by explicit owner instruction; final `main` `69c3ab5` (see Gate closure below). |
| Owner authorisation | Delegated merge authority, 2026-10-05 (`docs/GOVERNANCE.md` section 26). |
| Next phase and exact authorised scope | Phase 3, deterministic screening, under section 26. Phase 1B remains unauthorised; no paid API runs, cloud spending, broker or real money. |

---

## Phase 3: Deterministic universe screening

| Field | Record |
|---|---|
| Phase | 3, deterministic universe screening |
| Approved scope and acceptance criteria | Versioned US-equity universe files with provenance and a survivorship note; explicit point-in-time filters (price, liquidity, volatility, history, data freshness) with every rejection explained; deterministic factor scores; a candidate list capped by configuration and by the AI budget, failing closed; persistence of screens and candidates; a reproducible runner and report. No AI model called, no research run triggered, no Phase 1B scope. |
| Repository / PR links | [#20](https://github.com/siddharthatirumala/TradingAgents/pull/20) universes, [#21](https://github.com/siddharthatirumala/TradingAgents/pull/21) filters, [#22](https://github.com/siddharthatirumala/TradingAgents/pull/22) scoring, [#23](https://github.com/siddharthatirumala/TradingAgents/pull/23) funnel and candidate cap, [#24](https://github.com/siddharthatirumala/TradingAgents/pull/24) persistence, [#25](https://github.com/siddharthatirumala/TradingAgents/pull/25) runner, and this PR (gate record and consolidated review package). Phase 2 gate record: [#19](https://github.com/siddharthatirumala/TradingAgents/pull/19) (`2a36d94`). |
| Merge commits on `main` | #20 `5639156`, #21 `208cfe7`, #22 `df1157f`, #23 `8575b04`, #24 `c74f3fe`, #25 `8c8157f` |
| Reviewed commit | `8c8157f` (final Phase 3 code on `main`) |
| Tests and CI evidence | Each PR merged by `merge_pr.sh` with the same checks as Phase 2 (logs: `docs/sid_trading_firm/evidence/phase3/merge_pr19.txt` to `merge_pr25.txt`). Both CI workflows green on each exact head and on `main` after each merge; on `8c8157f`: `CI` run 37249610640 and `SID Trading Firm CI` run 37249610680, both success. SID suite at `8c8157f`: 505 tests (483 unit, 22 PostgreSQL integration run in CI). |
| Security and cost evidence | Phase 3 diff: files under `sid_trading_firm/`, `tests_sid/`, `docs/`, plus one commented line in the SID section of `.env.example` (an upstream-owned file that already carries a SID section); no other upstream file changed; gitleaks green on every PR. New text columns pass through the credential sanitiser (tested on SQLite and PostgreSQL). Paid API cost: **none**. One pipeline smoke test of the example screen used free Yahoo data (no AI): `docs/sid_trading_firm/evidence/phase3/smoke_screen_report.md`. |
| Known issues, exceptions, owners and expiry | (1) Windows exceptions unchanged; across merges #11-#25 `WIN-YF-CACHE-UNDER-HOME` matched in all 15 and `WIN-MEMLOG-CONCURRENT-PERMERROR13` in 3 (#12, #14 and one of #20-#25), each with its exact recorded signature. (2) The unexempted intermittent upstream `tests/test_backtest.py` failure did not recur in #11-#25. (3) The seed universe is hand-compiled and survivorship-biased (stated in the file and in every report); historical screening research needs a point-in-time membership source. (4) No fundamentals, sector or market-cap filters (no point-in-time source yet). (5) Factor ranks are comparable within one screen only. (6) The research cost per candidate is a single input taken from the all-Sonnet Phase 1A baseline; Phase 1B routing would change it and must re-measure. (7) Data age is measured in calendar days. |
| Rollback or recovery | Revert merge commits individually (`git revert -m 1`); schema: `python -m sid_trading_firm.persistence.migrate downgrade 0003_backtests` removes `screening_results` and `screening_candidates`. |
| Codex decision and reasons | **APPROVE (technical)**, recorded 2026-10-05 after remediation: the consolidated review of the section 26 work returned CHANGE REQUIRED; remediation PRs #27-#31 were reviewed and approved by Codex and merged by explicit owner instruction; final `main` `69c3ab5` (see Gate closure below). |
| Owner authorisation | Delegated merge authority, 2026-10-05 (`docs/GOVERNANCE.md` section 26). |
| Next phase and exact authorised scope | **None.** No next phase is authorised (see Gate closure below). |

---

## Gate closure: Phases 1A, 2 and 3 (2026-10-06)

| Field | Record |
|---|---|
| Gates closed | Phase 1A (engineering foundation), Phase 2 (deterministic backtesting), Phase 3 (deterministic screening) |
| Final reviewed commit | `main` `69c3ab58f9886e105a39c0fe82c6300ff17d8f4a` |
| Codex decision | **APPROVE (technical).** History: consolidated review of the section 26 package (PRs #5-#26) returned **CHANGE REQUIRED**; remediation [#27](https://github.com/siddharthatirumala/TradingAgents/pull/27) fail-closed checker and enforced exception scope, [#28](https://github.com/siddharthatirumala/TradingAgents/pull/28) non-finite scores refused, [#29](https://github.com/siddharthatirumala/TradingAgents/pull/29) credential-bearing strategy parameters refused before hashing and storage, [#30](https://github.com/siddharthatirumala/TradingAgents/pull/30) walk-forward windows validated and fail closed, [#31](https://github.com/siddharthatirumala/TradingAgents/pull/31) equity curves, benchmark-relative out-of-sample metrics, `run_id` and storage-first artifacts (migration 0005); Codex approved them after the combined evidence in draft PRs [#32](https://github.com/siddharthatirumala/TradingAgents/pull/32) and [#33](https://github.com/siddharthatirumala/TradingAgents/pull/33) (both closed unmerged). |
| Owner authorisation | Remediation review approved and merging of #27-#31 authorised by the owner (2026-10-05), sequentially, merge commits only. Delegated merge authority (section 26) ended with the consolidated review. |
| Remediation merges | #27 `56aa28b`, #28 `08878c7`, #29 `b02b8fb`, #30 `46c2601`, #31 `69c3ab5`. Each: exact head and commits verified, GitHub Files Changed equal to the PR's own patch, no governance file, conflict-free merge whose tree equalled the predicted tree, local SID unit suite, migrations round trip and ruff on the merged tree, both workflows green on the exact head, merge commit pinned to the head (no squash, no force-push), both workflows green on `main` afterwards. Final `main` tree `43c4c602bbac358f6999f23552280dc8db4db198` equals the combined tree tested in #32 and scanned in #33. Logs: `docs/sid_trading_firm/evidence/remediation/`. |
| CI on `69c3ab5` | `CI` run [37382921254](https://github.com/siddharthatirumala/TradingAgents/actions/runs/37382921254): upstream suite **1262 passed, 1 skipped, 0 failed** on Python 3.11, 3.12 (America/New_York), 3.13, 3.14; ruff "All checks passed!"; clean-install smoke. `SID Trading Firm CI` run [37382921480](https://github.com/siddharthatirumala/TradingAgents/actions/runs/37382921480): SID **613 unit passed** and **26 PostgreSQL 17 integration passed** on Python 3.11 and 3.13; clean non-editable install, `pip check` clean. |
| Migrations | 0001-0005 (`0005_backtest_equity`). On PostgreSQL in CI: head schema equals the models (Alembic autogenerate comparison) and downgrade to base then re-upgrade; complete equity curve round-trips bit-exactly. Locally (SQLite) on every merged tree: upgrade, downgrade to base, re-upgrade. |
| Security | gitleaks (PR-scoped) found no leaks on every remediation PR head (#27: 1 commit, #28: 1, #29: 2, #30: 1, #31: 3) and on the combined tree as one commit (#33: 1 commit, ~89 KB scanned, no leaks). A direct `gitleaks detect --no-git` directory scan was not run (no local binary; downloading one was not authorised). Persisted diagnostics, configuration and strategy parameters are credential-sanitised; credential-bearing strategy parameters are refused before identity hashing and persistence. No credentials in the repository; the only credential-shaped strings are synthetic test values assembled at runtime. |
| Cost | Paid API spend for the whole of Phases 1A-3: **$1.53** (two Phase 1A baselines). No AI calls, cloud spending or broker use since. |
| Known limitation: Windows local tests | Both Windows exceptions (`WIN-YF-CACHE-UNDER-HOME`, `WIN-MEMLOG-CONCURRENT-PERMERROR13`) applied only to the Phase 1A merge recovery and **ended** at the Phase 1A gate record; the earlier checker failed to enforce that and accepted them in merges #12-#26 (corrected in #27). The fail-closed checker now rejects them, so a local Windows run of the upstream suite fails on `tests/test_suite_isolation.py::test_yfinance_keeps_its_cache_out_of_the_users_home` (and intermittently on the concurrent memory-log test). Upstream-suite evidence comes from GitHub Linux CI, where both pass. No exception has been created or extended; restoring local Windows validation needs an owner decision (new exception or upstream fix). The unexempted intermittent `tests/test_backtest.py` failure has not recurred. |
| Other known issues | As listed in the Phase 2 and Phase 3 records above (adjusted prices, survivorship-biased seed universe, assumed costs, no volume limits, no fundamentals or point-in-time index membership, report formatting). |
| Rollback | Revert merge commits individually (`git revert -m 1 <merge>`); schema: `python -m sid_trading_firm.persistence.migrate downgrade <revision>`. |
| Next phase and exact authorised scope | **None. No next phase is authorised.** Phase 1B (AI research), Phase 4 (paper brokerage), cloud deployment and live trading are not authorised and have not been started. Any next phase needs a separate owner authorisation. |

---

## Phase 1B: Controlled research organisation (limited zero-spend build, in progress)

This record supersedes, for the limited scope below only, the "No next phase is authorised" entry of the
gate closure above (2026-10-06).

| Field | Record |
|---|---|
| Phase | 1B, controlled research organisation: **limited zero-spend build, in progress; gate open** |
| Owner authorisation | 2026-10-08, recorded in `docs/GOVERNANCE.md` section 27: strictly zero-spend Phase 1B implementation for research evaluation only, plus a hard maximum Phase 1B measurement budget of **$30 total** ($3 per run, $10 per day). |
| Approved scope and acceptance criteria | Proposal `docs/sid_trading_firm/proposals/phase-1b-proposal.md` (PR #35). Small PRs; mocked models and free/local data; `research.enabled` off by default; any missing risk limit rejects the decision. Gate criteria: the proposal's section 3 and GOVERNANCE section 21 (evidence references and structured outputs validated; stale, missing or invalid data and risk violations rejected; decisions persisted and traceable). |
| Cost rules | Development and CI: **$0** paid AI usage (`research.model_mode` accepts only `"mock"`). **$30 software authorisation ceiling based on provider billing assumptions**, bounded in code; permanent stop at the ceiling; no automatic retries or budget increases; paid calls require the PostgreSQL ledger. **No paid measurement without a separate owner instruction** stating symbols, number of runs and the $30 ceiling. |
| PRs so far | [#36](https://github.com/siddharthatirumala/TradingAgents/pull/36) 1B.1 research configuration, risk placeholders, $30 cap: merged `f7fcf92`. [#37](https://github.com/siddharthatirumala/TradingAgents/pull/37) 1B.2 lifetime-budget enforcement against the ledger, PostgreSQL ledger required for paid mode, migration 0006: merged `1e3a0e9`. Each was merged on the owner's explicit approval with exact-head CI and post-merge `main` CI green. |
| Tests and CI evidence | On `1e3a0e9`: SID 673 unit and 31 PostgreSQL integration tests passed on Python 3.11 and 3.13; upstream suite passing on Linux CI; ruff, clean install and gitleaks green. |
| Security and cost evidence | No paid AI call since the Phase 1A baselines: the local ledger holds 38 calls totalling $1.525070, the latest on 2026-10-04. Paid model mode is blocked at configuration load, and the baseline harness refuses real provider clients in mock mode. |
| Known issues | Windows local upstream-suite limitation unchanged (see the gate closure); no exception created or extended. |
| Rollback | Revert merge commits individually; schema `python -m sid_trading_firm.persistence.migrate downgrade 0005_backtest_equity` removes `budget_reservations`. |
| Codex decision and reasons | Requested per PR. Not yet recorded for the phase. |
| Not authorised | Brokers, paper trading (Phase 4), cloud deployment and spending, live or real-money trading, Phases 5-7, paid AI calls in development or CI, paid measurement without the separate instruction. |
| Next step | 1B.3 data snapshots, after this governance record is reviewed. |
