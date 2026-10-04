"""Analyst and research-debate contracts."""

from __future__ import annotations

from datetime import date
from typing import Annotated, Literal

from pydantic import Field

from sid_trading_firm.contracts.base import (
    Claim,
    Confidence,
    Contract,
    EvidenceId,
    RunId,
    Stance,
    Symbol,
    Text,
)

ShortText = Annotated[str, Field(min_length=1, max_length=1000)]


class AnalystDecision(Contract):
    """One analyst's structured view of one instrument."""

    run_id: RunId
    agent: Annotated[str, Field(min_length=1, max_length=64)]
    instrument: Symbol
    as_of: date
    stance: Stance
    confidence: Confidence
    summary: Text
    claims: Annotated[list[Claim], Field(min_length=1)]
    risks: list[ShortText] = Field(default_factory=list)
    missing_information: list[ShortText] = Field(default_factory=list)


class Rebuttal(Contract):
    """A direct answer to a specific point of the other side."""

    responds_to: ShortText
    statement: Text
    evidence_ids: Annotated[list[EvidenceId], Field(min_length=1)]


class DebateArgument(Contract):
    """One turn of the bull/bear debate: the strongest evidence-based case for one side."""

    run_id: RunId
    instrument: Symbol
    side: Literal["bull", "bear"]
    round: Annotated[int, Field(ge=1)]
    thesis: Text
    claims: Annotated[list[Claim], Field(min_length=1)]
    rebuttals: list[Rebuttal] = Field(default_factory=list)
    concessions: list[ShortText] = Field(default_factory=list)


class Disagreement(Contract):
    topic: ShortText
    bull_view: Text
    bear_view: Text
    evidence_ids: list[EvidenceId] = Field(default_factory=list)


class ResearchSummary(Contract):
    """The Research Manager's account of the debate: what is agreed, disputed and unknown."""

    run_id: RunId
    instrument: Symbol
    agreement: list[Claim] = Field(default_factory=list)
    disagreement: list[Disagreement] = Field(default_factory=list)
    unresolved_uncertainty: list[ShortText] = Field(default_factory=list)
    leaning: Stance
    confidence: Confidence
    rationale: Text
