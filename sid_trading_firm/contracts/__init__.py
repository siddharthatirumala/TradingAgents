"""Typed contracts between agents and stages, and evidence validation.

Agents exchange these instead of free-form text: every important claim cites
evidence by id, and validators enforce the pipeline's safety rules. Defined now
so later phases build on stable shapes; upstream agents are not rewired yet.
"""

from sid_trading_firm.contracts.base import Claim, Contract, new_evidence_id
from sid_trading_firm.contracts.decisions import (
    CIOAction,
    CIODecision,
    PortfolioFit,
    QuantCheck,
    QuantMetric,
    QuantValidation,
    RiskCategory,
    RiskConcern,
    RiskReview,
    RiskVerdict,
    RuleCheck,
    TradeProposal,
)
from sid_trading_firm.contracts.evidence import Evidence, EvidenceKind
from sid_trading_firm.contracts.research import (
    AnalystDecision,
    DebateArgument,
    Disagreement,
    Rebuttal,
    ResearchSummary,
)
from sid_trading_firm.contracts.validation import (
    EvidenceError,
    EvidenceReferenceError,
    EvidenceRegistry,
    referenced_ids,
)

__all__ = [
    "AnalystDecision",
    "CIOAction",
    "CIODecision",
    "Claim",
    "Contract",
    "DebateArgument",
    "Disagreement",
    "Evidence",
    "EvidenceError",
    "EvidenceKind",
    "EvidenceReferenceError",
    "EvidenceRegistry",
    "PortfolioFit",
    "QuantCheck",
    "QuantMetric",
    "QuantValidation",
    "Rebuttal",
    "ResearchSummary",
    "RiskCategory",
    "RiskConcern",
    "RiskReview",
    "RiskVerdict",
    "RuleCheck",
    "TradeProposal",
    "new_evidence_id",
    "referenced_ids",
]
