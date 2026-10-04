"""LLM call records and where they are kept.

One :class:`LLMCallRecord` per model call, successful or not. Stores answer the
two questions the budget guard asks (spend for a run, spend for a UTC day) and
hand records back for reporting. The PostgreSQL store lives in
``sid_trading_firm.persistence``; the ones here need no database.
"""

from __future__ import annotations

import json
import threading
import uuid
from dataclasses import asdict, dataclass, field
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Protocol

from sid_trading_firm.llm.pricing import CostStatus


@dataclass(frozen=True)
class LLMCallRecord:
    run_id: str
    agent: str
    provider: str
    model: str
    started_at: datetime
    finished_at: datetime
    latency_ms: float
    success: bool
    # Token counts are None when the provider reported no usage: unknown, not zero.
    input_tokens: int | None
    output_tokens: int | None
    cache_read_tokens: int | None
    cache_write_tokens: int | None
    usage_available: bool
    estimated_cost_usd: Decimal | None
    cost_status: CostStatus
    # What the guard assumed before the call (prompt characters -> tokens).
    estimated_input_tokens: int
    prompt_chars: int
    node: str | None = None
    error_type: str | None = None
    error_message: str | None = None
    call_id: str = field(default_factory=lambda: str(uuid.uuid4()))

    @property
    def total_tokens(self) -> int | None:
        if self.input_tokens is None or self.output_tokens is None:
            return None
        return self.input_tokens + self.output_tokens

    def to_json(self) -> str:
        data = asdict(self)
        data["started_at"] = self.started_at.isoformat()
        data["finished_at"] = self.finished_at.isoformat()
        data["estimated_cost_usd"] = str(self.estimated_cost_usd) if self.estimated_cost_usd is not None else None
        data["cost_status"] = self.cost_status.value
        return json.dumps(data)

    @classmethod
    def from_json(cls, line: str) -> LLMCallRecord:
        data = json.loads(line)
        data["started_at"] = datetime.fromisoformat(data["started_at"])
        data["finished_at"] = datetime.fromisoformat(data["finished_at"])
        cost = data["estimated_cost_usd"]
        data["estimated_cost_usd"] = Decimal(cost) if cost is not None else None
        data["cost_status"] = CostStatus(data["cost_status"])
        return cls(**data)


class UsageStore(Protocol):
    """Where call records go. A store that cannot answer must raise, not guess."""

    def add(self, record: LLMCallRecord) -> None: ...

    def spent_usd(self, *, run_id: str | None = None, day: date | None = None) -> Decimal: ...

    def records(self, run_id: str | None = None) -> list[LLMCallRecord]: ...


def _matches(record: LLMCallRecord, run_id: str | None, day: date | None) -> bool:
    if run_id is not None and record.run_id != run_id:
        return False
    return day is None or record.started_at.astimezone(UTC).date() == day


def _sum_cost(records) -> Decimal:
    return sum((r.estimated_cost_usd for r in records if r.estimated_cost_usd is not None), Decimal(0))


class InMemoryUsageStore:
    """Thread-safe in-process store, for tests and one-off scripts."""

    def __init__(self, records: list[LLMCallRecord] | None = None) -> None:
        self._lock = threading.Lock()
        self._records: list[LLMCallRecord] = list(records or [])

    def add(self, record: LLMCallRecord) -> None:
        with self._lock:
            self._records.append(record)

    def spent_usd(self, *, run_id: str | None = None, day: date | None = None) -> Decimal:
        with self._lock:
            return _sum_cost(r for r in self._records if _matches(r, run_id, day))

    def records(self, run_id: str | None = None) -> list[LLMCallRecord]:
        with self._lock:
            return [r for r in self._records if _matches(r, run_id, None)]


class JsonlUsageStore:
    """Append-only JSON-lines file: one record per line, readable without a database."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()

    def add(self, record: LLMCallRecord) -> None:
        with self._lock, self.path.open("a", encoding="utf-8") as f:
            f.write(record.to_json() + "\n")

    def _load(self) -> list[LLMCallRecord]:
        if not self.path.exists():
            return []
        with self.path.open(encoding="utf-8") as f:
            return [LLMCallRecord.from_json(line) for line in f if line.strip()]

    def spent_usd(self, *, run_id: str | None = None, day: date | None = None) -> Decimal:
        with self._lock:
            return _sum_cost(r for r in self._load() if _matches(r, run_id, day))

    def records(self, run_id: str | None = None) -> list[LLMCallRecord]:
        with self._lock:
            return [r for r in self._load() if _matches(r, run_id, None)]
