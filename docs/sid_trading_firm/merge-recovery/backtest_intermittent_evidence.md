# Unexplained intermittent failure: `tests/test_backtest.py::test_a_bullish_call_is_scored_the_same_way_as_before`

**Status: OPEN, UNEXEMPTED.** No exception record exists. If this test fails during any
formal validation, `check_upstream_failures.py` rejects it ("no recorded exception") and
`validate_pr.sh` stops.

## What the test does
Upstream test (unchanged by SID work). It writes two decisions and outcomes to a
`TradingMemoryLog` file under `tmp_path`, then checks `summarize()` gives the Buy rating a
hit rate of 0.5. The memory-log writer replaces files on disk: the same code path as the
known Windows race (`WIN-MEMLOG-CONCURRENT-PERMERROR13`).

## Observations (local Windows 11 Home 10.0.26200, Python 3.14.7)

| When (2026-10-04/05) | Code | Run type | Result |
|---|---|---|---|
| after `pip install -e ".[dev,sid]"` on PR #5 branch (pre-`e0e485b` working tree) | PR #5 + redaction fix | full upstream suite | **failed** (summary: `2 failed, 1257 passed`; the other failure was the known yfinance test) |
| immediately after | same | 10 isolated runs | **1 failed**, 9 passed |
| next | same | 30 isolated runs, `--tb=short` | 0 failed |
| next | same | 100 isolated runs with the evidence plugin | 0 failed |
| next | same | 3 full-suite runs with the evidence plugin | 0 failed (only the two recorded exceptions appeared) |
| PR #5 validation at `e0e485b` | main + PR #5 | full upstream suite (validate_pr.sh) | passed |
| GitHub Actions (Linux), every PR #1-#9 and every re-run | all heads | CI `tests` jobs, 4 Python versions | never failed |

Approximate rate: 2 failures in about 145 local runs; 0 in CI.

## What is not known
- **The failure signature was not captured.** The two failing runs used plain `pytest` without
  saved output or the evidence plugin; every later run with capture passed.
- Whether it reproduces on pristine pinned upstream (`1394a3f`): not yet attempted, because it
  could not be reproduced on demand even on SID code.

## Facts that bound it
- SID code does not enter this test's path: upstream imports nothing from `sid_trading_firm`
  (0 files), and the test exercises `tradingagents/backtest.py`, `tradingagents/memory/log.py`
  and `tradingagents/dataflows/files.py`, which Phase 1A did not modify.
- Both failures happened within minutes of an editable reinstall (`pip install -e`), which
  rewrites files on disk; a Windows file-access race (antivirus or indexer scanning new files)
  is a plausible but unconfirmed cause.

## Required before any exception could be considered
Captured signature with the evidence plugin, reproduction on pristine upstream `1394a3f`,
platform, scope, owner approval and expiry, per `docs/GOVERNANCE.md` section 23. Until then it is a
blocker whenever it occurs.
