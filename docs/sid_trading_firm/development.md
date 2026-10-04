# Development workflow

## Branches and pull requests

- `main` is protected by convention: nothing is pushed to it directly.
- Branch per logical change: `sid/<short-topic>` (for example `sid/p1-03-usage-ledger`).
  A change that builds on an unmerged one branches from it and its PR targets that
  branch; GitHub retargets it to `main` when the parent merges.
- PRs follow `.github/pull_request_template.md`. The owner reviews and merges.
- Before opening a PR:

```bash
pytest               # upstream suite: must stay green (one known Windows-only failure, below)
pytest tests_sid     # SID Trading Firm suite
ruff check .
```

Known environment issue: `tests/test_suite_isolation.py::test_yfinance_keeps_its_cache_out_of_the_users_home`
fails on Windows only, because `%TEMP%` sits inside the user's home folder. It
passes in CI (Linux). It is an upstream test and is left unmodified.

## Pre-commit (recommended)

```bash
pip install pre-commit
pre-commit install
```

This runs ruff, gitleaks and basic file checks on every commit. The gitleaks hook
builds a small Go binary on first use.

## Secrets

- Real keys go only in `.env` (gitignored). `.env.example` lists names, never values.
- CI runs gitleaks on every PR and push to `main`.
- Never paste keys into code, tests, fixtures, logs or PR descriptions.
- Production secrets will live in a managed vault (Azure Key Vault planned).

## Upstream TradingAgents sync

The fork tracks upstream through a remote:

```bash
git remote add upstream https://github.com/TauricResearch/TradingAgents.git   # once
git fetch upstream --tags
```

Current pin: see `sid_trading_firm/upstream.py`. When the weekly
"Upstream release watch" workflow opens an issue, or before relying on an
upstream fix:

1. `git checkout -b sid/upstream-sync-vX.Y.Z main`
2. `git merge vX.Y.Z` (the upstream release tag) and resolve conflicts.
3. Review the upstream changelog and diff, especially anything touching agents,
   prompts, ratings, data vendors or the graph: these change research behaviour.
4. Update `PINNED_UPSTREAM_VERSION` and `PINNED_UPSTREAM_COMMIT` in
   `sid_trading_firm/upstream.py`.
5. Run both suites and ruff. The pin test fails until step 4 is done.
6. Open the PR with a summary of behaviour-relevant upstream changes. Merge only
   when compatibility is confirmed.
