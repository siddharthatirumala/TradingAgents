"""Usage reports: what a run's model calls cost, by agent and by stage."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from decimal import Decimal

from sid_trading_firm.config.agents import display_name
from sid_trading_firm.llm.usage import LLMCallRecord

STAGES = {
    "Analysts": ("technical_analyst", "fundamentals_analyst", "news_analyst", "sentiment_analyst",
                 "macro_analyst", "market_regime_analyst"),
    "Research debate": ("bull_researcher", "bear_researcher", "research_manager", "quant_validator"),
    "Decision": ("trader", "aggressive_risk_analyst", "conservative_risk_analyst",
                 "neutral_risk_analyst", "risk_manager", "portfolio_manager", "cio"),
    "Support": ("reflector", "extractor"),
}
_STAGE_OF = {agent: stage for stage, agents in STAGES.items() for agent in agents}


def stage_of(agent: str) -> str:
    return _STAGE_OF.get(agent, "Other")


@dataclass
class Line:
    """Totals for one agent, stage or model. Tokens and cost cover calls that reported them."""

    calls: int = 0
    failures: int = 0
    no_usage: int = 0
    unpriced: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_tokens: int = 0
    cost_usd: Decimal = Decimal(0)
    latency_ms: float = 0.0
    max_latency_ms: float = 0.0
    tool_rounds: int = 0            # calls that asked for tools to be run
    structured_calls: int = 0
    fallback_calls: int = 0         # free-text calls retrying a failed structured call
    fallback_cost_usd: Decimal = Decimal(0)
    models: set[str] = field(default_factory=set)

    def add(self, r: LLMCallRecord, fallback: bool = False) -> None:
        self.calls += 1
        # A structured call answers by "calling" its schema tool; that is not a tool round.
        self.tool_rounds += r.tool_calls > 0 and r.structured_method is None
        self.structured_calls += r.structured_method is not None
        if fallback:
            self.fallback_calls += 1
            self.fallback_cost_usd += r.estimated_cost_usd or Decimal(0)
        self.failures += not r.success
        self.models.add(f"{r.provider}/{r.model}")
        self.latency_ms += r.latency_ms
        self.max_latency_ms = max(self.max_latency_ms, r.latency_ms)
        if not r.usage_available:
            self.no_usage += r.success
            return
        self.input_tokens += r.input_tokens or 0
        self.output_tokens += r.output_tokens or 0
        self.cache_read_tokens += r.cache_read_tokens or 0
        if r.estimated_cost_usd is None:
            self.unpriced += 1
        else:
            self.cost_usd += r.estimated_cost_usd


def fallback_call_ids(records: list[LLMCallRecord]) -> set[str]:
    """Calls that retried a failed structured call as plain text.

    Within a run, a call by an agent that already made a structured call, which
    is itself neither structured nor tool-using, is the free-text retry. Upstream
    agents that use structured output make exactly one structured call each, so
    any such follow-up is a fallback (one per failed structured call).
    """
    seen_structured: set[tuple[str, str]] = set()
    fallbacks = set()
    for r in sorted(records, key=lambda r: r.started_at):
        key = (r.run_id, r.agent)
        if r.structured_method is not None:
            seen_structured.add(key)
        elif key in seen_structured and r.tools_offered == 0:
            fallbacks.add(r.call_id)
    return fallbacks


@dataclass
class UsageSummary:
    records: list[LLMCallRecord]
    by_agent: dict[str, Line]
    by_stage: dict[str, Line]
    by_model: dict[str, Line]
    total: Line
    fallback_ids: set[str] = field(default_factory=set)

    @property
    def complete(self) -> bool:
        """Every successful call reported usage and was priced."""
        return self.total.no_usage == 0 and self.total.unpriced == 0


def summarize(records: list[LLMCallRecord]) -> UsageSummary:
    by_agent: dict[str, Line] = defaultdict(Line)
    by_stage: dict[str, Line] = defaultdict(Line)
    by_model: dict[str, Line] = defaultdict(Line)
    total = Line()
    fallbacks = fallback_call_ids(records)
    for r in records:
        fallback = r.call_id in fallbacks
        by_agent[r.agent].add(r, fallback)
        by_stage[stage_of(r.agent)].add(r, fallback)
        by_model[f"{r.provider}/{r.model}"].add(r, fallback)
        total.add(r, fallback)
    return UsageSummary(records, dict(by_agent), dict(by_stage), dict(by_model), total, fallbacks)


def _usd(value: Decimal) -> str:
    return f"${value:.4f}"


def capped_calls(summary: UsageSummary, output_cap: int | None) -> list[LLMCallRecord]:
    """Calls whose output reached the configured cap: their text was probably cut off."""
    if not output_cap:
        return []
    return [r for r in summary.records if r.output_tokens is not None and r.output_tokens >= output_cap]


def render_markdown(summary: UsageSummary, top: int = 5, output_cap: int | None = None) -> str:
    t = summary.total
    lines = ["| Agent | Stage | Calls | Tool rounds | Structured | Fallbacks | Input tok | Output tok | "
             "Total tok | Cost | Total latency | Slowest call |",
             "|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|"]
    order = sorted(summary.by_agent.items(), key=lambda kv: (list(STAGES).index(stage_of(kv[0]))
                                                            if stage_of(kv[0]) in STAGES else 99,
                                                            -kv[1].cost_usd))
    for agent, line in order:
        lines.append(f"| {display_name(agent)} | {stage_of(agent)} | {line.calls} | {line.tool_rounds} | "
                     f"{line.structured_calls} | {line.fallback_calls} | {line.input_tokens:,} | "
                     f"{line.output_tokens:,} | {line.input_tokens + line.output_tokens:,} | "
                     f"{_usd(line.cost_usd)} | {line.latency_ms / 1000:.1f}s | {line.max_latency_ms / 1000:.1f}s |")
    lines.append(f"| **Total run** | | **{t.calls}** | {t.tool_rounds} | {t.structured_calls} | "
                 f"**{t.fallback_calls}** | **{t.input_tokens:,}** | **{t.output_tokens:,}** | "
                 f"**{t.input_tokens + t.output_tokens:,}** | **{_usd(t.cost_usd)}** | "
                 f"{t.latency_ms / 1000:.1f}s | {t.max_latency_ms / 1000:.1f}s |")

    out = ["## Cost by agent", "", *lines, "", "## Cost by stage", "",
           "| Stage | Calls | Cost | Share |", "|---|---:|---:|---:|"]
    for stage, line in summary.by_stage.items():
        share = (line.cost_usd / t.cost_usd * 100) if t.cost_usd else Decimal(0)
        out.append(f"| {stage} | {line.calls} | {_usd(line.cost_usd)} | {share:.0f}% |")
    out += ["", "## Cost by model", "", "| Model | Calls | Input tok | Output tok | Cost |",
            "|---|---:|---:|---:|---:|"]
    for model, line in summary.by_model.items():
        out.append(f"| {model} | {line.calls} | {line.input_tokens:,} | {line.output_tokens:,} | "
                   f"{_usd(line.cost_usd)} |")

    slowest = sorted(summary.records, key=lambda r: r.latency_ms, reverse=True)[:top]
    out += ["", f"## Longest calls (top {top})", "", "| Agent | Model | Latency | Input tok | Output tok |",
            "|---|---|---:|---:|---:|"]
    out += [f"| {display_name(r.agent)} | {r.model} | {r.latency_ms / 1000:.1f}s | "
            f"{r.input_tokens if r.input_tokens is not None else 'n/a'} | "
            f"{r.output_tokens if r.output_tokens is not None else 'n/a'} |" for r in slowest]

    largest = sorted(summary.records, key=lambda r: r.input_tokens or 0, reverse=True)[:top]
    out += ["", f"## Largest prompts (top {top})", "", "| Agent | Input tok | Prompt chars | Cost |",
            "|---|---:|---:|---:|"]
    out += [f"| {display_name(r.agent)} | {r.input_tokens if r.input_tokens is not None else 'n/a'} | "
            f"{r.prompt_chars:,} | {_usd(r.estimated_cost_usd) if r.estimated_cost_usd is not None else 'n/a'} |"
            for r in largest]

    out += ["", "## Every call", "", "| # | Agent | Provider / model | Kind | Tools offered | Tool calls | "
            "Input tok | Output tok | Cost | Latency | OK |", "|---:|---|---|---|---:|---:|---:|---:|---:|---:|---|"]
    for i, r in enumerate(sorted(summary.records, key=lambda r: r.started_at), 1):
        kind = ("fallback (free text)" if r.call_id in summary.fallback_ids
                else f"structured ({r.structured_method})" if r.structured_method
                else "tool round" if r.tool_calls else "text")
        if output_cap and r.output_tokens is not None and r.output_tokens >= output_cap:
            kind += " **hit output cap**"
        out.append(f"| {i} | {display_name(r.agent)} | {r.provider}/{r.model} | {kind} | {r.tools_offered} | "
                   f"{r.tool_calls} | {r.input_tokens if r.input_tokens is not None else 'n/a'} | "
                   f"{r.output_tokens if r.output_tokens is not None else 'n/a'} | "
                   f"{_usd(r.estimated_cost_usd) if r.estimated_cost_usd is not None else 'n/a'} | "
                   f"{r.latency_ms / 1000:.1f}s | {'yes' if r.success else 'FAILED'} |")

    notes = []
    if t.failures:
        notes.append(f"{t.failures} call(s) failed; they are counted but carry no tokens.")
    if t.no_usage:
        notes.append(f"{t.no_usage} successful call(s) reported no token usage; their cost is unknown "
                     "and not included above.")
    if t.unpriced:
        notes.append(f"{t.unpriced} call(s) used a model with no price; their cost is not included above.")
    capped = capped_calls(summary, output_cap)
    if capped:
        names = ", ".join(display_name(r.agent) for r in capped)
        notes.append(f"{len(capped)} call(s) reached the {output_cap}-token output cap and were probably "
                     f"truncated: {names}.")
    if notes:
        out += ["", "## Data quality", "", *[f"- {n}" for n in notes]]
    return "\n".join(out)
