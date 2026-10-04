## Purpose
<!-- What problem does this PR solve? -->

## Changes
<!-- Exactly what was added, modified or deleted. -->

## Architecture
<!-- Why this implementation. Note any change to upstream tradingagents/ files and why it was necessary. -->

## Files
<!-- The important files changed. -->

## Testing
<!-- Commands run and results: upstream suite (pytest), SID suite (pytest tests_sid), ruff. -->

## Security
<!-- Secrets, credentials, data leaving the machine, new external services. -->

## Cost
<!-- Any new recurring API, cloud or data cost. "None" is a valid answer. -->

## Technical debt
<!-- Anything temporary, or to improve later. -->

## Next step
<!-- What should happen after this PR. -->

---
Safety checklist
- [ ] No live trading path added (`live_trading_enabled` stays false)
- [ ] No financial number is produced by an LLM where Python can calculate it
- [ ] No secrets in code, tests, logs or fixtures
