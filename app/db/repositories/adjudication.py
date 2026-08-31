"""导师裁决仓储。"""

from __future__ import annotations

from sqlalchemy.orm import Session

from app.core.domain import AdjudicationDecisionRecord
from app.db.models.governance import AdjudicationDecision


def _record(row: AdjudicationDecision) -> AdjudicationDecisionRecord:
    return AdjudicationDecisionRecord(
        event_id=row.event_id,
        hypothesis=row.hypothesis,
        direction=row.direction,
        reason=row.reason,
        decided_by=row.decided_by,
        decided_at=row.decided_at,
    )


class SqlAdjudicationDecisionRepo:
    def __init__(self, session: Session) -> None:
        self._session = session

    def get(self, event_id: str) -> AdjudicationDecisionRecord | None:
        row = self._session.get(AdjudicationDecision, event_id)
        return None if row is None else _record(row)

    def add(self, record: AdjudicationDecisionRecord) -> AdjudicationDecisionRecord:
        row = AdjudicationDecision(
            event_id=record.event_id,
            hypothesis=record.hypothesis,
            direction=record.direction,
            reason=record.reason,
            decided_by=record.decided_by,
        )
        self._session.add(row)
        self._session.flush()
        self._session.refresh(row)
        return _record(row)
