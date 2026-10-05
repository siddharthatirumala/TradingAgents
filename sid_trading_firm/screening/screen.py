"""The screening funnel: universe -> data -> filters -> factor scores -> bounded candidates.

No AI model is called here. The output is a short, explainable candidate list whose
size is capped by configuration and by the AI budget: the estimated research cost of
the candidates (per-candidate estimate x count) must fit the daily AI budget, and a
per-candidate estimate above the per-run budget refuses the screen (fail closed).
The research-cost estimate is an input taken from measurement, not a computed price.
"""

from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass, field
from decimal import Decimal

from sid_trading_firm.backtest.data import PricePanel
from sid_trading_firm.config.settings import BudgetSettings
from sid_trading_firm.screening.filters import (
    FilterConfig,
    FilterOutcome,
    evaluate_filters,
    screen_date_is_valid,
)
from sid_trading_firm.screening.scoring import ScoredSymbol, ScoringConfig, ScoringResult, score
from sid_trading_firm.screening.universe import Universe


class ScreenRefused(ValueError):
    """The screen cannot produce a candidate list within the configured limits."""


@dataclass
class ScreenResult:
    as_of: str
    universe: str
    universe_fingerprint: str
    data_fingerprint: str
    config_fingerprint: str
    inputs_fingerprint: str
    funnel: dict[str, int]
    outcomes: list[FilterOutcome]
    scoring: ScoringResult
    selected: list[ScoredSymbol]
    cost: dict[str, str | int | None]
    disabled_filters: list[str] = field(default_factory=list)
    missing_data: list[str] = field(default_factory=list)
    survivorship_note: str = ""


def _fingerprint(obj) -> str:
    return hashlib.sha256(json.dumps(obj, sort_keys=True, default=str).encode()).hexdigest()[:16]


def run_screen(universe: Universe, panel: PricePanel, as_of, filters: FilterConfig, scoring: ScoringConfig, *,
               max_candidates: int, research_cost_per_candidate_usd: Decimal, budgets: BudgetSettings) -> ScreenResult:
    as_of_ts = screen_date_is_valid(as_of)
    if max_candidates < 1:
        raise ScreenRefused("max_candidates must be at least 1")
    cost_each = Decimal(str(research_cost_per_candidate_usd))
    if cost_each <= 0:
        raise ScreenRefused("research_cost_per_candidate_usd must be positive")
    if cost_each > budgets.max_ai_cost_per_run_usd:
        raise ScreenRefused(f"estimated research cost per candidate ${cost_each} exceeds max_ai_cost_per_run_usd "
                            f"${budgets.max_ai_cost_per_run_usd}: every analysis would be stopped")

    view = panel.view(as_of_ts)
    eligible = universe.candidates
    with_data = [s for s in eligible if s in panel.frames]
    missing = sorted(set(eligible) - set(with_data))
    outcomes = [evaluate_filters(view, s, filters) for s in with_data]
    passed = [o.symbol for o in outcomes if o.passed]
    scoring_result = score(view, passed, scoring)

    by_budget = math.floor(budgets.max_ai_cost_per_day_usd / cost_each)
    limit = min(max_candidates, budgets.max_ai_candidates_per_run, by_budget)
    binding = [name for name, value in (("max_candidates", max_candidates),
                                        ("budgets.max_ai_candidates_per_run", budgets.max_ai_candidates_per_run),
                                        ("daily AI budget / cost per candidate", by_budget)) if value == limit]
    if limit < 1:
        raise ScreenRefused("the daily AI budget cannot cover a single candidate's estimated research cost")
    selected = scoring_result.scored[:limit]

    config = {"filters": filters.model_dump(), "scoring": scoring.model_dump(), "max_candidates": max_candidates,
              "research_cost_per_candidate_usd": str(cost_each),
              "budgets": {"max_ai_candidates_per_run": budgets.max_ai_candidates_per_run,
                          "max_ai_cost_per_run_usd": str(budgets.max_ai_cost_per_run_usd),
                          "max_ai_cost_per_day_usd": str(budgets.max_ai_cost_per_day_usd)}}
    config_fp = _fingerprint(config)
    data_fp = panel.fingerprint()
    return ScreenResult(
        as_of=str(as_of_ts.date()), universe=universe.identifier, universe_fingerprint=universe.fingerprint(),
        data_fingerprint=data_fp, config_fingerprint=config_fp,
        inputs_fingerprint=_fingerprint([universe.fingerprint(), data_fp, config_fp, str(as_of_ts.date())]),
        funnel={"universe": len(universe.members), "eligible_common_stocks": len(eligible),
                "with_data": len(with_data), "passed_filters": len(passed),
                "scored": len(scoring_result.scored), "selected": len(selected)},
        outcomes=outcomes, scoring=scoring_result, selected=selected,
        cost={"per_candidate_usd": str(cost_each), "selected": len(selected),
              "estimated_total_usd": str(cost_each * len(selected)), "limit": limit,
              "limited_by": ", ".join(binding)},
        disabled_filters=filters.disabled(), missing_data=missing, survivorship_note=universe.survivorship_note,
    )
