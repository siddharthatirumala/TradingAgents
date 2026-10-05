# Phase 1A merge recovery: review package

Evidence from the Phase 1A merge recovery (2026-10-04/05), kept in the repository so it can
be reviewed on GitHub. These scripts are review tooling: nothing in the application or the
test suites imports them. Paths in logs are redacted (`<HOME>`).

| File | What it is |
|---|---|
| `validate_pr.sh` | Review-mode validation of one PR against an anchored `main` (default anchor `059b9ff`). Checks ancestry, governance blobs (`AGENTS.md` 2ff76018, `docs/GOVERNANCE.md` 4cb8ff10), PR identity, unique commits, incremental diff, entry-by-entry merged tree, local suites, a 30-run reproduction of the concurrency race, and fresh GitHub CI. **Never merges, retargets or pushes**; re-checks the anchor at the end. |
| `sid_validation_plugin.py` | Observation-only pytest plugin (`-p sid_validation_plugin`), report schema 2. Writes a session start and finish (with pytest's exit status and counters), the collected test ids, every collection error and every setup/call/teardown and subtest report; for a failure, the exception type, failing statement and structured evidence taken from the failing test's real local objects (each `errors` item's type, errno, winerror, strerror; per-writer entry counts and duplicates). |
| `check_upstream_failures.py` | Decides PASS/FAIL from a plugin report, pytest's exit code and the exception records; fails closed. Requires exit status 0 or 1 matching the report, exactly one session start, collection finish and session finish, no collection error and complete outcome accounting (every collected test has its setup, call and teardown; counts match pytest's). A failure passes only if it is a test call whose exception is active (platform, expiry, owner approval) and in scope (the validation `--phase` is in `scope.phases` and the `scope.ends_at_gate` gate record is not yet in `docs/PHASES.md`), and matches the exact node id, exception type, failing statement and evidence. Tests: `tests_sid/test_upstream_failure_checker.py`. |
| `windows_exceptions.json` | The two Windows-only exception records with every field `docs/GOVERNANCE.md` section 23 requires, plus a machine-readable `scope` restating their recorded scope: validation phase `1A-merge-recovery` only, ending at the Phase 1A gate record. Both have therefore **ended** (the Phase 1A gate record merged in #11); the checker no longer accepts them. |
| `evidence/pristine_*.jsonl` | Plugin reports from **pristine pinned upstream `1394a3f`**: yfinance 5/5 failed; concurrency 5/30 failed (the failing runs are kept). |
| `backtest_intermittent_evidence.md` | The unexplained, **unexempted** backtest failure: observations and what is not known. |
| `merge_pr.sh` | **Retired** (delegated authority ended 2026-10-05). The merge script used under delegated authority: retarget, identity and unique commits, diff, merged tree == main + PR patch, local suites through the checker, CI on the exact head, merge commit, CI on `main`. |
| `evidence/main_a66753d_upstream.jsonl` | Plugin report of the upstream suite on final Phase 1A `main`. |
| `logs/` | Redacted logs: checker self-test of the schema-1 checker (superseded); PR #5 review validations at `d4f992f`, `e0e485b` (superseded) and `c783be7`; merge logs for #10 and #5-#9. |

Checker and plugin tests: `pytest tests_sid/test_upstream_failure_checker.py` (real pytest runs of synthetic suites; also run in CI). The schema-1 self-test and the `evidence/*.jsonl` reports predate schema 2 and are kept as historical evidence only.

Exception records (summary):

| Id | Test | Signature | Pristine `1394a3f` | Platform | Owner | Expires |
|---|---|---|---|---|---|---|
| WIN-YF-CACHE-UNDER-HOME | `tests/test_suite_isolation.py::test_yfinance_keeps_its_cache_out_of_the_users_home` | `AssertionError` at `assert not Path(_TzDBManager.get_location()).is_relative_to(Path.home())` | 5/5 failed | win32 | siddharthatirumala | 2026-10-31 (proposed; owner to confirm) |
| WIN-MEMLOG-CONCURRENT-PERMERROR13 | `tests/test_memory_log.py::test_concurrent_writers_keep_every_decision_and_outcome` | `AssertionError` at `assert errors == []`; nonempty `errors`, every item `PermissionError` errno 13 winerror 5 "Access is denied"; only the raising writers incomplete, no duplicates | 5/30 failed | win32 | siddharthatirumala | 2026-10-31 (proposed; owner to confirm) |

Both must pass in GitHub Linux CI (workflow `CI`, jobs `tests`), and they do on every PR head.

**Correction (2026-10-05).** Both records limited themselves to the Phase 1A merge recovery and to end at the Phase 1A gate record, but the schema-1 checker did not enforce that scope, so it kept accepting them after that gate, in merges #12-#26: the yfinance exception in all 15 of those merges and the concurrency exception in 3 (#12, #14, #22). From now on a local Windows run of the upstream suite fails the checker on `test_yfinance_keeps_its_cache_out_of_the_users_home`; upstream-suite evidence comes from Linux CI unless the owner approves a new exception.
