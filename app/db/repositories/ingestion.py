"""SQL repositories for durable ingestion jobs and human review items."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.domain import DocumentProcessingJobRecord, IngestionReviewRecord
from app.db.models.governance import DocumentProcessingJob, IngestionReview


def _job(row: DocumentProcessingJob) -> DocumentProcessingJobRecord:
    return DocumentProcessingJobRecord(
        job_id=row.job_id,
        document_id=row.document_id,
        owner=row.owner,
        actor_teams=list(row.actor_teams or []),
        upload_path=row.upload_path,
        source_filename=row.source_filename,
        published_at=row.published_at,
        revision_id=row.revision_id,
        object_key=row.object_key,
        object_version_id=row.object_version_id,
        upload_content_hash=row.upload_content_hash,
        ingestion_run_id=row.ingestion_run_id,
        security_id=row.security_id,
        thesis_id=row.thesis_id,
        view=row.view,
        status=row.status,
        attempt_count=row.attempt_count,
        max_attempts=row.max_attempts,
        result=dict(row.result) if row.result else None,
        last_error=row.last_error,
        created_at=row.created_at,
        started_at=row.started_at,
        finished_at=row.finished_at,
        updated_at=row.updated_at,
    )


def _review(row: IngestionReview) -> IngestionReviewRecord:
    return IngestionReviewRecord(
        review_id=row.review_id,
        dedupe_key=row.dedupe_key,
        review_type=row.review_type,
        document_id=row.document_id,
        job_id=row.job_id,
        event_id=row.event_id,
        reason=row.reason,
        assignee=row.assignee,
        status=row.status,
        payload=dict(row.payload or {}),
        security_candidates=list(row.security_candidates or []),
        resolution=row.resolution,
        resolved_by=row.resolved_by,
        created_at=row.created_at,
        resolved_at=row.resolved_at,
    )


class SqlDocumentProcessingJobRepo:
    def __init__(self, session: Session) -> None:
        self._session = session

    def add(self, record: DocumentProcessingJobRecord) -> None:
        self._session.add(DocumentProcessingJob(**record.__dict__))
        self._session.flush()

    def get(self, job_id: str) -> DocumentProcessingJobRecord | None:
        row = self._session.get(DocumentProcessingJob, job_id)
        return None if row is None else _job(row)

    def get_by_document(self, document_id: str) -> DocumentProcessingJobRecord | None:
        row = self._session.scalar(
            select(DocumentProcessingJob)
            .where(DocumentProcessingJob.document_id == document_id)
            .order_by(DocumentProcessingJob.created_at.desc())
            .limit(1)
        )
        return None if row is None else _job(row)

    def update(self, record: DocumentProcessingJobRecord) -> None:
        row = self._session.get(DocumentProcessingJob, record.job_id)
        if row is None:
            raise LookupError(record.job_id)
        for key, value in record.__dict__.items():
            if key in {"created_at", "updated_at"}:
                continue
            setattr(row, key, value)
        self._session.flush()

    def list_for_owner(
        self, owner: str, *, status: str | None = None, limit: int = 100
    ) -> list[DocumentProcessingJobRecord]:
        query = select(DocumentProcessingJob).where(DocumentProcessingJob.owner == owner)
        if status:
            query = query.where(DocumentProcessingJob.status == status)
        rows = self._session.scalars(
            query.order_by(DocumentProcessingJob.created_at.desc()).limit(limit)
        ).all()
        return [_job(row) for row in rows]

    def list_stale(self, *, before, statuses: tuple[str, ...]) -> list[DocumentProcessingJobRecord]:
        rows = self._session.scalars(
            select(DocumentProcessingJob).where(
                DocumentProcessingJob.status.in_(statuses),
                DocumentProcessingJob.updated_at < before,
            )
        ).all()
        return [_job(row) for row in rows]


class SqlIngestionReviewRepo:
    def __init__(self, session: Session) -> None:
        self._session = session

    def add(self, record: IngestionReviewRecord) -> IngestionReviewRecord:
        row = IngestionReview(**record.__dict__)
        self._session.add(row)
        self._session.flush()
        self._session.refresh(row)
        return _review(row)

    def get(self, review_id: str) -> IngestionReviewRecord | None:
        row = self._session.get(IngestionReview, review_id)
        return None if row is None else _review(row)

    def get_by_dedupe_key(self, dedupe_key: str) -> IngestionReviewRecord | None:
        row = self._session.scalar(
            select(IngestionReview).where(IngestionReview.dedupe_key == dedupe_key)
        )
        return None if row is None else _review(row)

    def update(self, record: IngestionReviewRecord) -> None:
        row = self._session.get(IngestionReview, record.review_id)
        if row is None:
            raise LookupError(record.review_id)
        for key, value in record.__dict__.items():
            setattr(row, key, value)
        self._session.flush()

    def list_for_assignee(
        self, assignee: str, *, status: str | None = None, limit: int = 100
    ) -> list[IngestionReviewRecord]:
        query = select(IngestionReview).where(IngestionReview.assignee == assignee)
        if status:
            query = query.where(IngestionReview.status == status)
        rows = self._session.scalars(
            query.order_by(IngestionReview.created_at.desc()).limit(limit)
        ).all()
        return [_review(row) for row in rows]
