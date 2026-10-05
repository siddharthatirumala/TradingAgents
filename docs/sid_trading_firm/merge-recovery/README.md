# Phase 1A merge recovery: review package

Evidence from the Phase 1A merge recovery (2026-10-04/05), kept in the repository so it can
be reviewed on GitHub. These scripts are review tooling: nothing in the application or the
test suites imports them. Paths in logs are redacted (`<HOME>`).

| File | What it is |
|---|---|
| `validate_pr.sh` | Review-mode validation of one PR against an anchored `main` (default anchor `059b9ff`). Checks ancestry, governance blobs (`AGENTS.md` 2ff76018, `docs/GOVERNANCE.md` 4cb8ff10), PR identity, unique commits, incremental diff, entry-by-entry merged tree, local suites, a 30-run reproduction of the concurrency race, and fresh GitHub CI. **Never merges, retargets or pushes**; re-checks the anchor at the end. |
| `sid_validation_plugin.py` | Observation-only pytest plugin (`-p sid_validation_plugin`). Writes one JSON line per outcome; for a failure, records the exception type, failing statement and structured evidence taken from the failing test's real local objects (each `errors` item's type, errno, winerror, strerror; per-writer entry counts and duplicates). |
| `check_upstream_failures.py` | Decides PASS/FAIL from a plugin report and the exception records. A failure passes only if an active (platform, expiry, owner approval) exception matches its exact node id, phase, exception type, failing statement and evidence. Missing, mixed, empty, truncated or unparseable evidence fails. |
| `windows_exceptions.json` | The two Windows-only exception records with every field `docs/GOVERNANCE.md` section 23 requires. |
| `checker_selftest.py` | 21 cases: 4 real failures accepted, 17 targeted alterations rejected. |
| `evidence/pristine_*.jsonl` | Plugin reports from **pristine pinned upstream `1394a3f`**: yfinance 5/5 failed; concurrency 5/30 failed (the failing runs are kept). |
| `backtest_intermittent_evidence.md` | The unexplained, **unexempted** backtest failure: observations and what is not known. |
| `merge_pr.sh` | The merge script used under delegated authority: retarget, identity and unique commits, diff, merged tree == main + PR patch, local suites through the checker, CI on the exact head, merge commit, CI on `main`. |
| `evidence/main_a66753d_upstream.jsonl` | Plugin report of the upstream suite on final Phase 1A `main`. |
| `logs/` | Redacted logs: checker self-test; PR #5 review validations at `d4f992f`, `e0e485b` (superseded) and `c783be7`; merge logs for #10 and #5-#9. |

Run the self-test from this folder: `python checker_selftest.py`.

Exception records (summary):

| Id | Test | Signature | Pristine `1394a3f` | Platform | Owner | Expires |
|---|---|---|---|---|---|---|
| WIN-YF-CACHE-UNDER-HOME | `tests/test_suite_isolation.py::test_yfinance_keeps_its_cache_out_of_the_users_home` | `AssertionError` at `assert not Path(_TzDBManager.get_location()).is_relative_to(Path.home())` | 5/5 failed | win32 | siddharthatirumala | 2026-10-31 (proposed; owner to confirm) |
| WIN-MEMLOG-CONCURRENT-PERMERROR13 | `tests/test_memory_log.py::test_concurrent_writers_keep_every_decision_and_outcome` | `AssertionError` at `assert errors == []`; nonempty `errors`, every item `PermissionError` errno 13 winerror 5 "Access is denied"; only the raising writers incomplete, no duplicates | 5/30 failed | win32 | siddharthatirumala | 2026-10-31 (proposed; owner to confirm) |

Both must pass in GitHub Linux CI (workflow `CI`, jobs `tests`), and they do on every PR head.
