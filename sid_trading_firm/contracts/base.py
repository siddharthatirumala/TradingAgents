"""Shared building blocks for the decision contracts."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Annotated, Literal

from pydantic import AfterValidator, BaseModel, ConfigDict, Field


class Contract(BaseModel):
    """Base for every contract: unknown fields are errors, and a filed contract cannot change."""

    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)


def _uuid(value: str) -> str:
    uuid.UUID(value)
    return value


def _aware(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("timestamps must be timezone-aware")
    return value


RunId = Annotated[str, AfterValidator(_uuid)]
EvidenceId = Annotated[str, Field(pattern=r"^ev_[A-Za-z0-9_\-]{4,64}$")]
Symbol = Annotated[str, Field(pattern=r"^[A-Z0-9][A-Z0-9.\-=^]{0,15}$")]
AwareDatetime = Annotated[datetime, AfterValidator(_aware)]
Confidence = Annotated[float, Field(ge=0.0, le=1.0)]
Text = Annotated[str, Field(min_length=1, max_length=4000)]
Stance = Literal["bullish", "neutral", "bearish"]


def new_evidence_id() -> str:
    return f"ev_{uuid.uuid4().hex[:16]}"


class Claim(Contract):
    """A statement and the evidence it rests on. A claim with no evidence is not accepted."""

    statement: Text
    evidence_ids: Annotated[list[EvidenceId], Field(min_length=1)]
