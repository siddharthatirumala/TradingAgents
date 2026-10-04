"""Baseline measurement: one normal upstream TradingAgents analysis, fully metered.

The point is cost and behaviour, not investment quality: how many model calls a
run makes, how many tokens, what each agent and stage costs, which calls are
slowest and which prompts largest, and how often structured output fell back to
free text. Every call goes through the usage ledger and the budget guard, so the
run stops if it would exceed the configured cap.

    python -m sid_trading_firm.measurement.baseline --ticker NVDA --date 2026-10-02

Output, under ``--out`` (default ``docs/sid_trading_firm/baselines``), one folder
per run: ``report.md``, ``llm_calls.jsonl`` (one record per call) and
``summary.json``. Upstream's own results, cache and memory log for the run go to a
scratch folder, so the measurement neither reads nor changes earlier runs.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import re
import sys
import tempfile
import time
from collections import Counter
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from pathlib import Path

from sid_trading_firm.config import ConfigError, Settings, Tier, load_settings
from sid_trading_firm.config.agents import UPSTREAM_NODE_AGENTS, display_name
from sid_trading_firm.llm import (
    AIBudgetStop,
    BudgetGuard,
    BudgetStopEvent,
    JsonlUsageStore,
    UsageLedger,
)
from sid_trading_firm.llm.models import upstream_config
from sid_trading_firm.llm.report import render_markdown, summarize
from sid_trading_firm.observability.logging import configure_logging
from sid_trading_firm.runtime import run_context

logger = logging.getLogger(__name__)

DEFAULT_OUT = Path("docs/sid_trading_firm/baselines")
DEFAULT_LEDGER = Path.home() / ".sid_trading_firm" / "llm_usage.jsonl"
ALL_ANALYSTS = ("market", "social", "news", "fundamentals")

# US-listed common stock symbols in Yahoo's convention, which upstream's data layer
# uses: 1-5 letters, optionally a share class after a hyphen (BRK-B). A dot marks
# an exchange suffix there (NVDA.L is London), so dotted symbols are refused.
_US_EQUITY = re.compile(r"^[A-Z]{1,5}(-[A-Z])?$")

# Upstream logs this when a structured call fails and it retries as free text.
_FALLBACK = re.compile(r"^(?P<agent>[\w ]+): structured-output invocation failed")


class BaselineError(RuntimeError):
    """The measurement cannot start."""


def check_us_equity(ticker: str) -> str:
    symbol = ticker.strip().upper()
    if not _US_EQUITY.match(symbol):
        raise BaselineError(
            f"{ticker!r} is not a US-listed common stock symbol (share classes are written BRK-B); "
            "Phase 1 scope is US equities only")
    return symbol


def check_api_keys(settings: Settings) -> list[str]:
    """Env var names of the keys the upstream run needs. Raises if any is missing; never prints values."""
    from tradingagents.llm_clients.api_key_env import get_api_key_env

    needed = []
    for tier in (Tier.STANDARD, Tier.DEEP):
        name = get_api_key_env(settings.models.tiers[tier].provider)
        if name and name not in needed:
            needed.append(name)
    missing = [name for name in needed if not os.environ.get(name, "").strip()
               or os.environ[name].strip() == "placeholder"]
    if missing:
        raise BaselineError(f"missing API key(s): {', '.join(missing)}; add them to .env (never commit it)")
    return needed


def previous_weekday(today: date | None = None) -> str:
    day = (today or datetime.now(UTC).date()) - timedelta(days=1)
    while day.weekday() >= 5:
        day -= timedelta(days=1)
    return day.isoformat()


class _FallbackCounter(logging.Handler):
    """Counts upstream's structured-output fallbacks per agent."""

    def __init__(self) -> None:
        super().__init__(logging.WARNING)
        self.counts: Counter = Counter()

    def emit(self, record: logging.LogRecord) -> None:
        match = _FALLBACK.match(record.getMessage())
        if match:
            node = match.group("agent").strip()
            self.counts[UPSTREAM_NODE_AGENTS.get(node, node)] += 1


@dataclass
class BaselineResult:
    run_id: str
    status: str                      # completed | budget_stopped | failed
    ticker: str
    trade_date: str
    out_dir: Path
    signal: str | None = None
    error: str | None = None
    wall_seconds: float = 0.0
    stops: list[BudgetStopEvent] = field(default_factory=list)
    fallbacks: dict[str, int] = field(default_factory=dict)


def run_baseline(
    ticker: str,
    trade_date: str,
    *,
    settings: Settings,
    out_root: Path = DEFAULT_OUT,
    ledger_path: Path = DEFAULT_LEDGER,
    analysts: tuple[str, ...] = ALL_ANALYSTS,
) -> BaselineResult:
    """Run one metered upstream analysis and write its report. Never raises for a stopped run."""
    from tradingagents.graph.trading_graph import TradingAgentsGraph

    ticker = check_us_equity(ticker)
    store = JsonlUsageStore(ledger_path)
    guard = BudgetGuard(settings.budgets, settings.pricing, store)
    fallbacks = _FallbackCounter()
    logging.getLogger("tradingagents.agents.structured").addHandler(fallbacks)
    scratch = Path(tempfile.mkdtemp(prefix="sid-baseline-"))
    config = upstream_config(settings) | {
        "results_dir": str(scratch / "results"),
        "data_cache_dir": str(scratch / "cache"),
        "memory_log_path": str(scratch / "memory.md"),
    }

    with run_context(instrument=ticker, strategy="upstream_baseline",
                     environment=settings.app.environment.value) as run:
        out_dir = Path(out_root) / f"{trade_date}_{ticker}_{run.run_id[:8]}"
        result = BaselineResult(run.run_id, "failed", ticker, trade_date, out_dir)
        started = time.perf_counter()
        logger.info("baseline run starting", extra={"trade_date": trade_date, "analysts": list(analysts)})
        try:
            graph = TradingAgentsGraph(list(analysts), config=config, callbacks=[UsageLedger(guard)])
            _, result.signal = graph.propagate(ticker, trade_date)
            result.status = "completed"
        except AIBudgetStop as stop:
            result.status, result.error = "budget_stopped", str(stop)
        except Exception as exc:   # a failed run is still measured and reported
            result.error = f"{type(exc).__name__}: {exc}"
            logger.exception("baseline run failed")
        finally:
            result.wall_seconds = round(time.perf_counter() - started, 1)
            logging.getLogger("tradingagents.agents.structured").removeHandler(fallbacks)
        result.stops = list(guard.stops)
        result.fallbacks = dict(fallbacks.counts)
    write_report(result, store.records(result.run_id), settings, analysts)
    return result


def write_report(result: BaselineResult, records, settings: Settings, analysts) -> Path:
    out = result.out_dir
    out.mkdir(parents=True, exist_ok=True)
    with (out / "llm_calls.jsonl").open("w", encoding="utf-8") as f:
        for record in records:
            f.write(record.to_json() + "\n")
    summary = summarize(records)
    t = summary.total
    std, deep = settings.models.tiers[Tier.STANDARD], settings.models.tiers[Tier.DEEP]

    (out / "summary.json").write_text(json.dumps({
        "run_id": result.run_id, "status": result.status, "ticker": result.ticker,
        "trade_date": result.trade_date, "signal": result.signal, "error": result.error,
        "wall_seconds": result.wall_seconds, "calls": t.calls, "failed_calls": t.failures,
        "input_tokens": t.input_tokens, "output_tokens": t.output_tokens,
        "cache_read_tokens": t.cache_read_tokens, "cost_usd": str(t.cost_usd),
        "calls_without_usage": t.no_usage, "calls_unpriced": t.unpriced,
        "by_agent": {a: {"calls": line.calls, "input_tokens": line.input_tokens,
                         "output_tokens": line.output_tokens, "cost_usd": str(line.cost_usd),
                         "latency_s": round(line.latency_ms / 1000, 1)}
                     for a, line in summary.by_agent.items()},
        "structured_output_fallbacks": result.fallbacks,
        "budget_stops": [s.to_dict() for s in result.stops],
        "models": {"upstream_quick (STANDARD)": std.key, "upstream_deep (DEEP)": deep.key},
        "budgets": settings.budgets.model_dump(mode="json"),
    }, indent=2), encoding="utf-8")

    fallback_rows = (["| Agent | Fallbacks |", "|---|---:|"]
                     + [f"| {display_name(a)} | {n} |" for a, n in sorted(result.fallbacks.items())]
                     if result.fallbacks else ["None: every structured call parsed on the first attempt."])
    stop_rows = ([f"- **{s.reason}** ({display_name(s.agent or '')}): {s.detail}" for s in result.stops]
                 if result.stops else ["None."])
    b = settings.budgets
    lines = [
        f"# Baseline LLM usage: {result.ticker} on {result.trade_date}",
        "",
        "Measures what one normal upstream TradingAgents analysis costs. It does not evaluate "
        "the investment decision.",
        "",
        "| | |", "|---|---|",
        f"| Run id | `{result.run_id}` |",
        f"| Status | **{result.status}**{' (' + result.error + ')' if result.error else ''} |",
        f"| Upstream decision | {result.signal or 'n/a'} |",
        f"| Analysts | {', '.join(analysts)} |",
        f"| Models | upstream quick tier = {std.key}; deep tier = {deep.key} |",
        f"| Output cap | {std.max_output_tokens or 'provider default'} tokens per call |",
        f"| Budget | ${b.max_ai_cost_per_run_usd} per run, ${b.max_ai_cost_per_day_usd} per day, "
        f"{b.max_llm_tokens_per_agent:,} tokens and {b.max_agent_iterations} calls per agent |",
        f"| Rounds | debate {b.max_debate_rounds}, risk {b.max_risk_discuss_rounds}, "
        f"analyst tool rounds {max(1, b.max_agent_iterations - 1)} |",
        f"| Wall time | {result.wall_seconds:.0f}s |",
        f"| Total | **{t.calls} calls, {t.input_tokens:,} input + {t.output_tokens:,} output tokens, "
        f"${t.cost_usd:.4f}** |",
        "",
        render_markdown(summary),
        "",
        "## Structured-output fallbacks",
        "",
        "Each fallback is a structured call that did not parse, retried by upstream as a second, free-text call.",
        "",
        *fallback_rows,
        "",
        "## Budget stops",
        "",
        *stop_rows,
        "",
        "## Notes",
        "",
        "- Costs are estimates from `sid_trading_firm/config/pricing.yaml` and provider-reported tokens.",
        "- Upstream has two model tiers. Agents SID maps to FAST (sentiment, reflection) ran on the "
        "STANDARD model here.",
        "- One sample: LLM output varies between runs, so treat these figures as one observation.",
    ]
    (out / "report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return out / "report.md"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--ticker", required=True, help="US-listed common stock, e.g. NVDA")
    parser.add_argument("--date", default=None, help="analysis date YYYY-MM-DD (default: previous weekday)")
    parser.add_argument("--budget-usd", type=Decimal, default=None,
                        help="hard cap for this run in USD (default: budgets.max_ai_cost_per_run_usd)")
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    parser.add_argument("--ledger", type=Path, default=DEFAULT_LEDGER,
                        help="shared usage ledger (JSON lines) that the daily budget is counted from")
    args = parser.parse_args(argv)

    overrides = {"budgets": {"max_ai_cost_per_run_usd": args.budget_usd}} if args.budget_usd else {}
    try:
        settings = load_settings(**overrides)
        configure_logging(settings.logging.level, settings.logging.format)
        keys = check_api_keys(settings)
        ticker = check_us_equity(args.ticker)
    except (ConfigError, BaselineError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    logger.info("API keys present for: %s", ", ".join(keys))
    result = run_baseline(ticker, args.date or previous_weekday(), settings=settings,
                          out_root=args.out, ledger_path=args.ledger)
    print(f"{result.status}: report at {result.out_dir / 'report.md'}")
    return 0 if result.status == "completed" else 1


if __name__ == "__main__":
    sys.exit(main())
