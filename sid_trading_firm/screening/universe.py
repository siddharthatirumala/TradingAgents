"""The investable universe: a versioned list of US-listed symbols with its provenance.

A universe file names where its list came from and as of when. A list compiled today
is not a historical index membership: screening it over past dates carries
survivorship bias, and every screening report says so.

Phase 1 scope: US-listed common stocks are the candidates; ETFs may appear for
benchmark and regime context but are never screening candidates.
"""

from __future__ import annotations

import hashlib
import json
import re
from datetime import date
from pathlib import Path
from typing import Annotated, Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

# Yahoo convention (as upstream's data layer): 1-5 letters, optional share class after a hyphen.
US_SYMBOL = re.compile(r"^[A-Z]{1,5}(-[A-Z])?$")


class UniverseMember(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    symbol: str
    asset_type: Literal["common_stock", "etf"]
    sector: str | None = None

    @field_validator("symbol")
    @classmethod
    def _us_symbol(cls, value: str) -> str:
        value = value.strip().upper()
        if not US_SYMBOL.match(value):
            raise ValueError(f"{value!r} is not a US-listed symbol (share classes are written BRK-B)")
        return value


class Universe(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    name: str
    version: str
    source: Annotated[str, Field(min_length=1)]
    as_of: date
    survivorship_note: Annotated[str, Field(min_length=1)]
    members: Annotated[list[UniverseMember], Field(min_length=1)]

    @model_validator(mode="after")
    def _unique(self) -> Universe:
        symbols = [m.symbol for m in self.members]
        duplicates = sorted({s for s in symbols if symbols.count(s) > 1})
        if duplicates:
            raise ValueError(f"duplicate symbols: {duplicates}")
        return self

    @property
    def identifier(self) -> str:
        return f"{self.name}_{self.version}"

    @property
    def candidates(self) -> list[str]:
        """Symbols eligible for screening (common stocks only)."""
        return sorted(m.symbol for m in self.members if m.asset_type == "common_stock")

    @property
    def etfs(self) -> list[str]:
        return sorted(m.symbol for m in self.members if m.asset_type == "etf")

    def fingerprint(self) -> str:
        canonical = json.dumps(self.model_dump(mode="json"), sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(canonical.encode()).hexdigest()[:16]


def load_universe(path: str | Path) -> Universe:
    return Universe.model_validate(yaml.safe_load(Path(path).read_text(encoding="utf-8")))
