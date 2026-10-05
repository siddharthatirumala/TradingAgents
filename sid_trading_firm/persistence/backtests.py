"""Storing strategy versions and backtest results, keyed by run_id.

Strategy status changes are explicit calls, never a side effect of a backtest. Paper
states are refused here: paper trading is Phase 4 and not authorised.

Strategy parameters are stored with credentials masked (recursively, by key and by
value pattern), so a credential passed as a parameter never reaches the database; the
existing-version comparison uses the same masked form.
"""

from __future__ import annotations

import uuid
from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select

from sid_trading_firm.persistence.db import Database
from sid_trading_firm.persistence.models import (
    STRATEGY_STATUSES,
    BacktestResultRow,
    StrategyVersion,
)
from sid_trading_firm.persistence.sanitize import sanitize

UNAUTHORISED_STATUSES = frozenset({"PAPER_APPROVED", "PAPER_ACTIVE"})


class BacktestRepository:
    def __init__(self, db: Database) -> None:
        self.db = db

    def strategy_version(self, identifier: str, params: Mapping[str, Any], params_hash: str, *,
                         description: str | None = None) -> uuid.UUID:
        """The id of this exact strategy version, created as PROPOSED if new."""
        clean = sanitize(_jsonable(params))
        with self.db.session() as s:
            existing = s.scalar(select(StrategyVersion).where(StrategyVersion.identifier == identifier,
                                                              StrategyVersion.params_hash == params_hash))
            if existing is not None:
                if existing.params != clean:
                    raise ValueError(f"{identifier}: parameter hash {params_hash} already stores different params")
                return existing.id
            row = StrategyVersion(identifier=identifier, params=clean, params_hash=params_hash,
                                  status="PROPOSED", description=description, created_at=datetime.now(UTC))
            s.add(row)
            s.flush()
            return row.id

    def set_status(self, version_id: uuid.UUID, status: str) -> None:
        if status not in STRATEGY_STATUSES:
            raise ValueError(f"unknown strategy status {status!r}")
        if status in UNAUTHORISED_STATUSES:
            raise PermissionError(f"{status} needs paper trading (Phase 4), which is not authorised")
        with self.db.session() as s:
            row = s.get(StrategyVersion, version_id)
            if row is None:
                raise LookupError(f"no strategy version {version_id}")
            row.status = status

    def record(self, *, run_id: str, version_id: uuid.UUID, segment: str, report: dict, config: dict,
               data_source: str, notes: str | None = None) -> uuid.UUID:
        """Store one evaluated segment (``report`` is ``PerformanceReport.as_dict()``)."""
        with self.db.session() as s:
            row = BacktestResultRow(
                run_id=uuid.UUID(run_id), strategy_version_id=version_id, segment=segment,
                period_start=datetime.fromisoformat(report["start"]).date(),
                period_end=datetime.fromisoformat(report["end"]).date(),
                data_fingerprint=report["data_fingerprint"], data_source=data_source,
                config=_jsonable(config), metrics=report["metrics"], regimes=report.get("regimes") or None,
                notes=notes, created_at=datetime.now(UTC))
            s.add(row)
            s.flush()
            return row.id

    def results_for_run(self, run_id: str) -> list[BacktestResultRow]:
        with self.db.session() as s:
            return list(s.scalars(select(BacktestResultRow).where(BacktestResultRow.run_id == uuid.UUID(run_id))
                                  .order_by(BacktestResultRow.created_at)))

    def get_version(self, version_id: uuid.UUID) -> StrategyVersion | None:
        with self.db.session() as s:
            return s.get(StrategyVersion, version_id)


def _jsonable(value):
    if isinstance(value, Mapping):
        return {str(k): _jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(v) for v in value]
    return value
