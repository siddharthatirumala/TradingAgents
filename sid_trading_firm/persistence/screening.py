"""Storing screening results and their ranked candidates, keyed by run_id.

A stored candidate is a symbol selected for later research, not a trade signal.
"""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime

from sqlalchemy import select

from sid_trading_firm.persistence.db import Database
from sid_trading_firm.persistence.models import ScreeningCandidate, ScreeningResultRow


class ScreeningRepository:
    def __init__(self, db: Database) -> None:
        self.db = db

    def record(self, *, run_id: str, result: dict, data_source: str) -> uuid.UUID:
        """Store one screen and its ranked candidates.

        ``result`` holds as_of, the four fingerprints, config, funnel, selected (symbol,
        composite, ranks, raw), rejected, excluded, missing_data and cost.
        """
        with self.db.session() as s:
            row = ScreeningResultRow(
                run_id=uuid.UUID(run_id), as_of=date.fromisoformat(result["as_of"]), universe=result["universe"],
                universe_fingerprint=result["universe_fingerprint"], data_fingerprint=result["data_fingerprint"],
                config_fingerprint=result["config_fingerprint"], inputs_fingerprint=result["inputs_fingerprint"],
                data_source=data_source, config=result["config"], funnel=result["funnel"],
                rejections={"filters": result["rejected"], "scoring": result["excluded"],
                            "missing_data": result["missing_data"]},
                cost=result["cost"], created_at=datetime.now(UTC))
            s.add(row)
            s.flush()
            for rank, c in enumerate(result["selected"], start=1):
                s.add(ScreeningCandidate(screening_result_id=row.id, rank=rank, symbol=c["symbol"],
                                         composite=c["composite"], factor_ranks=c["ranks"], factor_values=c["raw"]))
            return row.id

    def results_for_run(self, run_id: str) -> list[ScreeningResultRow]:
        with self.db.session() as s:
            return list(s.scalars(select(ScreeningResultRow).where(ScreeningResultRow.run_id == uuid.UUID(run_id))))

    def candidates(self, screening_result_id: uuid.UUID) -> list[ScreeningCandidate]:
        with self.db.session() as s:
            return list(s.scalars(select(ScreeningCandidate)
                                  .where(ScreeningCandidate.screening_result_id == screening_result_id)
                                  .order_by(ScreeningCandidate.rank)))
