"""Storing strategy versions and backtest results, keyed by run_id.

Strategy status changes are explicit calls, never a side effect of a backtest. Paper
states are refused here: paper trading is Phase 4 and not authorised.

Strategy parameters that carry a credential are refused before anything is written,
and the stored ``params_hash`` must equal the hash recomputed here from those (clean)
parameters, so neither a raw credential nor anything derived from one can become part
of a stored strategy identity. The credential-masking flush hook still covers the
column as a second line of defence.
"""

from __future__ import annotations

import math
import numbers
import uuid
from collections.abc import Mapping
from datetime import UTC, date, datetime
from typing import Any

from sqlalchemy import select

from sid_trading_firm.persistence.db import Database
from sid_trading_firm.persistence.models import (
    STRATEGY_STATUSES,
    BacktestResultRow,
    StrategyVersion,
)
from sid_trading_firm.strategies.registry import StrategySpec, reject_credentials

UNAUTHORISED_STATUSES = frozenset({"PAPER_APPROVED", "PAPER_ACTIVE"})


class BacktestRepository:
    def __init__(self, db: Database) -> None:
        self.db = db

    def strategy_version(self, identifier: str, params: Mapping[str, Any], params_hash: str, *,
                         description: str | None = None) -> uuid.UUID:
        """The id of this exact strategy version, created as PROPOSED if new.

        Refuses (before touching the database) parameters that carry a credential and a
        ``params_hash`` that is not the hash of ``identifier`` and ``params``.
        """
        reject_credentials(params, where=f"{identifier} parameters")
        expected = StrategySpec(identifier, params).params_hash
        if params_hash != expected:
            raise ValueError(f"{identifier}: params_hash does not match its parameters")
        clean = _jsonable(params)
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
               data_source: str, notes: str | None = None, equity: dict | None = None) -> uuid.UUID:
        """Store one evaluated segment (``report`` is ``PerformanceReport.as_dict()``).

        ``equity`` is the segment's equity curve as ``{"dates": [...], "values": [...]}``.
        """
        if equity is not None:
            equity = _validated_equity(equity)
        with self.db.session() as s:
            row = BacktestResultRow(
                run_id=uuid.UUID(run_id), strategy_version_id=version_id, segment=segment,
                period_start=datetime.fromisoformat(report["start"]).date(),
                period_end=datetime.fromisoformat(report["end"]).date(),
                data_fingerprint=report["data_fingerprint"], data_source=data_source,
                config=_jsonable(config), metrics=report["metrics"], regimes=report.get("regimes") or None,
                equity=equity, notes=notes, created_at=datetime.now(UTC))
            s.add(row)
            s.flush()
            return row.id

    def equity_curve(self, result_id: uuid.UUID) -> dict | None:
        """The stored equity curve of one result, values as floats (see :func:`equity_from_storage`)."""
        with self.db.session() as s:
            row = s.get(BacktestResultRow, result_id)
            if row is None:
                raise LookupError(f"no backtest result {result_id}")
            return equity_from_storage(row.equity)

    def results_for_run(self, run_id: str) -> list[BacktestResultRow]:
        with self.db.session() as s:
            return list(s.scalars(select(BacktestResultRow).where(BacktestResultRow.run_id == uuid.UUID(run_id))
                                  .order_by(BacktestResultRow.created_at)))

    def get_version(self, version_id: uuid.UUID) -> StrategyVersion | None:
        with self.db.session() as s:
            return s.get(StrategyVersion, version_id)


def _validated_equity(equity: Mapping) -> dict:
    """Equally long, non-empty lists of ISO dates and finite real values; anything else is refused."""
    dates, values = equity.get("dates"), equity.get("values")
    if not isinstance(dates, list) or not isinstance(values, list) or len(dates) != len(values) or not dates:
        raise ValueError("equity must hold equally long, non-empty 'dates' and 'values' lists")
    for d in dates:
        if not isinstance(d, str):
            raise ValueError(f"equity dates must be ISO date strings, got {d!r}")
        date.fromisoformat(d)
    for v in values:
        if isinstance(v, bool) or not isinstance(v, numbers.Real) or not math.isfinite(v):
            raise ValueError(f"equity values must be finite real numbers, got {v!r}")
    return {"dates": list(dates), "values": [float(v) for v in values]}


def equity_from_storage(equity: Mapping | None) -> dict | None:
    """A stored equity curve with every value as a float.

    PostgreSQL JSONB keeps each number's exact decimal value but renders large
    magnitudes without an exponent (1.7976931348623157e308 comes back as integer
    digits), which JSON decoding turns into ``int``. The stored decimal is the
    shortest representation of the original double, so ``float()`` restores it
    exactly; this is the only read path for equity values.
    """
    if equity is None:
        return None
    return {"dates": list(equity["dates"]), "values": [float(v) for v in equity["values"]]}


def _jsonable(value):
    if isinstance(value, Mapping):
        return {str(k): _jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(v) for v in value]
    return value
