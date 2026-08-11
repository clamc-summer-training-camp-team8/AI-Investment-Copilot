"""SQL repository for researcher review tasks."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.domain import ReviewTaskRecord
from app.db.models.governance import ReviewTask


def _record(row: ReviewTask) -> ReviewTaskRecord:
    return ReviewTaskRecord(
        task_id=row.task_id,
        thesis_id=row.thesis_id,
        trigger=row.trigger,
        priority=row.priority,
        assignee=row.assignee,
        state=row.state,
        detail=dict(row.detail) if row.detail else None,
        resolution=row.resolution,
        created_at=row.created_at,
        resolved_at=row.resolved_at,
    )


class SqlReviewTaskRepo:
    def __init__(self, session: Session) -> None:
        self._session = session

    def add(self, record: ReviewTaskRecord) -> ReviewTaskRecord:
        row = ReviewTask(
            task_id=record.task_id,
            thesis_id=record.thesis_id,
            trigger=record.trigger,
            priority=record.priority,
            assignee=record.assignee,
            state=record.state,
            detail=record.detail,
            resolution=record.resolution,
            resolved_at=record.resolved_at,
        )
        self._session.add(row)
        self._session.flush()
        self._session.refresh(row)
        return _record(row)

    def get(self, task_id: str) -> ReviewTaskRecord | None:
        row = self._session.get(ReviewTask, task_id)
        return None if row is None else _record(row)

    def update(self, record: ReviewTaskRecord) -> None:
        row = self._session.get(ReviewTask, record.task_id)
        if row is None:
            raise LookupError(record.task_id)
        row.assignee = record.assignee
        row.state = record.state
        row.priority = record.priority
        row.detail = record.detail
        row.resolution = record.resolution
        row.resolved_at = record.resolved_at
        self._session.flush()

    def list_for_assignee(
        self, assignee: str, *, state: str | None = None, limit: int = 100
    ) -> list[ReviewTaskRecord]:
        query = select(ReviewTask).where(ReviewTask.assignee == assignee)
        if state is not None:
            query = query.where(ReviewTask.state == state)
        rows = self._session.scalars(
            query.order_by(ReviewTask.created_at.desc()).limit(limit)
        ).all()
        return [_record(row) for row in rows]
