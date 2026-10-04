"""The upstream TradingAgents release this code was built and tested against.

Updating upstream is a deliberate act: a sync branch merges the new release,
both test suites run, and this pin moves in the same pull request. The pin test
in ``tests_sid`` fails when the installed ``tradingagents`` differs, so an
upstream change cannot alter research or risk behaviour unnoticed.
"""

UPSTREAM_REPOSITORY = "TauricResearch/TradingAgents"
PINNED_UPSTREAM_VERSION = "0.6.0"
PINNED_UPSTREAM_COMMIT = "1394a3f72aa4393e1a98f51b382434c4b4c2d972"
