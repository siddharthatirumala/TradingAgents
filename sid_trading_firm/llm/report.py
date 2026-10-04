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
    models: set[str] = field(default_factory=set)

    def add(self, r: LLMCallRecord) -> None:
        self.calls += 1
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


@dataclass
class UsageSummary:
    records: list[LLMCallRecord]
    by_agent: dict[str, Line]
    by_stage: dict[str, Line]
    by_model: dict[str, Line]
    total: Line

    @property
    def complete(self) -> bool:
        """Every successful call reported usage and was priced."""
        return self.total.no_usage == 0 and self.total.unpriced == 0


def summarize(records: list[LLMCallRecord]) -> UsageSummary:
    by_agent: dict[str, Line] = defaultdict(Line)
    by_stage: dict[str, Line] = defaultdict(Line)
    by_model: dict[str, Line] = defaultdict(Line)
    total = Line()
    for r in records:
        by_agent[r.agent].add(r)
        by_stage[stage_of(r.agent)].add(r)
        by_model[f"{r.provider}/{r.model}"].add(r)
        total.add(r)
    return UsageSummary(records, dict(by_agent), dict(by_stage), dict(by_model), total)


def _usd(value: Decimal) -> str:
    return f"${value:.4f}"


def render_markdown(summary: UsageSummary, top: int = 5) -> str:
    t = summary.total
    lines = ["| Agent | Stage | Calls | Input tok | Output tok | Cost | Total latency | Slowest call |",
             "|---|---|---:|---:|---:|---:|---:|---:|"]
    order = sorted(summary.by_agent.items(), key=lambda kv: (list(STAGES).index(stage_of(kv[0]))
                                                            if stage_of(kv[0]) in STAGES else 99,
                                                            -kv[1].cost_usd))
    for agent, line in order:
        lines.append(f"| {display_name(agent)} | {stage_of(agent)} | {line.calls} | "
                     f"{line.input_tokens:,} | {line.output_tokens:,} | {_usd(line.cost_usd)} | "
                     f"{line.latency_ms / 1000:.1f}s | {line.max_latency_ms / 1000:.1f}s |")
    lines.append(f"| **Total run** | | **{t.calls}** | **{t.input_tokens:,}** | **{t.output_tokens:,}** | "
                 f"**{_usd(t.cost_usd)}** | {t.latency_ms / 1000:.1f}s | {t.max_latency_ms / 1000:.1f}s |")

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

    notes = []
    if t.failures:
        notes.append(f"{t.failures} call(s) failed; they are counted but carry no tokens.")
    if t.no_usage:
        notes.append(f"{t.no_usage} successful call(s) reported no token usage; their cost is unknown "
                     "and not included above.")
    if t.unpriced:
        notes.append(f"{t.unpriced} call(s) used a model with no price; their cost is not included above.")
    if notes:
        out += ["", "## Data quality", "", *[f"- {n}" for n in notes]]
    return "\n".join(out)
