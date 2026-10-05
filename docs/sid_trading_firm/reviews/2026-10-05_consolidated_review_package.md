# Consolidated review package: work merged under delegated authority

**For:** Codex (independent reviewer). **From:** Claude Code (implementation). **Date:** 2026-10-05.
**Authority:** owner authorisation of 2026-10-05, recorded in `docs/GOVERNANCE.md` section 26.

None of the pull requests below has been independently reviewed by Codex. They were
merged by Claude Code under delegated authority after automated validation. This package
says what was merged and where the evidence is. It does not claim the work is correct:
please verify the evidence rather than this summary. Codex's decision on this package is
required before any further phase. **Phase 1B has not been started and is not authorised.**

## 1. Scope merged under section 26

Range: `main` went from `059b9ff` (before PR #10) to `8c8157f` (after PR #25), plus this
PR. All are merge commits (bottom-up, no squash, no force-push to `main`, no history rewrite).

| PR | Title | Merge | Size |
|---|---|---|---|
| [#10](https://github.com/siddharthatirumala/TradingAgents/pull/10) | Governance: record delegated merge authority and review cadence | `e09d8e4` | +77/-2, 4 files |
| [#5](https://github.com/siddharthatirumala/TradingAgents/pull/5) | PostgreSQL persistence foundation | `4ab215f` | +1327/-2, 18 files |
| [#6](https://github.com/siddharthatirumala/TradingAgents/pull/6) | Deterministic quant library | `0b79489` | +1228/-0, 10 files |
| [#7](https://github.com/siddharthatirumala/TradingAgents/pull/7) | Typed decision contracts and evidence validation | `1d02032` | +885/-0, 7 files |
| [#8](https://github.com/siddharthatirumala/TradingAgents/pull/8) | Record call details in the usage ledger | `20d788e` | +742/-26, 16 files |
| [#9](https://github.com/siddharthatirumala/TradingAgents/pull/9) | Native structured output for Claude models without forced tool use | `a66753d` | +710/-1, 7 files |
| [#11](https://github.com/siddharthatirumala/TradingAgents/pull/11) | Phase 1A gate record and merge-recovery evidence | `de36afd` | +2649/-0, 30 files |
| [#12](https://github.com/siddharthatirumala/TradingAgents/pull/12) | Phase 2.1: point-in-time price data | `27969b1` | +427/-0, 3 files |
| [#13](https://github.com/siddharthatirumala/TradingAgents/pull/13) | Phase 2.2: daily backtest simulator | `dc93133` | +485/-0, 2 files |
| [#14](https://github.com/siddharthatirumala/TradingAgents/pull/14) | Phase 2.3: performance metrics | `e6bb9e6` | +272/-0, 2 files |
| [#15](https://github.com/siddharthatirumala/TradingAgents/pull/15) | Phase 2.4: splits and walk-forward | `2f1de8d` | +289/-0, 2 files |
| [#16](https://github.com/siddharthatirumala/TradingAgents/pull/16) | Phase 2.5: versioned reference strategies | `46ca48a` | +277/-0, 4 files |
| [#17](https://github.com/siddharthatirumala/TradingAgents/pull/17) | Phase 2.6: strategy and backtest persistence | `9058caf` | +328/-2, 7 files |
| [#18](https://github.com/siddharthatirumala/TradingAgents/pull/18) | Phase 2.7: backtest runner, report and CLI | `87936cf` | +512/-0, 4 files |
| [#19](https://github.com/siddharthatirumala/TradingAgents/pull/19) | Phase 2 gate record and evidence | `2a36d94` | +308/-1, 11 files |
| [#20](https://github.com/siddharthatirumala/TradingAgents/pull/20) | Phase 3.1: screening universes | `5639156` | +219/-0, 4 files |
| [#21](https://github.com/siddharthatirumala/TradingAgents/pull/21) | Phase 3.2: screening filters | `208cfe7` | +220/-0, 3 files |
| [#22](https://github.com/siddharthatirumala/TradingAgents/pull/22) | Phase 3.3: factor scores | `df1157f` | +243/-0, 2 files |
| [#23](https://github.com/siddharthatirumala/TradingAgents/pull/23) | Phase 3.4: funnel and budget-bounded candidates | `8575b04` | +229/-0, 6 files |
| [#24](https://github.com/siddharthatirumala/TradingAgents/pull/24) | Phase 3.5: screening persistence | `c74f3fe` | +265/-0, 5 files |
| [#25](https://github.com/siddharthatirumala/TradingAgents/pull/25) | Phase 3.6: screening runner, report and CLI | `8c8157f` | +373/-0, 4 files |

PRs #5-#9 were Phase 1A work. You reviewed #5 twice before merge (two CHANGE REQUIRED
decisions, both corrected); #6-#9 and #10 were not reviewed by you. PRs #1-#4 were merged
with per-PR owner approval before section 26 existed.

Phase gate records: `docs/PHASES.md` (Phase 0, 1A, 2, 3).

## 2. How each PR was validated before merge

Each PR went through `docs/sid_trading_firm/merge-recovery/merge_pr.sh`, which stops on any
deviation:

1. `origin/main` equals the SHA left by the previous merge (an unexpected change to `main` stops the run).
2. The PR's base is `main`, its head is the expected commit, and its commits are exactly the expected unique commits (local git and the GitHub API).
3. GitHub "Files changed" equals the PR's own patch from its merge base. Governance files are refused unless explicitly allowed (only #10).
4. The merged tree equals `main` plus the PR patch, conflict-free.
5. Locally on the merged tree: the upstream suite runs through an observation-only pytest plugin and the exception checker (a failure passes only on an exact recorded signature); the SID suite; migrations upgrade/downgrade/upgrade; ruff.
6. Both CI workflows are green on the exact head commit: upstream suite on Python 3.11 to 3.14, ruff, clean install, SID suite on 3.11 and 3.13, PostgreSQL 17 integration, and PR-scoped gitleaks.
7. Merge commit; parents and tree verified; both workflows green on `main` afterwards.

Logs: `docs/sid_trading_firm/merge-recovery/logs/` (#5-#10) and
`docs/sid_trading_firm/evidence/phase2/`, `.../phase3/` (#11-#25).

## 3. Final state of `main` (`8c8157f`)

- CI: `CI` run 37249610640 success, `SID Trading Firm CI` run 37249610680 success.
- SID suite: 505 tests (483 unit, 22 PostgreSQL integration run in CI).
- Upstream suite (local, Windows, on each merged tree): 1258 passed and 1 failed, or 1257 passed and 2 failed when the memory-log exception fired, 4 skipped. Every failure matched a recorded Windows exception signature. Linux CI passes the upstream suite.
- Migrations: 0001 to 0004; upgrade/downgrade/upgrade OK; schema equals models (tested on SQLite and PostgreSQL).
- Changes outside `sid_trading_firm/`, `tests_sid/` and `docs/` across the section 26 range: `pyproject.toml`, `compose.sid.yaml`, `.github/workflows/sid-ci.yml` (#5), `.env.example` (#5 and #23), `tradingagents/llm_clients/anthropic_client.py` (#9: Sonnet 5.5 structured output) and `AGENTS.md` (#10). No other upstream file changed.
- Secret scan of added lines across the range: the only credential-shaped match is the synthetic key assembled at runtime in `tests_sid/redaction_checks.py` (a redaction test fixture). gitleaks passed on every PR.
- No broker code, no order submission, no live-trading path; `live_trading_enabled` cannot be enabled.

## 4. Cost

- Paid API spend during the whole period: **$1.53** (the two Phase 1A NVDA baselines, before section 26). Nothing has been spent since.
- No cloud spending. AI calls in tests are mocked.
- Two smoke tests (backtest and screen) used free Yahoo data and no AI:
  `docs/sid_trading_firm/evidence/phase2/smoke_backtest_report.md` and
  `docs/sid_trading_firm/evidence/phase3/smoke_screen_report.md`. Both are labelled as pipeline checks, not evidence of an edge.

## 5. Known issues and exceptions

| Item | Status | Owner / expiry |
|---|---|---|
| `WIN-YF-CACHE-UNDER-HOME` (upstream yfinance cache test, Windows) | Accepted exception, exact signature; matched in all 15 merges #11-#25 | owner; 2026-10-31 (proposed, owner to confirm) |
| `WIN-MEMLOG-CONCURRENT-PERMERROR13` (upstream concurrent memory-log test, Windows) | Accepted exception, exact signature with writer-integrity check; matched in 3 of 15 merges | owner; 2026-10-31 (proposed, owner to confirm) |
| `tests/test_backtest.py::test_a_bullish_call_is_scored_the_same_way_as_before` intermittent on Windows | **Not exempted**; did not recur in #11-#25; a blocker if it recurs | open |
| Full-history gitleaks flags two fake upstream fixtures (`b20c8e6`) | Accepted by owner as upstream false positives | repository hardening, not scheduled |
| Backtest limitations (adjusted prices, survivorship, assumed costs, unsold positions at period end, warm-up in cash, unused trailing walk-forward days, no volume limits) | Stated in reports and in the Phase 2 gate record | technical debt |
| Screening limitations (hand-compiled seed universe, no fundamentals or sector data, ranks per screen, single cost estimate, calendar-day data age) | Stated in reports and in the Phase 3 gate record | technical debt |
| Report formatting (counts with decimals, regimes as raw JSON, no OOS benchmark comparison) | Cosmetic | technical debt |

## 6. Decisions made without owner input (please check)

1. **Required `--out`.** Both CLIs require `--out` instead of writing to a default directory in the repository, to avoid changing upstream's `.gitignore`.
2. **Walk-forward storage.** Each window is stored under the strategy version chosen for it. The stitched out-of-sample row is stored under the base specification's version, with a note saying so.
3. **Candidate cap bounds.** `budgets.max_ai_candidates_per_run` defaults to 5 and is bounded at 1-50.
4. **Research cost input.** The research cost per candidate is a required explicit input; the example uses $0.80 from the Phase 1A all-Sonnet baselines.
5. **Paper states refused.** `PAPER_APPROVED` and `PAPER_ACTIVE` strategy statuses are refused by the repository, because Phase 4 is not authorised.
6. **Seed universe.** A 31-stock hand-compiled seed universe (plus SPY, QQQ) was added for development and is labelled survivorship-biased.

## 7. Suggested review focus

1. Look-ahead: `backtest/data.py` (`PanelView`, `truncated`), `backtest/engine.py` (decision at close, fill at next open), `backtest/splits.py` (selection on the truncated panel), and screening filters and factors (view-only access).
2. Simulator correctness: the cash constraint, sells before buys, cost and slippage arithmetic, and trade P&L (`tests_sid/test_backtest_engine.py` has hand-worked expectations).
3. Fail-closed behaviour: invalid strategy output, the screen refusal conditions, undefined metric states, and runs marked failed on storage errors.
4. Persistence: migrations 0003 and 0004, foreign keys, credential sanitising of the new columns.
5. Scope: no AI in historical evaluation or screening (AST tests), no broker code, no Phase 1B.
6. The two Windows exceptions and their expiry, which needs the owner's confirmation.

## 8. Requested decision

`APPROVE`, `CHANGE REQUIRED` or `REJECT` for the work merged under section 26, and
whether section 26 should end now (Claude Code treats it as ended after this package) or
be revised. No further phase will start until you review this package and the owner
authorises the next phase.
