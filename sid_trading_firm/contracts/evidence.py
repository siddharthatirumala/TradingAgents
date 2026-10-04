"""Evidence: a fact the system observed or calculated, with where and when it came from."""

from __future__ import annotations

from enum import StrEnum
from typing import Annotated

from pydantic import Field, model_validator

from sid_trading_firm.contracts.base import AwareDatetime, Contract, EvidenceId, RunId, Symbol


class EvidenceKind(StrEnum):
    PRICE = "price"
    INDICATOR = "indicator"
    QUANT_METRIC = "quant_metric"       # computed by sid_trading_firm.quant
    FUNDAMENTAL = "fundamental"
    FILING = "filing"
    NEWS = "news"
    SOCIAL = "social"
    MACRO = "macro"
    PREDICTION_MARKET = "prediction_market"
    MEMORY = "memory"                   # a past case or lesson
    OTHER = "other"


class Evidence(Contract):
    """One citable fact. Agents cite it by ``evidence_id``; they never create it.

    ``observed_at`` is when the fact was true or published (the close of a bar,
    a filing date, a headline's timestamp); ``retrieved_at`` is when the system
    fetched or computed it. A fact must carry a value, a quote, or both.
    """

    evidence_id: EvidenceId
    run_id: RunId
    kind: EvidenceKind
    source: Annotated[str, Field(min_length=1, max_length=128)]
    label: Annotated[str, Field(min_length=1, max_length=256)]
    observed_at: AwareDatetime
    retrieved_at: AwareDatetime
    instrument: Symbol | None = None
    value: float | int | str | None = None
    unit: Annotated[str, Field(max_length=32)] | None = None
    quote: Annotated[str, Field(max_length=2000)] | None = None
    url: Annotated[str, Field(max_length=2048)] | None = None

    @model_validator(mode="after")
    def _substance_and_order(self) -> Evidence:
        if self.value is None and not self.quote:
            raise ValueError("evidence needs a value or a quote")
        if isinstance(self.value, float) and self.value != self.value:
            raise ValueError("evidence value cannot be NaN; record the gap as missing information")
        if self.observed_at > self.retrieved_at:
            raise ValueError("evidence cannot be observed after it was retrieved")
        return self
