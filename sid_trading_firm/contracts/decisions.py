"""Decision-layer contracts: quant validation, risk review, portfolio fit, CIO, proposal, verdict.

The ordering they serve: research -> quant validation -> AI risk review ->
portfolio manager -> CIO -> hard risk engine -> (later) paper execution. A CIO
approval does not execute anything; only a :class:`RiskVerdict` from the
deterministic hard risk engine can clear a :class:`TradeProposal`, and a
proposal is not an order.
"""

from __future__ import annotations

import math
import uuid
from enum import StrEnum
from typing import Annotated, Literal

from pydantic import Field, model_validator

from sid_trading_firm.contracts.base import (
    AwareDatetime,
    Claim,
    Confidence,
    Contract,
    EvidenceId,
    RunId,
    Symbol,
    Text,
)
from sid_trading_firm.quant.result import Result

ShortText = Annotated[str, Field(min_length=1, max_length=1000)]
Name = Annotated[str, Field(min_length=1, max_length=64)]


# ----------------------------------------------------------- quant validation

class QuantMetric(Contract):
    """A number from ``sid_trading_firm.quant``, with its status. Never produced by an LLM."""

    name: Name
    value: float | None
    status: Literal["ok", "insufficient_data", "invalid_input", "undefined"]
    n_obs: Annotated[int, Field(ge=0)]
    unit: Annotated[str, Field(max_length=32)] | None = None
    evidence_id: EvidenceId | None = None
    reason: Annotated[str, Field(max_length=1000)] | None = None

    @model_validator(mode="after")
    def _value_matches_status(self) -> QuantMetric:
        if self.status == "ok":
            if self.value is None or not math.isfinite(self.value):
                raise ValueError(f"metric {self.name!r} is ok but has no finite value")
        elif self.value is not None:
            raise ValueError(f"metric {self.name!r} is {self.status} and must not carry a value")
        return self

    @classmethod
    def from_result(cls, name: str, result: Result, *, unit: str | None = None,
                    evidence_id: str | None = None) -> QuantMetric:
        return cls(name=name, value=result.value, status=result.status.value, n_obs=result.n_obs,
                   unit=unit, evidence_id=evidence_id, reason=result.reason)


class QuantCheck(Contract):
    name: Name
    passed: bool
    detail: ShortText


class QuantValidation(Contract):
    """Deterministic validation of an idea. ``interpretation`` is the only free text, kept apart."""

    run_id: RunId
    instrument: Symbol
    metrics: list[QuantMetric]
    checks: Annotated[list[QuantCheck], Field(min_length=1)]
    passed: bool
    interpretation: Text | None = None

    @model_validator(mode="after")
    def _consistent(self) -> QuantValidation:
        names = [m.name for m in self.metrics]
        if len(names) != len(set(names)):
            raise ValueError("metric names must be unique")
        if self.passed != all(c.passed for c in self.checks):
            raise ValueError("passed must be true exactly when every check passed")
        return self


# ---------------------------------------------------------------- risk review

class RiskCategory(StrEnum):
    LIQUIDITY = "liquidity"
    VOLATILITY = "volatility"
    CONCENTRATION = "concentration"
    CORRELATION = "correlation"
    EVENT = "event"
    DRAWDOWN = "drawdown"
    VALUATION = "valuation"
    DATA_QUALITY = "data_quality"
    REGIME = "regime"
    OTHER = "other"


class RiskConcern(Contract):
    category: RiskCategory
    severity: Literal["low", "medium", "high", "critical"]
    statement: Text
    evidence_ids: Annotated[list[EvidenceId], Field(min_length=1)]


class RiskReview(Contract):
    """The AI risk reviewer's judgement. It can veto; it cannot loosen the hard limits."""

    run_id: RunId
    instrument: Symbol
    reviewer: Name
    approve: bool
    veto: bool
    concerns: list[RiskConcern] = Field(default_factory=list)
    reasoning: Text

    @model_validator(mode="after")
    def _veto_is_rejection(self) -> RiskReview:
        if self.veto and self.approve:
            raise ValueError("a vetoed review cannot approve")
        if self.approve and any(c.severity == "critical" for c in self.concerns):
            raise ValueError("a review with a critical concern cannot approve")
        return self


# -------------------------------------------------------------- portfolio fit

class PortfolioFit(Contract):
    """The Portfolio Manager's view of whether the idea fits the book.

    ``proposed_weight`` is a proposal; deterministic sizing and the hard risk
    engine decide the actual size.
    """

    run_id: RunId
    instrument: Symbol
    fits: bool
    proposed_weight: Annotated[float, Field(ge=0.0, le=1.0)] | None = None
    sizing_method: Name | None = None
    rationale: Text
    correlation_notes: list[ShortText] = Field(default_factory=list)
    concentration_notes: list[ShortText] = Field(default_factory=list)

    @model_validator(mode="after")
    def _no_weight_without_fit(self) -> PortfolioFit:
        if not self.fits and self.proposed_weight:
            raise ValueError("an idea that does not fit the portfolio cannot propose a weight")
        return self


# ------------------------------------------------------------------------ CIO

class CIOAction(StrEnum):
    APPROVE = "APPROVE"
    REJECT = "REJECT"
    WAIT = "WAIT"
    REQUEST_MORE_RESEARCH = "REQUEST_MORE_RESEARCH"


class CIODecision(Contract):
    """The final AI judgement. APPROVE is a recommendation to the hard risk engine, not an execution."""

    run_id: RunId
    instrument: Symbol
    action: CIOAction
    thesis: Text
    supporting_evidence: list[Claim] = Field(default_factory=list)
    dissenting_evidence: list[Claim] = Field(default_factory=list)
    primary_risks: list[ShortText] = Field(default_factory=list)
    confidence: Confidence
    reasoning: Text
    proposed_action: ShortText | None = None
    requested_research: list[ShortText] = Field(default_factory=list)

    @model_validator(mode="after")
    def _action_has_its_support(self) -> CIODecision:
        if self.action is CIOAction.APPROVE:
            missing = [name for name, items in (("supporting_evidence", self.supporting_evidence),
                                                ("dissenting_evidence", self.dissenting_evidence),
                                                ("primary_risks", self.primary_risks)) if not items]
            if missing:
                raise ValueError(f"an APPROVE must state {', '.join(missing)}")
        if self.action is CIOAction.REQUEST_MORE_RESEARCH and not self.requested_research:
            raise ValueError("REQUEST_MORE_RESEARCH must say what research is needed")
        return self


# ------------------------------------------------------------ trade proposal

class TradeProposal(Contract):
    """A sized idea submitted to the hard risk engine. Not an order; nothing executes it here."""

    proposal_id: Annotated[str, Field(default_factory=lambda: str(uuid.uuid4()))]
    run_id: RunId
    instrument: Symbol
    side: Literal["buy", "sell"]
    quantity: Annotated[int, Field(gt=0)]
    order_type: Literal["market", "limit"]
    limit_price: Annotated[float, Field(gt=0)] | None = None
    reference_price: Annotated[float, Field(gt=0)]
    notional: Annotated[float, Field(gt=0)]
    sizing_method: Name
    strategy_version: Name | None = None
    created_at: AwareDatetime

    @model_validator(mode="after")
    def _consistent(self) -> TradeProposal:
        if self.order_type == "limit" and self.limit_price is None:
            raise ValueError("a limit proposal needs a limit_price")
        if self.order_type == "market" and self.limit_price is not None:
            raise ValueError("a market proposal cannot carry a limit_price")
        expected = self.quantity * self.reference_price
        if not math.isclose(self.notional, expected, rel_tol=1e-9):
            raise ValueError(f"notional {self.notional} != quantity x reference_price ({expected})")
        return self


# --------------------------------------------------------------- risk verdict

class RuleCheck(Contract):
    rule: Name
    passed: bool
    observed: float | str | None = None
    limit: float | str | None = None
    reason: ShortText


class RiskVerdict(Contract):
    """The hard risk engine's ruling on one proposal. Approved only when every rule passed."""

    proposal_id: Annotated[str, Field(min_length=1)]
    run_id: RunId
    approved: bool
    checks: Annotated[list[RuleCheck], Field(min_length=1)]
    evaluated_at: AwareDatetime
    engine_version: Name
    live_trading_enabled: Literal[False] = False

    @model_validator(mode="after")
    def _approved_only_if_all_passed(self) -> RiskVerdict:
        if self.approved != all(c.passed for c in self.checks):
            raise ValueError("approved must be true exactly when every rule check passed")
        return self

    @property
    def failed(self) -> list[RuleCheck]:
        return [c for c in self.checks if not c.passed]
