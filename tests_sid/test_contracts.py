"""Decision contracts: valid shapes, enforced safety rules, and evidence references."""

import ast
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import pytest
from pydantic import ValidationError

from sid_trading_firm import contracts
from sid_trading_firm.contracts import (
    AnalystDecision,
    CIOAction,
    CIODecision,
    Claim,
    DebateArgument,
    Disagreement,
    Evidence,
    EvidenceError,
    EvidenceKind,
    EvidenceReferenceError,
    EvidenceRegistry,
    PortfolioFit,
    QuantCheck,
    QuantMetric,
    QuantValidation,
    Rebuttal,
    ResearchSummary,
    RiskConcern,
    RiskReview,
    RiskVerdict,
    RuleCheck,
    TradeProposal,
    new_evidence_id,
    referenced_ids,
)
from sid_trading_firm.quant import realised_volatility, sharpe_ratio
from sid_trading_firm.runtime import new_run_id

pytestmark = pytest.mark.unit

RUN = new_run_id()
NOW = datetime(2026, 10, 2, 21, 0, tzinfo=UTC)


def evidence(evidence_id="ev_close_0001", run_id=RUN, **kw):
    fields = {"evidence_id": evidence_id, "run_id": run_id, "kind": EvidenceKind.PRICE, "source": "yfinance",
              "label": "NVDA close 2026-10-02", "observed_at": NOW, "retrieved_at": NOW + timedelta(hours=1),
              "instrument": "NVDA", "value": 188.4, "unit": "USD"}
    return Evidence(**(fields | kw))


def claim(*ids):
    return Claim(statement="Price is above its 200-day average.", evidence_ids=list(ids) or ["ev_close_0001"])


def cio(**kw):
    fields = {"run_id": RUN, "instrument": "NVDA", "action": CIOAction.APPROVE, "thesis": "Trend and earnings agree.",
              "supporting_evidence": [claim()], "dissenting_evidence": [claim("ev_pe_0001")],
              "primary_risks": ["Valuation"], "confidence": 0.6, "reasoning": "Bull case stronger on evidence."}
    return CIODecision(**(fields | kw))


# -------------------------------------------------------------------- evidence

def test_evidence_with_a_value_or_a_quote():
    assert evidence().value == 188.4
    news = evidence("ev_news_0001", kind=EvidenceKind.NEWS, value=None, quote="Company raises guidance.",
                    url="https://example.com/a")
    assert news.quote.startswith("Company")


@pytest.mark.parametrize("change, message", [
    ({"value": None, "quote": None}, "value or a quote"),
    ({"value": float("nan")}, "NaN"),
    ({"observed_at": NOW + timedelta(days=1)}, "observed after"),
    ({"observed_at": datetime(2026, 10, 2, 21, 0)}, "timezone-aware"),
    ({"evidence_id": "close-1"}, "pattern"),
    ({"run_id": "not-a-run"}, "UUID"),
    ({"surprise": 1}, "Extra inputs"),
])
def test_evidence_rejects_bad_facts(change, message):
    with pytest.raises(ValidationError, match=message):
        evidence(**change)


def test_contracts_are_immutable():
    with pytest.raises(ValidationError):
        evidence().value = 1.0


def test_new_evidence_ids_are_valid_and_unique():
    ids = {new_evidence_id() for _ in range(500)}
    assert len(ids) == 500
    evidence(next(iter(ids)))


# ------------------------------------------------------------------- research

def test_a_claim_without_evidence_is_rejected():
    with pytest.raises(ValidationError, match="at least 1"):
        Claim(statement="Trust me.", evidence_ids=[])


def test_analyst_decision():
    decision = AnalystDecision(run_id=RUN, agent="technical_analyst", instrument="NVDA", as_of=date(2026, 10, 2),
                               stance="bullish", confidence=0.7, summary="Uptrend intact.", claims=[claim()],
                               risks=["Extended above trend"], missing_information=["Options positioning"])
    assert decision.stance == "bullish"
    for bad in ({"confidence": 1.2}, {"stance": "very bullish"}, {"claims": []}, {"instrument": "nvda"}):
        with pytest.raises(ValidationError):
            AnalystDecision(**(decision.model_dump() | bad))


def test_debate_and_summary():
    argument = DebateArgument(run_id=RUN, instrument="NVDA", side="bear", round=1, thesis="Priced for perfection.",
                              claims=[claim("ev_pe_0001")],
                              rebuttals=[Rebuttal(responds_to="Bull: trend", statement="Trends reverse.",
                                                  evidence_ids=["ev_close_0001"])])
    assert argument.side == "bear"
    with pytest.raises(ValidationError):
        DebateArgument(**(argument.model_dump() | {"round": 0}))
    with pytest.raises(ValidationError):
        Rebuttal(responds_to="x", statement="y", evidence_ids=[])
    summary = ResearchSummary(run_id=RUN, instrument="NVDA", agreement=[claim()],
                              disagreement=[Disagreement(topic="Valuation", bull_view="Growth justifies it",
                                                         bear_view="Multiple compresses", evidence_ids=["ev_pe_0001"])],
                              unresolved_uncertainty=["Next quarter's margins"], leaning="neutral",
                              confidence=0.5, rationale="Evenly argued.")
    assert summary.unresolved_uncertainty


# ------------------------------------------------------------ quant validation

def test_quant_metrics_come_from_quant_results_with_their_status():
    ok = QuantMetric.from_result("volatility_20d", realised_volatility([0.01, -0.02, 0.015]), unit="annualised")
    undefined = QuantMetric.from_result("sharpe", sharpe_ratio([0.01] * 5))
    assert ok.status == "ok" and ok.value > 0
    assert undefined.status == "undefined" and undefined.value is None and undefined.reason


@pytest.mark.parametrize("value, status", [(None, "ok"), (float("inf"), "ok"), (1.0, "undefined")])
def test_metric_value_and_status_must_agree(value, status):
    with pytest.raises(ValidationError):
        QuantMetric(name="m", value=value, status=status, n_obs=10)


def test_quant_validation_passes_only_if_every_check_passes():
    checks = [QuantCheck(name="enough_history", passed=True, detail="252 bars"),
              QuantCheck(name="liquidity", passed=False, detail="ADV below threshold")]
    QuantValidation(run_id=RUN, instrument="NVDA", metrics=[], checks=checks, passed=False)
    with pytest.raises(ValidationError, match="every check"):
        QuantValidation(run_id=RUN, instrument="NVDA", metrics=[], checks=checks, passed=True)
    with pytest.raises(ValidationError, match="unique"):
        m = QuantMetric(name="beta", value=1.1, status="ok", n_obs=60)
        QuantValidation(run_id=RUN, instrument="NVDA", metrics=[m, m], checks=checks[:1], passed=True)


# ---------------------------------------------------------- risk and portfolio

def test_risk_review_rules():
    concern = RiskConcern(category="event", severity="critical", statement="Earnings tomorrow.",
                          evidence_ids=["ev_cal_0001"])
    RiskReview(run_id=RUN, instrument="NVDA", reviewer="risk_manager", approve=False, veto=True,
               concerns=[concern], reasoning="Binary event risk.")
    with pytest.raises(ValidationError, match="vetoed"):
        RiskReview(run_id=RUN, instrument="NVDA", reviewer="risk_manager", approve=True, veto=True,
                   reasoning="x")
    with pytest.raises(ValidationError, match="critical"):
        RiskReview(run_id=RUN, instrument="NVDA", reviewer="risk_manager", approve=True, veto=False,
                   concerns=[concern], reasoning="x")


def test_portfolio_fit_cannot_size_an_idea_that_does_not_fit():
    PortfolioFit(run_id=RUN, instrument="NVDA", fits=True, proposed_weight=0.05, rationale="Diversifies.")
    with pytest.raises(ValidationError):
        PortfolioFit(run_id=RUN, instrument="NVDA", fits=False, proposed_weight=0.05, rationale="x")
    with pytest.raises(ValidationError):
        PortfolioFit(run_id=RUN, instrument="NVDA", fits=True, proposed_weight=1.5, rationale="x")


# ------------------------------------------------------------------------ CIO

def test_cio_approve_must_show_both_sides_and_the_risks():
    assert cio().action is CIOAction.APPROVE
    for missing in ("supporting_evidence", "dissenting_evidence", "primary_risks"):
        with pytest.raises(ValidationError, match=missing):
            cio(**{missing: []})


def test_other_cio_actions():
    assert cio(action=CIOAction.REJECT, supporting_evidence=[], primary_risks=[]).action is CIOAction.REJECT
    assert cio(action=CIOAction.WAIT).action is CIOAction.WAIT
    with pytest.raises(ValidationError, match="what research"):
        cio(action=CIOAction.REQUEST_MORE_RESEARCH)
    assert cio(action=CIOAction.REQUEST_MORE_RESEARCH, requested_research=["Q3 margin guidance"])
    with pytest.raises(ValidationError):
        cio(action="EXECUTE")


# ------------------------------------------------------ proposal and verdict

def proposal(**kw):
    fields = {"run_id": RUN, "instrument": "NVDA", "side": "buy", "quantity": 100, "order_type": "market",
              "reference_price": 188.4, "notional": 18_840.0, "sizing_method": "volatility_target",
              "created_at": NOW}
    return TradeProposal(**(fields | kw))


def test_trade_proposal_is_internally_consistent():
    assert proposal().proposal_id
    assert proposal(order_type="limit", limit_price=187.0).limit_price == 187.0
    for bad, message in (({"order_type": "limit"}, "limit_price"), ({"limit_price": 187.0}, "market"),
                         ({"notional": 20_000.0}, "notional"), ({"quantity": 0}, "greater than 0"),
                         ({"side": "short"}, "Input should be")):
        with pytest.raises(ValidationError, match=message):
            proposal(**bad)


def test_risk_verdict_is_approved_only_when_every_rule_passed():
    passed = RuleCheck(rule="max_position_pct", passed=True, observed=4.0, limit=5.0, reason="within limit")
    failed = RuleCheck(rule="max_data_age_seconds", passed=False, observed=7200, limit=900, reason="stale price")
    verdict = RiskVerdict(proposal_id="p1", run_id=RUN, approved=False, checks=[passed, failed],
                          evaluated_at=NOW, engine_version="hard-risk-0")
    assert verdict.failed == [failed]
    with pytest.raises(ValidationError, match="every rule"):
        RiskVerdict(proposal_id="p1", run_id=RUN, approved=True, checks=[passed, failed], evaluated_at=NOW,
                    engine_version="hard-risk-0")
    with pytest.raises(ValidationError):
        RiskVerdict(proposal_id="p1", run_id=RUN, approved=True, checks=[], evaluated_at=NOW,
                    engine_version="hard-risk-0")


def test_a_verdict_can_never_claim_live_trading():
    with pytest.raises(ValidationError):
        RiskVerdict(proposal_id="p1", run_id=RUN, approved=True,
                    checks=[RuleCheck(rule="r", passed=True, reason="ok")], evaluated_at=NOW,
                    engine_version="hard-risk-0", live_trading_enabled=True)


def test_contracts_round_trip_through_json():
    original = cio()
    assert CIODecision.model_validate_json(original.model_dump_json()) == original


# --------------------------------------------------------- evidence references

def test_registry_finds_every_citation_at_any_depth():
    decision = cio(supporting_evidence=[claim("ev_close_0001")], dissenting_evidence=[claim("ev_pe_0001")])
    assert referenced_ids(decision) == {"ev_close_0001", "ev_pe_0001"}
    metric = QuantMetric(name="beta", value=1.2, status="ok", n_obs=60, evidence_id="ev_beta_0001")
    validation = QuantValidation(run_id=RUN, instrument="NVDA", metrics=[metric],
                                 checks=[QuantCheck(name="c", passed=True, detail="d")], passed=True)
    assert referenced_ids(validation) == {"ev_beta_0001"}


def test_registry_accepts_resolvable_citations_and_names_missing_ones():
    registry = EvidenceRegistry(RUN, [evidence("ev_close_0001"), evidence("ev_pe_0001", label="P/E", value=55.2)])
    registry.validate(cio())
    with pytest.raises(EvidenceReferenceError) as err:
        registry.validate(cio(dissenting_evidence=[claim("ev_made_up_9999")]))
    assert err.value.missing == {"ev_made_up_9999"}


def test_evidence_from_another_run_is_refused():
    other_run = new_run_id()
    registry = EvidenceRegistry(RUN, [evidence("ev_close_0001"), evidence("ev_pe_0001", run_id=other_run)])
    with pytest.raises(EvidenceReferenceError) as err:
        registry.validate(cio())
    assert err.value.foreign == {"ev_pe_0001"}
    with pytest.raises(EvidenceReferenceError):
        EvidenceRegistry(other_run, [evidence("ev_close_0001", run_id=other_run),
                                     evidence("ev_pe_0001", run_id=other_run)]).validate(cio())


def test_duplicate_evidence_ids_are_refused():
    registry = EvidenceRegistry(RUN, [evidence()])
    with pytest.raises(EvidenceError, match="duplicate"):
        registry.add(evidence())
    assert len(registry) == 1 and "ev_close_0001" in registry


# ------------------------------------------------------------------ isolation

def test_contracts_import_no_llm_code():
    forbidden = {"langchain", "langchain_core", "langgraph", "langchain_anthropic", "langchain_openai",
                 "anthropic", "openai", "tradingagents"}
    for path in Path(contracts.__file__).parent.rglob("*.py"):
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            modules = ([a.name for a in node.names] if isinstance(node, ast.Import)
                       else [node.module] if isinstance(node, ast.ImportFrom) and node.module else [])
            for module in modules:
                assert module.split(".")[0] not in forbidden, f"{path.name} imports {module}"
