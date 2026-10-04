"""Checking that contracts cite evidence that exists.

Agents cite evidence by id; only the system creates evidence. Before a contract
is accepted, every ``evidence_id`` it references (at any depth) must be in the
run's registry, and that evidence must belong to the same run.
"""

from __future__ import annotations

from collections.abc import Iterable, Iterator
from typing import Any

from pydantic import BaseModel

from sid_trading_firm.contracts.evidence import Evidence


class EvidenceError(ValueError):
    """Evidence was duplicated, or a contract cites evidence that does not exist."""


class EvidenceReferenceError(EvidenceError):
    def __init__(self, missing: set[str], foreign: set[str]) -> None:
        parts = []
        if missing:
            parts.append(f"unknown evidence ids: {sorted(missing)}")
        if foreign:
            parts.append(f"evidence from another run: {sorted(foreign)}")
        super().__init__("; ".join(parts))
        self.missing = missing
        self.foreign = foreign


def referenced_ids(obj: Any) -> set[str]:
    """Every evidence id cited anywhere inside ``obj`` (fields named evidence_id/evidence_ids)."""
    return set(_walk(obj))


def _walk(obj: Any) -> Iterator[str]:
    if isinstance(obj, BaseModel):
        for name in type(obj).model_fields:
            value = getattr(obj, name)
            if name == "evidence_ids":
                yield from value
            elif name == "evidence_id" and not isinstance(obj, Evidence):
                if value is not None:
                    yield value
            else:
                yield from _walk(value)
    elif isinstance(obj, (list, tuple, set)):
        for item in obj:
            yield from _walk(item)
    elif isinstance(obj, dict):
        for item in obj.values():
            yield from _walk(item)


class EvidenceRegistry:
    """The evidence available to one run."""

    def __init__(self, run_id: str, evidence: Iterable[Evidence] = ()) -> None:
        self.run_id = run_id
        self._items: dict[str, Evidence] = {}
        for item in evidence:
            self.add(item)

    def add(self, evidence: Evidence) -> None:
        if evidence.evidence_id in self._items:
            raise EvidenceError(f"duplicate evidence id {evidence.evidence_id}")
        self._items[evidence.evidence_id] = evidence

    def get(self, evidence_id: str) -> Evidence:
        return self._items[evidence_id]

    def __contains__(self, evidence_id: object) -> bool:
        return evidence_id in self._items

    def __len__(self) -> int:
        return len(self._items)

    def problems(self, contract: BaseModel) -> tuple[set[str], set[str]]:
        """``(missing, foreign)``: cited ids not in the registry, and ids from another run."""
        cited = referenced_ids(contract)
        missing = {i for i in cited if i not in self._items}
        foreign = {i for i in cited - missing if self._items[i].run_id != self.run_id}
        contract_run = getattr(contract, "run_id", None)
        if contract_run is not None and contract_run != self.run_id:
            foreign |= cited - missing
        return missing, foreign

    def validate(self, contract: BaseModel) -> None:
        """Raise :class:`EvidenceReferenceError` unless every citation resolves within this run."""
        missing, foreign = self.problems(contract)
        if missing or foreign:
            raise EvidenceReferenceError(missing, foreign)
